from tests.helpers import make_counter, make_queue

API = "/api/v1"


def test_queue_crud(client):
    q = make_queue(client, "  Pharmacy  ", description="Main desk")
    assert q["name"] == "Pharmacy" and q["status"] == "active" and q["waiting_count"] == 0
    assert client.get(f"{API}/queues").json()[0]["id"] == q["id"]
    detail = client.get(f"{API}/queues/{q['id']}").json()
    assert detail["counters"] == [] and detail["last_token"] == 0
    r = client.put(f"{API}/queues/{q['id']}", json={"name": "Pharmacy 2", "status": "paused"})
    assert r.status_code == 200 and r.json()["name"] == "Pharmacy 2" and r.json()["status"] == "paused"
    assert client.delete(f"{API}/queues/{q['id']}").status_code == 204
    assert client.get(f"{API}/queues/{q['id']}").status_code == 404


def test_invalid_queue_handling(client):
    r = client.get(f"{API}/queues/9999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "queue_not_found"
    assert client.post(f"{API}/queues/9999/entries").status_code == 404
    assert client.post(f"{API}/queues/9999/serve-next").status_code == 404
    assert client.delete(f"{API}/queues/9999").status_code == 404
    r = client.post(f"{API}/queues", json={"name": ""})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.post(f"{API}/queues", json={"name": "x", "status": "bogus"}).status_code == 422
    assert client.put(f"{API}/queues/1", json={}).status_code == 422
    assert client.get(f"{API}/nope").json()["error"]["code"] == "not_found"


def test_tokens_and_positions(client):
    q = make_queue(client)
    entries = [client.post(f"{API}/queues/{q['id']}/entries").json() for _ in range(3)]
    assert [e["token_number"] for e in entries] == [1, 2, 3]
    assert [e["position"] for e in entries] == [1, 2, 3]
    assert all(e["status"] == "waiting" for e in entries)
    listed = client.get(f"{API}/queues/{q['id']}/entries").json()
    assert [e["position"] for e in listed] == [1, 2, 3]
    pos = client.get(f"{API}/queues/{q['id']}/entries/{entries[2]['id']}/position").json()
    assert pos["position"] == 3 and pos["entries_ahead"] == 2


def test_remove_entry_updates_positions_and_never_reuses_tokens(client):
    q = make_queue(client)
    e = [client.post(f"{API}/queues/{q['id']}/entries").json() for _ in range(3)]
    assert client.delete(f"{API}/queues/{q['id']}/entries/{e[0]['id']}").status_code == 204
    waiting = client.get(f"{API}/queues/{q['id']}/entries", params={"status": "waiting"}).json()
    assert [(x["token_number"], x["position"]) for x in waiting] == [(2, 1), (3, 2)]
    nxt = client.post(f"{API}/queues/{q['id']}/entries").json()
    assert nxt["token_number"] == 4 and nxt["position"] == 3
    assert client.delete(f"{API}/queues/{q['id']}/entries/{e[0]['id']}").status_code == 409
    assert client.delete(f"{API}/queues/{q['id']}/entries/9999").status_code == 404
    other = make_queue(client, "Other")
    assert client.delete(f"{API}/queues/{other['id']}/entries/{e[1]['id']}").status_code == 404


def test_serve_next_is_fifo_and_assigns_counter(client):
    q = make_queue(client)
    c1 = make_counter(client, q["id"], "C1")
    c2 = make_counter(client, q["id"], "C2")
    ids = [client.post(f"{API}/queues/{q['id']}/entries").json()["id"] for _ in range(3)]
    r = client.post(f"{API}/queues/{q['id']}/serve-next")
    assert r.status_code == 200
    body = r.json()
    assert body["entry"]["id"] == ids[0] and body["entry"]["status"] == "serving"
    assert body["entry"]["counter_id"] == c1["id"] and body["counter"]["current_load"] == 1
    r = client.post(f"{API}/queues/{q['id']}/serve-next", json={"counter_id": c2["id"]})
    assert r.json()["entry"]["id"] == ids[1]
    r = client.post(f"{API}/queues/{q['id']}/serve-next")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_available_counter"
    state = client.get(f"{API}/queues/{q['id']}/state").json()
    assert state["waiting_count"] == 1 and state["serving_count"] == 2 and state["next_token"] == 3
    assert state["idle_counters"] == 0


def test_complete_service_creates_record_and_frees_counter(client):
    q = make_queue(client)
    c = make_counter(client, q["id"])
    e = client.post(f"{API}/queues/{q['id']}/entries").json()
    client.post(f"{API}/queues/{q['id']}/serve-next")
    r = client.post(f"{API}/queues/{q['id']}/entries/{e['id']}/complete")
    assert r.status_code == 200
    body = r.json()
    assert body["entry"]["status"] == "completed" and body["counter"]["current_load"] == 0
    assert body["record"]["waiting_time"] >= 0 and body["record"]["service_time"] >= 0
    assert client.post(f"{API}/queues/{q['id']}/entries/{e['id']}/complete").status_code == 409
    d = client.get(f"{API}/queues/{q['id']}").json()
    assert d["completed_count"] == 1
    assert client.get(f"{API}/counters/{c['id']}").json()["current_load"] == 0


def test_serve_next_error_cases(client):
    q = make_queue(client)
    assert client.post(f"{API}/queues/{q['id']}/serve-next").json()["error"]["code"] == "queue_empty"
    client.post(f"{API}/queues/{q['id']}/entries")
    assert client.post(f"{API}/queues/{q['id']}/serve-next").json()["error"]["code"] == "no_available_counter"
    other = make_queue(client, "Other")
    foreign = make_counter(client, other["id"], "F")
    r = client.post(f"{API}/queues/{q['id']}/serve-next", json={"counter_id": foreign["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "counter_wrong_queue"
    assert client.post(f"{API}/queues/{q['id']}/serve-next", json={"counter_id": 9999}).status_code == 404


def test_assign_specific_entry_to_counter(client):
    q = make_queue(client)
    c = make_counter(client, q["id"])
    e1 = client.post(f"{API}/queues/{q['id']}/entries").json()
    e2 = client.post(f"{API}/queues/{q['id']}/entries").json()
    r = client.post(f"{API}/queues/{q['id']}/entries/{e2['id']}/assign", json={"counter_id": c["id"]})
    assert r.status_code == 200 and r.json()["entry"]["id"] == e2["id"]
    assert client.get(f"{API}/queues/{q['id']}/entries/{e1['id']}").json()["position"] == 1
    assert client.post(f"{API}/queues/{q['id']}/entries/{e2['id']}/assign", json={"counter_id": c["id"]}).status_code == 409


def test_paused_and_closed_queue_rules(client):
    q = make_queue(client)
    make_counter(client, q["id"])
    client.post(f"{API}/queues/{q['id']}/entries")
    client.put(f"{API}/queues/{q['id']}", json={"status": "paused"})
    assert client.post(f"{API}/queues/{q['id']}/entries").status_code == 201
    assert client.post(f"{API}/queues/{q['id']}/serve-next").json()["error"]["code"] == "queue_not_active"
    client.put(f"{API}/queues/{q['id']}", json={"status": "closed"})
    assert client.post(f"{API}/queues/{q['id']}/entries").json()["error"]["code"] == "queue_closed"


def test_event_history(client):
    q = make_queue(client)
    c = make_counter(client, q["id"])
    e = client.post(f"{API}/queues/{q['id']}/entries").json()
    client.post(f"{API}/queues/{q['id']}/serve-next")
    client.post(f"{API}/queues/{q['id']}/entries/{e['id']}/complete")
    client.post(f"{API}/counters/{c['id']}/pause")
    events = client.get(f"{API}/queues/{q['id']}/events", params={"limit": 100}).json()
    kinds = [x["event_type"] for x in reversed(events)]
    assert kinds == [
        "queue_created", "counter_created", "entry_added", "service_started", "service_completed", "counter_paused",
    ]
    added = next(x for x in events if x["event_type"] == "entry_added")
    assert added["metadata"]["token_number"] == 1
    assert client.get(f"{API}/queues/{q['id']}/events", params={"event_type": "entry_added"}).json()[0]["id"] == added["id"]


def test_delete_queue_cascades(client):
    q = make_queue(client)
    make_counter(client, q["id"])
    client.post(f"{API}/queues/{q['id']}/entries")
    assert client.delete(f"{API}/queues/{q['id']}").status_code == 204
    assert client.get(f"{API}/counters").json() == []


def test_list_filters_and_counts(client):
    a = make_queue(client, "A")
    make_queue(client, "B", status="paused")
    client.post(f"{API}/queues/{a['id']}/entries")
    make_counter(client, a["id"])
    rows = {r["name"]: r for r in client.get(f"{API}/queues").json()}
    assert rows["A"]["waiting_count"] == 1 and rows["A"]["counter_count"] == 1
    assert [r["name"] for r in client.get(f"{API}/queues", params={"status": "paused"}).json()] == ["B"]
    assert client.get(f"{API}/queues", params={"synthetic": True}).json() == []


def test_health_and_cors(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.options(
        f"{API}/queues", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
