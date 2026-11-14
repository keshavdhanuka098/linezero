"""Runs the optimisation engine for a stored queue and persists the comparison."""
from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import optimization_engine as oe
from app.engines.prediction_engine import prepare_history
from app.models import OptimizationResult, Queue, utcnow
from app.services.bottleneck_service import resolve_as_of
from app.services.data_access import load_frames


class OptimizationService:
    def __init__(self, db: Session):
        self.db = db

    def estimate_arrival_rate(self, queue: Queue, h: pd.DataFrame, window_minutes: float) -> float | None:
        if h.empty:
            return None
        when, _ = resolve_as_of(queue, h, window_minutes, None)
        end = pd.Timestamp(when)
        first = h["arrival"].min()
        start = max(end - pd.Timedelta(minutes=window_minutes), first)
        span_min = (end - start).total_seconds() / 60.0
        if span_min < 10:
            return None
        n = int(((h["arrival"] >= start) & (h["arrival"] < end)).sum())
        return n / span_min if n else None

    def run(self, req) -> dict[str, Any]:
        queue = self.db.get(Queue, req.queue_id)
        if queue is None:
            raise NotFoundError(f"Queue {req.queue_id} not found", "queue_not_found")
        fr = load_frames(self.db, queue_id=req.queue_id)
        h, _ = prepare_history(fr.entries)
        costs = {int(k): v for k, v in (req.counter_costs_per_hour or {}).items()}
        existing = [oe.CounterSpec(str(c["id"]), c["name"], c["service_rate"], c["status"], c["id"],
                                   costs.get(c["id"], req.cost_per_counter_hour)) for c in fr.counters]
        if not existing:
            raise ConflictError("The queue has no counters to optimise", "no_counters")
        rate_source = "request"
        lam = req.arrival_rate
        if lam is None:
            lam = self.estimate_arrival_rate(queue, h, req.arrival_window_minutes)
            rate_source = f"estimated from the last {req.arrival_window_minutes:g} minutes of arrivals"
            if lam is None:
                raise UnprocessableError(
                    "Not enough arrival history to estimate the arrival rate; provide arrival_rate (customers/min)",
                    "arrival_rate_required")
        c = req.constraints
        constraints = oe.Constraints(
            max_active_counters=c.max_active_counters, min_active_counters=c.min_active_counters,
            max_cost_per_hour=c.max_cost_per_hour, max_counter_utilization=c.max_counter_utilization,
            allow_new_counters=c.allow_new_counters, allow_policy_change=c.allow_policy_change)
        s = req.simulation
        settings = oe.Settings(duration_min=s.duration_minutes, replications=s.replications, seed=s.seed,
                               service_distribution=s.service_distribution)
        try:
            result = oe.optimize(existing, lam, constraints, settings, req.new_counter_service_rate,
                                 req.new_counter_cost_per_hour)
        except oe.OptimizationError as exc:
            raise UnprocessableError(str(exc), "invalid_optimization_request")
        except oe.OptimizationInfeasible as exc:
            raise ConflictError(str(exc), "optimization_infeasible")
        except ValidationError as exc:
            raise UnprocessableError("Simulation configuration rejected", "invalid_simulation_configuration",
                                     [{"message": e["msg"]} for e in exc.errors()])
        result["details"]["arrival_rate_source"] = rate_source
        result["details"]["resource_requirements"] = result["resource_requirements"]
        result["details"]["synthetic_note"] = ("Counters and demand come from synthetic data."
                                               if queue.is_synthetic else None)
        row = OptimizationResult(
            queue_id=req.queue_id, current_allocation=json_safe(result["current_allocation"]),
            proposed_allocation=json_safe(result["proposed_allocation"]),
            current_metrics=json_safe(result["current_metrics"]), proposed_metrics=json_safe(result["proposed_metrics"]),
            estimated_improvement=json_safe(result["estimated_improvement"]), explanation=result["explanation"],
            details=json_safe(result["details"]), created_at=utcnow(), is_synthetic=queue.is_synthetic)
        self.db.add(row)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.to_dict(row)

    @staticmethod
    def to_dict(r: OptimizationResult) -> dict[str, Any]:
        d = r.details or {}
        return json_safe({
            "optimization_id": r.id, "queue_id": r.queue_id, "created_at": r.created_at,
            "current_allocation": r.current_allocation, "proposed_allocation": r.proposed_allocation,
            "current_metrics": r.current_metrics, "proposed_metrics": r.proposed_metrics,
            "estimated_improvement": r.estimated_improvement, "resource_requirements": d.get("resource_requirements"),
            "explanation": r.explanation, "details": d, "is_synthetic": r.is_synthetic})

    def get(self, optimization_id: int) -> dict[str, Any]:
        r = self.db.get(OptimizationResult, optimization_id)
        if r is None:
            raise NotFoundError(f"Optimization {optimization_id} not found", "optimization_not_found")
        return self.to_dict(r)
