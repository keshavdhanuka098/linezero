"""Risk service: builds a risk context from the queue database, runs the risk engine, stores/refreshes risk events.

Event lifecycle: a persisted scan refreshes the open event for the same (category, resource) - keeping its original
`detected_at` - creates events for newly detected risks, and marks open events that are no longer detected as resolved.
Assessing without persisting changes nothing.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.jsonutil import json_safe
from app.engines import risk_engine as re_
from app.engines.operations_intelligence import dt_to_epoch, provenance
from app.models import Queue, RiskEvent, RiskStatus, utcnow
from app.schemas.adaptive import DecisionRequest, RiskScanRequest
from app.services.bottleneck_service import resolve_as_of
from app.services.calibration_service import CalibrationService
from app.services.twin_service import TwinService


class RiskService:
    def __init__(self, db: Session):
        self.db = db
        self.cal = CalibrationService(db)

    def effective_counters(self, queue_id: int, counters: list[dict[str, Any]]):
        """Counters with the service rate the twin should use: the active calibration's if one exists."""
        active = self.cal.active_parameters(queue_id)
        if active is None:
            return [dict(c) for c in counters], "nominal_configuration"
        p = active["parameters"]
        out = []
        for c in counters:
            rate = (p.get("counter_service_rates") or {}).get(str(c["id"]), p.get("service_rate_per_min"))
            out.append({**c, "service_rate": float(rate if rate is not None else c["service_rate"])})
        return out, f"calibration_v{active['version']}"

    def build_context(self, queue_id: int, req: RiskScanRequest) -> tuple[re_.RiskContext, Any, Any]:
        queue, h, counters, fr = self.cal.observations(queue_id)
        anchor, anchor_basis = resolve_as_of(queue, h, 30.0, None)
        eff, source = self.effective_counters(queue_id, counters)
        forecast = None
        try:
            forecast = TwinService(self.db).forecast(queue_id, req.forecast_replications, req.seed, None)
        except (ConflictError, NotFoundError):
            forecast = None
        ctx = re_.RiskContext(h=h, counters=eff, anchor_s=dt_to_epoch(anchor), forecast=forecast,
                              wait_sla_min=req.wait_sla_min, rate_source=source,
                              extra={"anchor_basis": anchor_basis})
        return ctx, queue, fr

    def assess(self, queue_id: int, req: RiskScanRequest) -> dict[str, Any]:
        ctx, queue, fr = self.build_context(queue_id, req)
        result = re_.assess(ctx)
        result.update(queue_id=queue_id, provenance=provenance(queue.is_synthetic or fr.contains_synthetic),
                      service_rate_source=ctx.rate_source, anchor_basis=ctx.extra["anchor_basis"],
                      forecast_used=ctx.forecast is not None, wait_sla_min=req.wait_sla_min, persisted=False,
                      persisted_events=[], resolved_event_ids=[])
        return json_safe(result)

    def scan(self, queue_id: int, req: RiskScanRequest) -> dict[str, Any]:
        ctx, queue, fr = self.build_context(queue_id, req)
        result = re_.assess(ctx)
        synthetic = bool(queue.is_synthetic or fr.contains_synthetic)
        cal = self.cal.active_record(queue_id)
        persisted: list[dict[str, Any]] = []
        resolved: list[int] = []
        if req.persist:
            now = utcnow()
            open_rows = self.db.scalars(select(RiskEvent).where(
                RiskEvent.queue_id == queue_id, RiskEvent.status == RiskStatus.OPEN.value)).all()
            index = {(r.category, r.resource_type, r.resource_id): r for r in open_rows}
            seen = set()
            try:
                for a in result["events"]:
                    key = (a["category"], a["resource_type"], a["resource_id"])
                    seen.add(key)
                    row = index.get(key)
                    fields = dict(severity=a["severity"], score=a["score"], resource_name=a["resource_name"],
                                  last_seen_at=now, time_to_impact_min=a["time_to_impact_min"],
                                  supporting_metrics=json_safe(a["supporting_metrics"]), confidence=a["confidence"],
                                  uncertainty=json_safe(a["uncertainty"]),
                                  recommended_intervention=json_safe(a["recommended_intervention"]),
                                  explanation=a["explanation"], calibration_version=cal.version if cal else None,
                                  is_synthetic=synthetic)
                    if row is None:
                        row = RiskEvent(queue_id=queue_id, category=a["category"], resource_type=a["resource_type"],
                                        resource_id=a["resource_id"], detected_at=now, **fields)
                        self.db.add(row)
                    else:
                        for k, v in fields.items():
                            setattr(row, k, v)
                    persisted.append({"row": row, "assessment": a})
                for key, row in index.items():
                    if key not in seen:
                        row.status, row.resolved_at = RiskStatus.RESOLVED.value, now
                        resolved.append(row.id)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            for p in persisted:
                self.db.refresh(p["row"])
        result.update(queue_id=queue_id, provenance=provenance(synthetic), service_rate_source=ctx.rate_source,
                      anchor_basis=ctx.extra["anchor_basis"], forecast_used=ctx.forecast is not None,
                      wait_sla_min=req.wait_sla_min, persisted=req.persist,
                      persisted_events=[self.event_dict(p["row"]) for p in persisted], resolved_event_ids=resolved)
        return json_safe(result)

    @staticmethod
    def event_dict(r: RiskEvent) -> dict[str, Any]:
        return {"id": r.id, "queue_id": r.queue_id, "category": r.category, "severity": r.severity, "score": r.score,
                "resource_type": r.resource_type, "resource_id": r.resource_id, "resource_name": r.resource_name,
                "detected_at": r.detected_at, "last_seen_at": r.last_seen_at, "time_to_impact_min": r.time_to_impact_min,
                "supporting_metrics": r.supporting_metrics, "confidence": r.confidence, "uncertainty": r.uncertainty,
                "recommended_intervention": r.recommended_intervention, "explanation": r.explanation,
                "status": r.status, "resolved_at": r.resolved_at, "calibration_version": r.calibration_version,
                "is_synthetic": r.is_synthetic}

    def events(self, queue_id: int, status: str, limit: int) -> dict[str, Any]:
        queue = self.db.get(Queue, queue_id)
        if queue is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        stmt = select(RiskEvent).where(RiskEvent.queue_id == queue_id)
        if status != "all":
            stmt = stmt.where(RiskEvent.status == status)
        rows = self.db.scalars(stmt.order_by(RiskEvent.detected_at.desc(), RiskEvent.id.desc()).limit(limit)).all()
        return json_safe({"queue_id": queue_id, "provenance": provenance(queue.is_synthetic),
                          "events": [self.event_dict(r) for r in rows]})

    def resolve(self, event_id: int, req: DecisionRequest) -> dict[str, Any]:
        row = self.db.get(RiskEvent, event_id)
        if row is None:
            raise NotFoundError(f"Risk event {event_id} not found", "risk_event_not_found")
        if row.status == RiskStatus.RESOLVED.value:
            raise ConflictError("Risk event is already resolved", "already_resolved")
        row.status, row.resolved_at = RiskStatus.RESOLVED.value, utcnow()
        row.explanation = f"{row.explanation} [Resolved manually by {req.operator}" + (f": {req.note}" if req.note else "") + "]"
        self.db.commit()
        return json_safe(self.event_dict(row))

