"""Predictive operational risk engine.

Pure computation on a point-in-time snapshot of one queue (the observation frame from
`prediction_engine.prepare_history`, the counters, and optionally a `twin_forecast` result). It evaluates seven risk
categories and returns, for EVERY category, a score in [0, 1] with its components and formula, so the result can be
audited by hand. There is no randomness anywhere in this module.

Severity bands on the score:  < 0.20 none | 0.20-0.40 LOW | 0.40-0.60 MEDIUM | 0.60-0.80 HIGH | >= 0.80 CRITICAL.
Only categories at LOW or above become risk events; the rest stay visible as zero-severity assessments (the radar).

Categories, with the exact score definitions (clamp(x) = min(1, max(0, x))):

  queue_congestion       0.4 load + 0.3 queue + 0.3 forecast
                         load = clamp((rho - 0.7) / 0.4), rho = arrival rate / capacity of active counters
                         queue = clamp(queue length / congestion threshold), threshold = max(5, 2 x active counters)
                         forecast = highest simulated congestion probability over the 5/15/30/60-min horizons
                         (weights renormalise to 0.55 load + 0.45 queue when no forecast is supplied)
  counter_overload       per active counter: clamp((utilisation over the last 60 min - 0.75) / 0.25)
  waiting_time_trend     0.5 level + 0.5 trend; level = clamp(recent mean wait / SLA);
                         trend = clamp(wait projected 15 min ahead / SLA) only if the Kendall trend test has p < 0.05
  capacity_shortage      clamp((rho - 0.85) / 0.35); 1.0 when there is no active counter
  counter_failure_precursor
                         per active counter: max(stall, degradation). stall = clamp((elapsed service / counter's mean
                         service - 3) / 5); degradation = clamp((recent mean service / earlier mean service - 1.25) / 1.0)
                         only if a one-sided Mann-Whitney test has p < 0.05. This is an EARLY-WARNING indicator that a
                         counter may be failing, not a prediction that it will fail.
  abnormal_arrivals      significant (exact Poisson-rate test, p < 0.01) change in arrival rate versus the earlier
                         history: clamp((|relative change| - 0.15) / 0.85); drops are capped at 0.39 (never above LOW)
                         because fewer arrivals are an efficiency signal, not a service risk
  utilization_imbalance  clamp((max - min counter utilisation - 0.25) / 0.5) x clamp(mean utilisation / 0.6)

`time_to_impact_min` is the estimated minutes until the described impact (queue at its congestion threshold, wait at the
SLA, counter saturated); 0 means it is already happening and None means it cannot be estimated or is not expected.

Confidence is evidence-based, never a model probability: 1 - relative half-width of the 95% interval of the main rate used,
or n / n_full for sample-limited statistics (each assessment says which).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.engines import prediction_engine as pe
from app.engines.drift_detection_engine import arrival_rate_test

SEVERITY_BANDS = ((0.8, "CRITICAL"), (0.6, "HIGH"), (0.4, "MEDIUM"), (0.2, "LOW"))
CATEGORIES = ("queue_congestion", "counter_overload", "waiting_time_trend", "capacity_shortage",
              "counter_failure_precursor", "abnormal_arrivals", "utilization_imbalance")
CATEGORY_LABELS = {
    "queue_congestion": "Queue congestion", "counter_overload": "Counter overload",
    "waiting_time_trend": "Rising waiting times", "capacity_shortage": "Capacity shortage",
    "counter_failure_precursor": "Counter failure precursor", "abnormal_arrivals": "Abnormal arrivals",
    "utilization_imbalance": "Utilisation imbalance",
}
RHO_FLOOR, RHO_SPAN = 0.7, 0.4
CAP_FLOOR, CAP_SPAN = 0.85, 0.35
UTIL_FLOOR, UTIL_SPAN = 0.75, 0.25
STALL_FLOOR, STALL_SPAN = 3.0, 5.0
DEGRADE_FLOOR, DEGRADE_SPAN = 1.25, 1.0
ARRIVAL_EFFECT_FLOOR, ARRIVAL_EFFECT_SPAN = 0.15, 0.85
DROP_CAP = 0.39
IMBALANCE_FLOOR, IMBALANCE_SPAN = 0.25, 0.5
MIN_WAIT_SAMPLES = 12
MIN_SERVICE_SAMPLES = 10


def clamp(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def severity_of(score: float) -> str | None:
    for floor, name in SEVERITY_BANDS:
        if score >= floor:
            return name
    return None


@dataclass
class RiskContext:
    h: pd.DataFrame                      # prepare_history frame (arrival/start/end/left/status/counter_id)
    counters: list[dict[str, Any]]       # id, name, status, service_rate (effective per-minute rate)
    anchor_s: float                      # "now" for the analysis (epoch seconds)
    forecast: dict[str, Any] | None = None
    wait_sla_min: float = 10.0
    window_min: float = 60.0             # per-counter utilisation / trend window
    arrival_window_min: float = 30.0     # recent arrival-rate window
    rate_source: str = "nominal_configuration"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> list[dict[str, Any]]:
        return [c for c in self.counters if c["status"] == "active"]

    @property
    def reserve(self) -> list[dict[str, Any]]:
        return [c for c in self.counters if c["status"] != "active"]

    @property
    def capacity(self) -> float:
        return float(sum(c["service_rate"] for c in self.active))


# ------------------------------------------------------------------ small shared helpers
def rate_estimate(n: int, minutes: float) -> dict[str, Any]:
    """Poisson rate with an exact (Garwood) 95% interval and an evidence-based confidence."""
    if minutes <= 0:
        return {"rate": None, "ci95": None, "n": n, "minutes": minutes, "confidence": 0.0}
    lo = 0.0 if n == 0 else sps.chi2.ppf(0.025, 2 * n) / 2.0 / minutes
    hi = sps.chi2.ppf(0.975, 2 * n + 2) / 2.0 / minutes
    rate = n / minutes
    rel = (hi - lo) / (2.0 * rate) if rate > 0 else 1.0
    return {"rate": rate, "ci95": [float(lo), float(hi)], "n": int(n), "minutes": float(minutes),
            "confidence": float(1.0 - min(1.0, rel))}


def sample_confidence(n: int, n_full: int) -> float:
    return float(min(1.0, max(0, n) / n_full))


def _secs(series: pd.Series) -> np.ndarray:
    return pe.to_seconds(series) if len(series) else np.array([])


def counter_utilization(h: pd.DataFrame, counters: list[dict[str, Any]], anchor_s: float,
                        window_min: float) -> dict[int, dict[str, Any]]:
    """Share of the last `window_min` minutes each counter spent serving, and how many services it handled.

    Caveat (returned to clients): time a counter was paused or closed is not known historically, so utilisation is
    measured against the whole window and can understate load on a counter that was open only part of it."""
    out: dict[int, dict[str, Any]] = {}
    w0, w1 = anchor_s - window_min * 60.0, anchor_s
    if len(h) == 0:
        return {c["id"]: {"utilization": 0.0, "services": 0} for c in counters}
    st, en = _secs(h["start"]), _secs(h["end"])
    cid = h["counter_id"].to_numpy(dtype=float)
    en = np.where(np.isfinite(st) & ~np.isfinite(en), anchor_s, en)  # still being served: busy until now
    for c in counters:
        sel = np.isfinite(st) & (cid == c["id"])
        if not sel.any():
            out[c["id"]] = {"utilization": 0.0, "services": 0}
            continue
        overlap = np.clip(np.minimum(en[sel], w1) - np.maximum(st[sel], w0), 0.0, None)
        done_in_window = int(((en[sel] >= w0) & (en[sel] <= w1) & np.isfinite(_secs(h["end"])[sel])).sum())
        out[c["id"]] = {"utilization": float(min(1.0, overlap.sum() / (window_min * 60.0))), "services": done_in_window}
    return out


def snapshot(ctx: RiskContext) -> dict[str, Any]:
    """Queue state at the anchor, reconstructed from the observation frame."""
    h = ctx.h
    waiting = h[h["status"] == "waiting"] if len(h) else h
    serving = h[h["status"] == "serving"] if len(h) else h
    longest = None
    if len(waiting):
        longest = float(max(0.0, (ctx.anchor_s - _secs(waiting["arrival"]).min()) / 60.0))
    recent_n = 0
    if len(h):
        arr = _secs(h["arrival"])
        recent_n = int(((arr > ctx.anchor_s - ctx.arrival_window_min * 60.0) & (arr <= ctx.anchor_s)).sum())
    lam = rate_estimate(recent_n, ctx.arrival_window_min)
    return {
        "queue_length": int(len(waiting)), "serving": int(len(serving)), "longest_wait_min": longest,
        "arrival": lam, "active_counters": len(ctx.active), "reserve_counters": len(ctx.reserve),
        "capacity_per_min": ctx.capacity,
        "load_ratio": (lam["rate"] / ctx.capacity) if (lam["rate"] is not None and ctx.capacity > 0) else None,
        "congestion_threshold": max(5, 2 * len(ctx.active)),
    }


def _recommend(kind: str, ctx: RiskContext, resource: str | None = None) -> dict[str, Any]:
    has_reserve = bool(ctx.reserve)
    table = {
        "capacity": ({"type": "activate_counters", "label": "Open a reserve counter",
                      "rationale": "Adds service capacity directly.", "simulatable": True}
                     if has_reserve else
                     {"type": "reallocate_staff", "label": "Add assisting staff to open counters",
                      "rationale": "No reserve counter exists; extra hands speed up the counters that are open.",
                      "simulatable": True}),
        "overload": {"type": "reallocate_staff", "label": f"Relieve {resource or 'the overloaded counter'}",
                     "rationale": "Open a reserve counter if one exists, otherwise add assisting staff.",
                     "simulatable": True},
        "failure": {"type": "operator_inspection", "label": f"Inspect {resource or 'the counter'} now and prepare a "
                    "reserve counter", "rationale": "LineZero cannot simulate hardware or staff failures it has not "
                    "observed; an operator check is the safe response.", "simulatable": False},
        "surge": {"type": "redistribute_traffic", "label": "Redirect part of the arrivals or open capacity",
                  "rationale": "Demand is unusually high; shift some customers elsewhere or add counters.",
                  "simulatable": True},
        "drop": {"type": "none", "label": "Review staffing for the quiet period",
                 "rationale": "Fewer arrivals than usual; check upstream causes before reducing capacity.",
                 "simulatable": False},
        "balance": {"type": "assignment_strategy", "label": "Switch to longest-idle assignment",
                    "rationale": "Spreads customers evenly across counters.", "simulatable": True},
    }
    return table[kind]


def _assessment(category: str, *, resource_type: str, resource_id: int | None, resource_name: str, score: float,
                components: dict[str, Any], formula: str, supporting: dict[str, Any], confidence: float,
                uncertainty: dict[str, Any] | None, explanation: str, recommended: dict[str, Any],
                time_to_impact: float | None = None, status: str = "assessed") -> dict[str, Any]:
    score = clamp(score)
    return {
        "category": category, "label": CATEGORY_LABELS[category], "resource_type": resource_type,
        "resource_id": resource_id, "resource_name": resource_name, "score": score, "severity": severity_of(score),
        "components": components, "score_formula": formula, "time_to_impact_min": time_to_impact,
        "supporting_metrics": supporting, "confidence": float(min(1.0, max(0.0, confidence))),
        "uncertainty": uncertainty, "explanation": explanation, "recommended_intervention": recommended,
        "status": status,
    }


def _insufficient(category: str, why: str, ctx: RiskContext) -> dict[str, Any]:
    return _assessment(category, resource_type="queue", resource_id=None, resource_name="Queue", score=0.0,
                       components={}, formula="not computed", supporting={"reason": why}, confidence=0.0,
                       uncertainty=None, explanation=f"Not assessed: {why}", recommended=_recommend("capacity", ctx),
                       status="insufficient_data")


# ------------------------------------------------------------------ the seven categories
def queue_congestion(ctx: RiskContext, snap: dict[str, Any]) -> dict[str, Any]:
    cat = "queue_congestion"
    if not ctx.active:
        return _assessment(cat, resource_type="queue", resource_id=None, resource_name="Queue", score=1.0,
                           components={"no_active_counters": True}, formula="1.0 when no counter is active",
                           supporting={"queue_length": snap["queue_length"], "active_counters": 0}, confidence=1.0,
                           uncertainty=None, time_to_impact=0.0, recommended=_recommend("capacity", ctx),
                           explanation="No counter is active, so every waiting customer is stuck.")
    rho, q, thr = snap["load_ratio"], snap["queue_length"], snap["congestion_threshold"]
    load = clamp((rho - RHO_FLOOR) / RHO_SPAN) if rho is not None else None
    queue = clamp(q / thr)
    fc_p, fc_h, fc_band = None, None, None
    if ctx.forecast:
        hs = ctx.forecast["horizons"]
        fc_p = max(x["congestion"]["probability"] for x in hs)
        first = next((x["horizon_min"] for x in hs if x["congestion"]["probability"] >= 0.5), None)
        fc_h = first
        fc_band = [(x["horizon_min"], x["queue_length"]["p10"], x["queue_length"]["p90"]) for x in hs]
    if load is not None and fc_p is not None:
        score, formula = 0.4 * load + 0.3 * queue + 0.3 * fc_p, "0.4 load + 0.3 queue + 0.3 forecast"
    elif load is not None:
        score, formula = 0.55 * load + 0.45 * queue, "0.55 load + 0.45 queue (no forecast available)"
    else:
        score, formula = queue, "queue only (arrival rate unknown)"
    tti = None
    if q >= thr:
        tti = 0.0
    elif fc_h is not None:
        tti = float(fc_h)
    elif rho is not None and rho > 1.0:
        tti = float((thr - q) / (snap["arrival"]["rate"] - snap["capacity_per_min"]))
    lam = snap["arrival"]
    expl = (f"{q} waiting against a congestion threshold of {thr}; demand is "
            + (f"{rho:.0%} of capacity" if rho is not None else "unknown relative to capacity")
            + (f"; {fc_p:.0%} of simulated futures reach the threshold within 60 min" if fc_p is not None else "")
            + (f". Congestion is expected within about {tti:g} min." if tti not in (None, 0.0) else
               ". Congestion is already present." if tti == 0.0 else "."))
    return _assessment(
        cat, resource_type="queue", resource_id=None, resource_name="Queue", score=score,
        components={"load": load, "queue": queue, "forecast": fc_p}, formula=formula,
        supporting={"queue_length": q, "congestion_threshold": thr, "load_ratio": rho,
                    "arrival_rate_per_min": lam["rate"], "capacity_per_min": snap["capacity_per_min"],
                    "forecast_max_congestion_probability": fc_p, "forecast_first_horizon_over_50pct_min": fc_h,
                    "data_kind": {"queue_length": "observed", "arrival_rate_per_min": "observed",
                                  "forecast_max_congestion_probability": "simulated"}},
        confidence=lam["confidence"], uncertainty={"arrival_rate_ci95": lam["ci95"],
                                                   "forecast_queue_p10_p90_by_horizon": fc_band},
        explanation=expl, recommended=_recommend("capacity", ctx), time_to_impact=tti)


def counter_overload(ctx: RiskContext, util: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in ctx.active:
        u = util.get(c["id"], {"utilization": 0.0, "services": 0})
        score = clamp((u["utilization"] - UTIL_FLOOR) / UTIL_SPAN)
        tti = 0.0 if u["utilization"] >= 0.95 else None
        out.append(_assessment(
            "counter_overload", resource_type="counter", resource_id=c["id"], resource_name=c["name"], score=score,
            components={"utilization": u["utilization"]}, formula="clamp((utilization - 0.75) / 0.25)",
            supporting={"utilization": u["utilization"], "window_min": ctx.window_min, "services_in_window": u["services"],
                        "data_kind": {"utilization": "observed"}},
            confidence=sample_confidence(u["services"], 10), uncertainty=None, time_to_impact=tti,
            explanation=f"{c['name']} was busy {u['utilization']:.0%} of the last {ctx.window_min:g} min "
                        f"({u['services']} services).",
            recommended=_recommend("overload", ctx, c["name"])))
    return out


def waiting_time_trend(ctx: RiskContext, snap: dict[str, Any]) -> dict[str, Any]:
    cat = "waiting_time_trend"
    h = ctx.h
    if len(h) == 0:
        return _insufficient(cat, "no observations", ctx)
    st, arr = _secs(h["start"]), _secs(h["arrival"])
    win0 = ctx.anchor_s - ctx.window_min * 60.0
    m = np.isfinite(st) & (st >= win0) & (st <= ctx.anchor_s)
    t, w = st[m], ((st - arr)[m]) / 60.0
    if len(t) < MIN_WAIT_SAMPLES:
        return _insufficient(cat, f"only {len(t)} customers started service in the last {ctx.window_min:g} min "
                                  f"(need {MIN_WAIT_SAMPLES})", ctx)
    order = np.argsort(t)
    t, w = t[order], w[order]
    tau = sps.kendalltau(t, w)
    p = float(tau.pvalue) if np.isfinite(tau.pvalue) else 1.0
    slope_per_s = float(sps.theilslopes(w, t).slope)  # robust slope, minutes of wait per second of time
    slope_per_min = slope_per_s * 60.0
    level = float(np.mean(w[-10:]))
    sla = ctx.wait_sla_min
    level_c = clamp(level / sla)
    significant = p < 0.05 and slope_per_min > 0
    projected = level + slope_per_min * 15.0
    trend_c = clamp(projected / sla) if significant else 0.0
    tti = 0.0 if level >= sla else ((sla - level) / slope_per_min if significant and slope_per_min > 0 else None)
    longest = snap["longest_wait_min"]
    return _assessment(
        cat, resource_type="queue", resource_id=None, resource_name="Queue", score=0.5 * level_c + 0.5 * trend_c,
        components={"level": level_c, "trend": trend_c, "trend_significant": bool(significant)},
        formula="0.5 level + 0.5 trend (trend counts only if Kendall p < 0.05 and rising)",
        supporting={"recent_mean_wait_min": level, "wait_slope_min_per_min": slope_per_min, "kendall_tau": float(tau.statistic),
                    "kendall_p_value": p, "projected_wait_in_15_min": projected, "sla_min": sla,
                    "longest_current_wait_min": longest, "n_customers": int(len(t)),
                    "data_kind": {"recent_mean_wait_min": "observed", "projected_wait_in_15_min": "predicted"}},
        confidence=sample_confidence(len(t), 40), uncertainty={"kendall_p_value": p, "method": "Theil-Sen slope"},
        time_to_impact=tti, recommended=_recommend("capacity", ctx),
        explanation=(f"Recent waits average {level:.1f} min against an SLA of {sla:g} min; "
                     + (f"waits are rising by about {slope_per_min * 60:.1f} min per hour (p={p:.3f})."
                        if significant else "no statistically significant upward trend.")))


def capacity_shortage(ctx: RiskContext, snap: dict[str, Any]) -> dict[str, Any]:
    cat = "capacity_shortage"
    if not ctx.active:
        return _assessment(cat, resource_type="queue", resource_id=None, resource_name="Queue", score=1.0,
                           components={"no_active_counters": True}, formula="1.0 when no counter is active",
                           supporting={"active_counters": 0, "reserve_counters": len(ctx.reserve)}, confidence=1.0,
                           uncertainty=None, time_to_impact=0.0, recommended=_recommend("capacity", ctx),
                           explanation="There is no service capacity at all.")
    rho = snap["load_ratio"]
    if rho is None:
        return _insufficient(cat, "arrival rate could not be estimated", ctx)
    lam = snap["arrival"]
    mu_avg = snap["capacity_per_min"] / len(ctx.active)
    needed = math.ceil(lam["rate"] / (CAP_FLOOR * mu_avg)) if mu_avg > 0 else None
    extra = max(0, (needed or 0) - len(ctx.active))
    return _assessment(
        cat, resource_type="queue", resource_id=None, resource_name="Queue", score=clamp((rho - CAP_FLOOR) / CAP_SPAN),
        components={"load_ratio": rho}, formula="clamp((rho - 0.85) / 0.35)",
        supporting={"load_ratio": rho, "arrival_rate_per_min": lam["rate"], "capacity_per_min": snap["capacity_per_min"],
                    "additional_counters_for_85pct_load": extra, "reserve_counters": len(ctx.reserve),
                    "data_kind": {"arrival_rate_per_min": "observed", "capacity_per_min": "predicted"}},
        confidence=lam["confidence"], uncertainty={"arrival_rate_ci95": lam["ci95"],
                                                   "capacity_rate_source": ctx.rate_source},
        time_to_impact=0.0 if rho >= 1.0 else None, recommended=_recommend("capacity", ctx),
        explanation=(f"Demand is {rho:.0%} of capacity ({lam['rate']:.2f}/min vs {snap['capacity_per_min']:.2f}/min); "
                     + (f"about {extra} more counter(s) would bring load to 85%." if extra else
                        "capacity is adequate at the 85% target.")))


def counter_failure_precursors(ctx: RiskContext) -> list[dict[str, Any]]:
    h = ctx.h
    out = []
    if len(h) == 0:
        return out
    st, en = _secs(h["start"]), _secs(h["end"])
    cid = h["counter_id"].to_numpy(dtype=float)
    done = np.isfinite(st) & np.isfinite(en) & (en <= ctx.anchor_s)
    dur = np.where(done, (en - st) / 60.0, np.nan)
    pooled = dur[done]
    pooled_mean = float(pooled.mean()) if len(pooled) >= MIN_SERVICE_SAMPLES else None
    w0 = ctx.anchor_s - ctx.window_min * 60.0
    serving = (h["status"] == "serving").to_numpy() if len(h) else np.array([], bool)
    for c in ctx.active:
        mine = done & (cid == c["id"])
        n_c = int(mine.sum())
        mean_c = float(dur[mine].mean()) if n_c >= MIN_SERVICE_SAMPLES else pooled_mean
        # stall: a customer being served for far longer than this counter's typical service
        stall, elapsed = 0.0, None
        cur = serving & (cid == c["id"]) & np.isfinite(st)
        if cur.any() and mean_c:
            elapsed = float((ctx.anchor_s - st[cur].min()) / 60.0)
            stall = clamp((elapsed / mean_c - STALL_FLOOR) / STALL_SPAN)
        # degradation: recent services slower than the counter's earlier ones
        recent = mine & (en >= w0)
        base = mine & (en < w0)
        degr, ratio, p = 0.0, None, None
        if recent.sum() >= 8 and base.sum() >= 15:
            ratio = float(dur[recent].mean() / dur[base].mean())
            p = float(sps.mannwhitneyu(dur[recent], dur[base], alternative="greater").pvalue)
            degr = clamp((ratio - DEGRADE_FLOOR) / DEGRADE_SPAN) if p < 0.05 else 0.0
        score = max(stall, degr)
        why = []
        if stall > 0:
            why.append(f"a customer has been in service for {elapsed:.1f} min, {elapsed / mean_c:.1f}x this counter's "
                       f"typical {mean_c:.1f} min")
        if degr > 0:
            why.append(f"recent services take {ratio:.2f}x as long as earlier ones (p={p:.3f})")
        out.append(_assessment(
            "counter_failure_precursor", resource_type="counter", resource_id=c["id"], resource_name=c["name"],
            score=score, components={"stall": stall, "degradation": degr},
            formula="max(stall, degradation); stall = clamp((elapsed/mean - 3)/5); degradation = clamp((ratio - 1.25)/1.0) if p < 0.05",
            supporting={"current_service_elapsed_min": elapsed, "counter_mean_service_min": mean_c,
                        "recent_vs_earlier_service_ratio": ratio, "degradation_p_value": p, "services_observed": n_c,
                        "data_kind": {"current_service_elapsed_min": "observed"},
                        "caveat": "Early-warning indicator only; LineZero does not predict failures it has not observed."},
            confidence=sample_confidence(n_c, 30), uncertainty=({"degradation_p_value": p} if p is not None else None),
            time_to_impact=None, recommended=_recommend("failure", ctx, c["name"]),
            explanation=(f"{c['name']}: " + "; ".join(why) + ".") if why else
                        f"{c['name']}: service times look normal."))
    return out


def abnormal_arrivals(ctx: RiskContext) -> dict[str, Any]:
    cat = "abnormal_arrivals"
    h = ctx.h
    if len(h) == 0:
        return _insufficient(cat, "no observations", ctx)
    arr = _secs(h["arrival"])
    arr = arr[np.isfinite(arr) & (arr <= ctx.anchor_s)]
    rec0 = ctx.anchor_s - ctx.arrival_window_min * 60.0
    ref = arr[arr < rec0]
    if len(ref) == 0:
        return _insufficient(cat, "no earlier history to compare the recent arrival rate with", ctx)
    t_ref = (rec0 - ref.min()) / 60.0
    n_rec = int((arr >= rec0).sum())
    test = arrival_rate_test(int(len(ref)), t_ref, n_rec, ctx.arrival_window_min)
    if test["status"] != "ok":
        return _insufficient(cat, f"too few arrivals to compare ({len(ref)} earlier, {n_rec} recent)", ctx)
    effect, p = test["effect"], test["p_value"]
    significant = p < 0.01
    drop = effect < 0
    score = clamp((abs(effect) - ARRIVAL_EFFECT_FLOOR) / ARRIVAL_EFFECT_SPAN) if significant else 0.0
    if drop:
        score = min(score, DROP_CAP)
    rec_ci = rate_estimate(n_rec, ctx.arrival_window_min)
    return _assessment(
        cat, resource_type="queue", resource_id=None, resource_name="Queue", score=score,
        components={"relative_change": effect, "p_value": p, "significant": significant, "direction": "drop" if drop else "surge"},
        formula="clamp((|relative change| - 0.15) / 0.85) if exact Poisson-rate test p < 0.01; drops capped at 0.39",
        supporting={"recent_rate_per_min": test["recent_rate_per_min"], "earlier_rate_per_min": test["reference_rate_per_min"],
                    "relative_change": effect, "p_value": p, "recent_arrivals": n_rec, "earlier_arrivals": int(len(ref)),
                    "data_kind": {"recent_rate_per_min": "observed", "earlier_rate_per_min": "observed"}},
        confidence=rec_ci["confidence"], uncertainty={"recent_rate_ci95": rec_ci["ci95"], "p_value": p},
        time_to_impact=0.0 if score >= 0.2 and not drop else None,
        recommended=_recommend("drop" if drop else "surge", ctx),
        explanation=(f"Arrivals in the last {ctx.arrival_window_min:g} min run at {test['recent_rate_per_min']:.2f}/min versus "
                     f"{test['reference_rate_per_min']:.2f}/min earlier ({effect:+.0%}, p={p:.3g})"
                     + ("." if significant else "; not statistically different.")))


def utilization_imbalance(ctx: RiskContext, util: dict[int, dict[str, Any]]) -> dict[str, Any]:
    cat = "utilization_imbalance"
    rows = [(c, util.get(c["id"], {"utilization": 0.0, "services": 0})) for c in ctx.active]
    rows = [(c, u) for c, u in rows if u["services"] >= 5]
    if len(ctx.active) < 2 or len(rows) < 2:
        return _insufficient(cat, "needs at least two active counters with 5+ services in the window", ctx)
    us = np.array([u["utilization"] for _, u in rows])
    spread, mean_u = float(us.max() - us.min()), float(us.mean())
    hi = rows[int(us.argmax())][0]["name"]
    lo = rows[int(us.argmin())][0]["name"]
    activity = clamp(mean_u / 0.6)
    score = clamp((spread - IMBALANCE_FLOOR) / IMBALANCE_SPAN) * activity
    return _assessment(
        cat, resource_type="queue", resource_id=None, resource_name="Queue", score=score,
        components={"spread": spread, "mean_utilization": mean_u, "activity_factor": activity},
        formula="clamp((max - min utilization - 0.25) / 0.5) x clamp(mean utilization / 0.6)",
        supporting={"spread": spread, "mean_utilization": mean_u, "busiest": hi, "least_busy": lo,
                    "per_counter": {c["name"]: u["utilization"] for c, u in rows}, "window_min": ctx.window_min,
                    "data_kind": {"per_counter": "observed"}},
        confidence=sample_confidence(min(u["services"] for _, u in rows), 10), uncertainty=None,
        time_to_impact=None, recommended=_recommend("balance", ctx),
        explanation=f"{hi} was busy {max(us):.0%} and {lo} {min(us):.0%} of the last {ctx.window_min:g} min "
                    f"(spread {spread:.0%}, mean {mean_u:.0%}).")


# ------------------------------------------------------------------ public entry point
def assess(ctx: RiskContext) -> dict[str, Any]:
    """Evaluate every category. Returns all assessments (for the radar) and the subset that are risk events."""
    snap = snapshot(ctx)
    util = counter_utilization(ctx.h, ctx.active, ctx.anchor_s, ctx.window_min)
    items: list[dict[str, Any]] = [queue_congestion(ctx, snap)]
    items += counter_overload(ctx, util)
    items.append(waiting_time_trend(ctx, snap))
    items.append(capacity_shortage(ctx, snap))
    items += counter_failure_precursors(ctx)
    items.append(abnormal_arrivals(ctx))
    items.append(utilization_imbalance(ctx, util))
    order = {c: i for i, c in enumerate(CATEGORIES)}
    items.sort(key=lambda a: (order[a["category"]], a["resource_name"]))
    events = sorted((a for a in items if a["severity"] is not None), key=lambda a: -a["score"])
    by_cat = {}
    for c in CATEGORIES:
        sub = [a for a in items if a["category"] == c]
        top = max(sub, key=lambda a: a["score"]) if sub else None
        by_cat[c] = {"label": CATEGORY_LABELS[c], "score": top["score"] if top else 0.0,
                     "severity": top["severity"] if top else None, "resource": top["resource_name"] if top else None,
                     "status": top["status"] if top else "insufficient_data"}
    return {"snapshot": snap, "assessments": items, "events": events, "radar": by_cat,
            "overall_score": max((a["score"] for a in items), default=0.0),
            "overall_severity": severity_of(max((a["score"] for a in items), default=0.0)),
            "bands": {"LOW": 0.2, "MEDIUM": 0.4, "HIGH": 0.6, "CRITICAL": 0.8},
            "utilization_caveat": "Utilisation is measured against the whole window; time a counter was paused or "
                                  "closed is not recorded historically."}


__all__ = ["RiskContext", "assess", "severity_of", "clamp", "CATEGORIES", "rate_estimate", "counter_utilization"]
