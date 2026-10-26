import time

from fastapi.testclient import TestClient


def test_health_live_and_ready(client: TestClient) -> None:
    assert client.get("/healthz/live").json() == {"status": "ok"}
    r = client.get("/healthz/ready")
    assert r.status_code == 200
    assert r.json()["checks"] == {"simulation_loop": True, "repository": True, "tcp_lab_server": True}


def test_info_reports_simulation_mode(client: TestClient) -> None:
    body = client.get("/api/v1/info").json()
    assert body["simulation_mode"] is True
    assert body["ephemeral"] is True
    assert "hypothetical" in body["notice"]


def test_simulation_lifecycle(client: TestClient) -> None:
    assert client.get("/api/v1/simulation").json()["state"] == "stopped"
    assert client.post("/api/v1/simulation/start").json()["state"] == "running"
    time.sleep(0.1)
    paused = client.post("/api/v1/simulation/pause").json()
    assert paused["state"] == "paused" and paused["tick"] > 0
    reset = client.post("/api/v1/simulation/reset", json={"seed": 9}).json()
    assert reset == {**reset, "state": "stopped", "tick": 0, "seed": 9}
    # reset without a body keeps the seed
    assert client.post("/api/v1/simulation/reset").json()["seed"] == 9


def test_invalid_transition_uses_error_envelope(client: TestClient) -> None:
    r = client.post("/api/v1/simulation/pause")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"


def test_speed_validation(client: TestClient) -> None:
    assert client.put("/api/v1/simulation/speed", json={"speed": "2"}).json()["speed"] == "2"
    for bad in ("0", "100", "abc"):
        r = client.put("/api/v1/simulation/speed", json={"speed": bad})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"


def test_events_endpoint_filters(client: TestClient) -> None:
    client.post("/api/v1/simulation/start")
    client.post("/api/v1/simulation/pause")
    events = client.get("/api/v1/events", params={"type": "simulation."}).json()
    assert [e["type"] for e in events][-2:] == ["simulation.started", "simulation.paused"]
    last = events[-1]["seq"]
    assert client.get("/api/v1/events", params={"after_seq": last}).json() == []
    assert client.get("/api/v1/events", params={"limit": 0}).status_code == 422


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_openapi_is_served_without_cdn_docs(client: TestClient) -> None:
    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "MarketLab API"
    assert client.get("/docs").status_code == 404


def test_websocket_stream_hello_and_events(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/stream") as ws:
        hello = ws.receive_json()
        assert hello["kind"] == "hello" and hello["status"]["state"] == "stopped"
        client.post("/api/v1/simulation/start")
        kinds: dict[str, dict] = {}
        for _ in range(20):
            msg = ws.receive_json()
            kinds.setdefault(msg["kind"], msg)
            if "event" in kinds and "status" in kinds:
                break
        assert kinds["event"]["event"]["type"] == "simulation.started"
        assert kinds["status"]["status"]["state"] == "running"


def test_prometheus_metrics(client: TestClient) -> None:
    client.post("/api/v1/mm/orders", json={"side": "sell", "type": "market", "quantity": 100})
    text = client.get("/metrics").text
    assert "# TYPE marketlab_events_published_total counter" in text
    assert "marketlab_mm_inventory_shares 100" in text
    assert "marketlab_tcplab_premature_commits_total 0" in text
