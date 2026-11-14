from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.engines.simulation_engine import SimulationConfig


class SimulationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, max_length=120)
    configuration: SimulationConfig


class CompareItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, max_length=120)
    configuration: SimulationConfig


class SimulationCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configurations: list[CompareItem] = Field(min_length=2, max_length=10)
    seed: int | None = Field(
        default=None, ge=0, le=2**32 - 1,
        description="Shared seed for configurations that don't set their own (fair like-for-like comparison)",
    )


class SimulationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str | None
    status: str
    configuration: dict[str, Any]
    results: dict[str, Any] | None
    seed: int | None
    runtime_ms: float | None
    comparison_id: str | None
    created_at: datetime


class SimulationCompareOut(BaseModel):
    comparison_id: str
    runs: list[SimulationRunOut]
    comparison: dict[str, Any]


class SimulationResetOut(BaseModel):
    deleted: int
