"""Calibration service: loads observations, runs the calibration/drift engines, persists versioned results.

Versioning rules
  * Every accepted calibration or rollback becomes a NEW row with the next per-queue version number; history is
    append-only. The previously active row is flipped to 'superseded', never edited otherwise.
  * Candidates that fail validation are stored as 'rejected' (no version) so the audit trail explains why nothing changed.
  * A partial unique index guarantees at most one active row per queue.
  * Real queue data is only ever READ here; nothing writes to queues, counters or entries.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import calibration_engine as ce
from app.engines import drift_detection_engine as dd
from app.engines import prediction_engine as pe
from app.engines.operations_intelligence import dt_to_epoch, epoch_to_dt, provenance
from app.models import (
    CalibrationEvaluation, CalibrationRecord, CalibrationSource, CalibrationStatus, InterventionHistory,
    InterventionStatus, Queue, utcnow,
)
from app.schemas.adaptive import CalibrationEvaluateRequest, CalibrationRollbackRequest, CalibrationRunRequest
from app.services.data_access import load_frames

logger = logging.getLogger("linezero.calibration")
MAX_HISTORY_ROWS = 20000
#: intervention types that deliberately change demand; their windows must not inform the arrival-rate estimate
DEMAND_CHANGING = ("redistribute_traffic",)


class CalibrationService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ loading
    def _queue(self, queue_id: int) -> Queue:
        q = self.db.get(Queue, queue_id)
        if q is None:
            raise NotFoundError(f"Queue {queue_id} not found", "queue_not_found")
        return q

    def observations(self, queue_id: int):
        """(queue, history frame, counters, frames). History is read-only and capped to the newest rows."""
        queue = self._queue(queue_id)
        fr = load_frames(self.db, queue_id=queue_id)
        h, _stats = pe.prepare_history(fr.entries.tail(MAX_HISTORY_ROWS))
        return queue, h, fr.counters, fr

    def active_record(self, queue_id: int) -> CalibrationRecord | None:
        return self.db.scalars(select(CalibrationRecord).where(
            CalibrationRecord.queue_id == queue_id, CalibrationRecord.status == CalibrationStatus.ACTIVE.value)).first()

    def _next_version(self, queue_id: int) -> int:
        cur = self.db.scalar(select(func.max(CalibrationRecord.version)).where(CalibrationRecord.queue_id == queue_id))
        return (cur or 0) + 1

    def exclusion_windows(self, queue_id: int) -> tuple[tuple[float, float], ...]:
        """Windows during which an operator-applied demand-changing intervention was in force. Arrivals inside them
        reflect the intervention, not natural demand, so they are not used to learn the arrival rate."""
        rows = self.db.scalars(select(InterventionHistory).where(
            InterventionHistory.queue_id == queue_id,
            InterventionHistory.intervention_type.in_(DEMAND_CHANGING),
            InterventionHistory.status.in_([InterventionStatus.APPLIED.value, InterventionStatus.EVALUATED.value]),
            InterventionHistory.applied_at.is_not(None))).all()
        wins = []
        for r in rows:
            start = dt_to_epoch(r.applied_at)
            minutes = float((r.simulation_meta or {}).get("horizon_min", 60.0))
            if r.outcome and r.outcome.get("window_minutes"):
                minutes = float(r.outcome["window_minutes"])
            wins.append((start, start + minutes * 60.0))
        return tuple(wins)

    # ------------------------------------------------------------------ serialisation
    @staticmethod
    def record_dict(r: CalibrationRecord, detail: bool = False) -> dict[str, Any]:
        out = {
            "id": r.id, "queue_id": r.queue_id, "version": r.version, "status": r.status, "source": r.source,
            "decision": r.decision, "reason": r.reason, "parameters": r.parameters, "confidence": r.confidence,
            "created_at": r.created_at, "is_synthetic": r.is_synthetic, "incumbent_version": r.incumbent_version,
            "rollback_to_version": r.rollback_to_version,
            "training_window": {"start": r.training_start, "end": r.training_end},
            "validation_window": {"start": r.validation_start, "end": r.validation_end},
            "n_train_arrivals": r.n_train_arrivals, "n_train_services": r.n_train_services,
            "n_validation": r.n_validation, "candidate_metrics": r.candidate_metrics,
            "incumbent_metrics": r.incumbent_metrics,
            "mae_improvement_pct": (r.comparison or {}).get("mae_improvement_pct"),
        }
        if detail:
            out.update({"estimates": r.estimates, "settings": r.settings, "comparison": r.comparison,
                        "drift": r.drift, "confidence_detail": r.confidence_detail})
        return json_safe(out)

    # ------------------------------------------------------------------ status
    def status(self, queue_id: int) -> dict[str, Any]:
        queue, h, counters, fr = self.observations(queue_id)
        active = self.active_record(queue_id)
        served = int(h["start"].notna().sum()) if len(h) else 0
        needed = ce.MIN_TRAIN_SERVICES + ce.MIN_VALIDATION
        n_versions = self.db.scalar(select(func.count()).select_from(CalibrationRecord).where(
            CalibrationRecord.queue_id == queue_id, CalibrationRecord.version.is_not(None))) or 0
        n_rejected = self.db.scalar(select(func.count()).select_from(CalibrationRecord).where(
            CalibrationRecord.queue_id == queue_id, CalibrationRecord.status == CalibrationStatus.REJECTED.value)) or 0
        try:
            drift = self._drift(queue_id, queue, h, active)
        except ValueError as exc:  # windows could not be formed
            drift = {"status": "insufficient_data", "drift_detected": False, "note": str(exc)}
        return json_safe({
            "queue": {"id": queue.id, "name": queue.name, "is_synthetic": queue.is_synthetic},
            "provenance": provenance(queue.is_synthetic or fr.contains_synthetic),
            "observations": {
                "rows": int(len(h)), "served": served, "needed_for_calibration": needed, "ready": served >= needed,
                "first_arrival": None if not len(h) else h["arrival"].min(),
                "last_arrival": None if not len(h) else h["arrival"].max(),
            },
            "nominal_parameters": ce.nominal_parameters(counters),
            "active": self.record_dict(active, detail=True) if active else None,
            "model": "nominal_configuration" if active is None else f"calibration_v{active.version}",
            "versions": n_versions, "rejected_candidates": n_rejected,
            "drift": {k: drift.get(k) for k in ("status", "drift_detected", "severity", "drifted_signals", "note")},
        })

    # ------------------------------------------------------------------ run
    def run(self, queue_id: int, req: CalibrationRunRequest) -> dict[str, Any]:
        queue, h, counters, fr = self.observations(queue_id)
        active = self.active_record(queue_id)
        settings = ce.CalibrationSettings(
            validation_fraction=req.validation_fraction, min_improvement_pct=req.min_improvement_pct,
            prior_arrival_minutes=req.prior_arrival_minutes, prior_service_pseudo_n=req.prior_service_pseudo_n,
            lookback_minutes=req.lookback_minutes, exclude_arrival_windows=self.exclusion_windows(queue_id))
        try:
            res = ce.calibrate(h, counters, active.parameters if active else None, settings)
        except ValueError as exc:
            raise UnprocessableError(str(exc), "invalid_calibration_request")
        try:
            drift = self._drift(queue_id, queue, h, active)
        except ValueError:
            drift = None
        synthetic = bool(queue.is_synthetic or fr.contains_synthetic)
        prov = provenance(synthetic)
        base = {"queue_id": queue_id, "provenance": prov, "persisted": False, "drift": drift, "result": res,
                "previous_version": active.version if active else None, "record": None}
        if res["decision"] == "insufficient_data":
            return json_safe({**base, "decision": "insufficient_data", "reasons": res["reasons"]})
        if req.dry_run:
            return json_safe({**base, "decision": res["decision"], "reasons": res["reasons"], "dry_run": True})

        w = res["windows"]
        comparison = {k: res.get(k) for k in (
            "paired_abs_error_diff_s", "mae_improvement_pct", "candidate_capacity_per_min",
            "incumbent_capacity_per_min", "series", "binned_errors", "uncertainty", "limitations", "reasons",
            "incumbent_label")}
        rec = CalibrationRecord(
            queue_id=queue_id, status=CalibrationStatus.REJECTED.value, source=CalibrationSource.CALIBRATION.value,
            parameters=json_safe(res["candidate_parameters"]), estimates=json_safe(res["estimates"]),
            settings=json_safe(res["settings"]), training_start=epoch_to_dt(w["training_start_s"]),
            training_end=epoch_to_dt(w["training_end_s"]), validation_start=epoch_to_dt(w["validation_start_s"]),
            validation_end=epoch_to_dt(w["validation_end_s"]), n_train_arrivals=res.get("n_train_arrivals"),
            n_train_services=res.get("n_train_services"), n_validation=res.get("n_validation"),
            candidate_metrics=json_safe(res["candidate_metrics"]), incumbent_metrics=json_safe(res["incumbent_metrics"]),
            comparison=json_safe(comparison), drift=json_safe(drift), decision=res["decision"],
            reason=" ".join(res["reasons"]), confidence=res["confidence"]["value"],
            confidence_detail=json_safe(res["confidence"]), incumbent_version=active.version if active else None,
            is_synthetic=synthetic)
        try:
            if res["accepted"]:
                if active is not None:
                    active.status = CalibrationStatus.SUPERSEDED.value
                    self.db.flush()  # free the unique "one active" slot before inserting the new row
                rec.status, rec.version = CalibrationStatus.ACTIVE.value, self._next_version(queue_id)
            self.db.add(rec)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return json_safe({**base, "persisted": True, "decision": res["decision"], "reasons": res["reasons"],
                          "record": self.record_dict(rec, detail=True)})

    # ------------------------------------------------------------------ versions / rollback
    def versions(self, queue_id: int, include_rejected: bool = True) -> dict[str, Any]:
        queue = self._queue(queue_id)
        stmt = select(CalibrationRecord).where(CalibrationRecord.queue_id == queue_id)
        if not include_rejected:
            stmt = stmt.where(CalibrationRecord.status != CalibrationStatus.REJECTED.value)
        rows = self.db.scalars(stmt.order_by(CalibrationRecord.id.desc())).all()
        return {"queue_id": queue_id, "provenance": provenance(queue.is_synthetic),
                "versions": [self.record_dict(r, detail=True) for r in rows]}

    def rollback(self, queue_id: int, req: CalibrationRollbackRequest) -> dict[str, Any]:
        queue = self._queue(queue_id)
        target = self.db.scalars(select(CalibrationRecord).where(
            CalibrationRecord.queue_id == queue_id, CalibrationRecord.version == req.version,
            CalibrationRecord.status != CalibrationStatus.REJECTED.value)).first()
        if target is None:
            raise NotFoundError(f"Calibration version {req.version} does not exist for queue {queue_id}",
                                "calibration_version_not_found")
        active = self.active_record(queue_id)
        if active is not None and active.id == target.id:
            raise ConflictError(f"Version {req.version} is already the active calibration", "already_active")
        rec = CalibrationRecord(
            queue_id=queue_id, status=CalibrationStatus.ACTIVE.value, source=CalibrationSource.ROLLBACK.value,
            parameters=dict(target.parameters), estimates=target.estimates, settings=target.settings,
            training_start=target.training_start, training_end=target.training_end,
            validation_start=target.validation_start, validation_end=target.validation_end,
            n_train_arrivals=target.n_train_arrivals, n_train_services=target.n_train_services,
            n_validation=target.n_validation, candidate_metrics=target.candidate_metrics,
            incumbent_metrics=target.incumbent_metrics, comparison=target.comparison, decision="rollback",
            reason=f"Rolled back to version {req.version} by {req.operator}: {req.reason}",
            confidence=target.confidence, confidence_detail=target.confidence_detail,
            incumbent_version=active.version if active else None, rollback_to_version=target.version,
            is_synthetic=queue.is_synthetic or target.is_synthetic)
        try:
            if active is not None:
                active.status = CalibrationStatus.SUPERSEDED.value
                self.db.flush()
            rec.version = self._next_version(queue_id)
            self.db.add(rec)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"queue_id": queue_id, "provenance": provenance(queue.is_synthetic),
                "restored_from_version": target.version, "record": self.record_dict(rec, detail=True)}

    # ------------------------------------------------------------------ drift
    def _drift(self, queue_id: int, queue: Queue, h: pd.DataFrame, active: CalibrationRecord | None) -> dict[str, Any]:
        ref_end = dt_to_epoch(active.training_end) if active is not None and active.training_end else None
        wins = dd.default_windows(h, ref_end)
        if wins is None:
            raise ValueError("Not enough history to form a reference and a recent window")
        out = dd.detect_drift(h, *wins)
        out["reference_basis"] = ("training window of the active calibration" if ref_end is not None
                                  and wins[0][1] == ref_end else "first 60% of observed history (no calibration yet)")
        return out

    def drift(self, queue_id: int) -> dict[str, Any]:
        queue, h, _c, fr = self.observations(queue_id)
        active = self.active_record(queue_id)
        try:
            d = self._drift(queue_id, queue, h, active)
        except ValueError as exc:
            d = {"status": "insufficient_data", "drift_detected": False, "severity": None, "signals": {},
                 "note": str(exc)}
        return json_safe({"queue_id": queue_id, "provenance": provenance(queue.is_synthetic or fr.contains_synthetic),
                          "active_version": active.version if active else None, **d})

    # ------------------------------------------------------------------ evaluation of predictions vs actuals
    def evaluate(self, queue_id: int, req: CalibrationEvaluateRequest, store: bool) -> dict[str, Any]:
        queue, h, counters, fr = self.observations(queue_id)
        active = self.active_record(queue_id)
        synthetic = bool(queue.is_synthetic or fr.contains_synthetic)
        n_active = sum(1 for c in counters if c["status"] == "active")
        nominal = ce.nominal_parameters(counters)
        evf = ce.build_eval_frame(h, n_active, sum(c["service_rate"] for c in counters if c["status"] == "active"))
        notes: list[str] = []
        out: dict[str, Any] = {
            "queue_id": queue_id, "provenance": provenance(synthetic), "scope": req.scope,
            "active_version": active.version if active else None, "units": "seconds (series in minutes)",
            "stored": False, "n": 0, "calibrated": None, "nominal": None, "series": [], "binned_errors": [],
            "out_of_sample": None, "notes": notes,
        }
        if n_active == 0:
            notes.append("No active counters: waits cannot be modelled.")
            return json_safe(out)
        sub = evf
        out_of_sample = False
        if req.scope == "new_data" and active is not None and active.training_end is not None:
            cutoff = dt_to_epoch(active.training_end)
            sub = evf[evf["arrival_s"] > cutoff].reset_index(drop=True)
            out_of_sample = True
            if len(sub) == 0:
                notes.append("No customers have been observed since the active calibration's training window ended.")
            elif (active.validation_end is not None and len(sub)
                  and abs(dt_to_epoch(active.validation_end) - float(sub["arrival_s"].max())) < 1e-6):
                notes.append("These customers are the same ones the acceptance decision was validated on; record "
                             "new observations and evaluate again for a fresh out-of-sample check.")
        elif active is None:
            notes.append("No calibration is active; only the nominal (configured) model is evaluated, on all "
                         "history, which it was never fitted to.")
            out_of_sample = True
        else:
            notes.append("Scope 'all' includes the calibration's own training data, so the calibrated figures are "
                         "in-sample and optimistic.")
        out["out_of_sample"] = out_of_sample
        out["n"] = int(len(sub))
        if len(sub) == 0:
            return json_safe(out)
        if len(sub) < ce.MIN_VALIDATION:
            notes.append(f"Only {len(sub)} customers; error metrics are indicative, not reliable.")
        nom_eval = ce.evaluate_model(nominal, sub, counters)
        out["nominal"] = nom_eval["metrics"]
        pred_for_series = nom_eval["predicted_s"]
        cal_eval = None
        if active is not None:
            cal_eval = ce.evaluate_model(active.parameters, sub, counters)
            out["calibrated"] = cal_eval["metrics"]
            pred_for_series = cal_eval["predicted_s"]
        out["series"] = ce.downsample_series(sub, pred_for_series, nom_eval["predicted_s"] if cal_eval else None)
        out["binned_errors"] = ce.binned_errors(sub, pred_for_series)
        if cal_eval is not None and nom_eval["metrics"]["mae_s"]:
            out["mae_improvement_vs_nominal_pct"] = (
                (nom_eval["metrics"]["mae_s"] - cal_eval["metrics"]["mae_s"]) / nom_eval["metrics"]["mae_s"] * 100.0)
        window_start, window_end = epoch_to_dt(float(sub["arrival_s"].min())), epoch_to_dt(float(sub["arrival_s"].max()))
        out["window"] = {"start": window_start, "end": window_end}
        if store:
            now = utcnow()
            rows = [CalibrationEvaluation(
                queue_id=queue_id, calibration_id=None, model_label="nominal", version=None, evaluated_at=now,
                window_start=window_start, window_end=window_end, n=int(len(sub)), mae_s=nom_eval["metrics"]["mae_s"],
                rmse_s=nom_eval["metrics"]["rmse_s"], mape_pct=nom_eval["metrics"]["mape_pct"],
                mean_error_s=nom_eval["metrics"]["mean_error_s"], out_of_sample=out_of_sample, is_synthetic=synthetic)]
            if cal_eval is not None:
                m = cal_eval["metrics"]
                rows.append(CalibrationEvaluation(
                    queue_id=queue_id, calibration_id=active.id, model_label="calibrated", version=active.version,
                    evaluated_at=now, window_start=window_start, window_end=window_end, n=int(len(sub)),
                    mae_s=m["mae_s"], rmse_s=m["rmse_s"], mape_pct=m["mape_pct"], mean_error_s=m["mean_error_s"],
                    out_of_sample=out_of_sample, is_synthetic=synthetic))
            try:
                self.db.add_all(rows)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            out["stored"] = True
        return json_safe(out)

    def error_history(self, queue_id: int, limit: int = 200) -> dict[str, Any]:
        queue = self._queue(queue_id)
        rows = self.db.scalars(select(CalibrationEvaluation).where(CalibrationEvaluation.queue_id == queue_id)
                               .order_by(CalibrationEvaluation.evaluated_at.desc(), CalibrationEvaluation.id.desc())
                               .limit(limit)).all()
        return json_safe({
            "queue_id": queue_id, "provenance": provenance(queue.is_synthetic),
            "evaluations": [{"id": r.id, "model": r.model_label, "version": r.version, "evaluated_at": r.evaluated_at,
                             "n": r.n, "mae_s": r.mae_s, "rmse_s": r.rmse_s, "mape_pct": r.mape_pct,
                             "mean_error_s": r.mean_error_s, "out_of_sample": r.out_of_sample,
                             "window_start": r.window_start, "window_end": r.window_end,
                             "is_synthetic": r.is_synthetic} for r in reversed(rows)],
        })

    # ------------------------------------------------------------------ used by risk / intervention services
    def active_parameters(self, queue_id: int) -> dict[str, Any] | None:
        rec = self.active_record(queue_id)
        if rec is None:
            return None
        return {"version": rec.version, "parameters": rec.parameters, "confidence": rec.confidence,
                "created_at": rec.created_at, "is_synthetic": rec.is_synthetic}


__all__ = ["CalibrationService"]
