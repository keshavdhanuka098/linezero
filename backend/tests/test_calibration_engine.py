"""Calibration maths, validation discipline, drift detection."""
import numpy as np
import pandas as pd
import pytest

from app.engines import calibration_engine as ce
from app.engines import drift_detection_engine as dd
from app.engines import prediction_engine as pe
from tests.frames import T0, simulate_entries

TRUE_LAM, TRUE_MU = 0.5, 0.25  # per minute; 3 counters => rho = 0.667


def counters(rate=0.25, n=3):
    return [dict(id=i + 1, status="active", service_rate=rate) for i in range(n)]


def hist(n=800, seed=3, lam=TRUE_LAM, mean_service=4.0, speeds=(1, 1, 1)):
    df, _ = simulate_entries(lam=lam, mean_service_min=mean_service, speeds=speeds, n=n, seed=seed)
    h, _ = pe.prepare_history(df)
    return h


def test_estimates_recover_the_true_rates_with_intervals_that_contain_them():
    h = hist(n=1500, seed=11)
    arr = pe.to_seconds(h["arrival"])
    est = ce.estimate_parameters(h, float(arr.min()), float(arr.max()), None, ce.CalibrationSettings())
    p, e = est["parameters"], est["estimates"]
    assert p["arrival_rate_per_min"] == pytest.approx(TRUE_LAM, rel=0.1)
    assert p["service_rate_per_min"] == pytest.approx(TRUE_MU, rel=0.1)
    lo, hi = e["arrival"]["ci95"]
    assert lo < TRUE_LAM < hi
    lo, hi = e["service"]["ci95"]
    assert lo < TRUE_MU < hi
    assert set(p["counter_service_rates"]) == {"1", "2", "3"}


def test_prior_pulls_a_small_noisy_window_toward_the_previous_version():
    h = hist(n=60, seed=5)
    arr = pe.to_seconds(h["arrival"])
    window = (float(arr.min()), float(arr.max()))
    no_prior = ce.estimate_parameters(h, *window, None, ce.CalibrationSettings())["parameters"]
    prior = {"arrival_rate_per_min": 2.0, "service_rate_per_min": 1.0}
    pulled = ce.estimate_parameters(h, *window, prior, ce.CalibrationSettings())["parameters"]
    assert no_prior["arrival_rate_per_min"] < pulled["arrival_rate_per_min"] < 2.0
    assert no_prior["service_rate_per_min"] < pulled["service_rate_per_min"] < 1.0
    # with no prior weight the previous version must have no influence at all
    flat = ce.estimate_parameters(h, *window, prior, ce.CalibrationSettings(prior_arrival_minutes=0,
                                                                            prior_service_pseudo_n=0))["parameters"]
    assert flat["arrival_rate_per_min"] == pytest.approx(no_prior["arrival_rate_per_min"])


def test_training_estimates_use_nothing_that_happened_after_the_cutoff():
    h = hist(n=500, seed=7)
    arr = pe.to_seconds(h["arrival"])
    cutoff = float(np.quantile(arr, 0.6))
    base = ce.estimate_parameters(h, float(arr.min()), cutoff, None, ce.CalibrationSettings())
    # corrupt EVERYTHING after the cutoff: absurdly long services and a flood of arrivals
    late = h.copy()
    after = pe.to_seconds(late["arrival"]) > cutoff
    late.loc[after, "end"] = late.loc[after, "start"] + pd.Timedelta(hours=50)
    same = ce.estimate_parameters(late, float(arr.min()), cutoff, None, ce.CalibrationSettings())
    # services that finish after the cutoff are excluded, so the corrupted rows cannot leak in
    base_p, same_p = base["parameters"], same["parameters"]
    assert same_p["arrival_rate_per_min"] == pytest.approx(base_p["arrival_rate_per_min"])
    assert same_p["service_rate_per_min"] == pytest.approx(base_p["service_rate_per_min"], rel=0.05)


def test_excluded_windows_remove_both_arrivals_and_exposure():
    h = hist(n=600, seed=2)
    arr = pe.to_seconds(h["arrival"])
    t0, t1 = float(arr.min()), float(arr.max())
    mid = (t0 + t1) / 2
    win = (mid, mid + (t1 - t0) * 0.25)
    full = ce.estimate_parameters(h, t0, t1, None, ce.CalibrationSettings())
    cut = ce.estimate_parameters(h, t0, t1, None, ce.CalibrationSettings(exclude_arrival_windows=(win,)))
    assert cut["n_arrivals"] < full["n_arrivals"]
    assert cut["exposure_min"] == pytest.approx(full["exposure_min"] * 0.75, rel=1e-6)
    assert cut["parameters"]["arrival_rate_per_min"] == pytest.approx(full["parameters"]["arrival_rate_per_min"], rel=0.2)


def test_insufficient_data_is_reported_not_guessed():
    h = hist(n=25, seed=1)
    res = ce.calibrate(h, counters(), None, ce.CalibrationSettings())
    assert res["decision"] == "insufficient_data" and res["candidate_parameters"] is None
    assert res["reasons"] and "at least" in res["reasons"][0]
    empty = ce.calibrate(h.iloc[0:0], counters(), None, ce.CalibrationSettings())
    assert empty["decision"] == "insufficient_data"
    assert ce.calibrate(h, [dict(id=1, status="paused", service_rate=1.0)], None,
                        ce.CalibrationSettings())["decision"] == "insufficient_data"


def test_wrong_nominal_rates_are_fixed_and_validated_on_held_out_customers():
    h = hist(n=900, seed=3)
    res = ce.calibrate(h, counters(rate=0.15), None, ce.CalibrationSettings())  # configured rate is wrong
    assert res["decision"] == "accepted" and res["accepted"] is True
    w = res["windows"]
    assert w["training_end_s"] < w["validation_start_s"]  # chronological split, no overlap
    assert res["candidate_metrics"]["mae_s"] < res["incumbent_metrics"]["mae_s"]
    assert res["paired_abs_error_diff_s"]["mean_diff"] < 0 and res["paired_abs_error_diff_s"]["significant"]
    assert res["candidate_parameters"]["service_rate_per_min"] == pytest.approx(TRUE_MU, rel=0.15)
    assert 0.0 < res["confidence"]["value"] <= 1.0
    assert res["n_validation"] >= ce.MIN_VALIDATION


def test_a_candidate_that_does_not_beat_the_incumbent_is_rejected():
    h = hist(n=900, seed=3)
    good = ce.calibrate(h, counters(rate=0.15), None, ce.CalibrationSettings())["candidate_parameters"]
    again = ce.calibrate(h, counters(rate=0.15), good, ce.CalibrationSettings(min_improvement_pct=20.0))
    assert again["decision"] == "rejected" and again["accepted"] is False
    assert "required at least 20%" in " ".join(again["reasons"])


def test_a_stale_incumbent_is_replaced_when_conditions_changed():
    # old calibration says services take 8 min, but the data (4 min) disagrees
    h = hist(n=900, seed=9)
    stale = {"arrival_rate_per_min": 0.5, "service_rate_per_min": 0.125,
             "counter_service_rates": {"1": 0.125, "2": 0.125, "3": 0.125}}
    res = ce.calibrate(h, counters(), stale, ce.CalibrationSettings(prior_service_pseudo_n=2))
    assert res["accepted"] and res["candidate_metrics"]["mae_s"] < res["incumbent_metrics"]["mae_s"]


def test_error_metrics_mae_rmse_mape_and_mape_floor():
    actual = np.array([0.0, 60.0, 120.0, 300.0])
    pred = np.array([10.0, 30.0, 150.0, 300.0])
    m = ce.error_summary(actual, pred)
    assert m["mae_s"] == pytest.approx((10 + 30 + 30 + 0) / 4)
    assert m["rmse_s"] == pytest.approx(np.sqrt((100 + 900 + 900 + 0) / 4))
    assert m["mape_n"] == 3  # the zero-wait customer is excluded: percentage error is undefined there
    assert m["mape_pct"] == pytest.approx(np.mean([30 / 60, 30 / 120, 0]) * 100)
    nothing = ce.error_summary(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert nothing["mape_pct"] is None and nothing["mape_n"] == 0  # all below the floor => not computed


def test_wait_formula_matches_the_existing_prediction_engine_baseline():
    for q, busy, c, mu in [(0, 0, 3, 0.75), (0, 3, 3, 0.75), (5, 3, 3, 0.75), (7, 2, 4, 1.0)]:
        mine = ce.predict_wait_s(np.array([q]), np.array([busy]), c, mu)[0]
        theirs = pe.baseline_wait(pe.BaselineInputs(
            queue_length=q, active_counters=c, busy_counters=busy, counter_rates_per_min=[mu / c] * c))
        assert mine == pytest.approx(theirs["waiting_time_s"])


def test_capacity_uses_per_counter_rates_and_skips_inactive_counters():
    cs = [dict(id=1, status="active", service_rate=0.3), dict(id=2, status="paused", service_rate=9.0),
          dict(id=3, status="active", service_rate=0.2)]
    assert ce.capacity_per_min({"service_rate_per_min": 0.25, "counter_service_rates": {}}, cs) == pytest.approx(0.5)
    assert ce.capacity_per_min({"service_rate_per_min": 0.25, "counter_service_rates": {"1": 0.4}}, cs) == pytest.approx(0.65)


def test_settings_validation():
    for bad in (dict(validation_fraction=0.9), dict(min_improvement_pct=-1), dict(lookback_minutes=0)):
        with pytest.raises(ValueError):
            ce.calibrate(hist(), counters(), None, ce.CalibrationSettings(**bad))


# ------------------------------------------------------------------ drift
def test_no_drift_on_stationary_data_and_drift_when_demand_and_service_change():
    df1, end1 = simulate_entries(lam=0.5, mean_service_min=4.0, speeds=(1, 1, 1), n=500, seed=21)
    df2, _ = simulate_entries(lam=0.75, mean_service_min=6.0, speeds=(1, 1, 1, 1, 1), n=500, seed=22)
    df2 = df2.copy()
    shift = pd.Timedelta(minutes=end1 + 1)
    for c in ("arrival", "start", "end", "left"):
        df2[c] = df2[c] + shift
    stationary, _ = pe.prepare_history(df1)
    arr = pe.to_seconds(stationary["arrival"])
    split = float(np.quantile(arr, 0.6))
    same = dd.detect_drift(stationary, (float(arr.min()), split), (split, float(arr.max())))
    assert same["status"] == "ok" and same["drift_detected"] is False

    both, _ = pe.prepare_history(pd.concat([df1, df2], ignore_index=True))
    boundary = float(pe.to_seconds(pd.Series([T0 + shift]))[0])
    arr2 = pe.to_seconds(both["arrival"])
    res = dd.detect_drift(both, (float(arr2.min()), boundary - 1), (boundary, float(arr2.max())))
    assert res["drift_detected"] is True
    assert "arrival_rate" in res["drifted_signals"] and "service_time" in res["drifted_signals"]
    assert res["signals"]["arrival_rate"]["direction"] == "increase"
    assert res["signals"]["arrival_rate"]["effect"] == pytest.approx(0.5, abs=0.2)
    assert res["severity"] == "high"


def test_drift_needs_effect_size_not_only_significance():
    r = dd.arrival_rate_test(50000, 100000.0, 11000, 20000.0)  # 10% higher rate, hugely significant sample
    assert r["p_value"] < 1e-3 and r["effect"] == pytest.approx(0.1, abs=0.01)
    h = pd.DataFrame({c: [] for c in ("arrival", "start", "end", "left")})
    for c in h:
        h[c] = pd.to_datetime(h[c], utc=True)
    assert dd.detect_drift(h, (0, 10), (10, 20))["status"] == "insufficient_data"


def test_drift_rejects_overlapping_or_inverted_windows():
    h, _ = pe.prepare_history(simulate_entries(n=100, seed=1)[0])
    with pytest.raises(ValueError):
        dd.detect_drift(h, (0, 10), (5, 20))
    with pytest.raises(ValueError):
        dd.detect_drift(h, (10, 0), (11, 20))


def test_wait_drift_is_not_triggered_by_autocorrelated_noise_on_stationary_data():
    """Regression guard: a naive per-customer KS test flagged 18 of 40 stationary runs; block means must stay quiet."""
    flagged = 0
    for seed in range(30):
        h, _ = pe.prepare_history(simulate_entries(lam=0.5, mean_service_min=4.0, speeds=(1, 1, 1), n=500, seed=seed)[0])
        arr = pe.to_seconds(h["arrival"])
        split = float(np.quantile(arr, 0.6))
        r = dd.detect_drift(h, (float(arr.min()), split), (split, float(arr.max())))
        flagged += "waiting_time" in r["drifted_signals"]
    assert flagged <= 2
