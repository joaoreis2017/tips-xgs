"""Regression test for the dashboard's "events by probability" filter.

Prompted by a real screenshot: with every xGScore market extracted (every
over/under line, every handicap line, ...), a game's full event list was
dozens of rows of near-certain/near-impossible outcomes ("under 5 goals:
100%") with no Betclic odd to compare against -- not useful to look at.
build_context() now only keeps an event that clears *both* a probability
and an odd threshold.
"""

from datetime import date

import pytest

from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.report import build_context
from tipsxgs.valuebets import compute_value_bets


def _game(
    markets: dict,
    odds_markets: dict | None,
    slug: str = "home-away",
    home: str = "Lazio",
    away: str = "Milan",
) -> MatchedGame:
    fixture = Fixture(
        slug=slug,
        league="serie-a",
        home_team=home,
        away_team=away,
        kickoff=None,
        preview_url=f"https://xgscore.io/serie-a/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets)
    odds = (
        OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=None, markets=odds_markets)
        if odds_markets is not None
        else None
    )
    game = MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=96.0)
    compute_value_bets(game)
    return game


def test_events_require_both_probability_and_odd_thresholds():
    game = _game(
        markets={
            # Clears both thresholds -- should show up.
            "1x2": {"home": 0.55},
            # High probability, but no matching Betclic odd at all --
            # e.g. a handicap line Betclic doesn't offer.
            "handicap_home": {"0": 0.7},
            # Has an odd, but probability is too low.
            "btts": {"yes": 0.3},
        },
        odds_markets={
            "1x2": {"home": 1.8},
            "btts": {"yes": 1.9},
            # "handicap_home" deliberately has no matching odd entry.
        },
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5, min_odd=1.2)
    events = ctx["games"][0]["events"]

    assert len(events) == 1
    assert events[0].market == "1x2" and events[0].outcome == "home"


def test_events_empty_when_no_betclic_offer_matched():
    # A game with no matched Betclic offer at all (odds is None) has
    # every odd = None -- by design, nothing clears "odd > min_odd", so
    # the events table is empty even though probabilities exist.
    game = _game(markets={"1x2": {"home": 0.9}}, odds_markets=None)

    ctx = build_context(date(2026, 9, 12), [game])
    assert ctx["games"][0]["events"] == []
    # The underlying probability data is untouched -- still there for
    # games.json / other views, just not shown in this filtered table.
    assert game.prediction.markets == {"1x2": {"home": 0.9}}


def test_events_threshold_is_configurable():
    game = _game(markets={"1x2": {"home": 0.4}}, odds_markets={"1x2": {"home": 1.5}})

    # Below the default 0.5 probability threshold -- excluded.
    assert build_context(date(2026, 9, 12), [game])["games"][0]["events"] == []
    # Lowering the threshold includes it.
    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.3, min_odd=1.2)
    assert len(ctx["games"][0]["events"]) == 1


def test_has_predictions_distinguishes_genuinely_empty_from_filtered_out():
    # An empty `events` table can mean two very different things -- the
    # dashboard template needs `has_predictions` to tell them apart
    # rather than showing the same "nothing was scraped" message for
    # both (a real bug report from a user who had plenty of xGScore
    # predictions, just none clearing the Betclic-odd filter above).
    scraped_but_filtered = _game(markets={"1x2": {"home": 0.9}}, odds_markets=None)
    genuinely_empty = _game(markets={}, odds_markets=None)

    ctx = build_context(date(2026, 9, 12), [scraped_but_filtered, genuinely_empty])
    assert ctx["games"][0]["has_predictions"] is True
    assert ctx["games"][0]["events"] == []
    assert ctx["games"][1]["has_predictions"] is False
    assert ctx["games"][1]["events"] == []


def test_top_probability_bets_drops_markets_betclic_never_covers():
    # betclic_markets, when passed, drops odd-less entries for markets
    # config.yaml's betclic section has no extraction rule for at all
    # (e.g. handicap lines) -- see valuebets.top_probability_bets_today.
    game = _game(
        markets={"1x2": {"home": 0.9}, "handicap_home": {"-3": 0.99}},
        odds_markets=None,
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5, betclic_markets={"1x2", "btts"})
    rows = ctx["top_probability_bets"]
    assert len(rows) == 1
    assert rows[0]["game_slug"] == "home-away"
    assert rows[0]["label"] == "Resultado Final - Casa"


def test_top_probability_bets_covers_games_without_a_betclic_offer():
    # Requested explicitly: a cross-game "high probability" list that,
    # unlike top_value_bets, covers *every* game with a prediction --
    # including one with no matched Betclic offer at all.
    no_offer = _game(
        markets={"1x2": {"home": 0.9}}, odds_markets=None, slug="no-offer", home="Team C", away="Team D"
    )
    with_offer = _game(
        markets={"1x2": {"home": 0.55}},
        odds_markets={"1x2": {"home": 1.8}},
        slug="with-offer",
        home="Team A",
        away="Team B",
    )

    ctx = build_context(date(2026, 9, 12), [no_offer, with_offer], min_probability=0.5)
    rows = ctx["top_probability_bets"]

    by_slug = {r["game_slug"]: r for r in rows}
    assert "no-offer" in by_slug
    assert by_slug["no-offer"]["odd"] is None
    assert by_slug["no-offer"]["value_ratio"] is None
    assert "with-offer" in by_slug
    assert by_slug["with-offer"]["odd"] == pytest.approx(1.8)
    # Highest probability first.
    assert rows[0]["game_slug"] == "no-offer"
