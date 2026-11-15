"""Intervention API: persistence, approval workflow, operator control, nothing real is ever changed."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models import InterventionHistory, ServiceCounter
from app.seed.generate_demo_data import generate_scenario
from tests.adaptive_helpers import add_waiting, history, load_history, pause_counters, shift_to_now

API = "/api/v1/interventions"
BODY = {"replications": 4, "horizon_min": 45, "seed": 11}


@pytest.fixture
def hot(db):
    """Live queue: 3 active counters at ~93% load, 2 reserve (paused) counters, 12 customers waiting."""
    df = history(n=500, lam=0.7, seed=5, speeds=(1, 1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1, 1), nominal_rate=0.25, name="Hot")
    pause_counters(db, qid, 2)
    add_waiting(db, qid, 12)
    return qid


def counters_snapshot(db, qid):
    db.expire_all()
    return [(c.id, c.status, c.current_load) for c in db.scalars(
        select(ServiceCounter).where(ServiceCounter.queue_id == qid).order_by(ServiceCounter.id))]


def evaluate(client, qid, **kw):
    r = client.post(f"{API}/{qid}/evaluate", json={**BODY, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_errors_and_validation(client, db, hot):
    assert client.post(f"{API}/999/evaluate", json={}).status_code == 404
    for bad in ({"replications": 2}, {"replications": 99}, {"horizon_min": 5}, {"horizon_min": 999},
                {"cost_model": {"cost_weight": -1}}, {"cost_model": {"max_assist_staff": -1}}, {"bogus": 1},
                {"risk_event_id": 0}):
        r = client.post(f"{API}/{hot}/evaluate", json=bad)
        assert r.status_code == 422, bad
    assert client.post(f"{API}/{hot}/evaluate", json={"risk_event_id": 4242, **BODY}).status_code == 404
    empty = client.post("/api/v1/queues", json={"name": "NoCounters"}).json()["id"]
    r = client.post(f"{API}/{empty}/evaluate", json=BODY)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_active_counters"
    for path in ("item/9999", ):
        assert client.get(f"{API}/{path}").status_code == 404
    assert client.post(f"{API}/item/9999/approve", json={"operator": "a"}).status_code == 404
    assert client.get(f"{API}/999/history").status_code == 404
    assert client.get(f"{API}/{hot}/history", params={"status": "weird"}).status_code == 422


def test_evaluate_returns_ranked_simulated_candidates_against_the_baseline(client, db, hot):
    r = evaluate(client, hot)
    assert r["simulation_only"] and r["executed"] is False and r["requires_operator_approval"]
    assert r["provenance"]["observations"] == "observed_real_data"
    assert r["data_kind"]["baseline_and_candidates"] == "simulated"
    assert r["baseline"]["starting_state"]["queue_length"] == 12
    assert r["recommended_key"] and r["explanation"].startswith("Baseline")
    keys = {c["key"] for c in r["candidates"]}
    assert {"activate_1", "activate_2", "assist_15", "assist_30", "divert_10", "divert_20", "combined"} <= keys
    best = next(c for c in r["candidates"] if c["is_recommended"])
    assert best["rank"] == 1 and best["wait_reduction_min"]["mean"] > 0 and best["extra_cost"]["total"] >= 0
    assert r["inputs"]["service_rate_source"] == "nominal_configuration"
    assert r["persisted"] and r["evaluation_id"]


def test_proposals_are_stored_as_proposed_with_baseline_and_expectations(client, db, hot):
    r = evaluate(client, hot)
    hist = client.get(f"{API}/{hot}/history").json()["interventions"]
    assert len(hist) == len([c for c in r["candidates"] if c["feasible"]])
    assert {h["status"] for h in hist} == {"proposed"} and all(h["executed_by_linezero"] is False for h in hist)
    one = client.get(f"{API}/item/{hist[0]['id']}").json()["intervention"]
    assert one["baseline"]["summary"]["avg_waiting_time"] > 0 and one["expected"]["wait_reduction_min"]
    assert one["simulation_meta"]["base_seed"] == 11 and one["simulation_meta"]["config_hash"]
    assert one["result_kind"] == "simulated_expectation" and one["outcome"] is None
    assert any(h["is_recommended"] for h in hist)


def test_persist_false_stores_nothing_and_results_are_reproducible(client, db, hot):
    a = evaluate(client, hot, persist=False)
    b = evaluate(client, hot, persist=False)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(InterventionHistory)) == 0
    assert a["evaluation_id"] is None and a["persisted"] is False
    strip = lambda x: [(c["key"], c["score"], c["net_value"], c["rank"]) for c in x["candidates"]]  # noqa: E731
    assert strip(a) == strip(b) and a["reproducibility"]["config_hash"] == b["reproducibility"]["config_hash"]


def test_risk_event_can_be_linked(client, db, hot):
    scan = client.post(f"/api/v1/risk/{hot}/scan", json={"forecast_replications": 5}).json()
    ev = scan["persisted_events"][0]
    r = evaluate(client, hot, risk_event_id=ev["id"])
    assert r["risk_event_id"] == ev["id"]
    assert client.get(f"{API}/{hot}/history").json()["interventions"][0]["risk_event_id"] == ev["id"]


def _proposal(client, qid, key=None):
    r = evaluate(client, qid)
    key = key or r["recommended_key"]
    return next(c["record_id"] for c in r["candidates"] if c["key"] == key), r


def test_full_workflow_requires_explicit_operator_decisions_and_changes_nothing_real(client, db, hot):
    before = counters_snapshot(db, hot)
    rid, _ = _proposal(client, hot)
    # cannot skip approval
    skip = client.post(f"{API}/item/{rid}/applied", json={"operator": "ana"})
    assert skip.status_code == 409 and skip.json()["error"]["code"] == "invalid_transition"
    # operator is mandatory
    assert client.post(f"{API}/item/{rid}/approve", json={}).status_code == 422
    assert client.post(f"{API}/item/{rid}/approve", json={"operator": "   "}).status_code == 422

    ok = client.post(f"{API}/item/{rid}/approve", json={"operator": "ana", "note": "go"}).json()
    assert ok["intervention"]["status"] == "approved" and ok["intervention"]["decided_by"] == "ana"
    assert "has not changed anything" in ok["message"] and ok["intervention"]["executed_by_linezero"] is False
    assert client.post(f"{API}/item/{rid}/approve", json={"operator": "ana"}).status_code == 409  # twice

    now = datetime.now(timezone.utc)
    assert client.post(f"{API}/item/{rid}/applied", json={
        "operator": "ana", "applied_at": (now + timedelta(hours=1)).isoformat()}).status_code == 422
    assert client.post(f"{API}/item/{rid}/applied", json={
        "operator": "ana", "applied_at": (now - timedelta(days=1)).isoformat()}).status_code == 422
    done = client.post(f"{API}/item/{rid}/applied", json={"operator": "ana", "note": "opened counter 4"}).json()
    iv = done["intervention"]
    assert iv["status"] == "applied" and iv["applied_by"] == "ana" and iv["applied_at"] and iv["executed_by_linezero"] is False
    assert client.post(f"{API}/item/{rid}/reject", json={"operator": "ana"}).status_code == 409
    assert counters_snapshot(db, hot) == before  # LineZero changed no counter, whatever the operator decided


def test_only_one_candidate_per_evaluation_can_be_taken_forward(client, db, hot):
    r = evaluate(client, hot)
    ids = [c["record_id"] for c in r["candidates"] if c["record_id"]]
    assert client.post(f"{API}/item/{ids[0]}/approve", json={"operator": "a"}).status_code == 200
    second = client.post(f"{API}/item/{ids[1]}/approve", json={"operator": "b"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "another_candidate_in_force"
    assert client.post(f"{API}/item/{ids[1]}/reject", json={"operator": "b"}).status_code == 200  # rejecting is fine
    # a different evaluation is independent
    other, _ = _proposal(client, hot)
    assert client.post(f"{API}/item/{other}/approve", json={"operator": "b"}).status_code == 200


def test_rejected_proposals_stay_in_history_and_can_be_filtered(client, db, hot):
    rid, _ = _proposal(client, hot)
    assert client.post(f"{API}/item/{rid}/reject", json={"operator": "ana", "note": "too costly"}).json()["intervention"]["status"] == "rejected"
    assert client.post(f"{API}/item/{rid}/approve", json={"operator": "ana"}).status_code == 409
    rej = client.get(f"{API}/{hot}/history", params={"status": "rejected"}).json()["interventions"]
    assert [x["id"] for x in rej] == [rid] and rej[0]["decision_note"] == "too costly"


def test_budget_excludes_infeasible_candidates_from_the_stored_history(client, db, hot):
    r = evaluate(client, hot, cost_model={"max_extra_cost": 0.3})
    infeasible = [c for c in r["candidates"] if not c["feasible"]]
    assert infeasible and all(c["record_id"] is None for c in infeasible)
    stored = client.get(f"{API}/{hot}/history").json()["interventions"]
    assert len(stored) == len(r["candidates"]) - len(infeasible)


def test_synthetic_queue_is_labelled(client, db):
    qid = generate_scenario(db, "normal", 150, seed=2)["queue_id"]
    r = client.post(f"{API}/{qid}/evaluate", json=BODY)
    if r.status_code == 200:
        assert r.json()["provenance"]["is_synthetic"] and "SYNTHETIC" in r.json()["provenance"]["notice"]
        assert all(h["is_synthetic"] for h in client.get(f"{API}/{qid}/history").json()["interventions"])


def test_calibrated_rates_feed_the_simulation(client, db):
    df = history(n=900, lam=0.5, seed=3, speeds=(1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1), nominal_rate=0.15, name="Cal")
    pause_counters(db, qid, 1)
    add_waiting(db, qid, 6)
    nominal = client.post(f"{API}/{qid}/evaluate", json={**BODY, "persist": False}).json()
    assert client.post(f"/api/v1/calibration/{qid}/run", json={}).json()["decision"] == "accepted"
    cal = client.post(f"{API}/{qid}/evaluate", json={**BODY, "persist": False}).json()
    assert nominal["inputs"]["service_rate_source"] == "nominal_configuration"
    assert cal["inputs"]["service_rate_source"] == "calibration_v1" and cal["inputs"]["calibration_version"] == 1
    rates = lambda r: r["baseline"]["starting_state"]["counters"][0]["service_rate_per_min"]  # noqa: E731
    assert rates(cal) > rates(nominal)
    off = client.post(f"{API}/{qid}/evaluate", json={**BODY, "persist": False, "use_calibration": False}).json()
    assert off["inputs"]["service_rate_source"] == "nominal_configuration"
