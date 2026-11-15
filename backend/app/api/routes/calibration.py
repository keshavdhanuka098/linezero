"""Adaptive calibration of the Digital Twin: versioned parameters, validation, drift, rollback, error tracking."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.adaptive import (
    CalibrationEvaluateRequest, CalibrationRollbackRequest, CalibrationRunRequest,
)
from app.schemas.common import ErrorResponse
from app.services.calibration_service import CalibrationService

router = APIRouter(prefix="/calibration", tags=["adaptive-calibration"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.get("/{queue_id}/status", responses=ERR)
def status(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Active calibration, data sufficiency, nominal parameters, drift summary and data provenance."""
    return CalibrationService(db).status(queue_id)


@router.post("/{queue_id}/run", responses=ERR)
def run(queue_id: int, payload: CalibrationRunRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Fit a candidate on a chronological training window, validate it on the held-out latest customers, accept it only
    if it beats the incumbent, and store it as a new version. `dry_run` saves nothing."""
    return CalibrationService(db).run(queue_id, payload or CalibrationRunRequest())


@router.get("/{queue_id}/versions", responses=ERR)
def versions(queue_id: int, include_rejected: bool = Query(default=True), db: Session = Depends(get_db)) -> dict[str, Any]:
    return CalibrationService(db).versions(queue_id, include_rejected)


@router.post("/{queue_id}/rollback", responses=ERR)
def rollback(queue_id: int, payload: CalibrationRollbackRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Restore an earlier version's parameters as a NEW active version (history is never rewritten)."""
    return CalibrationService(db).rollback(queue_id, payload)


@router.get("/{queue_id}/drift", responses=ERR)
def drift(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Arrival-rate, service-time and waiting-time drift between the calibrated reference window and recent data."""
    return CalibrationService(db).drift(queue_id)


@router.get("/{queue_id}/evaluation", responses=ERR)
def evaluation(queue_id: int, scope: str = Query(default="new_data", pattern="^(new_data|all)$"),
               db: Session = Depends(get_db)) -> dict[str, Any]:
    """Predicted vs actual waiting times (MAE, RMSE, MAPE) for the active and the nominal model. Stores nothing."""
    return CalibrationService(db).evaluate(queue_id, CalibrationEvaluateRequest(scope=scope), store=False)  # type: ignore[arg-type]


@router.post("/{queue_id}/evaluation", responses=ERR)
def store_evaluation(queue_id: int, payload: CalibrationEvaluateRequest | None = None,
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    """Same as GET but saves the error snapshot so error can be tracked over time."""
    return CalibrationService(db).evaluate(queue_id, payload or CalibrationEvaluateRequest(), store=True)


@router.get("/{queue_id}/error-history", responses=ERR)
def error_history(queue_id: int, limit: int = Query(default=200, ge=1, le=1000),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """Stored evaluation snapshots, oldest first."""
    return CalibrationService(db).error_history(queue_id, limit)
