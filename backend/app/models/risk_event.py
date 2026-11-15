from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import RiskCategory, RiskStatus, Severity, sql_in


class RiskEvent(Base):
    """A detected operational risk. Repeated scans refresh the open event for the same (category, resource)."""

    __tablename__ = "risk_events"
    __table_args__ = (
        CheckConstraint(sql_in("category", RiskCategory), name="category_valid"),
        CheckConstraint(sql_in("severity", Severity), name="severity_valid"),
        CheckConstraint(sql_in("status", RiskStatus), name="status_valid"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        Index("ix_risk_events_queue_detected", "queue_id", "detected_at"),
        Index("ix_risk_events_queue_status", "queue_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'queue' | 'counter'
    resource_id: Mapped[int | None] = mapped_column(Integer)
    resource_name: Mapped[str] = mapped_column(String(120), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    time_to_impact_min: Mapped[float | None] = mapped_column(Float)
    supporting_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recommended_intervention: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RiskStatus.OPEN.value)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    calibration_version: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
