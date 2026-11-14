from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ErrorResponse
from app.schemas.simulation import (
    SimulationCompareOut, SimulationCompareRequest, SimulationResetOut, SimulationRunOut, SimulationRunRequest,
)
from app.services.simulation_service import SimulationService

router = APIRouter(prefix="/simulations", tags=["simulations"])
NOT_FOUND = {404: {"model": ErrorResponse}}


def get_service(db: Session = Depends(get_db)) -> SimulationService:
    return SimulationService(db)


@router.post("/run", response_model=SimulationRunOut, status_code=status.HTTP_201_CREATED)
def run_simulation(payload: SimulationRunRequest, svc: SimulationService = Depends(get_service)):
    return svc.run(payload.name, payload.configuration)


@router.post("/compare", response_model=SimulationCompareOut, status_code=status.HTTP_201_CREATED)
def compare_simulations(payload: SimulationCompareRequest, svc: SimulationService = Depends(get_service)):
    return svc.compare(payload)


@router.get("", response_model=list[SimulationRunOut])
def list_simulations(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    comparison_id: str | None = None,
    svc: SimulationService = Depends(get_service),
):
    return svc.list(limit, offset, comparison_id)


@router.delete("", response_model=SimulationResetOut)
def reset_simulations(svc: SimulationService = Depends(get_service)):
    """Reset simulation state: remove all stored simulation runs."""
    return SimulationResetOut(deleted=svc.reset())


@router.get("/{simulation_id}", response_model=SimulationRunOut, responses=NOT_FOUND)
def get_simulation(simulation_id: int, svc: SimulationService = Depends(get_service)):
    return svc.get(simulation_id)


@router.delete("/{simulation_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
def delete_simulation(simulation_id: int, svc: SimulationService = Depends(get_service)):
    svc.delete(simulation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
