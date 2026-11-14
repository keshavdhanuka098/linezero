"""Request/response schemas for the Part 2 intelligence endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ReportType


class PredictionOut(BaseModel):
    queue_id: int
    prediction_id: int | None
    predicted_waiting_time_s: float
    predicted_waiting_time_min: float
    prediction_method: str
    prediction_timestamp: datetime
    baseline_waiting_time_s: float
    input_features: dict[str, Any]
    queue_state: dict[str, Any]
    uncertainty: dict[str, Any] | None
    assumptions: list[str]
    notes: list[str]
    model: dict[str, Any]
    is_synthetic: bool


class ActualObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_id: int = Field(gt=0)
    actual_waiting_time_s: float = Field(ge=0)


class PredictionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_id: int = Field(gt=0)
    mode: Literal["stored", "backtest"] = "stored"
    prediction_ids: list[int] | None = None
    actuals: list[ActualObservation] | None = None
    max_match_gap_seconds: float = Field(default=900.0, gt=0, le=86400)


class BottleneckAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_id: int | None = Field(default=None, gt=0, description="Omit to analyse every non-closed queue")
    window_minutes: float = Field(default=240.0, ge=10, le=10080)
    lookback_minutes: float = Field(default=1440.0, ge=60, le=43200)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.lookback_minutes < self.window_minutes:
            raise ValueError("lookback_minutes must be >= window_minutes")
        return self


class DetectionOut(BaseModel):
    detection_id: int
    bottleneck_type: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    queue_id: int
    counter_id: int | None
    supporting_metrics: dict[str, Any]
    explanation: str
    operational_impact: str
    recommendation: str
    detection_timestamp: datetime
    window_start: datetime | None
    window_end: datetime | None
    is_synthetic: bool


class BottleneckAnalyzeOut(BaseModel):
    analyzed_at: datetime
    window_minutes: float
    lookback_minutes: float
    thresholds: dict[str, Any]
    queues_analyzed: int
    detection_count: int
    detections: list[DetectionOut]
    by_queue: list[dict[str, Any]]


class ConstraintsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_active_counters: int | None = Field(default=None, ge=1, le=100)
    min_active_counters: int = Field(default=1, ge=1, le=100)
    max_cost_per_hour: float | None = Field(default=None, gt=0)
    max_counter_utilization: float | None = Field(default=None, gt=0, le=1)
    allow_new_counters: int = Field(default=0, ge=0, le=20)
    allow_policy_change: bool = True


class SimulationSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration_minutes: float = Field(default=480.0, gt=0, le=100_000)
    replications: int = Field(default=8, ge=1, le=30)
    seed: int = Field(default=12345, ge=0, le=2**31)
    service_distribution: Literal["exponential", "deterministic", "uniform", "lognormal"] = "exponential"


class OptimizationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queue_id: int = Field(gt=0)
    arrival_rate: float | None = Field(default=None, gt=0, le=10_000, description="Customers/minute; estimated if omitted")
    arrival_window_minutes: float = Field(default=240.0, ge=10, le=10080)
    cost_per_counter_hour: float = Field(default=1.0, ge=0)
    counter_costs_per_hour: dict[int, float] | None = None
    new_counter_service_rate: float | None = Field(default=None, gt=0, le=1000)
    new_counter_cost_per_hour: float | None = Field(default=None, ge=0)
    constraints: ConstraintsIn = ConstraintsIn()
    simulation: SimulationSettingsIn = SimulationSettingsIn()


class OptimizationOut(BaseModel):
    optimization_id: int
    queue_id: int
    created_at: datetime
    current_allocation: dict[str, Any]
    proposed_allocation: dict[str, Any]
    current_metrics: dict[str, Any]
    proposed_metrics: dict[str, Any]
    estimated_improvement: dict[str, Any]
    resource_requirements: dict[str, Any] | None
    explanation: str
    details: dict[str, Any]
    is_synthetic: bool


class AnalyticsOut(BaseModel):
    filters: dict[str, Any]
    meta: dict[str, Any]
    summary: dict[str, Any]
    charts: dict[str, Any]
    tables: dict[str, Any]


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_type: ReportType
    queue_id: int | None = Field(default=None, gt=0)
    simulation_id: int | None = Field(default=None, gt=0)
    optimization_id: int | None = Field(default=None, gt=0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    tz_offset_minutes: int = Field(default=0, ge=-720, le=840)
    window_minutes: float = Field(default=240.0, ge=10, le=10080)
    lookback_minutes: float = Field(default=1440.0, ge=60, le=43200)


class ReportSummaryOut(BaseModel):
    report_id: int
    report_type: str
    title: str | None
    queue_id: int | None
    contains_synthetic_data: bool
    created_at: datetime


class ReportOut(ReportSummaryOut):
    report_data: dict[str, Any]
