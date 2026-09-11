"""Load and validate config.yaml.

config.yaml is the single place that needs updating once you've inspected
the real pages (see scripts/inspect_site.py and docs/CALIBRATION.md) -- the
scraping code itself is generic and driven entirely by this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"


@dataclass
class ExtractRule:
    """One field to pull out of a page.

    Exactly one of ``selector`` (CSS) or ``json_path`` (JMESPath, evaluated
    against whatever embedded JSON blob the extractor found on the page --
    or, for a list page, relative to *one item* of the resolved list)
    should be set. ``attr`` optionally pulls an attribute instead of text
    when using ``selector``. ``regex`` optionally post-processes the raw
    string (first capture group) before it's parsed as a number.
    """

    key: str
    selector: str | None = None
    attr: str | None = None
    json_path: str | None = None
    regex: str | None = None


@dataclass
class PageConfig:
    """Extraction rules for one page (fixtures list, a preview page, or
    the odds listing)."""

    url: str | None = None
    list_item_selector: str | None = None  # CSS: one match per list entry
    json_list_path: str | None = None  # JMESPath: resolves to a list of items
    fields: list[ExtractRule] = field(default_factory=list)
    embedded_json_hints: list[str] = field(default_factory=list)
    market_aliases: dict[str, str] = field(default_factory=dict)
    wait_selector: str | None = None


@dataclass
class SiteSection:
    base_url: str
    request_delay_seconds: float = 1.5
    pages: dict[str, PageConfig] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def page(self, name: str) -> PageConfig:
        return self.pages.get(name, PageConfig())


@dataclass
class AppConfig:
    timezone: str
    data_dir: Path
    reports_dir: Path
    value_bet_threshold: float
    min_match_confidence: float
    max_concurrent_previews: int
    headless: bool
    user_agent: str
    xgscore: SiteSection
    betclic: SiteSection
    raw: dict[str, Any] = field(default_factory=dict)


_KNOWN_SITE_KEYS = {"base_url", "request_delay_seconds", "fixtures", "preview", "odds"}


def _page_config(raw: dict | None) -> PageConfig:
    raw = raw or {}
    return PageConfig(
        url=raw.get("url"),
        list_item_selector=raw.get("list_item_selector"),
        json_list_path=raw.get("json_list_path"),
        fields=[ExtractRule(**item) for item in (raw.get("fields") or [])],
        embedded_json_hints=raw.get("embedded_json_hints", []) or [],
        market_aliases=raw.get("market_aliases", {}) or {},
        wait_selector=raw.get("wait_selector"),
    )


def _site_section(raw: dict) -> SiteSection:
    pages = {}
    for page_name in ("fixtures", "preview", "odds"):
        if page_name in raw:
            pages[page_name] = _page_config(raw[page_name])
    return SiteSection(
        base_url=raw.get("base_url", ""),
        request_delay_seconds=float(raw.get("request_delay_seconds", 1.5)),
        pages=pages,
        extra={k: v for k, v in raw.items() if k not in _KNOWN_SITE_KEYS},
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    repo_root = cfg_path.resolve().parent

    def resolve(p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else (repo_root / pp)

    return AppConfig(
        timezone=raw.get("timezone", "Europe/Lisbon"),
        data_dir=resolve(raw.get("data_dir", "data")),
        reports_dir=resolve(raw.get("reports_dir", "data")),
        value_bet_threshold=float(raw.get("value_bet_threshold", 1.0)),
        min_match_confidence=float(raw.get("min_match_confidence", 80)),
        max_concurrent_previews=int(raw.get("max_concurrent_previews", 3)),
        headless=bool(raw.get("headless", True)),
        user_agent=raw.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        ),
        xgscore=_site_section(raw.get("xgscore", {})),
        betclic=_site_section(raw.get("betclic", {})),
        raw=raw,
    )
