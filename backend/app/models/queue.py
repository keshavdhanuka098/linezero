from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import QueueStatus, sql_in


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (
        CheckConstraint(sql_in("status", QueueStatus), name="status_valid"),
        CheckConstraint("last_token >= 0", name="last_token_nonneg"),
        Index("ix_queues_is_synthetic", "is_synthetic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=QueueStatus.ACTIVE.value, index=True)
    last_token: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    scenario: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)

    counters = relationship(
        "ServiceCounter", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ServiceCounter.id",
    )
    entries = relationship(
        "QueueEntry", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
        order_by="QueueEntry.token_number",
    )
    events = relationship(
        "QueueEvent", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
        order_by="QueueEvent.id",
    )
    service_records = relationship(
        "ServiceRecord", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
    )
    predictions = relationship(
        "PredictionRecord", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
    )
    bottleneck_detections = relationship(
        "BottleneckDetection", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
    )
    optimization_results = relationship(
        "OptimizationResult", back_populates="queue", cascade="all, delete-orphan", passive_deletes=True,
    )
