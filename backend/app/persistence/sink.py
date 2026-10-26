"""History sinks: where events, trades, benchmark results and configurations are archived.

``NullSink`` (ephemeral mode) keeps nothing beyond the in-memory ring buffers.
``PostgresSink`` (persistent mode) writes through a bounded queue drained by one
background thread, so slow or unavailable databases never block the simulation.
If the queue overflows, the oldest pending writes are dropped and counted;
readiness reports the database state.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic_core import to_jsonable_python

from app.config import APP_VERSION
from app.events.models import Event

log = logging.getLogger(__name__)


class NullSink:
    persistent = False

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def record_event(self, event: Event) -> None: ...
    def record_benchmark(self, run: Any) -> None: ...
    def save_config(self, key: str, value: Any) -> None: ...
    def load_config(self, key: str) -> dict[str, Any] | None: return None
    def healthy(self) -> bool: return True
    def status(self) -> dict[str, Any]: return {"mode": "memory", "persistent": False}
    def query(self, kind: str, limit: int, **filters: Any) -> list[dict[str, Any]]:
        raise LookupError("History queries need persistent mode (MARKETLAB_PERSISTENCE_MODE=postgres).")


def _json(v: Any) -> str:
    return json.dumps(to_jsonable_python(v))


class PostgresSink:
    persistent = True

    def __init__(self, dsn: str, environment: str, queue_size: int = 10_000) -> None:
        self._dsn = dsn
        self._env = environment
        self.instance_id = uuid.uuid4()
        self._q: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.dropped = 0
        self.written = 0
        self.last_error: str | None = None
        self._connected = False

    # ---- lifecycle --------------------------------------------------------------
    def start(self) -> None:
        import psycopg

        with psycopg.connect(self._dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute("INSERT INTO app_instances (instance_id, started_at, version, environment) VALUES (%s, %s, %s, %s)",
                         (self.instance_id, datetime.now(UTC), APP_VERSION, self._env))
        self._connected = True
        self._thread = threading.Thread(target=self._run, name="pg-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _put(self, kind: str, args: tuple[Any, ...]) -> None:
        while True:
            try:
                self._q.put_nowait((kind, args))
                return
            except queue.Full:
                try:
                    self._q.get_nowait()
                    self.dropped += 1
                except queue.Empty:  # pragma: no cover
                    pass

    def _run(self) -> None:
        import psycopg

        conn = None
        batch: list[tuple[str, tuple[Any, ...]]] = []  # survives a failed write so it can be retried
        while not (self._stop.is_set() and self._q.empty() and not batch):
            try:
                if conn is None or conn.closed:
                    conn = psycopg.connect(self._dsn, autocommit=False, connect_timeout=5)
                    self._connected = True
                if not batch:
                    try:
                        batch.append(self._q.get(timeout=0.5))
                    except queue.Empty:
                        continue
                while len(batch) < 500:
                    try:
                        batch.append(self._q.get_nowait())
                    except queue.Empty:
                        break
                with conn.transaction():
                    with conn.cursor() as cur:
                        for kind, args in batch:
                            cur.execute(SQL[kind], args)
                self.written += len(batch)
                batch = []
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep the writer alive; report via status
                self._connected = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self._stop.is_set():
                    self.dropped += len(batch)  # shutting down: give up on this batch (counted)
                    batch = []
                log.warning("persistence write failed; will retry", extra={"error": self.last_error})
                try:
                    if conn is not None:
                        conn.close()
                except Exception:  # noqa: BLE001
                    pass
                conn = None
                time.sleep(1)
        if conn is not None:
            conn.close()

    # ---- writes -------------------------------------------------------------------
    def record_event(self, e: Event) -> None:
        self._put("event", (self.instance_id, e.seq, e.id, e.ts, e.mono_ns, e.type, e.module, e.entity_id, e.correlation_id, e.message, _json(e.data)))
        if e.type == "trade.executed":
            d = e.data
            self._put("trade", (self.instance_id, e.entity_id, e.ts, e.module, d.get("venue"), d.get("price"), d.get("quantity"),
                                d.get("taker_order_id"), d.get("maker_order_id"), d.get("taker_owner"), d.get("maker_owner"),
                                d.get("taker_fee"), d.get("maker_fee"), e.correlation_id))

    def record_benchmark(self, run: Any) -> None:
        self._put("benchmark", (self.instance_id, run.id, run.suite_id, run.status, run.description, run.started_ts, run.finished_ts,
                                _json(run.config), _json(run.summary), _json(run.phase_medians), _json(run.environment),
                                _json(run.notes), _json(run.trials)))

    def save_config(self, key: str, value: Any) -> None:
        self._put("config", (key, _json(value)))

    # ---- reads (synchronous; small, bounded) ----------------------------------------------
    def load_config(self, key: str) -> dict[str, Any] | None:
        import psycopg

        try:
            with psycopg.connect(self._dsn, connect_timeout=5) as conn:
                row = conn.execute("SELECT value FROM configs WHERE key = %s", (key,)).fetchone()
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load config", extra={"key": key, "error": str(exc)})
            return None

    def query(self, kind: str, limit: int, **filters: Any) -> list[dict[str, Any]]:
        import psycopg
        from psycopg.rows import dict_row

        sql, args = QUERIES[kind], []
        where = []
        for col in ("correlation_id", "type", "module", "instance_id"):
            if filters.get(col):
                where.append(f"{col} = %s")
                args.append(filters[col])
        if where:
            sql = sql.replace("/*WHERE*/", "WHERE " + " AND ".join(where))
        args.append(limit)
        with psycopg.connect(self._dsn, connect_timeout=5, row_factory=dict_row) as conn:
            return [to_jsonable_python(r) for r in conn.execute(sql, args).fetchall()]

    def healthy(self) -> bool:
        return self._connected

    def status(self) -> dict[str, Any]:
        return {"mode": "postgres", "persistent": True, "instance_id": str(self.instance_id), "connected": self._connected,
                "queued": self._q.qsize(), "written": self.written, "dropped": self.dropped, "last_error": self.last_error}


SQL = {
    "event": "INSERT INTO events (instance_id, seq, event_id, ts, mono_ns, type, module, entity_id, correlation_id, message, data) "
             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
    "trade": "INSERT INTO trades (instance_id, trade_id, ts, module, venue, price, quantity, taker_order_id, maker_order_id, taker_owner, "
             "maker_owner, taker_fee, maker_fee, correlation_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
    "benchmark": "INSERT INTO benchmark_runs (instance_id, run_id, suite_id, status, description, started_at, finished_at, config, summary, "
                 "phase_medians, environment, notes, trials) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb) "
                 "ON CONFLICT (instance_id, run_id) DO UPDATE SET status = EXCLUDED.status, summary = EXCLUDED.summary, trials = EXCLUDED.trials, "
                 "finished_at = EXCLUDED.finished_at, notes = EXCLUDED.notes, phase_medians = EXCLUDED.phase_medians, environment = EXCLUDED.environment",
    "config": "INSERT INTO configs (key, value, updated_at) VALUES (%s, %s::jsonb, now()) "
              "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
}

QUERIES = {
    "events": "SELECT instance_id, seq, event_id, ts, type, module, entity_id, correlation_id, message, data FROM events /*WHERE*/ ORDER BY ts DESC, seq DESC LIMIT %s",
    "trades": "SELECT * FROM trades /*WHERE*/ ORDER BY ts DESC LIMIT %s",
    "benchmarks": "SELECT instance_id, run_id, suite_id, status, description, started_at, finished_at, config, summary, phase_medians, notes "
                  "FROM benchmark_runs /*WHERE*/ ORDER BY started_at DESC NULLS LAST LIMIT %s",
    "instances": "SELECT * FROM app_instances /*WHERE*/ ORDER BY started_at DESC LIMIT %s",
}
