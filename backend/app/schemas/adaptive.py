"""Typed request/response schemas for the adaptive-intelligence endpoints (calibration, risk, interventions,
outcome learning, operations overview)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ calibration
class CalibrationRunRequest(StrictModel):
    validation_fraction: float = Field(default=0.3, ge=0.1, le=0.5,
                                       description="Latest share of served customers held out for validation")
    min_improvement_pct: float = Field(default=1.0, ge=0, le=100,
                                       description="Candidate must cut validation MAE by at least this much")
    prior_arrival_minutes: float = Field(default=60.0, ge=0, le=100_000,
                                         description="Weight of the active version as a prior for the arrival rate")
    prior_service_pseudo_n: float = Field(default=10.0, ge=0, le=100_000,
                                          description="Weight of the active version as a prior for the service rate")
    lookback_minutes: float | None = Field(default=None, gt=0, le=10_000_000,
                                           description="Only use observations from the last N minutes of history")
    dry_run: bool = Field(default=False, description="Compute and return the decision without saving anything")


class CalibrationRollbackRequest(StrictModel):
    version: int = Field(ge=1, description="The earlier calibration version to restore")
    reason: str = Field(min_length=3, max_length=500)
    operator: str = Field(min_length=1, max_length=120)


class CalibrationEvaluateRequest(StrictModel):
    scope: Literal["new_data", "all"] = Field(
        default="new_data",
        description="'new_data' evaluates only customers who arrived after the active version's training window "
                    "(out-of-sample); 'all' includes training data and is flagged as in-sample")


# ------------------------------------------------------------------ risk
class RiskScanRequest(StrictModel):
    persist: bool = Field(default=True, description="Store/refresh risk events in the database")
    forecast_replications: int = Field(default=20, ge=5, le=100)
    seed: int = Field(default=2026, ge=0, le=2**31)
    wait_sla_min: float = Field(default=10.0, gt=0, le=1440, description="Waiting time that counts as an SLA breach")


# ------------------------------------------------------------------ interventions
class CostModel(StrictModel):
    """All cost figures are RELATIVE units supplied by the operator (default: 1 unit = one counter-hour)."""

    counter_hour_cost: float = Field(default=1.0, ge=0, le=1_000_000)
    assist_staff_hour_cost: float = Field(default=0.5, ge=0, le=1_000_000,
                                          description="Cost of one assisting staff member per hour")
    diversion_cost_per_customer: float = Field(default=0.25, ge=0, le=1_000_000,
                                               description="Cost of sending one customer to an alternative channel")
    max_extra_cost: float | None = Field(default=None, ge=0, description="Budget cap on the extra cost of a candidate")
    max_assist_staff: int = Field(default=2, ge=0, le=100, description="Assisting staff that can be made available")
    cost_weight: float = Field(default=0.25, ge=0, le=1000,
                               description="Minutes-equivalent of score that one cost unit is worth when ranking")


class InterventionEvaluateRequest(StrictModel):
    horizon_min: float = Field(default=60.0, ge=10, le=240, description="Simulated horizon from 'now'")
    replications: int = Field(default=10, ge=3, le=20)
    seed: int = Field(default=2026, ge=0, le=2**31)
    risk_event_id: int | None = Field(default=None, ge=1)
    cost_model: CostModel = Field(default_factory=CostModel)
    persist: bool = Field(default=True, description="Store the evaluated candidates as 'proposed' in the history")
    use_calibration: bool = Field(default=True, description="Use the active calibration's arrival/service rates")


class DecisionRequest(StrictModel):
    operator: str = Field(min_length=1, max_length=120, description="Who made the decision")
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("operator")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("operator must not be blank")
        return v


class AppliedRequest(DecisionRequest):
    applied_at: datetime | None = Field(default=None, description="When it was carried out; defaults to now")


class ObservedOutcome(StrictModel):
    avg_wait_min: float = Field(ge=0, le=100_000)
    p95_wait_min: float | None = Field(default=None, ge=0, le=100_000)
    throughput_per_min: float | None = Field(default=None, ge=0, le=100_000)
    abandonment_rate: float | None = Field(default=None, ge=0, le=1)
    n_customers: int | None = Field(default=None, ge=0)


class OutcomeRequest(StrictModel):
    mode: Literal["observe", "manual"] = Field(
        default="observe", description="'observe' measures the outcome from the queue database; "
                                       "'manual' records figures an operator reports")
    window_minutes: float = Field(default=60.0, ge=10, le=1440, description="Length of the post-application window")
    observed: ObservedOutcome | None = Field(default=None, description="Required when mode is 'manual'")
    operator: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)


# ------------------------------------------------------------------ operations loop
class CycleRequest(StrictModel):
    recalibrate: bool = True
    evaluate_interventions: bool = True
    min_risk_severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    replications: int = Field(default=8, ge=3, le=20)
    seed: int = Field(default=2026, ge=0, le=2**31)


Json = dict[str, Any]
