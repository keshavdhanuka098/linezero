API = "/api/v1/simulations"
CFG = dict(arrival_rate=1.0, mean_service_time=1.5, num_counters=2, duration=500, seed=42)


def run(client, **over):
    r = client.post(f"{API}/run", json={"name": "t", "configuration": {**CFG, **over}})
    assert r.status_code == 201, r.text
    return r.json()


def test_run_stores_configuration_and_results(client):
    out = run(client)
    assert out["status"] == "completed" and out["name"] == "t" and out["seed"] == 42
    assert out["configuration"]["num_counters"] == 2
    assert out["results"]["total_arrivals"] > 0 and out["results"]["seed_used"] == 42
    assert out["runtime_ms"] >= 0 and out["created_at"].endswith("+00:00") or out["created_at"].endswith("Z")
    fetched = client.get(f"{API}/{out['id']}").json()
    assert fetched["results"] == out["results"] and fetched["configuration"] == out["configuration"]
    assert [s["id"] for s in client.get(API).json()] == [out["id"]]


def test_same_seed_gives_identical_results_via_api(client):
    a, b = run(client), run(client)
    assert a["id"] != b["id"] and a["results"] == b["results"]
    assert run(client, seed=43)["results"] != a["results"]


def test_unseeded_run_stores_resolved_seed(client):
    cfg = {k: v for k, v in CFG.items() if k != "seed"}
    out = client.post(f"{API}/run", json={"configuration": cfg}).json()
    assert isinstance(out["seed"], int) and out["configuration"]["seed"] == out["seed"]
    replay = run(client, seed=out["seed"])
    assert replay["results"]["total_arrivals"] == out["results"]["total_arrivals"]


def test_run_validation_errors(client):
    for bad in ({"num_counters": 0}, {"arrival_rate": -1}, {"abandonment_enabled": True},
                {"arrival_distribution": "nope"}, {"record_trace": True}, {"duration": 0}):
        r = client.post(f"{API}/run", json={"configuration": {**CFG, **bad}})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] in ("validation_error", "trace_not_supported")
    assert client.post(f"{API}/run", json={}).status_code == 422
    assert client.get(f"{API}/9999").status_code == 404
    assert client.get(f"{API}/9999").json()["error"]["code"] == "simulation_not_found"


def test_compare_configurations(client):
    body = {
        "seed": 5,
        "configurations": [
            {"name": "2 counters", "configuration": {**CFG, "seed": None, "num_counters": 2, "arrival_rate": 1.2}},
            {"name": "3 counters", "configuration": {**CFG, "seed": None, "num_counters": 3, "arrival_rate": 1.2}},
        ],
    }
    r = client.post(f"{API}/compare", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert len(out["runs"]) == 2 and all(run_["seed"] == 5 for run_ in out["runs"])
    assert all(run_["comparison_id"] == out["comparison_id"] for run_ in out["runs"])
    wait = out["comparison"]["metrics"]["avg_waiting_time"]
    assert wait["best_index"] == 1 and wait["values"][1] <= wait["values"][0]
    assert out["comparison"]["labels"] == ["2 counters", "3 counters"]
    stored = client.get(API, params={"comparison_id": out["comparison_id"]}).json()
    assert len(stored) == 2


def test_compare_needs_at_least_two(client):
    r = client.post(f"{API}/compare", json={"configurations": [{"configuration": CFG}]})
    assert r.status_code == 422


def test_reset_and_delete(client):
    a = run(client)
    run(client)
    assert client.delete(f"{API}/{a['id']}").status_code == 204
    assert client.delete(f"{API}/{a['id']}").status_code == 404
    assert client.delete(API).json() == {"deleted": 1}
    assert client.get(API).json() == []
