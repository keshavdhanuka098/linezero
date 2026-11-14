"""Grounded explanations for the Digital Twin.

Design rule: the explanation layer never produces simulation metrics. Metrics come from the simulation engines; this
module only (a) condenses them into a `facts` dict, (b) writes a deterministic explanation from those facts, and
(c) checks that optional LLM text contains no number that is absent from the facts.

Without a Gemini API key the deterministic explanation is returned, so the feature works fully offline.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.engines.twin_engine import TwinConfig

KINDS = ("congestion", "counter", "intervention", "scenarios")
_NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def _f(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def _cn(i: int) -> str:
    return f"Counter {i + 1}"


# ------------------------------------------------------------------ fact builders
def scenario_facts(cfg: TwinConfig) -> dict[str, Any]:
    closed = set(cfg.standby_counters)
    if cfg.staff_available is not None:
        closed |= set(range(cfg.staff_available, cfg.num_counters))
    peak = max([1.0] + [s.multiplier for s in (cfg.arrival_profile or [])])
    return {
        "arrival_rate_per_min": cfg.arrival_rate, "mean_service_time_min": cfg.mean_service_time,
        "num_counters": cfg.num_counters, "duration_min": cfg.duration, "peak_arrival_multiplier": peak,
        "closed_at_start": [_cn(i) for i in sorted(closed)],
        "outages": [{"counter": _cn(o.counter), "start": o.start, "end": o.end} for o in cfg.outages],
        "slowdowns": [{"counter": "all counters" if s.counter is None else _cn(s.counter), "start": s.start,
                       "end": s.end, "speed_factor": s.factor} for s in cfg.speed_changes],
        "abandonment_enabled": cfg.abandonment_enabled,
    }


def facts_from_simulation(cfg: TwinConfig, run: dict[str, Any]) -> dict[str, Any]:
    eps = run["primary"]["episodes"]["bottlenecks"] if "primary" in run else run["episodes"]["bottlenecks"]
    counters = run["counters"]
    return {
        "kind": "simulation", "scenario": scenario_facts(cfg), "summary": run["summary"],
        "bottlenecks": [{**e, "most_loaded_counter": _cn(e["most_loaded_counter"]),
                         "failed_counters": [_cn(i) for i in e["failed_counters"]],
                         "closed_counters": [_cn(i) for i in e["closed_counters"]]} for e in eps],
        "counters": [{"name": c["name"], "utilization_while_open": c["utilization_available"],
                      "served": c["served"], "closed_minutes": c["closed_time"], "failed_minutes": c["failed_time"]}
                     for c in counters],
    }


def facts_from_recommendation(cfg: TwinConfig, rec: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for r in rec["recommendations"][:4]:
        imp = r["improvement"]
        rows.append({
            "id": r["id"], "rank": r["rank"], "label": r["label"], "significant": r["significant"], "improves": r["improves"],
            "avg_wait_before": imp["avg_waiting_time"]["before"], "avg_wait_after": imp["avg_waiting_time"]["after"],
            "p95_before": imp["p95_waiting_time"]["before"], "p95_after": imp["p95_waiting_time"]["after"],
            "max_queue_before": imp["max_queue_length"]["before"], "max_queue_after": imp["max_queue_length"]["after"],
            "extra_cost": r["extra_cost"], "assumptions": r["assumptions"],
        })
    return {"kind": "recommendation", "scenario": scenario_facts(cfg), "diagnosis": {
        k: rec["diagnosis"][k] for k in ("first_congestion_at", "most_loaded_counter", "underused_counters",
                                          "closed_counters", "failed_counters", "avg_wait_min", "max_queue")},
        "recommended_id": rec["recommended_id"], "candidates": rows, "notes": rec["notes"]}


def facts_from_comparison(cmp: dict[str, Any]) -> dict[str, Any]:
    keys = ("avg_waiting_time", "p95_waiting_time", "max_queue_length", "abandoned", "resource_cost")
    return {"kind": "comparison", "baseline": cmp["labels"][0], "scenarios": [
        {"name": n, **{k: cmp["metrics"][k]["values"][i] for k in keys},
         "avg_wait_change_pct": cmp["metrics"]["avg_waiting_time"]["pct"][i],
         "avg_wait_change_significant": bool(i and cmp["metrics"]["avg_waiting_time"]["paired"][i]
                                             and cmp["metrics"]["avg_waiting_time"]["paired"][i]["significant"])}
        for i, n in enumerate(cmp["labels"])]}


# ------------------------------------------------------------ deterministic text
def _causes(sc: dict[str, Any], ep: dict[str, Any]) -> list[str]:
    out = []
    if sc["peak_arrival_multiplier"] > 1:
        out.append(f"arrivals rise to {_f(sc['peak_arrival_multiplier'], 1)}x the base rate of "
                   f"{_f(sc['arrival_rate_per_min'])} per minute")
    if ep["failed_counters"]:
        out.append(f"{', '.join(ep['failed_counters'])} out of service")
    if ep["closed_counters"]:
        out.append(f"{', '.join(ep['closed_counters'])} closed (reserve or unstaffed)")
    if sc["slowdowns"]:
        out.append("service slowed on " + ", ".join(sorted({s['counter'] for s in sc['slowdowns']})))
    if ep.get("avg_counters_available") is not None:
        out.append(f"on average {_f(ep['avg_counters_available'], 1)} of {sc['num_counters']} counters were available")
    return out


def explain_deterministic(kind: str, facts: dict[str, Any]) -> str:
    if kind == "congestion":
        s, sc = facts["summary"], facts["scenario"]
        if not facts["bottlenecks"]:
            return (f"No sustained congestion occurred. The queue peaked at {_f(s['max_queue_length'], 0)} and the "
                    f"average wait was {_f(s['avg_waiting_time'])} min (P95 {_f(s['p95_waiting_time'])} min).")
        parts = []
        for ep in facts["bottlenecks"][:2]:
            causes = _causes(sc, ep)
            parts.append(
                f"From t={_f(ep['start'], 1)} to t={_f(ep['end'], 1)} min the queue peaked at {ep['peak_queue']} "
                f"(congestion threshold {ep['threshold']}). {ep['most_loaded_counter']} was busiest at "
                f"{_f(ep['most_loaded_utilization'] * 100, 0)}% of the window. "
                + ("Contributing factors in this scenario: " + "; ".join(causes) + "." if causes else ""))
        parts.append(f"Over the whole run the average wait was {_f(s['avg_waiting_time'])} min and the maximum "
                     f"queue was {_f(s['max_queue_length'], 0)}.")
        return " ".join(parts)
    if kind == "counter":
        cs = [c for c in facts["counters"] if c["utilization_while_open"] > 0]
        if not cs:
            return "No counter served any customer in this run."
        top = max(cs, key=lambda c: c["utilization_while_open"])
        low = min(cs, key=lambda c: c["utilization_while_open"])
        spread = top["utilization_while_open"] - low["utilization_while_open"]
        if spread < 0.10:
            txt = (f"The open counters are similarly loaded (between {_f(low['utilization_while_open'] * 100, 0)}% and "
                   f"{_f(top['utilization_while_open'] * 100, 0)}% busy while open), so no single counter is "
                   "the problem; the constraint is total available capacity versus demand.")
        else:
            txt = (f"{top['name']} is the most loaded: busy {_f(top['utilization_while_open'] * 100, 0)}% of the time "
                   f"it was open, serving {_f(top['served'], 0)} customers. {low['name']} is the least loaded at "
                   f"{_f(low['utilization_while_open'] * 100, 0)}%, so work is unevenly spread.")
        down = [c for c in facts["counters"] if c["failed_minutes"] > 0]
        if down:
            txt += " Failed time: " + ", ".join(f"{c['name']} {_f(c['failed_minutes'], 1)} min" for c in down) + "."
        return txt
    if kind == "intervention":
        cands = facts["candidates"]
        if not cands:
            return "No interventions were generated for this scenario."
        best = next((c for c in cands if facts["recommended_id"] and c["id"] == facts["recommended_id"]), None)
        if best is None:
            top = cands[0]
            return ("No candidate intervention improved the outcome by more than simulation noise. The best-scoring "
                    f"option was \"{top['label']}\" (average wait {_f(top['avg_wait_before'])} to "
                    f"{_f(top['avg_wait_after'])} min), but the difference is not statistically clear.")
        return (f"The most effective intervention in simulation is \"{best['label']}\": average wait "
                f"{_f(best['avg_wait_before'])} to {_f(best['avg_wait_after'])} min, P95 {_f(best['p95_before'])} to "
                f"{_f(best['p95_after'])} min, maximum queue {_f(best['max_queue_before'], 1)} to "
                f"{_f(best['max_queue_after'], 1)}, at an extra resource cost of {_f(best['extra_cost'])}."
                .rstrip() + (" Assumptions: " + " ".join(best["assumptions"]) if best["assumptions"] else ""))
    if kind == "scenarios":
        sc = facts["scenarios"]
        base = sc[0]
        lines = [f"Baseline \"{base['name']}\": average wait {_f(base['avg_waiting_time'])} min, P95 "
                 f"{_f(base['p95_waiting_time'])} min, maximum queue {_f(base['max_queue_length'], 1)}."]
        for s in sc[1:]:
            pct = s["avg_wait_change_pct"]
            direction = "unchanged" if pct is None or pct == 0 else ("higher" if pct > 0 else "lower")
            lines.append(
                f"\"{s['name']}\": average wait {_f(s['avg_waiting_time'])} min"
                + (f" ({_f(abs(pct), 0)}% {direction} than baseline" if pct is not None else " (baseline is zero")
                + ("; difference is statistically clear)" if s["avg_wait_change_significant"]
                   else "; difference is within simulation noise)") + ".")
        return " ".join(lines)
    raise ValueError(f"Unknown explanation kind {kind!r}")


# --------------------------------------------------------------- LLM number guard
def _numbers_in(obj: Any, acc: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        acc.add(float(obj))
    elif isinstance(obj, str):
        acc.update(float(m) for m in _NUM.findall(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _numbers_in(k, acc)
            _numbers_in(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, acc)


def allowed_numbers(facts: dict[str, Any], extra_text: str = "") -> set[float]:
    acc: set[float] = set()
    _numbers_in(facts, acc)
    acc.update(float(m) for m in _NUM.findall(extra_text))
    acc.update(abs(v) for v in list(acc))
    acc.update(v * 100.0 for v in list(acc) if abs(v) <= 1.0)  # fractions quoted as percentages
    return acc


def unsupported_numbers(text: str, facts: dict[str, Any], extra_text: str = "") -> list[str]:
    allowed = allowed_numbers(facts, extra_text)
    bad = []
    for tok in _NUM.findall(text):
        v = abs(float(tok))
        if not any(abs(v - a) <= max(0.051, 0.005 * abs(a)) for a in allowed):
            bad.append(tok)
    return bad


def build_prompt(kind: str, facts: dict[str, Any], question: str | None) -> str:
    q = f"\nUser question (answer only from FACTS): {question}\n" if question else ""
    return (
        "You explain results of a queue simulation to an operations manager.\n"
        "Rules: use ONLY the numbers that appear in FACTS_JSON; do not compute, estimate or invent any other number; "
        "do not claim anything about real customers or real queues; say when a difference is not statistically clear; "
        "write 3-6 plain sentences, no lists, no markdown.\n"
        f"Task: {_TASK[kind]}\n{q}FACTS_JSON:\n{json.dumps(facts, default=str)}"
    )


_TASK = {
    "congestion": "Explain why congestion occurred and when.",
    "counter": "Say which counter is overloaded and which is underused.",
    "intervention": "Say which intervention is most effective and what it costs, including its assumptions.",
    "scenarios": "Explain how the scenarios differ from the baseline.",
}
