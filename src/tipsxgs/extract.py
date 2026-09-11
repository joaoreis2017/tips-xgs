"""Generic, config-driven extraction helpers.

Two complementary strategies are supported, because we don't know upfront
whether a given page ships its data as embedded JSON (common in Next.js /
Nuxt SPAs, as a ``<script id="__NEXT_DATA__">`` or ``window.__NUXT__``
blob) or purely as rendered HTML:

* :func:`find_embedded_json` scans ``<script>`` tags for JSON blobs.
* :func:`extract_by_selectors` pulls text/attributes via CSS selectors.

Both feed into :func:`normalize_markets` (see ``markets.py``) via a raw
``{key: value}`` dict, so calibrating a new page is just a matter of
editing ``config.yaml`` -- no code changes.
"""

from __future__ import annotations

import json
import re
from typing import Any

import jmespath
from bs4 import BeautifulSoup

from .config import ExtractRule

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Common variable/script-id names used by SPA frameworks to embed initial
# state. Extend ``embedded_json_hints`` in config.yaml if a site uses a
# different convention.
DEFAULT_JSON_HINTS = [
    "__NEXT_DATA__",
    "__NUXT__",
    "__INITIAL_STATE__",
    "__APOLLO_STATE__",
    "window.__data",
]


def find_embedded_json(html: str, hints: list[str] | None = None) -> list[dict]:
    """Return every JSON object found embedded in ``<script>`` tags that
    matches one of the ``hints`` (variable name / script id substrings).
    """
    soup = BeautifulSoup(html, "lxml")
    hints = list(hints or []) + DEFAULT_JSON_HINTS
    found: list[dict] = []

    for script in soup.find_all("script"):
        script_id = script.get("id", "")
        text = script.string or script.text or ""
        if not text.strip():
            continue
        haystack = f"{script_id}\n{text[:200]}"
        if not any(h in haystack for h in hints):
            # Still try plain `application/json` scripts -- cheap and
            # often exactly what we want (Next.js __NEXT_DATA__ etc.)
            if script.get("type") != "application/json":
                continue
        candidate = text.strip()
        # Scripts often look like `window.__NUXT__ = {...};` -- strip the
        # assignment prefix/suffix so json.loads has a clean object/array.
        match = re.search(r"(\{.*\}|\[.*\])\s*;?\s*$", candidate, re.DOTALL)
        if match:
            candidate = match.group(1)
        try:
            found.append(json.loads(candidate))
        except (json.JSONDecodeError, ValueError):
            continue
    return found


def extract_json_path(blobs: list[dict], path: str) -> Any:
    """Evaluate a JMESPath expression against the first blob that yields a
    non-``None`` result."""
    for blob in blobs:
        try:
            value = jmespath.search(path, blob)
        except jmespath.exceptions.JMESPathError:
            continue
        if value is not None:
            return value
    return None


def _parse_number(raw: str) -> float | None:
    if raw is None:
        return None
    m = NUMBER_RE.search(raw.replace("\xa0", " "))
    if not m:
        return None
    num = m.group(0).replace(",", ".")
    try:
        value = float(num)
    except ValueError:
        return None
    # Percent-like strings ("62%") should already have been normalized by
    # the caller if a 0..1 probability is expected; we return the raw
    # number here and let normalize_probabilities() decide.
    return value


def extract_by_selectors(html: str, fields: list[ExtractRule], root_selector: str | None = None) -> dict[str, float | str]:
    """Apply each :class:`ExtractRule` against ``html`` (or, if
    ``root_selector`` is given, against every element matching it -- in
    which case a list of dicts is returned instead, one per element)."""
    soup = BeautifulSoup(html, "lxml")
    roots = soup.select(root_selector) if root_selector else [soup]

    results = []
    for root in roots:
        row: dict[str, float | str] = {}
        for rule in fields:
            if not rule.selector:
                continue
            el = root.select_one(rule.selector)
            if el is None:
                continue
            raw = el.get(rule.attr) if rule.attr else el.get_text(strip=True)
            if rule.regex and raw is not None:
                m = re.search(rule.regex, raw)
                raw = m.group(1) if m else None
            if raw is None:
                continue
            num = _parse_number(raw) if isinstance(raw, str) else raw
            row[rule.key] = num if num is not None else raw
        results.append(row)

    return results[0] if not root_selector else results


def extract_by_json_paths(blobs: list[dict], fields: list[ExtractRule]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for rule in fields:
        if not rule.json_path:
            continue
        value = extract_json_path(blobs, rule.json_path)
        if value is not None:
            row[rule.key] = value
    return row


def parse_odds(raw: dict[str, Any]) -> dict[str, float]:
    """Keep only numeric-looking values, coerced to float decimal odds.

    Unlike :func:`normalize_probabilities`, odds are never divided by 100
    -- a decimal odd of "2.50" or "2,50" means exactly that.
    """
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, str):
            num = _parse_number(v)
            if num is not None:
                out[k] = num
    return out


def normalize_probabilities(raw: dict[str, float]) -> dict[str, float]:
    """Convert percentage-looking numbers (e.g. 62 -> 0.62) to 0..1 floats.

    A value already <= 1 is assumed to be a fraction already; anything
    between 1 and 100 is assumed to be a percentage.
    """
    out: dict[str, float] = {}
    for k, v in raw.items():
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        out[k] = v / 100.0 if v > 1.0 else v
    return out
