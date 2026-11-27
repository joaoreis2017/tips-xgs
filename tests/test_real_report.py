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


def test_build_real_context_game_breakdown_lists_every_qualifying_event_per_game():
    # Explicitly requested (2026-11-17): besides the two bet-plan bands,
    # a per-game breakdown of EVERY event whose real rate clears
    # min_probability (default 50%) and has a matched odd -- not just
    # the ones that also happen to fall in the multiple/mid-band ranges.
    game = make_game(
        {"1x2": {"home": 0.85, "away": 0.10}, "btts": {"yes": 0.60}},
        {"1x2": {"home": 1.30, "away": 9.0}, "btts": {"yes": 1.80}},
    )
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=6, hits=5, avg_predicted_probability=0.85),  # real 83%
        CalibrationBucket(market="btts", outcome="yes", probability_bucket="60-69%", count=4, hits=3, avg_predicted_probability=0.60),  # real 75%
        CalibrationBucket(market="1x2", outcome="away", probability_bucket="10-19%", count=10, hits=1, avg_predicted_probability=0.10),  # real 10%, below 50%
    ]

    ctx = build_real_context(date(2026, 11, 17), [game], buckets)

    assert len(ctx["game_breakdown"]) == 1
    block = ctx["game_breakdown"][0]
    assert block["slug"] == game.fixture.slug
    # 1x2 home (real 5/6 = 83%) ranked above btts yes (real 3/4 = 75%) --
    # sorted by real rate descending, not by market/model probability.
    assert [e["label"] for e in block["events"]] == ["Resultado Final - Casa", "Ambas Marcam - Sim"]
    real_rates = [e["real_probability"] for e in block["events"]]
    assert real_rates == sorted(real_rates, reverse=True)
    # away (10% real) excluded -- below the 50% min_probability floor
    assert not any("Fora" in e["label"] for e in block["events"])


def test_build_real_context_game_breakdown_requires_a_matched_odd():
    # Mirrors build_context's own per-game events table: an outcome
    # clearing the real-rate floor but with no matched Betclic odd is
    # dropped, not shown with odd/value as "--".
    game = make_game({"1x2": {"home": 0.85}}, {})  # no odds at all
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=6, hits=5, avg_predicted_probability=0.85)
    ]
    ctx = build_real_context(date(2026, 11, 17), [game], buckets)
    assert ctx["game_breakdown"] == []


def test_build_real_context_game_breakdown_require_odd_false_keeps_odd_less_events():
    # Real case (2026-11-27): a --skip-betclic run (no Betclic attempt
    # at all that day) must still show the real rates instead of an
    # empty page -- require_odd=False lets an odd-less qualifying event
    # through, same as build_context's own events table.
    game = make_game({"1x2": {"home": 0.85}}, {})  # no odds at all
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=6, hits=5, avg_predicted_probability=0.85)
    ]
    ctx = build_real_context(date(2026, 11, 17), [game], buckets, require_odd=False)
    assert len(ctx["game_breakdown"]) == 1
    event = ctx["game_breakdown"][0]["events"][0]
    assert event["odd"] is None
    assert event["value_ratio"] is None


def test_build_real_context_game_breakdown_respects_custom_min_probability():
    game = make_game({"1x2": {"home": 0.60}}, {"1x2": {"home": 1.5}})
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="60-69%", count=6, hits=4, avg_predicted_probability=0.60)
    ]  # real rate 4/6 = 67%

    below = build_real_context(date(2026, 11, 17), [game], buckets, min_probability=0.70)
    assert below["game_breakdown"] == []

    above = build_real_context(date(2026, 11, 17), [game], buckets, min_probability=0.50)
    assert len(above["game_breakdown"]) == 1


def test_build_real_context_multiple_legs_tiebreak_prefers_sample_size_then_model_probability():
    # Real case (2026-11-18): three fixtures tied at exactly the same
    # real rate and sample size -- without a tiebreak, whichever fixture
    # xGScore happened to list first would win a later leg cap purely by
    # accident. Now: higher sample size wins outright; when sample size
    # ALSO ties, the model's own probability decides.
    low_n = make_game({"1x2": {"home": 0.60}}, {"1x2": {"home": 1.3}}, slug="low-n", home="A1", away="A2")
    high_model = make_game({"1x2": {"home": 0.95}}, {"1x2": {"home": 1.3}}, slug="high-model", home="B1", away="B2")
    low_model = make_game({"1x2": {"home": 0.75}}, {"1x2": {"home": 1.3}}, slug="low-model", home="C1", away="C2")
    # Each bucket's own probability_bucket must match _bucket_label() of
    # that fixture's model probability (0.60 -> "60-69%", 0.95 -> "90-99%",
    # 0.75 -> "70-79%") for calibrated_probability's lookup to find it.
    # hits/count are chosen so all three land on the exact same real
    # rate (0.80) -- low_n with a HIGHER sample size (10) than the other
    # two (5 each), which share that lower sample size.
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="60-69%", count=10, hits=8, avg_predicted_probability=0.60),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="90-99%", count=5, hits=4, avg_predicted_probability=0.95),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="70-79%", count=5, hits=4, avg_predicted_probability=0.75),
    ]

    ctx = build_real_context(
        date(2026, 11, 17), [low_n, high_model, low_model], buckets,
        high_probability_min=0.70, high_odd_min=1.25, high_odd_max=1.45,
    )

    legs = ctx["multiple_legs"]
    assert [leg["real_probability"] for leg in legs] == [0.8, 0.8, 0.8]  # genuine 3-way tie
    # low_n wins outright: same real rate, but sample size 10 > 5.
    assert legs[0]["game_slug"] == "low-n"
    # high_model and low_model share sample size 5 -- model probability
    # (0.95 vs 0.75) breaks that second-level tie.
    assert legs[1]["game_slug"] == "high-model"
    assert legs[2]["game_slug"] == "low-model"


def test_build_real_context_multiple_leg_cap_keeps_only_the_best_n_legs():
    # Explicitly requested (2026-11-18), after backtesting: capping the
    # multiple's own leg count was the single biggest lever for its
    # consistency (a multiple needs every leg to hit, so each extra leg
    # multiplies the chance of losing).
    games = [
        make_game({"1x2": {"home": 0.95}}, {"1x2": {"home": 1.30}}, slug="a", home="A1", away="A2"),
        make_game({"1x2": {"home": 0.90}}, {"1x2": {"home": 1.30}}, slug="b", home="B1", away="B2"),
        make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.30}}, slug="c", home="C1", away="C2"),
        make_game({"1x2": {"home": 0.82}}, {"1x2": {"home": 1.30}}, slug="d", home="D1", away="D2"),
    ]
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket=f"{int(p*100)//10*10:02d}-{int(p*100)//10*10+9:02d}%", count=10, hits=9, avg_predicted_probability=p)
        for p in (0.95, 0.90, 0.85, 0.82)
    ]

    without_cap = build_real_context(date(2026, 11, 17), games, buckets, high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45)
    assert len(without_cap["multiple_legs"]) == 4
    assert without_cap["multiple_leg_cap"] is None

    with_cap = build_real_context(
        date(2026, 11, 17), games, buckets, high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45,
        multiple_leg_cap=2,
    )
    assert len(with_cap["multiple_legs"]) == 2
    assert with_cap["multiple_leg_cap"] == 2
    # Keeps the best 2 (highest real rate), same order as before capping.
    assert [leg["game_slug"] for leg in with_cap["multiple_legs"]] == ["a", "b"]


def test_build_real_context_multiple_leg_cap_recomputes_the_combined_odd_and_probability():
    games = [
        make_game({"1x2": {"home": 0.95}}, {"1x2": {"home": 1.30}}, slug="a", home="A1", away="A2"),
        make_game({"1x2": {"home": 0.90}}, {"1x2": {"home": 1.40}}, slug="b", home="B1", away="B2"),
        make_game({"1x2": {"home": 0.85}}, {"1x2": {"home": 1.20}}, slug="c", home="C1", away="C2"),
    ]
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="90-99%", count=10, hits=9, avg_predicted_probability=0.95),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="90-99%", count=10, hits=9, avg_predicted_probability=0.90),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="80-89%", count=10, hits=9, avg_predicted_probability=0.85),
    ]

    ctx = build_real_context(
        date(2026, 11, 17), games, buckets, high_probability_min=0.80, high_odd_min=1.20, high_odd_max=1.45,
        multiple_leg_cap=2,
    )
    # Only the best 2 legs (a, b) -- NOT the 3rd (c) -- contribute to the
    # combined odd/probability.
    assert ctx["multiple_combined_odd"] == pytest.approx(1.30 * 1.40)
    assert ctx["multiple_combined_probability"] == pytest.approx(0.9 * 0.9)  # both real_probability = 9/10


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
