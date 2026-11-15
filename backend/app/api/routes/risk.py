"""Predictive operational risk detection with explainable scores."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.adaptive import DecisionRequest, RiskScanRequest
from app.schemas.common import ErrorResponse
from app.services.risk_service import RiskService

router = APIRouter(prefix="/risk", tags=["operational-risk"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.get("/{queue_id}/assess", responses=ERR)
def assess(queue_id: int, wait_sla_min: float = Query(default=10.0, gt=0, le=1440),
           forecast_replications: int = Query(default=20, ge=5, le=100), seed: int = Query(default=2026, ge=0),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    """Score all seven risk categories now. Read-only: stores nothing."""
    return RiskService(db).assess(queue_id, RiskScanRequest(wait_sla_min=wait_sla_min, seed=seed,
                                                            forecast_replications=forecast_replications, persist=False))


@router.post("/{queue_id}/scan", responses=ERR)
def scan(queue_id: int, payload: RiskScanRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Assess and (by default) store or refresh risk events; open events no longer detected are marked resolved."""
    return RiskService(db).scan(queue_id, payload or RiskScanRequest())


@router.get("/{queue_id}/events", responses=ERR)
def events(queue_id: int, status: str = Query(default="all", pattern="^(open|resolved|all)$"),
           limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, Any]:
    return RiskService(db).events(queue_id, status, limit)


@router.post("/events/{event_id}/resolve", responses=ERR)
def resolve(event_id: int, payload: DecisionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return RiskService(db).resolve(event_id, payload)
