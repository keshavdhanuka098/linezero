from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import EntryStatus, sql_in


class QueueEntry(Base):
    """One customer in a line. Deliberately anonymous: only a token number, no personal data."""

    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("queue_id", "token_number", name="queue_token"),
        CheckConstraint(sql_in("status", EntryStatus), name="status_valid"),
        CheckConstraint("token_number > 0", name="token_positive"),
        CheckConstraint(
            "service_end_time IS NULL OR service_start_time IS NULL OR service_end_time >= service_start_time",
            name="service_times_ordered",
        ),
        Index("ix_queue_entries_queue_status_token", "queue_id", "status", "token_number"),
        Index("ix_queue_entries_arrival_time", "arrival_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    counter_id: Mapped[int | None] = mapped_column(ForeignKey("service_counters.id", ondelete="SET NULL"))
    token_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=EntryStatus.WAITING.value)
    arrival_time: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    service_start_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    service_end_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="entries")
    counter = relationship("ServiceCounter", back_populates="entries")
