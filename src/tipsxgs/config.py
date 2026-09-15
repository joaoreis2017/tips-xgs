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
class ArrayMarketRule:
    """Expand one whole market array (rows of ``[label, value, ...]``,
    e.g. one row per over/under line or per handicap line) into several
    canonical ``market.outcome`` entries at once -- see
    ``markets.expand_array_market`` for the templating rules and
    ``config.yaml``'s ``xgscore.preview.array_markets`` for real examples.
    Use this instead of one ``ExtractRule`` per line when a market has an
    open-ended or large number of outcomes sharing one shape.
    """

    json_path: str
    market_template: str
    outcome_template: str


@dataclass
class SelectionMatrixRule:
    """Expand *every line* of one Betclic market's ``selectionMatrix``
    (a list of rows, each with a ``selections`` list -- see
    ``config.yaml``'s ``betclic.odds`` comments for the real shape) into
    several canonical ``market.outcome`` odds at once, instead of one
    ``ExtractRule`` per line.

    Real, confirmed case this exists for: Betclic's "Total de golos -
    acima/abaixo" (over/under total goals) market ships *several* lines
    in one ``selectionMatrix`` (0.5 and 2.5 both seen in one real
    example) -- config.yaml originally only picked out the 2.5 line with
    two hand-written ``ExtractRule``s, silently discarding every other
    line Betclic actually offers odds for.

    ``json_path`` resolves to the whole ``selectionMatrix`` (a list of
    rows). Each row's ``selections`` are matched against
    ``name_pattern`` (a regex with named groups ``direction`` and
    ``line``, e.g. ``r"^(?P<direction>Acima|Abaixo) de (?P<line>[\\d,]+)$"``
    against a selection name like ``"Acima de 2,5"``) -- ``line`` has
    any comma swapped for a dot before use. ``direction_map`` translates
    the matched ``direction`` text to a canonical outcome (e.g.
    ``{"Acima": "over", "Abaixo": "under"}``); a direction not in the
    map is skipped rather than guessed at. ``market_template`` is
    ``.format(line=...)``'d to build the canonical market key (e.g.
    ``"over_under_{line}"``).
    """

    json_path: str
    name_pattern: str
    direction_map: dict[str, str]
    market_template: str


@dataclass
class HandicapMatrixRule:
    """Expand every line of a Betclic *3-way* handicap market's
    ``selectionMatrix`` (rows of ``[home, draw, away]`` selections, e.g.
    ``"Inter (-4)"`` / ``"Empate (Inter -4)"`` / ``"Udinese (+4)"``) into
    xGScore-style Asian-handicap "coverage" odds.

    Team names are baked into each selection's own name and vary by
    match, so this only looks at the trailing ``"(<sign><N>)"`` of the
    HOME selection (each row's first entry) and the AWAY selection
    (each row's third entry) -- confirmed real ordering (Inter -
    Udinese match dump): the home team's own selection is always
    listed first in each row and the away team's always third
    (draw always second), regardless of which side that row's line
    favors -- so no team-name matching is needed at all, unlike the
    per-team goals-total markets above.

    xGScore's ``handicap_home``/``handicap_away`` markets report a
    single "team covers this Asian (half-)line" probability with no
    draw outcome -- structurally different from Betclic's *integer*-
    line 3-way market (win/draw/lose after the handicap is applied).
    A real match's own Betclic page (Inter-Udinese) plus explicit user
    confirmation ("handicap +2 na Betclic = handicap +1.5 no
    xgscore", "+3 = +2.5") pinned down the exact relationship: a
    team's Betclic integer line N maps to the Asian half-line
    ``N - 0.5`` on its "+" (underdog) side, or ``-(N + 0.5)`` on its
    "-" (favourite) side -- i.e. that selection's *win* outcome at
    integer line N covers exactly the same result as the Asian
    handicap at that shifted half-line (the draw outcome has no Asian-
    handicap equivalent and is simply not used). See
    ``betclic/odds.py::_expand_handicap_matrix_markets``.
    """

    json_path: str
    selection_pattern: str = r"\((?P<sign>[+-])(?P<line>\d+(?:\.\d+)?)\)\s*$"


@dataclass
class PageConfig:
    """Extraction rules for one page (fixtures list, a preview page, or
    the odds listing)."""

    url: str | None = None
    # Alternative to `url` for a list page that needs *several* separate
    # visits merged into one result -- e.g. one specific competition's
    # page per league, rather than one generic "all football" page whose
    # infinite-scroll coverage is unpredictable from run to run. When
    # set, every scraper that supports it visits each URL in turn (same
    # wait_ms/scroll_count/scroll_pause_ms for all of them) and merges
    # every page's rows together, same as it already merges rows found
    # within one page. Takes precedence over `url` where both are set.
    urls: list[str] = field(default_factory=list)
    list_item_selector: str | None = None  # CSS: one match per list entry
    json_list_path: str | None = None  # JMESPath: resolves to a list of items
    fields: list[ExtractRule] = field(default_factory=list)
    array_markets: list[ArrayMarketRule] = field(default_factory=list)
    selection_matrix_markets: list[SelectionMatrixRule] = field(default_factory=list)
    handicap_matrix_markets: list[HandicapMatrixRule] = field(default_factory=list)
    embedded_json_hints: list[str] = field(default_factory=list)
    market_aliases: dict[str, str] = field(default_factory=dict)
    wait_selector: str | None = None
    # Extra time (ms) to let the page's JS keep firing XHR/fetch requests
    # after the DOM is ready, before we stop capturing responses -- some
    # pages (e.g. a SPA that loads "today's fixtures" league by league)
    # need much longer than BrowserSession's 2000ms default to have
    # everything in by the time we read `captured`. None keeps that
    # default.
    wait_ms: int | None = None
    # How many times to scroll to the bottom of the page (pausing
    # scroll_pause_ms after each) before reading it -- for an
    # infinite-scroll list that only renders an initial batch of items no
    # matter how long wait_ms is. 0 (default) never scrolls.
    scroll_count: int = 0
    scroll_pause_ms: int = 800


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
    # Per-game "events by probability" table filter -- with every
    # xGScore market now extracted (over/under every line, handicaps,
    # ...), that table would otherwise be dozens of rows long. An event
    # also needs a matched Betclic odd to show here (see report.py) --
    # doesn't affect value_bets_ranked/best_value_bet (the
    # value_ratio-based ranking), only this probability-ranked view.
    report_min_probability: float = 0.5
    # The cross-game lists (explicitly requested as two separate bands
    # rather than one combined "top probability" list) -- every event
    # across every game whose displayed probability (whole percent,
    # rounded -- see valuebets._rounded_percent) falls in
    # [report_high_probability_min, 100] goes in the high-confidence
    # panel, and everything in [report_mid_probability_min,
    # report_mid_probability_max] goes in the mid-confidence one.
    # Anything below report_mid_probability_min isn't shown in either.
    # Both bounds are inclusive, matching how the user specified them
    # ("67%, inclusive" / "34% a 66%, inclusive").
    report_high_probability_min: float = 0.67
    report_mid_probability_min: float = 0.34
    report_mid_probability_max: float = 0.66
    raw: dict[str, Any] = field(default_factory=dict)


_KNOWN_SITE_KEYS = {"base_url", "request_delay_seconds", "fixtures", "preview", "odds"}


def _page_config(raw: dict | None) -> PageConfig:
    raw = raw or {}
    return PageConfig(
        url=raw.get("url"),
        urls=list(raw.get("urls") or []),
        list_item_selector=raw.get("list_item_selector"),
        json_list_path=raw.get("json_list_path"),
        fields=[ExtractRule(**item) for item in (raw.get("fields") or [])],
        array_markets=[ArrayMarketRule(**item) for item in (raw.get("array_markets") or [])],
        selection_matrix_markets=[
            SelectionMatrixRule(**item) for item in (raw.get("selection_matrix_markets") or [])
        ],
        handicap_matrix_markets=[
            HandicapMatrixRule(**item) for item in (raw.get("handicap_matrix_markets") or [])
        ],
        embedded_json_hints=raw.get("embedded_json_hints", []) or [],
        market_aliases=raw.get("market_aliases", {}) or {},
        wait_selector=raw.get("wait_selector"),
        wait_ms=raw.get("wait_ms"),
        scroll_count=int(raw.get("scroll_count", 0) or 0),
        scroll_pause_ms=int(raw.get("scroll_pause_ms", 800) or 800),
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
        report_min_probability=float(raw.get("report_min_probability", 0.5)),
        report_high_probability_min=float(raw.get("report_high_probability_min", 0.67)),
        report_mid_probability_min=float(raw.get("report_mid_probability_min", 0.34)),
        report_mid_probability_max=float(raw.get("report_mid_probability_max", 0.66)),
        raw=raw,
    )
