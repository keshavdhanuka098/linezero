from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import EntryStatus, QueueStatus
from app.schemas.common import ErrorResponse
from app.schemas.entry import AssignRequest, EntryCreate, EntryOut, EntryPosition, ServeNextRequest
from app.schemas.queue import (
    CompleteResult, EventOut, QueueCreate, QueueDetail, QueueOut, QueueState, QueueUpdate, ServeResult,
)
from app.services.queue_service import QueueService

router = APIRouter(prefix="/queues", tags=["queues"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}


def get_service(db: Session = Depends(get_db)) -> QueueService:
    return QueueService(db)


@router.get("", response_model=list[QueueOut])
def list_queues(
    status_: QueueStatus | None = Query(default=None, alias="status"),
    synthetic: bool | None = Query(default=None, description="Filter generated (true) / real (false) queues"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: QueueService = Depends(get_service),
):
    return svc.list_queues(status_, synthetic, limit, offset)


@router.post("", response_model=QueueOut, status_code=status.HTTP_201_CREATED)
def create_queue(payload: QueueCreate, svc: QueueService = Depends(get_service)):
    return svc.create_queue(payload)


@router.get("/{queue_id}", response_model=QueueDetail, responses=ERR)
def get_queue(queue_id: int, svc: QueueService = Depends(get_service)):
    return svc.get_queue(queue_id)


@router.put("/{queue_id}", response_model=QueueOut, responses=ERR)
def update_queue(queue_id: int, payload: QueueUpdate, svc: QueueService = Depends(get_service)):
    return svc.update_queue(queue_id, payload)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERR)
def delete_queue(queue_id: int, svc: QueueService = Depends(get_service)):
    svc.delete_queue(queue_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{queue_id}/state", response_model=QueueState, responses=ERR)
def queue_state(
    queue_id: int, waiting_limit: int = Query(default=100, ge=1, le=1000), svc: QueueService = Depends(get_service)
):
    return svc.get_state(queue_id, waiting_limit)


@router.get("/{queue_id}/events", response_model=list[EventOut], responses=ERR)
def queue_events(
    queue_id: int,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    svc: QueueService = Depends(get_service),
):
    return svc.list_events(queue_id, event_type, limit, offset)


@router.post("/{queue_id}/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED, responses=ERR)
def add_entry(queue_id: int, payload: EntryCreate | None = None, svc: QueueService = Depends(get_service)):
    return svc.add_entry(queue_id, payload.service_class if payload else None)


@router.get("/{queue_id}/entries", response_model=list[EntryOut], responses=ERR)
def list_entries(
    queue_id: int,
    status_: EntryStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    svc: QueueService = Depends(get_service),
):
    return svc.list_entries(queue_id, status_, limit, offset)


@router.post("/{queue_id}/serve-next", response_model=ServeResult, responses=ERR)
def serve_next(
    queue_id: int,
    payload: ServeNextRequest | None = Body(default=None),
    svc: QueueService = Depends(get_service),
):
    return svc.serve_next(queue_id, payload.counter_id if payload else None)


@router.get("/{queue_id}/entries/{entry_id}", response_model=EntryOut, responses=ERR)
def get_entry(queue_id: int, entry_id: int, svc: QueueService = Depends(get_service)):
    return svc.get_entry(queue_id, entry_id)


@router.get("/{queue_id}/entries/{entry_id}/position", response_model=EntryPosition, responses=ERR)
def entry_position(queue_id: int, entry_id: int, svc: QueueService = Depends(get_service)):
    return svc.get_position(queue_id, entry_id)


@router.post("/{queue_id}/entries/{entry_id}/assign", response_model=ServeResult, responses=ERR)
def assign_entry(queue_id: int, entry_id: int, payload: AssignRequest, svc: QueueService = Depends(get_service)):
    return svc.assign_entry(queue_id, entry_id, payload.counter_id)


@router.post("/{queue_id}/entries/{entry_id}/complete", response_model=CompleteResult, responses=ERR)
def complete_entry(queue_id: int, entry_id: int, svc: QueueService = Depends(get_service)):
    return svc.complete_service(queue_id, entry_id)


@router.delete("/{queue_id}/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERR)
def remove_entry(queue_id: int, entry_id: int, svc: QueueService = Depends(get_service)):
    svc.remove_entry(queue_id, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
