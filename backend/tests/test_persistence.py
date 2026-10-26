"""PostgreSQL persistent mode. Runs only when MARKETLAB_TEST_DATABASE_URL points at a disposable database."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

DSN = os.environ.get("MARKETLAB_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set MARKETLAB_TEST_DATABASE_URL to run PostgreSQL tests")


@pytest.fixture(autouse=True)
def clean_db():
    import psycopg

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS events, trades, benchmark_runs, configs, app_instances, schema_migrations CASCADE")
    yield


def wait_flushed(client: TestClient) -> dict:
    for _ in range(50):
        st = client.get("/api/v1/history/status").json()
        if st["queued"] == 0 and st["written"] > 0:
            return st
        time.sleep(0.1)
    raise AssertionError(f"writer did not flush: {st}")


def pg_app():
    return create_app(make_settings(persistence_mode="postgres", database_url=DSN, db_connect_retries=3))


def test_history_survives_restart_and_configs_are_restored() -> None:
    with TestClient(pg_app()) as c:
        assert c.get("/healthz/ready").json()["persistence"] == {"enabled": True, "connected": True}
        cfg = c.get("/api/v1/mm/config").json() | {"spread": "0.20"}
        assert c.put("/api/v1/mm/config", json=cfg).status_code == 200
        r = c.post("/api/v1/mm/orders", json={"side": "buy", "type": "market", "quantity": 100}).json()
        corr = r["order"]["correlation_id"] or r["order"]["id"]
        st = wait_flushed(c)
        assert st["dropped"] == 0
        first_instance = st["instance_id"]

    with TestClient(pg_app()) as c:  # "restart": fresh process state, same database
        assert c.get("/api/v1/mm/config").json()["spread"] == "0.20"  # restored
        assert c.get("/api/v1/mm/ledger").json()["position"] == 0  # live state is ephemeral by design
        trades = c.get("/api/v1/history/trades").json()
        assert any(t["instance_id"] == first_instance and t["quantity"] == 100 for t in trades)
        events = c.get("/api/v1/history/events", params={"correlation_id": corr}).json()
        assert {"order.received", "trade.executed"} <= {e["type"] for e in events}
        assert len(c.get("/api/v1/history/instances").json()) == 2


def test_benchmark_results_are_archived() -> None:
    with TestClient(pg_app()) as c:
        run = c.post("/api/v1/tcp/benchmarks", json={"trials": 5, "warmup": 0}).json()
        for _ in range(100):
            if c.get(f"/api/v1/tcp/benchmarks/{run['id']}").json()["status"] == "completed":
                break
            time.sleep(0.05)
        wait_flushed(c)
        time.sleep(0.6)
        rows = c.get("/api/v1/history/benchmarks").json()
        assert rows[0]["run_id"] == run["id"] and rows[0]["summary"]["n"] == 5


def test_history_unavailable_in_memory_mode(client: TestClient) -> None:
    r = client.get("/api/v1/history/events")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_persistent"
