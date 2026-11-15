"""Outcome engine: windows, thresholds, honesty labels, learning summary."""
import numpy as np
import pandas as pd
import pytest

from app.engines import outcome_engine as oe

T0 = pd.Timestamp("2026-03-02 08:00", tz="UTC")
S0 = (T0 - pd.Timestamp("1970-01-01", tz="UTC")).total_seconds()
APPLIED = S0 + 3600.0  # 1 h in


def frame(wait_before=6.0, wait_after=2.0, n=120, rate_after=1.0, abandon_after=0):
    """One arrival per minute for 2 h; waits are `wait_before` until APPLIED, then `wait_after` (deterministic)."""
    rows = []
    t = 0.0
    k = 0
    while t < 7200.0:
        arr = T0 + pd.Timedelta(seconds=t)
        w = wait_before if t < 3600.0 else wait_after
        start = arr + pd.Timedelta(minutes=w)
        status, left = "completed", pd.NaT
        if t >= 3600.0 and abandon_after and k % abandon_after == 0:
            status, start, left = "abandoned", pd.NaT, arr + pd.Timedelta(minutes=3)
        rows.append(dict(status=status, arrival=arr, start=start, end=start + pd.Timedelta(minutes=2) if status == "completed" else pd.NaT, left=left))
        t += 60.0 / (1.0 if t < 3600.0 else rate_after)
        k += 1
    return pd.DataFrame(rows)


def test_observed_reduction_and_comparison_with_expectation():
    h = frame()
    r = oe.observe(h, APPLIED, 30.0, APPLIED + 4000.0, expected_reduction_min=4.0)
    # customers who queued before the change but started service after it (wait 6) dilute the post window
    assert r["status"] == "ok" and r["pre"]["avg_wait_min"] == pytest.approx(6.0)
    assert 2.0 < r["post"]["avg_wait_min"] < 3.0
    assert 3.0 < r["observed_wait_reduction_min"] < 4.0  # carry-over understates, never overstates, the 4.0 truth
    assert r["comparison"]["verdict"] in ("consistent_with_expectation", "worse_than_expected")
    assert any("not a controlled experiment" in c for c in r["caveats"])
    assert r["clean_for_calibration"] is True


def test_worse_and_better_than_expected_are_described_not_judged():
    h = frame()
    worse = oe.observe(h, APPLIED, 30.0, APPLIED + 4000.0, expected_reduction_min=9.0)["comparison"]
    better = oe.observe(h, APPLIED, 30.0, APPLIED + 4000.0, expected_reduction_min=1.0)["comparison"]
    assert worse["verdict"] == "worse_than_expected" and worse["error_min"] < 0
    assert better["verdict"] == "better_than_expected" and better["error_min"] > 0


def test_window_must_have_elapsed():
    r = oe.observe(frame(), APPLIED, 30.0, APPLIED + 600.0, 4.0)
    assert r["status"] == "window_not_elapsed" and r["ready_in_minutes"] == pytest.approx(20.0)
    assert "observed_wait_reduction_min" not in r


def test_insufficient_customers_gives_no_figures():
    r = oe.observe(frame(), APPLIED, 5.0 * 1.0 + 5.0, APPLIED + 4000.0, 4.0)  # 10-min windows -> ~10 customers
    h = frame().iloc[:60]  # nothing after the change
    r2 = oe.observe(h, APPLIED, 30.0, APPLIED + 4000.0, 4.0)
    assert r2["status"] == "insufficient_data" and "observed_wait_reduction_min" not in r2
    assert r["status"] in ("ok", "insufficient_data")


def test_demand_change_and_overlapping_interventions_are_flagged_as_confounders():
    r = oe.observe(frame(rate_after=2.0), APPLIED, 30.0, APPLIED + 4000.0, 4.0, other_applied_s=[APPLIED + 600.0])
    assert r["status"] == "ok" and r["arrival_rate_change"] == pytest.approx(1.0, abs=0.1)
    assert len(r["confounders"]) == 2 and r["clean_for_calibration"] is False and r["other_interventions_in_window"] == 1


def test_abandonment_rate_counts_arrivals_in_window():
    r = oe.observe(frame(abandon_after=4), APPLIED, 30.0, APPLIED + 4000.0, 4.0)
    assert r["pre"]["abandonment_rate"] == 0.0 and r["post"]["abandonment_rate"] == pytest.approx(0.25, abs=0.06)


def test_interval_needs_enough_blocks_and_contains_the_effect():
    iv = oe.reduction_interval(np.array([6.0, 6.2, 5.8, 6.1, 5.9]), np.array([2.0, 2.1, 1.9, 2.2, 1.8]))
    assert iv["low"] < 4.0 < iv["high"]
    assert oe.reduction_interval(np.array([6.0, 6.2]), np.array([2.0, 2.1])) is None


def test_verification_labels_never_call_synthetic_or_manual_data_verified():
    assert oe.verification_label("observe", False) == "verified_real_observation"
    assert oe.verification_label("observe", True) == "synthetic_observation"
    assert oe.verification_label("manual", False) == "operator_reported"
    assert oe.verification_label("manual", True) == "operator_reported"
    m = oe.manual_outcome({"avg_wait_min": 3.0}, 8.0, 4.0)
    assert m["observed_wait_reduction_min"] == 5.0 and m["clean_for_calibration"] is False


def test_learning_summary_keeps_kinds_apart():
    rows = [dict(verification="verified_real_observation", type="open_counter", expected=4.0, observed=3.0),
            dict(verification="verified_real_observation", type="open_counter", expected=2.0, observed=2.1),
            dict(verification="synthetic_observation", type="open_counter", expected=4.0, observed=9.0),
            dict(verification="operator_reported", type="x", expected=1.0, observed=None)]
    s = oe.learning_summary(rows)
    assert s["counts"] == {"verified_real_observation": 2, "synthetic_observation": 1, "operator_reported": 1}
    assert s["verified_real"]["n"] == 2 and s["verified_real"]["mean_error_min"] == pytest.approx(-0.45)
    assert s["verified_real"]["over_optimistic"] == 1 and s["by_type"]["open_counter"]["n"] == 2
    assert s["synthetic"]["n"] == 1 and s["operator_reported"]["n"] == 0
