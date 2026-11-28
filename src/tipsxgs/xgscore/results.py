"""Scrape past match results from xGScore's statistics/history page
(``https://xgscore.io/xg-statistics``), used by ``calibration.py`` to
check how well the model's own probabilities (already saved per day in
``data/<day>/games.json``) held up against what actually happened.

Same two extraction paths as ``fixtures.py``, controlled by
``config.yaml``'s ``xgscore.results`` section -- CALIBRATED (2026-11-14)
against a real capture of the page: a plain JSON array of match objects
(``played``, ``datetime``, ``tournament.name``, ``teams.h/a.name``,
``fullTimeGoals.h/a``), no nested "game" wrapper this time.

CONFIRMED LIMITATION: the page's own "Week / Yesterday / Today" toggle
had no query param found to pick another date -- this can only scrape
whichever one of those three the page currently shows (or whichever
``click_selector`` below explicitly switches it to).

REAL CASE (2026-11-18/19): a results.json ended up full of games that
matched none of that day's predictions. Two independent, compounding
causes, both now fixed:
1. The page's default tab turned out NOT to be stable -- a live DOM
   dump on one visit (2026-11-20) showed "Week" already selected
   (``-selected``/``aria-pressed="true"``) with no click needed, while
   a scrape minutes later on the same URL came back with only 2-3
   games dated that exact day -- i.e. "Today". Fixed by setting
   ``click_selector: "text=Week"`` in config.yaml (verified via
   ``scripts/inspect_site.py --click "text=Week"`` to reliably return a
   full week's results regardless of whatever the page would have
   defaulted to).
2. Independently, one page load can fire more than one JSON response
   that matches the configured ``json_list_path`` (e.g. a small one and
   a much larger one), and ``_results_from_json`` used to stop at the
   first match it saw -- a capture-order race, unrelated to which tab
   is visually shown. Fixed there (unions every matching blob's items,
   deduplicated by ``id``) and in ``cli.calibrate``, which no longer
   trusts "this scrape is for day X" at all -- it groups whatever comes
   back by each result's OWN date and only saves a day's results.json
   when that exact date shows up (see its own docstring), so a
   wrong/drifted tab now just contributes nothing instead of silently
   mislabeling itself. See ``BrowserSession.get_html_and_captured_json``.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import jmespath
from dateutil import parser as dateparser

from ..browser import BrowserSession
from ..config import AppConfig, PageConfig
from ..extract import extract_by_selectors, find_embedded_json
from ..models import MatchResult

logger = logging.getLogger(__name__)

# Matches a final score given as one combined string, e.g. "2-1", "2:1",
# "2 - 1" -- used only as a fallback when the page doesn't expose the two
# goal counts as separate fields (see _row_to_result).
_SCORE_RE = re.compile(r"(\d+)\D+(\d+)")


def _results_from_json(page_cfg: PageConfig, blobs: list[dict]) -> list[MatchResult]:
    """Union the matching items from EVERY captured blob, not just the
    first one that matches.

    REAL INCIDENT (2026-11-18/19): a single page load fires more than
    one JSON response that independently matches ``json_list_path``
    (e.g. ``[?played]``) -- a small one (a handful of games) and a much
    larger one (a full week). Which one Playwright's response listener
    captures first is a race, unrelated to which tab is visually
    "selected" on the page. Stopping at the first match (the old
    behaviour) silently threw away the larger blob whenever the smaller
    one happened to arrive first, which is exactly what produced a
    results.json full of games that matched none of that day's
    predictions. Unioning everything is safe: ``cli.calibrate`` already
    sorts every result into its own day by its own ``kickoff`` date, so
    extra (even duplicate) items from another blob just add coverage.
    """
    if not page_cfg.json_list_path:
        return []
    items: list[dict] = []
    seen_ids: set = set()
    for blob in blobs:
        try:
            found = jmespath.search(page_cfg.json_list_path, blob)
        except jmespath.exceptions.JMESPathError:
            continue
        if not isinstance(found, list) or not found:
            continue
        for item in found:
            item_id = item.get("id") if isinstance(item, dict) else None
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            items.append(item)

    results = []
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
        r = _row_to_result(row)
        if r:
            results.append(r)
    return results


def _results_from_css(page_cfg: PageConfig, html: str) -> list[MatchResult]:
    if not page_cfg.list_item_selector:
        return []
    rows = extract_by_selectors(html, page_cfg.fields, root_selector=page_cfg.list_item_selector)
    results = []
    for row in rows:
        r = _row_to_result(row)
        if r:
            results.append(r)
    return results


def _row_to_result(row: dict) -> MatchResult | None:
    home = row.get("home_team")
    away = row.get("away_team")
    league = row.get("league", "unknown")
    if not home or not away:
        return None

    home_goals = row.get("score_home")
    away_goals = row.get("score_away")
    if home_goals is None or away_goals is None:
        m = _SCORE_RE.search(str(row.get("score", "")))
        if not m:
            return None
        home_goals, away_goals = m.group(1), m.group(2)
    try:
        home_goals, away_goals = int(home_goals), int(away_goals)
    except (TypeError, ValueError):
        return None

    kickoff = None
    kickoff_raw = row.get("kickoff")
    if kickoff_raw:
        try:
            kickoff = dateparser.parse(str(kickoff_raw))
        except (ValueError, OverflowError):
            logger.debug("could not parse kickoff/date %r", kickoff_raw)

    return MatchResult(
        league=str(league),
        home_team=str(home),
        away_team=str(away),
        kickoff=kickoff,
        home_goals=home_goals,
        away_goals=away_goals,
    )


def scrape_results(cfg: AppConfig, day: date, session: BrowserSession | None = None) -> list[MatchResult]:
    """Return every finished match result found on ``xgscore.results``'s
    configured page(s). Requires ``config.yaml``'s ``xgscore.results``
    section to be calibrated (see docs/CALIBRATION.md) -- until then
    this logs a clear warning and returns an empty list rather than
    crashing.

    ``day`` is NOT used to pick a date on the real page as calibrated --
    its "Week / Yesterday / Today" toggle has no query-param equivalent
    we've found, so this always returns whatever it currently shows
    (whichever tab that is, possibly several days' worth at once --
    see ``config.yaml``'s own ``click_selector`` comment). ``day`` only
    feeds a literal ``{date}`` placeholder in ``url``/``urls``
    (substituted as ``YYYY-MM-DD``), kept in case a future
    recalibration finds a real date param to target -- the currently
    calibrated ``url`` has no such placeholder, so it's a no-op today.
    Callers (``cli.calibrate``) do NOT assume the results returned are
    for any particular day -- each one's own ``kickoff`` date decides
    where it gets saved, so a caller can use this for whatever date
    range the page currently shows, not just yesterday.
    """
    page_cfg = cfg.xgscore.page("results")
    urls = list(page_cfg.urls) or ([page_cfg.url] if page_cfg.url else [])
    if not urls:
        raise RuntimeError("xgscore.results.url (or .urls) is not set in config.yaml")
    urls = [u.format(date=day.isoformat()) for u in urls]

    own_session = session is None
    if own_session:
        session = BrowserSession(headless=cfg.headless, user_agent=cfg.user_agent).__enter__()
    try:
        results: list[MatchResult] = []
        for url in urls:
            html, blobs_captured = session.get_html_and_captured_json(
                url,
                wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000,
                click_selector=page_cfg.click_selector,
                click_wait_ms=page_cfg.click_wait_ms,
            )
            blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

            page_results = _results_from_json(page_cfg, blobs)
            if not page_results:
                page_results = _results_from_css(page_cfg, html)
            dated = [r.kickoff.date() for r in page_results if r.kickoff is not None]
            date_range = f"{min(dated)}..{max(dated)}" if dated else "none dated"
            logger.info(
                "%s: %d JSON blob(s) captured, %d result(s) extracted (kickoff dates: %s)",
                url,
                len(blobs),
                len(page_results),
                date_range,
            )
            results.extend(page_results)

        if not results:
            logger.warning(
                "No results extracted for %s. config.yaml's xgscore.results "
                "section likely needs calibration -- see docs/CALIBRATION.md "
                "and scripts/inspect_site.py.",
                day.isoformat(),
            )
        return results
    finally:
        if own_session:
            session.__exit__(None, None, None)
