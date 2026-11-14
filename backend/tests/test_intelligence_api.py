"""API-level tests for Part 2. Synthetic queues come from the Part 1 generator (SimPy engine)."""
import pytest
from sqlalchemy import select

from app.models import Queue
from app.seed.generate_demo_data import generate
from tests.helpers import make_counter, make_queue

V1 = "/api/v1"


@pytest.fixture
def seeded(db, client):
    generate(db, ["normal", "insufficient_capacity", "uneven_utilization"], customers=400, seed=5)
    return {q.scenario: q.id for q in db.scalars(select(Queue)).all()}


def real_queue(client, counters=2):
    q = make_queue(client, "Real")
    for i in range(counters):
        make_counter(client, q["id"], f"C{i + 1}", service_rate=0.5)
    return q["id"]


def test_part1_endpoints_still_work(client, seeded):
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get(f"{V1}/queues").json()) == 3
    r = client.post(f"{V1}/simulations/run", json={"configuration": {
        "arrival_rate": 1.0, "mean_service_time": 1.5, "num_counters": 2, "duration": 200, "seed": 1}})
    assert r.status_code == 201
    assert client.get("/openapi.json").status_code == 200 and client.get("/docs").status_code == 200


def test_prediction_baseline_on_live_queue_is_stored(client):
    qid = real_queue(client)
    for _ in range(3):
        client.post(f"{V1}/queues/{qid}/entries")
    r = client.get(f"{V1}/predictions/{qid}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["prediction_method"] == "statistical_baseline" and p["predicted_waiting_time_s"] == pytest.approx(120.0)
    assert p["prediction_id"] and p["assumptions"] and p["model"]["training"]["status"] == "no_history"
    assert p["uncertainty"] is None
    hist = client.get(f"{V1}/predictions/{qid}/history").json()
    assert hist[0]["prediction_id"] == p["prediction_id"] and hist[0]["actual_waiting_time_s"] is None


def test_prediction_errors(client):
    assert client.get(f"{V1}/predictions/999").status_code == 404
    q = make_queue(client)
    r = client.get(f"{V1}/predictions/{q['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_active_counters"


def test_prediction_on_synthetic_history_and_backtest(client, seeded):
    p = client.get(f"{V1}/predictions/{seeded['normal']}?store=false").json()
    assert p["is_synthetic"] and p["prediction_id"] is None and p["predicted_waiting_time_s"] >= 0
    assert p["model"]["training"]["status"] in ("trained", "insufficient_data")
    ev = client.post(f"{V1}/predictions/evaluate", json={"queue_id": seeded["normal"], "mode": "backtest"}).json()
    tr = ev["backtest"]["training_report"]
    assert tr["status"] == "trained" and ev["backtest"]["baseline_metrics_all_history"]["mae_s"] is not None
    assert {"statistical_baseline", "linear_regression", "random_forest"} == set(tr["validation_metrics"])


def test_evaluate_stored_predictions_with_actuals(client):
    qid = real_queue(client)
    ids = [client.get(f"{V1}/predictions/{qid}").json()["prediction_id"] for _ in range(2)]
    empty = client.post(f"{V1}/predictions/evaluate", json={"queue_id": qid}).json()
    assert empty["metrics"]["n"] == 0 and empty["metrics"]["mae_s"] is None and empty["notes"]
    ev = client.post(f"{V1}/predictions/evaluate", json={"queue_id": qid, "actuals": [
        {"prediction_id": ids[0], "actual_waiting_time_s": 10}, {"prediction_id": ids[1], "actual_waiting_time_s": 20}]}).json()
    assert ev["metrics"]["n"] == 2 and ev["metrics"]["mae_s"] == pytest.approx(15.0)
    assert ev["metrics"]["rmse_s"] == pytest.approx((250) ** 0.5)
    bad = client.post(f"{V1}/predictions/evaluate", json={"queue_id": qid, "actuals": [
        {"prediction_id": 9999, "actual_waiting_time_s": 1}]})
    assert bad.status_code == 422
    assert client.post(f"{V1}/predictions/evaluate", json={"queue_id": 999}).status_code == 404


def test_evaluate_matches_next_real_arrival(client):
    qid = real_queue(client, 1)
    pid = client.get(f"{V1}/predictions/{qid}").json()["prediction_id"]
    e = client.post(f"{V1}/queues/{qid}/entries").json()
    client.post(f"{V1}/queues/{qid}/serve-next")
    ev = client.post(f"{V1}/predictions/evaluate", json={"queue_id": qid}).json()
    assert ev["predictions_evaluated"] == 1 and ev["predictions"][0]["matched_entry_id"] == e["id"]
    assert ev["predictions"][0]["actual_waiting_time_s"] >= 0


def test_bottleneck_analysis_is_evidence_based_and_persisted(client, seeded):
    r = client.post(f"{V1}/bottlenecks/analyze", json={"queue_id": seeded["insufficient_capacity"]})
    assert r.status_code == 201, r.text
    body = r.json()
    kinds = {d["bottleneck_type"] for d in body["detections"]}
    assert "capacity_demand_imbalance" in kinds
    for d in body["detections"]:
        assert d["detection_id"] and d["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert d["supporting_metrics"] and d["explanation"] and d["recommendation"] and d["operational_impact"]
    listed = client.get(f"{V1}/bottlenecks", params={"queue_id": seeded["insufficient_capacity"]}).json()
    assert {d["detection_id"] for d in listed} == {d["detection_id"] for d in body["detections"]}
    sev = client.get(f"{V1}/bottlenecks", params={"severity": "CRITICAL"}).json()
    assert all(d["severity"] == "CRITICAL" for d in sev)


def test_bottleneck_uneven_and_healthy(client, seeded):
    u = client.post(f"{V1}/bottlenecks/analyze", json={"queue_id": seeded["uneven_utilization"]}).json()
    assert "uneven_utilization" in {d["bottleneck_type"] for d in u["detections"]}
    n = client.post(f"{V1}/bottlenecks/analyze", json={"queue_id": seeded["normal"]}).json()
    assert "capacity_demand_imbalance" not in {d["bottleneck_type"] for d in n["detections"]}


def test_bottleneck_all_queues_and_errors(client, seeded):
    allq = client.post(f"{V1}/bottlenecks/analyze", json={}).json()
    assert allq["queues_analyzed"] == 3
    assert client.post(f"{V1}/bottlenecks/analyze", json={"queue_id": 999}).status_code == 404
    assert client.post(f"{V1}/bottlenecks/analyze", json={"window_minutes": 5}).status_code == 422
    assert client.get(f"{V1}/bottlenecks", params={"severity": "SEVERE"}).status_code == 422
    empty = real_queue(client)
    r = client.post(f"{V1}/bottlenecks/analyze", json={"queue_id": empty}).json()
    assert r["detection_count"] == 0 and r["by_queue"][0]["notes"]


FAST = {"duration_minutes": 240, "replications": 3, "seed": 1}


def test_optimization_runs_real_simulation_and_is_retrievable(client, seeded):
    qid = seeded["insufficient_capacity"]
    r = client.post(f"{V1}/optimization/run", json={
        "queue_id": qid, "constraints": {"allow_new_counters": 2, "max_cost_per_hour": 5.0}, "simulation": FAST})
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["current_allocation"]["active_counter_count"] == 3
    assert o["proposed_allocation"]["active_counter_count"] in (4, 5)
    imp = o["estimated_improvement"]["avg_waiting_time_min"]
    assert imp["proposed"] < imp["current"] and imp["percent_reduction"] == pytest.approx(
        (imp["current"] - imp["proposed"]) / imp["current"] * 100)
    rq = o["resource_requirements"]
    assert rq["within_constraints"] and rq["cost_per_hour"] <= 5.0 and rq["new_counters_required"] >= 1
    assert "not" in o["details"]["optimality"].lower()
    assert client.get(f"{V1}/optimization/{o['optimization_id']}").json()["explanation"] == o["explanation"]


def test_optimization_errors(client, seeded):
    qid = seeded["insufficient_capacity"]
    assert client.get(f"{V1}/optimization/999").status_code == 404
    assert client.post(f"{V1}/optimization/run", json={"queue_id": 999}).status_code == 404
    r = client.post(f"{V1}/optimization/run", json={"queue_id": qid, "constraints": {"max_cost_per_hour": 0.1},
                                                    "simulation": FAST})
    assert r.status_code == 409 and r.json()["error"]["code"] == "optimization_infeasible"
    q = real_queue(client)
    r = client.post(f"{V1}/optimization/run", json={"queue_id": q, "simulation": FAST})
    assert r.status_code == 422 and r.json()["error"]["code"] == "arrival_rate_required"
    ok = client.post(f"{V1}/optimization/run", json={"queue_id": q, "arrival_rate": 0.4, "simulation": FAST})
    assert ok.status_code == 201
    assert client.post(f"{V1}/optimization/run", json={"queue_id": q, "arrival_rate": 0.4, "bogus": 1}).status_code == 422


def test_analytics_endpoints_shapes_and_filters(client, seeded):
    qid = seeded["normal"]
    for path in ("overview", "arrivals", "waiting-times", "utilization", "peak-hours"):
        r = client.get(f"{V1}/analytics/{path}", params={"queue_id": qid})
        assert r.status_code == 200, (path, r.text)
        b = r.json()
        assert set(b) == {"filters", "meta", "summary", "charts", "tables"} and b["meta"]["contains_synthetic_data"]
        assert b["filters"]["queue_id"] == qid and not b["meta"]["empty"]
    ov = client.get(f"{V1}/analytics/overview", params={"queue_id": qid, "compare_previous": True}).json()
    assert "comparison" in ov["summary"]
    day = client.get(f"{V1}/analytics/arrivals", params={"queue_id": qid, "granularity": "day"}).json()
    assert day["summary"]["granularity"] == "day"


def test_analytics_counter_and_date_filters(client, seeded):
    qid = seeded["normal"]
    cid = client.get(f"{V1}/counters", params={"queue_id": qid}).json()[0]["id"]
    full = client.get(f"{V1}/analytics/overview", params={"queue_id": qid}).json()
    one = client.get(f"{V1}/analytics/overview", params={"queue_id": qid, "counter_id": cid}).json()
    assert one["summary"]["kpis"]["served"] < full["summary"]["kpis"]["served"]
    start, end = full["filters"]["start_date"], full["filters"]["end_date"]
    mid = client.get(f"{V1}/analytics/overview", params={"queue_id": qid, "start_date": start,
                                                         "end_date": start[:10] + "T23:59:59+00:00"}).json()
    assert mid["summary"]["kpis"]["arrivals"] <= full["summary"]["kpis"]["arrivals"]
    assert client.get(f"{V1}/analytics/overview", params={"start_date": end, "end_date": start}).status_code == 422
    assert client.get(f"{V1}/analytics/overview", params={"queue_id": 999}).status_code == 404
    assert client.get(f"{V1}/analytics/overview", params={"counter_id": 99999}).status_code == 404
    other = client.get(f"{V1}/counters", params={"queue_id": seeded["insufficient_capacity"]}).json()[0]["id"]
    assert client.get(f"{V1}/analytics/overview", params={"queue_id": qid, "counter_id": other}).status_code == 422


def test_analytics_empty_queue(client):
    qid = real_queue(client)
    for path in ("overview", "arrivals", "waiting-times", "utilization", "peak-hours"):
        r = client.get(f"{V1}/analytics/{path}", params={"queue_id": qid})
        assert r.status_code == 200 and r.json()["meta"]["empty"] is True
    assert client.get(f"{V1}/analytics/arrivals", params={"granularity": "week"}).status_code == 422


def test_report_lifecycle_and_exports(client, seeded):
    qid = seeded["insufficient_capacity"]
    sim = client.post(f"{V1}/simulations/run", json={"name": "s", "configuration": {
        "arrival_rate": 1.0, "mean_service_time": 1.5, "num_counters": 2, "duration": 200, "seed": 3}}).json()
    opt = client.post(f"{V1}/optimization/run", json={"queue_id": qid, "simulation": FAST,
                                                      "constraints": {"allow_new_counters": 1}}).json()
    requests = [
        {"report_type": "queue_performance", "queue_id": qid},
        {"report_type": "simulation_results", "simulation_id": sim["id"]},
        {"report_type": "prediction_evaluation", "queue_id": seeded["normal"]},
        {"report_type": "bottleneck_analysis", "queue_id": qid},
        {"report_type": "optimization_comparison", "optimization_id": opt["optimization_id"]},
    ]
    ids = []
    for body in requests:
        r = client.post(f"{V1}/reports/generate", json=body)
        assert r.status_code == 201, (body, r.text)
        rep = r.json()
        meta = rep["report_data"]["meta"]
        assert meta["generated_at"] and meta["contains_synthetic_data"] is True and "DATA" in meta["data_notice"]
        assert rep["report_data"]["summary"] and rep["report_data"]["tables"]
        ids.append(rep["report_id"])
    listed = client.get(f"{V1}/reports").json()
    assert {r["report_id"] for r in listed} == set(ids) and "report_data" not in listed[0]
    assert client.get(f"{V1}/reports", params={"report_type": "simulation_results"}).json()[0]["report_type"] == "simulation_results"
    assert client.get(f"{V1}/reports/{ids[0]}").json()["report_data"]["meta"]["report_type"] == "queue_performance"
    csv = client.get(f"{V1}/reports/{ids[0]}/export", params={"format": "csv"})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"] and "data_notice" in csv.text
    assert client.get(f"{V1}/reports/{ids[0]}/export", params={"format": "json"}).json()["meta"]["title"]
    pdf = client.get(f"{V1}/reports/{ids[1]}/export", params={"format": "pdf"})
    assert pdf.status_code in (200, 501)
    if pdf.status_code == 200:
        assert pdf.content.startswith(b"%PDF")


def test_report_errors(client, seeded):
    assert client.get(f"{V1}/reports/999").status_code == 404
    assert client.get(f"{V1}/reports/999/export").status_code == 404
    assert client.post(f"{V1}/reports/generate", json={"report_type": "nope"}).status_code == 422
    assert client.post(f"{V1}/reports/generate", json={"report_type": "queue_performance"}).status_code == 422
    assert client.post(f"{V1}/reports/generate", json={"report_type": "queue_performance", "queue_id": 999}).status_code == 404
    assert client.post(f"{V1}/reports/generate", json={"report_type": "simulation_results"}).status_code == 422
    rid = client.post(f"{V1}/reports/generate", json={"report_type": "queue_performance", "queue_id": seeded["normal"]}).json()["report_id"]
    assert client.get(f"{V1}/reports/{rid}/export", params={"format": "xml"}).status_code == 422
