"""Intervention service: runs the intervention engine on the live queue state and manages the human approval workflow.

Workflow (every transition records who and when; LineZero never changes a real queue itself):

    proposed --approve--> approved --applied--> applied --outcome--> evaluated
        \\--reject--> rejected        \\--reject--> rejected

  * `proposed`  a simulation result only;
  * `approved`  an operator accepted the proposal (still nothing has happened);
  * `applied`   the operator CONFIRMS they carried the change out in the real world (`executed_by_linezero` stays false);
  * `evaluated` an outcome has been recorded (see the outcome methods).
Only one candidate per evaluation can be approved/applied.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import intervention_engine as ie
from app.engines import outcome_engine as oe
from app.engines.operations_intelligence import dt_to_epoch, provenance
from app.models import InterventionHistory, InterventionStatus, OutcomeVerification, Queue, RiskEvent, utcnow
from app.services.data_access import as_utc
from app.schemas.adaptive import AppliedRequest, DecisionRequest, InterventionEvaluateRequest, OutcomeRequest
from app.services.bottleneck_service import resolve_as_of
from app.services.calibration_service import CalibrationService
from app.services.twin_service import TwinService

IN_FORCE = (InterventionStatus.APPROVED.value, InterventionStatus.APPLIED.value, InterventionStatus.EVALUATED.value)


class InterventionService:
    def __init__(self, db: Session):
        self.db = db
        self.cal = CalibrationService(db)

    # ------------------------------------------------------------------ state for the engine
    def twin_state(self, queue_id: int, use_calibration: bool) -> tuple[dict[str, Any], dict[str, Any], Queue]:
        live = TwinService(self.db).live(queue_id)
        m = live["metrics"]
        active_cal = self.cal.active_parameters(queue_id) if use_calibration else None
        pooled = per = None
        if active_cal:
            pooled = active_cal["parameters"].get("service_rate_per_min")
            per = active_cal["parameters"].get("counter_service_rates") or {}
        counters, rate_src = [], "nominal_configuration"
        for c in live["counters"]:
            rate = c["service_rate_per_min"]
            if active_cal:
                rate = float((per or {}).get(str(c["id"]), pooled if pooled is not None else rate))
                rate_src = f"calibration_v{active_cal['version']}"
            counters.append({"index": c["index"], "name": c["name"], "rate_per_min": rate, "active": c["active"],
                             "busy": c["busy"]})
        lam, lam_src = m["arrival_rate_per_min"], m["arrival_rate_source"]
        if (not lam) and active_cal and active_cal["parameters"].get("arrival_rate_per_min"):
            lam, lam_src = active_cal["parameters"]["arrival_rate_per_min"], f"calibration_v{active_cal['version']}"
        state = {"queue_length": m["queue_length"], "arrival_rate_per_min": lam, "arrival_rate_source": lam_src,
                 "counters": counters}
        inputs = {"arrival_rate_source": lam_src, "service_rate_source": rate_src,
                  "calibration_version": active_cal["version"] if active_cal else None}
        queue = self.db.get(Queue, queue_id)
        return state, inputs, queue

    # ------------------------------------------------------------------ evaluate
    def evaluate(self, queue_id: int, req: InterventionEvaluateRequest) -> dict[str, Any]:
        if self.db.get(Queue, queue_id) is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        risk = None
        if req.risk_event_id is not None:
            risk = self.db.get(RiskEvent, req.risk_event_id)
            if risk is None or risk.queue_id != queue_id:
                raise NotFoundError(f"Risk event {req.risk_event_id} not found for queue {queue_id}", "risk_event_not_found")
        state, inputs, queue = self.twin_state(queue_id, req.use_calibration)
        if not any(c["active"] for c in state["counters"]):
            raise ConflictError("The queue has no active counters, so interventions cannot be simulated from its current state",
                                "no_active_counters")
        try:
            result = ie.evaluate(state, req.horizon_min, req.replications, req.seed, req.cost_model.model_dump())
        except ValueError as exc:
            raise UnprocessableError(str(exc), "invalid_intervention_request")
        synthetic = bool(queue.is_synthetic)
        evaluation_id = str(uuid.uuid4())
        rows: list[InterventionHistory] = []
        if req.persist:
            now = utcnow()
            try:
                for c in result["candidates"]:
                    if not c["feasible"]:
                        continue
                    row = InterventionHistory(
                        queue_id=queue_id, evaluation_id=evaluation_id, risk_event_id=risk.id if risk else None,
                        created_at=now, intervention_type=c["type"], candidate_key=c["key"], label=c["label"],
                        description=c["description"], parameters=json_safe(c["parameters"]),
                        assumptions=c["assumptions"], rank=c["rank"], is_recommended=c["is_recommended"],
                        baseline=json_safe(result["baseline"]),
                        expected=json_safe({k: c[k] for k in (
                            "score", "score_delta", "score_paired", "significant", "net_value", "extra_cost",
                            "wait_reduction_min", "p95_wait_reduction_min", "throughput_change_per_min",
                            "served_change", "utilization_change", "summary")}),
                        explanation=result["explanation"] if c["is_recommended"] else None,
                        confidence=c["confidence"]["value"],
                        simulation_meta=json_safe({**result["reproducibility"], "horizon_min": req.horizon_min,
                                                   "cost_model": result["cost_model"], "inputs": inputs,
                                                   "engine_version": result["engine_version"]}),
                        status=InterventionStatus.PROPOSED.value, executed_by_linezero=False,
                        calibration_version=inputs["calibration_version"], is_synthetic=synthetic)
                    self.db.add(row)
                    rows.append(row)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            for r in rows:
                self.db.refresh(r)
        by_key = {r.candidate_key: r for r in rows}
        for c in result["candidates"]:
            c["record_id"] = by_key[c["key"]].id if c["key"] in by_key else None
        result.update(queue_id=queue_id, evaluation_id=evaluation_id if req.persist else None, persisted=req.persist,
                      provenance=provenance(synthetic), inputs=inputs, risk_event_id=req.risk_event_id,
                      data_kind={"baseline_and_candidates": "simulated", "starting_state": "observed",
                                 "explanation": "deterministic_template"})
        return json_safe(result)

    # ------------------------------------------------------------------ records
    @staticmethod
    def row_dict(r: InterventionHistory, detail: bool = True) -> dict[str, Any]:
        out = {
            "id": r.id, "queue_id": r.queue_id, "evaluation_id": r.evaluation_id, "risk_event_id": r.risk_event_id,
            "created_at": r.created_at, "intervention_type": r.intervention_type, "candidate_key": r.candidate_key,
            "label": r.label, "description": r.description, "rank": r.rank, "is_recommended": r.is_recommended,
            "status": r.status, "confidence": r.confidence, "is_synthetic": r.is_synthetic,
            "decided_by": r.decided_by, "decided_at": r.decided_at, "decision_note": r.decision_note,
            "applied_by": r.applied_by, "applied_at": r.applied_at, "apply_note": r.apply_note,
            "executed_by_linezero": r.executed_by_linezero, "outcome_verification": r.outcome_verification,
            "outcome_recorded_at": r.outcome_recorded_at, "calibration_eligible": r.calibration_eligible,
            "calibration_version": r.calibration_version,
            "expected": r.expected, "outcome": r.outcome,
            "result_kind": "simulated_expectation" if r.outcome is None else r.outcome_verification,
        }
        if detail:
            out.update({"parameters": r.parameters, "assumptions": r.assumptions, "baseline": r.baseline,
                        "explanation": r.explanation, "simulation_meta": r.simulation_meta})
        return out

    def _get(self, intervention_id: int) -> InterventionHistory:
        r = self.db.get(InterventionHistory, intervention_id)
        if r is None:
            raise NotFoundError(f"Intervention {intervention_id} not found", "intervention_not_found")
        return r

    def get(self, intervention_id: int) -> dict[str, Any]:
        r = self._get(intervention_id)
        q = self.db.get(Queue, r.queue_id)
        return json_safe({"intervention": self.row_dict(r), "provenance": provenance(q.is_synthetic)})

    def history(self, queue_id: int, status: str | None, limit: int) -> dict[str, Any]:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        stmt = select(InterventionHistory).where(InterventionHistory.queue_id == queue_id)
        if status:
            stmt = stmt.where(InterventionHistory.status == status)
        rows = self.db.scalars(stmt.order_by(InterventionHistory.created_at.desc(), InterventionHistory.rank)
                               .limit(limit)).all()
        return json_safe({"queue_id": queue_id, "provenance": provenance(q.is_synthetic),
                          "interventions": [self.row_dict(r, detail=False) for r in rows]})

    # ------------------------------------------------------------------ approval workflow
    def _move(self, r: InterventionHistory, new: str) -> None:
        if not ie.can_transition(r.status, new):
            raise ConflictError(f"An intervention that is '{r.status}' cannot become '{new}'", "invalid_transition")

    def _guard_single_in_force(self, r: InterventionHistory) -> None:
        other = self.db.scalars(select(InterventionHistory).where(
            InterventionHistory.evaluation_id == r.evaluation_id, InterventionHistory.id != r.id,
            InterventionHistory.status.in_(IN_FORCE))).first()
        if other is not None:
            raise ConflictError(f"Candidate #{other.id} of the same evaluation is already {other.status}; only one "
                                "candidate per evaluation can be taken forward", "another_candidate_in_force")

    def approve(self, intervention_id: int, req: DecisionRequest) -> dict[str, Any]:
        r = self._get(intervention_id)
        self._move(r, InterventionStatus.APPROVED.value)
        self._guard_single_in_force(r)
        r.status, r.decided_by, r.decided_at, r.decision_note = (InterventionStatus.APPROVED.value, req.operator,
                                                                 utcnow(), req.note)
        self.db.commit()
        return self._wrap(r, "Approved. LineZero has not changed anything: carry the change out yourself, then confirm it.")

    def reject(self, intervention_id: int, req: DecisionRequest) -> dict[str, Any]:
        r = self._get(intervention_id)
        self._move(r, InterventionStatus.REJECTED.value)
        r.status, r.decided_by, r.decided_at, r.decision_note = (InterventionStatus.REJECTED.value, req.operator,
                                                                 utcnow(), req.note)
        self.db.commit()
        return self._wrap(r, "Rejected.")

    def mark_applied(self, intervention_id: int, req: AppliedRequest) -> dict[str, Any]:
        r = self._get(intervention_id)
        self._move(r, InterventionStatus.APPLIED.value)
        now = utcnow()
        at = as_utc(req.applied_at) if req.applied_at else now
        if at > now + timedelta(minutes=1):
            raise UnprocessableError("applied_at cannot be in the future", "applied_in_future")
        if r.decided_at is not None and at < as_utc(r.decided_at) - timedelta(seconds=1):
            raise UnprocessableError("applied_at cannot be earlier than the approval", "applied_before_approval")
        r.status, r.applied_by, r.applied_at, r.apply_note = InterventionStatus.APPLIED.value, req.operator, at, req.note
        r.executed_by_linezero = False  # an operator did it; LineZero never does
        self.db.commit()
        return self._wrap(r, "Recorded as applied by the operator. Record the outcome once enough customers have been served.")

    def _wrap(self, r: InterventionHistory, message: str) -> dict[str, Any]:
        q = self.db.get(Queue, r.queue_id)
        return json_safe({"intervention": self.row_dict(r), "message": message, "provenance": provenance(q.is_synthetic)})

    # ------------------------------------------------------------------ outcomes
    def record_outcome(self, intervention_id: int, req: OutcomeRequest) -> dict[str, Any]:
        """Evaluate an APPLIED intervention. 'observe' measures the queue database around `applied_at`; 'manual'
        stores operator-reported figures. Nothing is recorded unless the measurement is possible (409 otherwise)."""
        r = self._get(intervention_id)
        self._move(r, InterventionStatus.EVALUATED.value)
        q = self.db.get(Queue, r.queue_id)
        expected = ((r.expected or {}).get("wait_reduction_min") or {}).get("mean")
        if req.mode == "manual":
            if req.observed is None:
                raise UnprocessableError("observed figures are required when mode is 'manual'", "observed_required")
            base_wait = ((r.baseline or {}).get("summary") or {}).get("avg_waiting_time")
            result = oe.manual_outcome(req.observed.model_dump(), base_wait, expected)
        else:
            queue, h, _counters, _fr = self.cal.observations(r.queue_id)
            as_of, basis = resolve_as_of(queue, h, req.window_minutes, None)
            others = [dt_to_epoch(o.applied_at) for o in self.db.scalars(select(InterventionHistory).where(
                InterventionHistory.queue_id == r.queue_id, InterventionHistory.id != r.id,
                InterventionHistory.applied_at.is_not(None))).all()]
            result = oe.observe(h, dt_to_epoch(r.applied_at), req.window_minutes, dt_to_epoch(as_of), expected, others)
            result["as_of_basis"] = basis
            if result["status"] != "ok":
                code = "outcome_window_not_elapsed" if result["status"] == "window_not_elapsed" else "outcome_insufficient_data"
                raise ConflictError(result["reason"], code)
            result["window_minutes"] = req.window_minutes
        verification = oe.verification_label(req.mode, bool(q.is_synthetic))
        eligible = (verification == OutcomeVerification.VERIFIED_REAL.value and bool(result.get("clean_for_calibration")))
        result.update(recorded_by=req.operator, note=req.note, verification=verification,
                      calibration_eligible=eligible, executed_by_linezero=False)
        r.outcome, r.outcome_verification, r.outcome_recorded_at = json_safe(result), verification, utcnow()
        r.calibration_eligible, r.status = eligible, InterventionStatus.EVALUATED.value
        self.db.commit()
        msg = {"verified_real_observation": "Outcome measured from real queue observations.",
               "synthetic_observation": "Outcome measured on SYNTHETIC demo data: not a real-world result.",
               "operator_reported": "Outcome recorded as reported by the operator; not measured by LineZero."}[verification]
        return self._wrap(r, msg)

    def learning(self, queue_id: int) -> dict[str, Any]:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        rows = self.db.scalars(select(InterventionHistory).where(
            InterventionHistory.queue_id == queue_id).order_by(InterventionHistory.id)).all()
        done = [x for x in rows if x.status == InterventionStatus.EVALUATED.value and x.outcome]
        data = [{"verification": x.outcome_verification, "type": x.intervention_type,
                 "expected": ((x.expected or {}).get("wait_reduction_min") or {}).get("mean"),
                 "observed": x.outcome.get("observed_wait_reduction_min")} for x in done]
        summary = oe.learning_summary(data)
        v = summary["verified_real"]
        advice = {"recalibrate": False, "reason": "Not enough verified real outcomes to judge the model (need at least 5)."}
        if v["n"] >= 5:
            if abs(v["mean_error_min"]) >= 0.5:
                advice = {"recalibrate": True, "reason": (
                    f"Across {v['n']} verified real outcomes the twin's expected wait reduction was off by "
                    f"{v['mean_error_min']:+.2f} min on average (observed minus expected). Re-run calibration and review "
                    "the active version. LineZero does not change the model on its own.")}
            else:
                advice = {"recalibrate": False, "reason": f"Mean error {v['mean_error_min']:+.2f} min across {v['n']} verified "
                                                           "real outcomes is within 0.5 min."}
        counts = {s.value: sum(1 for x in rows if x.status == s.value) for s in InterventionStatus}
        return json_safe({
            "queue_id": queue_id, "provenance": provenance(q.is_synthetic), "status_counts": counts,
            "summary": summary, "advice": advice,
            "calibration_eligible_outcomes": sum(1 for x in done if x.calibration_eligible),
            "outcomes": [self.row_dict(x, detail=False) for x in reversed(done)][:50],
            "note": "Only verified real observations enter the error statistics. Synthetic and operator-reported "
                    "outcomes are counted separately and are never presented as real-world verification.",
        })
