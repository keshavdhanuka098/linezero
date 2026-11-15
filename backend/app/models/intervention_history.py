from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import InterventionStatus, OutcomeVerification, sql_in


class InterventionHistory(Base):
    """One candidate intervention produced by the intervention engine, and everything that later happens to it.

    Honesty fields: `executed_by_linezero` is ALWAYS false (LineZero never changes real queues). `expected` is a
    simulation result. `outcome` + `outcome_verification` say whether a real outcome was measured, only reported by an
    operator, or measured on synthetic data.
    """

    __tablename__ = "intervention_history"
    __table_args__ = (
        CheckConstraint(sql_in("status", InterventionStatus), name="status_valid"),
        CheckConstraint("outcome_verification IS NULL OR " + sql_in("outcome_verification", OutcomeVerification),
                        name="verification_valid"),
        CheckConstraint("executed_by_linezero = false", name="never_auto_executed"),
        Index("ix_intervention_history_queue_created", "queue_id", "created_at"),
        Index("ix_intervention_history_evaluation", "evaluation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    evaluation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    risk_event_id: Mapped[int | None] = mapped_column(ForeignKey("risk_events.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    intervention_type: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[list[Any] | None] = mapped_column(JSON)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    baseline: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    simulation_meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=InterventionStatus.PROPOSED.value)
    decided_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    applied_by: Mapped[str | None] = mapped_column(String(120))
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    apply_note: Mapped[str | None] = mapped_column(Text)
    executed_by_linezero: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    outcome_verification: Mapped[str | None] = mapped_column(String(40))
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    calibration_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    calibration_version: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
