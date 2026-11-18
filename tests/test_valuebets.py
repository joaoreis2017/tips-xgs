from datetime import datetime

import pytest

from tipsxgs.calibration import CalibrationBucket
from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.valuebets import (
    compute_real_rate_value_bets,
    compute_value_bets,
    multiple_combined_odd,
    multiple_combined_probability,
    pick_band_bets,
    pick_multiple_legs,
    top_probability_bets_today,
    top_value_bets_today,
)


def make_game(markets_prob, markets_odds, slug="union-berlin-schalke", home="Union Berlin", away="Schalke"):
    fixture = Fixture(
        slug=slug,
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=datetime(2026, 9, 11, 18, 0),
        preview_url=f"https://xgscore.io/bundesliga/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets_prob)
    odds = (
        OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=fixture.kickoff, markets=markets_odds)
        if markets_odds is not None
        else None
    )
    return MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=100.0 if odds else None)


def test_value_ratio_matches_user_example():
    # 70% probability, odd of 2.00 -> the user's own example of a "great value" bet.
    game = make_game(
        {"1x2": {"home": 0.70, "draw": 0.20, "away": 0.10}},
        {"1x2": {"home": 2.00, "draw": 4.0, "away": 8.0}},
    )
    entries = compute_value_bets(game)
    home = next(e for e in entries if e.market == "1x2" and e.outcome == "home")
    assert home.value_ratio == pytest.approx(1.4)
    assert home.is_value_bet is True


def test_rank_by_probability_orders_events_descending():
    game = make_game(
        {"1x2": {"home": 0.30, "draw": 0.25, "away": 0.45}, "btts": {"yes": 0.55, "no": 0.45}},
        {"1x2": {"home": 3.2, "draw": 3.4, "away": 2.1}, "btts": {"yes": 1.9, "no": 1.9}},
    )
    entries = compute_value_bets(game)
    probs = [e.probability for e in entries]
    assert probs == sorted(probs, reverse=True)
    assert entries[0].rank_by_probability == 1
    assert entries[0].outcome == "yes"  # btts yes at 0.55 is the highest single probability


def test_fair_probability_removes_overround_when_full_market_priced():
    # implied = 1/1.9091 + 1/3.6364 + 1/3.6364 = 0.5238 + 0.275 + 0.275 = 1.0738 (7.4% overround)
    game = make_game(
        {"1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}},
        {"1x2": {"home": 1.9091, "draw": 3.6364, "away": 3.6364}},
    )
    entries = compute_value_bets(game)
    home = next(e for e in entries if e.outcome == "home")
    assert home.fair_probability < home.implied_probability
    assert home.fair_probability == pytest.approx(0.5238 / 1.0738, rel=1e-3)


def test_missing_odds_still_ranks_by_probability_without_value_fields():
    game = make_game({"1x2": {"home": 0.6, "draw": 0.25, "away": 0.15}}, {})
    entries = compute_value_bets(game)
    assert entries[0].outcome == "home"
    assert all(e.odd is None and e.value_ratio is None for e in entries)


def test_value_bets_ranked_excludes_non_positive_value():
    # home has value_ratio 1.4 (value bet); draw/away are < 1 (not value bets)
    game = make_game(
        {"1x2": {"home": 0.70, "draw": 0.20, "away": 0.10}},
        {"1x2": {"home": 2.00, "draw": 3.0, "away": 5.0}},
    )
    compute_value_bets(game)
    ranked = game.value_bets_ranked
    assert len(ranked) == 1
    assert ranked[0].outcome == "home"
    assert all(v.is_value_bet for v in ranked)


def test_top_value_bets_today_sorts_across_games():
    strong = make_game(
        {"1x2": {"home": 0.7, "draw": 0.2, "away": 0.1}},
        {"1x2": {"home": 2.5, "draw": 4.0, "away": 8.0}},
    )
    weak = make_game(
        {"1x2": {"home": 0.5, "draw": 0.3, "away": 0.2}},
        {"1x2": {"home": 1.5, "draw": 3.0, "away": 5.0}},
    )
    compute_value_bets(strong)
    compute_value_bets(weak)
    top = top_value_bets_today([strong, weak], limit=1)
    assert len(top) == 1
    game, entry = top[0]
    assert game is strong
    assert entry.outcome == "home"


def test_top_probability_bets_today_includes_games_with_no_betclic_offer():
    # Unlike top_value_bets_today, this doesn't require a matched odd at
    # all -- a game with none (odds=None, e.g. no Betclic pairing) still
    # shows up here as long as its probability clears the threshold.
    with_odds = make_game(
        {"1x2": {"home": 0.55, "draw": 0.25, "away": 0.2}},
        {"1x2": {"home": 1.8, "draw": 3.5, "away": 4.0}},
        slug="with-odds",
        home="Team A",
        away="Team B",
    )
    no_offer = make_game(
        {"1x2": {"home": 0.9, "draw": 0.07, "away": 0.03}},
        None,
        slug="no-offer",
        home="Team C",
        away="Team D",
    )
    compute_value_bets(with_odds)
    compute_value_bets(no_offer)

    top = top_probability_bets_today([with_odds, no_offer], min_probability=0.5)
    by_game = {g.fixture.slug: e for g, e in top}

    assert "no-offer" in by_game
    assert by_game["no-offer"].odd is None
    assert by_game["no-offer"].value_ratio is None
    assert by_game["no-offer"].probability == pytest.approx(0.9)

    assert "with-odds" in by_game
    assert by_game["with-odds"].odd == pytest.approx(1.8)

    # Highest probability first, regardless of odds availability.
    assert list(by_game.values())[0].probability == pytest.approx(0.9)


def test_top_probability_bets_today_drops_uncoverable_odd_less_markets():
    # Real screenshot bug report: handicap/per-team-total lines that
    # config.yaml's betclic section has no extraction rule for at all
    # (permanently odd-less, not just "unmatched for this game") flooded
    # the top of this list at 100% probability. coverable_markets, once
    # given, drops those but keeps an odd-less entry for a market
    # Betclic *is* calibrated for (just not matched for this game).
    game = make_game(
        {
            "1x2": {"home": 0.9},  # coverable market, just unmatched here
            "handicap_home": {"-3": 0.99},  # not coverable at all
        },
        None,
    )
    compute_value_bets(game)

    top = top_probability_bets_today([game], min_probability=0.5, coverable_markets={"1x2", "btts"})
    assert [e.market for _, e in top] == ["1x2"]

    # Without coverable_markets (the default), nothing is dropped.
    top_unfiltered = top_probability_bets_today([game], min_probability=0.5)
    assert {e.market for _, e in top_unfiltered} == {"1x2", "handicap_home"}


def test_top_probability_bets_today_respects_threshold_and_limit():
    game = make_game(
        {"1x2": {"home": 0.7, "draw": 0.2, "away": 0.1}},
        {"1x2": {"home": 2.0, "draw": 4.0, "away": 8.0}},
    )
    compute_value_bets(game)

    # draw (0.2) and away (0.1) fall below a 0.5 threshold.
    top = top_probability_bets_today([game], min_probability=0.5)
    assert [e.outcome for _, e in top] == ["home"]

    # limit caps the result even when more entries clear the threshold.
    top_all = top_probability_bets_today([game], min_probability=0.0, limit=2)
    assert len(top_all) == 2


def test_top_probability_bets_today_max_probability_bounds_an_inclusive_band():
    # Explicitly requested: splitting into a high band (>=67%) and a
    # separate mid band (34%-66%), both bounds inclusive.
    game = make_game(
        {"1x2": {"home": 0.9, "draw": 0.55, "away": 0.1}},
        {"1x2": {"home": 1.5, "draw": 2.0, "away": 9.0}},
    )
    compute_value_bets(game)

    high = top_probability_bets_today([game], min_probability=0.67)
    assert [e.outcome for _, e in high] == ["home"]

    mid = top_probability_bets_today([game], min_probability=0.34, max_probability=0.66)
    assert [e.outcome for _, e in mid] == ["draw"]

    # Nothing below 0.34 shows up in either band -- "away" (0.1) is
    # excluded from both.
    assert not any(e.outcome == "away" for _, e in high + mid)


def test_top_probability_bets_today_buckets_by_displayed_rounded_percent():
    # A probability that *displays* as "67%" (0.669 rounds to 67) must
    # land in the high band even though its raw float is below 0.67 --
    # bucketing by the raw float alone would silently drop it from both
    # bands. See valuebets._rounded_percent.
    game = make_game(
        {"1x2": {"home": 0.669}},
        {"1x2": {"home": 1.5}},
    )
    compute_value_bets(game)

    high = top_probability_bets_today([game], min_probability=0.67)
    assert len(high) == 1

    mid = top_probability_bets_today([game], min_probability=0.34, max_probability=0.66)
    assert mid == []


def test_top_probability_bets_today_min_max_odd_bound_an_exclusive_range_and_require_an_odd():
    # Explicitly requested for the dashboard's high-confidence band:
    # "odd acima de 1.25 e abaixo de 1.45" -- both exclusive -- and,
    # unlike every other filter this function has, an odd becomes
    # REQUIRED once min_odd/max_odd are given: an odd-less entry (draw,
    # here) is dropped outright rather than kept with odd=None.
    game = make_game(
        {"1x2": {"home": 0.9, "draw": 0.9, "away": 0.9}},
        {"1x2": {"home": 1.35, "away": 1.45}},  # draw has no matched odd at all
    )
    compute_value_bets(game)

    in_range = top_probability_bets_today([game], min_probability=0.0, min_odd=1.25, max_odd=1.45)
    assert [e.outcome for _, e in in_range] == ["home"]

    # Exactly 1.45 (the boundary) is excluded -- max_odd is exclusive.
    assert not any(e.outcome == "away" for _, e in in_range)

    # Without min_odd/max_odd, nothing requires an odd at all -- all
    # three outcomes clear the (permissive) probability threshold.
    unfiltered = top_probability_bets_today([game], min_probability=0.0)
    assert {e.outcome for _, e in unfiltered} == {"home", "draw", "away"}


def test_top_probability_bets_today_odd_bounds_inclusive_flag():
    # Explicitly requested for the dashboard's mid-confidence band:
    # "odd superior a 1.5 e inferior a 2.2, inclusive para os 2" -- both
    # bounds inclusive this time, unlike the high band's exclusive ones
    # above. odd_bounds_inclusive=True switches > / < to >= / <=.
    game = make_game(
        {"1x2": {"home": 0.9, "draw": 0.9, "away": 0.9}},
        {"1x2": {"home": 1.5, "away": 2.2}},  # draw has no matched odd at all
    )
    compute_value_bets(game)

    exclusive = top_probability_bets_today(
        [game], min_probability=0.0, min_odd=1.5, max_odd=2.2, odd_bounds_inclusive=False
    )
    assert exclusive == []  # both boundary odds excluded

    inclusive = top_probability_bets_today(
        [game], min_probability=0.0, min_odd=1.5, max_odd=2.2, odd_bounds_inclusive=True
    )
    assert {e.outcome for _, e in inclusive} == {"home", "away"}
    # draw still excluded either way -- no matched odd at all.
    assert not any(e.outcome == "draw" for _, e in inclusive)


# --- Daily bet plan -----------------------------------------------------


def test_pick_multiple_legs_picks_higher_value_outcome_within_a_shared_fixture():
    # Two qualifying outcomes of the *same* match -- only the
    # higher-value_ratio one becomes a leg, never both (they aren't
    # independent, so combining both would misrepresent the combined
    # odds/probability below).
    two_candidates = make_game(
        # Both clear the default min_value_ratio=1.0 bar (1.008 and
        # 1.05) so the dedup logic itself -- not the value filter -- is
        # what's under test here.
        {"1x2": {"home": 0.72}, "btts": {"yes": 0.75}},
        {"1x2": {"home": 1.40}, "btts": {"yes": 1.40}},  # value_ratio: 1.008 vs 1.05
        slug="one-game",
        home="Team A",
        away="Team B",
    )
    other = make_game(
        {"1x2": {"home": 0.9}},
        {"1x2": {"home": 1.35}},  # value_ratio: 1.215
        slug="other-game",
        home="Team C",
        away="Team D",
    )
    compute_value_bets(two_candidates)
    compute_value_bets(other)

    legs = pick_multiple_legs([two_candidates, other], min_probability=0.7, min_odd=1.25, max_odd=1.45)
    assert len(legs) == 2
    assert len({g.fixture.id for g, _ in legs}) == 2
    one_game_leg = next(e for g, e in legs if g.fixture.slug == "one-game")
    assert one_game_leg.outcome == "yes"  # btts beats 1x2 home on value_ratio


def test_pick_multiple_legs_includes_every_qualifying_fixture_sorted_by_probability():
    # CHANGED (2026-09-29, explicitly requested): no more capping down to
    # a handful of legs -- every distinct-fixture candidate within the
    # band is included, sorted by probability descending (not
    # value_ratio, which only breaks ties *within* a shared fixture --
    # see the test above).
    game_72 = make_game(
        # odd 1.40 (not 1.30) so its value_ratio (1.008) still clears
        # the default min_value_ratio=1.0 bar -- this test is about
        # probability-sorting, not the value filter.
        {"1x2": {"home": 0.72}}, {"1x2": {"home": 1.40}}, slug="game-72", home="Team A", away="Team B"
    )
    game_90 = make_game(
        {"1x2": {"home": 0.9}}, {"1x2": {"home": 1.35}}, slug="game-90", home="Team C", away="Team D"
    )
    compute_value_bets(game_72)
    compute_value_bets(game_90)

    legs = pick_multiple_legs([game_72, game_90], min_probability=0.7, min_odd=1.25, max_odd=1.45)
    assert len(legs) == 2
    assert [g.fixture.slug for g, _ in legs] == ["game-90", "game-72"]


def test_pick_multiple_legs_returns_empty_when_nothing_qualifies():
    game = make_game({"1x2": {"home": 0.5}}, {"1x2": {"home": 1.3}})  # below min_probability
    compute_value_bets(game)
    assert pick_multiple_legs([game], min_probability=0.7, min_odd=1.25, max_odd=1.45) == []


def test_multiple_combined_odd_and_probability_multiply_across_legs():
    a = make_game({"1x2": {"home": 0.8}}, {"1x2": {"home": 1.3}}, slug="a", home="A1", away="A2")
    b = make_game({"1x2": {"home": 0.75}}, {"1x2": {"home": 1.4}}, slug="b", home="B1", away="B2")
    compute_value_bets(a)
    compute_value_bets(b)
    legs = [(a, a.value_bets[0]), (b, b.value_bets[0])]

    assert multiple_combined_odd(legs) == pytest.approx(1.3 * 1.4)
    assert multiple_combined_probability(legs) == pytest.approx(0.8 * 0.75)


def test_multiple_combined_odd_and_probability_are_none_for_empty_legs():
    assert multiple_combined_odd([]) is None
    assert multiple_combined_probability([]) is None


def test_pick_multiple_legs_requires_value_ratio_at_least_one_by_default():
    # Explicitly requested (2026-10-06): "nestas duas secções apenas
    # quero as apostas de valor maior ou igual a 1.00x" -- inclusive,
    # unlike the removed "apostas de valor" section's strict ">".
    below_one = make_game(
        {"1x2": {"home": 0.72}}, {"1x2": {"home": 1.30}}, slug="below-one"
    )  # value_ratio 0.936
    exactly_one = make_game(
        {"1x2": {"home": 0.8}}, {"1x2": {"home": 1.25000001}}, slug="exactly-one", home="A", away="B"
    )  # value_ratio ~1.0, deliberately just at the (exclusive) odd lower bound + epsilon
    above_one = make_game(
        {"1x2": {"home": 0.9}}, {"1x2": {"home": 1.35}}, slug="above-one", home="C", away="D"
    )  # value_ratio 1.215
    compute_value_bets(below_one)
    compute_value_bets(exactly_one)
    compute_value_bets(above_one)

    legs = pick_multiple_legs(
        [below_one, exactly_one, above_one], min_probability=0.7, min_odd=1.25, max_odd=1.45
    )
    assert "below-one" not in {g.fixture.slug for g, _ in legs}
    assert {g.fixture.slug for g, _ in legs} == {"exactly-one", "above-one"}

    # A higher bar excludes even the exactly-1.0-ish one.
    legs = pick_multiple_legs(
        [below_one, exactly_one, above_one],
        min_probability=0.7,
        min_odd=1.25,
        max_odd=1.45,
        min_value_ratio=1.1,
    )
    assert {g.fixture.slug for g, _ in legs} == {"above-one"}


def test_pick_band_bets_returns_every_entry_within_the_band_sorted_by_probability():
    # CHANGED (2026-09-29, explicitly requested): renamed from
    # pick_best_band_single, and returns every entry within the band
    # instead of narrowing to the single highest value_ratio one.
    # odd 1.65 (not 1.6) so its value_ratio (1.023) clears the default
    # min_value_ratio=1.0 bar -- this test is about probability-sorting
    # within the band, not the value filter (see the dedicated test
    # below for that).
    in_band_lower = make_game({"1x2": {"home": 0.62}}, {"1x2": {"home": 1.65}}, slug="in-band-lower")
    in_band_higher = make_game({"1x2": {"home": 0.65}}, {"1x2": {"home": 2.0}}, slug="in-band-higher")
    out_of_band = make_game({"1x2": {"home": 0.9}}, {"1x2": {"home": 1.3}}, slug="out-of-band")
    compute_value_bets(in_band_lower)
    compute_value_bets(in_band_higher)
    compute_value_bets(out_of_band)

    picks = pick_band_bets(
        [in_band_lower, in_band_higher, out_of_band],
        min_probability=0.6,
        max_probability=0.69,
        min_odd=1.5,
        max_odd=2.2,
    )
    assert [g.fixture.slug for g, _ in picks] == ["in-band-higher", "in-band-lower"]


def test_pick_band_bets_returns_empty_when_nothing_is_in_band():
    only_candidate = make_game({"1x2": {"home": 0.9}}, {"1x2": {"home": 1.6}}, slug="only")
    compute_value_bets(only_candidate)

    picks = pick_band_bets(
        [only_candidate], min_probability=0.6, max_probability=0.69, min_odd=1.5, max_odd=2.2
    )
    assert picks == []


def test_pick_band_bets_requires_value_ratio_at_least_one_by_default():
    # Explicitly requested (2026-10-06): same "maior ou igual a 1.00x"
    # bar as pick_multiple_legs, on top of this band's own
    # probability/odd range.
    in_band_below_one = make_game(
        {"1x2": {"home": 0.65}}, {"1x2": {"home": 1.5}}, slug="below-one"
    )  # value_ratio 0.975, within the band's own odd range (1.5-2.2 inclusive)
    in_band_above_one = make_game(
        {"1x2": {"home": 0.65}}, {"1x2": {"home": 1.6}}, slug="above-one", home="C", away="D"
    )  # value_ratio 1.04
    compute_value_bets(in_band_below_one)
    compute_value_bets(in_band_above_one)

    picks = pick_band_bets(
        [in_band_below_one, in_band_above_one],
        min_probability=0.6,
        max_probability=0.69,
        min_odd=1.5,
        max_odd=2.2,
    )
    assert [g.fixture.slug for g, _ in picks] == ["above-one"]


# --- calibration_buckets (explicitly requested 2026-11-14) ----------------


def test_compute_value_bets_uses_calibrated_probability_once_sample_size_is_enough():
    # Model says 70% for btts.yes, but 45 historical games at that same
    # band actually hit 85% -- value_ratio/edge should reflect the real
    # 85%, not the model's own 70%, once the bucket clears the sample
    # threshold (see calibration.calibrated_probability).
    game = make_game({"btts": {"yes": 0.70}}, {"btts": {"yes": 2.00}})
    buckets = [
        CalibrationBucket(market="btts", outcome="yes", probability_bucket="70-79%", count=45, hits=38, avg_predicted_probability=0.70)
    ]

    entries = compute_value_bets(game, calibration_buckets=buckets)
    entry = entries[0]

    assert entry.probability == pytest.approx(0.70)  # raw model number untouched
    assert entry.calibrated_probability == pytest.approx(38 / 45)
    assert entry.calibration_sample_size == 45
    assert entry.effective_probability == pytest.approx(38 / 45)
    assert entry.value_ratio == pytest.approx((38 / 45) * 2.00)
    assert entry.value_ratio != pytest.approx(0.70 * 2.00)


def test_compute_value_bets_falls_back_to_raw_probability_below_sample_threshold():
    # Same band, but only 5 games behind it -- too few to trust, so the
    # model's own raw probability is used, exactly as if no calibration
    # data had been passed at all.
    game = make_game({"btts": {"yes": 0.70}}, {"btts": {"yes": 2.00}})
    buckets = [
        CalibrationBucket(market="btts", outcome="yes", probability_bucket="70-79%", count=5, hits=4, avg_predicted_probability=0.70)
    ]

    entries = compute_value_bets(game, calibration_buckets=buckets)
    entry = entries[0]

    assert entry.calibrated_probability is None
    assert entry.calibration_sample_size is None
    assert entry.effective_probability == pytest.approx(0.70)
    assert entry.value_ratio == pytest.approx(0.70 * 2.00)


def test_compute_value_bets_with_no_calibration_buckets_behaves_exactly_as_before():
    game = make_game({"1x2": {"home": 0.70}}, {"1x2": {"home": 2.00}})
    entries = compute_value_bets(game)  # no calibration_buckets argument at all
    assert entries[0].calibrated_probability is None
    assert entries[0].value_ratio == pytest.approx(1.4)


# --- compute_real_rate_value_bets / "apostas por taxa real" (2026-11-17) --


def test_compute_real_rate_value_bets_uses_a_band_below_the_30_game_production_threshold():
    # Same band as test_compute_value_bets_falls_back_to_raw_probability_below_sample_threshold
    # (only 5 games) -- compute_value_bets leaves calibrated_probability
    # None there, but compute_real_rate_value_bets (no minimum sample
    # size at all) should surface it anyway, for the "apostas por taxa
    # real" page which explicitly wants to show provisional bands too.
    game = make_game({"btts": {"yes": 0.70}}, {"btts": {"yes": 2.00}})
    buckets = [
        CalibrationBucket(market="btts", outcome="yes", probability_bucket="70-79%", count=5, hits=4, avg_predicted_probability=0.70)
    ]

    entries = compute_real_rate_value_bets(game, buckets)
    entry = entries[0]

    assert entry.probability == pytest.approx(0.70)  # raw model number untouched
    assert entry.calibrated_probability == pytest.approx(4 / 5)
    assert entry.calibration_sample_size == 5
    assert entry.value_ratio == pytest.approx((4 / 5) * 2.00)

    # game.value_bets (the model-probability page) is untouched -- still
    # has calibrated_probability=None, since compute_value_bets was never
    # called on this game at all.
    assert game.value_bets == []


def test_compute_real_rate_value_bets_has_none_for_a_band_with_no_history_at_all():
    game = make_game({"1x2": {"home": 0.70}}, {"1x2": {"home": 2.00}})
    entries = compute_real_rate_value_bets(game, calibration_buckets=[])
    assert entries[0].calibrated_probability is None
    assert entries[0].calibration_sample_size is None


def test_top_probability_bets_today_probability_of_ranks_by_a_different_field():
    # home has the higher model probability (0.9) but a lower
    # "calibrated_probability" (0.3) stashed on the entry -- probability_of
    # lets a caller rank/filter by that instead.
    game = make_game({"1x2": {"home": 0.9, "away": 0.2}}, {"1x2": {"home": 1.5, "away": 3.0}})
    entries = compute_value_bets(game)
    home = next(e for e in entries if e.outcome == "home")
    away = next(e for e in entries if e.outcome == "away")
    home.calibrated_probability = 0.3
    away.calibrated_probability = 0.8

    by_model = top_probability_bets_today([game], min_probability=0.0)
    assert by_model[0][1].outcome == "home"  # default: ranks by raw probability

    by_calibrated = top_probability_bets_today(
        [game], min_probability=0.0, probability_of=lambda e: e.calibrated_probability
    )
    assert by_calibrated[0][1].outcome == "away"  # ranks by calibrated_probability instead


def test_top_probability_bets_today_probability_of_skips_entries_with_none():
    # An entry whose probability_of comes back None (no historical band
    # at all) is dropped outright, never silently falling back to
    # another number.
    game = make_game({"1x2": {"home": 0.9, "away": 0.8}}, {"1x2": {"home": 1.5, "away": 3.0}})
    entries = compute_value_bets(game)
    next(e for e in entries if e.outcome == "home").calibrated_probability = 0.5
    # "away" keeps calibrated_probability=None (never calibrated)

    picks = top_probability_bets_today(
        [game], min_probability=0.0, probability_of=lambda e: e.calibrated_probability
    )
    assert [e.outcome for _, e in picks] == ["home"]


def test_pick_multiple_legs_entries_of_uses_a_different_per_game_entry_list():
    # entries_of lets a caller supply an entirely different list of
    # entries per game (e.g. compute_real_rate_value_bets's output)
    # instead of game.value_bets.
    game = make_game({"1x2": {"home": 0.9}}, {"1x2": {"home": 1.3}}, slug="g")
    model_entries = compute_value_bets(game)
    real_entries = compute_real_rate_value_bets(game, calibration_buckets=[])
    # Mutate the "real" entries' calibrated_probability directly, as if a
    # calibration bucket had set it, to make the two entry lists diverge.
    real_entries[0].calibrated_probability = 0.95
    real_entries[0].value_ratio = 0.95 * 1.3

    legs = pick_multiple_legs(
        [game],
        min_probability=0.9,
        min_odd=1.25,
        max_odd=1.45,
        probability_of=lambda e: e.calibrated_probability,
        entries_of=lambda g: real_entries,
    )
    assert len(legs) == 1
    assert legs[0][1] is real_entries[0]
    assert legs[0][1] not in model_entries


def test_top_probability_bets_today_tiebreak_of_breaks_a_probability_tie():
    # Real case (2026-11-18): three entries tied at exactly the same
    # calibrated_probability -- without a tiebreak, which one ends up
    # first is just an accident of insertion order. tiebreak_of lets a
    # caller decide: here, higher calibration_sample_size wins the tie.
    game = make_game(
        {"1x2": {"home": 0.72}, "btts": {"yes": 0.61}, "double_chance": {"1x": 0.84}},
        {"1x2": {"home": 1.3}, "btts": {"yes": 1.3}, "double_chance": {"1x": 1.3}},
    )
    entries = compute_value_bets(game)
    for e in entries:
        e.calibrated_probability = 0.80  # tied on the ranking field
    home = next(e for e in entries if e.outcome == "home")
    yes = next(e for e in entries if e.outcome == "yes")
    onex = next(e for e in entries if e.outcome == "1x")
    home.calibration_sample_size = 5
    yes.calibration_sample_size = 12
    onex.calibration_sample_size = 5
    home.probability, yes.probability, onex.probability = 0.72, 0.61, 0.84

    picks = top_probability_bets_today(
        [game],
        min_probability=0.0,
        probability_of=lambda e: e.calibrated_probability,
        tiebreak_of=lambda e: (e.calibration_sample_size or 0, e.probability),
    )
    # "yes" has the highest sample size (12) -- wins outright.
    assert picks[0][1].outcome == "yes"
    # "home" and "1x" both have sample_size=5 -- next tiebreak is model
    # probability, where "1x" (0.84) beats "home" (0.72).
    assert picks[1][1].outcome == "1x"
    assert picks[2][1].outcome == "home"


def test_top_probability_bets_today_without_tiebreak_of_behaves_as_before():
    # Omitting tiebreak_of must not change anything for every existing
    # caller (report.build_context, every test above this one).
    game = make_game({"1x2": {"home": 0.9, "away": 0.1}}, {"1x2": {"home": 1.3, "away": 1.3}})
    compute_value_bets(game)
    picks = top_probability_bets_today([game], min_probability=0.0)
    assert [e.outcome for _, e in picks] == ["home", "away"]


def test_pick_multiple_legs_tiebreak_of_decides_which_fixture_wins_a_shared_slot():
    # Three different fixtures tied at the same real rate and sample
    # size -- the model probability tiebreak decides their relative
    # order (used when a caller later caps the leg count).
    a = make_game({"1x2": {"home": 0.60}}, {"1x2": {"home": 1.3}}, slug="a", home="A1", away="A2")
    b = make_game({"1x2": {"home": 0.95}}, {"1x2": {"home": 1.3}}, slug="b", home="B1", away="B2")
    c = make_game({"1x2": {"home": 0.75}}, {"1x2": {"home": 1.3}}, slug="c", home="C1", away="C2")
    for g in (a, b, c):
        compute_value_bets(g)
        g.value_bets[0].calibrated_probability = 0.80
        g.value_bets[0].calibration_sample_size = 5
        g.value_bets[0].value_ratio = 0.80 * g.value_bets[0].odd  # keep it >= min_value_ratio

    legs = pick_multiple_legs(
        [a, b, c],
        min_probability=0.70,
        min_odd=1.25,
        max_odd=1.45,
        probability_of=lambda e: e.calibrated_probability,
        tiebreak_of=lambda e: (e.calibration_sample_size or 0, e.probability),
    )
    assert [g.fixture.slug for g, _ in legs] == ["b", "c", "a"]


def test_multiple_combined_probability_with_probability_of_override():
    a = make_game({"1x2": {"home": 0.8}}, {"1x2": {"home": 1.3}}, slug="a", home="A1", away="A2")
    b = make_game({"1x2": {"home": 0.75}}, {"1x2": {"home": 1.4}}, slug="b", home="B1", away="B2")
    compute_value_bets(a)
    compute_value_bets(b)
    a.value_bets[0].calibrated_probability = 0.9
    b.value_bets[0].calibrated_probability = 0.6
    legs = [(a, a.value_bets[0]), (b, b.value_bets[0])]

    assert multiple_combined_probability(legs) == pytest.approx(0.8 * 0.75)  # default: raw probability
    assert multiple_combined_probability(
        legs, probability_of=lambda e: e.calibrated_probability
    ) == pytest.approx(0.9 * 0.6)
