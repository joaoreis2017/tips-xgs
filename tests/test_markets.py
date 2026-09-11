from tipsxgs.extract import normalize_probabilities, parse_odds
from tipsxgs.markets import full_label, merge_markets, normalize_markets


def test_normalize_markets_maps_raw_keys_via_alias():
    raw = {"prob_home_win": 0.62, "prob_draw": 0.24, "unrelated_field": 5}
    alias = {"prob_home_win": "1x2.home", "prob_draw": "1x2.draw"}
    result = normalize_markets(raw, alias)
    assert result == {"1x2": {"home": 0.62, "draw": 0.24}}


def test_normalize_markets_handles_dotted_market_names():
    # The market half of a canonical key can itself contain a dot (e.g. an
    # over/under line like "2.5") -- only the *outcome* (last segment)
    # never does, so this must rsplit, not split, on ".".
    raw = {"over_2_5": 1.84, "under_2_5": 1.68}
    alias = {"over_2_5": "over_under_2.5.over", "under_2_5": "over_under_2.5.under"}
    result = normalize_markets(raw, alias)
    assert result == {"over_under_2.5": {"over": 1.84, "under": 1.68}}


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
