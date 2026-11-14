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
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000):
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
