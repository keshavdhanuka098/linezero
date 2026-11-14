from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utcnow
from app.models.enums import ReportType, sql_in


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(sql_in("report_type", ReportType), name="type_valid"),
        Index("ix_reports_type_created", "report_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    queue_id: Mapped[int | None] = mapped_column(ForeignKey("queues.id", ondelete="SET NULL"))
    report_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    contains_synthetic_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
