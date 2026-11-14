import pytest
from sqlalchemy import func, select

from app.models import Queue, QueueEntry, QueueEvent, ServiceCounter, ServiceRecord
from app.seed.generate_demo_data import SCENARIOS, generate, generate_scenario, reset_synthetic_data


def counts(db):
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (Queue, ServiceCounter, QueueEntry, QueueEvent, ServiceRecord)}


def test_all_seven_scenarios_generate_labelled_data(db):
    out = generate(db, ["all"], customers=120, seed=1)
    assert len(out["scenarios"]) == 7 == len(SCENARIOS)
    c = counts(db)
    assert c["queues"] == 7 and c["queue_entries"] > 600 and c["queue_events"] > c["queue_entries"]
    for model in (Queue, ServiceCounter, QueueEntry, QueueEvent, ServiceRecord):
        assert db.scalar(select(func.count()).select_from(model).where(model.is_synthetic.is_(False))) == 0
    q = db.scalars(select(Queue)).first()
    assert q.description.startswith("[SYNTHETIC]") and q.scenario in SCENARIOS


def test_generated_data_is_internally_consistent(db):
    generate(db, ["normal"], customers=150, seed=2)
    q = db.scalars(select(Queue)).one()
    entries = db.scalars(select(QueueEntry).where(QueueEntry.queue_id == q.id)).all()
    assert [e.token_number for e in sorted(entries, key=lambda e: e.token_number)] == list(range(1, len(entries) + 1))
    assert q.last_token == len(entries)
    done = [e for e in entries if e.status == "completed"]
    records = db.scalars(select(ServiceRecord)).all()
    assert len(records) == len(done)
    by_entry = {r.entry_id: r for r in records}
    for e in done:
        r = by_entry[e.id]
        assert r.waiting_time == pytest.approx((e.service_start_time - e.arrival_time).total_seconds())
        assert r.service_time == pytest.approx((e.service_end_time - e.service_start_time).total_seconds())
        assert e.service_start_time >= e.arrival_time and e.counter_id is not None
    busy = db.scalars(select(ServiceCounter).where(ServiceCounter.current_load > 0)).all()
    assert len(busy) == sum(1 for e in entries if e.status == "serving")
    kinds = {k for (k,) in db.execute(select(QueueEvent.event_type).distinct())}
    assert {"queue_created", "entry_added", "service_started", "service_completed"} <= kinds


def test_same_seed_is_reproducible_and_different_seed_differs(db):
    a = generate_scenario(db, "normal", 100, seed=7)
    b = generate_scenario(db, "normal", 100, seed=7)
    c = generate_scenario(db, "normal", 100, seed=8)
    keys = ("customers", "completed", "avg_wait_minutes", "counter_utilization")
    assert [a[k] for k in keys] == [b[k] for k in keys]
    assert [a[k] for k in keys] != [c[k] for k in keys]


def test_reset_removes_only_synthetic_data(db):
    real = Queue(name="Real queue")
    real.counters.append(ServiceCounter(name="R1", service_rate=1))
    real.entries.append(QueueEntry(token_number=1))
    db.add(real)
    db.commit()
    generate(db, ["normal", "excess_capacity"], customers=60, seed=3)
    removed = reset_synthetic_data(db)
    assert removed["queues"] == 2 and removed["entries"] > 0 and removed["events"] > 0
    c = counts(db)
    assert c["queues"] == 1 and c["service_counters"] == 1 and c["queue_entries"] == 1
    generate(db, ["normal"], customers=60, seed=3)
    generate(db, ["normal"], customers=60, seed=3, reset=True)
    assert counts(db)["queues"] == 2


def test_volume_is_configurable(db):
    small = generate_scenario(db, "normal", 50, seed=1)
    large = generate_scenario(db, "normal", 400, seed=1)
    assert 25 < small["customers"] < 100 and 300 < large["customers"] < 520


def test_scenarios_show_their_intended_behaviour(db):
    s = {k: generate_scenario(db, k, 400, seed=11, scenario_index=i) for i, k in enumerate(SCENARIOS)}
    assert s["insufficient_capacity"]["abandoned"] > 20
    assert s["insufficient_capacity"]["avg_wait_minutes"] > 2 * s["normal"]["avg_wait_minutes"]
    assert s["insufficient_capacity"]["avg_utilization"] > 0.95 > s["normal"]["avg_utilization"]
    assert s["arrival_spike"]["avg_wait_minutes"] > 3 * s["normal"]["avg_wait_minutes"]
    assert s["excess_capacity"]["avg_wait_minutes"] < 0.1 and s["excess_capacity"]["avg_utilization"] < 0.3
    util = s["uneven_utilization"]["counter_utilization"]
    assert util[0] > 2 * util[-1]
    slow = s["slow_counter"]["counter_utilization"]
    assert slow[2] > max(slow[0], slow[1])
    assert len(s["mixed_rates"]["counter_utilization"]) == 4
    rates = [c.service_rate for c in db.scalars(select(ServiceCounter).join(Queue).where(Queue.scenario == "mixed_rates"))]
    assert rates == pytest.approx([0.4, 0.25, 0.175, 0.1])


def test_unknown_scenario_rejected(db):
    with pytest.raises(ValueError):
        generate(db, ["nope"])


def test_synthetic_data_visible_through_api(client, db):
    generate(db, ["normal"], customers=50, seed=1)
    q = client.get("/api/v1/queues", params={"synthetic": True}).json()
    assert len(q) == 1 and q[0]["is_synthetic"] is True and q[0]["counter_count"] == 3
    assert client.get("/api/v1/queues", params={"synthetic": False}).json() == []
    assert client.get(f"/api/v1/queues/{q[0]['id']}/state").status_code == 200
