def make_queue(client, name="Main", **extra):
    r = client.post("/api/v1/queues", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def make_counter(client, queue_id, name="C1", **extra):
    r = client.post("/api/v1/counters", json={"queue_id": queue_id, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()
