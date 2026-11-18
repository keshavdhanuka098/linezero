"""Request schemas for the SLA & Customer Experience Intelligence module."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.adaptive import CostModel

CLASS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlaPolicyIn(Strict):
    max_wait_min: float = Field(gt=0, le=1440, description="Maximum acceptable waiting time, in minutes")
    at_risk_probability: float = Field(default=0.25, gt=0, lt=1,
                                       description="Breach probability from which a waiting customer is 'at risk'")
    critical_probability: float = Field(default=0.6, gt=0, lt=1,
                                        description="Breach probability from which a waiting customer is 'critical'")
    label: str | None = Field(default=None, max_length=120)
    operator: str = Field(min_length=1, max_length=120, description="Who is making the change (audit field)")

    @field_validator("operator")
    @classmethod
    def _operator(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("operator must not be blank")
        return v

    @field_validator("label")
    @classmethod
    def _label(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def _ordered(self) -> "SlaPolicyIn":
        if not self.at_risk_probability < self.critical_probability:
            raise ValueError("at_risk_probability must be lower than critical_probability")
        return self


class EntryClassRequest(Strict):
    service_class: str = Field(min_length=1, max_length=40, pattern=CLASS_RE.pattern)


class SlaRecommendRequest(Strict):
    horizon_min: float = Field(default=60.0, ge=10, le=240)
    replications: int = Field(default=10, ge=3, le=20)
    seed: int = Field(default=2026, ge=0, le=2**31 - 1)
    cost_model: CostModel = Field(default_factory=CostModel)
    use_calibration: bool = True
    persist: bool = Field(default=False, description="Store the candidates as proposals for operator approval")


def class_ok(value: str) -> bool:
    return bool(CLASS_RE.match(value)) and len(value) <= 40


__all__: list[Any] = ["SlaPolicyIn", "EntryClassRequest", "SlaRecommendRequest", "class_ok", "CLASS_RE"]
