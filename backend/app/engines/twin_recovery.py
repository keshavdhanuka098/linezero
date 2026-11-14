"""Self-healing optimisation for the Digital Twin.

Three modes share one engine:

  * manual    - the user schedules actions (`TwinConfig.actions`) and simulates them (no code here; see the engine);
  * assisted  - `recommend()` diagnoses the scenario, generates candidate interventions and ranks them by simulating
                every candidate against the same seeds (common random numbers);
  * automatic - `auto_recover()` searches reactive recovery policies (open a closed counter / speed boost when the
                queue stays long) and returns the best one together with its before/after simulation.

Everything is simulation. Nothing here touches the real queues, counters or customers in the database.

Score (lower is better):  score = avg_wait + 0.5 * p95_wait + 20 * abandonment_rate     (minutes-equivalent)
The 20x abandonment weight and the 0.5x P95 weight are design choices, stated here and returned in every response.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.engines.twin_engine import CLOSED_REASONS, RecoveryPolicy, TwinConfig, run_replications
from app.engines.twin_scenarios import MAX_REPLICATIONS, improvement, paired_stat

SCORE_FORMULA = "score = avg_wait + 0.5 * p95_wait + 20 * abandonment_rate (lower is better)"
BOOST_FACTOR = 1.15
MAX_ACTIVATIONS_TRIED = 3
MAX_TOTAL_RUNS = 400


def score_of(summary: dict[str, float]) -> float:
    return summary["avg_waiting_time"] + 0.5 * summary["p95_waiting_time"] + 20.0 * summary["abandonment_rate"]


def _scores(result: dict[str, Any]) -> list[float]:
    return [score_of(s) for s in result["per_replication"]]


def _closed_counters(cfg: TwinConfig) -> list[int]:
    """Counters that start closed (reserve or unstaffed) and are never reopened by an existing action."""
    closed = set(cfg.standby_counters)
    if cfg.staff_available is not None:
        closed |= set(range(cfg.staff_available, cfg.num_counters))
    opened = {a.counter for a in cfg.actions if a.type == "activate_counter"}
    failed = {o.counter for o in cfg.outages}
    return sorted(closed - opened - failed)


def _check_budget(replications: int, runs_per_rep: int) -> None:
    if not 2 <= replications <= MAX_REPLICATIONS:
        raise ValueError(f"replications must be between 2 and {MAX_REPLICATIONS} for recommendations")
    if replications * runs_per_rep > MAX_TOTAL_RUNS:
        raise ValueError("Too many simulation runs requested; lower the number of replications")


def diagnose(cfg: TwinConfig, baseline: dict[str, Any]) -> dict[str, Any]:
    """Facts about why the baseline is congested. Every figure is read from simulation output or the configuration."""
    primary = baseline["primary"]
    eps = primary["episodes"]["bottlenecks"]
    open_counters = [c for c in baseline["counters"] if c["closed_time"] < cfg.duration - 1e-9]
    top = max(open_counters, key=lambda c: c["utilization_available"], default=None)
    idle = [c["name"] for c in open_counters if c["utilization_available"] < 0.4]
    speeds = cfg.counter_speed_factors or [1.0] * cfg.num_counters
    closed_static = _closed_counters(cfg)
    open_capacity = sum(speeds[i] / cfg.mean_service_time for i in range(cfg.num_counters) if i not in closed_static)
    load_ratio = cfg.arrival_rate / open_capacity if open_capacity > 0 else None
    return {
        "bottleneck_episodes": eps,
        "first_congestion_at": eps[0]["start"] if eps else None,
        "most_loaded_counter": None if top is None else {"index": top["counter_index"], "name": top["name"],
                                                         "utilization_while_open": top["utilization_available"]},
        "underused_counters": idle,
        "closed_counters": [f"Counter {i + 1}" for i in closed_static],
        "failed_counters": [f"Counter {o.counter + 1}" for o in cfg.outages],
        "base_load_ratio": load_ratio,
        "base_load_ratio_note": "arrival rate / capacity of counters open at t=0; ignores surges, outages and slow-downs",
        "avg_wait_min": baseline["summary"]["avg_waiting_time"],
        "p95_wait_min": baseline["summary"]["p95_waiting_time"],
        "max_queue": baseline["summary"]["max_queue_length"],
    }


def _candidates(cfg: TwinConfig, apply_at: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    reserve = _closed_counters(cfg)[:MAX_ACTIVATIONS_TRIED]
    for k in range(1, len(reserve) + 1):
        names = ", ".join(f"Counter {i + 1}" for i in reserve[:k])
        out.append({
            "id": f"activate_{k}", "type": "activate_counters",
            "label": f"Open {k} idle/closed counter{'s' if k > 1 else ''} ({names})",
            "description": f"Bring {names} online at t={apply_at:g} min.",
            "actions": [{"type": "activate_counter", "at": apply_at, "counter": i} for i in reserve[:k]],
            "patch": {}, "assumptions": ["Staff for the opened counters are available at the time of the action."],
            "extra_counters": k,
        })
    out.append({
        "id": "boost_staff", "type": "reallocate_staff",
        "label": f"Reallocate assisting staff (+{round((BOOST_FACTOR - 1) * 100)}% service speed)",
        "description": f"Cross-trained staff assist from t={apply_at:g} min, speeding every open counter.",
        "actions": [{"type": "boost_speed", "at": apply_at, "factor": BOOST_FACTOR}],
        "patch": {}, "assumptions": [f"The {BOOST_FACTOR}x speed-up is an assumption, not measured data."],
        "extra_counters": 0,
    })
    other = "lowest_index" if cfg.counter_assignment == "longest_idle" else "longest_idle"
    out.append({
        "id": f"assign_{other}", "type": "assignment_strategy",
        "label": f"Switch assignment strategy to '{other}'",
        "description": ("All counters share one queue, so this only changes which idle counter takes the next "
                        "customer; it mainly affects how load is spread, not the total capacity."),
        "actions": [], "patch": {"counter_assignment": other}, "assumptions": [], "extra_counters": 0,
    })
    if reserve:
        out.append({
            "id": "combo", "type": "combined", "label": "Open all reserve counters and add assisting staff",
            "description": "Combine opening the reserve counters with the staff speed-up.",
            "actions": [{"type": "activate_counter", "at": apply_at, "counter": i} for i in reserve]
                       + [{"type": "boost_speed", "at": apply_at, "factor": BOOST_FACTOR}],
            "patch": {}, "assumptions": ["Staff are available; the speed-up factor is an assumption."],
            "extra_counters": len(reserve),
        })
    return out


def _with(cfg: TwinConfig, cand: dict[str, Any]) -> TwinConfig:
    from app.engines.twin_engine import ScheduledAction

    actions = list(cfg.actions) + [ScheduledAction(**a) for a in cand["actions"]]
    return cfg.model_copy(update={"actions": actions, **cand["patch"]})


def recommend(cfg: TwinConfig, replications: int = 6, seed: int = 2026,
              max_extra_cost: float | None = None) -> dict[str, Any]:
    """Assisted mode: rank candidate interventions by simulated benefit."""
    n_cands = len(_candidates(cfg, 0.0))
    _check_budget(replications, n_cands + 1)
    baseline = run_replications(cfg, replications, seed, detail_first=True)
    diag = diagnose(cfg, baseline)
    apply_at = diag["first_congestion_at"] if diag["first_congestion_at"] is not None else 0.0
    base_scores = _scores(baseline)
    base_score = float(np.mean(base_scores))
    rows = []
    for cand in _candidates(cfg, apply_at):
        res = run_replications(_with(cfg, cand), replications, seed, detail_first=False)
        scores = _scores(res)
        pair = paired_stat(base_scores, scores)
        extra_cost = res["summary"]["resource_cost"] - baseline["summary"]["resource_cost"]
        affordable = max_extra_cost is None or extra_cost <= max_extra_cost + 1e-9
        rows.append({
            **{k: cand[k] for k in ("id", "type", "label", "description", "actions", "patch", "assumptions")},
            "score": float(np.mean(scores)), "score_delta": float(np.mean(scores)) - base_score,
            "score_paired": pair, "significant": bool(pair and pair["significant"]),
            "improves": float(np.mean(scores)) < base_score,
            "extra_cost": extra_cost, "within_budget": affordable,
            "improvement": improvement(baseline, res),
            "summary": res["summary"],
        })
    rows.sort(key=lambda r: r["score"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    best = next((r for r in rows if r["improves"] and r["significant"] and r["within_budget"]), None)
    notes = []
    if not diag["bottleneck_episodes"]:
        notes.append("The baseline run showed no sustained congestion, so interventions have little to fix.")
    if best is None:
        notes.append("No candidate improved the score by more than simulation noise within the budget.")
    return {
        "mode": "assisted", "simulation_only": True, "replications": replications, "base_seed": seed,
        "apply_at": apply_at, "score_formula": SCORE_FORMULA, "baseline_score": base_score,
        "baseline": {"summary": baseline["summary"], "stats": baseline["stats"], "counters": baseline["counters"]},
        "diagnosis": diag, "recommendations": rows, "recommended_id": best["id"] if best else None,
        "notes": notes,
        "disclaimer": "Recommendations are simulation results. LineZero never changes real queues automatically.",
    }


def _policy_grid(cfg: TwinConfig) -> list[RecoveryPolicy]:
    reserve = len(_closed_counters(cfg))
    cong = cfg.congestion_threshold
    thresholds = sorted({max(3, cong // 2), cong})
    grid = []
    for acts in range(0, min(reserve, MAX_ACTIVATIONS_TRIED) + 1):
        for boost in (1.0, BOOST_FACTOR):
            if acts == 0 and boost == 1.0:
                continue
            for th in thresholds:
                grid.append(RecoveryPolicy(queue_threshold=th, sustain=1.0, check_interval=1.0, cooldown=1.0,
                                           max_activations=acts, boost_factor=boost))
    return grid


def auto_recover(cfg: TwinConfig, replications: int = 6, seed: int = 2026,
                 max_extra_cost: float | None = None) -> dict[str, Any]:
    """Automatic simulation recovery: search reactive policies; return the best and its before/after simulation."""
    grid = _policy_grid(cfg)
    _check_budget(replications, len(grid) + 1)
    baseline = run_replications(cfg, replications, seed, detail_first=True)
    base_scores = _scores(baseline)
    base_score = float(np.mean(base_scores))
    rows = []
    for pol in grid:
        res = run_replications(cfg.model_copy(update={"recovery": pol}), replications, seed, detail_first=False)
        scores = _scores(res)
        pair = paired_stat(base_scores, scores)
        extra_cost = res["summary"]["resource_cost"] - baseline["summary"]["resource_cost"]
        rows.append({
            "policy": pol.model_dump(), "score": float(np.mean(scores)),
            "score_delta": float(np.mean(scores)) - base_score, "significant": bool(pair and pair["significant"]),
            "extra_cost": extra_cost, "within_budget": max_extra_cost is None or extra_cost <= max_extra_cost + 1e-9,
            "summary": res["summary"],
        })
    rows.sort(key=lambda r: r["score"])
    chosen = next((r for r in rows if r["score"] < base_score and r["significant"] and r["within_budget"]), None)
    out: dict[str, Any] = {
        "mode": "automatic", "simulation_only": True, "replications": replications, "base_seed": seed,
        "score_formula": SCORE_FORMULA, "baseline_score": base_score, "policies_evaluated": len(rows),
        "candidates": rows[:10],
        "baseline": {"summary": baseline["summary"], "stats": baseline["stats"], "counters": baseline["counters"],
                     "primary": baseline["primary"]},
        "chosen": None, "recovered": None, "before_after": None,
        "disclaimer": "Automatic recovery runs inside the simulation only. LineZero never changes real queues.",
    }
    if chosen is None:
        out["notes"] = ["No reactive policy beat the unmanaged scenario by more than simulation noise within the budget."]
        return out
    recovered_cfg = cfg.model_copy(update={"recovery": RecoveryPolicy(**chosen["policy"])})
    recovered = run_replications(recovered_cfg, replications, seed, detail_first=True)
    out["chosen"] = chosen
    out["recovered"] = {"summary": recovered["summary"], "stats": recovered["stats"],
                        "counters": recovered["counters"], "primary": recovered["primary"]}
    out["before_after"] = improvement(baseline, recovered)
    out["notes"] = [f"Policy chosen from {len(rows)} evaluated by simulation; this is the best of that family, "
                    "not a proof of global optimality."]
    return out


__all__ = ["recommend", "auto_recover", "diagnose", "score_of", "SCORE_FORMULA", "CLOSED_REASONS"]
