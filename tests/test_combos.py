from datetime import datetime

import pytest

from tipsxgs.combos import compute_combo_entries
from tipsxgs.models import Fixture, MatchedGame, Prediction


def make_game(markets_prob, slug="union-berlin-schalke", home="Union Berlin", away="Schalke"):
    fixture = Fixture(
        slug=slug,
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=datetime(2026, 9, 11, 18, 0),
        preview_url=f"https://xgscore.io/bundesliga/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets_prob) if markets_prob is not None else None
    return MatchedGame(fixture=fixture, prediction=prediction, odds=None, match_confidence=None)


def test_combo_entries_are_products_of_independent_markets():
    game = make_game(
        {
            "double_chance": {"1x": 0.6, "12": 0.75, "x2": 0.55},
            "1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "over_under_2.5": {"over": 0.6, "under": 0.4},
        }
    )
    entries = compute_combo_entries(game)

    dc_over = next(e for e in entries if e.market == "double_chance_total_2.5" and e.outcome == "1x_over")
    assert dc_over.probability == pytest.approx(0.6 * 0.6)
    assert dc_over.label == "1X & Mais de 2.5"
    assert dc_over.odd is None
    assert dc_over.value_ratio is None

    result_under = next(e for e in entries if e.market == "result_total_2.5" and e.outcome == "home_under")
    assert result_under.probability == pytest.approx(0.5 * 0.4)
    assert result_under.label == "Casa & Menos de 2.5"


def test_combo_entries_exclude_draw_from_result_total_combo():
    game = make_game(
        {
            "1x2": {"home": 0.5, "draw": 0.25, "away": 0.25},
            "over_under_2.5": {"over": 0.6, "under": 0.4},
        }
    )
    entries = compute_combo_entries(game)
    assert all(e.outcome.split("_")[0] != "draw" for e in entries if e.market.startswith("result_total_"))


def test_combo_entries_cover_every_over_under_line():
    game = make_game(
        {
            "double_chance": {"1x": 0.6},
            "over_under_1.5": {"over": 0.8, "under": 0.2},
            "over_under_2.5": {"over": 0.6, "under": 0.4},
        }
    )
    entries = compute_combo_entries(game)
    lines = {e.market for e in entries}
    assert lines == {"double_chance_total_1.5", "double_chance_total_2.5"}


def test_combo_entries_sorted_by_probability_descending():
    game = make_game(
        {
            "double_chance": {"1x": 0.6, "12": 0.9},
            "over_under_2.5": {"over": 0.6, "under": 0.4},
        }
    )
    entries = compute_combo_entries(game)
    probs = [e.probability for e in entries]
    assert probs == sorted(probs, reverse=True)


def test_combo_entries_empty_when_no_prediction():
    game = make_game(None)
    assert compute_combo_entries(game) == []


def test_combo_entries_empty_when_missing_double_chance_and_1x2():
    game = make_game({"over_under_2.5": {"over": 0.6, "under": 0.4}})
    assert compute_combo_entries(game) == []


def test_combo_entries_empty_when_no_over_under_lines():
    game = make_game({"double_chance": {"1x": 0.6}, "1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}})
    assert compute_combo_entries(game) == []
