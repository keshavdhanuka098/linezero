from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow


class ServiceRecord(Base):
    """Immutable fact written when a customer finishes service (the basis for analytics/prediction)."""

    __tablename__ = "service_records"
    __table_args__ = (
        UniqueConstraint("entry_id", name="entry"),
        CheckConstraint("waiting_time >= 0", name="waiting_time_nonneg"),
        CheckConstraint("service_time >= 0", name="service_time_nonneg"),
        Index("ix_service_records_queue_completed", "queue_id", "completed_at"),
        Index("ix_service_records_counter", "counter_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    counter_id: Mapped[int | None] = mapped_column(ForeignKey("service_counters.id", ondelete="SET NULL"))
    entry_id: Mapped[int | None] = mapped_column(ForeignKey("queue_entries.id", ondelete="SET NULL"))
    waiting_time: Mapped[float] = mapped_column(Float, nullable=False)
    service_time: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="service_records")
