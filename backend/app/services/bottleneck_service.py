"""Runs the bottleneck rules against stored data and persists every finding."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.jsonutil import json_safe
from app.engines import bottleneck_engine as be
from app.engines.prediction_engine import prepare_history, to_seconds
from app.models import BottleneckDetection, Queue, utcnow
from app.services.data_access import as_utc, last_activity, load_frames


def _dt(sec: float | None) -> datetime | None:
    return None if sec is None else datetime.fromtimestamp(sec, tz=timezone.utc)


def resolve_as_of(queue: Queue, h: pd.DataFrame, window_minutes: float, as_of: datetime | None) -> tuple[datetime, str]:
    """Real queues are analysed up to now. Generated (synthetic) queues, whose data ends when it was generated,
    are anchored at their latest activity once it is older than the window, so they stay analysable."""
    if as_of is not None:
        return as_utc(as_of), "requested"
    now = utcnow()
    last = last_activity(h)
    if queue.is_synthetic and last is not None and (now - last).total_seconds() > window_minutes * 60:
        return last, "latest_activity_of_synthetic_queue"
    return now, "now"


class BottleneckService:
    def __init__(self, db: Session):
        self.db = db

    def analyze(self, queue_id: int | None, window_minutes: float = 240.0, lookback_minutes: float = 1440.0,
                as_of: datetime | None = None) -> dict[str, Any]:
        if queue_id is not None:
            q = self.db.get(Queue, queue_id)
            if q is None:
                raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
            queues = [q]
        else:
            queues = list(self.db.scalars(select(Queue).where(Queue.status != "closed").order_by(Queue.id)).all())
        th = be.Thresholds()
        results, created = [], []
        try:
            for q in queues:
                fr = load_frames(self.db, queue_id=q.id)
                h, _ = prepare_history(fr.entries)
                when, basis = resolve_as_of(q, h, window_minutes, as_of)
                counters = [be.CounterInfo(c["id"], c["name"], c["service_rate"], c["status"]) for c in fr.counters]
                res = be.analyze(q.id, h, counters, when.timestamp(), window_minutes, lookback_minutes, th)
                rows = []
                for f in res.findings:
                    row = BottleneckDetection(
                        queue_id=q.id, counter_id=f.counter_id, bottleneck_type=f.bottleneck_type, severity=f.severity,
                        supporting_metrics=json_safe(f.supporting_metrics), explanation=f.explanation,
                        operational_impact=f.operational_impact, recommendation=f.recommendation,
                        window_start=_dt(f.window_start_s), window_end=_dt(f.window_end_s), created_at=utcnow(),
                        is_synthetic=q.is_synthetic)
                    self.db.add(row)
                    rows.append(row)
                created.append((q, when, basis, res, rows))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for q, when, basis, res, rows in created:
            results.append({
                "queue_id": q.id, "queue_name": q.name, "is_synthetic": q.is_synthetic,
                "as_of": when, "as_of_basis": basis, "summary": json_safe(res.summary), "notes": res.notes,
                "detections": [self.to_dict(r) for r in rows]})
        all_det = [d for r in results for d in r["detections"]]
        return json_safe({
            "analyzed_at": utcnow(), "window_minutes": window_minutes, "lookback_minutes": lookback_minutes,
            "thresholds": th.as_dict(), "queues_analyzed": len(results), "detection_count": len(all_det),
            "detections": all_det, "by_queue": results})

    @staticmethod
    def to_dict(r: BottleneckDetection) -> dict[str, Any]:
        return json_safe({
            "detection_id": r.id, "bottleneck_type": r.bottleneck_type, "severity": r.severity,
            "queue_id": r.queue_id, "counter_id": r.counter_id, "supporting_metrics": r.supporting_metrics,
            "explanation": r.explanation, "operational_impact": r.operational_impact,
            "recommendation": r.recommendation, "detection_timestamp": r.created_at,
            "window_start": r.window_start, "window_end": r.window_end, "is_synthetic": r.is_synthetic})

    def list(self, queue_id: int | None = None, counter_id: int | None = None, severity: str | None = None,
             bottleneck_type: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        stmt = select(BottleneckDetection).order_by(BottleneckDetection.id.desc()).limit(limit).offset(offset)
        if queue_id is not None:
            stmt = stmt.where(BottleneckDetection.queue_id == queue_id)
        if counter_id is not None:
            stmt = stmt.where(BottleneckDetection.counter_id == counter_id)
        if severity:
            stmt = stmt.where(BottleneckDetection.severity == severity)
        if bottleneck_type:
            stmt = stmt.where(BottleneckDetection.bottleneck_type == bottleneck_type)
        return [self.to_dict(r) for r in self.db.scalars(stmt).all()]
