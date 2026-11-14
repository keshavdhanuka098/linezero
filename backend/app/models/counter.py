from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import CounterStatus, sql_in


class ServiceCounter(Base):
    __tablename__ = "service_counters"
    __table_args__ = (
        UniqueConstraint("queue_id", "name", name="queue_name"),
        CheckConstraint(sql_in("status", CounterStatus), name="status_valid"),
        CheckConstraint("service_rate > 0", name="service_rate_positive"),
        CheckConstraint("current_load >= 0", name="current_load_nonneg"),
        Index("ix_service_counters_queue_status", "queue_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    service_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CounterStatus.ACTIVE.value)
    current_load: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="counters")
    entries = relationship("QueueEntry", back_populates="counter")
