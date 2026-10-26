"""Runs benchmarks one at a time in the background, keeps a bounded history and exports CSV."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.clock import utc_now
from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.tcplab.client import BenchmarkConfig, Conn, connect, run_trial
from app.tcplab.stats import summarize

log = logging.getLogger(__name__)
MAX_RUNS = 30
METRICS = ["connect_ms", "first_write_ms", "server_first_rx_ms", "server_complete_ms", "prep_ms", "wait_final_byte_ms",
           "server_processing_ms", "ttfb_ms", "response_spread_ms", "total_ms"]


class BenchmarkRun(BaseModel):
    id: str
    suite_id: str | None = None
    config: BenchmarkConfig
    description: str
    status: str = "queued"  # queued | running | completed | failed | canceled
    started_ts: datetime | None = None
    finished_ts: datetime | None = None
    trials: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    phase_medians: dict[str, float | None] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class Suite(BaseModel):
    id: str
    name: str
    transport: str
    run_ids: list[str]
    status: str = "running"
    started_ts: datetime
    finished_ts: datetime | None = None


SUITE_STANDARD: list[dict[str, Any]] = [
    {"mode": "complete", "connection": "cold", "label": "A · complete message, cold connection"},
    {"mode": "complete", "connection": "reused", "label": "C · complete message, pre-established connection"},
    {"mode": "split", "connection": "reused", "split_delay_ms": 0, "label": "B · split 499+1, no delay"},
    {"mode": "split", "connection": "reused", "split_delay_ms": 20, "prep_ms": 10, "label": "B · split 499+1, 20 ms delay, prep after"},
    {"mode": "early_work", "connection": "reused", "split_delay_ms": 20, "prep_ms": 10, "label": "D · split + useful early work (prep 10 ms)"},
]


class TCPLabService:
    def __init__(self, bus: EventBus, ids: IdGenerator, host: str, raw_port_getter, http_port: int) -> None:
        self._bus = bus
        self._ids = ids
        self.host = host
        self._raw_port = raw_port_getter
        self.http_port = http_port
        self.runs: OrderedDict[str, BenchmarkRun] = OrderedDict()
        self.suites: OrderedDict[str, Suite] = OrderedDict()
        self._task: asyncio.Task | None = None
        self.on_finished = lambda run: None  # persistence hook

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _port(self, cfg: BenchmarkConfig) -> int:
        return self._raw_port() if cfg.transport == "raw_tcp" else self.http_port

    def _new_run(self, cfg: BenchmarkConfig, suite_id: str | None = None) -> BenchmarkRun:
        run = BenchmarkRun(id=self._ids.next("RUN"), suite_id=suite_id, config=cfg, description=cfg.label or cfg.describe())
        self.runs[run.id] = run
        while len(self.runs) > MAX_RUNS:
            self.runs.popitem(last=False)
        return run

    def start(self, cfg: BenchmarkConfig) -> BenchmarkRun:
        if self.busy:
            raise RuntimeError("A benchmark is already running; wait for it to finish.")
        run = self._new_run(cfg)
        self._task = asyncio.create_task(self._execute(run), name=f"bench-{run.id}")
        return run

    def start_suite(self, transport: str, overrides: dict[str, Any] | None = None) -> Suite:
        if self.busy:
            raise RuntimeError("A benchmark is already running; wait for it to finish.")
        base = {"transport": transport, "trials": 40, "warmup": 5, **(overrides or {})}
        runs = [self._new_run(BenchmarkConfig(**{**base, **spec})) for spec in SUITE_STANDARD]
        suite = Suite(id=self._ids.next("SUITE"), name="Preset 5: TCP latency comparison", transport=transport,
                      run_ids=[r.id for r in runs], started_ts=utc_now())
        for r in runs:
            r.suite_id = suite.id
        self.suites[suite.id] = suite
        while len(self.suites) > 10:
            self.suites.popitem(last=False)

        async def go() -> None:
            for r in runs:
                await self._execute(r)
            suite.status = "completed" if all(r.status == "completed" for r in runs) else "failed"
            suite.finished_ts = utc_now()
            self._bus.publish("benchmark.suite_completed", "tcplab", f"Benchmark suite {suite.id} {suite.status}.", entity_id=suite.id)

        self._task = asyncio.create_task(go(), name=f"suite-{suite.id}")
        return suite

    async def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _execute(self, run: BenchmarkRun) -> None:
        cfg = run.config
        run.status = "running"
        run.started_ts = utc_now()
        self._bus.publish("benchmark.started", "tcplab", f"Benchmark started: {run.description} ({cfg.trials} trials + {cfg.warmup} warm-up).",
                          entity_id=run.id, correlation_id=run.suite_id or run.id, data=cfg.model_dump(mode="json"))
        port = self._port(cfg)
        total = cfg.warmup + cfg.trials
        counter = iter(range(total))
        results: list[dict[str, Any]] = []
        lock = asyncio.Lock()

        async def worker(wid: int) -> None:
            conn: Conn | None = None
            try:
                while True:
                    async with lock:
                        seq = next(counter, None)
                    if seq is None:
                        return
                    if cfg.connection == "reused" and conn is None:
                        conn = await connect(self.host, port, cfg.tcp_nodelay)  # established before the measured request
                    try:
                        res, conn = await asyncio.wait_for(run_trial(cfg, seq, self.host, port, conn), cfg.timeout_ms / 1000)
                    except TimeoutError:
                        res = {"seq": seq, "ok": False, "error": "timeout", "timeout": True}
                        if conn:
                            await conn.close()
                        conn = None
                    except Exception as exc:  # noqa: BLE001
                        res = {"seq": seq, "ok": False, "error": f"{type(exc).__name__}: {exc}", "timeout": False}
                        if conn:
                            await conn.close()
                        conn = None
                    res["warmup"] = seq < cfg.warmup
                    res["worker"] = wid
                    results.append(res)
            finally:
                if conn is not None:
                    await conn.close()

        try:
            await asyncio.wait_for(asyncio.gather(*(worker(i) for i in range(cfg.concurrency))), timeout=150)
            run.status = "completed"
        except asyncio.CancelledError:
            run.status = "canceled"
            raise
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
        finally:
            run.finished_ts = utc_now()
            results.sort(key=lambda r: r["seq"])
            run.trials = results
            measured = [r for r in results if not r["warmup"]]
            ok = [r for r in measured if r["ok"]]
            run.summary = summarize([r["total_ms"] for r in ok], errors=sum(1 for r in measured if not r["ok"] and not r.get("timeout")),
                                    timeouts=sum(1 for r in measured if r.get("timeout")))
            run.phase_medians = {m: (summarize([r[m] for r in ok if r.get(m) is not None])["median"]) for m in METRICS}
            first = next((r for r in ok), {})
            run.environment = {
                "target": f"{self.host}:{port} (this process, loopback)",
                "client_nodelay_applied": first.get("client_nodelay"),
                "client_nodelay_error": first.get("client_nodelay_error"),
                "server_nodelay_applied": first.get("server_nodelay"),
                "clock": "time.monotonic_ns (client and server share it: same process)",
                "segments_observed": False,
            }
            run.notes = self._notes(run)
            try:
                self.on_finished(run)
            except Exception:  # noqa: BLE001
                log.exception("could not archive benchmark run")
            self._bus.publish(
                "benchmark.completed", "tcplab",
                f"Benchmark {run.status}: {run.description}. "
                + (f"Median {run.summary['median']:.3f} ms over {run.summary['n']} trials." if run.summary.get("median") is not None else "No successful trials."),
                entity_id=run.id, correlation_id=run.suite_id or run.id,
                data={"median_ms": run.summary.get("median"), "n": run.summary.get("n"), "error_rate": run.summary.get("error_rate")},
            )

    @staticmethod
    def _notes(run: BenchmarkRun) -> list[str]:
        n = run.summary.get("n", 0)
        cfg = run.config
        notes = []
        if n < 30:
            notes.append(f"Small sample (n={n}): treat the numbers as indicative only.")
        if cfg.transport == "http":
            notes.append("HTTP server-side socket options are uvicorn's defaults; only the client socket's TCP_NODELAY is controlled.")
            notes.append("HTTP server timestamps mark when the application consumed body chunks from uvicorn's buffer, not when bytes reached "
                         "the socket; uvicorn may merge the 499-byte and 1-byte writes into one chunk. Raw TCP timestamps are taken at socket reads.")
        notes.append("Loopback within one process: no real network RTT; client and server also share one event loop, which adds scheduling noise.")
        notes.append("Application write() calls are counted, not TCP segments: no packet capture is performed.")
        spread = run.phase_medians.get("response_spread_ms")
        if spread is not None and spread > 20:
            notes.append(
                f"The response's first and last bytes arrived a median {spread:.1f} ms apart. A gap near 40 ms is the signature of "
                "Nagle's algorithm on the server holding back its second write (the body) until the first (the headers) is "
                "acknowledged, while the client delays that ACK. In development this was traced to uvicorn sockets created "
                "without TCP_NODELAY (e.g. under --reload); this lab cannot confirm the cause per run without packet capture."
            )
        if cfg.mode != "complete" and run.phase_medians.get("wait_final_byte_ms") is not None:
            notes.append(f"Median time the server waited between holding {cfg.payload_size - 1} bytes and the final byte: {run.phase_medians['wait_final_byte_ms']:.3f} ms.")
        return notes

    # ---- export ---------------------------------------------------------------
    CSV_COLS = ["run_id", "label", "transport", "mode", "connection", "payload_size", "split_delay_ms", "prep_ms_cfg", "proc_ms_cfg",
                "tcp_nodelay_requested", "seq", "warmup", "ok", "error", "writes", "server_reads", "connect_ms", "first_write_ms",
                "last_write_ms", "server_first_rx_ms", "server_prefix_ready_ms", "server_complete_ms", "prep_ms", "prep_overlapped",
                "wait_final_byte_ms", "server_processing_ms", "complete_to_response_ms", "ttfb_ms", "response_spread_ms", "total_ms", "client_nodelay", "server_nodelay"]

    def csv(self, runs: list[BenchmarkRun]) -> str:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=self.CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for run in runs:
            c = run.config
            for t in run.trials:
                w.writerow({**t, "run_id": run.id, "label": run.description, "transport": c.transport, "mode": c.mode,
                            "connection": c.connection, "payload_size": c.payload_size, "split_delay_ms": c.split_delay_ms,
                            "prep_ms_cfg": c.prep_ms, "proc_ms_cfg": c.server_processing_ms, "tcp_nodelay_requested": c.tcp_nodelay})
        return buf.getvalue()
