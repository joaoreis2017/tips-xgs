from datetime import date, datetime

import pytest

from tipsxgs.calibration import CalibrationBucket
from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.report import build_real_context
from tipsxgs.valuebets import compute_value_bets


def make_game(markets_prob, markets_odds, slug="union-berlin-schalke", home="Union Berlin", away="Schalke"):
    fixture = Fixture(
        slug=slug,
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=datetime(2026, 11, 17, 18, 0),
        preview_url=f"https://xgscore.io/bundesliga/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets_prob)
    odds = OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=fixture.kickoff, markets=markets_odds)
    game = MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=100.0)
    compute_value_bets(game)  # populate game.value_bets, same as the real pipeline does before rendering
    return game


def test_build_real_context_picks_a_leg_by_real_rate_even_below_30_games():
    # Model says 85% for home, but only 6 historical games at that band,
    # hitting 5/6 (83%) -- still enough to show here (just flagged
    # provisional), since compute_real_rate_value_bets has no minimum.
    game = make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.30}})
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=6, hits=5, avg_predicted_probability=0.85)
    ]

    ctx = build_real_context(
        date(2026, 11, 17), [game], buckets, high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45
    )

    assert len(ctx["multiple_legs"]) == 1
    leg = ctx["multiple_legs"][0]
    assert leg["real_probability"] == pytest.approx(5 / 6)
    assert leg["model_probability"] == pytest.approx(0.85)
    assert leg["sample_size"] == 6
    assert leg["is_confirmed"] is False  # below DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE (30)


def test_build_real_context_flags_a_band_as_confirmed_at_30_games_or_more():
    game = make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.30}})
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=30, hits=27, avg_predicted_probability=0.85)
    ]

    ctx = build_real_context(
        date(2026, 11, 17), [game], buckets, high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45
    )

    leg = ctx["multiple_legs"][0]
    assert leg["is_confirmed"] is True
    assert leg["sample_size"] == 30


def test_build_real_context_excludes_a_band_with_zero_historical_games():
    # No calibration bucket at all for this market+outcome+band -- there
    # is no real rate to rank it by, so it's left out entirely rather
    # than falling back to the model's own probability.
    game = make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.30}})

    ctx = build_real_context(
        date(2026, 11, 17), [game], calibration_buckets=[], high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45
    )

    assert ctx["multiple_legs"] == []


def test_build_real_context_does_not_mutate_the_games_own_value_bets():
    # The model-probability dashboard (game.value_bets) must keep working
    # exactly as before -- build_real_context computes its own separate
    # entries behind the scenes.
    game = make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.30}})
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=6, hits=5, avg_predicted_probability=0.85)
    ]
    original_calibrated = game.value_bets[0].calibrated_probability

    build_real_context(date(2026, 11, 17), [game], buckets)

    assert game.value_bets[0].calibrated_probability == original_calibrated  # still None, untouched


def test_build_real_context_ranks_multiple_legs_by_real_rate_not_model_probability():
    # game_a has the higher MODEL probability but a lower REAL rate;
    # game_b is the other way round -- sorting must follow the real rate.
    # game_a's odd (1.80) is high enough that even its lower real rate
    # (0.6) still clears pick_multiple_legs's default min_value_ratio=1.0
    # bar (0.6 * 1.80 = 1.08) -- otherwise it would be filtered out before
    # the ranking under test here ever got a chance to matter.
    game_a = make_game({"1x2": {"home": 0.95}}, {"1x2": {"home": 1.80}}, slug="a", home="A1", away="A2")
    game_b = make_game({"1x2": {"home": 0.82}}, {"1x2": {"home": 1.30}}, slug="b", home="B1", away="B2")
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="90-99%", count=10, hits=6, avg_predicted_probability=0.95),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=10, hits=9, avg_predicted_probability=0.82),
    ]

    ctx = build_real_context(
        date(2026, 11, 17), [game_a, game_b], buckets, high_probability_min=0.0, high_odd_min=1.0, high_odd_max=2.0
    )

    assert [leg["game_slug"] for leg in ctx["multiple_legs"]] == ["b", "a"]
