from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow


class QueueEvent(Base):
    __tablename__ = "queue_events"
    __table_args__ = (Index("ix_queue_events_queue_timestamp", "queue_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    counter_id: Mapped[int | None] = mapped_column(ForeignKey("service_counters.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="events")
