from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.routes.queues import ERR, get_service
from app.models.enums import CounterStatus
from app.schemas.counter import CounterCreate, CounterOut, CounterUpdate
from app.services.queue_service import QueueService

router = APIRouter(prefix="/counters", tags=["counters"])


@router.get("", response_model=list[CounterOut])
def list_counters(
    queue_id: int | None = Query(default=None, gt=0),
    status_: CounterStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    svc: QueueService = Depends(get_service),
):
    return svc.list_counters(queue_id, status_, limit, offset)


@router.post("", response_model=CounterOut, status_code=status.HTTP_201_CREATED, responses=ERR)
def create_counter(payload: CounterCreate, svc: QueueService = Depends(get_service)):
    return svc.create_counter(payload)


@router.get("/{counter_id}", response_model=CounterOut, responses=ERR)
def get_counter(counter_id: int, svc: QueueService = Depends(get_service)):
    return svc.get_counter(counter_id)


@router.patch("/{counter_id}", response_model=CounterOut, responses=ERR)
def update_counter(counter_id: int, payload: CounterUpdate, svc: QueueService = Depends(get_service)):
    return svc.update_counter(counter_id, payload)


@router.post("/{counter_id}/pause", response_model=CounterOut, responses=ERR)
def pause_counter(counter_id: int, svc: QueueService = Depends(get_service)):
    return svc.pause_counter(counter_id)


@router.post("/{counter_id}/resume", response_model=CounterOut, responses=ERR)
def resume_counter(counter_id: int, svc: QueueService = Depends(get_service)):
    return svc.resume_counter(counter_id)
