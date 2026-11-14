from datetime import timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import make_engine
from app.core.migrations import run_migrations
from app.models import (
    Queue, QueueEntry, QueueEvent, ServiceCounter, ServiceRecord, SimulationRun, utcnow,
)

TABLES = {"queues", "service_counters", "queue_entries", "queue_events", "service_records", "simulation_runs",
          "prediction_records", "bottleneck_detections", "optimization_results", "reports"}


def test_alembic_migration_initialises_database(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    run_migrations(url)
    eng = make_engine(url)
    assert TABLES <= set(inspect(eng).get_table_names())
    run_migrations(url)
    eng.dispose()


def test_relationships(db):
    q = Queue(name="Q")
    c = ServiceCounter(name="C1", service_rate=0.5)
    q.counters.append(c)
    q.entries.append(QueueEntry(token_number=1))
    q.events.append(QueueEvent(event_type="x", event_metadata={"a": 1}))
    db.add(q)
    db.commit()
    db.refresh(q)
    assert q.counters[0].queue is q
    assert q.entries[0].queue_id == q.id
    assert q.events[0].event_metadata == {"a": 1}
    rec = ServiceRecord(queue_id=q.id, counter_id=c.id, waiting_time=1, service_time=2)
    db.add(rec)
    db.commit()
    assert q.service_records[0].id == rec.id


def test_foreign_keys_enforced(db):
    db.add(QueueEntry(queue_id=999, token_number=1))
    with pytest.raises(IntegrityError):
        db.commit()


def test_unique_and_check_constraints(db):
    q = Queue(name="Q")
    db.add(q)
    db.commit()
    db.add_all([QueueEntry(queue_id=q.id, token_number=1), QueueEntry(queue_id=q.id, token_number=1)])
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(ServiceCounter(queue_id=q.id, name="bad", service_rate=0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(Queue(name="x", status="nonsense"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_cascade_delete_removes_children(db):
    q = Queue(name="Q")
    q.counters.append(ServiceCounter(name="C", service_rate=1))
    q.entries.append(QueueEntry(token_number=1))
    q.events.append(QueueEvent(event_type="e"))
    db.add(q)
    db.commit()
    db.delete(q)
    db.commit()
    for model in (ServiceCounter, QueueEntry, QueueEvent):
        assert db.scalars(select(model)).all() == []


def test_timestamps_are_utc_aware(db):
    q = Queue(name="Q")
    db.add(q)
    db.commit()
    db.expire_all()
    q = db.scalars(select(Queue)).one()
    assert q.created_at.tzinfo is not None and q.created_at.utcoffset().total_seconds() == 0
    delta = abs((utcnow() - q.created_at).total_seconds())
    assert delta < 5


def test_simulation_run_json_roundtrip(db):
    db.add(SimulationRun(configuration={"a": 1}, results={"b": [1, 2]}))
    db.commit()
    run = db.scalars(select(SimulationRun)).one()
    assert run.configuration == {"a": 1} and run.results == {"b": [1, 2]}


def test_part2_models_relationships_and_cascade(db):
    from app.models import BottleneckDetection, OptimizationResult, PredictionRecord, Report

    q = Queue(name="Q")
    db.add(q)
    db.commit()
    db.add_all([
        PredictionRecord(queue_id=q.id, predicted_waiting_time=60, prediction_method="statistical_baseline",
                         input_features={"queue_ahead": 2}),
        BottleneckDetection(queue_id=q.id, bottleneck_type="counter_overload", severity="HIGH",
                            supporting_metrics={"u": 0.9}, explanation="e", recommendation="r"),
        OptimizationResult(queue_id=q.id, current_allocation={}, proposed_allocation={}, current_metrics={},
                           proposed_metrics={}, estimated_improvement={}, explanation="x"),
        Report(report_type="queue_performance", queue_id=q.id, report_data={"a": 1}),
    ])
    db.commit()
    db.refresh(q)
    assert len(q.predictions) == len(q.bottleneck_detections) == len(q.optimization_results) == 1
    rep = db.scalars(select(Report)).one()
    db.delete(q)
    db.commit()
    assert db.scalars(select(PredictionRecord)).all() == [] and db.scalars(select(BottleneckDetection)).all() == []
    assert db.scalars(select(OptimizationResult)).all() == []
    db.expire_all()
    assert db.scalars(select(Report)).one().queue_id is None


def test_part2_constraints(db):
    from app.models import BottleneckDetection, PredictionRecord

    q = Queue(name="Q")
    db.add(q)
    db.commit()
    db.add(PredictionRecord(queue_id=q.id, predicted_waiting_time=-1, prediction_method="m", input_features={}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(BottleneckDetection(queue_id=q.id, bottleneck_type="counter_overload", severity="SEVERE",
                               supporting_metrics={}, explanation="e", recommendation="r"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_migration_head_is_0002(tmp_path):
    from alembic.script import ScriptDirectory
    from app.core.migrations import alembic_config

    assert ScriptDirectory.from_config(alembic_config(f"sqlite:///{tmp_path / 'x.db'}")).get_current_head() == "0002"
