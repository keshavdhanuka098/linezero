"""SLA & Customer Experience Intelligence service.

Reads the queue database (never writes queue state), reuses:
  * the prediction engine (`baseline_wait`: completions needed and service capacity),
  * the active calibration's service rates (via RiskService.effective_counters),
  * the intervention engine / simulation (via InterventionService.evaluate) for recommendations.
It writes only SLA policies (operator-defined targets) and, when asked, intervention proposals.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import prediction_engine as pe
from app.engines import sla_engine as se
from app.engines.operations_intelligence import dt_to_epoch, provenance
from app.models import DEFAULT_CLASS, EntryStatus, Queue, QueueEntry, SlaPolicy, utcnow
from app.schemas.adaptive import InterventionEvaluateRequest
from app.schemas.sla import EntryClassRequest, SlaPolicyIn, SlaRecommendRequest, class_ok
from app.services.bottleneck_service import resolve_as_of
from app.services.calibration_service import CalibrationService
from app.services.intervention_service import InterventionService
from app.services.risk_service import RiskService

MAX_BUCKETS = 500
NOT_CONFIGURED = ("No SLA target is configured for this queue. LineZero does not assume one: define the maximum "
                  "acceptable waiting time in SLA Intelligence > Configuration.")


class SlaService:
    def __init__(self, db: Session):
        self.db = db
        self.cal = CalibrationService(db)

    # ------------------------------------------------------------------ policies
    def _queue(self, queue_id: int) -> Queue:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def _policies(self, queue_id: int) -> dict[str, SlaPolicy]:
        rows = self.db.scalars(select(SlaPolicy).where(SlaPolicy.queue_id == queue_id).order_by(SlaPolicy.id)).all()
        return {r.service_class: r for r in rows}

    @staticmethod
    def policy_dict(p: SlaPolicy) -> dict[str, Any]:
        return {"id": p.id, "queue_id": p.queue_id, "service_class": p.service_class, "label": p.label,
                "max_wait_min": p.max_wait_min, "at_risk_probability": p.at_risk_probability,
                "critical_probability": p.critical_probability, "updated_by": p.updated_by,
                "created_at": p.created_at, "updated_at": p.updated_at}

    def list_policies(self, queue_id: int) -> dict[str, Any]:
        q = self._queue(queue_id)
        pol = self._policies(queue_id)
        return json_safe({"queue": {"id": q.id, "name": q.name, "is_synthetic": q.is_synthetic},
                          "configured": DEFAULT_CLASS in pol, "default_class": DEFAULT_CLASS,
                          "policies": [self.policy_dict(p) for p in pol.values()],
                          "note": "Customers without a service class use the 'standard' policy. A service class changes "
                                  "the SLA target only, not the order in which customers are served."})

    def upsert_policy(self, queue_id: int, service_class: str, req: SlaPolicyIn) -> dict[str, Any]:
        self._queue(queue_id)
        if not class_ok(service_class):
            raise UnprocessableError("service class must be lowercase letters, digits, '-' or '_' (max 40)",
                                     "invalid_service_class")
        pol = self._policies(queue_id)
        if service_class != DEFAULT_CLASS and DEFAULT_CLASS not in pol:
            raise UnprocessableError("Define the 'standard' policy first: customers without a class use it",
                                     "standard_class_required")
        row = pol.get(service_class)
        created = row is None
        if row is None:
            row = SlaPolicy(queue_id=queue_id, service_class=service_class)
            self.db.add(row)
        row.max_wait_min, row.label, row.updated_by = req.max_wait_min, req.label, req.operator
        row.at_risk_probability, row.critical_probability = req.at_risk_probability, req.critical_probability
        row.updated_at = utcnow()
        self.db.commit()
        self.db.refresh(row)
        return json_safe({"policy": self.policy_dict(row), "created": created})

    def delete_policy(self, queue_id: int, service_class: str, operator: str) -> dict[str, Any]:
        self._queue(queue_id)
        if not operator.strip():
            raise UnprocessableError("operator is required", "operator_required")
        pol = self._policies(queue_id)
        row = pol.get(service_class)
        if row is None:
            raise NotFoundError(f"No '{service_class}' SLA policy on queue {queue_id}", "policy_not_found")
        if service_class == DEFAULT_CLASS and len(pol) > 1:
            raise ConflictError("Delete the other service classes before the 'standard' one", "standard_class_required")
        self.db.delete(row)
        self.db.commit()
        return {"deleted": service_class, "queue_id": queue_id}

    def set_entry_class(self, queue_id: int, entry_id: int, req: EntryClassRequest) -> dict[str, Any]:
        self._queue(queue_id)
        e = self.db.get(QueueEntry, entry_id)
        if e is None or e.queue_id != queue_id:
            raise NotFoundError(f"Entry {entry_id} not found in queue {queue_id}", "entry_not_found")
        if req.service_class not in self._policies(queue_id):
            raise UnprocessableError(f"Queue {queue_id} has no SLA policy for service class '{req.service_class}'",
                                     "unknown_service_class")
        if e.status != EntryStatus.WAITING.value:
            raise ConflictError("Only waiting customers can change service class; history is not rewritten",
                                "entry_not_waiting")
        e.service_class = req.service_class
        self.db.commit()
        return {"entry_id": e.id, "token_number": e.token_number, "service_class": e.service_class}

    @staticmethod
    def resolve(pol: dict[str, SlaPolicy], service_class: str | None) -> tuple[SlaPolicy | None, bool]:
        """(policy, used_fallback). Unknown or empty class falls back to 'standard'; None if even that is missing."""
        cls = service_class or DEFAULT_CLASS
        if cls in pol:
            return pol[cls], False
        return pol.get(DEFAULT_CLASS), cls != DEFAULT_CLASS

    # ------------------------------------------------------------------ live customer monitoring
    def _capacity(self, queue_id: int, counters: list[dict[str, Any]]) -> dict[str, Any]:
        eff, source = RiskService(self.db).effective_counters(queue_id, counters)
        active = [c for c in eff if c["status"] == "active"]
        busy = sum(1 for c in active if c["current_load"] > 0)
        return {"active": len(active), "busy": busy, "rates": [float(c["service_rate"]) for c in active],
                "rate_source": source}

    def monitor(self, queue_id: int) -> dict[str, Any]:
        queue = self._queue(queue_id)
        pol = self._policies(queue_id)
        base = {"queue": {"id": queue.id, "name": queue.name, "is_synthetic": queue.is_synthetic}}
        if DEFAULT_CLASS not in pol:
            return json_safe({**base, "configured": False, "reason": NOT_CONFIGURED, "customers": [],
                              "provenance": provenance(queue.is_synthetic)})
        queue, h, counters, fr = self.cal.observations(queue_id)
        anchor, basis = resolve_as_of(queue, h, 30.0, None)
        cap = self._capacity(queue_id, counters)
        waiting = self.db.scalars(select(QueueEntry).where(
            QueueEntry.queue_id == queue_id, QueueEntry.status == EntryStatus.WAITING.value)
            .order_by(QueueEntry.token_number)).all()
        serving = self.db.scalars(select(QueueEntry).where(
            QueueEntry.queue_id == queue_id, QueueEntry.status == EntryStatus.SERVING.value)).all()
        idle = max(cap["active"] - cap["busy"], 0)
        rows: list[dict[str, Any]] = []
        for pos, e in enumerate(waiting, start=1):
            policy, fallback = self.resolve(pol, e.service_class)
            assert policy is not None  # 'standard' exists (checked above)
            elapsed = max((anchor - e.arrival_time.astimezone(anchor.tzinfo)).total_seconds(), 0.0)
            target_s = policy.max_wait_min * 60.0
            ahead = pos - 1
            rate = None
            k = None
            if cap["active"]:
                try:
                    bw = pe.baseline_wait(pe.BaselineInputs(
                        queue_length=ahead, active_counters=cap["active"], busy_counters=cap["busy"],
                        counter_rates_per_min=cap["rates"]))
                    rate, k = bw["service_capacity_per_min"], bw["completions_needed"]
                except (pe.PredictionUnavailable, pe.PredictionInputError):
                    rate = None
            a = se.assess_customer(ahead, idle, rate, elapsed, target_s, policy.at_risk_probability,
                                   policy.critical_probability)
            if k is not None:
                a["completions_needed"] = k
            rows.append({
                "entry_id": e.id, "token": e.token_number, "queue_id": queue_id, "position": pos,
                "service_class": e.service_class or DEFAULT_CLASS, "class_fallback": fallback,
                "current_wait_min": elapsed / 60.0,
                "predicted_total_wait_min": None if a["predicted_total_wait_s"] is None else a["predicted_total_wait_s"] / 60.0,
                "sla_target_min": policy.max_wait_min, "remaining_sla_min": a["remaining_sla_s"] / 60.0,
                "breach_probability": a["breach_probability"], "status": a["status"],
                "completions_needed": a["completions_needed"], "basis": a["basis"],
                "highlight": a["status"] != "safe",
            })
        rows.sort(key=lambda r: (-se.STATUS_RANK[r["status"]], -r["breach_probability"], r["position"]))
        counts = {s: sum(1 for r in rows if r["status"] == s) for s in se.STATUSES}
        pred = se.predicted_compliance([r["breach_probability"] for r in rows])
        return json_safe({
            **base, "configured": True, "as_of": anchor, "as_of_basis": basis,
            "provenance": provenance(queue.is_synthetic or fr.contains_synthetic),
            "customers": rows, "counts": counts, "waiting": len(rows), "serving": len(serving),
            "predicted_compliance": {**pred, "kind": "predicted",
                                     "definition": "Expected share of the customers waiting now who will be served within "
                                                   "their own SLA target (mean of 1 - breach probability)."},
            "capacity": {"active_counters": cap["active"], "busy_counters": cap["busy"], "idle_counters": idle,
                         "service_capacity_per_min": float(sum(cap["rates"])), "service_rate_source": cap["rate_source"]},
            "assumptions": se.ASSUMPTIONS,
            "data_kinds": {"current_wait": "observed", "breach_probability": "predicted",
                           "predicted_total_wait": "predicted", "sla_target": "operator_configured"},
        })

    # ------------------------------------------------------------------ performance and compliance
    def performance(self, queue_id: int, window_minutes: float = 60.0, lookback_hours: float = 24.0,
                    bucket_minutes: float = 60.0) -> dict[str, Any]:
        if not 5 <= window_minutes <= 1440:
            raise UnprocessableError("window_minutes must be between 5 and 1440", "invalid_window")
        if not 1 <= lookback_hours <= 720:
            raise UnprocessableError("lookback_hours must be between 1 and 720", "invalid_lookback")
        if window_minutes > lookback_hours * 60:
            raise UnprocessableError("window_minutes cannot be longer than the lookback", "invalid_window")
        if not 5 <= bucket_minutes <= 1440:
            raise UnprocessableError("bucket_minutes must be between 5 and 1440", "invalid_bucket")
        if lookback_hours * 60 / bucket_minutes > MAX_BUCKETS:
            raise UnprocessableError(f"lookback / bucket would produce more than {MAX_BUCKETS} buckets", "invalid_bucket")
        queue = self._queue(queue_id)
        pol = self._policies(queue_id)
        base = {"queue": {"id": queue.id, "name": queue.name, "is_synthetic": queue.is_synthetic}}
        if DEFAULT_CLASS not in pol:
            return json_safe({**base, "configured": False, "reason": NOT_CONFIGURED,
                              "provenance": provenance(queue.is_synthetic)})
        queue, h, _counters, fr = self.cal.observations(queue_id)
        anchor, basis = resolve_as_of(queue, h, 30.0, None)
        anchor_s = dt_to_epoch(anchor)
        start_s = anchor_s - lookback_hours * 3600.0
        cur_start_s = anchor_s - window_minutes * 60.0
        classes = dict(self.db.execute(select(QueueEntry.id, QueueEntry.service_class)
                                       .where(QueueEntry.queue_id == queue_id)).all())

        arr, st = pe.to_seconds(h["arrival"]), pe.to_seconds(h["start"])
        done = (h["status"].to_numpy() == "completed") & np.isfinite(arr) & np.isfinite(st) & (st >= start_s) & (st <= anchor_s)
        sub = h[done]
        waits = ((st[done] - arr[done]) / 60.0)
        ends = st[done]
        targets = np.array([(self.resolve(pol, classes.get(i) if classes.get(i) is not None else None)[0].max_wait_min)
                            for i in sub["entry_id"]], dtype=float)
        cls_of = [classes.get(i) or DEFAULT_CLASS for i in sub["entry_id"]]
        cur = ends >= cur_start_s
        overall = se.compliance(waits, targets)
        current = se.compliance(waits[cur], targets[cur])
        historical = se.compliance(waits[~cur], targets[~cur])
        in_window = (arr >= start_s) & (arr <= anchor_s)
        abandoned = int(((h["status"].to_numpy() == "abandoned") & in_window).sum())
        per_class = []
        for cls in sorted(set(cls_of) | set(pol)):
            m = np.array([c == cls for c in cls_of], dtype=bool) if len(cls_of) else np.array([], dtype=bool)
            c = se.compliance(waits[m], targets[m])
            p = pol.get(cls)
            per_class.append({"service_class": cls, "label": p.label if p else None,
                              "target_min": p.max_wait_min if p else None, **c})
        mon = self.monitor(queue_id)
        prov = provenance(queue.is_synthetic or fr.contains_synthetic)
        score_def = ("Completed customers who waited no longer than their SLA target, as a percentage of completed "
                     "customers. Abandoned customers are not included; they are reported separately.")
        return json_safe({
            **base, "configured": True, "provenance": prov, "as_of": anchor, "as_of_basis": basis,
            "window": {"current_minutes": window_minutes, "lookback_hours": lookback_hours, "bucket_minutes": bucket_minutes},
            "scores": {
                "current": {**current, "kind": "observed", "label": f"Current compliance (last {window_minutes:g} min)"},
                "historical": {**historical, "kind": "observed",
                               "label": f"Historical compliance (earlier in the last {lookback_hours:g} h)"},
                "overall": {**overall, "kind": "observed", "label": f"Overall compliance (last {lookback_hours:g} h)"},
                "predicted": mon["predicted_compliance"] | {"label": "Predicted compliance of customers waiting now"}
                if mon.get("configured") else None,
                "definition": score_def,
            },
            "summary": {
                "served": overall["n"], "met_sla": overall["met"], "breached_sla": overall["breached"],
                "abandoned": abandoned, "waiting_now": mon.get("waiting"), "serving_now": mon.get("serving"),
                "avg_wait_min": overall["avg_wait_min"], "p95_wait_min": overall["p95_wait_min"],
                "avg_target_min": overall["avg_target_min"], "avg_over_target_min": overall["avg_over_target_min"],
            },
            "per_class": per_class,
            "trend": se.trend(ends, waits, targets, start_s, anchor_s, bucket_minutes),
            "targets_note": "Compliance is evaluated against the targets configured now; targets changed later apply "
                            "to earlier customers as well.",
            "data_kinds": {"scores_current_historical_overall": "observed", "predicted": "predicted",
                           "targets": "operator_configured"},
        })

    # ------------------------------------------------------------------ recommendations
    def recommendations(self, queue_id: int, req: SlaRecommendRequest) -> dict[str, Any]:
        mon = self.monitor(queue_id)
        if not mon["configured"]:
            raise ConflictError(NOT_CONFIGURED, "sla_not_configured")
        base = {"queue": mon["queue"], "provenance": mon["provenance"], "simulation_only": True, "executed": False}
        risky = [r for r in mon["customers"] if r["status"] in ("at_risk", "critical")]
        breached = [r for r in mon["customers"] if r["status"] == "breached"]
        if not risky:
            msg = ("No waiting customer is currently at risk of breaching their SLA."
                   if not breached else
                   f"{len(breached)} waiting customer(s) have already exceeded their SLA; no other customer is "
                   "currently at risk, so no intervention is proposed.")
            return json_safe({**base, "needed": False, "message": msg, "affected": mon["counts"]})

        cap = mon["capacity"]
        worst = max(risky, key=lambda r: (r["breach_probability"], r["position"]))
        reasons = [
            f"{len(risky)} waiting customer(s) are at risk or critical "
            f"({mon['counts']['critical']} critical, {mon['counts']['at_risk']} at risk"
            f"{', ' + str(len(breached)) + ' already breached' if breached else ''}).",
            f"{mon['waiting']} customers are waiting with {cap['active_counters']} active counter(s) "
            f"({cap['busy_counters']} busy) serving about {cap['service_capacity_per_min']:.2f} customers/min "
            f"({cap['service_rate_source'].replace('_', ' ')}).",
            f"Token {worst['token']} (position {worst['position']}) has waited {worst['current_wait_min']:.1f} min of "
            f"{worst['sla_target_min']:g} min and needs {worst['completions_needed']} more completion(s); expected total "
            f"wait {worst['predicted_total_wait_min']:.1f} min, breach probability {worst['breach_probability']:.0%}."
            if worst["predicted_total_wait_min"] is not None else
            f"Token {worst['token']} cannot be served: there is no active counter.",
        ]
        gap: dict[str, Any] | None = None
        if cap["active_counters"] and cap["service_capacity_per_min"] > 0:
            need = se.required_rate_per_min(worst["completions_needed"], worst["remaining_sla_min"] * 60.0, 0.5)
            if need is not None:
                extra = max(need - cap["service_capacity_per_min"], 0.0)
                per_counter = cap["service_capacity_per_min"] / cap["active_counters"]
                gap = {"for_token": worst["token"], "required_capacity_per_min": need,
                       "current_capacity_per_min": cap["service_capacity_per_min"], "extra_capacity_per_min": extra,
                       "approx_extra_counters": int(math.ceil(extra / per_counter - 1e-9)) if per_counter > 0 else None,
                       "method": "capacity at which this customer's breach probability falls to 50% (exact Erlang tail)"}
                if extra > 0:
                    reasons.append(f"To bring token {worst['token']} to a 50% breach probability the queue needs about "
                                   f"{need:.2f} customers/min, i.e. {extra:.2f}/min more than now.")
        target = min(r["sla_target_min"] for r in risky)
        evaluation: dict[str, Any] | None = None
        eval_error: str | None = None
        try:
            evaluation = InterventionService(self.db).evaluate(queue_id, InterventionEvaluateRequest(
                horizon_min=req.horizon_min, replications=req.replications, seed=req.seed, cost_model=req.cost_model,
                use_calibration=req.use_calibration, persist=req.persist))
        except ConflictError as exc:
            eval_error = str(exc)
            reasons.append("No counter is active, so a simulation cannot start from the current state.")
        cands = []
        baseline = None
        if evaluation:
            baseline = {"avg_wait_min": evaluation["baseline"]["summary"]["avg_waiting_time"],
                        "p95_wait_min": evaluation["baseline"]["summary"]["p95_waiting_time"],
                        "kind": "simulated"}
            for c in [c for c in evaluation["candidates"] if c["feasible"] and c["rank"]][:3]:
                p95 = c["summary"]["p95_waiting_time"]
                cands.append({
                    "key": c["key"], "label": c["label"], "type": c["type"], "rank": c["rank"],
                    "is_recommended": c["is_recommended"], "description": c["description"],
                    "expected_wait_reduction_min": c["wait_reduction_min"], "avg_wait_after_min": c["summary"]["avg_waiting_time"],
                    "p95_wait_after_min": p95, "p95_within_target": p95 <= target,
                    "extra_cost": c["extra_cost"], "net_value": c["net_value"], "significant": c["significant"],
                    "assumptions": c["assumptions"], "record_id": c["record_id"], "kind": "simulated"})
        return json_safe({
            **base, "needed": True, "affected": mon["counts"], "target_min": target, "worst_customer": worst,
            "reasons": reasons, "capacity_gap": gap, "baseline": baseline, "candidates": cands,
            "recommended_key": evaluation["recommended_key"] if evaluation else None,
            "explanation": evaluation["explanation"] if evaluation else eval_error,
            "evaluation_id": evaluation["evaluation_id"] if evaluation else None, "persisted": req.persist,
            "reproducibility": evaluation["reproducibility"] if evaluation else None,
            "disclaimer": ("Expected reductions come from the existing intervention simulation and are not measured "
                           "results. People approve and carry out every change in Autonomous Interventions; LineZero "
                           "never changes a counter or queue."),
            "note": f"'p95 within target' compares the simulated 95th-percentile wait with the tightest at-risk target "
                    f"({target:g} min).",
        })

    # ------------------------------------------------------------------ all queues
    def summary(self) -> dict[str, Any]:
        out = []
        for q in self.db.scalars(select(Queue).order_by(Queue.id)).all():
            pol = self._policies(q.id)
            row: dict[str, Any] = {"queue_id": q.id, "name": q.name, "is_synthetic": q.is_synthetic,
                                   "configured": DEFAULT_CLASS in pol,
                                   "standard_target_min": pol[DEFAULT_CLASS].max_wait_min if DEFAULT_CLASS in pol else None}
            if row["configured"]:
                perf = self.performance(q.id)
                mon = self.monitor(q.id)
                row.update(current_score=perf["scores"]["current"]["score"], current_n=perf["scores"]["current"]["n"],
                           overall_score=perf["scores"]["overall"]["score"], counts=mon["counts"],
                           predicted_score=mon["predicted_compliance"]["score"])
            out.append(row)
        return json_safe({"queues": out})


__all__ = ["SlaService"]
