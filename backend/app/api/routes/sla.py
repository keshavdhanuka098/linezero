"""SLA & Customer Experience Intelligence: targets, live customer risk, compliance, recommended interventions."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ErrorResponse
from app.schemas.sla import EntryClassRequest, SlaPolicyIn, SlaRecommendRequest
from app.services.sla_service import SlaService

router = APIRouter(prefix="/sla", tags=["sla-intelligence"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


@router.get("/summary", responses=ERR)
def summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every queue: whether an SLA is configured, current compliance and how many waiting customers are at risk."""
    return SlaService(db).summary()


@router.get("/{queue_id}/policies", responses=ERR)
def list_policies(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return SlaService(db).list_policies(queue_id)


@router.put("/{queue_id}/policies/{service_class}", responses=ERR)
def upsert_policy(queue_id: int, service_class: str, payload: SlaPolicyIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Create or update the SLA target for a service class ('standard' must exist first)."""
    return SlaService(db).upsert_policy(queue_id, service_class, payload)


@router.delete("/{queue_id}/policies/{service_class}", responses=ERR)
def delete_policy(queue_id: int, service_class: str, operator: str = Query(min_length=1, max_length=120),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    return SlaService(db).delete_policy(queue_id, service_class, operator)


@router.post("/{queue_id}/entries/{entry_id}/class", responses=ERR)
def set_entry_class(queue_id: int, entry_id: int, payload: EntryClassRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Assign a waiting customer to a service class (must have a policy on this queue)."""
    return SlaService(db).set_entry_class(queue_id, entry_id, payload)


@router.get("/{queue_id}/monitor", responses=ERR)
def monitor(queue_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Every waiting customer with current wait, predicted total wait, SLA target, remaining time, breach probability."""
    return SlaService(db).monitor(queue_id)


@router.get("/{queue_id}/performance", responses=ERR)
def performance(queue_id: int, window_minutes: float = Query(default=60.0), lookback_hours: float = Query(default=24.0),
                bucket_minutes: float = Query(default=60.0), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Compliance score (current / historical / overall observed, predicted for customers waiting now), KPIs, trend."""
    return SlaService(db).performance(queue_id, window_minutes, lookback_hours, bucket_minutes)


@router.post("/{queue_id}/recommendations", responses=ERR)
def recommendations(queue_id: int, payload: SlaRecommendRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    """If customers are at risk: why, and simulated interventions with expected wait reductions (simulation only)."""
    return SlaService(db).recommendations(queue_id, payload or SlaRecommendRequest())
