"""Outcome learning API: measured vs reported vs synthetic outcomes, guards, learning statistics."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import InterventionHistory
from tests.adaptive_helpers import add_waiting, history, load_history, pause_counters, shift_to_now

API = "/api/v1/interventions"
BODY = {"replications": 4, "horizon_min": 45, "seed": 11}


def applied_intervention(client, db, qid, minutes_ago=50.0):
    r = client.post(f"{API}/{qid}/evaluate", json=BODY).json()
    rid = next(c["record_id"] for c in r["candidates"] if c["key"] == r["recommended_key"])
    assert client.post(f"{API}/item/{rid}/approve", json={"operator": "ana"}).status_code == 200
    row = db.get(InterventionHistory, rid)
    row.decided_at = datetime.now(timezone.utc) - timedelta(hours=3)  # the approval happened earlier
    db.commit()
    at = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    assert client.post(f"{API}/item/{rid}/applied", json={"operator": "ana", "applied_at": at}).status_code == 200
    return rid


@pytest.fixture
def live(db):
    df = history(n=700, lam=0.7, seed=5, speeds=(1, 1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1, 1), nominal_rate=0.25, name="Live")
    pause_counters(db, qid, 2)
    add_waiting(db, qid, 12)
    return qid


def test_guards(client, db, live):
    assert client.post(f"{API}/item/9999/outcome", json={"operator": "a"}).status_code == 404
    r = client.post(f"{API}/{live}/evaluate", json=BODY).json()
    rid = r["candidates"][0]["record_id"]
    early = client.post(f"{API}/item/{rid}/outcome", json={"operator": "a"})  # still only proposed
    assert early.status_code == 409 and early.json()["error"]["code"] == "invalid_transition"
    assert client.get(f"{API}/999/learning").status_code == 404
    rid = applied_intervention(client, db, live)
    for bad in ({"operator": "a", "window_minutes": 1}, {"operator": "a", "mode": "x"}, {}, {"operator": "a", "bogus": 1}):
        assert client.post(f"{API}/item/{rid}/outcome", json=bad).status_code == 422
    assert client.post(f"{API}/item/{rid}/outcome", json={"operator": "a", "mode": "manual"}).status_code == 422


def test_observed_outcome_on_a_real_queue_is_verified_and_stored(client, db, live):
    rid = applied_intervention(client, db, live, minutes_ago=50)
    out = client.post(f"{API}/item/{rid}/outcome", json={"operator": "ana", "window_minutes": 20, "note": "Friday"})
    assert out.status_code == 200, out.text
    iv = out.json()["intervention"]
    assert iv["status"] == "evaluated" and iv["outcome_verification"] == "verified_real_observation"
    o = iv["outcome"]
    assert o["mode"] == "observe" and o["status"] == "ok" and o["recorded_by"] == "ana"
    assert o["pre"]["customers_served"] >= 10 and o["post"]["customers_served"] >= 10
    assert o["comparison"]["expected_wait_reduction_min"] is not None and o["caveats"]
    assert iv["executed_by_linezero"] is False and iv["result_kind"] == "verified_real_observation"
    assert iv["calibration_eligible"] is (not o["confounders"])
    assert client.post(f"{API}/item/{rid}/outcome", json={"operator": "ana"}).status_code == 409  # only once


def test_window_not_elapsed_records_nothing(client, db, live):
    rid = applied_intervention(client, db, live, minutes_ago=5)
    r = client.post(f"{API}/item/{rid}/outcome", json={"operator": "ana", "window_minutes": 30})
    assert r.status_code == 409 and r.json()["error"]["code"] == "outcome_window_not_elapsed"
    item = client.get(f"{API}/item/{rid}").json()["intervention"]
    assert item["status"] == "applied" and item["outcome"] is None


def test_manual_outcome_is_labelled_operator_reported_and_never_calibration_eligible(client, db, live):
    rid = applied_intervention(client, db, live, minutes_ago=3)
    r = client.post(f"{API}/item/{rid}/outcome", json={
        "operator": "ana", "mode": "manual", "observed": {"avg_wait_min": 2.5, "n_customers": 40}})
    iv = r.json()["intervention"]
    assert iv["outcome_verification"] == "operator_reported" and iv["calibration_eligible"] is False
    assert iv["outcome"]["mode"] == "manual" and "did not measure" in iv["outcome"]["caveats"][0]
    assert "not measured by LineZero" in r.json()["message"]


def test_synthetic_queue_outcomes_are_never_called_verified(client, db):
    df = history(n=700, lam=0.7, seed=6, speeds=(1, 1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1, 1), nominal_rate=0.25, synthetic=True, name="Syn")
    pause_counters(db, qid, 2)
    add_waiting(db, qid, 12)
    rid = applied_intervention(client, db, qid)
    iv = client.post(f"{API}/item/{rid}/outcome", json={"operator": "ana", "window_minutes": 20}).json()
    assert iv["intervention"]["outcome_verification"] == "synthetic_observation"
    assert iv["intervention"]["calibration_eligible"] is False and "SYNTHETIC" in iv["message"]
    ln = client.get(f"{API}/{qid}/learning").json()
    assert ln["summary"]["counts"]["synthetic_observation"] == 1 and ln["summary"]["verified_real"]["n"] == 0
    assert ln["provenance"]["is_synthetic"] is True


def test_learning_statistics_only_count_verified_real_outcomes(client, db, live):
    empty = client.get(f"{API}/{live}/learning").json()
    assert empty["summary"]["counts"]["verified_real_observation"] == 0 and empty["advice"]["recalibrate"] is False
    rid = applied_intervention(client, db, live)
    client.post(f"{API}/item/{rid}/outcome", json={"operator": "ana", "window_minutes": 20})
    ln = client.get(f"{API}/{live}/learning").json()
    assert ln["status_counts"]["evaluated"] == 1 and len(ln["outcomes"]) == 1
    assert ln["summary"]["counts"]["verified_real_observation"] == 1
    assert "at least 5" in ln["advice"]["reason"]  # one outcome is never enough to judge the model
    assert "never presented as real-world verification" in ln["note"]
