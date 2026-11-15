"""Risk API: assess is read-only, scan persists and refreshes events, lifecycle, provenance, validation."""
import pytest
from sqlalchemy import func, select

from app.models import RiskEvent
from app.seed.generate_demo_data import generate_scenario
from tests.adaptive_helpers import history, load_history, shift_to_now

API = "/api/v1/risk"


@pytest.fixture
def hot_queue(db):
    """A live (non-synthetic) queue running at ~93% load with a demand surge in the last 40 minutes."""
    df = history(n=700, lam=0.7, seed=5, spikes=[(850.0, 1e9, 2.0)])
    return load_history(db, shift_to_now(df), nominal_rate=0.25, name="Hot")


def n_events(db):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(RiskEvent))


def test_unknown_queue_and_validation(client):
    assert client.get(f"{API}/999/assess").status_code == 404
    assert client.post(f"{API}/999/scan", json={}).status_code == 404
    assert client.get(f"{API}/999/events").status_code == 404
    q = client.post("/api/v1/queues", json={"name": "E"}).json()["id"]
    assert client.get(f"{API}/{q}/assess", params={"wait_sla_min": 0}).status_code == 422
    assert client.post(f"{API}/{q}/scan", json={"seed": -1}).status_code == 422
    assert client.get(f"{API}/{q}/events", params={"status": "bogus"}).status_code == 422
    assert client.post(f"{API}/events/9999/resolve", json={"operator": "x"}).status_code == 404


def test_assess_is_read_only_and_returns_all_seven_categories(client, db, hot_queue):
    r = client.get(f"{API}/{hot_queue}/assess").json()
    assert r["persisted"] is False and n_events(db) == 0
    assert len(r["radar"]) == 7 and r["forecast_used"] is True
    assert r["provenance"]["observations"] == "observed_real_data" and r["service_rate_source"] == "nominal_configuration"
    assert r["overall_severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL") and r["events"]
    ev = r["events"][0]
    for k in ("category", "severity", "resource_name", "time_to_impact_min", "supporting_metrics", "confidence",
              "recommended_intervention", "score_formula", "explanation"):
        assert k in ev
    # (exact determinism is asserted at engine level; a live queue's anchor is the wall clock, which moves)


def test_scan_persists_refreshes_and_resolves_events(client, db, hot_queue):
    first = client.post(f"{API}/{hot_queue}/scan", json={}).json()
    assert first["persisted"] is True and first["persisted_events"]
    n1 = n_events(db)
    assert n1 == len(first["events"])
    ids = {e["id"] for e in first["persisted_events"]}
    detected = {e["id"]: e["detected_at"] for e in first["persisted_events"]}

    second = client.post(f"{API}/{hot_queue}/scan", json={}).json()
    assert n_events(db) == n1  # refreshed, not duplicated
    for e in second["persisted_events"]:
        if e["id"] in ids:
            assert e["detected_at"] == detected[e["id"]] and e["last_seen_at"] >= e["detected_at"]

    top = second["persisted_events"][0]
    done = client.post(f"{API}/events/{top['id']}/resolve", json={"operator": "ana", "note": "handled"})
    assert done.status_code == 200 and done.json()["status"] == "resolved" and "ana" in done.json()["explanation"]
    assert client.post(f"{API}/events/{top['id']}/resolve", json={"operator": "ana"}).status_code == 409
    open_ev = client.get(f"{API}/{hot_queue}/events", params={"status": "open"}).json()["events"]
    assert top["id"] not in {e["id"] for e in open_ev}


def test_persist_false_scan_stores_nothing(client, db, hot_queue):
    r = client.post(f"{API}/{hot_queue}/scan", json={"persist": False}).json()
    assert r["persisted"] is False and n_events(db) == 0 and r["events"]


def test_events_that_stop_being_detected_are_marked_resolved(client, db, hot_queue):
    client.post(f"{API}/{hot_queue}/scan", json={})
    # a much looser SLA makes the wait-trend risk disappear while demand risks may remain
    row = db.scalars(select(RiskEvent)).first()
    row.category, row.resource_id, row.resource_name = "counter_failure_precursor", 99999, "Ghost counter"
    db.commit()
    again = client.post(f"{API}/{hot_queue}/scan", json={}).json()
    assert row.id in again["resolved_event_ids"]
    db.expire_all()
    assert db.get(RiskEvent, row.id).status == "resolved"


def test_synthetic_queue_is_labelled_and_uses_its_own_clock(client, db):
    qid = generate_scenario(db, "normal", 200, seed=3)["queue_id"]
    r = client.get(f"{API}/{qid}/assess").json()
    assert r["provenance"]["is_synthetic"] is True and "SYNTHETIC" in r["provenance"]["notice"]
    assert r["anchor_basis"] in ("latest_activity_of_synthetic_queue", "now")
    scan = client.post(f"{API}/{qid}/scan", json={}).json()
    assert all(e["is_synthetic"] for e in scan["persisted_events"])


def test_active_calibration_rates_are_used_when_present(client, db):
    df = history(n=900, lam=0.4, seed=3)
    qid = load_history(db, shift_to_now(df), nominal_rate=0.15, name="Cal")
    before = client.get(f"{API}/{qid}/assess").json()
    assert before["service_rate_source"] == "nominal_configuration"
    assert client.post(f"/api/v1/calibration/{qid}/run", json={}).json()["decision"] == "accepted"
    after = client.get(f"{API}/{qid}/assess").json()
    assert after["service_rate_source"] == "calibration_v1"
    assert after["snapshot"]["capacity_per_min"] > before["snapshot"]["capacity_per_min"]  # corrected 0.15 -> ~0.25


def test_a_queue_with_no_data_returns_a_valid_assessment(client):
    q = client.post("/api/v1/queues", json={"name": "Blank"}).json()["id"]
    r = client.get(f"{API}/{q}/assess")
    assert r.status_code == 200 and r.json()["events"][0]["category"] in ("queue_congestion", "capacity_shortage")
