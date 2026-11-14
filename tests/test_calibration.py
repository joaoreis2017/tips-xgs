from datetime import datetime

import pytest

from tipsxgs.calibration import (
    actual_outcome_hit,
    compute_calibration,
    compute_market_family_summary,
    match_games_to_results,
)
from tipsxgs.models import Fixture, MatchedGame, MatchResult, ValueBetEntry


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
    # only at that one side's own goals, a *different* market family
    # from over_under (whole-match total) above.
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


# --- compute_market_family_summary / compute_calibration ------------------


def test_compute_market_family_summary_pools_across_lines_into_one_family():
    game = make_game(
        [
            ValueBetEntry(market="over_under_1.5", outcome="over", label="x", probability=0.9),
            ValueBetEntry(market="over_under_2.5", outcome="over", label="x", probability=0.6),
        ]
    )
    result = make_result(home_goals=2, away_goals=1)  # total 3 -- both "over" bets hit
    paired = [(game, result)]

    summary = compute_market_family_summary(paired)
    assert len(summary) == 1
    assert summary[0].market_family == "over_under"
    assert summary[0].count == 2
    assert summary[0].hits == 2
    assert summary[0].hit_rate == pytest.approx(1.0)
    assert summary[0].avg_predicted_probability == pytest.approx((0.9 + 0.6) / 2)


def test_compute_market_family_summary_sorted_by_hit_rate_descending():
    game = make_game(
        [
            ValueBetEntry(market="1x2", outcome="away", label="x", probability=0.3),  # miss (actual: home)
            ValueBetEntry(market="btts", outcome="yes", label="x", probability=0.5),  # hit
        ]
    )
    result = make_result(home_goals=2, away_goals=1)
    summary = compute_market_family_summary([(game, result)])
    assert [s.market_family for s in summary] == ["btts", "1x2"]


def test_compute_market_family_summary_keeps_per_team_totals_separate_from_match_total():
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
    summary = compute_market_family_summary([(game, result)])

    by_family = {s.market_family: s for s in summary}
    assert set(by_family) == {"over_under", "home_total", "away_total"}
    assert by_family["over_under"].hits == 1
    assert by_family["home_total"].hits == 0
    assert by_family["away_total"].hits == 1


def test_compute_market_family_summary_ignores_unjudgeable_markets():
    game = make_game([ValueBetEntry(market="handicap_home", outcome="-1.5", label="x", probability=0.7)])
    result = make_result()
    assert compute_market_family_summary([(game, result)]) == []


def test_compute_calibration_buckets_by_market_and_probability_decile():
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


def test_compute_calibration_empty_when_nothing_paired():
    assert compute_calibration([]) == []
    assert compute_market_family_summary([]) == []
