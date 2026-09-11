"""Scrape today's fixtures list from xGScore.

Two extraction paths are tried, controlled by config.yaml's
``xgscore.fixtures`` section:

1. **Embedded JSON** (preferred, more stable): if ``json_list_path`` is
   set, it's a JMESPath expression evaluated against the embedded JSON
   blobs found on the fixtures page; it must resolve to a list of
   fixture objects. Each field rule's ``json_path`` is then a JMESPath
   expression evaluated *relative to one fixture item*.
2. **CSS selectors**: ``list_item_selector`` matches one element per
   fixture card/row; each field rule's ``selector``/``attr`` is
   evaluated relative to that element.

See docs/CALIBRATION.md for how to figure out which path applies and fill
in the actual selectors/paths after inspecting the live page.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

import jmespath
from dateutil import parser as dateparser

from ..browser import BrowserSession
from ..config import AppConfig, PageConfig
from ..extract import extract_by_selectors, find_embedded_json
from ..models import Fixture

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _preview_url(cfg: AppConfig, league: str, home: str, away: str) -> str:
    slug = f"{_slugify(home)}-{_slugify(away)}"
    return urljoin(cfg.xgscore.base_url, f"/{_slugify(league)}/{slug}/preview")


def _fixtures_from_json(cfg: AppConfig, page_cfg: PageConfig, blobs: list[dict]) -> list[Fixture]:
    if not page_cfg.json_list_path:
        return []
    items: list[dict] = []
    for blob in blobs:
        try:
            found = jmespath.search(page_cfg.json_list_path, blob)
        except jmespath.exceptions.JMESPathError:
            continue
        if isinstance(found, list):
            items = found
            break

    fixtures = []
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
        fx = _row_to_fixture(cfg, row)
        if fx:
            fixtures.append(fx)
    return fixtures


def _fixtures_from_css(cfg: AppConfig, page_cfg: PageConfig, html: str) -> list[Fixture]:
    if not page_cfg.list_item_selector:
        return []
    rows = extract_by_selectors(html, page_cfg.fields, root_selector=page_cfg.list_item_selector)
    fixtures = []
    for row in rows:
        fx = _row_to_fixture(cfg, row)
        if fx:
            fixtures.append(fx)
    return fixtures


def _row_to_fixture(cfg: AppConfig, row: dict) -> Fixture | None:
    home = row.get("home_team")
    away = row.get("away_team")
    league = row.get("league", "unknown")
    if not home or not away:
        return None

    preview_url = row.get("preview_url")
    if preview_url and not str(preview_url).startswith("http"):
        preview_url = urljoin(cfg.xgscore.base_url, str(preview_url))
    if not preview_url:
        preview_url = _preview_url(cfg, str(league), str(home), str(away))

    kickoff = None
    kickoff_raw = row.get("kickoff")
    if kickoff_raw:
        try:
            kickoff = dateparser.parse(str(kickoff_raw))
        except (ValueError, OverflowError):
            logger.debug("could not parse kickoff time %r", kickoff_raw)

    return Fixture(
        slug=_slugify(f"{home}-{away}"),
        league=_slugify(str(league)),
        home_team=str(home),
        away_team=str(away),
        kickoff=kickoff,
        preview_url=str(preview_url),
    )


def scrape_today_fixtures(cfg: AppConfig, session: BrowserSession | None = None) -> list[Fixture]:
    """Return every fixture listed for today on xGScore's homepage/fixtures
    page. Requires ``config.yaml``'s ``xgscore.fixtures`` section to be
    calibrated (see docs/CALIBRATION.md) -- until then this logs a clear
    warning and returns an empty list rather than crashing the pipeline.
    """
    page_cfg = cfg.xgscore.page("fixtures")
    url = page_cfg.url or cfg.xgscore.base_url
    if not url:
        raise RuntimeError("xgscore.fixtures.url (or xgscore.base_url) is not set in config.yaml")

    own_session = session is None
    if own_session:
        session = BrowserSession(headless=cfg.headless, user_agent=cfg.user_agent).__enter__()
    try:
        html, blobs_captured = session.get_html_and_captured_json(url)
        blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

        fixtures = _fixtures_from_json(cfg, page_cfg, blobs)
        if not fixtures:
            fixtures = _fixtures_from_css(cfg, page_cfg, html)

        if not fixtures:
            logger.warning(
                "No fixtures extracted from %s. config.yaml's xgscore.fixtures "
                "section likely needs calibration -- see docs/CALIBRATION.md "
                "and scripts/inspect_site.py.",
                url,
            )
        return fixtures
    finally:
        if own_session:
            session.__exit__(None, None, None)


def filter_today(fixtures: list[Fixture], today: datetime) -> list[Fixture]:
    """Keep only fixtures whose kickoff falls on ``today`` (fixtures with
    no parsed kickoff time are kept -- better a false positive shown in
    the report than a silently dropped game)."""
    out = []
    for fx in fixtures:
        if fx.kickoff is None or fx.kickoff.date() == today.date():
            out.append(fx)
    return out
