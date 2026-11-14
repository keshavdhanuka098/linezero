"""Digital Twin service: reads REAL queue state from the database; everything else is simulation.

Only read operations touch the database. No twin operation writes to queues, counters or entries.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import prediction_engine as pe
from app.engines import twin_forecast as tf
from app.models import Queue
from app.services.bottleneck_service import resolve_as_of
from app.services.prediction_service import PredictionService, _num
from app.services.queue_service import QueueService

logger = logging.getLogger("linezero.twin")
DEFAULT_SCENARIO_MINUTES = 120


class TwinService:
    def __init__(self, db: Session):
        self.db = db

    def _queue(self, queue_id: int) -> Queue:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def _arrival_rate(self, queue: Queue, h: pd.DataFrame, ctx: pe.HistoryContext) -> tuple[float | None, str, Any]:
        """Recent arrival rate from the existing prediction features; falls back to the historical average."""
        as_of, as_of_source = resolve_as_of(queue, h, 30.0, None)
        if h.empty:
            return None, "no_history", as_of
        t = np.array([(pd.Timestamp(as_of) - pe.EPOCH).total_seconds()])
        feats = pe.compute_features(h, t, ctx).iloc[0].to_dict()
        rate = _num(feats.get("arrival_rate_per_min"))
        if rate is not None and rate > 0:
            return rate, f"last_30_min_of_real_arrivals ({as_of_source})", as_of
        span_min = (h["arrival"].max() - h["arrival"].min()).total_seconds() / 60.0
        if span_min >= 10 and len(h) >= 10:
            return len(h) / span_min, "historical_average_of_all_arrivals", as_of
        return None, "insufficient_history", as_of

    def live(self, queue_id: int) -> dict[str, Any]:
        queue = self._queue(queue_id)
        state = QueueService(self.db).get_state(queue_id)
        ps = PredictionService(self.db)
        h, _, ctx, active, _ = ps._history(queue_id)
        rate, rate_source, as_of = self._arrival_rate(queue, h, ctx)

        counters = []
        for i, c in enumerate(state.counters):
            counters.append({
                "index": i, "id": c.id, "name": c.name, "status": c.status.value, "service_rate_per_min": c.service_rate,
                "active": c.status.value == "active", "busy": c.current_load > 0,
            })
        n_active = sum(1 for c in counters if c["active"])
        n_busy = sum(1 for c in counters if c["active"] and c["busy"])
        waiting_secs = [e.waiting_time_seconds or 0.0 for e in state.waiting]
        cong_q = max(5, 2 * n_active)
        if n_active == 0:
            status_ = "no_capacity"
        elif state.waiting_count >= cong_q:
            status_ = "congested"
        elif state.waiting_count > 0 and n_busy >= n_active:
            status_ = "busy"
        else:
            status_ = "normal"
        mu = float(sum(c["service_rate_per_min"] for c in counters if c["active"]))

        predicted = None
        if n_active:
            try:
                p = ps.predict(queue_id, store=False)
                predicted = {"waiting_time_min": p["predicted_waiting_time_min"], "method": p["prediction_method"]}
            except Exception as exc:  # prediction is optional context; never break the live view
                logger.info("live prediction unavailable: %s", exc)

        suggested = None
        if n_active:
            ref = mu / n_active
            suggested = {
                "arrival_rate": float(rate) if rate else 1.0, "mean_service_time": 1.0 / ref,
                "num_counters": len(counters), "duration": DEFAULT_SCENARIO_MINUTES,
                "counter_speed_factors": [c["service_rate_per_min"] / ref for c in counters],
                "standby_counters": [c["index"] for c in counters if not c["active"]],
                "arrival_rate_is_estimated_from_data": bool(rate),
            }
        return json_safe({
            "queue": {"id": queue.id, "name": queue.name, "status": queue.status, "is_synthetic": queue.is_synthetic},
            "as_of": state.as_of, "arrival_anchor_time": as_of,
            "counters": counters,
            "waiting": [{"token": e.token_number, "position": e.position, "waiting_seconds": e.waiting_time_seconds}
                        for e in state.waiting],
            "serving": [{"token": e.token_number, "counter_id": e.counter_id,
                         "service_elapsed_seconds": (state.as_of - e.service_start_time).total_seconds()
                         if e.service_start_time is not None else None} for e in state.serving],
            "metrics": {
                "queue_length": state.waiting_count, "serving": state.serving_count,
                "completed_total": state.completed_count, "abandoned_total": state.abandoned_count,
                "active_counters": n_active, "busy_counters": n_busy, "idle_counters": state.idle_counters,
                "counter_utilization_now": (n_busy / n_active) if n_active else None,
                "longest_current_wait_min": (max(waiting_secs) / 60.0) if waiting_secs else 0.0,
                "avg_current_wait_min": (float(np.mean(waiting_secs)) / 60.0) if waiting_secs else 0.0,
                "arrival_rate_per_min": rate, "arrival_rate_source": rate_source,
                "service_capacity_per_min": mu, "load_ratio": (rate / mu) if (rate and mu > 0) else None,
                "congestion_threshold": cong_q,
            },
            "operational_status": status_, "predicted_wait_now": predicted,
            "suggested_configuration": suggested,
            "data_provenance": {
                "queue_and_counters": "database (synthetic demo data)" if queue.is_synthetic else "database (real)",
                "arrival_rate": rate_source, "waiting_times": "computed from entry timestamps in the database",
                "predicted_wait_now": "existing prediction engine" if predicted else "unavailable",
            },
        })

    def forecast(self, queue_id: int, replications: int, seed: int, arrival_rate: float | None) -> dict[str, Any]:
        live = self.live(queue_id)
        m = live["metrics"]
        rate, source = m["arrival_rate_per_min"], m["arrival_rate_source"]
        if arrival_rate is not None:
            rate, source = arrival_rate, "user_override"
        state = {
            "queue_length": m["queue_length"], "arrival_rate_per_min": rate, "arrival_rate_source": source,
            "counters": [{"index": c["index"], "name": c["name"], "rate_per_min": c["service_rate_per_min"],
                          "active": c["active"], "busy": c["busy"]} for c in live["counters"]],
        }
        try:
            out = tf.forecast(state, replications=replications, seed=seed)
        except tf.ForecastUnavailable as exc:
            raise ConflictError(str(exc), "no_active_counters")
        except ValueError as exc:
            raise UnprocessableError(str(exc), "invalid_forecast_request")
        out["queue"] = live["queue"]
        out["as_of"] = live["as_of"]
        out["current_prediction"] = live["predicted_wait_now"]
        out["data_provenance"] = {
            "starting_state": "real queue state from the database"
                              + (" (synthetic demo data)" if live["queue"]["is_synthetic"] else ""),
            "arrival_rate": source,
            "future": "simulation (SimPy) - a model-based projection, not a measurement",
        }
        return json_safe(out)
