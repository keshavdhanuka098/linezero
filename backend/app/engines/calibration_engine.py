"""Adaptive calibration of the Digital Twin's arrival and service parameters.

Pure computation: no database, no HTTP. Inputs are the observation frame produced by
`prediction_engine.prepare_history` (one row per customer: arrival / start / end / left / counter_id) and the queue's
counters. Everything returned is JSON-friendly.

What is calibrated
------------------
* arrival rate  lambda  (customers / minute)  - Gamma-Poisson posterior over the training window;
* service rate  mu      (customers / minute / counter) - Gamma posterior for exponential service durations, pooled
                         and per counter (per-counter estimates are shrunk toward the pooled one).

Both use a conjugate Gamma update with the *active calibration version as the prior*, whose weight is capped
(`prior_arrival_minutes`, `prior_service_pseudo_n`). New observations therefore move the parameters without blindly
overwriting them, and one noisy window cannot erase what was learned earlier. With no previous version there is no
prior and the posterior mean is the maximum-likelihood estimate.

How a candidate is accepted
---------------------------
1. Served customers are split *chronologically*: the earliest ones are the training window, the latest
   `validation_fraction` the validation window.
2. Parameters are fitted using only information that existed at the end of the training window (arrivals up to the
   cut-off, services that had *finished* by the cut-off).
3. Both the candidate and the incumbent (the active version, or the counters' configured nominal rates when no
   version exists) predict the wait of every validation customer from the queue state that customer actually saw on
   arrival (state reconstruction uses only events before that arrival).
4. The candidate is accepted only if enough validation customers exist and its MAE beats the incumbent's by at least
   `min_improvement_pct`. A paired 95% interval on the per-customer absolute-error difference is reported with the
   decision.

Prediction model ("twin wait estimate"): a customer who sees L people waiting and `busy` of `c` counters serving
needs max(L + 1 - (c - busy), 0) service completions; with total capacity mu_total the expected time is
needed / mu_total. It is the same first-moment formula as `prediction_engine.baseline_wait`.

Limits (also returned to the client): the counters currently active are assumed to have been active throughout the
history; customers who are still waiting have no observed wait yet, so validation is right-censored; a Gamma/exponential
service model is an assumption.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.engines import prediction_engine as pe
from app.engines.twin_scenarios import paired_stat

MIN_TRAIN_ARRIVALS = 20
MIN_TRAIN_SERVICES = 20
MIN_VALIDATION = pe.MIN_VALIDATION_SAMPLES  # 30
MIN_COUNTER_SAMPLES = 10
MAPE_FLOOR_S = 30.0  # MAPE is only defined where the actual wait is meaningfully > 0
CONFIDENCE_FULL_VALIDATION_N = 100
COUNTER_SHRINK_PSEUDO_N = 5.0
MAX_SERIES_POINTS = 300
CONFIDENCE_FORMULA = ("confidence = min(1, n_validation / 100) x (1 - min(1, relative half-width of the 95% interval "
                      "of the pooled service rate))")


@dataclass(frozen=True)
class CalibrationSettings:
    validation_fraction: float = 0.3
    min_improvement_pct: float = 1.0
    prior_arrival_minutes: float = 60.0
    prior_service_pseudo_n: float = 10.0
    lookback_minutes: float | None = None
    #: epoch-second windows whose arrivals must not inform the arrival rate (e.g. traffic was deliberately diverted)
    exclude_arrival_windows: tuple[tuple[float, float], ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not 0.1 <= self.validation_fraction <= 0.5:
            raise ValueError("validation_fraction must be between 0.1 and 0.5")
        if self.min_improvement_pct < 0 or self.min_improvement_pct > 100:
            raise ValueError("min_improvement_pct must be between 0 and 100")
        if self.prior_arrival_minutes < 0 or self.prior_service_pseudo_n < 0:
            raise ValueError("prior strengths must be >= 0")
        if self.lookback_minutes is not None and self.lookback_minutes <= 0:
            raise ValueError("lookback_minutes must be > 0")


# --------------------------------------------------------------------------- parameters
def nominal_parameters(counters: list[dict[str, Any]]) -> dict[str, Any]:
    """The configured (not learned) parameters: each counter's service_rate from the database."""
    rates = {str(c["id"]): float(c["service_rate"]) for c in counters if c["status"] == "active"}
    pooled = float(np.mean(list(rates.values()))) if rates else None
    return {"arrival_rate_per_min": None, "service_rate_per_min": pooled, "counter_service_rates": rates,
            "source": "nominal_configuration"}


def capacity_per_min(params: dict[str, Any], counters: list[dict[str, Any]]) -> float:
    """Total service capacity of the currently active counters under `params`."""
    pooled = params.get("service_rate_per_min")
    per = params.get("counter_service_rates") or {}
    total = 0.0
    for c in counters:
        if c["status"] != "active":
            continue
        rate = per.get(str(c["id"]), pooled)
        total += float(rate if rate is not None else c["service_rate"])
    return total


def _gamma_interval(shape: float, rate: float, level: float = 0.95) -> tuple[float, float]:
    lo = sps.gamma.ppf((1 - level) / 2, a=shape, scale=1.0 / rate)
    hi = sps.gamma.ppf(1 - (1 - level) / 2, a=shape, scale=1.0 / rate)
    return float(lo), float(hi)


def _excluded_overlap_s(t0: float, t1: float, windows: tuple[tuple[float, float], ...]) -> float:
    total = 0.0
    for a, b in sorted(windows):
        lo, hi = max(a, t0), min(b, t1)
        if hi > lo:
            total += hi - lo
    return total


def _in_windows(t: np.ndarray, windows: tuple[tuple[float, float], ...]) -> np.ndarray:
    mask = np.zeros(len(t), dtype=bool)
    for a, b in windows:
        mask |= (t >= a) & (t <= b)
    return mask


def estimate_parameters(
    h: pd.DataFrame, t_start_s: float, t_end_s: float, prior: dict[str, Any] | None, settings: CalibrationSettings,
) -> dict[str, Any]:
    """Posterior estimates using ONLY observations inside [t_start_s, t_end_s].

    Arrivals count if they arrived in the window; service durations count if the service *finished* in the window
    (so nothing that happened after `t_end_s` leaks in)."""
    arr = pe.to_seconds(h["arrival"]) if len(h) else np.array([])
    st = pe.to_seconds(h["start"]) if len(h) else np.array([])
    en = pe.to_seconds(h["end"]) if len(h) else np.array([])

    # ---- arrival rate
    in_win = (arr >= t_start_s) & (arr <= t_end_s)
    excl = settings.exclude_arrival_windows
    if excl:
        in_win &= ~_in_windows(arr, excl)
    n_arr = int(in_win.sum())
    exposure_min = max((t_end_s - t_start_s) - _excluded_overlap_s(t_start_s, t_end_s, excl), 0.0) / 60.0
    lam = None
    arrival_est: dict[str, Any] = {"n": n_arr, "exposure_min": exposure_min, "status": "insufficient_data",
                                   "min_required": MIN_TRAIN_ARRIVALS}
    if n_arr >= MIN_TRAIN_ARRIVALS and exposure_min > 0:
        a0 = b0 = 0.0
        prior_lam = (prior or {}).get("arrival_rate_per_min")
        if prior_lam and settings.prior_arrival_minutes > 0:
            a0, b0 = prior_lam * settings.prior_arrival_minutes, settings.prior_arrival_minutes
        shape, rate = a0 + n_arr, b0 + exposure_min
        lam = shape / rate
        lo, hi = _gamma_interval(shape, rate)
        arrival_est.update(status="ok", mean=lam, ci95=[lo, hi], prior_used=bool(a0),
                           mle=n_arr / exposure_min)

    # ---- service rates
    m = np.isfinite(st) & np.isfinite(en) & (en >= t_start_s) & (en <= t_end_s)
    dur_min = np.where(m, (en - st) / 60.0, np.nan)
    ok = m & np.isfinite(dur_min) & (dur_min > 0)
    n_srv = int(ok.sum())
    mu = None
    service_est: dict[str, Any] = {"n": n_srv, "status": "insufficient_data", "min_required": MIN_TRAIN_SERVICES}
    pooled_shape = pooled_rate = None
    if n_srv >= MIN_TRAIN_SERVICES:
        s = float(dur_min[ok].sum())
        a0 = b0 = 0.0
        prior_mu = (prior or {}).get("service_rate_per_min")
        if prior_mu and settings.prior_service_pseudo_n > 0:
            a0, b0 = settings.prior_service_pseudo_n, settings.prior_service_pseudo_n / prior_mu
        pooled_shape, pooled_rate = a0 + n_srv, b0 + s
        mu = pooled_shape / pooled_rate
        lo, hi = _gamma_interval(pooled_shape, pooled_rate)
        service_est.update(status="ok", mean=mu, ci95=[lo, hi], prior_used=bool(a0), mle=n_srv / s,
                           mean_service_time_min=1.0 / mu)

    per_counter: dict[str, float] = {}
    counter_est: dict[str, Any] = {}
    if pooled_shape is not None and "counter_id" in h:
        cid = h["counter_id"].to_numpy(dtype=float) if len(h) else np.array([])
        for c in sorted({int(x) for x in cid[ok] if np.isfinite(x)}):
            sel = ok & (cid == c)
            n_c = int(sel.sum())
            if n_c < MIN_COUNTER_SAMPLES:
                counter_est[str(c)] = {"n": n_c, "status": "insufficient_data", "min_required": MIN_COUNTER_SAMPLES}
                continue
            a0 = COUNTER_SHRINK_PSEUDO_N
            b0 = a0 / mu  # shrink toward the pooled posterior mean
            shape, rate = a0 + n_c, b0 + float(dur_min[sel].sum())
            per_counter[str(c)] = shape / rate
            lo, hi = _gamma_interval(shape, rate)
            counter_est[str(c)] = {"n": n_c, "status": "ok", "mean": shape / rate, "ci95": [lo, hi]}

    return {
        "parameters": {"arrival_rate_per_min": lam, "service_rate_per_min": mu, "counter_service_rates": per_counter},
        "estimates": {"arrival": arrival_est, "service": service_est, "counters": counter_est},
        "n_arrivals": n_arr, "n_services": n_srv, "exposure_min": exposure_min,
    }


# --------------------------------------------------------------------------- prediction + metrics
def predict_wait_s(queue_ahead: np.ndarray, busy: np.ndarray, active: int, capacity: float) -> np.ndarray:
    """Expected wait (seconds) for customers who saw `queue_ahead` waiting and `busy` counters serving."""
    if capacity <= 0 or active <= 0:
        return np.full(len(queue_ahead), np.nan)
    idle = np.maximum(active - busy, 0)
    needed = np.maximum(queue_ahead + 1 - idle, 0)
    return needed / capacity * 60.0


def build_eval_frame(h: pd.DataFrame, active_counters: int, nominal_rate_total: float) -> pd.DataFrame:
    """One row per served customer: the queue state they saw on arrival and the wait they actually experienced."""
    cols = ["arrival_s", "actual_wait_s", "queue_ahead", "busy"]
    if len(h) == 0 or active_counters == 0:
        return pd.DataFrame(columns=cols)
    st = pe.to_seconds(h["start"])
    arr = pe.to_seconds(h["arrival"])
    rows = np.where(np.isfinite(st))[0]
    if len(rows) == 0:
        return pd.DataFrame(columns=cols)
    ctx = pe.HistoryContext(active_counters, max(nominal_rate_total, 1e-9))
    f = pe.compute_features(h, arr[rows], ctx, self_rows=rows)
    out = pd.DataFrame({
        "arrival_s": arr[rows], "actual_wait_s": (st - arr)[rows],
        "queue_ahead": f["queue_ahead"].to_numpy(float), "busy": f["busy_counters"].to_numpy(float),
    })
    return out[np.isfinite(out["actual_wait_s"]) & (out["actual_wait_s"] >= 0)].reset_index(drop=True)


def error_summary(actual_s: np.ndarray, predicted_s: np.ndarray) -> dict[str, Any]:
    """MAE, RMSE, bias and MAPE (seconds). MAPE only uses customers whose actual wait >= MAPE_FLOOR_S, because a
    percentage error is undefined at zero and meaningless for near-zero waits; `mape_n` says how many were usable."""
    a, p = np.asarray(actual_s, float), np.asarray(predicted_s, float)
    base = pe.error_metrics(a, p)
    keep = np.isfinite(a) & np.isfinite(p) & (a >= MAPE_FLOOR_S)
    mape_n = int(keep.sum())
    mape = float(np.mean(np.abs(p[keep] - a[keep]) / a[keep]) * 100.0) if mape_n else None
    return {**base, "mape_pct": mape, "mape_n": mape_n, "mape_floor_s": MAPE_FLOOR_S,
            "mean_actual_wait_s": float(np.nanmean(a)) if base["n"] else None}


def residual_band(actual_s: np.ndarray, predicted_s: np.ndarray) -> dict[str, Any] | None:
    return pe.residual_interval(actual_s, predicted_s)


def confidence_of(n_validation: int, service_est: dict[str, Any]) -> dict[str, Any]:
    """Transparent model-confidence score in [0, 1] (see CONFIDENCE_FORMULA)."""
    sufficiency = min(1.0, n_validation / CONFIDENCE_FULL_VALIDATION_N)
    precision = 0.0
    if service_est.get("status") == "ok":
        lo, hi = service_est["ci95"]
        precision = 1.0 - min(1.0, (hi - lo) / (2.0 * service_est["mean"]))
    return {"value": float(sufficiency * precision), "formula": CONFIDENCE_FORMULA,
            "components": {"data_sufficiency": float(sufficiency), "service_rate_precision": float(precision),
                           "n_validation": int(n_validation)}}


def downsample_series(eval_df: pd.DataFrame, pred_s: np.ndarray, other_pred_s: np.ndarray | None = None,
                      limit: int = MAX_SERIES_POINTS) -> list[dict[str, Any]]:
    """Evenly thinned (time, actual, predicted[, other model's predicted]) points for charts, wait in minutes."""
    n = len(eval_df)
    if n == 0:
        return []
    idx = np.unique(np.linspace(0, n - 1, min(n, limit)).round().astype(int))
    rows = []
    for i in idx:
        row = {"t": float(eval_df["arrival_s"].iloc[i]), "actual_min": float(eval_df["actual_wait_s"].iloc[i] / 60.0),
               "predicted_min": float(pred_s[i] / 60.0)}
        if other_pred_s is not None:
            row["incumbent_min"] = float(other_pred_s[i] / 60.0)
        rows.append(row)
    return rows


def binned_errors(eval_df: pd.DataFrame, pred_s: np.ndarray, bins: int = 12) -> list[dict[str, Any]]:
    """MAE per equal-time bin: shows whether prediction error changes over time."""
    n = len(eval_df)
    if n < 2 * bins:
        bins = max(1, n // 5)
    if n == 0 or bins < 1:
        return []
    t = eval_df["arrival_s"].to_numpy(float)
    edges = np.linspace(t.min(), t.max() + 1e-6, bins + 1)
    out = []
    for i in range(bins):
        sel = (t >= edges[i]) & (t < edges[i + 1])
        if not sel.any():
            continue
        err = np.abs(pred_s[sel] - eval_df["actual_wait_s"].to_numpy(float)[sel])
        out.append({"start": float(edges[i]), "end": float(edges[i + 1]), "n": int(sel.sum()),
                    "mae_s": float(err.mean())})
    return out


def evaluate_model(params: dict[str, Any], eval_df: pd.DataFrame, counters: list[dict[str, Any]]) -> dict[str, Any]:
    active = sum(1 for c in counters if c["status"] == "active")
    cap = capacity_per_min(params, counters)
    pred = predict_wait_s(eval_df["queue_ahead"].to_numpy(float), eval_df["busy"].to_numpy(float), active, cap)
    return {"predicted_s": pred, "capacity_per_min": cap,
            "metrics": error_summary(eval_df["actual_wait_s"].to_numpy(float), pred)}


# --------------------------------------------------------------------------- the calibration run
def calibrate(
    h: pd.DataFrame, counters: list[dict[str, Any]], previous: dict[str, Any] | None, settings: CalibrationSettings,
) -> dict[str, Any]:
    """Fit a candidate calibration, validate it against the incumbent and decide. Never mutates anything."""
    settings.validate()
    incumbent_label = "active_calibration" if previous else "nominal_configuration"
    incumbent = previous if previous else nominal_parameters(counters)
    out: dict[str, Any] = {
        "decision": "insufficient_data", "accepted": False, "reasons": [], "incumbent_label": incumbent_label,
        "incumbent_parameters": incumbent, "candidate_parameters": None, "estimates": None,
        "settings": {"validation_fraction": settings.validation_fraction,
                     "min_improvement_pct": settings.min_improvement_pct,
                     "prior_arrival_minutes": settings.prior_arrival_minutes,
                     "prior_service_pseudo_n": settings.prior_service_pseudo_n,
                     "lookback_minutes": settings.lookback_minutes,
                     "excluded_arrival_windows": len(settings.exclude_arrival_windows)},
    }
    active = sum(1 for c in counters if c["status"] == "active")
    if active == 0:
        out["reasons"].append("The queue has no active counters, so waits cannot be modelled.")
        return out
    if len(h) == 0:
        out["reasons"].append("No observations exist for this queue.")
        return out

    arr = pe.to_seconds(h["arrival"])
    all_times = np.concatenate([arr, pe.to_seconds(h["start"]), pe.to_seconds(h["end"])])
    as_of = float(np.max(all_times[np.isfinite(all_times)]))
    if settings.lookback_minutes is not None:
        keep = arr >= as_of - settings.lookback_minutes * 60.0
        h = h[keep].reset_index(drop=True)
        arr = pe.to_seconds(h["arrival"])
    served_mask = np.isfinite(pe.to_seconds(h["start"])) if len(h) else np.array([], bool)
    n_served = int(served_mask.sum())
    out["n_served_observations"] = n_served
    if n_served < MIN_TRAIN_SERVICES + MIN_VALIDATION:
        out["reasons"].append(
            f"Only {n_served} served customers are available; at least {MIN_TRAIN_SERVICES + MIN_VALIDATION} are "
            f"needed ({MIN_TRAIN_SERVICES} to fit and {MIN_VALIDATION} to validate).")
        return out

    nominal_total = float(sum(c["service_rate"] for c in counters if c["status"] == "active"))
    evf = build_eval_frame(h, active, nominal_total)
    served_arr = np.sort(evf["arrival_s"].to_numpy(float))
    k = int(math.floor(len(served_arr) * (1.0 - settings.validation_fraction)))
    k = min(max(k, 1), len(served_arr) - 1)
    cutoff = float(served_arr[k - 1])
    t_start = float(np.nanmin(arr))
    train_n_served = int((served_arr <= cutoff).sum())
    valid = evf[evf["arrival_s"] > cutoff].reset_index(drop=True)
    out["windows"] = {"training_start_s": t_start, "training_end_s": cutoff,
                      "validation_start_s": float(valid["arrival_s"].min()) if len(valid) else None,
                      "validation_end_s": float(valid["arrival_s"].max()) if len(valid) else None}
    out["n_train_served"], out["n_validation"] = train_n_served, int(len(valid))
    if len(valid) < MIN_VALIDATION:
        out["reasons"].append(f"Only {len(valid)} validation customers; at least {MIN_VALIDATION} are required.")
        return out

    fit = estimate_parameters(h, t_start, cutoff, previous, settings)
    out["estimates"] = fit["estimates"]
    out["n_train_arrivals"], out["n_train_services"] = fit["n_arrivals"], fit["n_services"]
    cand = fit["parameters"]
    if cand["service_rate_per_min"] is None:
        out["reasons"].append(
            f"Only {fit['n_services']} completed services finished inside the training window; "
            f"at least {MIN_TRAIN_SERVICES} are needed to estimate a service rate.")
        return out
    if cand["arrival_rate_per_min"] is None and previous:
        cand["arrival_rate_per_min"] = previous.get("arrival_rate_per_min")  # keep what was learned earlier
        out["reasons"].append("Arrival rate not re-estimated (too few training arrivals); previous value kept.")
    out["candidate_parameters"] = {**cand, "source": "calibration"}

    cand_eval = evaluate_model(cand, valid, counters)
    inc_eval = evaluate_model(incumbent, valid, counters)
    actual = valid["actual_wait_s"].to_numpy(float)
    cm, im = cand_eval["metrics"], inc_eval["metrics"]
    err_c = np.abs(cand_eval["predicted_s"] - actual)
    err_i = np.abs(inc_eval["predicted_s"] - actual)
    paired = paired_stat(list(err_i), list(err_c))  # mean_diff < 0 means the candidate has lower error
    improvement_pct = None
    if im["mae_s"] and im["mae_s"] > 0:
        improvement_pct = (im["mae_s"] - cm["mae_s"]) / im["mae_s"] * 100.0
    out.update({
        "candidate_metrics": cm, "incumbent_metrics": im, "paired_abs_error_diff_s": paired,
        "mae_improvement_pct": improvement_pct,
        "candidate_capacity_per_min": cand_eval["capacity_per_min"],
        "incumbent_capacity_per_min": inc_eval["capacity_per_min"],
        "series": downsample_series(valid, cand_eval["predicted_s"], inc_eval["predicted_s"]),
        "binned_errors": binned_errors(valid, cand_eval["predicted_s"]),
        "uncertainty": {"residual_interval_s": residual_band(actual, cand_eval["predicted_s"]),
                        "arrival_rate_ci95": (fit["estimates"]["arrival"].get("ci95")),
                        "service_rate_ci95": (fit["estimates"]["service"].get("ci95"))},
        "confidence": confidence_of(len(valid), fit["estimates"]["service"]),
    })

    if improvement_pct is None:
        out["reasons"].append("The incumbent has zero validation error; no improvement is possible.")
        accepted = False
    else:
        accepted = improvement_pct >= settings.min_improvement_pct and cm["mae_s"] < im["mae_s"]
        verb = "improved" if improvement_pct > 0 else "did not improve"
        out["reasons"].append(
            f"Validation MAE {verb}: {im['mae_s'] / 60:.2f} min ({incumbent_label.replace('_', ' ')}) -> "
            f"{cm['mae_s'] / 60:.2f} min (candidate), {improvement_pct:+.1f}% on {len(valid)} held-out customers; "
            f"required at least {settings.min_improvement_pct:g}%.")
        if paired and not paired["significant"] and accepted:
            out["reasons"].append("The paired 95% interval on the error difference includes zero, so the gain may be "
                                  "within noise.")
    out["accepted"] = bool(accepted)
    out["decision"] = "accepted" if accepted else "rejected"
    out["limitations"] = [
        "Counters currently active are assumed to have been active for the whole history.",
        "Customers still waiting have no observed wait yet, so validation is right-censored (long waits are under-represented).",
        "Service durations are modelled as exponential; per-counter rates are shrunk toward the pooled rate.",
    ]
    return out


__all__ = [
    "CalibrationSettings", "calibrate", "estimate_parameters", "nominal_parameters", "capacity_per_min",
    "predict_wait_s", "build_eval_frame", "error_summary", "evaluate_model", "confidence_of", "downsample_series",
    "binned_errors", "MAPE_FLOOR_S", "MIN_VALIDATION", "MIN_TRAIN_SERVICES",
]
