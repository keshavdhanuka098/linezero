"""Digital Twin HTTP API."""
from tests.helpers import make_counter, make_queue

API = "/api/v1/twin"
CFG = dict(arrival_rate=1.2, mean_service_time=4.0, num_counters=5, duration=120, seed=3)
STRESS = {**CFG, "staff_available": 2, "standby_counters": [4],
          "outages": [{"counter": 0, "start": 30, "end": 100}]}


def test_status_never_exposes_a_key(client):
    body = client.get(f"{API}/status").json()
    assert body["writes_to_real_queues"] is False and "key" not in str(body).lower().replace("gemini_api_key", "")
    assert set(body["gemini"]) == {"configured", "model"}


def test_presets_return_six_valid_scenarios(client):
    out = client.get(f"{API}/presets", params={"num_counters": 4}).json()
    assert [p["id"] for p in out] == ["normal", "arrival_surge", "staff_shortage", "counter_failure",
                                      "slow_service", "peak_hour"]
    assert client.get(f"{API}/presets", params={"num_counters": 0}).status_code == 422


def test_simulate_returns_stats_and_playback(client):
    r = client.post(f"{API}/simulate", json={"configuration": STRESS, "replications": 3, "seed": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stats"]["avg_waiting_time"]["n"] == 3
    pb = body["playback"]
    assert pb["frames"] and pb["customers"] and any(e["type"] == "counter_failure" for e in pb["events"])


def test_simulate_validation_errors(client):
    for bad in ({"outages": [{"counter": 9, "start": 1, "end": 2}]}, {"staff_available": 99},
                {"arrival_rate": 500, "duration": 1000}, {"nope": 1}):
        r = client.post(f"{API}/simulate", json={"configuration": {**CFG, **bad}})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"


def test_compare_accepts_two_to_five_scenarios(client):
    sc = lambda n, **o: {"name": n, "configuration": {**CFG, **o}}  # noqa: E731
    ok = client.post(f"{API}/compare", json={"scenarios": [sc("a"), sc("b", staff_available=3)], "replications": 4})
    assert ok.status_code == 200 and ok.json()["metrics"]["avg_waiting_time"]["values"][1] > \
        ok.json()["metrics"]["avg_waiting_time"]["values"][0]
    assert client.post(f"{API}/compare", json={"scenarios": [sc("a")]}).status_code == 422
    assert client.post(f"{API}/compare", json={"scenarios": [sc(str(i)) for i in range(6)]}).status_code == 422


def test_recommend_and_recover(client):
    rec = client.post(f"{API}/recommend", json={"configuration": STRESS, "replications": 4}).json()
    assert rec["simulation_only"] and rec["recommendations"][0]["improvement"]["avg_waiting_time"]
    auto = client.post(f"{API}/recover", json={"configuration": STRESS, "replications": 4}).json()
    assert auto["mode"] == "automatic" and auto["chosen"] and auto["before_after"]
    assert client.post(f"{API}/recommend", json={"configuration": STRESS, "replications": 1}).status_code == 422


def test_explain_works_without_gemini(client):
    r = client.post(f"{API}/explain", json={"kind": "congestion", "configuration": STRESS, "replications": 3})
    assert r.status_code == 200 and r.json()["source"] == "deterministic" and r.json()["text"]
    assert client.post(f"{API}/explain", json={"kind": "scenarios"}).status_code == 422


def _live_queue(client):
    q = make_queue(client)
    for i in range(3):
        make_counter(client, q["id"], f"C{i + 1}", service_rate=0.5)
    for _ in range(6):
        client.post(f"/api/v1/queues/{q['id']}/entries")
    client.post(f"/api/v1/queues/{q['id']}/serve-next")
    return q


def test_live_state_reflects_real_queue_data(client):
    q = _live_queue(client)
    r = client.get(f"{API}/live/{q['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    m = body["metrics"]
    assert m["queue_length"] == 5 and m["busy_counters"] == 1 and m["active_counters"] == 3
    assert len(body["counters"]) == 3 and len(body["waiting"]) == 5
    assert body["suggested_configuration"]["num_counters"] == 3
    assert client.get(f"{API}/live/9999").status_code == 404


def test_forecast_from_live_state_does_not_change_the_queue(client):
    q = _live_queue(client)
    before = client.get(f"/api/v1/queues/{q['id']}/state").json()
    r = client.get(f"{API}/forecast/{q['id']}", params={"replications": 10, "arrival_rate": 1.0})
    assert r.status_code == 200, r.text
    fc = r.json()
    assert [h["horizon_min"] for h in fc["horizons"]] == [5, 15, 30, 60]
    assert fc["starting_state"]["queue_length"] == 5 and fc["starting_state"]["arrival_rate_source"] == "user_override"
    after = client.get(f"/api/v1/queues/{q['id']}/state").json()
    assert (before["waiting_count"], before["serving_count"]) == (after["waiting_count"], after["serving_count"])


def test_forecast_without_active_counters_is_a_conflict(client):
    q = make_queue(client)
    assert client.get(f"{API}/forecast/{q['id']}").status_code == 409
