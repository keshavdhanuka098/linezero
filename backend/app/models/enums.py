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
