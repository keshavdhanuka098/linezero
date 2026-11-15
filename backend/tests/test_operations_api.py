"""Operations loop: overview and automatic cycle never approve or change anything."""
import pytest
from sqlalchemy import select

from app.models import InterventionHistory, ServiceCounter
from tests.adaptive_helpers import add_waiting, history, load_history, pause_counters, shift_to_now

API = "/api/v1/operations"


@pytest.fixture
def hot(db):
    df = history(n=700, lam=0.7, seed=5, speeds=(1, 1, 1, 1, 1))
    qid = load_history(db, shift_to_now(df), speeds=(1, 1, 1, 1, 1), nominal_rate=0.15, name="Hot")
    pause_counters(db, qid, 2)
    add_waiting(db, qid, 14)
    return qid


def test_404(client):
    assert client.get(f"{API}/999/overview").status_code == 404
    assert client.post(f"{API}/999/cycle").status_code == 404


def test_overview_lists_every_loop_stage_with_counts_only(client, hot):
    o = client.get(f"{API}/{hot}/overview").json()
    assert [s["stage"] for s in o["stages"]] == ["observe", "calibrate", "detect", "propose", "approve", "evaluate", "recalibrate"]
    assert o["model"] == "nominal_configuration" and o["open_risks"] == 0
    assert o["provenance"]["observations"] == "observed_real_data" and "never executes" in o["automation"]


def test_cycle_runs_automatic_stages_and_leaves_decisions_to_operators(client, db, hot):
    before = [(x.id, x.status) for x in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == hot))]
    r = client.post(f"{API}/{hot}/cycle", json={"replications": 4}).json()
    steps = {s["step"]: s for s in r["steps"]}
    assert steps["calibrate"]["decision"] == "accepted" and steps["detect_risk"]["events"] >= 1
    assert r["executed"] is False and "Nothing was approved" in r["note"]
    db.expire_all()
    rows = db.scalars(select(InterventionHistory).where(InterventionHistory.queue_id == hot)).all()
    assert all(x.status == "proposed" and not x.executed_by_linezero for x in rows)
    if "evaluation_id" in steps.get("propose_interventions", {}):
        assert rows and r["pending_operator_actions"]
    assert [(x.id, x.status) for x in db.scalars(select(ServiceCounter).where(ServiceCounter.queue_id == hot))] == before
    assert r["overview"]["model"].startswith("calibration_v")


def test_cycle_options_can_skip_stages(client, hot):
    r = client.post(f"{API}/{hot}/cycle", json={"recalibrate": False, "evaluate_interventions": False}).json()
    assert [s["step"] for s in r["steps"]] == ["detect_risk"]
    assert client.post(f"{API}/{hot}/cycle", json={"min_risk_severity": "BAD"}).status_code == 422
