"""Scrape past match results from xGScore's statistics/history page
(``https://xgscore.io/xg-statistics``), used by ``calibration.py`` to
check how well the model's own probabilities (already saved per day in
``data/<day>/games.json``) held up against what actually happened.

Same two extraction paths as ``fixtures.py``, controlled by
``config.yaml``'s ``xgscore.results`` section -- see
docs/CALIBRATION.md's "xgscore.results" section for how to fill it in
after inspecting the live page. Not calibrated yet as of writing (this
project's build environment has no network access to xgscore.io at
all -- see docs/CALIBRATION.md's intro).
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
    if not page_cfg.json_list_path:
        return []
    items: list[dict] = []
    for blob in blobs:
        try:
            found = jmespath.search(page_cfg.json_list_path, blob)
        except jmespath.exceptions.JMESPathError:
            continue
        if isinstance(found, list) and found:
            items = found
            break

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
    configured page(s) for ``day``. Requires ``config.yaml``'s
    ``xgscore.results`` section to be calibrated (see
    docs/CALIBRATION.md) -- until then this logs a clear warning and
    returns an empty list rather than crashing.

    ``url``/each entry of ``urls`` may contain a literal ``{date}``
    placeholder, substituted with ``day`` as ``YYYY-MM-DD`` -- handy if
    the real page takes the date as a query param/path segment.
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
                url, wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000
            )
            blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

            page_results = _results_from_json(page_cfg, blobs)
            if not page_results:
                page_results = _results_from_css(page_cfg, html)
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
