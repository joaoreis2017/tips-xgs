"""Regression test for the xGScore results scraper against the real JSON
shape confirmed on xgscore.io's xg-statistics page (2026-11-14) -- see
config.yaml's xgscore.results section for where this structure came
from.

That page fires (at least) two unrelated small JSON responses before
the actual results array:
1. ``{"geo": "PT"}``
2. an empty list (a decoy, same shape as the real array -- this is why
   ``_results_from_json`` only accepts a *non-empty* json_list_path
   match, same rationale as xgscore/fixtures.py)

``json_list_path: "[?played]"`` must pick out the real results array
and drop any not-yet-played game within it (``played: false``).
"""

from datetime import datetime, timezone

from tipsxgs.config import load_config
from tipsxgs.xgscore.results import scrape_results

GEO_BLOB = {"geo": "PT"}
EMPTY_DECOY = []

# Trimmed from the real captured payload (a Nations League matchday) --
# two played games plus a synthetic not-yet-played one to prove the
# "[?played]" filter drops it.
RESULTS_BLOB = [
    {
        "id": "007c1352-f6ac-4d1d-b3fc-af3bc2b273fc",
        "slug": "andorra-gibraltar",
        "datetime": "2026-11-13T19:45:00.000Z",
        "played": True,
        "tournament": {"id": "unl", "name": "League of Nations", "slug": "nations-league"},
        "fullTimeGoals": {"h": 2, "a": 0},
        "teams": {"h": {"name": "Andorra"}, "a": {"name": "Gibraltar"}},
    },
    {
        "id": "b3a3791a-f4c9-43d3-b1bd-4646f68d0bc3",
        "slug": "moldova-kazakhstan",
        "datetime": "2026-11-13T17:00:00.000Z",
        "played": True,
        "tournament": {"id": "unl", "name": "League of Nations", "slug": "nations-league"},
        "fullTimeGoals": {"h": 2, "a": 1},
        "teams": {"h": {"name": "Moldova"}, "a": {"name": "Kazakhstan"}},
    },
    {
        "id": "not-played-yet",
        "slug": "future-game",
        "datetime": "2026-11-15T19:45:00.000Z",
        "played": False,
        "tournament": {"id": "unl", "name": "League of Nations", "slug": "nations-league"},
        "fullTimeGoals": {"h": 0, "a": 0},
        "teams": {"h": {"name": "TeamA"}, "a": {"name": "TeamB"}},
    },
]


class FakeSession:
    def get_html_and_captured_json(
        self, url, url_substring_filter=None, wait_ms=2000, click_selector=None, click_wait_ms=1500
    ):
        return "<html></html>", [GEO_BLOB, EMPTY_DECOY, RESULTS_BLOB]


def test_scrape_results_against_real_xgscore_json_shape():
    cfg = load_config()  # repo-root config.yaml, calibrated for xgscore.results
    results = scrape_results(cfg, day=datetime(2026, 11, 13).date(), session=FakeSession())

    assert len(results) == 2  # the not-yet-played game is dropped
    by_pair = {(r.home_team, r.away_team): r for r in results}

    andorra = by_pair[("Andorra", "Gibraltar")]
    assert andorra.league == "League of Nations"
    assert andorra.home_goals == 2
    assert andorra.away_goals == 0
    assert andorra.kickoff == datetime(2026, 11, 13, 19, 45, tzinfo=timezone.utc)

    moldova = by_pair[("Moldova", "Kazakhstan")]
    assert moldova.home_goals == 2
    assert moldova.away_goals == 1

    assert ("TeamA", "TeamB") not in by_pair


SMALL_DECOY_BLOB = [
    {
        "id": "small-blob-game",
        "slug": "corinthians-botafogo",
        "datetime": "2026-11-19T00:30:00.000Z",
        "played": True,
        "tournament": {"id": "brasileirao", "name": "Brasileirão", "slug": "brasileirao"},
        "fullTimeGoals": {"h": 1, "a": 1},
        "teams": {"h": {"name": "Corinthians"}, "a": {"name": "Botafogo"}},
    },
]


class TwoBlobsSession:
    """Simulates the real 2026-11-18/19 incident: a single page load
    fires more than one JSON response that independently matches
    json_list_path -- here a small, unrelated one captured first, and
    the actual (larger) results blob captured second."""

    def get_html_and_captured_json(
        self, url, url_substring_filter=None, wait_ms=2000, click_selector=None, click_wait_ms=1500
    ):
        return "<html></html>", [GEO_BLOB, EMPTY_DECOY, SMALL_DECOY_BLOB, RESULTS_BLOB]


def test_scrape_results_unions_every_blob_that_matches_json_list_path():
    cfg = load_config()
    results = scrape_results(cfg, day=datetime(2026, 11, 13).date(), session=TwoBlobsSession())

    by_pair = {(r.home_team, r.away_team): r for r in results}
    # The small, earlier-captured blob's game must NOT shadow the
    # larger blob's games -- both must be present.
    assert ("Corinthians", "Botafogo") in by_pair
    assert ("Andorra", "Gibraltar") in by_pair
    assert ("Moldova", "Kazakhstan") in by_pair
    assert ("TeamA", "TeamB") not in by_pair  # still dropped: not played yet


def test_scrape_results_deduplicates_the_same_item_seen_in_two_matching_blobs():
    cfg = load_config()
    # The same results array captured twice (e.g. two tabs that happen
    # to overlap) must not produce duplicate MatchResults.
    class DuplicateBlobsSession:
        def get_html_and_captured_json(
            self, url, url_substring_filter=None, wait_ms=2000, click_selector=None, click_wait_ms=1500
        ):
            return "<html></html>", [RESULTS_BLOB, RESULTS_BLOB]

    results = scrape_results(cfg, day=datetime(2026, 11, 13).date(), session=DuplicateBlobsSession())
    assert len(results) == 2  # not 4


class SpySession:
    """Records what it was called with instead of returning real data --
    used to confirm scrape_results forwards click_selector/click_wait_ms
    through to the browser session (see browser.py's own docstring for
    the real case this exists for: xgscore.results' "Yesterday" tab
    default silently changing to "Today")."""

    def __init__(self):
        self.calls = []

    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, click_selector=None, click_wait_ms=1500):
        self.calls.append(dict(click_selector=click_selector, click_wait_ms=click_wait_ms))
        return "<html></html>", [GEO_BLOB, EMPTY_DECOY, RESULTS_BLOB]


def test_scrape_results_forwards_click_selector_to_the_browser_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # A minimal config.yaml, calibrated just enough for this page, with
    # click_selector set -- confirms the value actually reaches the
    # browser session call, not just that config.py can parse it.
    (tmp_path / "config.yaml").write_text(
        "xgscore:\n"
        "  results:\n"
        "    url: 'https://xgscore.io/xg-statistics'\n"
        "    json_list_path: '[?played]'\n"
        "    click_selector: 'button.yesterday'\n"
        "    click_wait_ms: 2500\n"
        "    fields: []\n"
        "betclic: {}\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "config.yaml")
    spy = SpySession()
    scrape_results(cfg, day=datetime(2026, 11, 13).date(), session=spy)

    assert spy.calls == [dict(click_selector="button.yesterday", click_wait_ms=2500)]
