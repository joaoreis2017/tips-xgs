"""Regression test for the xGScore fixtures scraper against the real JSON
shape confirmed on xgscore.io (2026-09-11) -- see config.yaml's
xgscore.fixtures section for where this structure came from.

The homepage fires (at least) three unrelated JSON responses:
1. ``{"geo": "PT"}``
2. a plain array of ISO datetime strings
3. the actual "top value bets" array we care about (one bet per game)

``json_list_path: "[?game]"`` must pick out (3) regardless of the order
they're captured in -- this test deliberately puts the *decoy* blobs
first to lock that in.
"""

from datetime import datetime, timezone

from tipsxgs.config import load_config
from tipsxgs.xgscore.fixtures import scrape_today_fixtures

GEO_BLOB = {"geo": "PT"}

DATES_BLOB = [
    "2026-09-12T13:00:00.000Z",
    "2026-09-14T19:00:00.000Z",
]

# Trimmed from the real captured payload -- two games, one of them with an
# apostrophe in a team name (Newell's OB) to prove we use xGScore's own
# `game.slug` rather than re-slugifying team names ourselves (a naive
# slugify would produce "newell-s-ob", not the real "newells-ob").
BETS_BLOB = [
    {
        "id": "933b0128-4b97-4c29-8f8f-c3741c9b3e01",
        "oddsCategory": "dc",
        "oddsLabel": "1x",
        "startCf": 1.43,
        "maxCf": 1.46,
        "chance": 0.783,
        "gameId": "f15a1c99-b6e5-4b98-9968-908ed8d9258b",
        "game": {
            "slug": "union-berlin-schalke",
            "datetime": "2026-09-11T18:30:00.000Z",
            "played": False,
            "tournament": {
                "id": "ger-1",
                "name": "Bundesliga",
                "slug": "bundesliga",
                "country": {"name": "Germany"},
            },
            "forecastScore": {"h": 1.94, "a": 1.23},
            "teams": {
                "h": {"name": "Union", "countryId": "ger"},
                "a": {"name": "Schalke", "countryId": "ger"},
            },
        },
        "valueBet": 0.08,
        "text": "Home No lose",
    },
    {
        "id": "2ed799ca-2c17-48dc-b70b-2082084151e5",
        "oddsCategory": "h2",
        "oddsLabel": "0",
        "startCf": 1.88,
        "maxCf": 1.95,
        "chance": 0.543,
        "gameId": "cf509dcc-feb2-4ce8-a9eb-98aac79b6b94",
        "game": {
            "slug": "newells-ob-velez-s",
            "datetime": "2026-09-11T20:00:00.000Z",
            "played": False,
            "tournament": {
                "id": "arg-1",
                "name": "Argentina Liga Profesional",
                "slug": "argentina-primera",
                "country": {"name": "Argentina"},
            },
            "forecastScore": {"h": 1.03, "a": 1.18},
            "teams": {
                "h": {"name": "Newell's OB", "countryId": "arg"},
                "a": {"name": "Vélez S.", "countryId": "arg"},
            },
        },
        "valueBet": 0.01,
        "text": "Away Handicap (0)",
    },
]


class FakeSession:
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000):
        # Decoys deliberately captured *before* the real bets array.
        return "<html></html>", [GEO_BLOB, DATES_BLOB, BETS_BLOB]


def test_scrape_today_fixtures_against_real_xgscore_json_shape():
    cfg = load_config()  # repo-root config.yaml, calibrated for xgscore.fixtures
    fixtures = scrape_today_fixtures(cfg, session=FakeSession())

    assert len(fixtures) == 2
    by_slug = {fx.slug: fx for fx in fixtures}

    ub = by_slug["union-berlin-schalke"]
    assert ub.league == "bundesliga"
    assert ub.home_team == "Union"
    assert ub.away_team == "Schalke"
    assert ub.kickoff == datetime(2026, 9, 11, 18, 30, tzinfo=timezone.utc)
    assert ub.preview_url == "https://xgscore.io/bundesliga/union-berlin-schalke/preview"

    # The apostrophe case: xGScore's own game.slug ("newells-ob-velez-s"),
    # not our own naive re-slugification of "Newell's OB".
    newells = by_slug["newells-ob-velez-s"]
    assert newells.home_team == "Newell's OB"
    assert newells.preview_url == (
        "https://xgscore.io/argentina-primera/newells-ob-velez-s/preview"
    )
