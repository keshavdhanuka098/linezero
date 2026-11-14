from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import QueueStatus
from app.schemas.counter import CounterOut
from app.schemas.entry import EntryOut


class QueueCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: QueueStatus = QueueStatus.ACTIVE


class QueueUpdate(BaseModel):
    """PUT body: send the fields you want to change (at least one)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: QueueStatus | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: name, description, status")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        return self


class QueueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None
    status: QueueStatus
    is_synthetic: bool
    scenario: str | None
    created_at: datetime
    updated_at: datetime
    waiting_count: int = 0
    serving_count: int = 0
    counter_count: int = 0


class QueueDetail(QueueOut):
    counters: list[CounterOut] = []
    completed_count: int = 0
    removed_count: int = 0
    abandoned_count: int = 0
    last_token: int = 0


class QueueState(BaseModel):
    """Live snapshot of a queue."""

    queue_id: int
    queue_status: QueueStatus
    as_of: datetime
    waiting_count: int
    serving_count: int
    completed_count: int
    removed_count: int
    abandoned_count: int
    next_token: int | None
    idle_counters: int
    waiting: list[EntryOut]
    serving: list[EntryOut]
    counters: list[CounterOut]
    waiting_truncated: bool = False


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    queue_id: int
    counter_id: int | None
    event_type: str
    timestamp: datetime
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="event_metadata")
    is_synthetic: bool


class ServeResult(BaseModel):
    entry: EntryOut
    counter: CounterOut


class CompleteResult(BaseModel):
    entry: EntryOut
    counter: CounterOut | None
    record: "ServiceRecordOut"


from app.schemas.entry import ServiceRecordOut  # noqa: E402

CompleteResult.model_rebuild()
