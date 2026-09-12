"""Regression test for the xGScore preview scraper against the real JSON
shape confirmed on xgscore.io (2026-09-11) -- see config.yaml's
xgscore.preview section for where this structure came from.

The preview page fires a *lot* of unrelated JSON responses (team form,
league standings, head-to-head, a per-bookmaker odds-comparison array)
alongside the one small object that actually holds xGScore's own market
probabilities. This test includes representative decoys (deliberately
*before* the real one) to lock in that the field rules correctly ignore
them -- especially the per-bookmaker odds array, which uses the exact
same key names ("r", "dc", "bts", "tm", "tl", ...) but holds decimal odds
instead of probabilities, and is a *list* of several such objects rather
than a single dict.
"""

from datetime import datetime, timezone

from tipsxgs.config import load_config
from tipsxgs.models import Fixture
from tipsxgs.xgscore.preview import scrape_preview

GEO_BLOB = {"geo": "PT"}

# Decoy #1: a team-strength/form stats object -- no "r"/"bts"/"tm" keys.
TEAM_STATS_BLOB = {
    "id": "a3605852-b39c-4628-8c32-38dade7494c3",
    "hRank": 5,
    "hForm": 2.1,
    "aRank": 3.2,
    "aForm": 4,
    "gameId": "f15a1c99-b6e5-4b98-9968-908ed8d9258b",
}

# Decoy #2: this game's "top value bets" array (one flagged pick per
# market, matching the homepage feed's shape) -- a *list*, so a bare `.r`
# field access on it resolves to null, not the real market data.
VALUE_BETS_BLOB = [
    {
        "id": "2e0f32ec-ae12-41c8-b5e7-55e0339babf8",
        "oddsCategory": "tm",
        "oddsLabel": "2.5",
        "chance": 0.639,
        "gameId": "f15a1c99-b6e5-4b98-9968-908ed8d9258b",
        "text": "Total Over 2.5",
    }
]

# Decoy #3: the per-bookmaker odds-comparison array -- same key names
# ("r", "dc", "bts", "tm", "tl", ...) as the real metadata object below,
# but each row holds decimal ODDS (e.g. 2.5, 3.635) rather than a
# probability percentage, and it's wrapped in a list (several bookmakers
# + MAX/AVG aggregates), not a lone dict.
BOOKMAKER_ODDS_BLOB = [
    {
        "id": "0f54c468-8093-4170-b861-f314144eacf1",
        "r": [["1", 2.5], ["x", 3.635], ["2", 2.937]],
        "bts": [["yes", 1.49], ["no", 2.476]],
        "tm": [["2.5", 1.684]],
        "tl": [["2.5", 2.373]],
        "bookmakerId": 2,
        "sourceType": "BOOKMAKER",
        "gameId": "f15a1c99-b6e5-4b98-9968-908ed8d9258b",
    }
]

# The real thing: xGScore's own computed market probabilities for this
# game -- the *full* set confirmed live (2026-09-12), including every
# array_markets source (itm1/itl1/itm2/itl2 per-team totals, h1/h2
# handicap, dc double chance), not just r/bts/tm/tl. Values are
# double-encoded JSON strings on the wire -- BrowserSession/
# find_embedded_json run every blob through deep_parse_json_strings(), so
# the FakeSession below hands back the already-decoded (real nested list)
# form, exactly like the scraper would see it after that step.
METADATA_BLOB = {
    "id": "63d5a517-b04a-47fe-8949-a73831ec4531",
    "r": [["1", 54.5, 12.7, 2.4], ["x", 23.7, -3.6, 1.8], ["2", 21.7, -10.7, 0.7]],
    "dc": [["1x", 78.3, 8.1, 0.7], ["12", 76.3, 1, 1.8], ["x2", 45.5, -14.9, 2.4]],
    "bts": [["yes", 67.1, 0.5, 4.7], ["no", 32.9, -8, 4.7]],
    "tm": [["0.5", 94.8, -4.3, 1.3], ["2.5", 63.9, 4.9, 7], ["3", 50.1, 2.3, 8.3]],
    "tl": [["0.5", 5.2, -1.2, 1.3], ["2.5", 36.1, -6.5, 7], ["3", 49.9, -5.7, 8.3]],
    "itm1": [["0.5", 86.1, -0.2, 2.8], ["2.5", 31.6, 6.9, 5.8], ["4", 5.5, None, 2.5]],
    "itl1": [["0.5", 13.9, -8.8, 2.8], ["2.5", 68.4, -13.6, 5.8], ["4", 94.5, None, 2.5]],
    "itm2": [["0.5", 69.6, -11.7, 2.9], ["2.5", 11.8, -7, 2.3], ["4", 0.8, None, 0.3]],
    "itl2": [["0.5", 30.4, 2.6, 2.9], ["2.5", 88.2, 0.4, 2.3], ["4", 99.2, None, 0.3]],
    "h1": [["-2.5", 15.8, 4.3, 2.7], ["0", 71.5, 14.5, 1.5], ["1.5", 91.1, -0.8, 0.2]],
    "h2": [["-1.5", 8.9, -7.9, 0.2], ["0", 28.5, -16, 1.5], ["2.5", 84.2, -14.9, 2.7]],
    "cs": None,
    "gameId": "f15a1c99-b6e5-4b98-9968-908ed8d9258b",
    "metadataId": "56a2e4d2-3698-4568-84d7-11e5e7f037fe",
}


class FakeSession:
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        # Decoys deliberately captured *before* the real metadata blob.
        return "<html></html>", [
            GEO_BLOB,
            TEAM_STATS_BLOB,
            VALUE_BETS_BLOB,
            BOOKMAKER_ODDS_BLOB,
            METADATA_BLOB,
        ]


def test_scrape_preview_against_real_xgscore_json_shape():
    cfg = load_config()  # repo-root config.yaml, calibrated for xgscore.preview
    fixture = Fixture(
        slug="union-berlin-schalke",
        league="bundesliga",
        home_team="Union",
        away_team="Schalke",
        kickoff=datetime(2026, 9, 11, 18, 30, tzinfo=timezone.utc),
        preview_url="https://xgscore.io/bundesliga/union-berlin-schalke/preview",
    )

    prediction = scrape_preview(cfg, fixture, session=FakeSession())

    rounded = {market: {k: round(v, 3) for k, v in outcomes.items()} for market, outcomes in prediction.markets.items()}
    assert rounded == {
        "1x2": {"home": 0.545, "draw": 0.237, "away": 0.217},
        "btts": {"yes": 0.671, "no": 0.329},
        "double_chance": {"1x": 0.783, "12": 0.763, "x2": 0.455},
        "over_under_0.5": {"over": 0.948, "under": 0.052},
        "over_under_2.5": {"over": 0.639, "under": 0.361},
        "over_under_3": {"over": 0.501, "under": 0.499},
        "home_total_0.5": {"over": 0.861, "under": 0.139},
        "home_total_2.5": {"over": 0.316, "under": 0.684},
        "home_total_4": {"over": 0.055, "under": 0.945},
        "away_total_0.5": {"over": 0.696, "under": 0.304},
        "away_total_2.5": {"over": 0.118, "under": 0.882},
        "away_total_4": {"over": 0.008, "under": 0.992},
        "handicap_home": {"-2.5": 0.158, "0": 0.715, "1.5": 0.911},
        "handicap_away": {"-1.5": 0.089, "0": 0.285, "2.5": 0.842},
    }
