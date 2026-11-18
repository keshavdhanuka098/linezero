"""Queue + counter business logic. All state changes run in a single DB transaction and write events."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.models import (
    CounterStatus, EntryStatus, EventType, Queue, QueueEntry, QueueEvent, QueueStatus,
    ServiceCounter, ServiceRecord, SlaPolicy, utcnow,
)
from app.schemas.counter import CounterCreate, CounterOut, CounterUpdate
from app.schemas.entry import EntryOut, EntryPosition
from app.schemas.queue import (
    CompleteResult, QueueCreate, QueueDetail, QueueOut, QueueState, QueueUpdate, ServeResult,
)
from app.schemas.entry import ServiceRecordOut

WAITING = EntryStatus.WAITING.value
SERVING = EntryStatus.SERVING.value


class QueueService:
    def __init__(self, db: Session):
        self.db = db

    @contextmanager
    def _tx(self) -> Iterator[None]:
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _queue(self, queue_id: int) -> Queue:
        queue = self.db.get(Queue, queue_id)
        if queue is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return queue

    def _counter(self, counter_id: int) -> ServiceCounter:
        counter = self.db.get(ServiceCounter, counter_id)
        if counter is None:
            raise NotFoundError(f"Counter {counter_id} not found", "counter_not_found")
        return counter

    def _entry(self, queue_id: int, entry_id: int) -> QueueEntry:
        entry = self.db.get(QueueEntry, entry_id)
        if entry is None or entry.queue_id != queue_id:
            raise NotFoundError(f"Entry {entry_id} not found in queue {queue_id}", "entry_not_found")
        return entry

    def _log(
        self, queue_id: int, event_type: EventType, counter_id: int | None = None,
        metadata: dict[str, Any] | None = None, timestamp: datetime | None = None,
    ) -> None:
        self.db.add(
            QueueEvent(
                queue_id=queue_id, counter_id=counter_id, event_type=event_type.value,
                timestamp=timestamp or utcnow(), event_metadata=metadata or {},
            )
        )

    def _positions(self, queue_id: int) -> dict[int, int]:
        ids = self.db.scalars(
            select(QueueEntry.id)
            .where(QueueEntry.queue_id == queue_id, QueueEntry.status == WAITING)
            .order_by(QueueEntry.token_number)
        ).all()
        return {entry_id: i for i, entry_id in enumerate(ids, start=1)}

    @staticmethod
    def _entry_out(entry: QueueEntry, positions: dict[int, int] | None = None, now: datetime | None = None) -> EntryOut:
        waiting_time = None
        if entry.service_start_time is not None:
            waiting_time = (entry.service_start_time - entry.arrival_time).total_seconds()
        elif entry.status == WAITING:
            waiting_time = ((now or utcnow()) - entry.arrival_time).total_seconds()
        out = EntryOut.model_validate(entry)
        out.position = (positions or {}).get(entry.id) if entry.status == WAITING else None
        out.waiting_time_seconds = waiting_time
        return out

    def _queue_counts(self, queue_ids: list[int]) -> dict[int, dict[str, int]]:
        counts = {qid: {s.value: 0 for s in EntryStatus} | {"counters": 0} for qid in queue_ids}
        if not queue_ids:
            return counts
        rows = self.db.execute(
            select(QueueEntry.queue_id, QueueEntry.status, func.count())
            .where(QueueEntry.queue_id.in_(queue_ids))
            .group_by(QueueEntry.queue_id, QueueEntry.status)
        ).all()
        for qid, status, n in rows:
            counts[qid][status] = n
        rows = self.db.execute(
            select(ServiceCounter.queue_id, func.count())
            .where(ServiceCounter.queue_id.in_(queue_ids))
            .group_by(ServiceCounter.queue_id)
        ).all()
        for qid, n in rows:
            counts[qid]["counters"] = n
        return counts

    def _queue_out(self, queue: Queue, counts: dict[str, int]) -> QueueOut:
        out = QueueOut.model_validate(queue)
        out.waiting_count = counts[WAITING]
        out.serving_count = counts[SERVING]
        out.counter_count = counts["counters"]
        return out

    def create_queue(self, data: QueueCreate) -> QueueOut:
        with self._tx():
            queue = Queue(name=data.name, description=data.description, status=data.status.value)
            self.db.add(queue)
            self.db.flush()
            self._log(queue.id, EventType.QUEUE_CREATED, metadata={"name": queue.name, "status": queue.status})
        return self._queue_out(queue, self._queue_counts([queue.id])[queue.id])

    def list_queues(
        self, status: QueueStatus | None = None, synthetic: bool | None = None, limit: int = 100, offset: int = 0
    ) -> list[QueueOut]:
        stmt = select(Queue).order_by(Queue.id).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(Queue.status == status.value)
        if synthetic is not None:
            stmt = stmt.where(Queue.is_synthetic.is_(synthetic))
        queues = self.db.scalars(stmt).all()
        counts = self._queue_counts([q.id for q in queues])
        return [self._queue_out(q, counts[q.id]) for q in queues]

    def get_queue(self, queue_id: int) -> QueueDetail:
        queue = self._queue(queue_id)
        c = self._queue_counts([queue_id])[queue_id]
        base = self._queue_out(queue, c)
        counters = self.db.scalars(
            select(ServiceCounter).where(ServiceCounter.queue_id == queue_id).order_by(ServiceCounter.id)
        ).all()
        return QueueDetail(
            **base.model_dump(),
            counters=[CounterOut.model_validate(x) for x in counters],
            completed_count=c[EntryStatus.COMPLETED.value],
            removed_count=c[EntryStatus.REMOVED.value],
            abandoned_count=c[EntryStatus.ABANDONED.value],
            last_token=queue.last_token,
        )

    def update_queue(self, queue_id: int, data: QueueUpdate) -> QueueOut:
        with self._tx():
            queue = self._queue(queue_id)
            changes: dict[str, Any] = {}
            for field, value in data.model_dump(exclude_unset=True).items():
                value = value.value if hasattr(value, "value") else value
                if getattr(queue, field) != value:
                    changes[field] = {"from": getattr(queue, field), "to": value}
                    setattr(queue, field, value)
            if changes:
                queue.updated_at = utcnow()
                self._log(queue_id, EventType.QUEUE_UPDATED, metadata={"changes": changes})
        return self._queue_out(queue, self._queue_counts([queue_id])[queue_id])

    def delete_queue(self, queue_id: int) -> None:
        with self._tx():
            queue = self._queue(queue_id)
            self.db.delete(queue)

    def add_entry(self, queue_id: int, service_class: str | None = None) -> EntryOut:
        with self._tx():
            queue = self._queue(queue_id)
            if queue.status == QueueStatus.CLOSED.value:
                raise ConflictError(f"Queue {queue_id} is closed", "queue_closed")
            if service_class is not None and self.db.scalar(select(SlaPolicy.id).where(
                    SlaPolicy.queue_id == queue_id, SlaPolicy.service_class == service_class)) is None:
                raise UnprocessableError(
                    f"Queue {queue_id} has no SLA policy for service class '{service_class}'", "unknown_service_class")
            self.db.execute(
                update(Queue).where(Queue.id == queue_id)
                .values(last_token=Queue.last_token + 1, updated_at=Queue.updated_at)
                .execution_options(synchronize_session=False)
            )
            token = self.db.execute(select(Queue.last_token).where(Queue.id == queue_id)).scalar_one()
            now = utcnow()
            entry = QueueEntry(queue_id=queue_id, token_number=token, status=WAITING, arrival_time=now,
                               service_class=service_class)
            self.db.add(entry)
            self.db.flush()
            position = self.db.execute(
                select(func.count()).where(
                    QueueEntry.queue_id == queue_id, QueueEntry.status == WAITING,
                    QueueEntry.token_number <= token,
                )
            ).scalar_one()
            self._log(
                queue_id, EventType.ENTRY_ADDED, timestamp=now,
                metadata={"entry_id": entry.id, "token_number": token, "position": position},
            )
        return self._entry_out(entry, {entry.id: position})

    def list_entries(
        self, queue_id: int, status: EntryStatus | None = None, limit: int = 100, offset: int = 0
    ) -> list[EntryOut]:
        self._queue(queue_id)
        stmt = (
            select(QueueEntry).where(QueueEntry.queue_id == queue_id)
            .order_by(QueueEntry.token_number).limit(limit).offset(offset)
        )
        if status:
            stmt = stmt.where(QueueEntry.status == status.value)
        entries = self.db.scalars(stmt).all()
        positions = self._positions(queue_id)
        now = utcnow()
        return [self._entry_out(e, positions, now) for e in entries]

    def get_entry(self, queue_id: int, entry_id: int) -> EntryOut:
        self._queue(queue_id)
        entry = self._entry(queue_id, entry_id)
        return self._entry_out(entry, self._positions(queue_id))

    def get_position(self, queue_id: int, entry_id: int) -> EntryPosition:
        self._queue(queue_id)
        entry = self._entry(queue_id, entry_id)
        pos = self._positions(queue_id).get(entry.id) if entry.status == WAITING else None
        return EntryPosition(
            entry_id=entry.id, token_number=entry.token_number, status=EntryStatus(entry.status),
            position=pos, entries_ahead=None if pos is None else pos - 1,
        )

    def remove_entry(self, queue_id: int, entry_id: int) -> None:
        with self._tx():
            self._queue(queue_id)
            entry = self._entry(queue_id, entry_id)
            if entry.status != WAITING:
                raise ConflictError(
                    f"Only waiting entries can be removed (entry is {entry.status})", "entry_not_waiting"
                )
            entry.status = EntryStatus.REMOVED.value
            self._log(
                queue_id, EventType.ENTRY_REMOVED,
                metadata={"entry_id": entry.id, "token_number": entry.token_number},
            )

    def _pick_counter(self, queue_id: int, counter_id: int | None) -> ServiceCounter:
        if counter_id is not None:
            counter = self._counter(counter_id)
            if counter.queue_id != queue_id:
                raise ConflictError(
                    f"Counter {counter_id} does not belong to queue {queue_id}", "counter_wrong_queue"
                )
            if counter.status != CounterStatus.ACTIVE.value:
                raise ConflictError(f"Counter {counter_id} is {counter.status}", "counter_unavailable")
            if counter.current_load > 0:
                raise ConflictError(f"Counter {counter_id} is busy", "counter_busy")
            return counter
        counter = self.db.scalars(
            select(ServiceCounter)
            .where(
                ServiceCounter.queue_id == queue_id,
                ServiceCounter.status == CounterStatus.ACTIVE.value,
                ServiceCounter.current_load == 0,
            )
            .order_by(ServiceCounter.id).limit(1)
        ).first()
        if counter is None:
            raise ConflictError(f"No idle active counter in queue {queue_id}", "no_available_counter")
        return counter

    def _start_service(self, queue: Queue, entry: QueueEntry, counter: ServiceCounter) -> ServeResult:
        if queue.status != QueueStatus.ACTIVE.value:
            raise ConflictError(f"Queue {queue.id} is {queue.status}; cannot serve", "queue_not_active")
        now = utcnow()
        claimed = self.db.execute(
            update(QueueEntry)
            .where(QueueEntry.id == entry.id, QueueEntry.status == WAITING)
            .values(status=SERVING, counter_id=counter.id, service_start_time=now)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            raise ConflictError(f"Entry {entry.id} is no longer waiting", "entry_unavailable")
        busy = self.db.execute(
            update(ServiceCounter)
            .where(
                ServiceCounter.id == counter.id, ServiceCounter.current_load == 0,
                ServiceCounter.status == CounterStatus.ACTIVE.value,
            )
            .values(current_load=1)
            .execution_options(synchronize_session=False)
        )
        if busy.rowcount != 1:
            raise ConflictError(f"Counter {counter.id} is no longer available", "counter_busy")
        self.db.refresh(entry)
        self.db.refresh(counter)
        self._log(
            queue.id, EventType.SERVICE_STARTED, counter_id=counter.id, timestamp=now,
            metadata={
                "entry_id": entry.id, "token_number": entry.token_number,
                "waiting_time_seconds": (now - entry.arrival_time).total_seconds(),
            },
        )
        return ServeResult(entry=self._entry_out(entry), counter=CounterOut.model_validate(counter))

    def serve_next(self, queue_id: int, counter_id: int | None = None) -> ServeResult:
        """Serve the waiting customer with the lowest token (strict FIFO)."""
        with self._tx():
            queue = self._queue(queue_id)
            if queue.status != QueueStatus.ACTIVE.value:
                raise ConflictError(f"Queue {queue_id} is {queue.status}; cannot serve", "queue_not_active")
            entry = self.db.scalars(
                select(QueueEntry)
                .where(QueueEntry.queue_id == queue_id, QueueEntry.status == WAITING)
                .order_by(QueueEntry.token_number).limit(1)
            ).first()
            if entry is None:
                raise ConflictError(f"Queue {queue_id} has no waiting customers", "queue_empty")
            counter = self._pick_counter(queue_id, counter_id)
            return self._start_service(queue, entry, counter)

    def assign_entry(self, queue_id: int, entry_id: int, counter_id: int) -> ServeResult:
        """Send a specific waiting customer to a specific idle counter."""
        with self._tx():
            queue = self._queue(queue_id)
            entry = self._entry(queue_id, entry_id)
            if entry.status != WAITING:
                raise ConflictError(f"Entry {entry_id} is {entry.status}, not waiting", "entry_not_waiting")
            counter = self._pick_counter(queue_id, counter_id)
            return self._start_service(queue, entry, counter)

    def complete_service(self, queue_id: int, entry_id: int) -> CompleteResult:
        with self._tx():
            self._queue(queue_id)
            entry = self._entry(queue_id, entry_id)
            if entry.status != SERVING:
                raise ConflictError(f"Entry {entry_id} is {entry.status}, not being served", "entry_not_serving")
            now = utcnow()
            start = entry.service_start_time or now
            end = max(now, start)
            entry.status = EntryStatus.COMPLETED.value
            entry.service_end_time = end
            counter = self.db.get(ServiceCounter, entry.counter_id) if entry.counter_id else None
            if counter is not None and counter.current_load > 0:
                counter.current_load -= 1
            record = ServiceRecord(
                queue_id=queue_id, counter_id=entry.counter_id, entry_id=entry.id,
                waiting_time=(start - entry.arrival_time).total_seconds(),
                service_time=(end - start).total_seconds(), completed_at=end,
            )
            self.db.add(record)
            self.db.flush()
            self._log(
                queue_id, EventType.SERVICE_COMPLETED, counter_id=entry.counter_id, timestamp=end,
                metadata={
                    "entry_id": entry.id, "token_number": entry.token_number,
                    "waiting_time_seconds": record.waiting_time, "service_time_seconds": record.service_time,
                },
            )
        return CompleteResult(
            entry=self._entry_out(entry),
            counter=CounterOut.model_validate(counter) if counter else None,
            record=ServiceRecordOut.model_validate(record),
        )

    def get_state(self, queue_id: int, waiting_limit: int = 100) -> QueueState:
        queue = self._queue(queue_id)
        counts = self._queue_counts([queue_id])[queue_id]
        now = utcnow()
        waiting = self.db.scalars(
            select(QueueEntry).where(QueueEntry.queue_id == queue_id, QueueEntry.status == WAITING)
            .order_by(QueueEntry.token_number).limit(waiting_limit)
        ).all()
        positions = {e.id: i for i, e in enumerate(waiting, start=1)}
        serving = self.db.scalars(
            select(QueueEntry).where(QueueEntry.queue_id == queue_id, QueueEntry.status == SERVING)
            .order_by(QueueEntry.service_start_time)
        ).all()
        counters = self.db.scalars(
            select(ServiceCounter).where(ServiceCounter.queue_id == queue_id).order_by(ServiceCounter.id)
        ).all()
        idle = sum(1 for c in counters if c.status == CounterStatus.ACTIVE.value and c.current_load == 0)
        return QueueState(
            queue_id=queue_id, queue_status=QueueStatus(queue.status), as_of=now,
            waiting_count=counts[WAITING], serving_count=counts[SERVING],
            completed_count=counts[EntryStatus.COMPLETED.value],
            removed_count=counts[EntryStatus.REMOVED.value],
            abandoned_count=counts[EntryStatus.ABANDONED.value],
            next_token=waiting[0].token_number if waiting else None,
            idle_counters=idle,
            waiting=[self._entry_out(e, positions, now) for e in waiting],
            serving=[self._entry_out(e, None, now) for e in serving],
            counters=[CounterOut.model_validate(c) for c in counters],
            waiting_truncated=counts[WAITING] > len(waiting),
        )

    def list_events(self, queue_id: int, event_type: str | None = None, limit: int = 100, offset: int = 0):
        self._queue(queue_id)
        stmt = (
            select(QueueEvent).where(QueueEvent.queue_id == queue_id)
            .order_by(QueueEvent.id.desc()).limit(limit).offset(offset)
        )
        if event_type:
            stmt = stmt.where(QueueEvent.event_type == event_type)
        return self.db.scalars(stmt).all()

    def create_counter(self, data: CounterCreate) -> CounterOut:
        with self._tx():
            self._queue(data.queue_id)
            counter = ServiceCounter(
                queue_id=data.queue_id, name=data.name, service_rate=data.service_rate, status=data.status.value
            )
            self.db.add(counter)
            try:
                self.db.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    f"A counter named '{data.name}' already exists in queue {data.queue_id}", "counter_name_taken"
                ) from exc
            self._log(
                data.queue_id, EventType.COUNTER_CREATED, counter_id=counter.id,
                metadata={"name": counter.name, "service_rate": counter.service_rate},
            )
        return CounterOut.model_validate(counter)

    def list_counters(
        self, queue_id: int | None = None, status: CounterStatus | None = None, limit: int = 200, offset: int = 0
    ) -> list[CounterOut]:
        stmt = select(ServiceCounter).order_by(ServiceCounter.id).limit(limit).offset(offset)
        if queue_id is not None:
            stmt = stmt.where(ServiceCounter.queue_id == queue_id)
        if status:
            stmt = stmt.where(ServiceCounter.status == status.value)
        return [CounterOut.model_validate(c) for c in self.db.scalars(stmt).all()]

    def get_counter(self, counter_id: int) -> CounterOut:
        return CounterOut.model_validate(self._counter(counter_id))

    def _apply_status(self, counter: ServiceCounter, new_status: CounterStatus) -> bool:
        old = counter.status
        if old == new_status.value:
            return False
        counter.status = new_status.value
        event = {
            CounterStatus.PAUSED: EventType.COUNTER_PAUSED,
            CounterStatus.CLOSED: EventType.COUNTER_CLOSED,
            CounterStatus.ACTIVE: EventType.COUNTER_RESUMED,
        }[new_status]
        self._log(counter.queue_id, event, counter_id=counter.id, metadata={"from": old, "to": new_status.value})
        return True

    def update_counter(self, counter_id: int, data: CounterUpdate) -> CounterOut:
        with self._tx():
            counter = self._counter(counter_id)
            changes = data.model_dump(exclude_unset=True)
            status = changes.pop("status", None)
            other: dict[str, Any] = {}
            for field, value in changes.items():
                if getattr(counter, field) != value:
                    other[field] = {"from": getattr(counter, field), "to": value}
                    setattr(counter, field, value)
            if other:
                try:
                    self.db.flush()
                except IntegrityError as exc:
                    raise ConflictError(
                        f"A counter named '{changes.get('name')}' already exists in this queue", "counter_name_taken"
                    ) from exc
                self._log(counter.queue_id, EventType.COUNTER_UPDATED, counter_id=counter.id, metadata=other)
            if status is not None:
                self._apply_status(counter, CounterStatus(status))
        return CounterOut.model_validate(counter)

    def pause_counter(self, counter_id: int) -> CounterOut:
        """Idempotent. A customer already at the counter finishes; no new one is assigned."""
        with self._tx():
            counter = self._counter(counter_id)
            self._apply_status(counter, CounterStatus.PAUSED)
        return CounterOut.model_validate(counter)

    def resume_counter(self, counter_id: int) -> CounterOut:
        with self._tx():
            counter = self._counter(counter_id)
            self._apply_status(counter, CounterStatus.ACTIVE)
        return CounterOut.model_validate(counter)
