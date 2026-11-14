from tipsxgs.calibration import CalibrationBucket
from tipsxgs.report import build_calibration_context


def test_build_calibration_context_groups_buckets_under_their_market_family():
    buckets = [
        CalibrationBucket(market_family="1x2", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72),
        CalibrationBucket(market_family="btts", probability_bucket="50-59%", count=5, hits=4, avg_predicted_probability=0.55),
    ]

    ctx = build_calibration_context(buckets, total_games=12)

    assert ctx["total_games"] == 12
    by_family = {m["market_family"]: m for m in ctx["markets"]}
    assert by_family["1x2"]["sample_size"] == 10
    assert len(by_family["1x2"]["buckets"]) == 1
    assert by_family["1x2"]["buckets"][0]["probability_bucket"] == "70-79%"
    assert by_family["btts"]["sample_size"] == 5


def test_build_calibration_context_verdict_good_within_tolerance():
    # 70% real vs 72% previsto -- a 2-point gap, well inside the 7-point
    # "bem calibrado" tolerance.
    buckets = [CalibrationBucket(market_family="1x2", probability_bucket="70-79%", count=10, hits=7, avg_predicted_probability=0.72)]
    ctx = build_calibration_context(buckets, total_games=10)
    assert ctx["markets"][0]["buckets"][0]["verdict"] == "good"


def test_build_calibration_context_verdict_over_when_actual_rate_is_much_lower():
    # Predicted 90% but only actually hit 50% of the time -- the model
    # was overconfident ("over" = predicted too high relative to reality).
    buckets = [CalibrationBucket(market_family="1x2", probability_bucket="90-99%", count=10, hits=5, avg_predicted_probability=0.90)]
    ctx = build_calibration_context(buckets, total_games=10)
    assert ctx["markets"][0]["buckets"][0]["verdict"] == "over"


def test_build_calibration_context_verdict_under_when_actual_rate_is_much_higher():
    # Predicted only 50% but hit 90% of the time -- the model undersold
    # itself ("under" = predicted too low relative to reality).
    buckets = [CalibrationBucket(market_family="1x2", probability_bucket="50-59%", count=10, hits=9, avg_predicted_probability=0.50)]
    ctx = build_calibration_context(buckets, total_games=10)
    assert ctx["markets"][0]["buckets"][0]["verdict"] == "under"


def test_build_calibration_context_empty_inputs():
    ctx = build_calibration_context([], total_games=0)
    assert ctx["markets"] == []
    assert ctx["total_games"] == 0
