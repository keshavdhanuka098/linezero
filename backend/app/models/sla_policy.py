from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow

DEFAULT_CLASS = "standard"


class SlaPolicy(Base):
    """An SLA target for one queue and one service class. A queue has no policy until an operator defines one:
    LineZero never assumes a target. `standard` is the class used by customers without a service class."""

    __tablename__ = "sla_policies"
    __table_args__ = (
        UniqueConstraint("queue_id", "service_class", name="queue_class"),
        CheckConstraint("max_wait_min > 0 AND max_wait_min <= 1440", name="max_wait_range"),
        CheckConstraint("at_risk_probability > 0 AND at_risk_probability < critical_probability "
                        "AND critical_probability < 1", name="thresholds_ordered"),
        Index("ix_sla_policies_queue", "queue_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    service_class: Mapped[str] = mapped_column(String(40), nullable=False, default=DEFAULT_CLASS)
    label: Mapped[str | None] = mapped_column(String(120))
    max_wait_min: Mapped[float] = mapped_column(Float, nullable=False)
    at_risk_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    critical_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)
