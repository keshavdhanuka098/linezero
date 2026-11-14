"""Runs simulations and persists configuration + results."""
from __future__ import annotations

import secrets
import time
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.engines.comparison import compare_results
from app.engines.simulation_engine import SimulationConfig, run_simulation
from app.models import SimulationRun
from app.schemas.simulation import SimulationCompareOut, SimulationCompareRequest, SimulationRunOut


class SimulationService:
    def __init__(self, db: Session):
        self.db = db

    def _execute(self, name: str | None, config: SimulationConfig, comparison_id: str | None = None) -> SimulationRun:
        if config.record_trace:
            raise UnprocessableError("record_trace is not available through the API", "trace_not_supported")
        if config.seed is None:
            config = config.model_copy(update={"seed": secrets.randbits(32)})
        started = time.perf_counter()
        results = run_simulation(config)
        runtime_ms = (time.perf_counter() - started) * 1000
        run = SimulationRun(
            name=name, status="completed", configuration=config.model_dump(mode="json"),
            results=results, seed=config.seed, runtime_ms=round(runtime_ms, 3), comparison_id=comparison_id,
        )
        self.db.add(run)
        return run

    def run(self, name: str | None, config: SimulationConfig) -> SimulationRun:
        try:
            run = self._execute(name, config)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return run

    def get(self, simulation_id: int) -> SimulationRun:
        run = self.db.get(SimulationRun, simulation_id)
        if run is None:
            raise NotFoundError(f"Simulation {simulation_id} not found", "simulation_not_found")
        return run

    def list(self, limit: int = 50, offset: int = 0, comparison_id: str | None = None) -> list[SimulationRun]:
        stmt = select(SimulationRun).order_by(SimulationRun.id.desc()).limit(limit).offset(offset)
        if comparison_id:
            stmt = stmt.where(SimulationRun.comparison_id == comparison_id)
        return list(self.db.scalars(stmt).all())

    def compare(self, request: SimulationCompareRequest) -> SimulationCompareOut:
        shared_seed = request.seed if request.seed is not None else secrets.randbits(32)
        comparison_id = str(uuid.uuid4())
        try:
            runs = []
            for i, item in enumerate(request.configurations):
                cfg = item.configuration
                if cfg.seed is None:
                    cfg = cfg.model_copy(update={"seed": shared_seed})
                runs.append(self._execute(item.name or f"config {i + 1}", cfg, comparison_id))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        labels = [r.name for r in runs]
        return SimulationCompareOut(
            comparison_id=comparison_id,
            runs=[SimulationRunOut.model_validate(r) for r in runs],
            comparison=compare_results(labels, [r.results for r in runs]),
        )

    def delete(self, simulation_id: int) -> None:
        run = self.get(simulation_id)
        self.db.delete(run)
        self.db.commit()

    def reset(self) -> int:
        """Delete every stored simulation run."""
        count = self.db.scalar(select(func.count()).select_from(SimulationRun)) or 0
        self.db.execute(delete(SimulationRun))
        self.db.commit()
        return count
