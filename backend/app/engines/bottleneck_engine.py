"""Rule-based bottleneck detection.

Pure computation: takes a queue's entries (see prediction_engine.prepare_history for the frame layout) and its
counters, measures the recent operating window, and returns findings. Every finding carries the numbers that
triggered it (`supporting_metrics`) and the thresholds that were applied, so a reader can reproduce the decision.

Rules (thresholds live in `Thresholds` and are echoed in every response):
  A counter_overload            per counter: sustained high utilisation
  B uneven_utilization          queue level: large utilisation spread between active counters
  C arrival_spike               queue level: 15-minute arrival counts far above the typical level
  D slow_service                per counter: mean service time well above peers / configured rate / its own history
  E capacity_demand_imbalance   queue level: arrival rate approaching or exceeding total service capacity

Units: durations in seconds unless a key says otherwise; rates in customers per minute.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import poisson

from app.engines.prediction_engine import to_seconds

SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass(frozen=True)
class Thresholds:
    min_window_minutes: float = 10.0
    overload_util: tuple[float, float, float] = (0.85, 0.92, 0.97)  # LOW, MEDIUM, HIGH
    overload_persistence_util: float = 0.75
    long_wait_service_multiple: float = 3.0
    min_counter_services: int = 5
    uneven_spread: tuple[float, float, float, float] = (0.25, 0.40, 0.55, 0.70)  # LOW..CRITICAL
    uneven_min_peak_util: float = 0.50
    spike_bucket_minutes: float = 15.0
    spike_min_buckets: int = 6
    spike_ratio: tuple[float, float, float, float] = (1.5, 2.0, 3.0, 4.0)
    spike_min_count: int = 8
    spike_alpha: float = 0.01
    spike_merge_gap_buckets: int = 1
    slow_ratio: tuple[float, float, float, float] = (1.3, 1.6, 2.2, 3.0)
    slow_min_samples: int = 8
    slow_min_history_samples: int = 20
    slow_min_z: float = 2.5
    capacity_ratio: tuple[float, float, float, float] = (0.90, 1.00, 1.15, 1.40)
    capacity_min_arrivals: int = 10
    capacity_target_util: float = 0.85

    def as_dict(self) -> dict[str, Any]:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


@dataclass
class CounterInfo:
    id: int
    name: str
    rate_per_min: float
    status: str


@dataclass
class Finding:
    bottleneck_type: str
    severity: str
    queue_id: int
    counter_id: int | None
    supporting_metrics: dict[str, Any]
    explanation: str
    operational_impact: str
    recommendation: str
    window_start_s: float
    window_end_s: float


@dataclass
class AnalysisResult:
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def severity_from_ladder(value: float, ladder: tuple[float, ...], lowest_index: int = 0) -> str | None:
    """Map a value onto SEVERITIES using ascending cut-offs; None if below the first cut-off."""
    level = None
    for i, cut in enumerate(ladder):
        if value >= cut:
            level = i + lowest_index
    return None if level is None else SEVERITIES[min(level, 3)]


def bump(sev: str, steps: int = 1) -> str:
    return SEVERITIES[min(SEVERITIES.index(sev) + steps, 3)]


def _min(x: float) -> float:
    return round(x / 60.0, 2)


def _overlap(st: np.ndarray, en: np.ndarray, a: float, b: float) -> float:
    en = np.where(np.isfinite(en), en, b)
    return float(np.clip(np.minimum(en, b) - np.maximum(st, a), 0.0, None).sum())


class _Frame:
    """Numpy views of the entries frame, computed once per analysis."""

    def __init__(self, h: pd.DataFrame):
        self.n = len(h)
        self.arr = to_seconds(h["arrival"]) if self.n else np.array([])
        self.st = to_seconds(h["start"]) if self.n else np.array([])
        self.en = to_seconds(h["end"]) if self.n else np.array([])
        self.lf = to_seconds(h["left"]) if self.n else np.array([])
        self.cid = h["counter_id"].to_numpy(dtype=float, na_value=np.nan) if self.n else np.array([])
        self.status = h["status"].to_numpy() if self.n else np.array([])
        self.leave = np.where(np.isfinite(self.st), self.st, np.where(np.isfinite(self.lf), self.lf, np.inf))

    def queue_len(self, t: float) -> int:
        return int(((self.arr <= t) & (self.leave > t)).sum())


def _capacity(counters: list[CounterInfo]) -> tuple[int, float]:
    active = [c for c in counters if c.status == "active"]
    return len(active), float(sum(c.rate_per_min for c in active))


def analyze(
    queue_id: int, history: pd.DataFrame, counters: list[CounterInfo], as_of_s: float,
    window_minutes: float = 240.0, lookback_minutes: float = 1440.0, thresholds: Thresholds | None = None,
) -> AnalysisResult:
    th = thresholds or Thresholds()
    res = AnalysisResult()
    f = _Frame(history)
    if f.n == 0:
        res.notes.append("The queue has no entries, so there is nothing to analyse.")
        res.summary = {"entries": 0}
        return res

    first = float(np.nanmin(f.arr))
    we = float(as_of_s)
    ws = max(we - window_minutes * 60.0, first)
    window_s = we - ws
    res.summary = {
        "window_start_s": ws, "window_end_s": we, "window_minutes": round(window_s / 60.0, 2),
        "requested_window_minutes": window_minutes, "lookback_minutes": lookback_minutes,
        "entries": f.n,
    }
    if window_s < th.min_window_minutes * 60.0:
        res.notes.append(
            f"Only {window_s / 60:.1f} minutes of data fall in the analysis window "
            f"(need >= {th.min_window_minutes:g}); no bottleneck rules were evaluated."
        )
        return res

    n_active, mu_total = _capacity(counters)
    arrivals_w = int(((f.arr >= ws) & (f.arr < we)).sum())
    lam = arrivals_w / (window_s / 60.0)
    started_w = (f.st >= ws) & (f.st <= we)
    waits_w = (f.st - f.arr)[started_w]
    done_w = np.isfinite(f.en) & (f.en >= ws) & (f.en <= we) & np.isfinite(f.st)
    svc_w = (f.en - f.st)[done_w]
    mean_wait = float(waits_w.mean()) if len(waits_w) else None
    p95_wait = float(np.percentile(waits_w, 95)) if len(waits_w) else None
    mean_service = float(svc_w.mean()) if len(svc_w) else None
    q_now, q_start = f.queue_len(we), f.queue_len(ws)
    abandoned_w = int(((f.status == "abandoned") & (f.lf >= ws) & (f.lf <= we)).sum())
    mid = (ws + we) / 2.0

    stats: dict[int, dict[str, Any]] = {}
    for c in counters:
        m = f.cid == c.id
        busy = _overlap(f.st[m], f.en[m], ws, we)
        b1 = _overlap(f.st[m], f.en[m], ws, mid)
        b2 = _overlap(f.st[m], f.en[m], mid, we)
        mm = m & done_w
        svc = (f.en - f.st)[mm]
        stats[c.id] = {
            "counter": c, "utilization": busy / window_s,
            "utilization_first_half": b1 / max(mid - ws, 1e-9), "utilization_second_half": b2 / max(we - mid, 1e-9),
            "served": int(mm.sum()), "svc": svc, "mean_service_s": float(svc.mean()) if len(svc) else None,
            "sd_service_s": float(svc.std(ddof=1)) if len(svc) > 1 else None,
        }
    total_served = sum(s["served"] for s in stats.values())
    res.summary.update({
        "arrivals_in_window": arrivals_w, "arrival_rate_per_min": round(lam, 4),
        "active_counters": n_active, "service_capacity_per_min": round(mu_total, 4),
        "mean_wait_s": mean_wait, "p95_wait_s": p95_wait, "mean_service_s": mean_service,
        "queue_length_now": q_now, "queue_length_at_window_start": q_start, "abandoned_in_window": abandoned_w,
        "counter_utilization": {str(cid): round(s["utilization"], 4) for cid, s in stats.items()},
    })

    def impact_text() -> str:
        parts = []
        if mean_wait is not None:
            parts.append(f"customers who started service in the window waited {_min(mean_wait)} min on average"
                         + (f" (p95 {_min(p95_wait)} min)" if p95_wait is not None else ""))
        parts.append(f"{q_now} customer(s) are waiting now")
        if abandoned_w:
            parts.append(f"{abandoned_w} customer(s) left without being served")
        return "; ".join(parts).capitalize() + "."

    long_wait = bool(mean_wait is not None and mean_service and mean_wait >= th.long_wait_service_multiple * mean_service)

    for cid, s in stats.items():
        c: CounterInfo = s["counter"]
        if c.status == "closed" or s["served"] < th.min_counter_services:
            continue
        u = s["utilization"]
        base = severity_from_ladder(u, th.overload_util)
        persistent = min(s["utilization_first_half"], s["utilization_second_half"]) >= th.overload_persistence_util
        if base is None or not persistent:
            continue
        sev, reasons = base, []
        if long_wait:
            sev = bump(sev)
            reasons.append(f"mean wait {_min(mean_wait)} min is >= {th.long_wait_service_multiple:g}x the mean service time")
        if q_now >= 2 * max(n_active, 1) and q_now > q_start:
            sev = bump(sev)
            reasons.append(f"the line grew from {q_start} to {q_now}")
        fair = total_served and s["served"] / total_served
        res.findings.append(Finding(
            "counter_overload", sev, queue_id, c.id,
            {"utilization": round(u, 4), "utilization_first_half": round(s["utilization_first_half"], 4),
             "utilization_second_half": round(s["utilization_second_half"], 4), "customers_served": s["served"],
             "share_of_all_services": round(float(fair), 4) if total_served else None,
             "mean_wait_s": mean_wait, "queue_length_now": q_now, "queue_length_at_window_start": q_start,
             "thresholds": {"utilization": list(th.overload_util)}},
            f"{c.name} was busy {u:.0%} of the {window_s / 60:.0f}-minute window "
            f"({s['utilization_first_half']:.0%} then {s['utilization_second_half']:.0%} across its halves), "
            f"which is above the {th.overload_util[0]:.0%} overload threshold"
            + (f"; severity raised because {' and '.join(reasons)}." if reasons else "."),
            impact_text(),
            f"Relieve {c.name}: route new customers to idle counters, open or resume another counter, "
            "or move part of its workload to a faster counter.",
            ws, we,
        ))

    act = [s for s in stats.values() if s["counter"].status == "active"]
    if len(act) >= 2:
        utils = {s["counter"].id: s["utilization"] for s in act}
        hi_id, lo_id = max(utils, key=utils.get), min(utils, key=utils.get)
        spread = utils[hi_id] - utils[lo_id]
        sev = severity_from_ladder(spread, th.uneven_spread)
        if sev and utils[hi_id] >= th.uneven_min_peak_util:
            hi, lo = stats[hi_id]["counter"], stats[lo_id]["counter"]
            rates = [s["counter"].rate_per_min for s in act]
            speed_note = ""
            if max(rates) / min(rates) > 1.25:
                speed_note = " Part of this gap may reflect different counter speeds (configured rates differ)."
            arr_u = np.array(list(utils.values()))
            res.findings.append(Finding(
                "uneven_utilization", sev, queue_id, hi.id,
                {"utilization_by_counter": {str(k): round(v, 4) for k, v in utils.items()},
                 "most_loaded_counter_id": hi.id, "least_loaded_counter_id": lo.id,
                 "utilization_spread": round(spread, 4), "std_of_utilization": round(float(arr_u.std()), 4),
                 "services_by_counter": {str(s["counter"].id): s["served"] for s in act},
                 "thresholds": {"spread": list(th.uneven_spread), "min_peak_utilization": th.uneven_min_peak_util}},
                f"{hi.name} was busy {utils[hi_id]:.0%} of the window while {lo.name} was busy only "
                f"{utils[lo_id]:.0%} - a {spread:.0%} gap across {len(act)} active counters.{speed_note}",
                impact_text() + " Work is concentrated on few counters while others have spare capacity.",
                f"Rebalance: assign each waiting customer to the longest-idle counter rather than always the "
                f"lowest-numbered one, so {lo.name} takes work from {hi.name}.",
                ws, we,
            ))

    bucket_s = th.spike_bucket_minutes * 60.0
    ls = max(we - lookback_minutes * 60.0, first)
    n_b = int((we - ls) // bucket_s)
    if n_b >= th.spike_min_buckets:
        edges = we - bucket_s * np.arange(n_b, -1, -1)
        counts = np.histogram(f.arr, bins=edges)[0]
        typical = max(float(np.median(counts)), 1.0)
        pvals = poisson.sf(counts - 1, typical)
        flagged = (counts >= th.spike_ratio[0] * typical) & (counts >= th.spike_min_count) \
            & (pvals < th.spike_alpha / n_b)
        episodes: list[list[int]] = []
        for i in np.where(flagged)[0]:
            if episodes and i - episodes[-1][1] - 1 <= th.spike_merge_gap_buckets:
                episodes[-1][1] = int(i)
            else:
                episodes.append([int(i), int(i)])
        scored = []
        for a, b in episodes:
            peak = float(counts[a:b + 1].max())
            scored.append((peak / typical, a, b, peak))
        for ratio, a, b, peak in sorted(scored, reverse=True)[:3]:
            sev = severity_from_ladder(ratio, th.spike_ratio)
            peak_rate = peak / th.spike_bucket_minutes
            exceeds = bool(mu_total > 0 and peak_rate >= mu_total) or (n_active == 0)
            if exceeds:
                sev = bump(sev)
            ep_start, ep_end = float(edges[a]), float(edges[b + 1])
            ongoing = bool(ep_end >= we - 1e-6)
            res.findings.append(Finding(
                "arrival_spike", sev, queue_id, None,
                {"episode_start_s": ep_start, "episode_end_s": ep_end, "ongoing": ongoing,
                 "peak_arrivals_per_bucket": int(peak), "typical_arrivals_per_bucket": typical,
                 "bucket_minutes": th.spike_bucket_minutes, "peak_to_typical_ratio": round(ratio, 3),
                 "peak_arrival_rate_per_min": round(peak_rate, 4), "typical_arrival_rate_per_min": round(typical / th.spike_bucket_minutes, 4),
                 "service_capacity_per_min": round(mu_total, 4), "peak_exceeds_capacity": exceeds,
                 "poisson_p_value_of_peak": float(poisson.sf(peak - 1, typical)),
                 "buckets_examined": n_b,
                 "thresholds": {"ratio": list(th.spike_ratio), "min_count": th.spike_min_count,
                                "alpha_family_wise": th.spike_alpha}},
                f"Arrivals reached {peak:.0f} per {th.spike_bucket_minutes:g} min ({peak_rate:.2f}/min), "
                f"{ratio:.1f}x the typical {typical:.0f} per bucket"
                + (f", above the total service capacity of {mu_total:.2f}/min" if exceeds else "")
                + f". The spike {'is still under way' if ongoing else 'has ended'}.",
                impact_text(),
                "Prepare surge capacity for recurring peaks: schedule extra counters ahead of the spike, "
                "and consider appointment smoothing or customer notifications to spread demand.",
                max(ep_start, ls), min(ep_end, we),
            ))

    elig = {cid: s for cid, s in stats.items() if s["served"] >= th.slow_min_samples and s["mean_service_s"]}
    lb_mask = np.isfinite(f.en) & np.isfinite(f.st) & (f.en >= ls) & (f.en < ws)
    for cid, s in elig.items():
        c = s["counter"]
        mean_c, sd_c, n_c = s["mean_service_s"], s["sd_service_s"], s["served"]
        var_c = (sd_c ** 2 / n_c) if sd_c else None
        evidence: list[dict[str, Any]] = []

        def add(kind: str, ref: float, label: str, ref_sample: np.ndarray | None = None):
            if ref <= 0:
                return
            z = None
            if var_c is not None:
                var_ref = 0.0
                if ref_sample is not None and len(ref_sample) > 1:
                    var_ref = float(ref_sample.var(ddof=1)) / len(ref_sample)
                z = (mean_c - ref) / math.sqrt(var_c + var_ref) if (var_c + var_ref) > 0 else None
            evidence.append({"reference": kind, "reference_mean_service_s": round(ref, 2),
                             "ratio": round(mean_c / ref, 3), "z_score": None if z is None else round(float(z), 2),
                             "label": label})

        peer_ids = [k for k in elig if k != cid]
        if peer_ids:
            pooled = np.concatenate([elig[k]["svc"] for k in peer_ids])
            add("peer_median", float(np.median([elig[k]["mean_service_s"] for k in peer_ids])),
                "peer counters", pooled)
        if c.rate_per_min > 0:
            add("configured_rate", 60.0 / c.rate_per_min, "its configured service rate")
        hist = (f.en - f.st)[lb_mask & (f.cid == cid)]
        if len(hist) >= th.slow_min_history_samples:
            add("own_history", float(hist.mean()), "its own earlier performance", hist)
        hits = [e for e in evidence
                if e["ratio"] >= th.slow_ratio[0] and (e["z_score"] is None or e["z_score"] >= th.slow_min_z)]
        if not hits:
            continue
        worst = max(hits, key=lambda e: e["ratio"])
        sev = severity_from_ladder(worst["ratio"], th.slow_ratio)
        peer_ev = next((e for e in evidence if e["reference"] == "peer_median"), None)
        res.findings.append(Finding(
            "slow_service", sev, queue_id, c.id,
            {"mean_service_s": round(mean_c, 2), "services_measured": n_c,
             "std_service_s": None if sd_c is None else round(sd_c, 2), "comparisons": evidence,
             "worst_reference": worst["reference"], "worst_ratio": worst["ratio"],
             "thresholds": {"ratio": list(th.slow_ratio), "min_samples": th.slow_min_samples, "min_z": th.slow_min_z}},
            f"{c.name} averaged {_min(mean_c)} min per customer over {n_c} services - "
            + "; ".join(f"{e['ratio']:.2f}x {e['label']} ({_min(e['reference_mean_service_s'])} min)" for e in hits) + ".",
            impact_text() + f" Each customer at {c.name} occupies the counter longer, reducing total throughput.",
            f"Investigate {c.name}: check staffing, equipment and the type of work routed to it; route complex "
            "cases to faster counters" + (" and review whether its configured service rate is accurate."
                                          if peer_ev and not any(e['reference'] == 'configured_rate' for e in hits) else "."),
            ws, we,
        ))

    if arrivals_w >= th.capacity_min_arrivals:
        if n_active == 0:
            res.findings.append(Finding(
                "capacity_demand_imbalance", "CRITICAL", queue_id, None,
                {"arrival_rate_per_min": round(lam, 4), "active_counters": 0, "service_capacity_per_min": 0.0,
                 "arrivals_in_window": arrivals_w, "queue_length_now": q_now},
                f"{arrivals_w} customers arrived in the window ({lam:.2f}/min) but no counter is active.",
                impact_text(), "Open or resume at least one counter immediately.", ws, we,
            ))
        elif mu_total > 0:
            rho = lam / mu_total
            sev = severity_from_ladder(rho, th.capacity_ratio)
            if sev:
                per_counter = mu_total / n_active
                needed = math.ceil(lam / (th.capacity_target_util * per_counter))
                res.findings.append(Finding(
                    "capacity_demand_imbalance", sev, queue_id, None,
                    {"arrival_rate_per_min": round(lam, 4), "service_capacity_per_min": round(mu_total, 4),
                     "demand_to_capacity_ratio": round(rho, 4), "active_counters": n_active,
                     "arrivals_in_window": arrivals_w, "queue_length_now": q_now,
                     "queue_length_at_window_start": q_start, "abandoned_in_window": abandoned_w,
                     "counters_needed_for_target_utilization": needed, "target_utilization": th.capacity_target_util,
                     "thresholds": {"ratio": list(th.capacity_ratio)}},
                    f"Arrivals averaged {lam:.2f}/min against a configured capacity of {mu_total:.2f}/min across "
                    f"{n_active} active counter(s): demand is {rho:.0%} of capacity"
                    + (" and the line grew from " + f"{q_start} to {q_now}." if q_now > q_start else "."),
                    impact_text(),
                    f"Add capacity: about {needed} counters of average speed are needed to keep utilisation at or "
                    f"below {th.capacity_target_util:.0%} (currently {n_active}). Otherwise waits will keep growing.",
                    ws, we,
                ))

    order = {s: i for i, s in enumerate(reversed(SEVERITIES))}
    res.findings.sort(key=lambda x: (order[x.severity], x.bottleneck_type))
    if not res.findings:
        res.notes.append("No bottleneck rule fired in this window; the supporting summary shows the measured values.")
    return res
