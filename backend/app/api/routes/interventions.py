"""Autonomous intervention engine: simulate and rank interventions; operators approve, apply and review them."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.adaptive import AppliedRequest, DecisionRequest, InterventionEvaluateRequest, OutcomeRequest
from app.schemas.common import ErrorResponse
from app.services.intervention_service import InterventionService

router = APIRouter(prefix="/interventions", tags=["autonomous-interventions"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.post("/{queue_id}/evaluate", responses=ERR)
def evaluate(queue_id: int, payload: InterventionEvaluateRequest | None = None,
             db: Session = Depends(get_db)) -> dict[str, Any]:
    """Simulate the unchanged queue and every feasible candidate with common random numbers, price them, rank them.
    Simulation only: nothing is executed. With persist=true the candidates are stored as 'proposed'."""
    return InterventionService(db).evaluate(queue_id, payload or InterventionEvaluateRequest())


@router.get("/{queue_id}/history", responses=ERR)
def history(queue_id: int, status: str | None = Query(default=None, pattern="^(proposed|approved|rejected|applied|evaluated)$"),
            limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict[str, Any]:
    return InterventionService(db).history(queue_id, status, limit)


@router.get("/item/{intervention_id}", responses=ERR)
def get_one(intervention_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return InterventionService(db).get(intervention_id)


@router.post("/item/{intervention_id}/approve", responses=ERR)
def approve(intervention_id: int, payload: DecisionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Operator approval. Changes nothing in the real queue."""
    return InterventionService(db).approve(intervention_id, payload)


@router.post("/item/{intervention_id}/reject", responses=ERR)
def reject(intervention_id: int, payload: DecisionRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return InterventionService(db).reject(intervention_id, payload)


@router.post("/item/{intervention_id}/applied", responses=ERR)
def applied(intervention_id: int, payload: AppliedRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """The operator confirms they carried the approved change out in the real world."""
    return InterventionService(db).mark_applied(intervention_id, payload)


@router.post("/item/{intervention_id}/outcome", responses=ERR)
def outcome(intervention_id: int, payload: OutcomeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Evaluate an applied intervention: measure before/after windows from the database ('observe') or store figures
    an operator reports ('manual'). The result carries a verification label."""
    return InterventionService(db).record_outcome(intervention_id, payload)


@router.get("/{queue_id}/learning", responses=ERR)
def learning(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Expected vs observed results of past interventions, kept apart by verification label."""
    return InterventionService(db).learning(queue_id)
