from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow


class OptimizationResult(Base):
    __tablename__ = "optimization_results"
    __table_args__ = (Index("ix_optimization_results_queue_created", "queue_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    current_allocation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_allocation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    current_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    proposed_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    estimated_improvement: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="optimization_results")
