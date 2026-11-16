from tipsxgs.calibration import CalibrationBucket
from tipsxgs.report import build_calibration_context


def _markets_by_group(ctx):
    markets = []
    for fam in ctx["families"]:
        markets.extend(fam["markets"])
    return {(m["market"], m["outcome"]): m for m in markets}


def test_build_calibration_context_groups_buckets_under_market_and_outcome():
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72),
        CalibrationBucket(market="1x2", outcome="away", probability_bucket="20-29%", count=8, hits=2, avg_predicted_probability=0.25),
        CalibrationBucket(market="over_under_2.5", outcome="over", probability_bucket="50-59%", count=5, hits=4, avg_predicted_probability=0.55),
    ]

    ctx = build_calibration_context(buckets, total_games=12)

    assert ctx["total_games"] == 12
    by_group = _markets_by_group(ctx)
    assert len(by_group) == 3  # "1x2.home" and "1x2.away" are NOT merged
    assert by_group[("1x2", "home")]["sample_size"] == 10
    assert len(by_group[("1x2", "home")]["buckets"]) == 1
    assert by_group[("1x2", "home")]["buckets"][0]["probability_bucket"] == "70-79%"
    assert by_group[("1x2", "away")]["sample_size"] == 8
    assert by_group[("over_under_2.5", "over")]["sample_size"] == 5


def test_build_calibration_context_label_combines_market_and_outcome():
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72)
    ]
    ctx = build_calibration_context(buckets, total_games=10)
    assert _markets_by_group(ctx)[("1x2", "home")]["label"] == "Resultado Final - Casa"


def test_build_calibration_context_families_group_different_lines_of_the_same_market():
    # Explicitly requested (2026-11-17): both the filter dropdown and the
    # page's own detail sections group by market *family* (over_under_1.5
    # and over_under_2.5 both land under the same "over_under" family),
    # not by the exact market.
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=27, avg_predicted_probability=0.83),
        CalibrationBucket(market="over_under_2.5", outcome="over", probability_bucket="50-59%", count=10, hits=6, avg_predicted_probability=0.55),
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72),
    ]
    ctx = build_calibration_context(buckets, total_games=30)
    by_name = {fam["name"]: fam for fam in ctx["families"]}
    assert set(by_name) == {"over_under", "1x2"}

    over_under_markets = {m["market"] for m in by_name["over_under"]["markets"]}
    assert over_under_markets == {"over_under_1.5", "over_under_2.5"}
    assert by_name["over_under"]["sample_size"] == 40
    assert by_name["1x2"]["sample_size"] == 10


def test_build_calibration_context_label_includes_the_exact_line():
    # Explicitly requested: over_under_1.5 must read differently from
    # over_under_2.5 in the rendered label, not just internally.
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=27, avg_predicted_probability=0.83),
        CalibrationBucket(market="over_under_2.5", outcome="over", probability_bucket="80-89%", count=30, hits=20, avg_predicted_probability=0.83),
    ]
    ctx = build_calibration_context(buckets, total_games=30)
    labels = {m["label"] for m in _markets_by_group(ctx).values()}
    assert "Mais/Menos de 1.5 Golos - Mais" in labels
    assert "Mais/Menos de 2.5 Golos - Mais" in labels


def test_build_calibration_context_verdict_good_within_tolerance():
    # 70% real vs 72% previsto -- a 2-point gap, well inside the 7-point
    # "bem calibrado" tolerance.
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72)
    ]
    ctx = build_calibration_context(buckets, total_games=10)
    m = _markets_by_group(ctx)[("1x2", "home")]
    assert m["buckets"][0]["verdict"] == "good"
    fam = {fam["name"]: fam for fam in ctx["families"]}["1x2"]
    assert fam["verdict_counts"] == {"good": 1, "over": 0, "under": 0}


def test_build_calibration_context_verdict_over_when_actual_rate_is_much_lower():
    # Predicted 90% but only actually hit 50% of the time -- the model
    # was overconfident ("over" = predicted too high relative to reality).
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="90-99%", count=10, hits=5, avg_predicted_probability=0.90)
    ]
    ctx = build_calibration_context(buckets, total_games=10)
    assert _markets_by_group(ctx)[("1x2", "home")]["buckets"][0]["verdict"] == "over"


def test_build_calibration_context_verdict_under_when_actual_rate_is_much_higher():
    # Predicted only 50% but hit 90% of the time -- the model undersold
    # itself ("under" = predicted too low relative to reality).
    buckets = [
        CalibrationBucket(market="1x2", outcome="home", probability_bucket="50-59%", count=10, hits=9, avg_predicted_probability=0.50)
    ]
    ctx = build_calibration_context(buckets, total_games=10)
    assert _markets_by_group(ctx)[("1x2", "home")]["buckets"][0]["verdict"] == "under"


def test_build_calibration_context_family_verdict_counts_tally_across_its_markets():
    # Explicitly requested (2026-11-17): the summary table shows, per
    # family, how many of ITS bands (across every one of its outcomes)
    # landed in each verdict bucket.
    buckets = [
        CalibrationBucket(market="over_under_1.5", outcome="over", probability_bucket="80-89%", count=30, hits=26, avg_predicted_probability=0.83),  # good
        CalibrationBucket(market="over_under_2.5", outcome="under", probability_bucket="50-59%", count=10, hits=9, avg_predicted_probability=0.55),  # under
        CalibrationBucket(market="over_under_2.5", outcome="under", probability_bucket="90-99%", count=10, hits=5, avg_predicted_probability=0.95),  # over
    ]
    ctx = build_calibration_context(buckets, total_games=30)
    fam = {fam["name"]: fam for fam in ctx["families"]}["over_under"]
    assert fam["verdict_counts"] == {"good": 1, "over": 1, "under": 1}
    assert fam["band_count"] == 3


def test_build_calibration_context_empty_inputs():
    ctx = build_calibration_context([], total_games=0)
    assert ctx["families"] == []
    assert ctx["total_games"] == 0
