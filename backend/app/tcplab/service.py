"""Runs benchmarks one at a time in the background, keeps a bounded history and exports CSV."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import random
from collections import OrderedDict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.clock import utc_now
from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.tcplab.client import BenchmarkConfig, Conn, connect, run_abort_trial, run_race_trial, run_trial
from app.tcplab.stats import summarize

log = logging.getLogger(__name__)
MAX_RUNS = 30
METRICS = ["connect_ms", "first_write_ms", "decision_ms", "server_first_rx_ms", "server_complete_ms", "prep_ms", "wait_final_byte_ms",
           "server_processing_ms", "ttfb_ms", "response_spread_ms", "decision_to_accept_ms", "decision_to_response_ms", "total_ms"]


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
    decision_summary: dict[str, Any] = Field(default_factory=dict)  # decision -> response, the latency that matters for trading
    race: dict[str, Any] | None = None
    abort: dict[str, Any] | None = None


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
    {"mode": "split", "connection": "reused", "split_delay_ms": 0, "label": "B · front-loaded 499+1, decide at once"},
    {"mode": "split", "connection": "reused", "split_delay_ms": 20, "prep_ms": 10, "label": "B · front-loaded, server prepares after last byte"},
    {"mode": "early_work", "connection": "reused", "split_delay_ms": 20, "prep_ms": 10, "label": "D · front-loaded, server prepares early (HFT setup)"},
    {"mode": "race", "connection": "reused", "split_delay_ms": 5, "prep_ms": 0, "label": "Race · pre-sent 499 vs full 500, no server prep"},
    {"mode": "race", "connection": "reused", "split_delay_ms": 20, "prep_ms": 10, "label": "Race · pre-sent 499 vs full 500, 10 ms server prep"},
    {"mode": "abort", "connection": "cold", "split_delay_ms": 2, "label": "Abort · send 499 ahead, then decide not to trade"},
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
        self.counters = lambda: {}  # server-side message counters (set by the app container)

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

        async def race_loop() -> None:
            rng = random.Random(12345)  # seeded: which side the event loop wakes first alternates reproducibly
            pre = full = None
            try:
                for seq in range(total):
                    if pre is None or full is None:
                        pre = await connect(self.host, port, cfg.tcp_nodelay)
                        full = await connect(self.host, port, cfg.tcp_nodelay)
                    try:
                        res = await asyncio.wait_for(run_race_trial(cfg, seq, pre, full, rng.random() < 0.5), cfg.timeout_ms / 1000)
                    except (TimeoutError, Exception) as exc:  # noqa: BLE001
                        res = {"seq": seq, "ok": False, "error": "timeout" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}",
                               "timeout": isinstance(exc, TimeoutError)}
                        for c in (pre, full):
                            await c.close()
                        pre = full = None
                    res["warmup"] = seq < cfg.warmup
                    results.append(res)
            finally:
                for c in (pre, full):
                    if c is not None:
                        await c.close()

        async def abort_loop() -> None:
            for seq in range(total):
                try:
                    res = await asyncio.wait_for(run_abort_trial(cfg, seq, self.host, port), cfg.timeout_ms / 1000)
                except Exception as exc:  # noqa: BLE001
                    res = {"seq": seq, "ok": False, "error": f"{type(exc).__name__}: {exc}", "timeout": isinstance(exc, TimeoutError)}
                res["warmup"] = seq < cfg.warmup
                results.append(res)
            await asyncio.sleep(0.3)  # let the server notice the last closed connections

        before = self.counters().get(cfg.transport, {})
        try:
            if cfg.mode == "race":
                await asyncio.wait_for(race_loop(), timeout=150)
            elif cfg.mode == "abort":
                await asyncio.wait_for(abort_loop(), timeout=150)
            else:
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
            run.decision_summary = summarize([r["decision_to_response_ms"] for r in ok if r.get("decision_to_response_ms") is not None])
            if cfg.mode == "race":
                run.race = self._race_summary(ok)
            if cfg.mode == "abort":
                after = self.counters().get(cfg.transport, {})
                run.abort = {
                    "sent_incomplete": len(results),
                    "discarded_by_server": after.get("discarded", 0) - before.get("discarded", 0),
                    "acted_on_by_server": after.get("completed", 0) - before.get("completed", 0),
                    "premature_commits": after.get("premature", 0) - before.get("premature", 0),
                }
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
    def _race_summary(ok: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(ok)
        pre = sum(1 for r in ok if r["winner"] == "pre_sent")
        full = sum(1 for r in ok if r["winner"] == "full_payload")
        by_order = {}
        for first in (True, False):
            sub = [r for r in ok if r["pre_first_scheduled"] is first]
            by_order["pre_scheduled_first" if first else "full_scheduled_first"] = {
                "trials": len(sub), "pre_sent_wins": sum(1 for r in sub if r["winner"] == "pre_sent")}
        return {
            "trials": n, "pre_sent_wins": pre, "full_payload_wins": full, "ties": n - pre - full,
            "pre_sent_win_rate": (pre / n) if n else None,
            "margin": summarize([r["margin_ms"] for r in ok]),
            "pre_decision_to_accept": summarize([r["pre_decision_to_accept_ms"] for r in ok]),
            "full_decision_to_accept": summarize([r["full_decision_to_accept_ms"] for r in ok]),
            "by_scheduling_order": by_order,
        }

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
        if cfg.mode in ("split", "early_work") and run.decision_summary.get("median") is not None:
            notes.append(
                f"Decision → response (from the moment the final byte is sent): median {run.decision_summary['median']:.3f} ms. "
                f"Total time {run.summary.get('median') or 0:.3f} ms also includes the {cfg.split_delay_ms:g} ms during which the first "
                f"{cfg.payload_size - 1} bytes were already sitting at the server before the decision."
            )
        if cfg.mode == "race" and run.race:
            r = run.race
            m = r["margin"].get("median")
            notes.append(
                f"Same signal, two clients: the pre-sent order was accepted first in {r['pre_sent_wins']} of {r['trials']} trials"
                + (f", by a median of {m:.3f} ms." if m is not None else ".")
                + (" With server preparation, the pre-sent order's checks ran before the signal; the full payload's could only start after it arrived."
                   if cfg.prep_ms else " With no server preparation, the only difference left is 1 byte vs 500 on the wire; over loopback that is microseconds, so the margin is tiny and noisy. On a real network it is wire time and packets the full order pays and the pre-sent one doesn't.")
            )
            bo = r["by_scheduling_order"]
            pf, ff = bo["pre_scheduled_first"], bo["full_scheduled_first"]
            decided_by_order = pf["trials"] and ff["trials"] and pf["pre_sent_wins"] >= 0.9 * pf["trials"] and ff["pre_sent_wins"] <= 0.1 * ff["trials"]
            if decided_by_order:
                notes.append(
                    "The winner simply followed which client this process happened to run first after the signal "
                    f"(pre-sent won {pf['pre_sent_wins']}/{pf['trials']} when it went first, {ff['pre_sent_wins']}/{ff['trials']} when it went second). "
                    "Loopback hides the wire-time edge: 499 fewer bytes take microseconds here, less than scheduling noise. On a real network the "
                    "full order pays that wire time after the decision; add server preparation (try 10 ms) to see the pre-sent order win every race."
                )
            else:
                notes.append("Which client the event loop wakes first alternates by a seeded coin flip; win rates for each order are reported to expose any bias.")
        if cfg.mode == "abort" and run.abort:
            a = run.abort
            notes.append(f"Sent {a['sent_incomplete']} incomplete orders and abandoned them: the server discarded {a['discarded_by_server']} and acted on {a['acted_on_by_server']}.")
        return notes

    # ---- export ---------------------------------------------------------------
    CSV_COLS = ["run_id", "label", "transport", "mode", "connection", "payload_size", "split_delay_ms", "prep_ms_cfg", "proc_ms_cfg",
                "tcp_nodelay_requested", "seq", "warmup", "ok", "error", "writes", "server_reads", "connect_ms", "first_write_ms",
                "last_write_ms", "server_first_rx_ms", "server_prefix_ready_ms", "server_complete_ms", "prep_ms", "prep_overlapped",
                "wait_final_byte_ms", "server_processing_ms", "complete_to_response_ms", "ttfb_ms", "response_spread_ms", "total_ms",
                "decision_ms", "decision_to_accept_ms", "decision_to_response_ms", "aborted", "winner", "margin_ms", "pre_first_scheduled",
                "pre_decision_to_accept_ms", "full_decision_to_accept_ms", "client_nodelay", "server_nodelay"]

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
