from tipsxgs.extract import normalize_probabilities, parse_odds
from tipsxgs.markets import full_label, merge_markets, normalize_markets


def test_normalize_markets_maps_raw_keys_via_alias():
    raw = {"prob_home_win": 0.62, "prob_draw": 0.24, "unrelated_field": 5}
    alias = {"prob_home_win": "1x2.home", "prob_draw": "1x2.draw"}
    result = normalize_markets(raw, alias)
    assert result == {"1x2": {"home": 0.62, "draw": 0.24}}


def test_normalize_probabilities_converts_percentages():
    assert normalize_probabilities({"a": 62, "b": 0.24, "c": None}) == {"a": 0.62, "b": 0.24}


def test_parse_odds_keeps_numeric_only():
    assert parse_odds({"a": "2.50", "b": "2,50", "c": "n/a", "d": 3}) == {"a": 2.5, "b": 2.5, "d": 3.0}


def test_full_label_uses_known_pt_labels():
    assert full_label("1x2", "home") == "Resultado Final - Casa"
    assert full_label("btts", "yes") == "Ambas Marcam - Sim"


def test_full_label_falls_back_gracefully_for_unknown_market():
    assert full_label("some_new_market", "weird_outcome") == "Some New Market - Weird Outcome"


def test_merge_markets_combines_without_losing_data():
    a = {"1x2": {"home": 0.5}}
    b = {"1x2": {"away": 0.3}, "btts": {"yes": 0.6}}
    merged = merge_markets(a, b)
    assert merged == {"1x2": {"home": 0.5, "away": 0.3}, "btts": {"yes": 0.6}}
