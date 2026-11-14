from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engines.twin_engine import TwinConfig

SEED_MAX = 2**32 - 1 - 200


class NamedScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    configuration: TwinConfig


class TwinSimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: TwinConfig
    replications: int = Field(default=5, ge=1, le=20, description="Independent seeds; the first is returned for playback")
    seed: int = Field(default=2026, ge=0, le=SEED_MAX)


class TwinCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[NamedScenario] = Field(min_length=2, max_length=5)
    replications: int = Field(default=8, ge=1, le=20)
    seed: int = Field(default=2026, ge=0, le=SEED_MAX)


class TwinRecoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: TwinConfig
    replications: int = Field(default=6, ge=2, le=20)
    seed: int = Field(default=2026, ge=0, le=SEED_MAX)
    max_extra_cost: float | None = Field(default=None, ge=0, description="Reject options costing more than this extra")


class TwinExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["congestion", "counter", "intervention", "scenarios"]
    configuration: TwinConfig | None = None
    scenarios: list[NamedScenario] | None = Field(default=None, min_length=2, max_length=5)
    replications: int = Field(default=6, ge=2, le=20)
    seed: int = Field(default=2026, ge=0, le=SEED_MAX)
    question: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _inputs(self):
        if self.kind == "scenarios" and not self.scenarios:
            raise ValueError("kind 'scenarios' requires 2-5 scenarios")
        if self.kind != "scenarios" and self.configuration is None:
            raise ValueError(f"kind '{self.kind}' requires a configuration")
        return self
