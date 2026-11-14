"""Waiting-time prediction: collects queue state, validates, predicts, stores, evaluates."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import prediction_engine as pe
from app.models import PredictionRecord, Queue, QueueEntry, utcnow
from app.services.data_access import load_frames

_MODEL_CACHE: dict[tuple, pe.ModelBundle] = {}
MAX_HISTORY_ROWS = 20000


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class PredictionService:
    def __init__(self, db: Session):
        self.db = db

    def _queue(self, queue_id: int) -> Queue:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def _history(self, queue_id: int):
        fr = load_frames(self.db, queue_id=queue_id)
        edf = fr.entries.tail(MAX_HISTORY_ROWS)
        h, stats = pe.prepare_history(edf)
        active = [c for c in fr.counters if c["status"] == "active"]
        ctx = pe.HistoryContext(len(active), float(sum(c["service_rate"] for c in active)))
        return h, stats, ctx, active, fr

    def _bundle(self, queue_id: int, h: pd.DataFrame, ctx: pe.HistoryContext) -> pe.ModelBundle:
        key = (queue_id, len(h), str(h["arrival"].max()) if len(h) else None, ctx.active_counters,
               round(ctx.nominal_total_rate_per_min, 6))
        if key not in _MODEL_CACHE:
            if len(_MODEL_CACHE) > 64:
                _MODEL_CACHE.clear()
            _MODEL_CACHE[key] = pe.train_and_select(pe.build_dataset(h, ctx))
        return _MODEL_CACHE[key]

    def predict(self, queue_id: int, store: bool = True) -> dict[str, Any]:
        queue = self._queue(queue_id)
        now = utcnow()
        h, stats, ctx, active, fr = self._history(queue_id)
        if ctx.active_counters == 0:
            raise ConflictError("The queue has no active counters, so no finite waiting time can be predicted",
                                "no_active_counters")
        t = np.array([(pd.Timestamp(now) - pe.EPOCH).total_seconds()])
        feats = pe.compute_features(h, t, ctx).iloc[0].to_dict()
        obs = _num(feats.get("observed_mean_service_s"))
        inputs = pe.BaselineInputs(
            queue_length=int(feats["queue_ahead"]), active_counters=ctx.active_counters,
            busy_counters=int(feats["busy_counters"]), counter_rates_per_min=[c["service_rate"] for c in active],
            observed_mean_service_s=obs, observed_service_samples=int(feats["observed_service_samples"]),
            arrival_rate_per_min=_num(feats.get("arrival_rate_per_min")),
        )
        try:
            base = pe.baseline_wait(inputs)
        except pe.PredictionInputError as exc:
            raise UnprocessableError("Prediction inputs are invalid", "invalid_prediction_inputs", exc.problems)
        except pe.PredictionUnavailable as exc:
            raise ConflictError(str(exc), "no_active_counters")
        bundle = self._bundle(queue_id, h, ctx)
        row = {k: _num(v) if k in pe.FEATURES else v for k, v in feats.items()}
        row["baseline_wait_s"] = base["waiting_time_s"]
        result = pe.predict(row, bundle)
        features = {k: row.get(k) for k in pe.FEATURES}
        assumptions = [
            "Prediction is for a customer who joins this queue right now and is served first-come-first-served.",
            f"Service speed source: {base['service_time_source'].replace('_', ' ')}.",
            "Active counters are assumed to stay active and keep their current service speed during the wait.",
            "Expected service time is memoryless-in-the-mean (first-moment approximation); no new arrivals can overtake.",
        ]
        details = {"uncertainty": result["uncertainty"], "assumptions": assumptions, "notes": result["notes"],
                   "baseline": base, "model_training": bundle.report, "history": stats}
        out = {
            "queue_id": queue_id, "prediction_id": None, "predicted_waiting_time_s": result["predicted_waiting_time_s"],
            "predicted_waiting_time_min": result["predicted_waiting_time_s"] / 60.0,
            "prediction_method": result["method"], "prediction_timestamp": now,
            "baseline_waiting_time_s": result["baseline_waiting_time_s"],
            "input_features": features, "queue_state": {
                "queue_length": inputs.queue_length, "active_counters": inputs.active_counters,
                "busy_counters": inputs.busy_counters, "arrival_rate_per_min": inputs.arrival_rate_per_min,
                "observed_mean_service_s": obs, "hour_of_day_utc": now.hour},
            "uncertainty": result["uncertainty"], "assumptions": assumptions, "notes": result["notes"],
            "model": {"selected": bundle.method, "training": bundle.report},
            "is_synthetic": queue.is_synthetic,
        }
        if store:
            rec = PredictionRecord(
                queue_id=queue_id, predicted_waiting_time=result["predicted_waiting_time_s"],
                prediction_method=result["method"], prediction_timestamp=now, input_features=json_safe(features),
                details=json_safe(details), is_synthetic=queue.is_synthetic)
            self.db.add(rec)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            out["prediction_id"] = rec.id
        return json_safe(out)

    def list_predictions(self, queue_id: int, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        self._queue(queue_id)
        rows = self.db.scalars(select(PredictionRecord).where(PredictionRecord.queue_id == queue_id)
                               .order_by(PredictionRecord.id.desc()).limit(limit).offset(offset)).all()
        return [self.record_dict(r) for r in rows]

    @staticmethod
    def record_dict(r: PredictionRecord) -> dict[str, Any]:
        err = None if r.actual_waiting_time is None else r.predicted_waiting_time - r.actual_waiting_time
        return json_safe({
            "prediction_id": r.id, "queue_id": r.queue_id, "predicted_waiting_time_s": r.predicted_waiting_time,
            "actual_waiting_time_s": r.actual_waiting_time, "error_s": err,
            "absolute_error_s": None if err is None else abs(err), "prediction_method": r.prediction_method,
            "prediction_timestamp": r.prediction_timestamp, "evaluated_at": r.evaluated_at,
            "matched_entry_id": r.matched_entry_id, "is_synthetic": r.is_synthetic})

    def evaluate(self, queue_id: int, mode: str = "stored", prediction_ids: list[int] | None = None,
                 actuals: list[dict] | None = None, max_match_gap_seconds: float = 900.0) -> dict[str, Any]:
        queue = self._queue(queue_id)
        notes: list[str] = []
        out: dict[str, Any] = {"queue_id": queue_id, "mode": mode, "evaluated_at": utcnow(),
                               "is_synthetic": queue.is_synthetic, "units": "seconds"}
        if mode == "backtest":
            h, stats, ctx, _, _ = self._history(queue_id)
            ds = pe.build_dataset(h, ctx)
            bundle = pe.train_and_select(ds)
            y = ds["actual_wait_s"].to_numpy(float)
            out["backtest"] = {
                "usable_samples": int(len(ds)), "history": stats, "training_report": bundle.report,
                "baseline_metrics_all_history": pe.error_metrics(y, ds["baseline_wait_s"].to_numpy(float)),
                "note": ("Metrics under training_report.validation_metrics were measured on the newest 30% of "
                         "history, which no model saw during fitting. If status is not 'trained', no ML model "
                         "exists and only baseline errors are reported."),
            }
            return json_safe(out)
        stmt = select(PredictionRecord).where(PredictionRecord.queue_id == queue_id)
        if prediction_ids:
            stmt = stmt.where(PredictionRecord.id.in_(prediction_ids))
        preds = list(self.db.scalars(stmt.order_by(PredictionRecord.id)).all())
        manual = {int(a["prediction_id"]): float(a["actual_waiting_time_s"]) for a in (actuals or [])}
        unknown = set(manual) - {p.id for p in preds}
        if unknown:
            raise UnprocessableError(f"actuals refer to predictions not in this queue/selection: {sorted(unknown)}",
                                     "unknown_prediction_ids")
        now = utcnow()
        unresolved = 0
        try:
            for p in preds:
                if p.id in manual:
                    p.actual_waiting_time, p.evaluated_at = manual[p.id], now
                    continue
                if p.actual_waiting_time is not None:
                    continue
                e = self.db.scalars(select(QueueEntry).where(
                    QueueEntry.queue_id == queue_id, QueueEntry.arrival_time >= p.prediction_timestamp,
                    QueueEntry.service_start_time.is_not(None)).order_by(QueueEntry.arrival_time).limit(1)).first()
                if e is None or (e.arrival_time - p.prediction_timestamp).total_seconds() > max_match_gap_seconds:
                    unresolved += 1
                    continue
                p.actual_waiting_time = (e.service_start_time - e.arrival_time).total_seconds()
                p.matched_entry_id, p.evaluated_at = e.id, now
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        done = [p for p in preds if p.actual_waiting_time is not None]
        out["matching_rule"] = ("A prediction is compared with the wait of the first customer who joined after it "
                                f"was made and started service, if that customer arrived within {max_match_gap_seconds:g}s; "
                                "the customer is not exactly the one predicted for, so conditions may differ slightly.")
        out["metrics"] = pe.error_metrics([p.actual_waiting_time for p in done], [p.predicted_waiting_time for p in done])
        out["by_method"] = {}
        for m in sorted({p.prediction_method for p in done}):
            sub = [p for p in done if p.prediction_method == m]
            out["by_method"][m] = pe.error_metrics([p.actual_waiting_time for p in sub],
                                                   [p.predicted_waiting_time for p in sub])
        out["predictions_considered"] = len(preds)
        out["predictions_evaluated"] = len(done)
        out["predictions_unresolved"] = len(preds) - len(done)
        if not done:
            notes.append("No prediction has an observed outcome yet, so no accuracy figures exist. "
                         "Metrics are null rather than estimated.")
        elif len(done) < 30:
            notes.append(f"Only {len(done)} evaluated predictions; error metrics are indicative, not reliable.")
        out["predictions"] = [self.record_dict(p) for p in done[-200:]]
        out["notes"] = notes
        return json_safe(out)
