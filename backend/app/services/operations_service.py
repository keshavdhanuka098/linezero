"""Operations loop: one view of where the closed loop stands, and one call that advances its automatic stages.

    observe -> calibrate -> detect risk -> propose interventions -> operator approval -> outcome -> recalibrate

`cycle` runs ONLY the automatic stages (recalibrate if the validation gate allows it, scan risks, simulate
interventions for the worst risk). It never approves, applies or changes anything in a real queue; the human stages
stay with operators.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from app.core.errors import NotFoundError
from app.core.jsonutil import json_safe
from app.engines.operations_intelligence import loop_status, provenance
from app.models import InterventionHistory, InterventionStatus, Queue, RiskEvent, RiskStatus
from app.schemas.adaptive import CalibrationRunRequest, CycleRequest, InterventionEvaluateRequest, RiskScanRequest
from app.services.calibration_service import CalibrationService
from app.services.intervention_service import InterventionService
from app.services.risk_service import RiskService
from sqlalchemy.orm import Session

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


class OperationsService:
    def __init__(self, db: Session):
        self.db = db

    def _queue(self, queue_id: int) -> Queue:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def _count(self, queue_id: int, status: str) -> int:
        return self.db.scalar(select(func.count()).select_from(InterventionHistory).where(
            InterventionHistory.queue_id == queue_id, InterventionHistory.status == status)) or 0

    def overview(self, queue_id: int) -> dict[str, Any]:
        queue = self._queue(queue_id)
        cal = CalibrationService(self.db).status(queue_id)
        open_risks = self.db.scalar(select(func.count()).select_from(RiskEvent).where(
            RiskEvent.queue_id == queue_id, RiskEvent.status == RiskStatus.OPEN.value)) or 0
        learning = InterventionService(self.db).learning(queue_id)
        active = cal["active"]
        stages = loop_status(
            n_served=cal["observations"]["served"], active_version=active["version"] if active else None,
            drift_detected=cal["drift"].get("drift_detected"), open_risks=open_risks,
            proposals_pending=self._count(queue_id, InterventionStatus.PROPOSED.value),
            approved_waiting_apply=self._count(queue_id, InterventionStatus.APPROVED.value),
            applied_waiting_outcome=self._count(queue_id, InterventionStatus.APPLIED.value),
            outcomes_recorded=self._count(queue_id, InterventionStatus.EVALUATED.value))
        return json_safe({
            "queue": cal["queue"], "provenance": provenance(queue.is_synthetic), "stages": stages,
            "model": cal["model"], "calibration": {k: cal[k] for k in ("observations", "versions", "rejected_candidates", "drift")},
            "open_risks": open_risks, "learning": {"counts": learning["summary"]["counts"], "advice": learning["advice"]},
            "automation": ("LineZero detects, simulates and recommends. Operators approve and carry out every change; "
                           "LineZero never executes an intervention."),
        })

    def cycle(self, queue_id: int, req: CycleRequest) -> dict[str, Any]:
        queue = self._queue(queue_id)
        steps: list[dict[str, Any]] = []
        if req.recalibrate:
            res = CalibrationService(self.db).run(queue_id, CalibrationRunRequest())
            steps.append({"step": "calibrate", "decision": res["decision"], "reasons": res.get("reasons"),
                          "version": (res.get("record") or {}).get("version")})
        scan = RiskService(self.db).scan(queue_id, RiskScanRequest(seed=req.seed, forecast_replications=max(5, req.replications)))
        events = scan["persisted_events"]
        steps.append({"step": "detect_risk", "overall_severity": scan["overall_severity"], "events": len(events),
                      "resolved": len(scan["resolved_event_ids"])})
        threshold = SEVERITY_ORDER[req.min_risk_severity]
        worst = max((e for e in events if SEVERITY_ORDER.get(e["severity"], 0) >= threshold),
                    key=lambda e: (SEVERITY_ORDER[e["severity"]], e["score"]), default=None)
        proposals = None
        if req.evaluate_interventions and worst is not None:
            try:
                proposals = InterventionService(self.db).evaluate(queue_id, InterventionEvaluateRequest(
                    replications=req.replications, seed=req.seed, risk_event_id=worst["id"]))
                steps.append({"step": "propose_interventions", "risk_event_id": worst["id"],
                              "recommended_key": proposals["recommended_key"], "evaluation_id": proposals["evaluation_id"],
                              "candidates": len(proposals["candidates"])})
            except Exception as exc:  # e.g. no active counters: report, do not fail the whole cycle
                steps.append({"step": "propose_interventions", "skipped": True, "reason": str(exc)})
        elif req.evaluate_interventions:
            steps.append({"step": "propose_interventions", "skipped": True,
                          "reason": f"No risk at or above {req.min_risk_severity}."})
        return json_safe({
            "queue_id": queue_id, "provenance": provenance(queue.is_synthetic), "steps": steps,
            "pending_operator_actions": ["Review and approve or reject the proposals."] if proposals else [],
            "executed": False,
            "note": "Automatic stages only. Nothing was approved, applied or changed in the queue.",
            "overview": self.overview(queue_id),
        })
