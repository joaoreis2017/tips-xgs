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
from ..markets import expand_array_market, merge_markets, normalize_markets
from ..models import Fixture, Prediction

logger = logging.getLogger(__name__)


def _unwrap_transfer_state_metadata(blobs: list[dict]) -> list[dict]:
    """xGScore's own game-preview page is an Angular (server-rendered)
    app that caches every XHR response it already made during
    server-side rendering inside one big "TransferState" object embedded
    in the page -- keyed by opaque hashes, each value shaped like
    ``{"b": <the real response body>, "h": ..., "s": 200, "u": "https://
    api.xgscore.io/forecast-odds/public?gameId=...", ...}`` -- rather
    than firing that request again once the client hydrates. Confirmed
    real (2026-09-14): a match (Como - Parma) whose own preview page
    logged "No preview data extracted" nonetheless had the *exact* real
    metadata object (r/dc/bts/tm/tl/h1/h2/..., ``metadataId`` included)
    sitting right there, just wrapped this way -- BrowserSession's
    network capture only sees a bare, already-unwrapped copy of that
    same object when the client happens to *also* re-fetch it live
    (which Angular's hydration is specifically designed to skip when it
    already has the SSR'd copy), so relying on that alone silently
    missed most matches.

    Rather than rewriting every one of config.yaml's xgscore.preview
    ``fields``/``array_markets`` json_path rules (which all assume a
    bare ``{"r": ..., "metadataId": ...}`` blob -- the shape confirmed
    when it *does* get captured as its own XHR) to also parse through
    this wrapper, this unwraps it once up front and appends every inner
    object it finds (identified by carrying a ``metadataId`` key, same
    marker the original calibration used) as an *additional* blob --
    the exact same json_path rules then match it too, whichever shape
    actually showed up for a given page.
    """
    extra = []
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for value in blob.values():
            inner = value.get("b") if isinstance(value, dict) else None
            if isinstance(inner, dict) and "metadataId" in inner:
                extra.append(inner)
    return blobs + extra


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
        blobs = _unwrap_transfer_state_metadata(blobs)

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

        # array_markets: whole-array fields (every over/under line, every
        # handicap line, ...) that expand into several canonical
        # market.outcome entries each, rather than one field per line --
        # see markets.expand_array_market() and config.yaml's
        # xgscore.preview.array_markets for the real rules.
        for rule in page_cfg.array_markets:
            rows = extract_json_path(blobs, rule.json_path)
            if not isinstance(rows, list):
                continue
            markets = merge_markets(
                markets, expand_array_market(rows, rule.market_template, rule.outcome_template)
            )

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
