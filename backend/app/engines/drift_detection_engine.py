"""Operational distribution-drift detection.

Compares a *reference* window (what the model was calibrated on) with a *recent* window and tests three signals:

  arrival_rate  - exact conditional binomial test: given the total number of arrivals in both windows, the share that
                  falls in the recent window should equal its share of the observed time if the rate is unchanged;
  service_time  - two-sample Kolmogorov-Smirnov test on service durations (customers whose service finished in each
                  window), effect = relative change of the mean;
  waiting_time  - Welch t-test on 30-minute BLOCK MEANS of waits (customers whose service started in each window),
                  effect = relative change of the mean (and an absolute change in minutes). Waits of consecutive
                  customers are strongly autocorrelated (a long queue stays long), so testing individual waits as
                  if they were independent makes the test far too eager: in a 40-run check on stationary simulated
                  data a plain KS test flagged 18 runs; block means flagged none of 40 at the same threshold.

A signal counts as *drifted* only if BOTH hold:
  1. the p-value is below alpha / 3 (Bonferroni correction for the three tests), and
  2. the effect is practically meaningful (`min_effect`, default 15% relative; waits also need >= 0.25 min absolute).
With very large samples tiny, harmless differences become "significant"; the effect-size guard prevents alarms for them.

Signals with too few samples are reported as `insufficient_data` instead of being guessed. All times are epoch seconds.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.engines import prediction_engine as pe

MIN_SAMPLES = 30
MIN_ARRIVALS_PER_WINDOW = 10
MIN_ABS_WAIT_CHANGE_MIN = 0.25
WAIT_BLOCK_MIN = 30.0
MIN_WAIT_BLOCKS = 5
MIN_CUSTOMERS_PER_BLOCK = 3


def arrival_rate_test(n_ref: int, t_ref_min: float, n_rec: int, t_rec_min: float) -> dict[str, Any]:
    """Two-sided exact test that the arrival rate is the same in both windows (conditional binomial)."""
    total = n_ref + n_rec
    if t_ref_min <= 0 or t_rec_min <= 0 or n_ref < MIN_ARRIVALS_PER_WINDOW or n_rec < MIN_ARRIVALS_PER_WINDOW // 2:
        return {"status": "insufficient_data", "n_reference": n_ref, "n_recent": n_rec,
                "min_required": MIN_ARRIVALS_PER_WINDOW}
    p0 = t_rec_min / (t_ref_min + t_rec_min)
    res = sps.binomtest(n_rec, total, p0, alternative="two-sided")
    r_ref, r_rec = n_ref / t_ref_min, n_rec / t_rec_min
    return {"status": "ok", "test": "conditional binomial (Poisson rate comparison)", "p_value": float(res.pvalue),
            "reference_rate_per_min": r_ref, "recent_rate_per_min": r_rec, "effect": r_rec / r_ref - 1.0,
            "n_reference": n_ref, "n_recent": n_rec}


def distribution_test(ref: np.ndarray, rec: np.ndarray, name: str, unit_scale: float = 1.0) -> dict[str, Any]:
    ref, rec = ref[np.isfinite(ref)], rec[np.isfinite(rec)]
    if len(ref) < MIN_SAMPLES or len(rec) < MIN_SAMPLES // 2:
        return {"status": "insufficient_data", "n_reference": int(len(ref)), "n_recent": int(len(rec)),
                "min_required": MIN_SAMPLES}
    ks = sps.ks_2samp(ref, rec)
    m_ref, m_rec = float(ref.mean()), float(rec.mean())
    return {"status": "ok", "test": "two-sample Kolmogorov-Smirnov", "statistic": float(ks.statistic),
            "p_value": float(ks.pvalue), "reference_mean": m_ref * unit_scale, "recent_mean": m_rec * unit_scale,
            "effect": (m_rec / m_ref - 1.0) if m_ref > 0 else None, "abs_change": (m_rec - m_ref) * unit_scale,
            "n_reference": int(len(ref)), "n_recent": int(len(rec))}


def wait_block_test(start_s: np.ndarray, wait_min: np.ndarray, reference: tuple[float, float],
                    recent: tuple[float, float]) -> dict[str, Any]:
    """Welch t-test on per-block mean waits, so autocorrelated waits do not inflate the false-alarm rate."""

    def blocks(a: float, b: float, inclusive: bool) -> tuple[np.ndarray, int]:
        m = (start_s >= a) & ((start_s <= b) if inclusive else (start_s < b))
        idx = np.floor((start_s[m] - a) / (WAIT_BLOCK_MIN * 60.0)).astype(int)
        w = wait_min[m]
        means = [float(w[idx == k].mean()) for k in np.unique(idx) if (idx == k).sum() >= MIN_CUSTOMERS_PER_BLOCK]
        return np.array(means), int(m.sum())

    ref_b, n_ref = blocks(*reference, inclusive=False)
    rec_b, n_rec = blocks(*recent, inclusive=True)
    if len(ref_b) < MIN_WAIT_BLOCKS or len(rec_b) < MIN_WAIT_BLOCKS:
        return {"status": "insufficient_data", "n_reference": int(len(ref_b)), "n_recent": int(len(rec_b)),
                "min_required": MIN_WAIT_BLOCKS, "unit": f"{WAIT_BLOCK_MIN:g}-minute blocks"}
    t = sps.ttest_ind(rec_b, ref_b, equal_var=False)
    m_ref, m_rec = float(ref_b.mean()), float(rec_b.mean())
    p = float(t.pvalue) if np.isfinite(t.pvalue) else 1.0
    return {"status": "ok", "test": f"Welch t-test on {WAIT_BLOCK_MIN:g}-minute block means", "statistic": float(t.statistic)
            if np.isfinite(t.statistic) else 0.0, "p_value": p, "reference_mean": m_ref, "recent_mean": m_rec,
            "effect": (m_rec / m_ref - 1.0) if m_ref > 0 else None, "abs_change": m_rec - m_ref,
            "n_reference": int(len(ref_b)), "n_recent": int(len(rec_b)), "customers_reference": n_ref,
            "customers_recent": n_rec, "unit": f"{WAIT_BLOCK_MIN:g}-minute blocks"}


def detect_drift(
    h: pd.DataFrame, reference: tuple[float, float], recent: tuple[float, float], alpha: float = 0.01,
    min_effect: float = 0.15,
) -> dict[str, Any]:
    """`reference` and `recent` are (start_s, end_s) epoch-second windows; they must not overlap."""
    (r0, r1), (c0, c1) = reference, recent
    if not (r0 < r1 and c0 < c1):
        raise ValueError("each window needs start < end")
    if r1 > c0 + 1e-9:
        raise ValueError("the reference window must end before the recent window starts")
    if not 0 < alpha < 1 or min_effect < 0:
        raise ValueError("alpha must be in (0,1) and min_effect >= 0")
    arr = pe.to_seconds(h["arrival"]) if len(h) else np.array([])
    st = pe.to_seconds(h["start"]) if len(h) else np.array([])
    en = pe.to_seconds(h["end"]) if len(h) else np.array([])

    n_ref = int(((arr >= r0) & (arr < r1)).sum())
    n_rec = int(((arr >= c0) & (arr <= c1)).sum())
    signals: dict[str, dict[str, Any]] = {
        "arrival_rate": arrival_rate_test(n_ref, (r1 - r0) / 60.0, n_rec, (c1 - c0) / 60.0),
    }
    dur = (en - st) / 60.0
    ok_d = np.isfinite(dur) & (dur > 0)
    signals["service_time"] = distribution_test(
        dur[ok_d & (en >= r0) & (en < r1)], dur[ok_d & (en >= c0) & (en <= c1)], "service_time")
    wait = (st - arr) / 60.0
    ok_w = np.isfinite(wait) & (wait >= 0)
    signals["waiting_time"] = wait_block_test(st[ok_w], wait[ok_w], (r0, r1), (c0, c1))

    threshold = alpha / 3.0
    for name, s in signals.items():
        if s["status"] != "ok":
            s["drifted"] = False
            continue
        effect = s.get("effect")
        meaningful = effect is not None and abs(effect) >= min_effect
        if name == "waiting_time":
            meaningful = meaningful and abs(s["abs_change"]) >= MIN_ABS_WAIT_CHANGE_MIN
        s["drifted"] = bool(s["p_value"] < threshold and meaningful)
        s["direction"] = None if effect is None else ("increase" if effect > 0 else "decrease")

    evaluated = [s for s in signals.values() if s["status"] == "ok"]
    drifted = [k for k, s in signals.items() if s.get("drifted")]
    if not evaluated:
        status, severity = "insufficient_data", None
    else:
        status = "ok"
        biggest = max((abs(s["effect"]) for s in evaluated if s.get("effect") is not None and s["drifted"]),
                      default=0.0)
        severity = "none" if not drifted else ("high" if len(drifted) >= 2 or biggest >= 0.5 else "moderate")
    return {
        "status": status, "drift_detected": bool(drifted), "severity": severity, "drifted_signals": drifted,
        "signals": signals,
        "windows": {"reference": {"start_s": r0, "end_s": r1, "minutes": (r1 - r0) / 60.0},
                    "recent": {"start_s": c0, "end_s": c1, "minutes": (c1 - c0) / 60.0}},
        "rule": (f"drift = p < {threshold:.4g} (alpha {alpha:g} / 3 tests) AND |relative effect| >= "
                 f"{min_effect:.0%}" + f" (waits also need >= {MIN_ABS_WAIT_CHANGE_MIN:g} min absolute change)"),
        "alpha": alpha, "min_effect": min_effect,
    }


def default_windows(h: pd.DataFrame, reference_end_s: float | None = None) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Reference = everything up to `reference_end_s` (the active calibration's training end); recent = everything
    after it. Without a calibration, split the history at the 60% mark of arrivals. None if there is no data."""
    if len(h) == 0:
        return None
    arr = pe.to_seconds(h["arrival"])
    arr = arr[np.isfinite(arr)]
    if len(arr) < 2:
        return None
    t0, t1 = float(arr.min()), float(arr.max())
    if reference_end_s is None or not (t0 < reference_end_s < t1):
        reference_end_s = float(np.quantile(arr, 0.6))
    if not (t0 < reference_end_s < t1) or math.isclose(reference_end_s, t1):
        return None
    return (t0, reference_end_s), (reference_end_s, t1)


__all__ = ["detect_drift", "default_windows", "arrival_rate_test", "distribution_test"]
