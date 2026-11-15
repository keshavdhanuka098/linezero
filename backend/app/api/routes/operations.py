"""The closed operations loop: status of every stage and one call that advances the automatic ones."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.adaptive import CycleRequest
from app.schemas.common import ErrorResponse
from app.services.operations_service import OperationsService

router = APIRouter(prefix="/operations", tags=["operations-loop"])
ERR = {404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.get("/{queue_id}/overview", responses=ERR)
def overview(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return OperationsService(db).overview(queue_id)


@router.post("/{queue_id}/cycle", responses=ERR)
def cycle(queue_id: int, payload: CycleRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Recalibrate (if validated), scan risks, simulate interventions for the worst risk. Never approves or applies."""
    return OperationsService(db).cycle(queue_id, payload or CycleRequest())
