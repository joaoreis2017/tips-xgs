"""Regression test for the Betclic odds scraper against the real gRPC/JSON
shape confirmed on betclic.pt (2026-09-11) -- see config.yaml's
betclic.fixtures section for where this structure came from.
"""

from datetime import datetime, timezone

from tipsxgs.betclic.odds import scrape_today_odds
from tipsxgs.config import load_config

REAL_SHAPE_BLOB = {
    "grpc:1596417301": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "1216417087131648",
                        "name": "Rakow Czestochowa - Motor Lublin",
                        "matchDateUtc": "2026-09-11T16:00:00.0000000Z",
                        "isLive": True,
                        "contestants": [
                            {"contestantId": "a", "name": "Rakow Czestochowa"},
                            {"contestantId": "b", "name": "Motor Lublin"},
                        ],
                        "competition": {"id": "221", "name": "Polónia - Ekstraklasa"},
                        "market": {
                            "name": "Resultado (Tempo Regulamentar)",
                            "mainSelections": [
                                {"name": "Rakow Czestochowa", "odds": 2.18},
                                {"name": "Empate", "odds": 2.42},
                                {"name": "Motor Lublin", "odds": 3.07},
                            ],
                        },
                    }
                ]
            }
        }
    }
}


class FakeSession:
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000):
        return "<html></html>", [REAL_SHAPE_BLOB]


def test_scrape_today_odds_against_real_betclic_json_shape():
    cfg = load_config()  # repo-root config.yaml, calibrated for betclic.fixtures
    offers = scrape_today_odds(cfg, session=FakeSession())

    assert len(offers) == 1
    offer = offers[0]
    assert offer.home_team == "Rakow Czestochowa"
    assert offer.away_team == "Motor Lublin"
    assert offer.kickoff == datetime(2026, 9, 11, 16, 0, tzinfo=timezone.utc)
    assert offer.markets == {"1x2": {"home": 2.18, "draw": 2.42, "away": 3.07}}


# Second confirmed shape (2026-09-11): the same Angular TransferState blob
# that carries the "Em Direto" (live) matches under one grpc:<hash> key also
# carries *upcoming* (not-yet-kicked-off) fixtures for a specific
# competition -- e.g. "Liga Portugal Betclic" -- under a *different*
# grpc:<hash> key in that very same <script> blob, with isLive: false and a
# real future matchDateUtc. Both keys sit side by side in one JSON object,
# so `json_list_path: "*.response.payload.matches[]"` (a wildcard over
# every top-level key) already merges live + upcoming matches from a single
# page load with no config change -- this test locks that merging in.
MULTI_KEY_BLOB = {
    "grpc:1596417301": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "1216417087131648",
                        "name": "Rakow Czestochowa - Motor Lublin",
                        "matchDateUtc": "2026-09-11T16:00:00.0000000Z",
                        "isLive": True,
                        "contestants": [
                            {"contestantId": "a", "name": "Rakow Czestochowa"},
                            {"contestantId": "b", "name": "Motor Lublin"},
                        ],
                        "competition": {"id": "221", "name": "Polónia - Ekstraklasa"},
                        "market": {
                            "name": "Resultado (Tempo Regulamentar)",
                            "mainSelections": [
                                {"name": "Rakow Czestochowa", "odds": 2.18},
                                {"name": "Empate", "odds": 2.42},
                                {"name": "Motor Lublin", "odds": 3.07},
                            ],
                        },
                    }
                ]
            }
        }
    },
    "grpc:3335296709": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "1216417087131649",
                        "name": "Sporting CP - Benfica",
                        "matchDateUtc": "2026-09-14T19:30:00.0000000Z",
                        "isLive": False,
                        "contestants": [
                            {"contestantId": "c", "name": "Sporting CP"},
                            {"contestantId": "d", "name": "Benfica"},
                        ],
                        "competition": {"id": "32", "name": "Liga Portugal Betclic"},
                        "market": {
                            "name": "Resultado (Tempo Regulamentar)",
                            "mainSelections": [
                                {"name": "Sporting CP", "odds": 1.95},
                                {"name": "Empate", "odds": 3.4},
                                {"name": "Benfica", "odds": 3.9},
                            ],
                        },
                    },
                    {
                        "matchId": "1216417087131650",
                        "name": "FC Porto - Braga",
                        "matchDateUtc": "2026-09-15T20:00:00.0000000Z",
                        "isLive": False,
                        "contestants": [
                            {"contestantId": "e", "name": "FC Porto"},
                            {"contestantId": "f", "name": "Braga"},
                        ],
                        "competition": {"id": "32", "name": "Liga Portugal Betclic"},
                        "market": {
                            "name": "Resultado (Tempo Regulamentar)",
                            "mainSelections": [
                                {"name": "FC Porto", "odds": 1.75},
                                {"name": "Empate", "odds": 3.6},
                                {"name": "Braga", "odds": 4.6},
                            ],
                        },
                    },
                ]
            }
        }
    },
}


class MultiKeyFakeSession:
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000):
        return "<html></html>", [MULTI_KEY_BLOB]


def test_scrape_today_odds_merges_live_and_upcoming_matches_from_one_blob():
    cfg = load_config()
    offers = scrape_today_odds(cfg, session=MultiKeyFakeSession())

    # 1 live match (grpc:1596417301) + 2 upcoming Liga Portugal Betclic
    # matches (grpc:3335296709), all from the same JSON blob.
    assert len(offers) == 3
    by_teams = {(o.home_team, o.away_team): o for o in offers}

    live = by_teams[("Rakow Czestochowa", "Motor Lublin")]
    assert live.markets == {"1x2": {"home": 2.18, "draw": 2.42, "away": 3.07}}

    upcoming = by_teams[("Sporting CP", "Benfica")]
    assert upcoming.kickoff == datetime(2026, 9, 14, 19, 30, tzinfo=timezone.utc)
    assert upcoming.markets == {"1x2": {"home": 1.95, "draw": 3.4, "away": 3.9}}

    also_upcoming = by_teams[("FC Porto", "Braga")]
    assert also_upcoming.markets == {"1x2": {"home": 1.75, "draw": 3.6, "away": 4.6}}
