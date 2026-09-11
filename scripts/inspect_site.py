#!/usr/bin/env python3
"""Calibration helper: dump a page's rendered HTML + any embedded/XHR JSON
so you can find the real selectors / JSON paths to put in config.yaml.

This has to be run somewhere that can actually reach xgscore.io / Betclic
-- e.g. your own machine, or a GitHub Actions runner -- since this
repository's own dev sandbox may have restricted egress to those hosts.

Usage:
    python scripts/inspect_site.py https://xgscore.io/
    python scripts/inspect_site.py https://xgscore.io/bundesliga/union-berlin-schalke/preview
    python scripts/inspect_site.py <betclic football url> --json-filter api

Output (written to ./inspect_out/<slug>/):
    page.html          rendered DOM
    screenshot.png      what a browser actually shows (helps line up
                         "the number I see" with "the selector that holds
                         it" -- open both side by side)
    captured_json/*.json  every JSON XHR/fetch response seen, one file
                          each (use --json-filter to narrow these down)
    embedded_json/*.json  every JSON blob found inside <script> tags

Then: open page.html in a browser, right-click the number you want ->
Inspect, copy a CSS selector for it, and add an entry under the
appropriate config.yaml page's `fields:` list. If the data instead shows
up in one of the captured_json/*.json files, use a JMESPath expression
(https://jmespath.org) against that file's structure as the `json_path`
instead of a `selector`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tipsxgs.browser import BrowserSession  # noqa: E402
from tipsxgs.extract import find_embedded_json  # noqa: E402


def slugify(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-")[-80:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--json-filter", default=None, help="Only keep captured JSON responses whose URL contains this substring")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--show", action="store_true", help="Run with a visible browser window instead of headless")
    parser.add_argument("--out", default="inspect_out")
    args = parser.parse_args()

    out_dir = Path(args.out) / slugify(args.url)
    (out_dir / "captured_json").mkdir(parents=True, exist_ok=True)
    (out_dir / "embedded_json").mkdir(parents=True, exist_ok=True)

    headless = not args.show
    print(f"Loading {args.url} (headless={headless})...")
    with BrowserSession(headless=headless) as session:
        html, captured = session.get_html_and_captured_json(args.url, url_substring_filter=args.json_filter, wait_ms=3000)

    (out_dir / "page.html").write_text(html, encoding="utf-8")
    print(f"Saved rendered HTML -> {out_dir / 'page.html'} ({len(html)} bytes)")

    for i, blob in enumerate(captured):
        path = out_dir / "captured_json" / f"{i:02d}.json"
        path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(captured)} captured JSON XHR/fetch response(s) -> {out_dir / 'captured_json'}")

    embedded = find_embedded_json(html)
    for i, blob in enumerate(embedded):
        path = out_dir / "embedded_json" / f"{i:02d}.json"
        path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(embedded)} embedded JSON blob(s) from <script> tags -> {out_dir / 'embedded_json'}")

    if not captured and not embedded:
        print(
            "\nNo JSON found at all -- this page is likely rendered as plain HTML. "
            "Use browser dev tools on page.html (or the live site) to find CSS "
            "selectors for the numbers you need, and use the `selector`/`attr` "
            "form of a field rule in config.yaml instead of `json_path`."
        )

    print(f"\nDone. Inspect the files under {out_dir}/ to fill in config.yaml.")


if __name__ == "__main__":
    main()
