"""Scrape today's football odds from Betclic.

Mirrors xgscore/fixtures.py + xgscore/preview.py: a list page
(``betclic.fixtures``) gives us the day's matches + a link to each
match's own odds page, and a detail page (``betclic.odds``) gives us the
full set of markets for one match (1X2 alone is rarely enough to find
value bets -- BTTS, over/under lines and correct score usually live on
the match's own page).

If a list-page row already carries every market you care about (Betclic
sometimes shows 1X2 + O/U 2.5 inline), you can skip the detail-page hop
entirely by leaving ``betclic.odds.url`` unset -- ``scrape_today_odds``
will just use whatever the list page gave it.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

import jmespath
from dateutil import parser as dateparser

from ..browser import BrowserSession, polite_delay
from ..config import AppConfig, HandicapMatrixRule, PageConfig, SelectionMatrixRule
from ..extract import extract_by_selectors, extract_json_path, find_embedded_json, parse_odds, slugify
from ..markets import merge_markets, normalize_markets
from ..models import OddsOffer

logger = logging.getLogger(__name__)


def _items_from_json(page_cfg: PageConfig, blobs: list[dict], seen_match_ids: set) -> list[dict]:
    """Collect every item ``page_cfg.json_list_path`` resolves to across
    *all* of ``blobs``, deduped by ``matchId`` against ``seen_match_ids``
    (shared across calls when scraping several pages/URLs -- see
    ``_scrape_list`` -- so an overlapping match found on two different
    pages/blobs is only kept once).
    """
    if not page_cfg.json_list_path:
        return []

    # Merge items from *every* blob that matches, not just the first one
    # found -- an infinite-scroll list (see betclic.fixtures.scroll_count)
    # fires a separate XHR per page as you scroll, so each additional page
    # shows up as its own blob in `blobs`, holding a *different* slice of
    # matches rather than a bigger one. Taking only the first match here
    # silently threw away every page after the first (confirmed live:
    # scrolling changed which matches turned up, but the total count
    # stayed flat at one page's worth until this fix).
    items: list[dict] = []
    for blob in blobs:
        try:
            found = jmespath.search(page_cfg.json_list_path, blob)
        except jmespath.exceptions.JMESPathError:
            continue
        # Only accept a *non-empty* match -- see the identical guard in
        # xgscore/fixtures.py for why (a page can fire several unrelated
        # JSON responses, and json_list_path may resolve to an empty list
        # against one of those before reaching the real fixtures blob).
        if not isinstance(found, list) or not found:
            continue
        for item in found:
            match_id = item.get("matchId") if isinstance(item, dict) else None
            if match_id is not None:
                if match_id in seen_match_ids:
                    continue
                seen_match_ids.add(match_id)
            items.append(item)
    return items


def _items_to_rows(page_cfg: PageConfig, items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        row = {}
        for rule in page_cfg.fields:
            if not rule.json_path:
                continue
            try:
                value = jmespath.search(rule.json_path, item)
            except jmespath.exceptions.JMESPathError:
                value = None
            if value is not None:
                row[rule.key] = value
        rows.append(row)
    return rows


def _rows_from_css(page_cfg: PageConfig, html: str) -> list[dict]:
    if not page_cfg.list_item_selector:
        return []
    return extract_by_selectors(html, page_cfg.fields, root_selector=page_cfg.list_item_selector)


def _scrape_list(cfg: AppConfig, session: BrowserSession) -> list[dict]:
    page_cfg = cfg.betclic.page("fixtures")
    # `urls` (several competition-specific pages -- more reliable than one
    # generic "all football" page's unpredictable infinite-scroll
    # coverage) takes precedence over the single `url` fallback.
    urls = list(page_cfg.urls) or ([page_cfg.url] if page_cfg.url else [])
    if not urls and cfg.betclic.base_url:
        urls = [cfg.betclic.base_url]
    if not urls:
        raise RuntimeError("betclic.fixtures.url/urls (or betclic.base_url) is not set in config.yaml")

    seen_match_ids: set = set()
    all_items: list[dict] = []
    css_rows: list[dict] = []
    for i, url in enumerate(urls, start=1):
        # One line per competition page -- with 17+ of these visited
        # sequentially (each with its own wait_ms + polite_delay), a run
        # can easily take several minutes with *zero* log output between
        # "Scraping Betclic odds..." and the final count otherwise, which
        # looks indistinguishable from a genuine hang. This is purely
        # visibility, no behavior change.
        logger.info("Visiting Betclic competition page %d/%d: %s", i, len(urls), url)
        html, blobs_captured = session.get_html_and_captured_json(
            url,
            wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000,
            scroll_count=page_cfg.scroll_count,
            scroll_pause_ms=page_cfg.scroll_pause_ms,
        )
        blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

        items = _items_from_json(page_cfg, blobs, seen_match_ids)
        if items:
            all_items.extend(items)
        else:
            css_rows.extend(_rows_from_css(page_cfg, html))

        if len(urls) > 1:
            with polite_delay(cfg.betclic.request_delay_seconds):
                pass

    rows = _items_to_rows(page_cfg, all_items) + css_rows

    if not rows:
        logger.warning(
            "No matches extracted from %s. config.yaml's betclic.fixtures "
            "section likely needs calibration -- see docs/CALIBRATION.md "
            "and scripts/inspect_site.py.",
            urls,
        )
    return rows


def _selection_name_and_odds(selection: dict) -> tuple[str | None, float | None]:
    """One entry of a Betclic ``selectionMatrix`` row's ``selections`` --
    either the flat ``{name, odds}`` shape or the
    ``{selectionOneof: {selection: {name, odds}}}`` wrapped shape both
    seen in real data (see config.yaml's ``betclic.odds`` comments)."""
    if not isinstance(selection, dict):
        return None, None
    if "selectionOneof" in selection:
        selection = selection.get("selectionOneof", {}).get("selection", {}) or {}
    return selection.get("name"), selection.get("odds")


def _expand_selection_matrix_markets(
    blobs: list[dict], rules: list[SelectionMatrixRule]
) -> dict[str, dict[str, float]]:
    """See :class:`SelectionMatrixRule` -- expand every line of a whole
    Betclic market's ``selectionMatrix`` into canonical
    ``market.outcome`` odds, e.g. every over/under total-goals line
    Betclic offers instead of the one line an ``ExtractRule`` happened
    to be hand-written for.
    """
    out: dict[str, dict[str, float]] = {}
    for rule in rules:
        rows = extract_json_path(blobs, rule.json_path)
        if not isinstance(rows, list):
            continue
        pattern = re.compile(rule.name_pattern)
        for row in rows:
            selections = row.get("selections") if isinstance(row, dict) else None
            if not isinstance(selections, list):
                continue
            for selection in selections:
                name, odd = _selection_name_and_odds(selection)
                if not name or odd is None:
                    continue
                m = pattern.match(name)
                if not m:
                    continue
                outcome = rule.direction_map.get(m.group("direction"))
                if not outcome:
                    continue
                line = m.group("line").replace(",", ".")
                market = rule.market_template.format(line=line)
                try:
                    out.setdefault(market, {})[outcome] = float(odd)
                except (TypeError, ValueError):
                    continue
    return out


def _asian_line(sign: str, magnitude: float) -> float:
    """Convert one Betclic 3-way handicap selection's own sign+magnitude
    (e.g. ``"+", 2.0`` from ``"Udinese (+2)"``) into the equivalent
    xGScore Asian half-line -- see :class:`HandicapMatrixRule`'s
    docstring for the derivation and its real-data confirmation."""
    return magnitude - 0.5 if sign == "+" else -(magnitude + 0.5)


def _format_line(value: float) -> str:
    # Always ends in .5 by construction (see _asian_line), so plain
    # str() already gives "-2.5"/"1.5"/"0.5" etc., matching xGScore's
    # own h1/h2 array row labels (config.yaml's array_markets comment).
    return str(value)


def _expand_handicap_matrix_markets(
    blobs: list[dict], rules: list[HandicapMatrixRule]
) -> dict[str, dict[str, float]]:
    """See :class:`HandicapMatrixRule` -- expand every line of Betclic's
    3-way handicap market into ``handicap_home``/``handicap_away`` odds
    keyed by the xGScore-equivalent Asian half-line, from the home/away
    selections' own trailing ``"(<sign><N>)"`` (team names, which vary
    by match and sit *before* that suffix, are ignored entirely)."""
    out: dict[str, dict[str, float]] = {}
    for rule in rules:
        rows = extract_json_path(blobs, rule.json_path)
        if not isinstance(rows, list):
            continue
        pattern = re.compile(rule.selection_pattern)
        for row in rows:
            selections = row.get("selections") if isinstance(row, dict) else None
            if not isinstance(selections, list) or len(selections) < 3:
                continue
            # Confirmed real ordering: home selection first, draw
            # second (skipped -- no Asian-handicap equivalent), away
            # selection third.
            for market_key, selection in (("handicap_home", selections[0]), ("handicap_away", selections[2])):
                name, odd = _selection_name_and_odds(selection)
                if not name or odd is None:
                    continue
                m = pattern.search(name)
                if not m:
                    continue
                try:
                    magnitude = float(m.group("line").replace(",", "."))
                    odd_value = float(odd)
                except (TypeError, ValueError):
                    continue
                line = _asian_line(m.group("sign"), magnitude)
                out.setdefault(market_key, {})[_format_line(line)] = odd_value
    return out


def _scrape_detail_markets(cfg: AppConfig, match_url: str, session: BrowserSession) -> dict[str, dict[str, float]]:
    page_cfg = cfg.betclic.page("odds")
    if (
        not page_cfg.url
        and not page_cfg.fields
        and not page_cfg.selection_matrix_markets
        and not page_cfg.handicap_matrix_markets
    ):
        return {}

    html, blobs_captured = session.get_html_and_captured_json(
        match_url, wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000
    )
    blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

    raw: dict = {}
    for rule in page_cfg.fields:
        if rule.json_path:
            value = extract_json_path(blobs, rule.json_path)
            if value is not None:
                raw[rule.key] = value

    css_fields = [r for r in page_cfg.fields if r.selector]
    if css_fields:
        css_raw = extract_by_selectors(html, css_fields)
        raw.update({k: v for k, v in css_raw.items() if k not in raw})

    odds = parse_odds(raw)
    markets = normalize_markets(odds, page_cfg.market_aliases)

    if page_cfg.selection_matrix_markets:
        markets = merge_markets(markets, _expand_selection_matrix_markets(blobs, page_cfg.selection_matrix_markets))
    if page_cfg.handicap_matrix_markets:
        markets = merge_markets(markets, _expand_handicap_matrix_markets(blobs, page_cfg.handicap_matrix_markets))

    return markets


def _build_match_url(cfg: AppConfig, row: dict) -> str | None:
    """Build a match detail page URL from Betclic's own routing template
    (confirmed 2026-09-11 straight from the site's ``metatags`` payload:
    ``"/{sportName}-s{sportId}/{competitionName}-c{competitionId}/{matchName}-m{matchId}"``).

    Requires ``match_id`` and ``competition_id`` fields to be configured
    on ``betclic.fixtures.fields`` (see config.yaml) -- without those we
    have no way to build the URL, and this returns ``None`` so the
    pipeline just skips the detail-page hop (1X2 from the listing still
    works either way).

    NOTE: the *slug* text (competition/match name -> lowercase,
    hyphenated, accents stripped) is our best-effort reproduction of
    Betclic's own slugification -- confirmed for the URL *shape*, not
    yet verified character-for-character against a live rendered link.
    """
    match_id = row.get("match_id")
    competition_id = row.get("competition_id")
    home = row.get("home_team")
    away = row.get("away_team")
    league = row.get("league")
    if not (match_id and competition_id and home and away and league):
        return None
    sport_slug = "futebol-s1"
    competition_slug = f"{slugify(str(league))}-c{competition_id}"
    match_slug = f"{slugify(str(home))}-{slugify(str(away))}-m{match_id}"
    return f"/{sport_slug}/{competition_slug}/{match_slug}"


def _row_to_offer(cfg: AppConfig, row: dict) -> tuple[OddsOffer, str | None] | None:
    home = row.get("home_team")
    away = row.get("away_team")
    if not home or not away:
        return None

    match_url = row.get("match_url") or _build_match_url(cfg, row)
    if match_url and not str(match_url).startswith("http"):
        match_url = urljoin(cfg.betclic.base_url, str(match_url))

    kickoff = None
    kickoff_raw = row.get("kickoff")
    if kickoff_raw:
        try:
            kickoff = dateparser.parse(str(kickoff_raw))
        except (ValueError, OverflowError):
            logger.debug("could not parse kickoff time %r", kickoff_raw)

    list_page_cfg = cfg.betclic.page("fixtures")
    inline_odds = parse_odds(
        {
            k: v
            for k, v in row.items()
            if k not in ("home_team", "away_team", "kickoff", "match_url", "league", "match_id", "competition_id")
        }
    )
    inline_markets = normalize_markets(inline_odds, list_page_cfg.market_aliases)

    offer = OddsOffer(
        bookmaker="betclic",
        home_team=str(home),
        away_team=str(away),
        kickoff=kickoff,
        markets=inline_markets,
        url=str(match_url) if match_url else None,
        scraped_at=datetime.now(timezone.utc),
    )
    return offer, (str(match_url) if match_url else None)


def scrape_today_odds(
    cfg: AppConfig, session: BrowserSession | None = None, day: date | None = None
) -> list[OddsOffer]:
    """Return every football match + odds Betclic lists for today.

    Requires ``config.yaml``'s ``betclic`` section to be calibrated (see
    docs/CALIBRATION.md) -- until then this logs a clear warning and
    returns an empty list rather than crashing the pipeline.
    """
    own_session = session is None
    if own_session:
        session = BrowserSession(headless=cfg.headless, user_agent=cfg.user_agent).__enter__()
    try:
        rows = _scrape_list(cfg, session)
        parsed_rows = [p for p in (_row_to_offer(cfg, row) for row in rows) if p]

        # Each competition page lists *every* upcoming fixture for that
        # league (days or weeks out), not just today's -- confirmed live:
        # 219 matches parsed from 17 competition pages when only ~15
        # xGScore fixtures (and so at most ~15-20 relevant Betclic ones)
        # were for today. The listing itself is cheap (already fetched
        # above), but hopping to each match's own detail page for
        # BTTS/over-under is not -- so only do that for matches actually
        # kicking off today; every offer is still kept in the returned
        # list either way (a non-today one just keeps only its inline 1X2
        # odds, no BTTS/O-U) -- matching.py's own day-mismatch penalty
        # already keeps it from being wrongly paired, and the "closest
        # candidate" diagnostic logging there is more useful with the
        # full pool than without it. An offer with no parsed kickoff
        # counts as "today" rather than being skipped, same "false
        # positive over silent drop" tradeoff as xgscore.fixtures.filter_today.
        today = day or datetime.now(timezone.utc).date()

        def _is_today(offer: OddsOffer) -> bool:
            return offer.kickoff is None or offer.kickoff.date() == today

        todays_hops = sum(1 for offer, match_url in parsed_rows if match_url and _is_today(offer))
        skipped = sum(1 for offer, match_url in parsed_rows if match_url and not _is_today(offer))
        if skipped:
            logger.info(
                "Skipping the detail-page hop for %d Betclic match(es) not kicking off today (%s)",
                skipped,
                today.isoformat(),
            )

        logger.info("Betclic listing done -- hopping to each today's match's detail page for BTTS/over-under...")
        offers = []
        hop_i = 0
        for offer, match_url in parsed_rows:
            if match_url and _is_today(offer):
                hop_i += 1
                # Same visibility reasoning as the competition-page loop
                # above -- one of these per match kicking off today, each
                # with its own wait + polite_delay.
                logger.info(
                    "Fetching Betclic match odds %d/%d: %s - %s",
                    hop_i,
                    todays_hops,
                    offer.home_team,
                    offer.away_team,
                )
                with polite_delay(cfg.betclic.request_delay_seconds):
                    try:
                        detail_markets = _scrape_detail_markets(cfg, match_url, session)
                    except Exception:  # noqa: BLE001
                        logger.exception("failed to scrape betclic odds detail for %s", match_url)
                        detail_markets = {}
                for market, outcomes in detail_markets.items():
                    offer.markets.setdefault(market, {}).update(outcomes)
            offers.append(offer)
        return offers
    finally:
        if own_session:
            session.__exit__(None, None, None)
