"""Outcome evaluation: what actually happened after an operator applied an intervention?

Pure functions over the observation frame (no database access).

Design
  * Pre window  = the W minutes BEFORE the operator-confirmed `applied_at`; post window = the W minutes AFTER it.
    Customers are assigned to a window by the time their service STARTED (that is when their wait becomes known).
    Customers who queued before the change but were served after it therefore count in the post window; this
    carry-over dilutes the measured effect (it errs towards under-stating an improvement, never over-stating it).
  * Metrics per window: average and p95 wait, service starts per minute (throughput), arrival rate, abandonment rate
    (abandoned customers among those who ARRIVED in the window).
  * The post window must have fully elapsed (`as_of` >= applied_at + W) and both windows need MIN_CUSTOMERS customers;
    otherwise nothing is computed and the reason is returned.
  * Uncertainty: Welch interval on the difference of 15-minute block means (consecutive waits are autocorrelated, so
    individual waits would give an over-confident interval). With fewer than MIN_BLOCKS blocks no interval is given.
  * A before/after comparison is NOT a controlled experiment. Demand, staffing and weather may have changed as well, so
    every result lists the arrival-rate change between the windows and states this limit. The simulated expectation was
    made against a counterfactual that is no longer observable; the comparison is evidence, not proof of causation.

Verification labels (see `verification_label`)
  verified_real_observation  measured from a REAL (non-synthetic) queue's database;
  synthetic_observation      measured from synthetic demo data, so it is NOT a real-world result;
  operator_reported          typed in by an operator; LineZero did not measure it.
Only `verified_real_observation` outcomes can be `calibration_eligible`.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.engines import prediction_engine as pe

MIN_CUSTOMERS = 10
MIN_BLOCKS = 4
BLOCK_MIN = 15.0
SIGNIFICANT_ERROR_MIN = 0.25   # |observed - expected| below this (minutes) counts as "as expected"

CAVEATS = [
    "A before/after comparison is not a controlled experiment: demand, staffing or other conditions may also have "
    "changed between the windows. Check the arrival-rate change reported alongside.",
    "Customers who joined the queue before the change but were served after it count in the post window, which "
    "understates the effect of a short window.",
    "The simulated expectation assumed the same demand as when the intervention was proposed; it cannot be checked "
    "against a counterfactual that did not happen.",
]


def verification_label(mode: str, queue_is_synthetic: bool) -> str:
    if mode == "manual":
        return "operator_reported"
    return "synthetic_observation" if queue_is_synthetic else "verified_real_observation"


def _empty_window(a: float, b: float) -> dict[str, Any]:
    return {"start_s": a, "end_s": b, "minutes": (b - a) / 60.0, "customers_served": 0, "arrivals": 0}


def window_metrics(h: pd.DataFrame, a: float, b: float) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    """Metrics of customers whose service started in [a, b). Also returns their start times and waits (minutes)."""
    out = _empty_window(a, b)
    if len(h) == 0:
        return out, np.array([]), np.array([])
    arr, st = pe.to_seconds(h["arrival"]), pe.to_seconds(h["start"])
    ok = np.isfinite(st) & (st >= a) & (st < b) & np.isfinite(arr)
    wait = (st[ok] - arr[ok]) / 60.0
    keep = wait >= 0
    starts, wait = st[ok][keep], wait[keep]
    minutes = (b - a) / 60.0
    arrived = np.isfinite(arr) & (arr >= a) & (arr < b)
    abandoned = arrived & (h["status"].to_numpy() == "abandoned")
    out.update({
        "customers_served": int(len(wait)), "arrivals": int(arrived.sum()),
        "avg_wait_min": float(wait.mean()) if len(wait) else None,
        "p95_wait_min": float(np.percentile(wait, 95)) if len(wait) else None,
        "throughput_per_min": float(len(wait) / minutes), "arrival_rate_per_min": float(arrived.sum() / minutes),
        "abandonment_rate": float(abandoned.sum() / arrived.sum()) if arrived.sum() else None,
    })
    return out, starts, wait


def _block_means(starts: np.ndarray, wait: np.ndarray, a: float) -> np.ndarray:
    if len(wait) == 0:
        return np.array([])
    idx = np.floor((starts - a) / (BLOCK_MIN * 60.0)).astype(int)
    return np.array([float(wait[idx == k].mean()) for k in np.unique(idx) if (idx == k).sum() >= 2])


def reduction_interval(pre_blocks: np.ndarray, post_blocks: np.ndarray) -> dict[str, Any] | None:
    """95% Welch interval for (pre mean - post mean) on block means; None if there are too few blocks."""
    if len(pre_blocks) < MIN_BLOCKS or len(post_blocks) < MIN_BLOCKS:
        return None
    v1, v2 = pre_blocks.var(ddof=1) / len(pre_blocks), post_blocks.var(ddof=1) / len(post_blocks)
    diff = float(pre_blocks.mean() - post_blocks.mean())
    se = math.sqrt(v1 + v2)
    if se == 0.0:
        return {"low": diff, "high": diff, "blocks_pre": int(len(pre_blocks)), "blocks_post": int(len(post_blocks)),
                "unit": f"{BLOCK_MIN:g}-minute blocks"}
    dof = (v1 + v2) ** 2 / (v1 ** 2 / (len(pre_blocks) - 1) + v2 ** 2 / (len(post_blocks) - 1))
    half = float(sps.t.ppf(0.975, dof) * se)
    return {"low": diff - half, "high": diff + half, "blocks_pre": int(len(pre_blocks)),
            "blocks_post": int(len(post_blocks)), "unit": f"{BLOCK_MIN:g}-minute blocks"}


def observe(h: pd.DataFrame, applied_s: float, window_min: float, as_of_s: float,
            expected_reduction_min: float | None, other_applied_s: list[float] | None = None) -> dict[str, Any]:
    """Measure pre/post windows around `applied_s`. Always returns a dict with `status`:
    'ok', 'window_not_elapsed' or 'insufficient_data' (then no figures are given)."""
    w = window_min * 60.0
    pre_a, post_b = applied_s - w, applied_s + w
    base = {"mode": "observe", "window_minutes": window_min, "applied_at_s": applied_s, "caveats": list(CAVEATS)}
    if as_of_s < post_b:
        return {**base, "status": "window_not_elapsed", "ready_in_minutes": (post_b - as_of_s) / 60.0,
                "reason": f"The {window_min:g}-minute window after the change has not finished yet "
                          f"({(post_b - as_of_s) / 60.0:.1f} min to go)."}
    pre, pre_s, pre_w = window_metrics(h, pre_a, applied_s)
    post, post_s, post_w = window_metrics(h, applied_s, post_b)
    if pre["customers_served"] < MIN_CUSTOMERS or post["customers_served"] < MIN_CUSTOMERS:
        return {**base, "status": "insufficient_data", "pre": pre, "post": post,
                "reason": f"At least {MIN_CUSTOMERS} customers must have started service in both windows "
                          f"(before: {pre['customers_served']}, after: {post['customers_served']})."}
    observed = pre["avg_wait_min"] - post["avg_wait_min"]
    interval = reduction_interval(_block_means(pre_s, pre_w, pre_a), _block_means(post_s, post_w, applied_s))
    confounders = []
    ra, rb = pre["arrival_rate_per_min"], post["arrival_rate_per_min"]
    rate_change = None if not ra else rb / ra - 1.0
    if rate_change is not None and abs(rate_change) >= 0.15:
        confounders.append(f"The arrival rate changed by {rate_change:+.0%} between the windows, so part of the "
                           "difference may come from demand rather than the intervention.")
    clash = [t for t in (other_applied_s or []) if pre_a <= t <= post_b and abs(t - applied_s) > 1.0]
    if clash:
        confounders.append(f"{len(clash)} other intervention(s) were applied within these windows; their effects "
                           "cannot be separated.")
    comparison = compare(observed, interval, expected_reduction_min)
    return {**base, "status": "ok", "pre": pre, "post": post, "observed_wait_reduction_min": observed,
            "reduction_interval95": interval, "arrival_rate_change": rate_change, "confounders": confounders,
            "other_interventions_in_window": len(clash), "comparison": comparison,
            "clean_for_calibration": not confounders}


def compare(observed: float, interval: dict[str, Any] | None, expected: float | None) -> dict[str, Any]:
    """Observed vs expected wait reduction. `verdict` is descriptive only."""
    if expected is None:
        return {"expected_wait_reduction_min": None, "error_min": None, "verdict": "no_expectation"}
    err = observed - expected
    if abs(err) < SIGNIFICANT_ERROR_MIN:
        verdict = "as_expected"
    elif interval is not None and interval["low"] <= expected <= interval["high"]:
        verdict = "consistent_with_expectation"
    else:
        verdict = "better_than_expected" if err > 0 else "worse_than_expected"
    return {"expected_wait_reduction_min": expected, "observed_wait_reduction_min": observed, "error_min": err,
            "abs_error_min": abs(err), "verdict": verdict,
            "relative_error": None if expected == 0 else err / abs(expected)}


def manual_outcome(observed: dict[str, Any], baseline_avg_wait_min: float | None,
                   expected_reduction_min: float | None) -> dict[str, Any]:
    """Figures typed in by an operator. Stored as reported, never as a measurement."""
    out = {"status": "ok", "mode": "manual", "reported": observed, "caveats": [
        "Reported by an operator; LineZero did not measure these figures.", *CAVEATS[1:]]}
    if baseline_avg_wait_min is not None:
        reduction = baseline_avg_wait_min - observed["avg_wait_min"]
        out["observed_wait_reduction_min"] = reduction
        out["reduction_basis"] = "simulated baseline average wait minus the reported average wait"
        out["comparison"] = compare(reduction, None, expected_reduction_min)
    out["clean_for_calibration"] = False
    return out


def learning_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate recorded outcomes. Only verified real observations enter the error statistics; synthetic and
    operator-reported ones are counted but kept apart. `rows`: dicts with verification, expected_reduction_min,
    observed_reduction_min, type."""
    def stats(sub: list[dict[str, Any]]) -> dict[str, Any]:
        errs = [r["observed"] - r["expected"] for r in sub if r["observed"] is not None and r["expected"] is not None]
        if not errs:
            return {"n": 0}
        e = np.asarray(errs, dtype=float)
        return {"n": int(len(e)), "mean_error_min": float(e.mean()), "mean_abs_error_min": float(np.abs(e).mean()),
                "over_optimistic": int((e < -SIGNIFICANT_ERROR_MIN).sum()),
                "under_optimistic": int((e > SIGNIFICANT_ERROR_MIN).sum()),
                "as_expected": int((np.abs(e) <= SIGNIFICANT_ERROR_MIN).sum())}
    by_kind = {k: [r for r in rows if r["verification"] == k] for k in
               ("verified_real_observation", "synthetic_observation", "operator_reported")}
    verified = stats(by_kind["verified_real_observation"])
    by_type: dict[str, Any] = {}
    for t in sorted({r["type"] for r in by_kind["verified_real_observation"]}):
        by_type[t] = stats([r for r in by_kind["verified_real_observation"] if r["type"] == t])
    return {"counts": {k: len(v) for k, v in by_kind.items()}, "verified_real": verified, "by_type": by_type,
            "synthetic": stats(by_kind["synthetic_observation"]), "operator_reported": stats(by_kind["operator_reported"])}


__all__ = ["observe", "manual_outcome", "compare", "learning_summary", "verification_label", "window_metrics",
           "reduction_interval", "MIN_CUSTOMERS", "CAVEATS"]
