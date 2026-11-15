"""Digital Twin endpoints. Reads live queue data; all projections are simulation. Nothing here modifies real queues."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import UnprocessableError
from app.core.jsonutil import json_safe
from app.engines import twin_explain as tx
from app.engines import twin_recovery as tr
from app.engines.twin_engine import TwinConfig, run_replications
from app.engines.twin_scenarios import compare_scenarios, preset_scenarios
from app.schemas.common import ErrorResponse
from app.schemas.twin import (
    TwinCompareRequest, TwinExplainRequest, TwinRecoverRequest, TwinSimulateRequest,
)
from app.services import gemini_service
from app.services.twin_service import TwinService

router = APIRouter(prefix="/twin", tags=["digital-twin"])
ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise UnprocessableError(str(exc), "invalid_twin_request")


@router.get("/status")
def twin_status() -> dict[str, Any]:
    """Capabilities. Never returns the Gemini key."""
    return {"engine": "simpy", "gemini": gemini_service.status(), "horizons_min": [5, 15, 30, 60],
            "max_compare_scenarios": 5, "writes_to_real_queues": False}


@router.get("/presets")
def presets(
    arrival_rate: float = Query(default=1.2, gt=0, le=1000), mean_service_time: float = Query(default=4.0, gt=0, le=240),
    num_counters: int = Query(default=5, ge=1, le=100), duration: float = Query(default=120.0, gt=0, le=1440),
) -> list[dict[str, Any]]:
    """The six predefined scenarios built from a base configuration."""
    base = {"arrival_rate": arrival_rate, "mean_service_time": mean_service_time, "num_counters": num_counters,
            "duration": duration, "abandonment_enabled": False}
    out = preset_scenarios(base)
    for p in out:  # fail early if a preset would be invalid for these parameters
        _guard(TwinConfig.model_validate, p["configuration"])
    return out


@router.get("/live/{queue_id}", responses=ERR)
def live(queue_id: int, db: Session = Depends(get_db)):
    """Real queue state (waiting, counters, utilisation, arrival rate) plus a suggested what-if base configuration."""
    return TwinService(db).live(queue_id)


@router.get("/forecast/{queue_id}", responses=ERR)
def forecast(queue_id: int, replications: int = Query(default=30, ge=5, le=200),
             seed: int = Query(default=2026, ge=0, le=2**31), arrival_rate: float | None = Query(default=None, gt=0),
             db: Session = Depends(get_db)):
    """5/15/30/60-minute forecast of queue length, waiting time, arrivals, utilisation and congestion risk."""
    return TwinService(db).forecast(queue_id, replications, seed, arrival_rate)


@router.post("/simulate", responses=ERR)
def simulate(payload: TwinSimulateRequest):
    """Run a what-if / chaos scenario. Returns aggregate statistics and full playback data for the first seed."""
    res = _guard(run_replications, payload.configuration, payload.replications, payload.seed)
    primary = res.pop("primary")
    return json_safe({**res, "playback": primary})


@router.post("/compare", responses=ERR)
def compare(payload: TwinCompareRequest):
    """Compare 2-5 scenarios on the same seeds; the first scenario is the baseline."""
    items = [(s.name, s.configuration) for s in payload.scenarios]
    return json_safe(_guard(compare_scenarios, items, payload.replications, payload.seed))


@router.post("/recommend", responses=ERR)
def recommend(payload: TwinRecoverRequest):
    """Assisted self-healing: diagnose and rank interventions by simulated benefit."""
    return json_safe(_guard(tr.recommend, payload.configuration, payload.replications, payload.seed,
                            payload.max_extra_cost))


@router.post("/recover", responses=ERR)
def recover(payload: TwinRecoverRequest):
    """Automatic simulation recovery: search reactive policies; returns before/after playback. Simulation only."""
    return json_safe(_guard(tr.auto_recover, payload.configuration, payload.replications, payload.seed,
                            payload.max_extra_cost))


@router.post("/explain", responses=ERR)
def explain(payload: TwinExplainRequest):
    """Grounded explanation. Facts are recomputed server-side; Gemini (if configured) can only reword them."""
    if payload.kind == "scenarios":
        items = [(s.name, s.configuration) for s in payload.scenarios or []]
        facts = tx.facts_from_comparison(_guard(compare_scenarios, items, payload.replications, payload.seed))
    elif payload.kind == "intervention":
        rec = _guard(tr.recommend, payload.configuration, payload.replications, payload.seed)
        facts = tx.facts_from_recommendation(payload.configuration, rec)
    else:
        res = _guard(run_replications, payload.configuration, payload.replications, payload.seed)
        facts = tx.facts_from_simulation(payload.configuration, res)
    return json_safe(_guard(gemini_service.explain, payload.kind, facts, payload.question))
