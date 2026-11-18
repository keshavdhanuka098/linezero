"""SLA module API: configuration, live monitoring, compliance, recommendations, regression of existing endpoints."""
import numpy as np
import pytest
from sqlalchemy import func, select

from app.engines import sla_engine as se
from app.models import InterventionHistory, QueueEntry, ServiceCounter, ServiceRecord
from tests.adaptive_helpers import add_waiting, history, load_history, pause_counters, shift_to_now

API = "/api/v1/sla"
OP = {"operator": "ana"}


@pytest.fixture
def hot(db):
    """Live real queue: 3 active counters (nominal 0.25/min each), 2 reserve, 12 customers waiting ~4-5 min."""
    df = history(n=700, lam=0.7, seed=5, speeds=(1, 1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1, 1), nominal_rate=0.25, name="Hot")
    pause_counters(db, qid, 2)
    for c in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == qid, ServiceCounter.status == "active")).all():
        c.current_load = 1                                  # all active counters are serving someone
    db.commit()
    add_waiting(db, qid, 12, minutes_ago=5.0)
    return qid


def put(client, qid, cls="standard", **kw):
    body = {"max_wait_min": 8, **OP, **kw}
    return client.put(f"{API}/{qid}/policies/{cls}", json=body)


# ---------------------------------------------------------------- configuration
def test_not_configured_is_explained_never_assumed(client, hot):
    for path in ("monitor", "performance"):
        r = client.get(f"{API}/{hot}/{path}").json()
        assert r["configured"] is False and "does not assume" in r["reason"]
    r = client.post(f"{API}/{hot}/recommendations", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "sla_not_configured"
    assert client.get(f"{API}/{hot}/policies").json() == {**client.get(f"{API}/{hot}/policies").json(), "configured": False, "policies": []}


def test_policy_validation(client, hot):
    assert client.get(f"{API}/9999/policies").status_code == 404
    assert put(client, 9999).status_code == 404
    for bad in ({"max_wait_min": 0}, {"max_wait_min": -3}, {"max_wait_min": 5000}, {"max_wait_min": "x"},
                {"at_risk_probability": 0.7, "critical_probability": 0.5}, {"at_risk_probability": 0.5, "critical_probability": 0.5},
                {"at_risk_probability": 0}, {"critical_probability": 1}, {"operator": "  "}, {"bogus": 1}):
        assert put(client, hot, **bad).status_code == 422, bad
    assert client.put(f"{API}/{hot}/policies/standard", json={"max_wait_min": 8}).status_code == 422  # operator missing
    assert put(client, hot, "Bad Class").status_code in (404, 422)
    assert put(client, hot, "priority").json()["error"]["code"] == "standard_class_required"  # standard first


def test_create_update_and_persist_policy_with_audit_fields(client, hot):
    r = put(client, hot, label="Counter service").json()
    assert r["created"] and r["policy"]["max_wait_min"] == 8 and r["policy"]["updated_by"] == "ana"
    r2 = put(client, hot, max_wait_min=12, operator="bo", at_risk_probability=0.3, critical_probability=0.7).json()
    assert r2["created"] is False and r2["policy"]["id"] == r["policy"]["id"]
    got = client.get(f"{API}/{hot}/policies").json()
    assert got["configured"] and len(got["policies"]) == 1
    p = got["policies"][0]
    assert (p["max_wait_min"], p["updated_by"], p["at_risk_probability"], p["critical_probability"]) == (12, "bo", 0.3, 0.7)


def test_class_policies_delete_rules_and_isolation_between_queues(client, db, hot):
    other = load_history(db, shift_to_now(history(n=60, seed=9)), name="Other")
    put(client, hot)
    assert put(client, hot, "priority", max_wait_min=3).status_code == 200
    assert client.get(f"{API}/{other}/policies").json()["policies"] == []           # per-queue targets
    d = client.delete(f"{API}/{hot}/policies/standard", params=OP)
    assert d.status_code == 409 and d.json()["error"]["code"] == "standard_class_required"
    assert client.delete(f"{API}/{hot}/policies/priority").status_code == 422        # operator required
    assert client.delete(f"{API}/{hot}/policies/priority", params=OP).status_code == 200
    assert client.delete(f"{API}/{hot}/policies/priority", params=OP).status_code == 404
    assert client.delete(f"{API}/{hot}/policies/standard", params=OP).status_code == 200


# ---------------------------------------------------------------- live monitoring
def test_monitor_lists_every_waiting_customer_with_engine_consistent_numbers(client, hot):
    put(client, hot, max_wait_min=8)
    m = client.get(f"{API}/{hot}/monitor").json()
    assert m["configured"] and m["waiting"] == 12 and len(m["customers"]) == 12
    cap = m["capacity"]
    assert cap["active_counters"] == 3 and cap["service_capacity_per_min"] == pytest.approx(0.75)
    assert sum(m["counts"].values()) == 12
    for r in m["customers"]:
        assert set(r) >= {"entry_id", "token", "queue_id", "current_wait_min", "predicted_total_wait_min", "sla_target_min",
                          "remaining_sla_min", "breach_probability", "status"}
        assert r["sla_target_min"] == 8 and 0 <= r["breach_probability"] <= 1
        assert r["remaining_sla_min"] == pytest.approx(8 - r["current_wait_min"], abs=1e-6)
        k = r["completions_needed"]
        remaining = r["remaining_sla_min"] * 60
        assert r["breach_probability"] == pytest.approx(se.breach_probability(k, 0.75, remaining), abs=1e-9)
        assert r["predicted_total_wait_min"] == pytest.approx(r["current_wait_min"] + k / 0.75, abs=1e-6)
        assert r["highlight"] == (r["status"] != "safe")
    # first-come-first-served: the customer in position k needs k service completions while all counters are busy
    by_pos = sorted(m["customers"], key=lambda r: r["position"])
    assert [r["completions_needed"] for r in by_pos] == list(range(1, 13))   # k-th in line needs k completions
    assert m["customers"][0]["status"] in ("critical", "breached", "at_risk")      # worst first
    assert m["predicted_compliance"]["score"] == pytest.approx(100 * (1 - np.mean([r["breach_probability"] for r in m["customers"]])), abs=0.01)
    assert m["provenance"]["observations"] == "observed_real_data"


def test_changing_the_target_changes_the_classification(client, hot):
    put(client, hot, max_wait_min=1)                      # customers already waited ~4-5 min
    assert client.get(f"{API}/{hot}/monitor").json()["counts"]["breached"] == 12
    put(client, hot, max_wait_min=1440)
    c = client.get(f"{API}/{hot}/monitor").json()["counts"]
    assert c["breached"] == 0 and c["safe"] == 12


def test_policy_thresholds_are_respected(client, hot):
    put(client, hot, max_wait_min=30, at_risk_probability=0.01, critical_probability=0.02)
    strict = client.get(f"{API}/{hot}/monitor").json()["counts"]
    put(client, hot, max_wait_min=30, at_risk_probability=0.98, critical_probability=0.99)
    lax = client.get(f"{API}/{hot}/monitor").json()["counts"]
    assert strict["at_risk"] + strict["critical"] > lax["at_risk"] + lax["critical"]


def test_no_active_counter_means_no_finite_prediction(client, db, hot):
    for c in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == hot)).all():
        c.status = "paused"
    db.commit()
    put(client, hot, max_wait_min=30)
    m = client.get(f"{API}/{hot}/monitor").json()
    assert all(r["basis"] == "no_active_counters" and r["breach_probability"] == 1.0 and r["predicted_total_wait_min"] is None
               for r in m["customers"])


def test_service_class_changes_the_target_and_is_validated(client, hot):
    put(client, hot, max_wait_min=30)
    put(client, hot, "priority", max_wait_min=2)
    m = client.get(f"{API}/{hot}/monitor").json()
    tok = m["customers"][-1]
    eid = tok["entry_id"]
    assert client.post(f"{API}/{hot}/entries/{eid}/class", json={"service_class": "nope"}).json()["error"]["code"] == "unknown_service_class"
    assert client.post(f"{API}/{hot}/entries/{eid}/class", json={"service_class": "Bad Class"}).status_code == 422
    assert client.post(f"{API}/{hot}/entries/999999/class", json={"service_class": "priority"}).status_code == 404
    assert client.post(f"{API}/{hot}/entries/{eid}/class", json={"service_class": "priority"}).status_code == 200
    row = next(r for r in client.get(f"{API}/{hot}/monitor").json()["customers"] if r["entry_id"] == eid)
    assert row["sla_target_min"] == 2 and row["service_class"] == "priority" and row["status"] == "breached"


def test_classes_can_only_be_changed_for_waiting_customers(client, db, hot):
    put(client, hot)
    put(client, hot, "priority", max_wait_min=2)
    done = db.scalar(select(QueueEntry.id).where(QueueEntry.queue_id == hot, QueueEntry.status == "completed"))
    r = client.post(f"{API}/{hot}/entries/{done}/class", json={"service_class": "priority"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "entry_not_waiting"


def test_existing_entry_endpoint_unchanged_and_accepts_an_optional_class(client, db):
    qid = client.post("/api/v1/queues", json={"name": "Desk"}).json()["id"]
    plain = client.post(f"/api/v1/queues/{qid}/entries")                         # no body: exactly as before
    assert plain.status_code == 201 and plain.json()["service_class"] is None
    r = client.post(f"/api/v1/queues/{qid}/entries", json={"service_class": "priority"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_service_class"
    assert client.post(f"/api/v1/queues/{qid}/entries", json={"service_class": "BAD"}).status_code == 422
    put(client, qid, max_wait_min=5)
    put(client, qid, "priority", max_wait_min=2)
    ok = client.post(f"/api/v1/queues/{qid}/entries", json={"service_class": "priority"})
    assert ok.status_code == 201 and ok.json()["service_class"] == "priority"
    m = client.get(f"{API}/{qid}/monitor").json()
    assert {(r["service_class"], r["sla_target_min"]) for r in m["customers"]} == {("standard", 5), ("priority", 2)}


def test_monitor_follows_live_data(client, db, hot):
    put(client, hot, max_wait_min=30)
    assert client.get(f"{API}/{hot}/monitor").json()["waiting"] == 12
    add_waiting(db, hot, 3, minutes_ago=1)
    assert client.get(f"{API}/{hot}/monitor").json()["waiting"] == 15


# ---------------------------------------------------------------- performance and compliance
def test_compliance_score_is_computed_from_completed_customers_and_matches_the_database(client, db, hot):
    put(client, hot, max_wait_min=5)
    p = client.get(f"{API}/{hot}/performance", params={"window_minutes": 60, "lookback_hours": 24, "bucket_minutes": 60}).json()
    # independent recomputation from raw entries
    rows = db.execute(select(QueueEntry.arrival_time, QueueEntry.service_start_time).where(
        QueueEntry.queue_id == hot, QueueEntry.status == "completed")).all()
    waits = [(s - a).total_seconds() / 60 for a, s in rows]
    o = p["scores"]["overall"]
    assert 0 < o["n"] <= len(waits)
    in_span = o["n"]
    assert o["met"] + o["breached"] == in_span
    assert o["score"] == pytest.approx(100 * o["met"] / in_span, abs=0.01)
    # if the whole history is inside the lookback the counts equal the raw recomputation
    if in_span == len(waits):
        assert o["met"] == sum(w <= 5 for w in waits)
    s = p["summary"]
    assert (s["served"], s["met_sla"], s["breached_sla"]) == (o["n"], o["met"], o["breached"])
    assert s["avg_wait_min"] == pytest.approx(o["avg_wait_min"]) and s["avg_target_min"] == 5
    sc = p["scores"]
    assert sc["current"]["n"] + sc["historical"]["n"] == sc["overall"]["n"]
    assert sum(b["served"] for b in p["trend"]) == o["n"]
    assert sc["current"]["kind"] == sc["historical"]["kind"] == "observed" and sc["predicted"]["kind"] == "predicted"
    assert "Abandoned customers are not included" in sc["definition"]


def test_score_moves_with_the_target(client, hot):
    low = put(client, hot, max_wait_min=0.5) and client.get(f"{API}/{hot}/performance").json()["scores"]["overall"]["score"]
    high = put(client, hot, max_wait_min=1440) and client.get(f"{API}/{hot}/performance").json()["scores"]["overall"]["score"]
    assert high == 100.0 and low < high


def test_per_class_targets_are_applied_to_each_customer(client, db, hot):
    put(client, hot, max_wait_min=1440)
    put(client, hot, "priority", max_wait_min=0.01)
    first = db.scalar(select(QueueEntry).where(QueueEntry.queue_id == hot, QueueEntry.status == "completed").order_by(QueueEntry.token_number.desc()))
    first.service_class = "priority"
    db.commit()
    p = client.get(f"{API}/{hot}/performance").json()
    cls = {c["service_class"]: c for c in p["per_class"]}
    assert cls["priority"]["n"] == 1 and cls["priority"]["breached"] == 1 and cls["standard"]["score"] == 100.0
    assert p["scores"]["overall"]["breached"] == 1


def test_performance_parameter_validation(client, hot):
    put(client, hot)
    for params in ({"window_minutes": 1}, {"window_minutes": 5000}, {"lookback_hours": 0}, {"lookback_hours": 9999},
                   {"bucket_minutes": 1}, {"window_minutes": 600, "lookback_hours": 5},
                   {"lookback_hours": 720, "bucket_minutes": 5}):
        assert client.get(f"{API}/{hot}/performance", params=params).status_code == 422, params
    assert client.get(f"{API}/9999/performance").status_code == 404


def test_empty_queue_has_no_score_not_a_fake_one(client):
    qid = client.post("/api/v1/queues", json={"name": "Empty"}).json()["id"]
    put(client, qid)
    p = client.get(f"{API}/{qid}/performance").json()
    assert p["scores"]["overall"]["n"] == 0 and p["scores"]["overall"]["score"] is None
    assert p["summary"]["avg_wait_min"] is None and p["scores"]["predicted"]["score"] is None
    m = client.get(f"{API}/{qid}/monitor").json()
    assert m["customers"] == [] and m["counts"] == {"safe": 0, "at_risk": 0, "critical": 0, "breached": 0}


def test_synthetic_queue_is_labelled_and_analysable(client, db):
    qid = load_history(db, history(n=200, seed=4), synthetic=True, name="Synth")
    put(client, qid, max_wait_min=5)
    p = client.get(f"{API}/{qid}/performance").json()
    assert p["provenance"]["is_synthetic"] and p["as_of_basis"] == "latest_activity_of_synthetic_queue"
    assert p["scores"]["overall"]["n"] > 0


# ---------------------------------------------------------------- recommendations
def snapshot(db, qid):
    db.expire_all()
    return [(c.id, c.status, c.current_load) for c in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == qid).order_by(ServiceCounter.id))]


def test_no_recommendation_when_nobody_is_at_risk(client, db, hot):
    put(client, hot, max_wait_min=1440)
    r = client.post(f"{API}/{hot}/recommendations", json={"replications": 3}).json()
    assert r["needed"] is False and "No waiting customer" in r["message"]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(InterventionHistory)) == 0


def test_recommendations_explain_and_validate_with_the_simulation(client, db, hot):
    before = snapshot(db, hot)
    put(client, hot, max_wait_min=8)
    m = client.get(f"{API}/{hot}/monitor").json()
    assert m["counts"]["at_risk"] + m["counts"]["critical"] > 0
    r = client.post(f"{API}/{hot}/recommendations", json={"replications": 3, "horizon_min": 30}).json()
    assert r["needed"] and r["simulation_only"] and r["executed"] is False and r["queue"]["id"] == hot
    assert r["reasons"] and any("waiting" in x for x in r["reasons"])
    assert r["baseline"]["kind"] == "simulated" and r["target_min"] == 8
    assert 1 <= len(r["candidates"]) <= 3
    for c in r["candidates"]:
        assert c["kind"] == "simulated" and "mean" in c["expected_wait_reduction_min"] and "p95_within_target" in c
        assert c["record_id"] is None                       # nothing stored unless asked
    best = r["candidates"][0]
    assert best["rank"] == 1 and best["expected_wait_reduction_min"]["mean"] > 0
    assert r["capacity_gap"]["required_capacity_per_min"] > r["capacity_gap"]["current_capacity_per_min"] or r["capacity_gap"]["extra_capacity_per_min"] == 0
    assert "never changes a counter" in r["disclaimer"]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(InterventionHistory)) == 0
    assert snapshot(db, hot) == before                       # no real change


def test_recommendation_is_reproducible_and_can_be_sent_to_the_approval_workflow(client, db, hot):
    put(client, hot, max_wait_min=8)
    body = {"replications": 3, "horizon_min": 30, "seed": 5}
    a = client.post(f"{API}/{hot}/recommendations", json=body).json()
    b = client.post(f"{API}/{hot}/recommendations", json=body).json()
    key = lambda r: [(c["key"], c["expected_wait_reduction_min"]["mean"]) for c in r["candidates"]]  # noqa: E731
    assert key(a) == key(b) and a["reproducibility"]["config_hash"] == b["reproducibility"]["config_hash"]
    kept = client.post(f"{API}/{hot}/recommendations", json={**body, "persist": True}).json()
    assert kept["persisted"] and kept["evaluation_id"] and all(c["record_id"] for c in kept["candidates"])
    hist = client.get(f"/api/v1/interventions/{hot}/history").json()["interventions"]
    assert hist and {h["status"] for h in hist} == {"proposed"} and all(h["executed_by_linezero"] is False for h in hist)


def test_recommendation_validation(client, hot):
    put(client, hot)
    for bad in ({"replications": 1}, {"horizon_min": 1}, {"seed": -1}, {"bogus": 1}):
        assert client.post(f"{API}/{hot}/recommendations", json=bad).status_code == 422
    assert client.post(f"{API}/9999/recommendations", json={}).status_code == 404


def test_recommendation_without_active_counters_degrades_honestly(client, db, hot):
    for c in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == hot)).all():
        c.status = "paused"
    db.commit()
    put(client, hot, max_wait_min=30)
    r = client.post(f"{API}/{hot}/recommendations", json={"replications": 3}).json()
    assert r["needed"] and r["candidates"] == [] and any("No counter is active" in x for x in r["reasons"])


# ---------------------------------------------------------------- summary
def test_summary_covers_every_queue(client, db, hot):
    other = client.post("/api/v1/queues", json={"name": "NoSla"}).json()["id"]
    put(client, hot, max_wait_min=8)
    rows = {r["queue_id"]: r for r in client.get(f"{API}/summary").json()["queues"]}
    assert rows[other]["configured"] is False and "counts" not in rows[other]
    assert rows[hot]["configured"] and rows[hot]["standard_target_min"] == 8 and sum(rows[hot]["counts"].values()) == 12
