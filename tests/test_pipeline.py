from tipsxgs.config import load_config
from tipsxgs.pipeline import _betclic_coverable_markets


def test_betclic_coverable_markets_derived_from_real_config():
    # Real config.yaml only has extraction rules for 1x2 (inline on the
    # fixtures listing) + btts/over_under_2.5 (the match detail page) --
    # nothing for handicap or per-team-total lines. This is what makes
    # those structurally unable to ever carry a real Betclic odd, driving
    # valuebets.top_probability_bets_today's coverable_markets filter.
    cfg = load_config()
    assert _betclic_coverable_markets(cfg) == {"1x2", "btts", "over_under_2.5"}
