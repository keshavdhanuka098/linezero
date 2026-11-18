from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EntryStatus


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    queue_id: int
    token_number: int
    status: EntryStatus
    position: int | None = Field(default=None, description="1-based place in line; null unless waiting")
    counter_id: int | None = None
    arrival_time: datetime
    service_start_time: datetime | None = None
    service_end_time: datetime | None = None
    waiting_time_seconds: float | None = Field(
        default=None, description="Time spent waiting (so far, if still waiting)"
    )
    is_synthetic: bool = False
    service_class: str | None = Field(default=None, description="SLA service class; null = 'standard'")


class EntryCreate(BaseModel):
    """Optional body of POST /queues/{id}/entries (the endpoint still works with no body)."""
    model_config = ConfigDict(extra="forbid")
    service_class: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9_-]*$",
                                      description="SLA service class; must have an SLA policy on this queue")


class EntryPosition(BaseModel):
    entry_id: int
    token_number: int
    status: EntryStatus
    position: int | None
    entries_ahead: int | None


class ServeNextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter_id: int | None = Field(default=None, gt=0, description="Specific counter; auto-picked if omitted")


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counter_id: int = Field(gt=0)


class ServiceRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    queue_id: int
    counter_id: int | None
    entry_id: int | None
    waiting_time: float
    service_time: float
    completed_at: datetime
    is_synthetic: bool
