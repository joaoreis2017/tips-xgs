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
