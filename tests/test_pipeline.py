from tipsxgs.config import load_config
from tipsxgs.pipeline import _betclic_coverable_markets, _count_with_data


def test_betclic_coverable_markets_derived_from_real_config():
    # Real config.yaml only has extraction rules for 1x2 (inline on the
    # fixtures listing) + btts/over_under (the match detail page's
    # selection_matrix_markets, covering every over/under line Betclic
    # offers, not just one hardcoded line) -- nothing for handicap or
    # per-team-total lines. This is what makes those structurally unable
    # to ever carry a real Betclic odd, driving
    # valuebets.top_probability_bets_today's coverable_markets filter.
    cfg = load_config()
    assert _betclic_coverable_markets(cfg) == {"1x2", "btts", "over_under"}


def test_count_with_data_ignores_empty_previews():
    # Real bug: scrape_preview() returns an *empty* Prediction (not an
    # exception) when a page's extraction found nothing, so
    # len(predictions) alone claimed "15/15 successfully" on a live run
    # where 12 of those 15 had no real data at all. _count_with_data
    # only counts the ones that actually got market data.
    class _P:
        def __init__(self, markets):
            self.markets = markets

    predictions = {"a": _P({"1x2": {"home": 0.5}}), "b": _P({}), "c": _P({"btts": {"yes": 0.6}})}
    assert _count_with_data(predictions) == 2
