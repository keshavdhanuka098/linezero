from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import CounterStatus


class CounterCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    queue_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    service_rate: float = Field(default=1.0, gt=0, le=1000, description="Customers served per minute")
    status: CounterStatus = CounterStatus.ACTIVE


class CounterUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    service_rate: float | None = Field(default=None, gt=0, le=1000)
    status: CounterStatus | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one of: name, service_rate, status")
        for f in self.model_fields_set:
            if getattr(self, f) is None:
                raise ValueError(f"{f} cannot be null")
        return self


class CounterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    queue_id: int
    name: str
    service_rate: float
    status: CounterStatus
    current_load: int
    is_synthetic: bool
