"""Synthetic data generator.

    python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset

Every generated row has is_synthetic = true (queues also carry `scenario` and a "[SYNTHETIC]" description
prefix; events carry {"synthetic": true}). Data comes from the SimPy engine, so waits/service times are
consistent with a real queueing process, not random numbers.
Units: simulated minutes are converted to real timestamps; waiting_time/service_time are stored in seconds.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.engines.simulation_engine import ProfileSegment, SimulationConfig, run_simulation
from app.models import (
    CounterStatus, EntryStatus, EventType, Queue, QueueEntry, QueueEvent, QueueStatus, ServiceCounter,
    ServiceRecord, utcnow,
)

LABEL = "[SYNTHETIC]"


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    description: str
    arrival_rate: float
    mean_service_time: float
    speed_factors: tuple[float, ...]
    counter_assignment: str = "longest_idle"
    spikes: tuple[tuple[float, float, float], ...] = ()
    mean_patience: float | None = None


SCENARIOS: dict[str, Scenario] = {s.key: s for s in [
    Scenario("normal", "Normal operations", "Healthy load: ~67% utilisation on 3 equal counters.",
             0.5, 4.0, (1.0, 1.0, 1.0)),
    Scenario("arrival_spike", "Sudden arrival spike", "Arrival rate quadruples mid-day, then recovers.",
             0.4, 4.0, (1.0, 1.0, 1.0), spikes=((0.40, 0.55, 4.0),)),
    Scenario("insufficient_capacity", "Insufficient capacity", "Demand exceeds capacity; line grows and customers give up.",
             1.0, 4.0, (1.0, 1.0, 1.0), mean_patience=25.0),
    Scenario("uneven_utilization", "Uneven counter utilisation", "Customers always go to the lowest-numbered idle counter.",
             0.4, 4.0, (1.0, 1.0, 1.0, 1.0), counter_assignment="lowest_index"),
    Scenario("slow_counter", "Slow service counter", "One counter works at ~35% of normal speed.",
             0.45, 4.0, (1.0, 1.0, 0.35)),
    Scenario("excess_capacity", "Excess capacity", "Six counters for a light load (~20% utilisation).",
             0.3, 4.0, (1.0,) * 6),
    Scenario("mixed_rates", "Counters with different service rates", "Four counters at 1.6x, 1.0x, 0.7x and 0.4x speed.",
             0.6, 4.0, (1.6, 1.0, 0.7, 0.4)),
]}


def _config(sc: Scenario, customers: int, seed: int) -> tuple[SimulationConfig, float]:
    avg_mult = 1.0 + sum((e - s) * (m - 1.0) for s, e, m in sc.spikes)
    duration = customers / (sc.arrival_rate * avg_mult)
    profile = [ProfileSegment(start=s * duration, end=e * duration, multiplier=m) for s, e, m in sc.spikes]
    cfg = SimulationConfig(
        arrival_rate=sc.arrival_rate, mean_service_time=sc.mean_service_time, num_counters=len(sc.speed_factors),
        duration=duration, seed=seed, counter_speed_factors=list(sc.speed_factors),
        counter_assignment=sc.counter_assignment, arrival_profile=profile or None,
        abandonment_enabled=sc.mean_patience is not None, mean_patience=sc.mean_patience, record_trace=True,
    )
    return cfg, duration


def reset_synthetic_data(session: Session) -> dict[str, int]:
    """Delete all synthetic queues; counters, entries, events and records go with them (ON DELETE CASCADE)."""
    counts = {
        "queues": session.scalar(select(func.count()).select_from(Queue).where(Queue.is_synthetic.is_(True))) or 0,
        "entries": session.scalar(select(func.count()).select_from(QueueEntry).where(QueueEntry.is_synthetic.is_(True))) or 0,
        "events": session.scalar(select(func.count()).select_from(QueueEvent).where(QueueEvent.is_synthetic.is_(True))) or 0,
        "service_records": session.scalar(select(func.count()).select_from(ServiceRecord).where(ServiceRecord.is_synthetic.is_(True))) or 0,
    }
    session.execute(delete(Queue).where(Queue.is_synthetic.is_(True)))
    session.commit()
    return counts


def generate_scenario(
    session: Session, key: str, customers: int = 500, seed: int = 42, end_time: datetime | None = None,
    scenario_index: int = 0,
) -> dict:
    sc = SCENARIOS[key]
    run_seed = int(np.random.SeedSequence([seed, scenario_index]).generate_state(1)[0])
    cfg, duration = _config(sc, customers, run_seed)
    result = run_simulation(cfg)
    trace = result["trace"]
    end_time = end_time or utcnow()
    base = end_time - timedelta(minutes=duration)

    def ts(minutes: float) -> datetime:
        return base + timedelta(minutes=minutes)

    queue = Queue(
        name=f"{LABEL} {sc.title}", description=f"{LABEL} {sc.description}", status=QueueStatus.ACTIVE.value,
        last_token=len(trace), is_synthetic=True, scenario=key, created_at=base, updated_at=end_time,
    )
    session.add(queue)
    session.flush()

    serving_counters = {t["counter_index"] for t in trace if t["service_start_time"] is not None and t["service_end_time"] is None}
    counters = []
    for i, factor in enumerate(sc.speed_factors):
        counters.append(ServiceCounter(
            queue_id=queue.id, name=f"Counter {i + 1}", service_rate=round(factor / sc.mean_service_time, 6),
            status=CounterStatus.ACTIVE.value, current_load=1 if i in serving_counters else 0, is_synthetic=True,
        ))
    session.add_all(counters)
    session.flush()

    entries: list[QueueEntry] = []
    for t in trace:
        if t["abandon_time"] is not None:
            status = EntryStatus.ABANDONED
        elif t["service_end_time"] is not None:
            status = EntryStatus.COMPLETED
        elif t["service_start_time"] is not None:
            status = EntryStatus.SERVING
        else:
            status = EntryStatus.WAITING
        counter = counters[t["counter_index"]] if t["counter_index"] is not None else None
        entries.append(QueueEntry(
            queue_id=queue.id, counter_id=counter.id if counter else None, token_number=t["customer"],
            status=status.value, arrival_time=ts(t["arrival_time"]),
            service_start_time=ts(t["service_start_time"]) if t["service_start_time"] is not None else None,
            service_end_time=ts(t["service_end_time"]) if t["service_end_time"] is not None else None,
            is_synthetic=True,
        ))
    session.add_all(entries)
    session.flush()

    events: list[dict] = [dict(
        queue_id=queue.id, counter_id=None, event_type=EventType.QUEUE_CREATED.value, timestamp=base,
        event_metadata={"synthetic": True, "scenario": key}, is_synthetic=True,
    )]
    records: list[dict] = []

    def ev(kind: EventType, when: datetime, entry: QueueEntry, extra: dict | None = None):
        events.append(dict(
            queue_id=queue.id, counter_id=entry.counter_id if kind != EventType.ENTRY_ADDED else None,
            event_type=kind.value, timestamp=when, is_synthetic=True,
            event_metadata={"synthetic": True, "scenario": key, "entry_id": entry.id,
                            "token_number": entry.token_number, **(extra or {})},
        ))

    for t, entry in zip(trace, entries):
        ev(EventType.ENTRY_ADDED, entry.arrival_time, entry)
        if t["abandon_time"] is not None:
            ev(EventType.ENTRY_ABANDONED, ts(t["abandon_time"]), entry,
               {"waited_seconds": round((t["abandon_time"] - t["arrival_time"]) * 60, 3)})
        if entry.service_start_time is not None:
            wait_s = (entry.service_start_time - entry.arrival_time).total_seconds()
            ev(EventType.SERVICE_STARTED, entry.service_start_time, entry, {"waiting_time_seconds": wait_s})
        if entry.service_end_time is not None:
            svc_s = (entry.service_end_time - entry.service_start_time).total_seconds()
            ev(EventType.SERVICE_COMPLETED, entry.service_end_time, entry,
               {"waiting_time_seconds": wait_s, "service_time_seconds": svc_s})
            records.append(dict(
                queue_id=queue.id, counter_id=entry.counter_id, entry_id=entry.id, waiting_time=wait_s,
                service_time=svc_s, completed_at=entry.service_end_time, is_synthetic=True,
            ))
    events.sort(key=lambda e: e["timestamp"])
    if events:
        session.execute(insert(QueueEvent), events)
    if records:
        session.execute(insert(ServiceRecord), records)
    session.commit()

    return {
        "scenario": key, "queue_id": queue.id, "duration_minutes": round(duration, 1),
        "customers": len(trace), "completed": len(records),
        "abandoned": result["abandoned"], "waiting_now": result["customers_waiting_at_end"],
        "serving_now": result["customers_in_service_at_end"], "avg_wait_minutes": result["avg_waiting_time"],
        "avg_utilization": result["avg_utilization"],
        "counter_utilization": [c["utilization"] for c in result["counters"]],
        "events": len(events),
    }


def generate(
    session: Session, scenarios: list[str] | None = None, customers: int = 500, seed: int = 42,
    reset: bool = False, end_time: datetime | None = None,
) -> dict:
    keys = list(SCENARIOS) if not scenarios or scenarios == ["all"] else scenarios
    unknown = [k for k in keys if k not in SCENARIOS]
    if unknown:
        raise ValueError(f"Unknown scenario(s): {unknown}. Choose from {list(SCENARIOS)} or 'all'")
    if customers < 1:
        raise ValueError("customers must be >= 1")
    removed = reset_synthetic_data(session) if reset else None
    end_time = end_time or utcnow()
    summaries = [
        generate_scenario(session, k, customers, seed, end_time, scenario_index=list(SCENARIOS).index(k))
        for k in keys
    ]
    return {"reset": removed, "seed": seed, "customers_per_queue": customers, "scenarios": summaries}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate labelled synthetic LineZero data")
    parser.add_argument("--scenario", default="all", help=f"Comma-separated: all, {', '.join(SCENARIOS)}")
    parser.add_argument("--customers", type=int, default=500, help="Approx. customers per generated queue")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reset", action="store_true", help="Delete existing synthetic data first")
    parser.add_argument("--reset-only", action="store_true", help="Only delete synthetic data")
    parser.add_argument("--list", action="store_true", help="List scenarios and exit")
    args = parser.parse_args()

    if args.list:
        for sc in SCENARIOS.values():
            print(f"{sc.key:24s} {sc.description}")
        return

    from app.core.database import SessionLocal
    from app.core.migrations import run_migrations

    run_migrations()
    with SessionLocal() as session:
        if args.reset_only:
            print(json.dumps({"reset": reset_synthetic_data(session)}, indent=2))
            return
        out = generate(session, args.scenario.split(","), args.customers, args.seed, args.reset)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
