"""Resource optimisation: a transparent, constraint-respecting search that compares allocations by simulation.

What it does
  * Candidate allocations = "use the k fastest available counters" for every feasible k, each combined with an
    assignment policy (`lowest_index` = how serve-next works today, or `longest_idle` = spread work evenly).
  * Every candidate - including the current allocation - is simulated with the SAME random seeds (common random
    numbers), several replications each, using the project's SimPy engine. Differences are therefore paired.
  * Score J = w_wait * (wait / reference_wait) + w_imbalance * (max-min utilisation) + w_cost * (cost / current cost).
    The lowest score among feasible candidates is proposed - but only if it beats the current allocation by a
    minimum margin; otherwise the current allocation is reported as already the best of those evaluated.

What it does NOT do
  * It does not prove global optimality. Only the candidate family above is searched (see `search_space` in the
    result), results are simulation estimates with sampling error, and the simulation starts from an empty queue.
  * It never proposes anything infeasible: every proposed allocation is re-validated against the constraints
    (`validate_allocation`) and the function raises if validation fails.

Units: rates customers/minute; durations minutes; cost in the caller's currency per counter-hour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
from scipy.stats import t as student_t

POLICY_CURRENT = "lowest_index"
POLICIES = ("lowest_index", "longest_idle")
MAX_CANDIDATES = 60
MAX_TOTAL_ARRIVALS = 5_000_000
WAIT_REFERENCE_FLOOR_MIN = 0.5


class OptimizationError(ValueError):
    """Bad input / unsupported request (HTTP 422)."""


class OptimizationInfeasible(Exception):
    """No allocation satisfies the constraints (HTTP 409)."""


@dataclass
class CounterSpec:
    key: str
    name: str
    rate_per_min: float
    status: str
    counter_id: int | None = None
    cost_per_hour: float = 1.0


@dataclass
class Constraints:
    max_active_counters: int | None = None
    min_active_counters: int = 1
    max_cost_per_hour: float | None = None
    max_counter_utilization: float | None = None
    allow_new_counters: int = 0
    allow_policy_change: bool = True

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Settings:
    duration_min: float = 480.0
    replications: int = 8
    seed: int = 12345
    service_distribution: str = "exponential"
    w_wait: float = 1.0
    w_imbalance: float = 0.5
    w_cost: float = 0.25
    min_improvement: float = 0.02

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


Simulate = Callable[[dict[str, Any]], dict[str, Any]]


def default_simulate(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run the project's SimPy engine (imported lazily so this module has no hard SimPy dependency)."""
    from app.engines.simulation_engine import SimulationConfig, run_simulation

    return run_simulation(SimulationConfig(**cfg))


@dataclass(frozen=True)
class Allocation:
    keys: tuple[str, ...]
    policy: str


def validate_allocation(
    alloc: Allocation, pool: dict[str, CounterSpec], c: Constraints
) -> list[dict[str, Any]]:
    """Return the list of constraint checks (each {name, limit, value, ok}); all must be ok for a valid allocation."""
    checks: list[dict[str, Any]] = []
    unknown = [k for k in alloc.keys if k not in pool]
    dup = len(set(alloc.keys)) != len(alloc.keys)
    closed = [k for k in alloc.keys if k in pool and pool[k].status == "closed"]
    checks.append({"name": "counters_exist_and_distinct", "limit": "all chosen counters exist once", "value": {
        "unknown": unknown, "duplicates": dup}, "ok": not unknown and not dup})
    checks.append({"name": "no_closed_counters", "limit": "closed counters cannot be used", "value": closed,
                   "ok": not closed})
    n = len(alloc.keys)
    checks.append({"name": "min_active_counters", "limit": c.min_active_counters, "value": n, "ok": n >= c.min_active_counters})
    if c.max_active_counters is not None:
        checks.append({"name": "max_active_counters", "limit": c.max_active_counters, "value": n,
                       "ok": n <= c.max_active_counters})
    new_used = sum(1 for k in alloc.keys if k in pool and pool[k].status == "new")
    checks.append({"name": "new_counters_allowed", "limit": c.allow_new_counters, "value": new_used,
                   "ok": new_used <= c.allow_new_counters})
    cost = sum(pool[k].cost_per_hour for k in alloc.keys if k in pool)
    if c.max_cost_per_hour is not None:
        checks.append({"name": "max_cost_per_hour", "limit": c.max_cost_per_hour, "value": round(cost, 4),
                       "ok": cost <= c.max_cost_per_hour + 1e-9})
    checks.append({"name": "assignment_policy_allowed",
                   "limit": "any" if c.allow_policy_change else POLICY_CURRENT, "value": alloc.policy,
                   "ok": alloc.policy in POLICIES and (c.allow_policy_change or alloc.policy == POLICY_CURRENT)})
    return checks


def _all_ok(checks: list[dict[str, Any]]) -> bool:
    return all(ch["ok"] for ch in checks)


def build_pool(existing: list[CounterSpec], c: Constraints, new_rate: float, new_cost: float) -> dict[str, CounterSpec]:
    pool = {s.key: s for s in existing if s.status != "closed"}
    for i in range(1, c.allow_new_counters + 1):
        pool[f"new-{i}"] = CounterSpec(f"new-{i}", f"New counter {i}", new_rate, "new", None, new_cost)
    return pool


def generate_candidates(
    pool: dict[str, CounterSpec], current: Allocation, c: Constraints
) -> list[Allocation]:
    ranked = sorted(pool.values(), key=lambda s: (-s.rate_per_min, s.counter_id if s.counter_id is not None else 10**9,
                                                  s.key))
    hi = min(len(ranked), c.max_active_counters or len(ranked))
    policies = POLICIES if c.allow_policy_change else (POLICY_CURRENT,)
    out: list[Allocation] = []
    seen: set[Allocation] = set()

    def add(a: Allocation) -> None:
        if a not in seen and _all_ok(validate_allocation(a, pool, c)):
            seen.add(a)
            out.append(a)

    def service_order(keys: list[str]) -> tuple[str, ...]:
        return tuple(sorted(keys, key=lambda k: (pool[k].counter_id is None,
                                                 pool[k].counter_id if pool[k].counter_id is not None else 0, k)))

    for k in range(max(c.min_active_counters, 1), hi + 1):
        top = service_order([s.key for s in ranked[:k]])
        for p in policies:
            add(Allocation(top, p))
    for p in policies:
        add(Allocation(current.keys, p))
    return out[:MAX_CANDIDATES]


def _sim_config(alloc: Allocation, pool: dict[str, CounterSpec], lam: float, ref_rate: float, st: Settings,
                seed: int) -> dict[str, Any]:
    rates = [pool[k].rate_per_min for k in alloc.keys]
    factors = [r / ref_rate for r in rates]
    if any(f > 100 or f <= 0 for f in factors):
        raise OptimizationError("Counter service rates differ by more than 100x; cannot be simulated")
    return {
        "arrival_rate": lam, "mean_service_time": 1.0 / ref_rate, "num_counters": len(rates),
        "duration": st.duration_min, "seed": int(seed), "counter_speed_factors": factors,
        "counter_assignment": alloc.policy, "service_distribution": st.service_distribution,
        "arrival_distribution": "poisson",
    }


def evaluate(alloc: Allocation, pool: dict[str, CounterSpec], lam: float, ref_rate: float, st: Settings,
             simulate: Simulate) -> dict[str, Any]:
    reps = []
    for r in range(st.replications):
        res = simulate(_sim_config(alloc, pool, lam, ref_rate, st, st.seed + r))
        reps.append(res)
    waits = np.array([x["avg_waiting_time"] for x in reps], dtype=float)
    p95 = np.array([x["p95_waiting_time"] for x in reps], dtype=float)
    utils = np.array([[c["utilization"] for c in x["counters"]] for x in reps], dtype=float)
    mean_utils = utils.mean(axis=0)
    cost = sum(pool[k].cost_per_hour for k in alloc.keys)
    rho = lam / sum(pool[k].rate_per_min for k in alloc.keys)
    return {
        "waits_per_rep": waits.tolist(),
        "avg_waiting_time_min": float(waits.mean()),
        "avg_waiting_time_min_std_error": float(waits.std(ddof=1) / math.sqrt(len(waits))) if len(waits) > 1 else None,
        "p95_waiting_time_min": float(p95.mean()),
        "avg_queue_length": float(np.mean([x["avg_queue_length"] for x in reps])),
        "throughput_per_min": float(np.mean([x["throughput"] for x in reps])),
        "abandoned_per_run": float(np.mean([x.get("abandoned", 0) for x in reps])),
        "customers_remaining_at_end": float(np.mean([x.get("customers_remaining", 0) for x in reps])),
        "avg_utilization": float(mean_utils.mean()),
        "counter_utilization": {k: float(u) for k, u in zip(alloc.keys, mean_utils)},
        "utilization_imbalance": float(mean_utils.max() - mean_utils.min()) if len(mean_utils) > 1 else 0.0,
        "max_counter_utilization": float(mean_utils.max()),
        "cost_per_hour": float(cost),
        "demand_to_capacity_ratio": float(rho),
        "stable": bool(rho < 1.0),
    }


def _score(m: dict[str, Any], ref_wait: float, ref_cost: float, st: Settings) -> float:
    return (st.w_wait * m["avg_waiting_time_min"] / ref_wait
            + st.w_imbalance * m["utilization_imbalance"]
            + st.w_cost * (m["cost_per_hour"] / ref_cost if ref_cost > 0 else 0.0))


def paired_difference(cur: list[float], new: list[float]) -> dict[str, Any]:
    """Improvement = current - proposed, paired by replication (same random numbers)."""
    d = np.asarray(cur, dtype=float) - np.asarray(new, dtype=float)
    n = len(d)
    mean = float(d.mean())
    if n < 2:
        return {"mean": mean, "std_error": None, "ci95": None, "significant": None, "replications": n}
    se = float(d.std(ddof=1) / math.sqrt(n))
    half = float(student_t.ppf(0.975, n - 1) * se)
    return {"mean": mean, "std_error": se, "ci95": [mean - half, mean + half],
            "significant": bool(se > 0 and abs(mean) > half) if se > 0 else bool(mean != 0), "replications": n}


def _describe(alloc: Allocation, pool: dict[str, CounterSpec], current_keys: set[str]) -> dict[str, Any]:
    items = []
    for k in alloc.keys:
        s = pool[k]
        items.append({
            "counter_id": s.counter_id, "key": s.key, "name": s.name, "service_rate_per_min": s.rate_per_min,
            "status_now": s.status, "cost_per_hour": s.cost_per_hour,
            "action": ("keep" if k in current_keys else ("add_new" if s.status == "new" else "activate")),
        })
    deactivate = [{"counter_id": pool[k].counter_id, "key": k, "name": pool[k].name, "action": "deactivate"}
                  for k in current_keys if k not in alloc.keys and k in pool]
    return {
        "assignment_policy": alloc.policy, "active_counter_count": len(alloc.keys), "counters": items,
        "counters_to_deactivate": deactivate,
        "total_service_capacity_per_min": float(sum(pool[k].rate_per_min for k in alloc.keys)),
        "cost_per_hour": float(sum(pool[k].cost_per_hour for k in alloc.keys)),
    }


def optimize(
    existing: list[CounterSpec], arrival_rate: float, constraints: Constraints | None = None,
    settings: Settings | None = None, new_counter_rate: float | None = None, new_counter_cost: float | None = None,
    simulate: Simulate | None = None,
) -> dict[str, Any]:
    c = constraints or Constraints()
    st = settings or Settings()
    simulate = simulate or default_simulate
    if not (arrival_rate > 0 and math.isfinite(arrival_rate)):
        raise OptimizationError("arrival_rate must be a finite number > 0 (customers per minute)")
    if st.replications < 1 or st.duration_min <= 0:
        raise OptimizationError("replications must be >= 1 and duration_min > 0")
    if c.min_active_counters < 1:
        raise OptimizationError("min_active_counters must be >= 1")
    if c.max_active_counters is not None and c.max_active_counters < c.min_active_counters:
        raise OptimizationError("max_active_counters must be >= min_active_counters")
    usable = [s for s in existing if s.status != "closed"]
    if not usable and c.allow_new_counters == 0:
        raise OptimizationInfeasible("The queue has no usable (non-closed) counters and new counters are not allowed")
    rates = [s.rate_per_min for s in usable] or [new_counter_rate or 0.0]
    if any(r <= 0 for r in rates):
        raise OptimizationError("Counter service rates must be > 0")
    if c.allow_new_counters and not (new_counter_rate or usable):
        raise OptimizationError("new_counter_rate is required when the queue has no counters")
    new_rate = new_counter_rate if new_counter_rate else float(np.median(rates))
    avg_cost = float(np.mean([s.cost_per_hour for s in usable])) if usable else 1.0
    new_cost = new_counter_cost if new_counter_cost is not None else avg_cost
    pool = build_pool(existing, c, new_rate, new_cost)

    active_now = [s for s in existing if s.status == "active"]
    current = Allocation(tuple(s.key for s in active_now), POLICY_CURRENT)
    if not current.keys:
        raise OptimizationInfeasible(
            "No counter is currently active, so there is no current allocation to compare against. "
            "Resume at least one counter first (the capacity_demand_imbalance rule already reports this).")

    cands = generate_candidates(pool, current, c)
    if not cands:
        raise OptimizationInfeasible("No allocation satisfies the constraints (check max_cost_per_hour / counter limits)")
    if current not in cands:
        cands.append(current)
    total_arrivals = arrival_rate * st.duration_min * st.replications * len(cands)
    if total_arrivals > MAX_TOTAL_ARRIVALS:
        raise OptimizationError(
            f"Too much simulation work ({total_arrivals:,.0f} simulated arrivals > {MAX_TOTAL_ARRIVALS:,}); "
            "lower replications or duration_min")

    ref_rate = float(np.mean([pool[k].rate_per_min for k in pool]))
    evaluated: dict[Allocation, dict[str, Any]] = {a: evaluate(a, pool, arrival_rate, ref_rate, st, simulate)
                                                   for a in cands}
    cur_m = evaluated[current]
    ref_wait = max(cur_m["avg_waiting_time_min"], WAIT_REFERENCE_FLOOR_MIN)
    ref_cost = cur_m["cost_per_hour"]
    cur_checks = validate_allocation(current, pool, c)
    cur_ok = _all_ok(cur_checks)

    rows = []
    for a, m in evaluated.items():
        checks = validate_allocation(a, pool, c)
        util_ok = (c.max_counter_utilization is None) or (m["max_counter_utilization"] <= c.max_counter_utilization)
        feasible = _all_ok(checks) and util_ok
        rows.append({"alloc": a, "metrics": m, "feasible": feasible, "score": _score(m, ref_wait, ref_cost, st),
                     "util_cap_ok": util_ok})
    feasible_rows = [r for r in rows if r["feasible"]]
    if not feasible_rows:
        raise OptimizationInfeasible(
            "No evaluated allocation satisfies every constraint "
            "(including max_counter_utilization); relax a constraint or allow new counters")

    best = min(feasible_rows, key=lambda r: (r["score"], len(r["alloc"].keys), r["metrics"]["cost_per_hour"]))
    cur_row = next(r for r in rows if r["alloc"] == current)
    cur_score = cur_row["score"]
    change = best["alloc"] != current and (
        (not cur_row["feasible"]) or best["score"] <= cur_score * (1.0 - st.min_improvement))
    chosen = best if change else (cur_row if cur_row["feasible"] else best)
    prop_alloc, prop_m = chosen["alloc"], chosen["metrics"]

    final_checks = validate_allocation(prop_alloc, pool, c)
    if not _all_ok(final_checks) or (c.max_counter_utilization is not None
                                     and prop_m["max_counter_utilization"] > c.max_counter_utilization):
        raise OptimizationInfeasible("Internal validation failed: proposed allocation violates a constraint")

    wait_diff = paired_difference(cur_m["waits_per_rep"], prop_m["waits_per_rep"])
    cw, pw = cur_m["avg_waiting_time_min"], prop_m["avg_waiting_time_min"]
    improvement = {
        "avg_waiting_time_min": {"current": cw, "proposed": pw, "absolute_reduction": cw - pw,
                                 "percent_reduction": (cw - pw) / cw * 100 if cw > 0 else None,
                                 "paired_difference": wait_diff},
        "p95_waiting_time_min": {"current": cur_m["p95_waiting_time_min"], "proposed": prop_m["p95_waiting_time_min"],
                                 "absolute_reduction": cur_m["p95_waiting_time_min"] - prop_m["p95_waiting_time_min"]},
        "utilization_imbalance": {"current": cur_m["utilization_imbalance"], "proposed": prop_m["utilization_imbalance"],
                                  "absolute_reduction": cur_m["utilization_imbalance"] - prop_m["utilization_imbalance"]},
        "cost_per_hour": {"current": cur_m["cost_per_hour"], "proposed": prop_m["cost_per_hour"],
                          "change": prop_m["cost_per_hour"] - cur_m["cost_per_hour"]},
        "throughput_per_min": {"current": cur_m["throughput_per_min"], "proposed": prop_m["throughput_per_min"]},
        "objective_score": {"current": cur_score, "proposed": chosen["score"]},
        "is_improvement": bool(change),
    }

    cur_keys = set(current.keys)
    proposed_desc = _describe(prop_alloc, pool, cur_keys)
    current_desc = _describe(current, pool, cur_keys)
    for ch in current_desc["counters"]:
        ch["action"] = "keep"
    to_activate = [x for x in proposed_desc["counters"] if x["action"] == "activate"]
    to_add = [x for x in proposed_desc["counters"] if x["action"] == "add_new"]
    requirements = {
        "active_counters": len(prop_alloc.keys), "counters_to_activate": to_activate,
        "counters_to_deactivate": proposed_desc["counters_to_deactivate"], "new_counters_required": len(to_add),
        "new_counters": to_add, "assignment_policy_change": None if prop_alloc.policy == current.policy else {
            "from": current.policy, "to": prop_alloc.policy},
        "cost_per_hour": proposed_desc["cost_per_hour"],
        "cost_change_per_hour": proposed_desc["cost_per_hour"] - current_desc["cost_per_hour"],
        "constraint_checks": final_checks, "within_constraints": True,
        "max_counter_utilization_limit": c.max_counter_utilization,
        "max_counter_utilization_simulated": prop_m["max_counter_utilization"],
    }

    explanation = _explain(change, current, prop_alloc, pool, cur_m, prop_m, improvement, wait_diff, c, cur_ok,
                           arrival_rate)
    candidate_table = sorted(
        [{"counters": [pool[k].name for k in r["alloc"].keys], "counter_keys": list(r["alloc"].keys),
          "assignment_policy": r["alloc"].policy, "is_current": r["alloc"] == current,
          "is_proposed": r["alloc"] == prop_alloc, "feasible": r["feasible"], "score": r["score"],
          "avg_waiting_time_min": r["metrics"]["avg_waiting_time_min"],
          "p95_waiting_time_min": r["metrics"]["p95_waiting_time_min"],
          "utilization_imbalance": r["metrics"]["utilization_imbalance"],
          "avg_utilization": r["metrics"]["avg_utilization"], "cost_per_hour": r["metrics"]["cost_per_hour"],
          "demand_to_capacity_ratio": r["metrics"]["demand_to_capacity_ratio"]} for r in rows],
        key=lambda x: x["score"])
    return {
        "current_allocation": current_desc, "proposed_allocation": proposed_desc,
        "current_metrics": _public_metrics(cur_m), "proposed_metrics": _public_metrics(prop_m),
        "estimated_improvement": improvement, "resource_requirements": requirements, "explanation": explanation,
        "details": {
            "arrival_rate_per_min": arrival_rate, "constraints": c.as_dict(), "settings": st.as_dict(),
            "current_allocation_within_constraints": cur_ok, "candidates_evaluated": len(rows),
            "candidates": candidate_table,
            "search_space": ("For each feasible count k, the k fastest available counters, each with the "
                             f"policies {list(POLICIES if c.allow_policy_change else (POLICY_CURRENT,))}, plus the "
                             "current counters. Not an exhaustive search over all counter subsets."),
            "optimality": "Best among the evaluated candidates only. Global optimality is NOT claimed or proven.",
            "assumptions": [
                f"Poisson arrivals at {arrival_rate:.3f} customers/min; {st.service_distribution} service times "
                "with each counter's configured rate.",
                f"Each candidate is simulated for {st.duration_min:g} min from an empty queue, "
                f"{st.replications} replications, identical random seeds across candidates.",
                f"The current policy is assumed to be '{POLICY_CURRENT}' (serve-next uses the lowest-id idle counter).",
                "Paused counters are assumed to be resumable; closed counters are never used.",
                "No customer abandonment is modelled.",
            ],
        },
    }


def _public_metrics(m: dict[str, Any]) -> dict[str, Any]:
    keys = ["avg_waiting_time_min", "avg_waiting_time_min_std_error", "p95_waiting_time_min", "avg_queue_length",
            "throughput_per_min", "customers_remaining_at_end", "avg_utilization", "counter_utilization",
            "utilization_imbalance", "max_counter_utilization", "cost_per_hour", "demand_to_capacity_ratio", "stable",
            "waits_per_rep"]
    return {k: m[k] for k in keys}


def _explain(change: bool, current: Allocation, prop: Allocation, pool: dict[str, CounterSpec], cm: dict, pm: dict,
             imp: dict, wd: dict, c: Constraints, cur_ok: bool, lam: float) -> str:
    cur_names = ", ".join(pool[k].name for k in current.keys)
    parts = [f"Current: {len(current.keys)} counter(s) ({cur_names}) with '{current.policy}' assignment, demand "
             f"{cm['demand_to_capacity_ratio']:.0%} of capacity, simulated average wait {cm['avg_waiting_time_min']:.2f} min, "
             f"utilisation spread {cm['utilization_imbalance']:.0%}."]
    if not cur_ok:
        parts.append("The current allocation violates at least one of the supplied constraints.")
    if not change:
        parts.append("No evaluated alternative improved the objective by at least the required margin, so the "
                     "current allocation is kept. This is the best of the evaluated candidates, not a proof of optimality.")
        return " ".join(parts)
    names = ", ".join(pool[k].name for k in prop.keys)
    parts.append(f"Proposed: {len(prop.keys)} counter(s) ({names}) with '{prop.policy}' assignment, simulated average "
                 f"wait {pm['avg_waiting_time_min']:.2f} min, utilisation spread {pm['utilization_imbalance']:.0%}, cost "
                 f"{pm['cost_per_hour']:.2f}/h (was {cm['cost_per_hour']:.2f}/h).")
    pct = imp["avg_waiting_time_min"]["percent_reduction"]
    if pct is not None:
        sig = wd.get("significant")
        ci = wd.get("ci95")
        parts.append(
            f"Estimated average-wait reduction: {pct:.1f}%"
            + (f" (paired 95% CI for the difference {ci[0]:.2f} to {ci[1]:.2f} min over {wd['replications']} runs; "
               f"{'statistically distinguishable from zero' if sig else 'NOT statistically distinguishable from zero'})."
               if ci else "."))
    parts.append("Chosen as the lowest-scoring feasible candidate (wait, utilisation imbalance and cost). "
                 "Only the evaluated candidates were searched; global optimality is not claimed.")
    return " ".join(parts)
