from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import CalibrationSource, CalibrationStatus, sql_in


class CalibrationRecord(Base):
    """One versioned set of calibrated twin parameters for a queue (append-only history).

    Accepted calibrations and rollbacks get a per-queue `version` number; at most one row per queue is `active`.
    Candidates that failed validation are stored with status 'rejected' and no version, so the audit trail shows why
    a recalibration did not change the model. Rows are never updated except to flip active -> superseded.
    """

    __tablename__ = "calibration_records"
    __table_args__ = (
        CheckConstraint(sql_in("status", CalibrationStatus), name="status_valid"),
        CheckConstraint(sql_in("source", CalibrationSource), name="source_valid"),
        Index("ix_calibration_records_queue_version", "queue_id", "version"),
        Index("uq_calibration_records_one_active", "queue_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default=CalibrationSource.CALIBRATION.value)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    estimates: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    training_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    training_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    validation_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    validation_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    n_train_arrivals: Mapped[int | None] = mapped_column(Integer)
    n_train_services: Mapped[int | None] = mapped_column(Integer)
    n_validation: Mapped[int | None] = mapped_column(Integer)
    candidate_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    incumbent_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    drift: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    incumbent_version: Mapped[int | None] = mapped_column(Integer)
    rollback_to_version: Mapped[int | None] = mapped_column(Integer)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class CalibrationEvaluation(Base):
    """A stored prediction-error snapshot (MAE/RMSE/MAPE) so error can be tracked over time."""

    __tablename__ = "calibration_evaluations"
    __table_args__ = (
        CheckConstraint("n >= 0", name="n_nonneg"),
        Index("ix_calibration_evaluations_queue_time", "queue_id", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    calibration_id: Mapped[int | None] = mapped_column(ForeignKey("calibration_records.id", ondelete="SET NULL"))
    model_label: Mapped[str] = mapped_column(String(30), nullable=False)  # 'calibrated' | 'nominal'
    version: Mapped[int | None] = mapped_column(Integer)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    mae_s: Mapped[float | None] = mapped_column(Float)
    rmse_s: Mapped[float | None] = mapped_column(Float)
    mape_pct: Mapped[float | None] = mapped_column(Float)
    mean_error_s: Mapped[float | None] = mapped_column(Float)
    out_of_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
