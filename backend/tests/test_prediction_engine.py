import math

import numpy as np
import pytest

from app.engines import prediction_engine as pe
from tests.frames import simulate_entries


def test_baseline_hand_calculation():
    r = pe.baseline_wait(pe.BaselineInputs(5, 3, 3, [0.25] * 3))
    assert r["waiting_time_s"] == pytest.approx(480.0) and r["completions_needed"] == 6
    assert pe.baseline_wait(pe.BaselineInputs(5, 3, 2, [0.25] * 3))["waiting_time_s"] == pytest.approx(400.0)
    assert pe.baseline_wait(pe.BaselineInputs(0, 2, 1, [0.5, 0.5]))["waiting_time_s"] == 0.0


def test_baseline_uses_observed_service_time_only_with_enough_samples():
    few = pe.baseline_wait(pe.BaselineInputs(2, 2, 2, [1.0, 1.0], observed_mean_service_s=120, observed_service_samples=3))
    assert few["service_time_source"] == "nominal_counter_rates"
    many = pe.baseline_wait(pe.BaselineInputs(2, 2, 2, [1.0, 1.0], observed_mean_service_s=120, observed_service_samples=40))
    assert many["service_time_source"] == "observed_recent_service_times"
    assert many["waiting_time_s"] == pytest.approx(3 / (2 / 2.0) * 60)


def test_baseline_reports_overload_and_reference():
    r = pe.baseline_wait(pe.BaselineInputs(0, 2, 0, [0.5, 0.5], arrival_rate_per_min=0.5))
    assert r["overloaded"] is False and "steady_state_reference_wait_s" in r
    assert pe.baseline_wait(pe.BaselineInputs(0, 2, 0, [0.5, 0.5], arrival_rate_per_min=1.5))["overloaded"] is True


@pytest.mark.parametrize("bad", [
    dict(queue_length=-1, active_counters=1, counter_rates_per_min=[1]),
    dict(queue_length=1.5, active_counters=1, counter_rates_per_min=[1]),
    dict(queue_length=1, active_counters=1, busy_counters=2, counter_rates_per_min=[1]),
    dict(queue_length=1, active_counters=2, counter_rates_per_min=[1]),
    dict(queue_length=1, active_counters=1, counter_rates_per_min=[0]),
    dict(queue_length=1, active_counters=1, counter_rates_per_min=[float("nan")]),
    dict(queue_length=1, active_counters=1),
    dict(queue_length=1, active_counters=1, counter_rates_per_min=[1], arrival_rate_per_min=-1),
])
def test_input_validation_rejects_bad_inputs(bad):
    with pytest.raises(pe.PredictionInputError):
        pe.baseline_wait(pe.BaselineInputs(**bad))


def test_no_active_counters_is_unavailable_not_zero():
    with pytest.raises(pe.PredictionUnavailable):
        pe.baseline_wait(pe.BaselineInputs(3, 0, 0))


def test_error_metrics():
    m = pe.error_metrics([10, 20, 30], [12, 18, 36])
    assert m["n"] == 3 and m["mae_s"] == pytest.approx((2 + 2 + 6) / 3)
    assert m["rmse_s"] == pytest.approx(math.sqrt((4 + 4 + 36) / 3))
    assert m["mean_error_s"] == pytest.approx((2 - 2 + 6) / 3)
    assert pe.error_metrics([], [])["mae_s"] is None
    with pytest.raises(ValueError):
        pe.error_metrics([1], [1, 2])


def test_feature_reconstruction_matches_brute_force():
    df, _ = simulate_entries(n=300, seed=5)
    h, _ = pe.prepare_history(df)
    ctx = pe.HistoryContext(3, 0.75)
    arr, st, en = (pe.to_seconds(h[c]) for c in ("arrival", "start", "end"))
    rows = np.arange(40, 280, 23)
    f = pe.compute_features(h, arr[rows], ctx, self_rows=rows)
    for j, i in enumerate(rows):
        t = arr[i]
        assert f.queue_ahead[j] == sum(1 for k in range(len(h)) if arr[k] < t and st[k] > t)
        assert f.busy_counters[j] == min(sum(1 for k in range(len(h)) if k != i and st[k] <= t < en[k]), 3)


def test_features_do_not_leak_the_target():
    df, _ = simulate_entries(n=300, seed=6)
    h, _ = pe.prepare_history(df)
    ctx = pe.HistoryContext(3, 0.75)
    ds = pe.build_dataset(h, ctx)
    i = 150
    h2 = h.copy()
    h2.loc[i, "start"] = h2.loc[i, "start"] + np.timedelta64(30, "m")
    h2.loc[i, "end"] = h2.loc[i, "end"] + np.timedelta64(30, "m")
    arr = pe.to_seconds(h["arrival"])
    f1 = pe.compute_features(h, arr[[i]], ctx, self_rows=np.array([i]))
    f2 = pe.compute_features(h2, arr[[i]], ctx, self_rows=np.array([i]))
    for col in ("queue_ahead", "busy_counters", "recent_avg_wait_s", "hist_hour_mean_wait_s", "avg_service_time_s"):
        assert f1[col][0] == pytest.approx(f2[col][0])
    assert len(ds) > 200 and not ds[pe.FEATURES].isna().any().any()


def test_insufficient_data_never_trains_ml():
    df, _ = simulate_entries(n=300, seed=7)
    h, _ = pe.prepare_history(df)
    ds = pe.build_dataset(h, pe.HistoryContext(3, 0.75)).head(50)
    b = pe.train_and_select(ds)
    assert b.method == pe.METHOD_BASELINE and b.model is None
    assert b.report["status"] == "insufficient_data" and b.report["models_trained"] == []
    assert "validation_metrics" not in b.report
    assert pe.train_and_select(ds.head(0)).report["status"] == "no_history"


def test_model_selection_is_measured_on_holdout_and_baseline_is_default():
    df, _ = simulate_entries(n=900, seed=8)
    h, _ = pe.prepare_history(df)
    b = pe.train_and_select(pe.build_dataset(h, pe.HistoryContext(3, 0.75)))
    assert b.report["status"] == "trained"
    vm = b.report["validation_metrics"]
    assert set(vm) == {pe.METHOD_BASELINE, pe.METHOD_LINEAR, pe.METHOD_FOREST}
    assert b.report["train_samples"] + b.report["validation_samples"] == b.report["samples"]
    if b.method != pe.METHOD_BASELINE:
        assert vm[b.method]["mae_s"] <= pe.IMPROVEMENT_REQUIRED * vm[pe.METHOD_BASELINE]["mae_s"]
    row = {k: 1.0 for k in pe.FEATURES} | {"baseline_wait_s": 100.0}
    out = pe.predict(row, b)
    assert out["predicted_waiting_time_s"] >= 0 and out["method"] in (pe.METHOD_BASELINE, b.method)


def test_ml_falls_back_outside_training_range():
    df, _ = simulate_entries(n=900, seed=8)
    h, _ = pe.prepare_history(df)
    b = pe.train_and_select(pe.build_dataset(h, pe.HistoryContext(3, 0.75)))
    b2 = pe.ModelBundle(pe.METHOD_LINEAR, b.report and __import__("sklearn.linear_model", fromlist=["x"]).LinearRegression().fit(
        np.zeros((3, len(pe.FEATURES))), [0, 1, 2]), b.report, None, 100.0)
    out = pe.predict({k: 1.0 for k in pe.FEATURES} | {"baseline_wait_s": 5000.0}, b2)
    assert out["method"] == pe.METHOD_BASELINE and out["predicted_waiting_time_s"] == 5000.0
    assert any("beyond" in n for n in out["notes"])


def test_interval_requires_enough_residuals():
    assert pe.residual_interval(list(range(10)), list(range(10))) is None
    assert pe.residual_interval(list(range(40)), [x + 1 for x in range(40)])["n_residuals"] == 40
