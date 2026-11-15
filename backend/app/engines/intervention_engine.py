"""Autonomous intervention engine: generate, simulate, compare and rank operational interventions.

Given the CURRENT state of a queue (customers waiting, which counters are busy, counter service rates, recent arrival
rate) the engine

  1. captures the baseline: the unchanged queue simulated over the horizon;
  2. generates candidate interventions (open reserve counters, assist/speed-up, divert traffic, change assignment, a
     combination) and drops, with a stated reason, those that are infeasible for resource reasons;
  3. simulates every candidate with the SAME random seeds as the baseline (common random numbers), so the paired
     difference isolates the effect of the intervention from simulation noise;
  4. prices each candidate (extra counter-hours, assisting staff, diverted customers) with an operator-supplied cost model;
  5. ranks the feasible candidates and explains the choice.

Score (lower is better):   score = avg_wait + 0.5 * p95_wait + 20 * abandonment_rate        (minutes-equivalent)
Net value (higher better): net_value = (baseline_score - candidate_score) - cost_weight * extra_cost
A candidate is RECOMMENDED only if it is feasible, its score improvement is statistically significant (paired 95%
interval excludes zero), and its net value is positive. Otherwise no recommendation is made and the engine says why.

Everything is simulation. This module never touches the database, and every result carries
`simulation_only = True`, `executed = False` and `requires_operator_approval = True`. Real operational changes are
made by people; LineZero only records their decision (see the intervention service).

Assumptions that are NOT measured data (returned with every result): the +15% / +30% assist speed-ups, how many staff
they need, the diversion share, and the cost figures are operator/engine inputs. Service times are exponential,
arrival rate and counter speeds are constant over the horizon, nobody abandons, no counter fails during the horizon.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from app.engines import twin_forecast as tf
from app.engines.twin_engine import ScheduledAction, TwinConfig, run_replications
from app.engines.twin_recovery import SCORE_FORMULA, score_of
from app.engines.twin_scenarios import improvement, paired_stat

ENGINE_VERSION = "1.0"
MAX_ACTIVATIONS = 3
ASSIST_LEVELS = ((1.15, 1, "reallocate_staff", "Reallocate assisting staff (+15% speed)"),
                 (1.30, 2, "adjust_service_capacity", "Adjust service capacity (+30% speed, 2 assisting staff)"))
DIVERSION_SHARES = (0.10, 0.20)
NO_NEED_WAIT_MIN = 1.0  # baseline average wait below this: nothing worth fixing
RANKING_RULE = ("feasible candidates sorted by net_value = (baseline_score - score) - cost_weight x extra_cost, "
                "highest first")

# legal status moves of an intervention record (anything else is a 409)
TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"applied", "rejected"},
    "applied": {"evaluated"},
    "rejected": set(),
    "evaluated": set(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def config_hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ candidate generation
def generate_candidates(state: dict[str, Any], cost: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (candidates, not_evaluated). Each candidate: key, type, label, description, actions, patch,
    assumptions, assist_staff, diversion_share, extra_counters."""
    counters = state["counters"]
    reserve = [i for i, c in enumerate(counters) if not c["active"]]
    cands: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    if reserve:
        for k in range(1, min(len(reserve), MAX_ACTIVATIONS) + 1):
            names = ", ".join(counters[i]["name"] for i in reserve[:k])
            cands.append({
                "key": f"activate_{k}", "type": "activate_counters", "label": f"Open {k} reserve counter{'s' if k > 1 else ''}",
                "description": f"Bring {names} online immediately.",
                "actions": [{"type": "activate_counter", "at": 0.0, "counter": i} for i in reserve[:k]], "patch": {},
                "assumptions": ["A staff member is available for each counter opened, immediately."],
                "assist_staff": 0, "diversion_share": 0.0, "extra_counters": k, "counters": [counters[i]["name"] for i in reserve[:k]],
            })
    else:
        skipped.append({"key": "activate_counters", "type": "activate_counters",
                        "reason": "No reserve (closed or paused) counter exists to open."})

    for factor, staff, typ, label in ASSIST_LEVELS:
        key = f"assist_{int(round((factor - 1) * 100))}"
        if staff > cost["max_assist_staff"]:
            skipped.append({"key": key, "type": typ,
                            "reason": f"Needs {staff} assisting staff but only {cost['max_assist_staff']} are available."})
            continue
        cands.append({
            "key": key, "type": typ, "label": label,
            "description": f"{staff} cross-trained staff assist from now, speeding every open counter by {round((factor - 1) * 100)}%.",
            "actions": [{"type": "boost_speed", "at": 0.0, "factor": factor}], "patch": {},
            "assumptions": [f"The {factor}x speed-up is an assumption, not measured data.",
                            f"Assumes {staff} assisting staff are available for the whole horizon."],
            "assist_staff": staff, "diversion_share": 0.0, "extra_counters": 0, "speed_factor": factor,
        })

    for share in DIVERSION_SHARES:
        cands.append({
            "key": f"divert_{int(round(share * 100))}", "type": "redistribute_traffic",
            "label": f"Redirect {int(round(share * 100))}% of arrivals to another channel",
            "description": f"Send {int(round(share * 100))}% of incoming customers elsewhere (another queue, online, appointment).",
            "actions": [], "patch": {"__arrival_scale": 1.0 - share},
            "assumptions": [f"Exactly {int(round(share * 100))}% of arrivals can be redirected; redirected customers leave "
                            "this queue and are not counted as served here."],
            "assist_staff": 0, "diversion_share": share, "extra_counters": 0,
        })

    other = "lowest_index"  # the baseline engine default is longest_idle; offer the alternative
    cands.append({
        "key": "assign_lowest_index", "type": "assignment_strategy",
        "label": "Change counter allocation rule to 'lowest index first'",
        "description": "All counters share one queue, so this changes which idle counter takes the next customer, "
                       "not total capacity; it mainly shows whether load balancing matters.",
        "actions": [], "patch": {"counter_assignment": other}, "assumptions": [],
        "assist_staff": 0, "diversion_share": 0.0, "extra_counters": 0,
    })

    if reserve and cost["max_assist_staff"] >= 1:
        cands.append({
            "key": "combined", "type": "combined",
            "label": "Open all reserve counters and add assisting staff (+15%)",
            "description": "Combine every reserve counter with the +15% staff assist.",
            "actions": [{"type": "activate_counter", "at": 0.0, "counter": i} for i in reserve[:MAX_ACTIVATIONS]]
                       + [{"type": "boost_speed", "at": 0.0, "factor": 1.15}], "patch": {},
            "assumptions": ["Staff for every opened counter and the assist are available immediately.",
                            "The 1.15x speed-up is an assumption, not measured data."],
            "assist_staff": 1, "diversion_share": 0.0, "extra_counters": min(len(reserve), MAX_ACTIVATIONS),
        })
    return cands, skipped


def _apply(cfg: TwinConfig, cand: dict[str, Any]) -> TwinConfig:
    patch = dict(cand["patch"])
    scale = patch.pop("__arrival_scale", None)
    update: dict[str, Any] = dict(patch)
    if scale is not None:
        update["arrival_rate"] = cfg.arrival_rate * scale
    update["actions"] = list(cfg.actions) + [ScheduledAction(**a) for a in cand["actions"]]
    return cfg.model_copy(update=update)


# ------------------------------------------------------------------ evaluation
def _scores(res: dict[str, Any]) -> list[float]:
    return [score_of(s) for s in res["per_replication"]]


def _confidence(pair: dict[str, Any] | None) -> dict[str, Any]:
    """Simulation confidence in the *direction and size* of the score change: 1 - (95% half-width / |mean change|) for a
    significant change, 0 otherwise. It measures simulation noise only - not model error or real-world validity."""
    if not pair or not pair["significant"] or pair["mean_diff"] == 0:
        return {"value": 0.0, "basis": "score change not statistically distinguishable from simulation noise"}
    v = max(0.0, min(1.0, 1.0 - pair["ci95"] / abs(pair["mean_diff"])))
    return {"value": float(v), "basis": "1 - (95% half-width / |mean score change|) across paired replications; "
                                        "simulation noise only"}


def _cost(cand: dict[str, Any], cm: dict[str, Any], horizon: float, lam: float, sim_cost_delta: float) -> dict[str, float]:
    hours = horizon / 60.0
    assist = cand["assist_staff"] * cm["assist_staff_hour_cost"] * hours
    diverted = lam * cand["diversion_share"] * horizon
    diversion = diverted * cm["diversion_cost_per_customer"]
    return {"counter_hours": float(sim_cost_delta), "assisting_staff": float(assist), "diversion": float(diversion),
            "expected_diverted_customers": float(diverted), "total": float(sim_cost_delta + assist + diversion)}


def evaluate(state: dict[str, Any], horizon_min: float, replications: int, seed: int,
             cost_model: dict[str, Any]) -> dict[str, Any]:
    """Run the full baseline-vs-candidates experiment. `state` has the same shape `twin_forecast.build_config` takes."""
    cfg, notes = tf.build_config(state, horizon_min, seed)
    cfg = cfg.model_copy(update={"cost_per_counter_hour": cost_model["counter_hour_cost"], "sample_interval": None})
    lam = cfg.arrival_rate
    baseline = run_replications(cfg, replications, seed, detail_first=False)
    base_scores = _scores(baseline)
    base_score = float(np.mean(base_scores))
    cands, not_evaluated = generate_candidates(state, cost_model)
    rows: list[dict[str, Any]] = []
    for cand in cands:
        res = run_replications(_apply(cfg, cand), replications, seed, detail_first=False)
        scores = _scores(res)
        pair = paired_stat(base_scores, scores)
        imp = improvement(baseline, res)
        cost = _cost(cand, cost_model, horizon_min, lam, res["summary"]["resource_cost"] - baseline["summary"]["resource_cost"])
        score = float(np.mean(scores))
        net = (base_score - score) - cost_model["cost_weight"] * cost["total"]
        wait_pair = imp["avg_waiting_time"]["paired"]
        feasible, why = True, None
        if cost_model["max_extra_cost"] is not None and cost["total"] > cost_model["max_extra_cost"] + 1e-9:
            feasible, why = False, (f"Extra cost {cost['total']:.2f} exceeds the budget of "
                                    f"{cost_model['max_extra_cost']:.2f}.")
        rows.append({
            "key": cand["key"], "type": cand["type"], "label": cand["label"], "description": cand["description"],
            "parameters": {"actions": cand["actions"], "patch": cand["patch"], "assist_staff": cand["assist_staff"],
                           "diversion_share": cand["diversion_share"], "extra_counters": cand["extra_counters"],
                           "counters": cand.get("counters")},
            "assumptions": cand["assumptions"], "feasible": feasible, "infeasible_reason": why,
            "score": score, "score_delta": score - base_score, "score_paired": pair,
            "significant": bool(pair and pair["significant"]), "improves": score < base_score,
            "net_value": float(net), "extra_cost": cost,
            "wait_reduction_min": {"mean": -wait_pair["mean_diff"] if wait_pair else None,
                                   "ci95": wait_pair["ci95"] if wait_pair else None,
                                   "pct": -imp["avg_waiting_time"]["pct"] if imp["avg_waiting_time"]["pct"] is not None else None},
            "p95_wait_reduction_min": -imp["p95_waiting_time"]["delta"],
            "throughput_change_per_min": imp["throughput"]["delta"],
            "served_change": imp["total_served"]["delta"],
            "utilization_change": imp["avg_utilization_available"]["delta"],
            "summary": res["summary"], "improvement": imp, "confidence": _confidence(pair),
            "rank": None, "is_recommended": False,
        })
    feasible_rows = sorted((r for r in rows if r["feasible"]), key=lambda r: -r["net_value"])
    for i, r in enumerate(feasible_rows, 1):
        r["rank"] = i
    best = next((r for r in feasible_rows if r["improves"] and r["significant"] and r["net_value"] > 0), None)
    if best is not None:
        best["is_recommended"] = True
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, -r["net_value"]))

    base_avg = baseline["summary"]["avg_waiting_time"]
    out_notes = list(notes_text(notes))
    if base_avg < NO_NEED_WAIT_MIN:
        out_notes.append(f"The baseline average wait is only {base_avg:.2f} min; the queue does not currently need an intervention.")
    if best is None:
        out_notes.append("No feasible candidate both improved the score beyond simulation noise and justified its cost.")
    seeds = [seed + r for r in range(replications)]
    out = {
        "simulation_only": True, "executed": False, "requires_operator_approval": True,
        "engine_version": ENGINE_VERSION, "horizon_min": horizon_min, "replications": replications,
        "score_formula": SCORE_FORMULA, "ranking_rule": RANKING_RULE, "cost_model": cost_model,
        "baseline": {"score": base_score, "summary": baseline["summary"],
                     "stats": {k: {"mean": v["mean"], "ci95": v["ci95"]} for k, v in baseline["stats"].items()},
                     "starting_state": {"queue_length": state["queue_length"], "arrival_rate_per_min": lam,
                                        "arrival_rate_source": state.get("arrival_rate_source"),
                                        "counters": [{"name": c["name"], "active": c["active"], "busy": c["busy"],
                                                      "service_rate_per_min": c["rate_per_min"]} for c in state["counters"]]}},
        "candidates": rows, "not_evaluated": not_evaluated,
        "recommended_key": best["key"] if best else None,
        "reproducibility": {"base_seed": seed, "seeds": seeds, "replications": replications,
                            "common_random_numbers": True,
                            "config_hash": config_hash({"v": ENGINE_VERSION, "state": state, "horizon": horizon_min,
                                                        "reps": replications, "seed": seed, "cost": cost_model})},
        "global_assumptions": [
            "Service times are exponential; arrival rate and counter speeds are constant over the horizon.",
            "No customer abandons and no counter fails during the horizon.",
            "Speed-ups, staffing needs, diversion shares and costs are assumptions or operator inputs, not measurements.",
        ],
        "notes": out_notes,
        "disclaimer": "These are simulated outcomes. LineZero has not executed any intervention; an operator must "
                      "approve and carry out any real change.",
    }
    out["explanation"] = explain(out)
    return out


def notes_text(notes: dict[str, Any]) -> list[str]:
    out = []
    if notes.get("arrival_rate_floored"):
        out.append("The arrival rate was unavailable and was floored to a tiny value; results are not informative.")
    if notes.get("queue_truncated"):
        out.append("The starting queue was truncated to the simulator's maximum.")
    return out


def explain(result: dict[str, Any]) -> str:
    """Deterministic plain-language rationale built only from the numbers in `result` (no generative model)."""
    base = result["baseline"]
    b_avg, b_p95 = base["summary"]["avg_waiting_time"], base["summary"]["p95_waiting_time"]
    head = (f"Baseline (no change): average wait {b_avg:.1f} min, P95 {b_p95:.1f} min, "
            f"{base['summary']['max_queue_length']:.0f} customers at the longest queue, over {result['horizon_min']:g} simulated minutes.")
    key = result["recommended_key"]
    if key is None:
        return head + " " + " ".join(result["notes"]) if result["notes"] else head
    best = next(c for c in result["candidates"] if c["key"] == key)
    w = best["wait_reduction_min"]
    parts = [head,
             f"Recommended: {best['label']}. It is expected to cut the average wait by {w['mean']:.1f} min "
             f"(+/-{w['ci95']:.1f}, 95% across {result['replications']} paired simulations; {w['pct']:.0f}%) and P95 by "
             f"{best['p95_wait_reduction_min']:.1f} min, at an extra cost of {best['extra_cost']['total']:.2f} units.",
             f"It ranked first on net value ({best['net_value']:.2f}) = score improvement ({-best['score_delta']:.2f}) minus "
             f"{result['cost_model']['cost_weight']:g} x cost."]
    others = [c for c in result["candidates"] if c["rank"] and c["key"] != key]
    if others:
        nxt = others[0]
        parts.append(f"Next best: {nxt['label']} (net value {nxt['net_value']:.2f}, wait reduction "
                     f"{(nxt['wait_reduction_min']['mean'] or 0):.1f} min).")
    if best["type"] == "redistribute_traffic":
        parts.append(f"Note: about {best['extra_cost']['expected_diverted_customers']:.0f} customers are redirected, so this queue "
                     "serves fewer people.")
    parts.append("This is a simulation result; nothing has been done. Operator approval is required.")
    return " ".join(parts)


__all__ = ["evaluate", "generate_candidates", "can_transition", "TRANSITIONS", "explain", "config_hash", "RANKING_RULE"]
