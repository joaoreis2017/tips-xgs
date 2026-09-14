"""Regression test for the Betclic odds scraper against the real gRPC/JSON
shape confirmed on betclic.pt (2026-09-11) -- see config.yaml's
betclic.fixtures section for where this structure came from.
"""

from datetime import date, datetime, timezone

from tipsxgs.betclic.odds import _build_match_url, scrape_today_odds
from tipsxgs.config import load_config


def _load_config_single_fixtures_url():
    """load_config(), but with the repo's real betclic.fixtures.urls (one
    entry per competition -- 17 as of writing) trimmed down to one dummy
    URL. Tests below use a FakeSession that ignores the URL it's given
    and returns the same fixed blob regardless -- without this, every
    such test would visit all 17 real URLs (each with its own
    polite_delay sleep), which is both needlessly slow and, for a
    FakeSession whose behavior depends on call *count*
    (``TwoStepFakeSession``), outright wrong. Tests that specifically
    exercise multi-URL merging set their own `.urls` instead."""
    cfg = load_config()
    cfg.betclic.page("fixtures").urls = ["https://example.invalid/fixtures"]
    return cfg

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
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        return "<html></html>", [REAL_SHAPE_BLOB]


def test_scrape_today_odds_against_real_betclic_json_shape():
    cfg = _load_config_single_fixtures_url()  # repo-root config.yaml, calibrated for betclic.fixtures
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
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        return "<html></html>", [MULTI_KEY_BLOB]


def test_scrape_today_odds_merges_live_and_upcoming_matches_from_one_blob():
    cfg = _load_config_single_fixtures_url()
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


# Regression for a real bug (2026-09-11 live run): betclic.fixtures.url is
# an infinite-scroll list, so scrolling (scroll_count in config.yaml)
# fires a *separate* XHR per page -- each page is captured as its own,
# separate blob in `blobs` (unlike the single-blob-multiple-grpc-keys case
# above), holding a *different* slice of matches. Taking only the first
# blob's matches silently dropped every later page: live, the total
# offer count stayed flat at one page's worth no matter how much
# scrolling happened, until _rows_from_json was fixed to merge across
# every blob instead of stopping at the first non-empty one.
PAGE_1_BLOB = {
    "grpc:1111111111": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "1",
                        "matchDateUtc": "2026-09-12T14:30:00.0000000Z",
                        "isLive": False,
                        "contestants": [{"name": "Aali"}, {"name": "Malkiya"}],
                        "competition": {"name": "Bahrein - Liga"},
                        "market": {
                            "mainSelections": [
                                {"name": "Aali", "odds": 1.5},
                                {"name": "Empate", "odds": 3.5},
                                {"name": "Malkiya", "odds": 5.0},
                            ]
                        },
                    }
                ]
            }
        }
    }
}

# A second, separate captured response -- as if triggered by a
# scroll-to-bottom -- with a *different* match (not a repeat of page 1).
PAGE_2_BLOB = {
    "grpc:2222222222": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "2",
                        "matchDateUtc": "2026-09-12T18:45:00.0000000Z",
                        "isLive": False,
                        "contestants": [{"name": "Sevilla"}, {"name": "Valencia"}],
                        "competition": {"name": "Espanha - La Liga"},
                        "market": {
                            "mainSelections": [
                                {"name": "Sevilla", "odds": 1.9},
                                {"name": "Empate", "odds": 3.4},
                                {"name": "Valencia", "odds": 4.2},
                            ]
                        },
                    }
                ]
            }
        }
    }
}


class MultiPageFakeSession:
    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        return "<html></html>", [PAGE_1_BLOB, PAGE_2_BLOB]


def test_scrape_today_odds_merges_matches_across_scroll_triggered_pages():
    cfg = _load_config_single_fixtures_url()
    offers = scrape_today_odds(cfg, session=MultiPageFakeSession())

    assert len(offers) == 2
    by_teams = {(o.home_team, o.away_team) for o in offers}
    assert by_teams == {("Aali", "Malkiya"), ("Sevilla", "Valencia")}


class MultiUrlFakeSession:
    """Returns a *different* blob depending on which competition URL was
    requested -- mirrors betclic.fixtures.urls (one page per league)
    rather than one page's captured-JSON list."""

    def __init__(self):
        self.urls_visited: list[str] = []

    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        self.urls_visited.append(url)
        if "premier-league" in url:
            return "<html></html>", [PAGE_1_BLOB]
        if "la-liga" in url:
            return "<html></html>", [PAGE_2_BLOB]
        return "<html></html>", []


def test_scrape_today_odds_visits_every_competition_url_and_merges_results():
    cfg = load_config()
    fixtures_page = cfg.betclic.page("fixtures")
    fixtures_page.urls = [
        "https://www.betclic.pt/futebol-s1/inglaterra-premier-league-c3",
        "https://www.betclic.pt/futebol-s1/espanha-la-liga-c7",
        "https://www.betclic.pt/futebol-s1/alemanha-bundesliga-c5",  # no matches for this one
    ]
    cfg.betclic.request_delay_seconds = 0  # skip the real polite_delay sleep in this test

    session = MultiUrlFakeSession()
    offers = scrape_today_odds(cfg, session=session)

    # Visited every configured URL (not just the first with results).
    assert len(session.urls_visited) == 3
    by_teams = {(o.home_team, o.away_team) for o in offers}
    assert by_teams == {("Aali", "Malkiya"), ("Sevilla", "Valencia")}


# Third confirmed shape (2026-09-11): a match's own detail page, requested
# specifically to calibrate BTTS / over-under (the listing page above only
# carries the inline 1X2 market). Same Angular TransferState pattern, but
# this grpc:<hash> key holds {"response": {"payload": {"match": {...}}}}
# (singular "match") with every market grouped under
# match.subCategories[].markets[] -- real example: "CD Nacional - FC
# Alverca" (Liga Portugal Betclic). Two selection shapes coexist in the
# same payload: "As duas equipas marcam" (BTTS) wraps each selection as
# {"selectionOneof": {"oneofKind": "selection", "selection": {...}}}, while
# "Total de golos - acima/abaixo" (over/under) uses plain {name, odds}
# objects -- config.yaml's betclic.odds.fields matches each shape exactly.
MATCH_DETAIL_BLOB = {
    "grpc:2547122988": {
        "response": {
            "oneofKind": "payload",
            "payload": {
                "match": {
                    "matchId": "1217462611771392",
                    "subCategories": [
                        {
                            "markets": [
                                {
                                    "id": "1217462616989698",
                                    "name": "Resultado (Tempo Regulamentar)",
                                    "mainSelections": [
                                        {"name": "CD Nacional", "odds": 2.55},
                                        {"name": "Empate", "odds": 3.2},
                                        {"name": "FC Alverca", "odds": 2.67},
                                    ],
                                },
                                {
                                    "id": "1217463160180773",
                                    "name": "Total de golos - acima/abaixo",
                                    "selectionMatrix": [
                                        {
                                            "selections": [
                                                {"name": "Acima de 0,5", "odds": 1.03},
                                                {"name": "Abaixo de 0,5", "odds": 5.75},
                                            ]
                                        },
                                        {
                                            "selections": [
                                                {"name": "Acima de 2,5", "odds": 1.84},
                                                {"name": "Abaixo de 2,5", "odds": 1.68},
                                            ]
                                        },
                                    ],
                                },
                                {
                                    "id": "1217463160180824",
                                    "name": "As duas equipas marcam",
                                    "selectionMatrix": [
                                        {
                                            "selections": [
                                                {
                                                    "selectionOneof": {
                                                        "oneofKind": "selection",
                                                        "selection": {"name": "Sim", "odds": 1.68},
                                                    }
                                                },
                                                {
                                                    "selectionOneof": {
                                                        "oneofKind": "selection",
                                                        "selection": {"name": "Não", "odds": 1.83},
                                                    }
                                                },
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    ],
                }
            },
        }
    }
}

FIXTURES_LIST_BLOB = {
    "grpc:3335296709": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "1217462611771392",
                        "name": "CD Nacional - FC Alverca",
                        "matchDateUtc": "2026-09-12T14:30:00.0000000Z",
                        "isLive": False,
                        "contestants": [
                            {"contestantId": "a", "name": "CD Nacional"},
                            {"contestantId": "b", "name": "FC Alverca"},
                        ],
                        "competition": {"id": "32", "name": "Liga Portugal Betclic"},
                        "market": {
                            "name": "Resultado (Tempo Regulamentar)",
                            "mainSelections": [
                                {"name": "CD Nacional", "odds": 2.55},
                                {"name": "Empate", "odds": 3.2},
                                {"name": "FC Alverca", "odds": 2.67},
                            ],
                        },
                    }
                ]
            }
        }
    }
}


class TwoStepFakeSession:
    """First call (the fixtures list) returns FIXTURES_LIST_BLOB; every
    subsequent call (one per match's detail page) returns MATCH_DETAIL_BLOB
    -- mirrors scrape_today_odds()'s "list page, then hop to each match's
    own page" flow."""

    def __init__(self):
        self.calls = []

    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        self.calls.append(url)
        if len(self.calls) == 1:
            return "<html></html>", [FIXTURES_LIST_BLOB]
        return "<html></html>", [MATCH_DETAIL_BLOB]


def test_build_match_url_from_betclic_routing_template():
    cfg = load_config()
    row = {
        "home_team": "CD Nacional",
        "away_team": "FC Alverca",
        "league": "Liga Portugal Betclic",
        "match_id": "1217462611771392",
        "competition_id": "32",
    }
    url = _build_match_url(cfg, row)
    assert url == "/futebol-s1/liga-portugal-betclic-c32/cd-nacional-fc-alverca-m1217462611771392"


def test_scrape_today_odds_reads_btts_and_over_under_from_match_detail_page():
    cfg = _load_config_single_fixtures_url()
    session = TwoStepFakeSession()
    # The detail-page hop is now skipped for matches not kicking off on
    # `day` (see the "only today's matches" filter in scrape_today_odds)
    # -- pin it to the fixture's own kickoff date (2026-09-12) so this
    # test still exercises the hop.
    offers = scrape_today_odds(cfg, session=session, day=date(2026, 9, 12))

    assert len(offers) == 1
    offer = offers[0]
    assert offer.home_team == "CD Nacional"
    assert offer.away_team == "FC Alverca"
    # 1x2 from the listing page + btts/over-under from the detail-page hop.
    assert offer.markets == {
        "1x2": {"home": 2.55, "draw": 3.2, "away": 2.67},
        "btts": {"yes": 1.68, "no": 1.83},
        "over_under_2.5": {"over": 1.84, "under": 1.68},
    }
    # scrape_today_odds should have hopped to the built detail-page URL.
    assert len(session.calls) == 2
    assert session.calls[1].endswith(
        "/futebol-s1/liga-portugal-betclic-c32/cd-nacional-fc-alverca-m1217462611771392"
    )


# Regression for a real live-run problem (2026-09-14): a competition page
# lists *every* upcoming fixture for that league (days or weeks out), not
# just today's -- 219 matches parsed from 17 competition pages when only
# ~15 xGScore fixtures were for today, each triggering its own detail-page
# hop (~5s apiece with the polite delay) for matches that could never be
# matched to a today-only xGScore fixture anyway.
TWO_MATCHES_LIST_BLOB = {
    "grpc:1111111111": {
        "response": {
            "payload": {
                "matches": [
                    {
                        "matchId": "today-1",
                        "name": "CD Nacional - FC Alverca",
                        "matchDateUtc": "2026-09-12T14:30:00.0000000Z",
                        "isLive": False,
                        "contestants": [{"name": "CD Nacional"}, {"name": "FC Alverca"}],
                        "competition": {"id": "32", "name": "Liga Portugal Betclic"},
                        "market": {
                            "mainSelections": [
                                {"name": "CD Nacional", "odds": 2.55},
                                {"name": "Empate", "odds": 3.2},
                                {"name": "FC Alverca", "odds": 2.67},
                            ]
                        },
                    },
                    {
                        "matchId": "future-1",
                        "name": "Sporting - Benfica",
                        "matchDateUtc": "2026-10-30T20:00:00.0000000Z",  # weeks out
                        "isLive": False,
                        "contestants": [{"name": "Sporting"}, {"name": "Benfica"}],
                        "competition": {"id": "32", "name": "Liga Portugal Betclic"},
                        "market": {
                            "mainSelections": [
                                {"name": "Sporting", "odds": 1.9},
                                {"name": "Empate", "odds": 3.3},
                                {"name": "Benfica", "odds": 4.1},
                            ]
                        },
                    },
                ]
            }
        }
    }
}


class TwoMatchesFakeSession:
    """Like ``TwoStepFakeSession``, but the list page carries two matches
    -- one kicking off ``day``, one weeks out -- so the detail-page hop's
    "only today's matches" filter has something to actually filter."""

    def __init__(self):
        self.calls = []

    def get_html_and_captured_json(self, url, url_substring_filter=None, wait_ms=2000, **_kwargs):
        self.calls.append(url)
        if len(self.calls) == 1:
            return "<html></html>", [TWO_MATCHES_LIST_BLOB]
        return "<html></html>", [MATCH_DETAIL_BLOB]


def test_scrape_today_odds_skips_detail_hop_for_matches_not_kicking_off_today():
    cfg = _load_config_single_fixtures_url()
    session = TwoMatchesFakeSession()
    offers = scrape_today_odds(cfg, session=session, day=date(2026, 9, 12))

    # Both matches are still returned...
    assert len(offers) == 2
    by_teams = {(o.home_team, o.away_team): o for o in offers}

    # ...but only the one kicking off on `day` got the detail-page hop
    # (btts/over-under on top of its inline 1x2)...
    today_offer = by_teams[("CD Nacional", "FC Alverca")]
    assert today_offer.markets == {
        "1x2": {"home": 2.55, "draw": 3.2, "away": 2.67},
        "btts": {"yes": 1.68, "no": 1.83},
        "over_under_2.5": {"over": 1.84, "under": 1.68},
    }

    # ...while the one weeks out kept only its inline 1x2 -- no detail
    # page was ever requested for it.
    future_offer = by_teams[("Sporting", "Benfica")]
    assert future_offer.markets == {"1x2": {"home": 1.9, "draw": 3.3, "away": 4.1}}

    # One call for the listing page + exactly one detail-page hop (not two).
    assert len(session.calls) == 2
