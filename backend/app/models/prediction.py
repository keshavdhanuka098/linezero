from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow


class PredictionRecord(Base):
    """One waiting-time prediction for a customer joining a queue at `prediction_timestamp`.

    All durations are in seconds (same unit as ServiceRecord). `actual_waiting_time` stays NULL until the
    prediction is evaluated against a real outcome (POST /predictions/evaluate).
    """

    __tablename__ = "prediction_records"
    __table_args__ = (
        CheckConstraint("predicted_waiting_time >= 0", name="predicted_nonneg"),
        CheckConstraint("actual_waiting_time IS NULL OR actual_waiting_time >= 0", name="actual_nonneg"),
        Index("ix_prediction_records_queue_timestamp", "queue_id", "prediction_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    predicted_waiting_time: Mapped[float] = mapped_column(Float, nullable=False)
    actual_waiting_time: Mapped[float | None] = mapped_column(Float)
    prediction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    prediction_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    input_features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    matched_entry_id: Mapped[int | None] = mapped_column(ForeignKey("queue_entries.id", ondelete="SET NULL"))
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())

    queue = relationship("Queue", back_populates="predictions")
