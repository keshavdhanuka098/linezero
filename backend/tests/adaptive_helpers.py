"""Helpers that load a known-truth history into the test database as a REAL (non-synthetic) or synthetic queue."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.models import (
    CounterStatus, EntryStatus, Queue, QueueEntry, ServiceCounter, ServiceRecord, QueueStatus,
)
from tests.frames import simulate_entries


def shift_to_now(entries: pd.DataFrame, lag_min: float = 1.0) -> pd.DataFrame:
    """Shift every timestamp so the history ends `lag_min` minutes before the wall clock (a live, current queue)."""
    df = entries.copy()
    last = max(df[c].max() for c in ("arrival", "start", "end") if df[c].notna().any())
    delta = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=lag_min) - last
    for c in ("arrival", "start", "end", "left"):
        df[c] = df[c] + delta
    return df


def load_history(db, entries: pd.DataFrame, speeds=(1.0, 1.0, 1.0), nominal_rate=0.25, synthetic=False,
                 name="History", pad_waiting: int = 0) -> int:
    """Insert `entries` (from tests.frames.simulate_entries) as one queue; returns the queue id.

    Counter service_rate is `nominal_rate` x speed, i.e. the CONFIGURED rate (which tests may set wrong on purpose).
    """
    q = Queue(name=name, status=QueueStatus.ACTIVE.value, is_synthetic=synthetic, last_token=len(entries))
    db.add(q)
    db.flush()
    counters = []
    for i, sp in enumerate(speeds):
        c = ServiceCounter(queue_id=q.id, name=f"Counter {i + 1}", service_rate=nominal_rate * sp,
                           status=CounterStatus.ACTIVE.value, is_synthetic=synthetic)
        db.add(c)
        counters.append(c)
    db.flush()
    id_by_first = {float(i + 1): counters[i].id for i in range(len(counters))}
    for tok, row in enumerate(entries.itertuples(index=False), start=1):
        cid = id_by_first.get(row.counter_id) if not pd.isna(row.counter_id) else None
        status = row.status
        e = QueueEntry(
            queue_id=q.id, counter_id=cid, token_number=tok, status=EntryStatus(status).value,
            arrival_time=row.arrival.round('us').to_pydatetime(),
            service_start_time=None if pd.isna(row.start) else row.start.round('us').to_pydatetime(),
            service_end_time=None if pd.isna(row.end) else row.end.round('us').to_pydatetime(), is_synthetic=synthetic)
        db.add(e)
        db.flush()
        if status == "completed":
            db.add(ServiceRecord(queue_id=q.id, counter_id=cid, entry_id=e.id,
                                 waiting_time=(row.start - row.arrival).total_seconds(),
                                 service_time=(row.end - row.start).total_seconds(),
                                 completed_at=row.end.round('us').to_pydatetime(), is_synthetic=synthetic))
    db.commit()
    return q.id


def history(n=800, lam=0.5, mean_service=4.0, speeds=(1.0, 1.0, 1.0), seed=3, **kw):
    df, _ = simulate_entries(lam=lam, mean_service_min=mean_service, speeds=speeds, n=n, seed=seed, **kw)
    return df


def add_waiting(db, queue_id: int, n: int, minutes_ago: float = 5.0) -> None:
    """Put `n` customers in the live waiting line (status 'waiting')."""
    from datetime import datetime, timedelta, timezone

    from app.models import Queue

    q = db.get(Queue, queue_id)
    now = datetime.now(timezone.utc)
    for k in range(n):
        q.last_token += 1
        db.add(QueueEntry(queue_id=queue_id, token_number=q.last_token, status=EntryStatus.WAITING.value,
                          arrival_time=now - timedelta(minutes=minutes_ago - k * 0.1), is_synthetic=q.is_synthetic))
    db.commit()


def pause_counters(db, queue_id: int, how_many: int) -> list[int]:
    """Set the last `how_many` counters to paused (reserve). Returns their ids."""
    from sqlalchemy import select

    cs = db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == queue_id).order_by(ServiceCounter.id)).all()
    chosen = cs[-how_many:]
    for c in chosen:
        c.status = CounterStatus.PAUSED.value
    db.commit()
    return [c.id for c in chosen]
