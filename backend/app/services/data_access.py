"""Loads queue history from the database into the DataFrames the engines use."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EventType, Queue, QueueEntry, QueueEvent, ServiceCounter, ServiceRecord

ENTRY_COLS = ["entry_id", "queue_id", "status", "arrival", "start", "end", "left", "counter_id", "is_synthetic"]
REC_COLS = ["queue_id", "completed_at", "waiting_time", "service_time", "counter_id", "is_synthetic"]


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass
class Frames:
    entries: pd.DataFrame
    records: pd.DataFrame
    counters: list[dict]
    contains_synthetic: bool


def load_frames(
    db: Session, queue_id: int | None = None, counter_id: int | None = None,
    start: datetime | None = None, end: datetime | None = None,
) -> Frames:
    start, end = as_utc(start), as_utc(end)
    q = select(QueueEntry)
    if queue_id is not None:
        q = q.where(QueueEntry.queue_id == queue_id)
    if counter_id is not None:
        q = q.where(QueueEntry.counter_id == counter_id)
    if end is not None:
        q = q.where(QueueEntry.arrival_time <= end)
    entries = db.scalars(q.order_by(QueueEntry.arrival_time)).all()

    left: dict[int, datetime] = {}
    if any(e.status in ("abandoned", "removed") for e in entries):
        eq = select(QueueEvent).where(QueueEvent.event_type.in_(
            [EventType.ENTRY_ABANDONED.value, EventType.ENTRY_REMOVED.value]))
        if queue_id is not None:
            eq = eq.where(QueueEvent.queue_id == queue_id)
        for ev in db.scalars(eq).all():
            eid = (ev.event_metadata or {}).get("entry_id")
            if eid is not None:
                left[int(eid)] = ev.timestamp
    rows = [
        dict(entry_id=e.id, queue_id=e.queue_id, status=e.status, arrival=e.arrival_time, start=e.service_start_time,
             end=e.service_end_time, left=left.get(e.id), counter_id=e.counter_id, is_synthetic=e.is_synthetic)
        for e in entries
    ]
    edf = pd.DataFrame(rows, columns=ENTRY_COLS)
    for c in ("arrival", "start", "end", "left"):
        edf[c] = pd.to_datetime(edf[c], utc=True)
    edf["counter_id"] = pd.to_numeric(edf["counter_id"])
    if start is not None and len(edf):
        latest = edf[["arrival", "start", "end", "left"]].max(axis=1)
        edf = edf[latest >= pd.Timestamp(start)].reset_index(drop=True)

    rq = select(ServiceRecord)
    if queue_id is not None:
        rq = rq.where(ServiceRecord.queue_id == queue_id)
    if counter_id is not None:
        rq = rq.where(ServiceRecord.counter_id == counter_id)
    if start is not None:
        rq = rq.where(ServiceRecord.completed_at >= start)
    if end is not None:
        rq = rq.where(ServiceRecord.completed_at <= end)
    recs = db.scalars(rq.order_by(ServiceRecord.completed_at)).all()
    rdf = pd.DataFrame(
        [dict(queue_id=r.queue_id, completed_at=r.completed_at, waiting_time=r.waiting_time,
              service_time=r.service_time, counter_id=r.counter_id, is_synthetic=r.is_synthetic) for r in recs],
        columns=REC_COLS)
    rdf["completed_at"] = pd.to_datetime(rdf["completed_at"], utc=True)
    rdf["counter_id"] = pd.to_numeric(rdf["counter_id"])

    cq = select(ServiceCounter).order_by(ServiceCounter.id)
    if queue_id is not None:
        cq = cq.where(ServiceCounter.queue_id == queue_id)
    if counter_id is not None:
        cq = cq.where(ServiceCounter.id == counter_id)
    counters = [dict(id=c.id, queue_id=c.queue_id, name=c.name, status=c.status, service_rate=c.service_rate,
                     current_load=c.current_load) for c in db.scalars(cq).all()]
    synthetic = bool(len(edf) and edf["is_synthetic"].any()) or bool(len(rdf) and rdf["is_synthetic"].any())
    return Frames(edf, rdf, counters, synthetic)


def last_activity(h: pd.DataFrame) -> datetime | None:
    if h.empty:
        return None
    m = h[["arrival", "start", "end", "left"]].max().max()
    return None if pd.isna(m) else m.to_pydatetime()
