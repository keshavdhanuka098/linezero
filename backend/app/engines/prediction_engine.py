"""Waiting-time prediction: a transparent statistical baseline plus an optional, honestly-validated ML layer.

Pure computation (NumPy / Pandas / scikit-learn): no database, no HTTP. The service layer loads history into a
DataFrame (see `prepare_history`) and calls into this module.

Units: every duration is in SECONDS except rates, which are customers per MINUTE (matching ServiceCounter.service_rate).

Design rules (from the brief):
  * The baseline is always available and always explainable (see `baseline_wait`).
  * ML models are trained only on real history, evaluated on a chronological hold-out set, and used for a
    prediction only if they beat the baseline on that hold-out set by a margin. Otherwise the baseline is used and
    the response says why. Nothing here reports an accuracy figure that was not measured on held-out data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

import numpy as np
import pandas as pd

from app.engines.queueing_theory import mmc

METHOD_BASELINE = "statistical_baseline"
METHOD_LINEAR = "linear_regression"
METHOD_FOREST = "random_forest"

MIN_OBSERVED_SERVICE_SAMPLES = 10
ROLLING_SERVICE_WINDOW = 50
ROLLING_WAIT_WINDOW = 20
MIN_HOUR_SAMPLES = 5
ARRIVAL_WINDOW_S = 1800.0
MIN_ARRIVAL_SPAN_S = 300.0
MIN_TRAIN_SAMPLES = 100
MIN_VALIDATION_SAMPLES = 30
MIN_INTERVAL_SAMPLES = 30
IMPROVEMENT_REQUIRED = 0.95
MAX_TRAIN_ROWS = 5000
TRAIN_FRACTION = 0.70
INTERVAL_QUANTILES = (0.10, 0.90)

FEATURES = [
    "queue_ahead", "busy_counters", "active_counters", "avg_service_time_s", "arrival_rate_per_min",
    "load_ratio", "hour_sin", "hour_cos", "hist_hour_mean_wait_s", "recent_avg_wait_s", "baseline_wait_s",
]

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


class PredictionInputError(ValueError):
    """The supplied inputs are invalid (maps to HTTP 422). `.problems` lists every issue found."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class PredictionUnavailable(Exception):
    """Inputs are valid but no finite prediction exists (maps to HTTP 409), e.g. no active counters."""


@dataclass
class BaselineInputs:
    queue_length: int
    active_counters: int
    busy_counters: int = 0
    counter_rates_per_min: Sequence[float] = ()
    observed_mean_service_s: float | None = None
    observed_service_samples: int = 0
    arrival_rate_per_min: float | None = None


def _finite_number(x: Any) -> bool:
    return isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool) and math.isfinite(x)


def validate_inputs(inp: BaselineInputs) -> None:
    """Raise PredictionInputError listing every problem; return None if the inputs are usable."""
    problems: list[str] = []
    for name in ("queue_length", "active_counters", "busy_counters"):
        v = getattr(inp, name)
        if not _finite_number(v) or int(v) != v or v < 0:
            problems.append(f"{name} must be a non-negative integer (got {v!r})")
    if not problems and inp.busy_counters > inp.active_counters:
        problems.append(
            f"busy_counters ({inp.busy_counters}) cannot exceed active_counters ({inp.active_counters})"
        )
    rates = list(inp.counter_rates_per_min or [])
    if any((not _finite_number(r)) or r <= 0 for r in rates):
        problems.append("counter_rates_per_min must all be finite numbers > 0")
    elif rates and not problems and len(rates) != inp.active_counters:
        problems.append(
            f"counter_rates_per_min has {len(rates)} entries but active_counters is {inp.active_counters}"
        )
    if inp.observed_mean_service_s is not None and (
        not _finite_number(inp.observed_mean_service_s) or inp.observed_mean_service_s <= 0
    ):
        problems.append("observed_mean_service_s must be a finite number > 0")
    if inp.arrival_rate_per_min is not None and (
        not _finite_number(inp.arrival_rate_per_min) or inp.arrival_rate_per_min < 0
    ):
        problems.append("arrival_rate_per_min must be a finite number >= 0")
    if not problems:
        has_observed = (
            inp.observed_mean_service_s is not None and inp.observed_service_samples >= MIN_OBSERVED_SERVICE_SAMPLES
        )
        if inp.active_counters > 0 and not rates and not has_observed:
            problems.append(
                "a service-speed source is required: provide counter_rates_per_min, or observed_mean_service_s "
                f"with at least {MIN_OBSERVED_SERVICE_SAMPLES} samples"
            )
    if problems:
        raise PredictionInputError(problems)


def baseline_wait(inp: BaselineInputs) -> dict[str, Any]:
    """Expected wait (seconds) for a customer who joins the line now.

    A customer with L people ahead starts service at the (L + 1 - idle)-th service completion (a counter that is
    already idle can take someone immediately). With total service rate mu (customers/min) summed over the active
    counters and memoryless-in-the-mean service, the expected time for k completions is k / mu, so

        wait = max(L + 1 - idle, 0) / mu * 60 seconds.

    mu is the sum of the active counters' nominal rates, or - once at least 10 recent services have been observed -
    active_counters / observed_mean_service. This is a first-moment approximation: it ignores service-time
    variability and counters that change state during the wait. It is a point estimate, not a guarantee.
    """
    validate_inputs(inp)
    if inp.active_counters == 0:
        raise PredictionUnavailable("There are no active counters, so no finite waiting time can be predicted")
    use_observed = (
        inp.observed_mean_service_s is not None and inp.observed_service_samples >= MIN_OBSERVED_SERVICE_SAMPLES
    )
    if use_observed:
        mu = inp.active_counters / (inp.observed_mean_service_s / 60.0)
        source = "observed_recent_service_times"
        mean_service_s = float(inp.observed_mean_service_s)
    else:
        mu = float(sum(inp.counter_rates_per_min))
        source = "nominal_counter_rates"
        mean_service_s = inp.active_counters / mu * 60.0
    idle = max(inp.active_counters - inp.busy_counters, 0)
    completions_needed = max(inp.queue_length + 1 - idle, 0)
    seconds = completions_needed / mu * 60.0

    out: dict[str, Any] = {
        "waiting_time_s": float(seconds), "completions_needed": int(completions_needed),
        "idle_counters": int(idle), "service_capacity_per_min": float(mu),
        "mean_service_time_s": float(mean_service_s), "service_time_source": source,
    }
    if inp.arrival_rate_per_min is not None:
        rho = inp.arrival_rate_per_min / mu
        out["arrival_rate_per_min"] = float(inp.arrival_rate_per_min)
        out["load_ratio"] = float(rho)
        out["overloaded"] = bool(rho >= 1.0)
        if rho < 1.0 and inp.arrival_rate_per_min > 0:
            ref = mmc(inp.arrival_rate_per_min, mu / inp.active_counters, inp.active_counters)
            if ref.get("stable"):
                out["steady_state_reference_wait_s"] = float(ref["avg_waiting_time"] * 60.0)
    return out


def to_seconds(series: pd.Series) -> np.ndarray:
    """Timezone-aware datetimes -> float epoch seconds (NaT -> NaN), independent of pandas' datetime unit."""
    s = pd.to_datetime(series, utc=True)
    return (s - EPOCH).dt.total_seconds().to_numpy(dtype=float)


def prepare_history(entries: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Normalise a queue's entries into the frame the feature builder expects.

    Required columns: status, arrival, start, end, left (datetimes; NaT when unknown / not applicable).
      * waiting            -> still in line (no start, no left)
      * serving            -> started, not finished
      * completed          -> started and finished
      * abandoned/removed  -> `left` is when they left the line; rows without it are dropped because we cannot tell
                              whether they were still ahead of a later customer.
    """
    h = entries.copy()
    for c in ("arrival", "start", "end", "left"):
        h[c] = pd.to_datetime(h[c], utc=True)
    left_line = h["status"].isin(["abandoned", "removed"])
    unknown = left_line & h["left"].isna()
    stats = {"rows_in": int(len(h)), "dropped_unknown_departure": int(unknown.sum())}
    h = h[~unknown].sort_values("arrival").reset_index(drop=True)
    stats["rows_used"] = int(len(h))
    return h, stats


@dataclass
class HistoryContext:
    active_counters: int
    nominal_total_rate_per_min: float


def compute_features(
    h: pd.DataFrame, t: np.ndarray, ctx: HistoryContext, self_rows: np.ndarray | None = None
) -> pd.DataFrame:
    with np.errstate(divide="ignore", invalid="ignore"):
        return _compute_features(h, t, ctx, self_rows)


def _compute_features(
    h: pd.DataFrame, t: np.ndarray, ctx: HistoryContext, self_rows: np.ndarray | None
) -> pd.DataFrame:
    """Reconstruct the queue state at each query time `t` (epoch seconds) using ONLY information known at `t`.

    `self_rows[i]` is the row of `h` that *is* the customer being predicted for (backtests), or -1; that customer is
    excluded from every statistic so the target never leaks into its own features.
    Fully vectorised (searchsorted + cumulative sums), O((n + q) log n).
    """
    t = np.asarray(t, dtype=float)
    q = len(t)
    arr = to_seconds(h["arrival"]) if len(h) else np.array([])
    st = to_seconds(h["start"]) if len(h) else np.array([])
    en = to_seconds(h["end"]) if len(h) else np.array([])
    lf = to_seconds(h["left"]) if len(h) else np.array([])
    has_self = self_rows is not None
    selfr = np.asarray(self_rows, dtype=int) if has_self else np.full(q, -1)
    valid_self = selfr >= 0

    leave = np.where(np.isfinite(st), st, np.where(np.isfinite(lf), lf, np.inf))
    arr_sorted = np.sort(arr)
    leave_fin = np.sort(leave[np.isfinite(leave)])
    arrived = np.searchsorted(arr_sorted, t, side="left")
    departed = np.searchsorted(leave_fin, t, side="right")
    if has_self and len(h):
        self_leave = np.where(valid_self, leave[np.clip(selfr, 0, len(h) - 1)], np.inf)
        departed = departed - (valid_self & (self_leave <= t)).astype(int)
    queue_ahead = np.maximum(arrived - departed, 0)

    started = np.sort(st[np.isfinite(st)])
    ended = np.sort(en[np.isfinite(en)])
    busy = np.searchsorted(started, t, side="right") - np.searchsorted(ended, t, side="right")
    if has_self and len(h):
        self_start = np.where(valid_self, st[np.clip(selfr, 0, len(h) - 1)], np.inf)
        busy = busy - (valid_self & (self_start <= t)).astype(int)
    busy = np.clip(busy, 0, ctx.active_counters)

    m = np.isfinite(st) & np.isfinite(en)
    o = np.argsort(en[m], kind="stable")
    e_end = en[m][o]
    svc = (en - st)[m][o]
    cs = np.concatenate([[0.0], np.cumsum(svc)])
    idx = np.searchsorted(e_end, t, side="left")
    k = np.minimum(idx, ROLLING_SERVICE_WINDOW)
    svc_mean = np.where(k > 0, (cs[idx] - cs[np.maximum(idx - k, 0)]) / np.maximum(k, 1), np.nan)
    svc_n = idx

    m2 = np.isfinite(st)
    o2 = np.argsort(st[m2], kind="stable")
    s_start = st[m2][o2]
    s_wait = (st - arr)[m2][o2]
    s_hour = ((arr[m2][o2] // 3600) % 24).astype(int)
    cs2 = np.concatenate([[0.0], np.cumsum(s_wait)])
    idx2 = np.searchsorted(s_start, t, side="left")
    k2 = np.minimum(idx2, ROLLING_WAIT_WINDOW)
    recent_wait = np.where(k2 > 0, (cs2[idx2] - cs2[np.maximum(idx2 - k2, 0)]) / np.maximum(k2, 1), np.nan)
    overall_wait = np.where(idx2 > 0, cs2[idx2] / np.maximum(idx2, 1), np.nan)

    qhour = ((t // 3600) % 24).astype(int)
    hour_mean = overall_wait.copy()
    for g in range(24):
        sel = s_hour == g
        if not sel.any():
            continue
        starts_g = s_start[sel]
        cs_g = np.concatenate([[0.0], np.cumsum(s_wait[sel])])
        qi = np.where(qhour == g)[0]
        if len(qi) == 0:
            continue
        ig = np.searchsorted(starts_g, t[qi], side="left")
        ok = ig >= MIN_HOUR_SAMPLES
        hour_mean[qi[ok]] = cs_g[ig[ok]] / ig[ok]

    first = arr_sorted[0] if len(arr_sorted) else np.nan
    n_recent = arrived - np.searchsorted(arr_sorted, t - ARRIVAL_WINDOW_S, side="left")
    span = np.minimum(ARRIVAL_WINDOW_S, t - first) if len(arr_sorted) else np.full(q, np.nan)
    arrival_rate = np.where(span >= MIN_ARRIVAL_SPAN_S, n_recent / (span / 60.0), np.nan)

    active = ctx.active_counters
    nominal_service_s = (active / ctx.nominal_total_rate_per_min * 60.0) if (
        active > 0 and ctx.nominal_total_rate_per_min > 0) else np.nan
    use_obs = svc_n >= MIN_OBSERVED_SERVICE_SAMPLES
    avg_service = np.where(use_obs, svc_mean, nominal_service_s)
    mu = np.where(avg_service > 0, active / (avg_service / 60.0), np.nan)
    idle = np.maximum(active - busy, 0)
    needed = np.maximum(queue_ahead + 1 - idle, 0)
    baseline = needed / mu * 60.0

    ang = 2 * np.pi * (t % 86400.0) / 86400.0
    return pd.DataFrame({
        "queue_ahead": queue_ahead.astype(float), "busy_counters": busy.astype(float),
        "active_counters": np.full(q, float(active)), "avg_service_time_s": avg_service,
        "arrival_rate_per_min": arrival_rate, "load_ratio": arrival_rate / mu,
        "hour_sin": np.sin(ang), "hour_cos": np.cos(ang),
        "hist_hour_mean_wait_s": hour_mean, "recent_avg_wait_s": recent_wait,
        "baseline_wait_s": baseline, "prior_service_records": svc_n.astype(float),
        "observed_service_samples": svc_n.astype(float), "observed_mean_service_s": svc_mean,
        "service_time_source": np.where(use_obs, "observed_recent_service_times", "nominal_counter_rates"),
    })


def build_dataset(h: pd.DataFrame, ctx: HistoryContext, max_rows: int = MAX_TRAIN_ROWS) -> pd.DataFrame:
    """One row per served customer: features as they were when that customer arrived, plus the actual wait."""
    if len(h) == 0 or ctx.active_counters == 0:
        return pd.DataFrame(columns=FEATURES + ["actual_wait_s", "arrival_s"])
    st = to_seconds(h["start"])
    arr = to_seconds(h["arrival"])
    rows = np.where(np.isfinite(st))[0]
    if len(rows) == 0:
        return pd.DataFrame(columns=FEATURES + ["actual_wait_s", "arrival_s"])
    f = compute_features(h, arr[rows], ctx, self_rows=rows)
    f["actual_wait_s"] = (st - arr)[rows]
    f["arrival_s"] = arr[rows]
    ok = f[FEATURES + ["actual_wait_s"]].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    ok &= f["prior_service_records"] >= MIN_OBSERVED_SERVICE_SAMPLES
    f = f[ok].sort_values("arrival_s").reset_index(drop=True)
    return f.tail(max_rows).reset_index(drop=True)


def error_metrics(actual: Sequence[float], predicted: Sequence[float]) -> dict[str, Any]:
    """MAE, RMSE and signed error summaries (seconds). `mean_error_s` > 0 means the method over-predicts."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    if a.shape != p.shape:
        raise ValueError("actual and predicted must have the same length")
    keep = np.isfinite(a) & np.isfinite(p)
    a, p = a[keep], p[keep]
    n = int(len(a))
    if n == 0:
        return {"n": 0, "mae_s": None, "rmse_s": None, "mean_error_s": None, "median_abs_error_s": None,
                "max_abs_error_s": None}
    err = p - a
    return {
        "n": n, "mae_s": float(np.mean(np.abs(err))), "rmse_s": float(np.sqrt(np.mean(err ** 2))),
        "mean_error_s": float(np.mean(err)), "median_abs_error_s": float(np.median(np.abs(err))),
        "max_abs_error_s": float(np.max(np.abs(err))),
    }


def residual_interval(actual: Sequence[float], predicted: Sequence[float]) -> dict[str, Any] | None:
    """Empirical (actual - predicted) quantiles; None if there are too few samples to support an interval."""
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    keep = np.isfinite(a) & np.isfinite(p)
    r = (a - p)[keep]
    if len(r) < MIN_INTERVAL_SAMPLES:
        return None
    lo, hi = np.quantile(r, INTERVAL_QUANTILES)
    return {"lower_offset_s": float(lo), "upper_offset_s": float(hi), "level": 0.8, "n_residuals": int(len(r))}


@dataclass
class ModelBundle:
    method: str
    model: Any | None
    report: dict[str, Any]
    interval: dict[str, Any] | None
    max_baseline_wait_s: float
    features: list[str] = field(default_factory=lambda: list(FEATURES))


def _ml_models() -> dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import LinearRegression

    return {
        METHOD_LINEAR: LinearRegression(),
        METHOD_FOREST: RandomForestRegressor(
            n_estimators=100, max_depth=8, min_samples_leaf=5, random_state=42, n_jobs=1
        ),
    }


def train_and_select(dataset: pd.DataFrame) -> ModelBundle:
    """Train candidate models on the older 70% of the data and judge everything on the newest 30%.

    The returned report states exactly what was measured. If there is not enough data, or no ML model beats the
    baseline on the hold-out set by IMPROVEMENT_REQUIRED, the baseline is selected and no ML model is used.
    """
    n = len(dataset)
    report: dict[str, Any] = {
        "samples": int(n), "min_samples_for_ml": MIN_TRAIN_SAMPLES, "features": list(FEATURES),
        "split": "chronological: oldest 70% train, newest 30% validation",
        "improvement_required": f"ML hold-out MAE must be <= {IMPROVEMENT_REQUIRED:.0%} of the baseline's",
    }
    if n == 0:
        report.update(status="no_history", selected=METHOD_BASELINE,
                      reason="No completed services with enough prior history; the statistical baseline is used.")
        return ModelBundle(METHOD_BASELINE, None, report, None, math.inf)

    y = dataset["actual_wait_s"].to_numpy(float)
    base_all = dataset["baseline_wait_s"].to_numpy(float)
    max_base = float(np.nanmax(base_all)) if n else math.inf

    n_train = int(n * TRAIN_FRACTION)
    n_val = n - n_train
    if n < MIN_TRAIN_SAMPLES or n_val < MIN_VALIDATION_SAMPLES:
        report.update(
            status="insufficient_data", selected=METHOD_BASELINE,
            reason=(f"Only {n} usable historical samples (need >= {MIN_TRAIN_SAMPLES}); ML models were NOT trained. "
                    "The statistical baseline is used."),
            baseline_history_metrics=error_metrics(y, base_all), models_trained=[],
        )
        return ModelBundle(METHOD_BASELINE, None, report, residual_interval(y, base_all), max_base)

    train, val = dataset.iloc[:n_train], dataset.iloc[n_train:]
    ytr, yva = train["actual_wait_s"].to_numpy(float), val["actual_wait_s"].to_numpy(float)
    base_val = val["baseline_wait_s"].to_numpy(float)
    candidates: dict[str, Any] = {METHOD_BASELINE: error_metrics(yva, base_val)}
    fitted: dict[str, Any] = {}
    preds: dict[str, np.ndarray] = {METHOD_BASELINE: base_val}
    for name, model in _ml_models().items():
        model.fit(train[FEATURES].to_numpy(float), ytr)
        p = np.clip(model.predict(val[FEATURES].to_numpy(float)), 0.0, None)
        fitted[name], preds[name] = model, p
        candidates[name] = error_metrics(yva, p)

    base_mae = candidates[METHOD_BASELINE]["mae_s"]
    best = min(fitted, key=lambda m: candidates[m]["mae_s"])
    best_mae = candidates[best]["mae_s"]
    use_ml = bool(base_mae and base_mae > 0 and best_mae <= IMPROVEMENT_REQUIRED * base_mae)
    selected = best if use_ml else METHOD_BASELINE
    if use_ml:
        reason = (f"{best} had hold-out MAE {best_mae:.1f}s vs baseline {base_mae:.1f}s "
                  f"({(1 - best_mae / base_mae):.0%} lower), so it is used when inputs are inside its training range.")
    else:
        reason = (f"No ML model beat the baseline by the required margin on the hold-out set "
                  f"(best: {best} MAE {best_mae:.1f}s vs baseline {base_mae:.1f}s); the baseline is used.")
    report.update(
        status="trained", selected=selected, reason=reason, models_trained=sorted(fitted),
        train_samples=int(n_train), validation_samples=int(n_val), validation_metrics=candidates,
        train_window_end_s=float(train["arrival_s"].iloc[-1]),
    )
    interval = residual_interval(yva, preds[selected])
    return ModelBundle(selected, fitted.get(selected), report, interval, max_base)


def predict(features_row: dict[str, Any], bundle: ModelBundle) -> dict[str, Any]:
    """Final prediction for one live feature row. Falls back to the baseline whenever the ML path is unsafe."""
    base = float(features_row["baseline_wait_s"])
    notes: list[str] = []
    method, value = METHOD_BASELINE, base
    if bundle.method != METHOD_BASELINE and bundle.model is not None:
        vec = [features_row.get(f) for f in FEATURES]
        if any(v is None or not math.isfinite(float(v)) for v in vec):
            notes.append("Some history-based features are unavailable right now; the baseline was used instead.")
        elif base > bundle.max_baseline_wait_s:
            notes.append(
                "Current conditions are beyond anything seen in the training data "
                f"(baseline {base:.0f}s > training maximum {bundle.max_baseline_wait_s:.0f}s); "
                "the baseline was used instead of extrapolating."
            )
        else:
            value = float(max(bundle.model.predict(np.array([vec], dtype=float))[0], 0.0))
            method = bundle.method
    if method == METHOD_BASELINE and bundle.method == METHOD_BASELINE:
        notes.append(bundle.report.get("reason", ""))
    interval = None
    if bundle.interval is not None and method == bundle.method:
        interval = {
            "lower_s": float(max(value + bundle.interval["lower_offset_s"], 0.0)),
            "upper_s": float(max(value + bundle.interval["upper_offset_s"], 0.0)),
            "level": bundle.interval["level"],
            "basis": f"empirical quantiles of {bundle.interval['n_residuals']} out-of-sample residuals "
                     "(actual - predicted); not conditional on the current load",
        }
    return {"predicted_waiting_time_s": float(max(value, 0.0)), "method": method,
            "baseline_waiting_time_s": base, "uncertainty": interval, "notes": [n for n in notes if n]}
