"""Side-by-side comparison of simulation results."""
from __future__ import annotations

from typing import Any

METRICS: dict[str, str | None] = {
    "avg_waiting_time": "lower",
    "max_waiting_time": "lower",
    "p95_waiting_time": "lower",
    "avg_queue_length": "lower",
    "max_queue_length": "lower",
    "customers_remaining": "lower",
    "abandoned": "lower",
    "total_served": "higher",
    "throughput": "higher",
    "avg_service_time": None,
    "avg_utilization": None,
}


def compare_results(labels: list[str], results: list[dict]) -> dict[str, Any]:
    """Compare every run to the first one (the baseline)."""
    out: dict[str, Any] = {"baseline_index": 0, "labels": labels, "metrics": {}}
    for metric, better in METRICS.items():
        values = [r[metric] for r in results]
        base = values[0]
        deltas = [round(v - base, 6) for v in values]
        pct = [None if base == 0 else round((v - base) / abs(base) * 100, 3) for v in values]
        best_index = None
        if better and len(set(values)) > 1:
            target = min(values) if better == "lower" else max(values)
            best_index = values.index(target)
        out["metrics"][metric] = {
            "better": better, "values": values, "delta_vs_baseline": deltas,
            "pct_change_vs_baseline": pct, "best_index": best_index,
        }
    return out
