"""Short-horizon forecasting (5/15/30/60 minutes) for the Digital Twin.

Method (all of it is reproducible and inspectable):
  1. Take the CURRENT queue state from the database: customers waiting, which counters are busy, each counter's
     service rate, and the recent arrival rate (computed by the existing prediction engine from real history).
  2. Start many replications of the project's SimPy engine from that state and let it run for the longest horizon.
  3. At each horizon read the queue length, arrivals so far, counter utilisation and congestion from the replications.
  4. The waiting time a customer arriving at the horizon would face is computed from the simulated state with the
     existing prediction engine's baseline formula (`baseline_wait`), so forecasts and live predictions share one
     definition of "waiting time".

Limits: arrival rate and counter speeds are held constant over the horizon, service times are exponential, nobody
abandons, no counter fails. The spread across replications is simulation variability, not a validated prediction
interval. No accuracy figure is claimed.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.engines import prediction_engine as pe
from app.engines.twin_engine import TwinConfig, run_twin

HORIZONS = (5, 15, 30, 60)
MAX_INITIAL_QUEUE = 500
MIN_RATE = 1e-3


class ForecastUnavailable(Exception):
    """The live state does not allow a forecast (e.g. no active counters). Maps to HTTP 409."""


def risk_band(p: float) -> str:
    """Illustrative bands on the share of replications that reach the congestion threshold."""
    return "low" if p < 0.2 else "moderate" if p < 0.5 else "high"


def build_config(state: dict[str, Any], horizon: float, seed: int) -> tuple[TwinConfig, dict[str, Any]]:
    counters = state["counters"]
    active = [c for c in counters if c["active"]]
    if not active:
        raise ForecastUnavailable("The queue has no active counters, so no forecast can be made")
    ref = float(np.mean([c["rate_per_min"] for c in active]))
    rate = state.get("arrival_rate_per_min")
    notes: dict[str, Any] = {"arrival_rate_floored": False, "queue_truncated": False}
    if rate is None or rate <= 0:
        rate, notes["arrival_rate_floored"] = MIN_RATE, True
    queue = int(state["queue_length"])
    if queue > MAX_INITIAL_QUEUE:
        queue, notes["queue_truncated"] = MAX_INITIAL_QUEUE, True
    cfg = TwinConfig(
        arrival_rate=float(rate), mean_service_time=1.0 / ref, num_counters=len(counters), duration=float(horizon),
        counter_speed_factors=[c["rate_per_min"] / ref for c in counters],
        standby_counters=[i for i, c in enumerate(counters) if not c["active"]],
        initial_queue=queue, initial_busy_counters=[i for i, c in enumerate(counters) if c["active"] and c["busy"]],
        sample_interval=1.0, seed=seed,
    )
    return cfg, notes


def _pct(a: np.ndarray, q: float) -> float:
    return float(np.percentile(a, q))


def forecast(state: dict[str, Any], horizons: tuple[int, ...] = HORIZONS, replications: int = 30,
             seed: int = 2026) -> dict[str, Any]:
    if not 5 <= replications <= 200:
        raise ValueError("replications must be between 5 and 200")
    horizon = max(horizons)
    cfg, notes = build_config(state, horizon, seed)
    active = [c for c in state["counters"] if c["active"]]
    rates = [c["rate_per_min"] for c in active]
    n_active = len(active)
    mu_total = float(sum(rates))
    lam = cfg.arrival_rate
    cong_q = max(5, 2 * n_active)

    runs = [run_twin(cfg.model_copy(update={"seed": seed + r}), detail=False) for r in range(replications)]
    out_h: list[dict[str, Any]] = []
    for h in horizons:
        q, busy, arrivals, util, waits, peak = [], [], [], [], [], []
        for run in runs:
            frames = run["frames"]
            at = next(f for f in frames if abs(f["t"] - h) < 1e-6)
            window = [f for f in frames if h - min(5, h) < f["t"] <= h + 1e-6]
            q.append(at["queue"])
            busy.append(at["in_service"])
            arrivals.append(at["arrivals"])
            util.append(float(np.mean([f["in_service"] / n_active for f in window])))
            peak.append(max(f["queue"] for f in frames if f["t"] <= h + 1e-6))
            base = pe.baseline_wait(pe.BaselineInputs(
                queue_length=int(at["queue"]), active_counters=n_active, busy_counters=int(at["in_service"]),
                counter_rates_per_min=rates, arrival_rate_per_min=lam))
            waits.append(base["waiting_time_s"] / 60.0)
        qa, ua, wa, aa = np.array(q, float), np.array(util), np.array(waits), np.array(arrivals, float)
        p_cong = float(np.mean(np.array(peak) >= cong_q))
        out_h.append({
            "horizon_min": h,
            "queue_length": {"mean": float(qa.mean()), "p10": _pct(qa, 10), "p90": _pct(qa, 90)},
            "waiting_time_min": {"mean": float(wa.mean()), "p10": _pct(wa, 10), "p90": _pct(wa, 90)},
            "arrivals_since_now": {"mean": float(aa.mean()), "p10": _pct(aa, 10), "p90": _pct(aa, 90)},
            "counter_utilization": {"mean": float(ua.mean()), "p10": _pct(ua, 10), "p90": _pct(ua, 90)},
            "congestion": {"probability": p_cong, "risk": risk_band(p_cong), "threshold_queue": cong_q,
                           "definition": f"share of replications whose queue reached {cong_q} at any point up to this horizon"},
        })
    return {
        "method": "replicated_simpy_from_live_state", "replications": replications, "seed": seed,
        "horizons": out_h,
        "starting_state": {
            "queue_length": cfg.initial_queue, "active_counters": n_active,
            "busy_counters": len(cfg.initial_busy_counters), "arrival_rate_per_min": lam,
            "arrival_rate_source": state.get("arrival_rate_source"), "service_capacity_per_min": mu_total,
            "load_ratio": lam / mu_total if mu_total > 0 else None,
        },
        "assumptions": [
            "Arrival rate and counter speeds stay constant over the horizon.",
            "Service times are exponential; customers do not abandon; no counter fails.",
            "Customers already being served finish after a freshly sampled (memoryless) remaining time.",
            "Spread (p10-p90) is variability across simulation replications, not a validated prediction interval.",
        ],
        "notes": notes,
    }


__all__ = ["forecast", "build_config", "ForecastUnavailable", "HORIZONS"]
