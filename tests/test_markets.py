from tipsxgs.extract import normalize_probabilities, parse_odds
from tipsxgs.markets import (
    expand_array_market,
    full_label,
    market_family,
    market_label,
    merge_markets,
    normalize_markets,
)


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


def test_expand_array_market_line_in_market_name():
    rows = [["0.5", 94.8], ["2.5", 63.9]]
    result = expand_array_market(rows, "over_under_{label}", "over")
    assert result == {"over_under_0.5": {"over": 0.948}, "over_under_2.5": {"over": 0.639}}


def test_expand_array_market_line_in_outcome_name():
    rows = [["-2.5", 15.8], ["0", 71.5]]
    result = expand_array_market(rows, "handicap_home", "{label}")
    assert result == {"handicap_home": {"-2.5": 0.158, "0": 0.715}}


def test_expand_array_market_never_misreads_small_percentages_as_fractions():
    # A tail probability like 0.8 means 0.8%, not an already-a-fraction
    # 80% -- unlike normalize_probabilities()'s ">1.0" heuristic (fine for
    # a flat, mixed-purpose dict with no other context), every row here
    # comes from the exact same percentage convention, so this always
    # divides by 100 with no guessing.
    rows = [["4", 0.8], ["3.5", 3.3]]
    result = expand_array_market(rows, "away_total_{label}", "over")
    assert result == {"away_total_4": {"over": 0.008}, "away_total_3.5": {"over": 0.033}}


def test_expand_array_market_skips_malformed_rows():
    rows = [["0.5", 94.8], ["bad_row"], ["1.5", None], ["2.5", 63.9]]
    result = expand_array_market(rows, "over_under_{label}", "over")
    assert result == {"over_under_0.5": {"over": 0.948}, "over_under_2.5": {"over": 0.639}}


def test_market_label_handles_dynamic_over_under_and_handicap_names():
    assert market_label("over_under_3.5") == "Mais/Menos de 3.5 Golos"
    assert market_label("home_total_2.5") == "Total Casa Mais/Menos de 2.5"
    assert market_label("away_total_1") == "Total Fora Mais/Menos de 1"
    assert market_label("handicap_home") == "Handicap Casa"
    assert market_label("handicap_away") == "Handicap Fora"


def test_market_family_strips_the_trailing_line_only():
    # Different lines of the same market family collapse to one family --
    # used to check "does Betclic cover this KIND of market" without
    # enumerating every concrete line (pipeline._betclic_coverable_markets,
    # valuebets.top_probability_bets_today's coverable_markets check).
    assert market_family("over_under_2.5") == "over_under"
    assert market_family("over_under_0.5") == "over_under"
    assert market_family("home_total_3.5") == "home_total"
    assert market_family("away_total_1") == "away_total"
    # A market with no per-line suffix at all is returned unchanged.
    assert market_family("1x2") == "1x2"
    assert market_family("btts") == "btts"
    assert market_family("handicap_home") == "handicap_home"
