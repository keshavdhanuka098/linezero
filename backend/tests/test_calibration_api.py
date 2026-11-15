"""Calibration API + service: versioning, validation gate, rollback, evaluation, provenance, constraints."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import CalibrationRecord, CalibrationStatus, QueueEntry, ServiceRecord
from tests.adaptive_helpers import history, load_history

API = "/api/v1/calibration"
WRONG = 0.15  # configured counter rate; the data were generated at 0.25


@pytest.fixture
def real_queue(db):
    return load_history(db, history(n=900, seed=3), nominal_rate=WRONG, synthetic=False, name="Real")


def test_unknown_queue_is_404(client):
    for path in ("status", "versions", "drift", "evaluation", "error-history"):
        r = client.get(f"{API}/999/{path}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "queue_not_found"
    assert client.post(f"{API}/999/run").status_code == 404


def test_status_before_any_calibration_uses_nominal_configuration(client, real_queue):
    s = client.get(f"{API}/{real_queue}/status").json()
    assert s["model"] == "nominal_configuration" and s["active"] is None
    assert s["observations"]["ready"] is True and s["observations"]["served"] >= 800
    assert s["provenance"]["observations"] == "observed_real_data" and s["provenance"]["notice"] is None
    assert s["nominal_parameters"]["service_rate_per_min"] == pytest.approx(WRONG)


def test_synthetic_queue_is_clearly_labelled_everywhere(client, db):
    qid = load_history(db, history(n=300, seed=4), synthetic=True, name="Synth")
    for url in (f"{API}/{qid}/status", f"{API}/{qid}/drift", f"{API}/{qid}/versions", f"{API}/{qid}/evaluation"):
        p = client.get(url).json()["provenance"]
        assert p["is_synthetic"] is True and "SYNTHETIC" in p["notice"]
    run = client.post(f"{API}/{qid}/run", json={}).json()
    assert run["provenance"]["is_synthetic"] is True and run["record"]["is_synthetic"] is True


def test_insufficient_observations_are_handled_safely(client, db):
    qid = load_history(db, history(n=30, seed=4), name="Tiny")
    r = client.post(f"{API}/{qid}/run", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] == "insufficient_data" and body["persisted"] is False and body["reasons"]
    assert client.get(f"{API}/{qid}/versions").json()["versions"] == []
    empty = client.post("/api/v1/queues", json={"name": "Empty"}).json()["id"]
    assert client.post(f"{API}/{empty}/run", json={}).json()["decision"] == "insufficient_data"
    assert client.get(f"{API}/{empty}/drift").json()["status"] == "insufficient_data"


def test_dry_run_saves_nothing_and_run_creates_version_1(client, real_queue):
    dry = client.post(f"{API}/{real_queue}/run", json={"dry_run": True}).json()
    assert dry["decision"] == "accepted" and dry["persisted"] is False and dry["record"] is None
    assert client.get(f"{API}/{real_queue}/versions").json()["versions"] == []

    run = client.post(f"{API}/{real_queue}/run", json={}).json()
    rec = run["record"]
    assert run["persisted"] and rec["version"] == 1 and rec["status"] == "active" and rec["source"] == "calibration"
    assert rec["parameters"]["service_rate_per_min"] == pytest.approx(0.25, rel=0.15)
    assert rec["candidate_metrics"]["mae_s"] < rec["incumbent_metrics"]["mae_s"]
    assert rec["training_window"]["end"] < rec["validation_window"]["start"]
    assert rec["comparison"]["series"] and rec["estimates"]["arrival"]["ci95"]
    s = client.get(f"{API}/{real_queue}/status").json()
    assert s["model"] == "calibration_v1" and s["versions"] == 1


def test_a_candidate_that_fails_validation_is_stored_as_rejected_and_changes_nothing(client, real_queue):
    client.post(f"{API}/{real_queue}/run", json={})
    r = client.post(f"{API}/{real_queue}/run", json={"min_improvement_pct": 50}).json()
    assert r["decision"] == "rejected" and r["persisted"] is True
    assert r["record"]["status"] == "rejected" and r["record"]["version"] is None
    vs = client.get(f"{API}/{real_queue}/versions").json()["versions"]
    assert [v["status"] for v in vs] == ["rejected", "active"]
    assert client.get(f"{API}/{real_queue}/versions", params={"include_rejected": False}).json()["versions"][0]["version"] == 1
    assert client.get(f"{API}/{real_queue}/status").json()["active"]["version"] == 1


def _make_second_version(client, qid):
    """Re-run until a candidate is accepted; the data are fixed so this is deterministic."""
    for frac in (0.2, 0.25, 0.35, 0.4, 0.5):
        r = client.post(f"{API}/{qid}/run", json={"validation_fraction": frac, "min_improvement_pct": 0}).json()
        if r["decision"] == "accepted":
            return r["record"]
    pytest.skip("no accepted second candidate on this data")  # pragma: no cover


def test_versions_are_append_only_and_rollback_restores_an_earlier_version(client, real_queue):
    v1 = client.post(f"{API}/{real_queue}/run", json={}).json()["record"]
    v2 = _make_second_version(client, real_queue)
    assert v2["version"] == 2 and v2["incumbent_version"] == 1
    vs = {v["version"]: v for v in client.get(f"{API}/{real_queue}/versions").json()["versions"] if v["version"]}
    assert vs[1]["status"] == "superseded" and vs[2]["status"] == "active"

    bad = client.post(f"{API}/{real_queue}/rollback", json={"version": 9, "reason": "nope", "operator": "ana"})
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "calibration_version_not_found"
    same = client.post(f"{API}/{real_queue}/rollback", json={"version": 2, "reason": "same one", "operator": "ana"})
    assert same.status_code == 409

    rb = client.post(f"{API}/{real_queue}/rollback",
                     json={"version": 1, "reason": "v2 looked worse in review", "operator": "ana"}).json()
    rec = rb["record"]
    assert rec["version"] == 3 and rec["source"] == "rollback" and rec["status"] == "active"
    assert rec["rollback_to_version"] == 1 and rec["parameters"] == v1["parameters"]
    assert "ana" in rec["reason"]
    after = {v["version"]: v["status"] for v in client.get(f"{API}/{real_queue}/versions").json()["versions"] if v["version"]}
    assert after == {1: "superseded", 2: "superseded", 3: "active"}  # nothing deleted or rewritten
    assert client.get(f"{API}/{real_queue}/status").json()["model"] == "calibration_v3"


def test_database_refuses_two_active_versions(db, real_queue):
    base = dict(queue_id=real_queue, status=CalibrationStatus.ACTIVE.value, source="calibration", parameters={},
                decision="accepted")
    db.add(CalibrationRecord(version=1, **base))
    db.commit()
    db.add(CalibrationRecord(version=2, **base))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_evaluation_compares_predicted_to_actual_and_tracks_error_over_time(client, real_queue):
    before = client.get(f"{API}/{real_queue}/evaluation").json()
    assert before["calibrated"] is None and before["n"] > 0 and before["nominal"]["mae_s"] > 0  # nominal only
    client.post(f"{API}/{real_queue}/run", json={})
    ev = client.get(f"{API}/{real_queue}/evaluation").json()
    assert ev["out_of_sample"] is True and ev["stored"] is False and ev["n"] >= 30
    assert ev["calibrated"]["mae_s"] < ev["nominal"]["mae_s"] and ev["mae_improvement_vs_nominal_pct"] > 0
    assert {"mae_s", "rmse_s", "mape_pct", "mean_error_s"} <= set(ev["calibrated"])
    assert ev["series"] and {"actual_min", "predicted_min", "incumbent_min"} <= set(ev["series"][0])
    assert any("same ones the acceptance decision" in n for n in ev["notes"])
    assert client.get(f"{API}/{real_queue}/error-history").json()["evaluations"] == []  # GET stores nothing

    stored = client.post(f"{API}/{real_queue}/evaluation", json={}).json()
    assert stored["stored"] is True
    client.post(f"{API}/{real_queue}/evaluation", json={})
    hist = client.get(f"{API}/{real_queue}/error-history").json()["evaluations"]
    assert len(hist) == 4 and {e["model"] for e in hist} == {"nominal", "calibrated"}
    assert all(e["out_of_sample"] for e in hist)

    in_sample = client.get(f"{API}/{real_queue}/evaluation", params={"scope": "all"}).json()
    assert in_sample["out_of_sample"] is False and in_sample["n"] > ev["n"]
    assert any("in-sample" in n for n in in_sample["notes"])


def test_drift_endpoint_reports_signals_and_basis(client, real_queue):
    d = client.get(f"{API}/{real_queue}/drift").json()
    assert d["status"] == "ok" and set(d["signals"]) == {"arrival_rate", "service_time", "waiting_time"}
    assert "no calibration yet" in d["reference_basis"] and d["drift_detected"] is False
    client.post(f"{API}/{real_queue}/run", json={})
    d2 = client.get(f"{API}/{real_queue}/drift").json()
    assert d2["active_version"] == 1 and "active calibration" in d2["reference_basis"]


def test_request_validation(client, real_queue):
    for bad in ({"validation_fraction": 0.9}, {"min_improvement_pct": -1}, {"lookback_minutes": 0}, {"bogus": 1}):
        r = client.post(f"{API}/{real_queue}/run", json=bad)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", bad
    assert client.post(f"{API}/{real_queue}/rollback", json={"version": 0, "reason": "x", "operator": ""}).status_code == 422
    assert client.get(f"{API}/{real_queue}/evaluation", params={"scope": "weird"}).status_code == 422


def test_calibration_never_modifies_real_queue_data(client, db, real_queue):
    def snapshot():
        return (db.scalar(select(func.count()).select_from(QueueEntry)), db.scalar(select(func.count()).select_from(ServiceRecord)),
                db.scalar(select(func.sum(ServiceRecord.waiting_time))))
    db.expire_all()
    before = snapshot()
    client.post(f"{API}/{real_queue}/run", json={})
    client.post(f"{API}/{real_queue}/evaluation", json={})
    db.expire_all()
    assert snapshot() == before


def test_migration_0003_adds_only_new_tables_and_round_trips(tmp_path):
    """Upgrade 0002 -> 0003 keeps existing data; downgrade drops exactly the four new tables."""
    import sqlite3

    from alembic import command

    from app.core.migrations import alembic_config

    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "0002")
    con = sqlite3.connect(tmp_path / "m.db")
    con.execute("INSERT INTO queues(name,status,last_token,is_synthetic,created_at,updated_at) "
                "VALUES('keep','active',0,0,'2026-01-01','2026-01-01')")
    con.commit()
    before = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    command.upgrade(cfg, "head")
    con = sqlite3.connect(tmp_path / "m.db")
    after = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert after - before == {"calibration_records", "calibration_evaluations", "risk_events", "intervention_history"}
    assert con.execute("SELECT name FROM queues").fetchall() == [("keep",)]
    con.close()
    command.downgrade(cfg, "0002")
    con = sqlite3.connect(tmp_path / "m.db")
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == before
    assert con.execute("SELECT name FROM queues").fetchall() == [("keep",)]
    con.close()
    command.upgrade(cfg, "head")
