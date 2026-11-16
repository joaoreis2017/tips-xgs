from datetime import datetime

import pytest

from tipsxgs.calibration import (
    CalibrationBucket,
    actual_outcome_hit,
    calibrated_probability,
    compute_calibration,
    load_accumulated_calibration,
    match_games_to_results,
)
from tipsxgs.models import Fixture, MatchedGame, MatchResult, ValueBetEntry
from tipsxgs.storage import save_day, save_results


def make_game(value_bets, slug="union-berlin-schalke", home="Union Berlin", away="Schalke", kickoff=None):
    fixture = Fixture(
        slug=slug,
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=kickoff or datetime(2026, 9, 11, 18, 0),
        preview_url=f"https://xgscore.io/bundesliga/{slug}/preview",
    )
    return MatchedGame(fixture=fixture, prediction=None, odds=None, value_bets=value_bets)


def make_result(home="Union Berlin", away="Schalke", home_goals=2, away_goals=1, kickoff=None):
    return MatchResult(
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=kickoff or datetime(2026, 9, 11, 18, 0),
        home_goals=home_goals,
        away_goals=away_goals,
    )


# --- actual_outcome_hit ---------------------------------------------------


def test_actual_outcome_hit_1x2():
    assert actual_outcome_hit("1x2", "home", 2, 1) is True
    assert actual_outcome_hit("1x2", "away", 2, 1) is False
    assert actual_outcome_hit("1x2", "draw", 1, 1) is True


def test_actual_outcome_hit_double_chance_excludes_draw_correctly():
    # 1x2 result is "home" (2-1) -- 1x and 12 cover it, x2 doesn't.
    assert actual_outcome_hit("double_chance", "1x", 2, 1) is True
    assert actual_outcome_hit("double_chance", "12", 2, 1) is True
    assert actual_outcome_hit("double_chance", "x2", 2, 1) is False


def test_actual_outcome_hit_btts():
    assert actual_outcome_hit("btts", "yes", 1, 1) is True
    assert actual_outcome_hit("btts", "no", 1, 1) is False
    assert actual_outcome_hit("btts", "no", 0, 2) is True


def test_actual_outcome_hit_over_under_respects_the_line():
    assert actual_outcome_hit("over_under_2.5", "over", 2, 1) is True  # 3 > 2.5
    assert actual_outcome_hit("over_under_2.5", "under", 2, 1) is False
    assert actual_outcome_hit("over_under_3.5", "over", 2, 1) is False  # 3 < 3.5
    assert actual_outcome_hit("over_under_3.5", "under", 2, 1) is True


def test_actual_outcome_hit_per_team_totals_are_judged_independently_of_match_total():
    # home_goals=2, away_goals=1 (total 3) -- home_total/away_total look
    # only at that one side's own goals, a *different* market from
    # over_under (whole-match total) above.
    assert actual_outcome_hit("home_total_1.5", "over", 2, 1) is True  # 2 > 1.5
    assert actual_outcome_hit("home_total_1.5", "under", 2, 1) is False
    assert actual_outcome_hit("away_total_1.5", "over", 2, 1) is False  # 1 < 1.5
    assert actual_outcome_hit("away_total_1.5", "under", 2, 1) is True
    # Sanity: the match-total market at the same line still looks at
    # home+away combined (3), not either side alone.
    assert actual_outcome_hit("over_under_1.5", "over", 2, 1) is True


def test_actual_outcome_hit_unknown_market_returns_none():
    # A handicap/correct-score style market can't be judged from the
    # score alone with the information available here.
    assert actual_outcome_hit("handicap_home", "-1.5", 2, 1) is None
    assert actual_outcome_hit("correct_score", "2-1", 2, 1) is None


# --- match_games_to_results -----------------------------------------------


def test_match_games_to_results_pairs_by_team_name_and_date():
    game = make_game([])
    other_day_result = make_result(kickoff=datetime(2026, 9, 12, 18, 0))  # different day -- shouldn't match
    real_result = make_result()

    paired = match_games_to_results([game], [other_day_result, real_result])
    assert len(paired) == 1
    assert paired[0] == (game, real_result)


def test_match_games_to_results_drops_games_with_no_good_candidate():
    game = make_game([], home="Union Berlin", away="Schalke")
    unrelated_result = make_result(home="Real Madrid", away="Barcelona")
    assert match_games_to_results([game], [unrelated_result]) == []


# --- compute_calibration ---------------------------------------------------


def test_compute_calibration_pools_multiple_games_of_the_same_exact_market_and_outcome():
    game_a = make_game(
        [ValueBetEntry(market="over_under_2.5", outcome="over", label="x", probability=0.9)],
        slug="game-a",
    )
    game_b = make_game(
        [ValueBetEntry(market="over_under_2.5", outcome="over", label="x", probability=0.91)],
        slug="game-b",
        home="A",
        away="B",
    )
    result_a = make_result(home_goals=2, away_goals=1)  # total 3 -- hit
    result_b = make_result(home="A", away="B", home_goals=2, away_goals=1)  # total 3 -- hit

    buckets = compute_calibration([(game_a, result_a), (game_b, result_b)])

    # Same exact market, same outcome, same decile -- pooled into one row.
    assert len(buckets) == 1
    assert buckets[0].market == "over_under_2.5"
    assert buckets[0].outcome == "over"
    assert buckets[0].probability_bucket == "90-99%"
    assert buckets[0].count == 2
    assert buckets[0].hits == 2
    assert buckets[0].avg_predicted_probability == pytest.approx((0.9 + 0.91) / 2)


def test_compute_calibration_keeps_different_lines_of_over_under_fully_separate():
    # Explicitly requested (2026-11-14, taken further): over_under_1.5
    # must NEVER be pooled with over_under_2.5, even for the same
    # outcome word and even if both probabilities land in the same
    # decile -- each exact line is tracked on its own.
    game = make_game(
        [
            ValueBetEntry(market="over_under_1.5", outcome="over", label="x", probability=0.85),  # hit
            ValueBetEntry(market="over_under_2.5", outcome="over", label="y", probability=0.82),  # hit
            ValueBetEntry(market="over_under_3.5", outcome="over", label="z", probability=0.05),  # miss, total 3 < 3.5
        ]
    )
    result = make_result(home_goals=2, away_goals=1)  # total 3
    buckets = compute_calibration([(game, result)])

    by_market = {b.market: b for b in buckets}
    assert set(by_market) == {"over_under_1.5", "over_under_2.5", "over_under_3.5"}
    assert by_market["over_under_1.5"].count == 1
    assert by_market["over_under_2.5"].count == 1
    assert by_market["over_under_3.5"].count == 1
    assert by_market["over_under_1.5"].hits == 1
    assert by_market["over_under_2.5"].hits == 1
    assert by_market["over_under_3.5"].hits == 0


def test_compute_calibration_keeps_over_separate_from_under_at_the_same_line():
    game = make_game(
        [
            ValueBetEntry(market="over_under_2.5", outcome="over", label="x", probability=0.55),
            ValueBetEntry(market="over_under_2.5", outcome="under", label="y", probability=0.45),
        ]
    )
    result = make_result(home_goals=2, away_goals=1)  # total 3 -- "over" hits, "under" misses
    buckets = compute_calibration([(game, result)])

    by_outcome = {b.outcome: b for b in buckets}
    assert set(by_outcome) == {"over", "under"}
    assert by_outcome["over"].hits == 1
    assert by_outcome["under"].hits == 0


def test_compute_calibration_keeps_home_wins_separate_from_away_wins():
    # Explicitly requested: 1x2's home/draw/away outcomes must each get
    # their own row, never pooled together.
    game = make_game(
        [
            ValueBetEntry(market="1x2", outcome="home", label="x", probability=0.7),  # hit
            ValueBetEntry(market="1x2", outcome="draw", label="y", probability=0.2),  # miss
            ValueBetEntry(market="1x2", outcome="away", label="z", probability=0.1),  # miss
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])

    by_outcome = {b.outcome: b for b in buckets}
    assert set(by_outcome) == {"home", "draw", "away"}
    assert by_outcome["home"].hits == 1
    assert by_outcome["draw"].hits == 0
    assert by_outcome["away"].hits == 0


def test_compute_calibration_keeps_home_total_separate_from_away_total_per_line():
    # Explicitly requested: each team's own total, at each line, is its
    # own row -- home_total_1.5.over never pooled with
    # away_total_1.5.over, nor with home_total_0.5.over.
    game = make_game(
        [
            ValueBetEntry(market="home_total_0.5", outcome="over", label="x", probability=0.95),  # home 2 > 0.5: hit
            ValueBetEntry(market="home_total_1.5", outcome="over", label="y", probability=0.6),  # home 2 > 1.5: hit
            ValueBetEntry(market="away_total_1.5", outcome="over", label="z", probability=0.6),  # away 1 < 1.5: miss
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])

    by_market = {b.market: b for b in buckets}
    assert set(by_market) == {"home_total_0.5", "home_total_1.5", "away_total_1.5"}
    assert by_market["home_total_0.5"].hits == 1
    assert by_market["home_total_1.5"].hits == 1
    assert by_market["away_total_1.5"].hits == 0


def test_compute_calibration_keeps_1x_separate_from_x2_and_excludes_12():
    # Explicitly requested: double_chance's "1x" and "x2" tracked
    # separately, and "12" dropped entirely (never bet on it).
    game = make_game(
        [
            ValueBetEntry(market="double_chance", outcome="1x", label="x", probability=0.85),  # covers home: hit
            ValueBetEntry(market="double_chance", outcome="x2", label="y", probability=0.35),  # doesn't cover home: miss
            ValueBetEntry(market="double_chance", outcome="12", label="z", probability=0.95),  # excluded entirely
        ]
    )
    result = make_result(home_goals=2, away_goals=1)  # actual: home
    buckets = compute_calibration([(game, result)])

    by_outcome = {b.outcome: b for b in buckets}
    assert set(by_outcome) == {"1x", "x2"}  # "12" never shows up at all
    assert by_outcome["1x"].hits == 1
    assert by_outcome["x2"].hits == 0


def test_compute_calibration_keeps_per_team_totals_separate_from_match_total():
    # Explicitly requested: over/under for the whole match must NOT be
    # pooled together with either team's own individual total.
    game = make_game(
        [
            ValueBetEntry(market="over_under_1.5", outcome="over", label="x", probability=0.9),  # total 3 > 1.5: hit
            ValueBetEntry(market="home_total_1.5", outcome="under", label="x", probability=0.4),  # home 2, miss
            ValueBetEntry(market="away_total_0.5", outcome="over", label="x", probability=0.5),  # away 1 > 0.5: hit
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])

    by_market = {b.market: b for b in buckets}
    assert set(by_market) == {"over_under_1.5", "home_total_1.5", "away_total_0.5"}
    assert by_market["over_under_1.5"].hits == 1
    assert by_market["home_total_1.5"].hits == 0
    assert by_market["away_total_0.5"].hits == 1


def test_compute_calibration_ignores_unjudgeable_markets():
    game = make_game([ValueBetEntry(market="handicap_home", outcome="-1.5", label="x", probability=0.7)])
    result = make_result()
    assert compute_calibration([(game, result)]) == []


def test_compute_calibration_excludes_whole_number_lines():
    # Explicitly requested (2026-11-16): only half-integer lines (0.5,
    # 1.5, 2.5, ...) are tracked -- a whole-number line (1, 2, 3, ...)
    # is never bet on and is dropped entirely, same treatment as
    # double_chance's "12".
    game = make_game(
        [
            ValueBetEntry(market="over_under_2", outcome="over", label="x", probability=0.7),  # whole number: excluded
            ValueBetEntry(market="over_under_2.5", outcome="over", label="y", probability=0.6),  # half-integer: kept
            ValueBetEntry(market="home_total_1", outcome="over", label="z", probability=0.8),  # whole number: excluded
            ValueBetEntry(market="home_total_1.5", outcome="over", label="w", probability=0.55),  # half-integer: kept
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])
    assert {b.market for b in buckets} == {"over_under_2.5", "home_total_1.5"}


def test_compute_calibration_buckets_by_probability_decile():
    game = make_game(
        [
            ValueBetEntry(market="1x2", outcome="home", label="x", probability=0.75),  # hit, bucket 70-79%
            ValueBetEntry(market="1x2", outcome="away", label="y", probability=0.15),  # miss, bucket 10-19%
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])

    by_bucket = {b.probability_bucket: b for b in buckets}
    assert by_bucket["70-79%"].hits == 1
    assert by_bucket["70-79%"].count == 1
    assert by_bucket["10-19%"].hits == 0
    assert by_bucket["10-19%"].count == 1


def test_compute_calibration_sorted_by_market_outcome_then_probability_descending():
    # Explicitly requested: within a market+outcome, the highest-
    # confidence band should read first ("é mais seguro apostar quando
    # a prob está acima de X%" is read top-down). Same exact
    # market+outcome ("over_under_1.5"/"over") across three entries at
    # three different probabilities, to check the ordering within one
    # group (a real game only ever has one such entry; using three
    # here is purely to exercise the sort).
    game = make_game(
        [
            ValueBetEntry(market="over_under_1.5", outcome="over", label="x", probability=0.85),
            ValueBetEntry(market="over_under_1.5", outcome="over", label="y", probability=0.15),
            ValueBetEntry(market="over_under_1.5", outcome="over", label="z", probability=0.05),
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    buckets = compute_calibration([(game, result)])
    assert [b.probability_bucket for b in buckets] == ["80-89%", "10-19%", "00-09%"]


def test_compute_calibration_does_not_pool_a_hit_rate_across_bands():
    # The whole point of this redesign (explicitly reported as the
    # earlier compute_market_family_summary not making sense): no
    # single aggregate hit-rate across every band is returned anywhere
    # -- only per-band rows, so nothing here can be pooled back into a
    # tautological ~1/n-outcomes constant by a caller.
    game = make_game(
        [
            ValueBetEntry(market="btts", outcome="yes", label="x", probability=0.5),
            ValueBetEntry(market="btts", outcome="no", label="y", probability=0.5),
        ]
    )
    result = make_result(home_goals=1, away_goals=1)  # btts yes
    buckets = compute_calibration([(game, result)])
    # "yes" and "no" are also kept as separate outcomes now, on top of
    # landing in the same "50-59%" band.
    by_outcome = {b.outcome: b for b in buckets}
    assert set(by_outcome) == {"yes", "no"}
    assert by_outcome["yes"].count == 1
    assert by_outcome["yes"].hits == 1
    assert by_outcome["no"].count == 1
    assert by_outcome["no"].hits == 0


def test_compute_calibration_empty_when_nothing_paired():
    assert compute_calibration([]) == []


# --- calibrated_probability -------------------------------------------------


def test_calibrated_probability_returns_the_bucket_once_sample_size_is_enough():
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=27, avg_predicted_probability=0.83)
    ]
    prob, count = calibrated_probability("over_under_1.5", "over", 0.85, buckets, min_sample_size=30)
    assert prob == pytest.approx(27 / 30)
    assert count == 30


def test_calibrated_probability_none_below_sample_size():
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=29, hits=27, avg_predicted_probability=0.83)
    ]
    assert calibrated_probability("over_under_1.5", "over", 0.85, buckets, min_sample_size=30) == (None, None)


def test_calibrated_probability_none_when_bucket_missing_entirely():
    assert calibrated_probability("over_under_1.5", "over", 0.85, [], min_sample_size=30) == (None, None)


def test_calibrated_probability_does_not_match_a_different_outcome():
    # A bucket computed for "over" must never answer a lookup for
    # "under", even at the exact same market+band.
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=24, avg_predicted_probability=0.83)
    ]
    assert calibrated_probability("over_under_1.5", "under", 0.85, buckets, min_sample_size=30) == (None, None)


def test_calibrated_probability_does_not_match_a_different_line():
    # Explicitly requested: a bucket computed for over_under_1.5 must
    # NEVER answer a lookup for over_under_2.5, even same outcome/band
    # -- each line is tracked (and looked up) completely separately now.
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=24, avg_predicted_probability=0.83)
    ]
    assert calibrated_probability("over_under_2.5", "over", 0.81, buckets, min_sample_size=30) == (None, None)


# --- load_accumulated_calibration -------------------------------------------


def test_load_accumulated_calibration_reads_every_saved_day(tmp_path):
    day1 = make_game(
        [ValueBetEntry(market="1x2", outcome="home", label="x", probability=0.75)],
        slug="game-day1",
        kickoff=datetime(2026, 9, 10, 18, 0),
    )
    result1 = make_result(home_goals=2, away_goals=1, kickoff=datetime(2026, 9, 10, 18, 0))
    save_day(datetime(2026, 9, 10).date(), [day1], tmp_path)
    save_results(datetime(2026, 9, 10).date(), [result1], tmp_path)

    day2 = make_game(
        [ValueBetEntry(market="1x2", outcome="home", label="x", probability=0.78)],
        slug="game-day2",
        kickoff=datetime(2026, 9, 11, 18, 0),
    )
    result2 = make_result(home_goals=2, away_goals=1, kickoff=datetime(2026, 9, 11, 18, 0))
    save_day(datetime(2026, 9, 11).date(), [day2], tmp_path)
    save_results(datetime(2026, 9, 11).date(), [result2], tmp_path)

    buckets = load_accumulated_calibration(tmp_path)
    by_bucket = {b.probability_bucket: b for b in buckets}
    assert by_bucket["70-79%"].count == 2  # both days' entries pooled into the same band


def test_load_accumulated_calibration_empty_dir_returns_empty(tmp_path):
    assert load_accumulated_calibration(tmp_path) == []
