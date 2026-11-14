"""NumPy-only FIFO multi-counter simulator that builds the `entries` DataFrame the engines consume.

Independent of SimPy/SQLAlchemy on purpose: the pure engines (prediction, bottleneck, analytics, optimisation search)
are tested on data whose ground truth is known, and these tests run anywhere NumPy/Pandas are installed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

T0 = pd.Timestamp("2026-11-02T08:00:00Z")


def ts(minutes):
    return T0 + pd.to_timedelta(minutes, unit="min")


def simulate_entries(
    lam: float = 0.5, mean_service_min: float = 4.0, speeds=(1.0, 1.0, 1.0), n: int = 600, seed: int = 1,
    policy: str = "longest_idle", spikes=(), patience_min: float | None = None, first_counter_id: int = 1,
):
    """Return (entries_df, duration_minutes). `spikes` = [(start_min, end_min, multiplier)]."""
    rng = np.random.default_rng(seed)
    peak = max([1.0] + [m for _, _, m in spikes])
    arrivals, t = [], 0.0
    while len(arrivals) < n:
        t += rng.exponential(1.0 / (lam * peak))
        mult = next((m for s, e, m in spikes if s <= t < e), 1.0)
        if rng.random() * peak <= mult:
            arrivals.append(t)
    free = [0.0] * len(speeds)
    rows = []
    for k, a in enumerate(arrivals):
        ready = [i for i, f in enumerate(free) if f <= a]
        if ready:
            i = min(ready) if policy == "lowest_index" else min(ready, key=lambda j: free[j])
            start = a
        else:
            i = int(np.argmin(free))
            start = free[i]
        if patience_min is not None and start - a > rng.exponential(patience_min):
            rows.append(dict(status="abandoned", arrival=ts(a), start=pd.NaT, end=pd.NaT,
                             left=ts(a + rng.exponential(patience_min)), counter_id=np.nan))
            continue
        end = start + rng.exponential(mean_service_min / speeds[i])
        free[i] = end
        rows.append(dict(status="completed", arrival=ts(a), start=ts(start), end=ts(end), left=pd.NaT,
                         counter_id=float(first_counter_id + i)))
    df = pd.DataFrame(rows)
    return df, float(arrivals[-1])


def fake_simulate(cfg: dict) -> dict:
    """Stand-in for app.engines.simulation_engine.run_simulation (same keys the optimiser reads).

    Exponential service, Poisson arrivals, FIFO, `counter_assignment` honoured. Used so the optimiser's search logic
    is tested without SimPy; the real engine is exercised by the integration tests.
    """
    rng = np.random.default_rng(cfg["seed"])
    lam, dur = cfg["arrival_rate"], cfg["duration"]
    speeds = cfg["counter_speed_factors"]
    mean_s = cfg["mean_service_time"]
    arrivals, t = [], 0.0
    while True:
        t += rng.exponential(1.0 / lam)
        if t >= dur:
            break
        arrivals.append(t)
    free = [0.0] * len(speeds)
    busy = [0.0] * len(speeds)
    waits = []
    served = 0
    for a in arrivals:
        ready = [i for i, f in enumerate(free) if f <= a]
        if ready:
            i = min(ready) if cfg["counter_assignment"] == "lowest_index" else min(ready, key=lambda j: free[j])
            start = a
        else:
            i = int(np.argmin(free))
            start = free[i]
        if start >= dur:
            continue
        svc = rng.exponential(mean_s / speeds[i])
        end = start + svc
        free[i] = end
        busy[i] += min(end, dur) - start
        waits.append(start - a)
        served += int(end <= dur)
    w = np.array(waits) if waits else np.array([0.0])
    return {
        "avg_waiting_time": float(w.mean()), "p95_waiting_time": float(np.percentile(w, 95)),
        "avg_queue_length": float(w.sum() / dur), "throughput": served / dur, "abandoned": 0,
        "customers_remaining": len(arrivals) - served,
        "counters": [{"utilization": b / dur} for b in busy], "avg_utilization": float(np.mean(busy) / dur),
    }
