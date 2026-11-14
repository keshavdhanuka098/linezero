from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import analytics_engine as ae
from app.models import Queue, ServiceCounter
from app.services.data_access import as_utc, load_frames


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def _data(self, queue_id, counter_id, start, end, tz_offset) -> ae.AnalyticsData:
        if queue_id is not None and self.db.get(Queue, queue_id) is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        if counter_id is not None:
            c = self.db.get(ServiceCounter, counter_id)
            if c is None:
                raise NotFoundError(f"Counter {counter_id} not found", "counter_not_found")
            if queue_id is not None and c.queue_id != queue_id:
                raise UnprocessableError(f"Counter {counter_id} does not belong to queue {queue_id}", "counter_wrong_queue")
        if start and end and as_utc(end) < as_utc(start):
            raise UnprocessableError("end_date must not be earlier than start_date", "invalid_date_range")
        fr = load_frames(self.db, queue_id, counter_id, start, end)
        return ae.AnalyticsData(
            fr.entries, fr.records, fr.counters,
            start=pd.Timestamp(as_utc(start)) if start else None, end=pd.Timestamp(as_utc(end)) if end else None,
            tz_offset_minutes=tz_offset, filters={"queue_id": queue_id, "counter_id": counter_id},
            contains_synthetic=fr.contains_synthetic)

    def run(self, kind: str, queue_id=None, counter_id=None, start: datetime | None = None, end: datetime | None = None,
            granularity: str = "hour", tz_offset_minutes: int = 0, compare: bool = False) -> dict[str, Any]:
        d = self._data(queue_id, counter_id, start, end, tz_offset_minutes)
        try:
            if kind == "overview":
                prev = None
                if compare:
                    s, e = ae.resolve_range(d)
                    if s is not None and e is not None and e > s:
                        length = e - s
                        prev = self._data(queue_id, counter_id, (s - length).to_pydatetime(), s.to_pydatetime(),
                                          tz_offset_minutes)
                        prev.start, prev.end = s - length, s
                return json_safe(ae.overview(d, prev, compare))
            if kind == "arrivals":
                return json_safe(ae.arrivals(d, granularity))
            if kind == "waiting-times":
                return json_safe(ae.waiting_times(d, granularity))
            if kind == "utilization":
                return json_safe(ae.utilization(d, granularity))
            if kind == "peak-hours":
                return json_safe(ae.peak_hours(d))
        except ae.AnalyticsError as exc:
            raise UnprocessableError(str(exc), "invalid_analytics_request")
        raise UnprocessableError(f"Unknown analytics type {kind}", "unknown_analytics")
