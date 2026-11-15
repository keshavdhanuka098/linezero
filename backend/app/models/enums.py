"""Status / event vocabularies shared by models, services and schemas."""
from __future__ import annotations

from enum import Enum


class QueueStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class CounterStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class EntryStatus(str, Enum):
    WAITING = "waiting"
    SERVING = "serving"
    COMPLETED = "completed"
    REMOVED = "removed"
    ABANDONED = "abandoned"


class EventType(str, Enum):
    QUEUE_CREATED = "queue_created"
    QUEUE_UPDATED = "queue_updated"
    ENTRY_ADDED = "entry_added"
    ENTRY_REMOVED = "entry_removed"
    ENTRY_ABANDONED = "entry_abandoned"
    SERVICE_STARTED = "service_started"
    SERVICE_COMPLETED = "service_completed"
    COUNTER_CREATED = "counter_created"
    COUNTER_UPDATED = "counter_updated"
    COUNTER_PAUSED = "counter_paused"
    COUNTER_RESUMED = "counter_resumed"
    COUNTER_CLOSED = "counter_closed"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BottleneckType(str, Enum):
    COUNTER_OVERLOAD = "counter_overload"
    UNEVEN_UTILIZATION = "uneven_utilization"
    ARRIVAL_SPIKE = "arrival_spike"
    SLOW_SERVICE = "slow_service"
    CAPACITY_DEMAND_IMBALANCE = "capacity_demand_imbalance"


class ReportType(str, Enum):
    QUEUE_PERFORMANCE = "queue_performance"
    SIMULATION_RESULTS = "simulation_results"
    PREDICTION_EVALUATION = "prediction_evaluation"
    BOTTLENECK_ANALYSIS = "bottleneck_analysis"
    OPTIMIZATION_COMPARISON = "optimization_comparison"


def sql_in(column: str, enum: type[Enum]) -> str:
    values = ",".join(f"'{e.value}'" for e in enum)
    return f"{column} IN ({values})"


# --------------------------------------------------------------------------- LineZero 2.0 (adaptive intelligence)
class CalibrationStatus(str, Enum):
    ACTIVE = "active"          # the version the twin currently uses (at most one per queue)
    SUPERSEDED = "superseded"  # accepted earlier, replaced by a newer version or a rollback
    REJECTED = "rejected"      # a candidate that failed validation; kept for audit, never used


class CalibrationSource(str, Enum):
    CALIBRATION = "calibration"
    ROLLBACK = "rollback"


class RiskCategory(str, Enum):
    QUEUE_CONGESTION = "queue_congestion"
    COUNTER_OVERLOAD = "counter_overload"
    WAITING_TIME_TREND = "waiting_time_trend"
    CAPACITY_SHORTAGE = "capacity_shortage"
    COUNTER_FAILURE_PRECURSOR = "counter_failure_precursor"
    ABNORMAL_ARRIVALS = "abnormal_arrivals"
    UTILIZATION_IMBALANCE = "utilization_imbalance"


class RiskStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class InterventionStatus(str, Enum):
    PROPOSED = "proposed"   # produced by simulation only; nothing has happened
    APPROVED = "approved"   # an operator accepted the proposal; LineZero still changed nothing
    REJECTED = "rejected"
    APPLIED = "applied"     # the operator confirms they carried it out in the real world
    EVALUATED = "evaluated"  # an outcome (observed or operator-reported) has been recorded


class OutcomeVerification(str, Enum):
    VERIFIED_REAL = "verified_real_observation"   # measured from real (non-synthetic) database observations
    SYNTHETIC = "synthetic_observation"           # measured from synthetic demo data: NOT real-world verified
    OPERATOR_REPORTED = "operator_reported"       # typed in by an operator, not measured by LineZero
