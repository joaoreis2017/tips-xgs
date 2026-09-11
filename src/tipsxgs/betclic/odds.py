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
from datetime import datetime, timezone
from urllib.parse import urljoin

import jmespath
from dateutil import parser as dateparser

from ..browser import BrowserSession, polite_delay
from ..config import AppConfig, PageConfig
from ..extract import extract_by_selectors, extract_json_path, find_embedded_json, parse_odds, slugify
from ..markets import normalize_markets
from ..models import OddsOffer

logger = logging.getLogger(__name__)


def _rows_from_json(page_cfg: PageConfig, blobs: list[dict]) -> list[dict]:
    if not page_cfg.json_list_path:
        return []
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
        if isinstance(found, list) and found:
            items = found
            break

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
    url = page_cfg.url or cfg.betclic.base_url
    if not url:
        raise RuntimeError("betclic.fixtures.url (or betclic.base_url) is not set in config.yaml")

    html, blobs_captured = session.get_html_and_captured_json(
        url,
        wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000,
        scroll_count=page_cfg.scroll_count,
        scroll_pause_ms=page_cfg.scroll_pause_ms,
    )
    blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

    rows = _rows_from_json(page_cfg, blobs)
    if not rows:
        rows = _rows_from_css(page_cfg, html)

    if not rows:
        logger.warning(
            "No matches extracted from %s. config.yaml's betclic.fixtures "
            "section likely needs calibration -- see docs/CALIBRATION.md "
            "and scripts/inspect_site.py.",
            url,
        )
    return rows


def _scrape_detail_markets(cfg: AppConfig, match_url: str, session: BrowserSession) -> dict[str, dict[str, float]]:
    page_cfg = cfg.betclic.page("odds")
    if not page_cfg.url and not page_cfg.fields:
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
    return normalize_markets(odds, page_cfg.market_aliases)


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


def scrape_today_odds(cfg: AppConfig, session: BrowserSession | None = None) -> list[OddsOffer]:
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
        offers = []
        for row in rows:
            parsed = _row_to_offer(cfg, row)
            if not parsed:
                continue
            offer, match_url = parsed
            if match_url:
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
