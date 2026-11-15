"""Predefined what-if scenarios and side-by-side scenario comparison for the Digital Twin.

Comparison uses common random numbers: every scenario is simulated with the same seeds (base_seed, base_seed+1, ...),
so differences between scenarios are paired and not swamped by sampling noise. Every number returned is measured from
simulation runs; nothing is estimated by hand.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.engines.twin_engine import SUMMARY_KEYS, TwinConfig, run_replications

MAX_COMPARE_SCENARIOS = 5
MAX_REPLICATIONS = 20

#: direction in which a metric improves (None = neither direction is "better")
DIRECTION: dict[str, str | None] = {
    "avg_waiting_time": "lower", "p95_waiting_time": "lower", "max_queue_length": "lower",
    "total_served": "higher", "abandoned": "lower", "abandonment_rate": "lower",
    "avg_utilization_available": None, "resource_cost": "lower", "avg_queue_length": "lower",
    "throughput": "higher",
}
LABELS = {
    "avg_waiting_time": "Average wait (min)", "p95_waiting_time": "P95 wait (min)",
    "max_queue_length": "Max queue length", "total_served": "Customers served", "abandoned": "Abandoned customers",
    "abandonment_rate": "Abandonment rate", "avg_utilization_available": "Counter utilization (while open)",
    "resource_cost": "Resource cost", "avg_queue_length": "Average queue length", "throughput": "Throughput (per min)",
}

PRESET_IDS = ["normal", "arrival_surge", "staff_shortage", "counter_failure", "slow_service", "peak_hour"]


def preset_scenarios(base: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the six predefined scenarios from a base configuration (arrival_rate, mean_service_time,
    num_counters, duration are required). Each scenario is a complete TwinConfig-compatible dict."""
    d = float(base["duration"])
    n = int(base["num_counters"])
    root = {k: v for k, v in base.items() if k not in ("seed", "record_trace")}

    def mk(sid: str, name: str, description: str, assumptions: list[str], **patch: Any) -> dict[str, Any]:
        return {"id": sid, "name": name, "description": description, "assumptions": assumptions,
                "configuration": {**root, **patch}}

    staff = max(1, round(n * 0.6)) if n > 1 else 1
    return [
        mk("normal", "Normal operations", "Baseline demand and full staffing with every counter working.",
           ["Arrivals are Poisson at the base rate.", "All counters are staffed and working for the whole run."]),
        mk("arrival_surge", "Arrival surge",
           "Customer arrivals double between 30% and 60% of the run, then return to normal.",
           ["The surge multiplier (2.0x) is an illustrative assumption, not measured data."],
           arrival_profile=[{"start": round(d * 0.3, 4), "end": round(d * 0.6, 4), "multiplier": 2.0}]),
        mk("staff_shortage", "Staff shortage",
           f"Only {staff} of {n} counters are staffed; the rest stay closed.",
           ["Staffed counters are the lowest-numbered ones.", "Shortage is 40% of counters (rounded); illustrative."],
           staff_available=staff),
        mk("counter_failure", "Counter failure",
           "Counter 1 fails at 25% of the run and is repaired at 75%.",
           ["The customer being served at the moment of failure finishes first.",
            "Failure window is illustrative, not measured."],
           outages=[{"counter": 0, "start": round(d * 0.25, 4), "end": round(d * 0.75, 4), "kind": "failure"}]),
        mk("slow_service", "Slow service",
           "Every counter works 30% slower from 20% of the run onward.",
           ["Speed factor 0.7 is an illustrative assumption."],
           speed_changes=[{"counter": None, "start": round(d * 0.2, 4), "end": None, "factor": 0.7}]),
        mk("peak_hour", "Peak-hour congestion",
           "Demand ramps to 1.5x, peaks at 2.2x, then eases to 1.3x.",
           ["Multipliers are an illustrative peak shape, not fitted to historical data."],
           arrival_profile=[
               {"start": round(d * 0.2, 4), "end": round(d * 0.4, 4), "multiplier": 1.5},
               {"start": round(d * 0.4, 4), "end": round(d * 0.7, 4), "multiplier": 2.2},
               {"start": round(d * 0.7, 4), "end": round(d * 0.85, 4), "multiplier": 1.3},
           ]),
    ]


def paired_stat(before: list[float], after: list[float]) -> dict[str, Any] | None:
    """Paired difference (after - before) across replications with a 95% t interval."""
    if len(before) != len(after) or len(before) < 2:
        return None
    diff = np.asarray(after, dtype=float) - np.asarray(before, dtype=float)
    mean = float(diff.mean())
    sd = float(diff.std(ddof=1))
    if sd == 0.0:
        return {"mean_diff": mean, "ci95": 0.0, "significant": mean != 0.0, "n": len(diff)}
    from scipy.stats import t as student_t
    half = float(student_t.ppf(0.975, len(diff) - 1) * sd / math.sqrt(len(diff)))
    return {"mean_diff": mean, "ci95": half, "significant": abs(mean) > half, "n": len(diff)}


def improvement(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Before/after block for every metric: `base` and `other` are `run_replications` results."""
    out: dict[str, Any] = {}
    for k in SUMMARY_KEYS:
        b, o = base["stats"][k]["mean"], other["stats"][k]["mean"]
        pair = paired_stat([s[k] for s in base["per_replication"]], [s[k] for s in other["per_replication"]])
        better = DIRECTION[k]
        delta = o - b
        pct = None if b == 0 else delta / abs(b) * 100.0
        improved = None
        if better and pair and pair["significant"]:
            improved = (delta < 0) if better == "lower" else (delta > 0)
        out[k] = {"label": LABELS[k], "before": b, "after": o, "delta": delta, "pct": pct,
                  "better": better, "paired": pair, "significant": bool(pair and pair["significant"]),
                  "improved": improved}
    return out


def compare_scenarios(items: list[tuple[str, TwinConfig]], replications: int, base_seed: int) -> dict[str, Any]:
    if not 2 <= len(items) <= MAX_COMPARE_SCENARIOS:
        raise ValueError(f"Compare between 2 and {MAX_COMPARE_SCENARIOS} scenarios")
    if not 1 <= replications <= MAX_REPLICATIONS:
        raise ValueError(f"replications must be between 1 and {MAX_REPLICATIONS}")
    results = [run_replications(cfg, replications, base_seed, detail_first=False) for _, cfg in items]
    names = [n for n, _ in items]
    metrics: dict[str, Any] = {}
    for k in SUMMARY_KEYS:
        values = [r["stats"][k]["mean"] for r in results]
        base = values[0]
        better = DIRECTION[k]
        best = None
        if better and len(set(values)) > 1:
            best = int(np.argmin(values) if better == "lower" else np.argmax(values))
        metrics[k] = {
            "label": LABELS[k], "better": better, "values": values,
            "ci95": [r["stats"][k]["ci95"] for r in results],
            "delta": [v - base for v in values],
            "pct": [None if base == 0 else (v - base) / abs(base) * 100.0 for v in values],
            "best_index": best,
            "paired": [None] + [paired_stat([s[k] for s in results[0]["per_replication"]],
                                            [s[k] for s in r["per_replication"]]) for r in results[1:]],
        }
    return {
        "labels": names, "baseline_index": 0, "replications": replications, "base_seed": base_seed,
        "scenarios": [{"name": n, "summary": r["summary"], "stats": r["stats"], "counters": r["counters"]}
                      for n, r in zip(names, results)],
        "metrics": metrics,
        "improvements": [{"scenario": names[i], "vs": names[0], "metrics": improvement(results[0], results[i])}
                         for i in range(1, len(results))],
        "method": ("Each scenario is simulated with the same seeds (common random numbers); differences are paired "
                   "across replications and reported with a 95% t interval. 'significant' means the interval "
                   "excludes zero."),
    }
