"""Scrape one game's preview page on xGScore for market probabilities.

e.g. https://xgscore.io/bundesliga/union-berlin-schalke/preview

Like fixtures.py, this supports both an embedded-JSON strategy and a
CSS-selector strategy, controlled by ``config.yaml``'s ``xgscore.preview``
section. Every extracted raw ``{key: value}`` pair is normalized to a 0..1
probability and mapped to a canonical ``market.outcome`` via
``xgscore.preview.market_aliases`` -- see markets.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..browser import BrowserSession
from ..config import AppConfig
from ..extract import (
    extract_by_selectors,
    extract_json_path,
    find_embedded_json,
    normalize_probabilities,
)
from ..markets import normalize_markets
from ..models import Fixture, Prediction

logger = logging.getLogger(__name__)


def scrape_preview(cfg: AppConfig, fixture: Fixture, session: BrowserSession | None = None) -> Prediction:
    """Fetch and parse ``fixture.preview_url`` into a :class:`Prediction`.

    Returns a ``Prediction`` with empty ``markets`` (rather than raising)
    when nothing could be extracted, so one bad page doesn't abort the
    whole daily run -- check the logs / ``extra_stats['_raw']`` for
    debugging, and see docs/CALIBRATION.md.
    """
    page_cfg = cfg.xgscore.page("preview")

    own_session = session is None
    if own_session:
        session = BrowserSession(headless=cfg.headless, user_agent=cfg.user_agent).__enter__()
    try:
        html, blobs_captured = session.get_html_and_captured_json(
            fixture.preview_url, wait_ms=page_cfg.wait_ms if page_cfg.wait_ms is not None else 2000
        )
        blobs = blobs_captured + find_embedded_json(html, page_cfg.embedded_json_hints)

        raw: dict = {}
        for rule in page_cfg.fields:
            if rule.json_path:
                value = extract_json_path(blobs, rule.json_path)
                if value is not None:
                    raw[rule.key] = value

        if page_cfg.list_item_selector or any(r.selector for r in page_cfg.fields):
            css_fields = [r for r in page_cfg.fields if r.selector]
            css_raw = extract_by_selectors(html, css_fields)
            raw.update({k: v for k, v in css_raw.items() if k not in raw})

        if not raw:
            logger.warning(
                "No preview data extracted from %s. config.yaml's "
                "xgscore.preview section likely needs calibration -- see "
                "docs/CALIBRATION.md and scripts/inspect_site.py.",
                fixture.preview_url,
            )

        probabilities = normalize_probabilities(
            {k: v for k, v in raw.items() if isinstance(v, (int, float))}
        )
        markets = normalize_markets(probabilities, page_cfg.market_aliases)

        extra_stats = {k: v for k, v in raw.items() if k not in probabilities}

        return Prediction(
            fixture_id=fixture.id,
            markets=markets,
            extra_stats=extra_stats,
            scraped_at=datetime.now(timezone.utc),
        )
    finally:
        if own_session:
            session.__exit__(None, None, None)


def scrape_previews(
    cfg: AppConfig, fixtures: list[Fixture], session: BrowserSession | None = None
) -> dict[str, Prediction]:
    """Scrape every fixture's preview page, reusing one browser session.

    Sequential with a polite delay between requests (see
    ``xgscore.request_delay_seconds``) -- these pages are typically few
    (one day's fixtures), so raw throughput matters less than not getting
    rate-limited/blocked.
    """
    from ..browser import polite_delay

    own_session = session is None
    if own_session:
        session = BrowserSession(headless=cfg.headless, user_agent=cfg.user_agent).__enter__()
    try:
        out = {}
        for fixture in fixtures:
            with polite_delay(cfg.xgscore.request_delay_seconds):
                try:
                    out[fixture.id] = scrape_preview(cfg, fixture, session=session)
                except Exception:  # noqa: BLE001
                    logger.exception("failed to scrape preview for %s", fixture.preview_url)
        return out
    finally:
        if own_session:
            session.__exit__(None, None, None)
