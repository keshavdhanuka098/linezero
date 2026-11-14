from tests.helpers import make_counter, make_queue

API = "/api/v1"


def test_counter_create_list_get(client):
    q = make_queue(client)
    c = make_counter(client, q["id"], "Desk 1", service_rate=0.5)
    assert c["status"] == "active" and c["current_load"] == 0 and c["service_rate"] == 0.5
    assert client.get(f"{API}/counters", params={"queue_id": q["id"]}).json()[0]["id"] == c["id"]
    assert client.get(f"{API}/counters/{c['id']}").json()["name"] == "Desk 1"


def test_counter_validation_and_errors(client):
    q = make_queue(client)
    make_counter(client, q["id"], "Dup")
    r = client.post(f"{API}/counters", json={"queue_id": q["id"], "name": "Dup"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "counter_name_taken"
    assert client.post(f"{API}/counters", json={"queue_id": 9999, "name": "X"}).status_code == 404
    assert client.post(f"{API}/counters", json={"queue_id": q["id"], "name": "X", "service_rate": 0}).status_code == 422
    assert client.post(f"{API}/counters", json={"queue_id": q["id"], "name": "X", "status": "bad"}).status_code == 422
    assert client.get(f"{API}/counters/9999").status_code == 404
    assert client.patch(f"{API}/counters/9999", json={"name": "z"}).status_code == 404
    assert client.patch(f"{API}/counters/1", json={}).status_code == 422


def test_pause_resume_and_status_update(client):
    q = make_queue(client)
    c = make_counter(client, q["id"])
    assert client.post(f"{API}/counters/{c['id']}/pause").json()["status"] == "paused"
    assert client.post(f"{API}/counters/{c['id']}/pause").json()["status"] == "paused"
    assert client.post(f"{API}/counters/{c['id']}/resume").json()["status"] == "active"
    r = client.patch(f"{API}/counters/{c['id']}", json={"status": "closed", "service_rate": 2.0, "name": "Renamed"})
    assert r.json() == {**c, "status": "closed", "service_rate": 2.0, "name": "Renamed"}
    events = [e["event_type"] for e in client.get(f"{API}/queues/{q['id']}/events").json()]
    assert events.count("counter_paused") == 1 and events.count("counter_resumed") == 1
    assert "counter_closed" in events and "counter_updated" in events


def test_paused_counter_receives_no_customers(client):
    q = make_queue(client)
    c1 = make_counter(client, q["id"], "C1")
    c2 = make_counter(client, q["id"], "C2")
    client.post(f"{API}/counters/{c1['id']}/pause")
    for _ in range(2):
        client.post(f"{API}/queues/{q['id']}/entries")
    r = client.post(f"{API}/queues/{q['id']}/serve-next")
    assert r.json()["counter"]["id"] == c2["id"]
    assert client.post(f"{API}/queues/{q['id']}/serve-next").json()["error"]["code"] == "no_available_counter"
    r = client.post(f"{API}/queues/{q['id']}/serve-next", json={"counter_id": c1["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "counter_unavailable"
    client.post(f"{API}/counters/{c1['id']}/resume")
    assert client.post(f"{API}/queues/{q['id']}/serve-next").status_code == 200


def test_pausing_busy_counter_lets_current_customer_finish(client):
    q = make_queue(client)
    c = make_counter(client, q["id"])
    e = client.post(f"{API}/queues/{q['id']}/entries").json()
    client.post(f"{API}/queues/{q['id']}/serve-next")
    assert client.post(f"{API}/counters/{c['id']}/pause").json()["current_load"] == 1
    assert client.post(f"{API}/queues/{q['id']}/entries/{e['id']}/complete").status_code == 200
    assert client.get(f"{API}/counters/{c['id']}").json()["current_load"] == 0
