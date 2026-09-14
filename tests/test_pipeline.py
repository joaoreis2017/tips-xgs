from tipsxgs.config import load_config
from tipsxgs.pipeline import _betclic_coverable_markets, _count_with_data


def test_betclic_coverable_markets_derived_from_real_config():
    # Real config.yaml has extraction rules for 1x2 (inline on the
    # fixtures listing) + btts/over_under/home_total/away_total (the
    # match detail page's selection_matrix_markets, each covering every
    # line Betclic offers for that market, not just one hardcoded line)
    # -- nothing for handicap (Betclic's handicap market is a real
    # calibrated 3-way per line, a different shape xGScore's simple
    # per-team coverage-probability handicap markets don't map onto,
    # left uncalibrated for now). This is what makes handicap
    # structurally unable to ever carry a real Betclic odd, driving
    # valuebets.top_probability_bets_today's coverable_markets filter.
    cfg = load_config()
    assert _betclic_coverable_markets(cfg) == {"1x2", "btts", "over_under", "home_total", "away_total"}


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
