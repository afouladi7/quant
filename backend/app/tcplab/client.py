"""Benchmark client. Targets ONLY this process's own loopback endpoints.

All timestamps come from ``time.monotonic_ns()``. The server runs in the same
process, so client and server readings share one clock and can be compared
directly. What is *not* observed: individual TCP segments (no packet capture),
kernel queueing, or ACK timing. "Writes" are application ``write()`` calls,
which do not map one-to-one to TCP segments.
"""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import time
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.tcplab.protocol import MAX_MESSAGE, MIN_MESSAGE, build_message

Mode = Literal["complete", "split", "early_work", "abort", "race"]


class BenchmarkConfig(BaseModel):
    transport: Literal["raw_tcp", "http"] = "raw_tcp"
    mode: Mode = "complete"
    connection: Literal["cold", "reused"] = Field("cold", description="cold = new TCP connection per trial (connect is measured); reused = connection established before measuring")
    payload_size: int = Field(500, ge=MIN_MESSAGE, le=MAX_MESSAGE, description="Total application message bytes (raw: incl. 16-byte header; HTTP: body)")
    trials: int = Field(50, ge=1, le=500)
    warmup: int = Field(5, ge=0, le=50)
    split_delay_ms: float = Field(
        0, ge=0, le=1000,
        description="Time between sending the first N-1 bytes and the decision (final byte, abort, or race signal)",
    )
    prep_ms: int = Field(0, ge=0, le=200, description="Server preparatory work")
    server_processing_ms: int = Field(0, ge=0, le=200, description="Server work after the message is complete")
    concurrency: int = Field(1, ge=1, le=8)
    tcp_nodelay: bool = True
    timeout_ms: int = Field(5000, ge=100, le=10_000)
    label: str | None = Field(None, max_length=80)

    @model_validator(mode="after")
    def _bounds(self) -> "BenchmarkConfig":
        if self.mode == "early_work" and self.prep_ms == 0:
            raise ValueError("early_work mode needs prep_ms > 0 (there must be work to overlap)")
        if self.mode == "abort" and self.connection != "cold":
            raise ValueError("abort closes the connection, so it needs connection='cold'")
        if self.mode == "race" and (self.connection != "reused" or self.concurrency != 1):
            raise ValueError("race uses two pre-established connections: set connection='reused' and concurrency=1")
        per_trial = self.split_delay_ms + self.prep_ms + self.server_processing_ms + 5
        if (self.trials + self.warmup) * per_trial / self.concurrency > 120_000:
            raise ValueError("estimated run time exceeds the 120 s limit; reduce trials, delays or work")
        return self

    def describe(self) -> str:
        if self.mode == "race":
            parts = [self.transport.replace("_", " "), "race: pre-sent 499 bytes vs full payload", f"sent {self.split_delay_ms:g} ms ahead"]
        elif self.mode == "abort":
            parts = [self.transport.replace("_", " "), "send ahead, then abort", f"decide after {self.split_delay_ms:g} ms"]
        else:
            parts = [self.transport.replace("_", " "), self.mode.replace("_", " "), f"{self.connection} conn"]
            if self.mode != "complete":
                parts.append(f"decision {self.split_delay_ms:g} ms after the first {self.payload_size - 1} bytes")
        if self.prep_ms:
            parts.append(f"prep {self.prep_ms} ms")
        if self.server_processing_ms:
            parts.append(f"proc {self.server_processing_ms} ms")
        parts.append("NODELAY" if self.tcp_nodelay else "Nagle on")
        return " · ".join(parts)


def _ms(a: int | None, b: int | None) -> float | None:
    return None if a is None or b is None else (b - a) / 1e6


class Conn:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, nodelay: bool | None, nodelay_error: str | None) -> None:
        self.reader, self.writer, self.nodelay, self.nodelay_error = reader, writer, nodelay, nodelay_error

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def connect(host: str, port: int, nodelay: bool) -> Conn:
    reader, writer = await asyncio.open_connection(host, port)
    sock: socket.socket | None = writer.get_extra_info("socket")
    applied: bool | None = None
    err = None
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1 if nodelay else 0)
            applied = bool(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
        except OSError as exc:  # pragma: no cover - platform specific
            err = str(exc)
    return Conn(reader, writer, applied, err)


def http_request(cfg: BenchmarkConfig, seq: int, keep_alive: bool) -> tuple[bytes, bytes]:
    body = bytes((seq + i) % 251 for i in range(cfg.payload_size))
    head = (
        "POST /api/v1/tcp/echo HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Content-Type: application/octet-stream\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: {'keep-alive' if keep_alive else 'close'}\r\n"
        f"X-ML-Prep-Ms: {cfg.prep_ms}\r\nX-ML-Proc-Ms: {cfg.server_processing_ms}\r\n"
        f"X-ML-Early-Work: {'1' if cfg.mode == 'early_work' else '0'}\r\nX-ML-Seq: {seq}\r\n\r\n"
    ).encode()
    return head, body


async def read_http_response(reader: asyncio.StreamReader) -> tuple[int, dict[str, Any]]:
    first = await reader.readexactly(1)
    ttfb = time.monotonic_ns()
    head = first + await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    length = next((int(l.split(":", 1)[1]) for l in lines[1:] if l.lower().startswith("content-length:")), 0)
    body = await reader.readexactly(length)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {body[:200]!r}")
    return ttfb, json.loads(body)


async def read_raw_response(reader: asyncio.StreamReader) -> tuple[int, dict[str, Any]]:
    first = await reader.readexactly(1)
    ttfb = time.monotonic_ns()
    rest = await reader.readexactly(3)
    (length,) = struct.unpack("!I", first + rest)
    return ttfb, json.loads(await reader.readexactly(length))


async def run_trial(cfg: BenchmarkConfig, seq: int, host: str, port: int, conn: Conn | None) -> tuple[dict[str, Any], Conn | None]:
    """One measured request. Returns (result, connection to reuse or None)."""
    t0 = time.monotonic_ns()
    connect_ns = None
    if conn is None:
        conn = await connect(host, port, cfg.tcp_nodelay)
        connect_ns = time.monotonic_ns()
    if cfg.transport == "raw_tcp":
        msg = build_message(cfg.payload_size, seq, prep_ms=cfg.prep_ms, proc_ms=cfg.server_processing_ms,
                            early=cfg.mode == "early_work", nodelay=cfg.tcp_nodelay)
        head, body = b"", msg
    else:
        head, body = http_request(cfg, seq, keep_alive=cfg.connection == "reused")
    w = conn.writer
    writes = 0
    if cfg.mode == "complete":
        decision = t0  # the decision to trade is made, then the whole message is sent (connecting first if cold)
        w.write(head + body)
        await w.drain()
        writes = 1
        first_write = last_write = time.monotonic_ns()
    else:
        w.write(head + body[:-1])  # sent ahead of the decision
        await w.drain()
        first_write = time.monotonic_ns()
        if cfg.split_delay_ms > 0:
            await asyncio.sleep(cfg.split_delay_ms / 1000)
        decision = time.monotonic_ns()  # decided to trade: only the final byte remains to send
        w.write(body[-1:])
        await w.drain()
        last_write = time.monotonic_ns()
        writes = 2
    if cfg.transport == "raw_tcp":
        ttfb, srv = await read_raw_response(conn.reader)
    else:
        ttfb, srv = await read_http_response(conn.reader)
    done = time.monotonic_ns()
    keep = conn if cfg.connection == "reused" else None
    if keep is None:
        await conn.close()
    result = {
        "seq": seq,
        "ok": True,
        "error": None,
        "writes": writes,
        "server_reads": srv.get("reads"),
        "connect_ms": _ms(t0, connect_ns),
        "first_write_ms": _ms(t0, first_write),
        "last_write_ms": _ms(t0, last_write),
        "server_first_rx_ms": _ms(t0, srv.get("first_rx_ns")),
        "server_prefix_ready_ms": _ms(t0, srv.get("prefix_ready_ns")),
        "server_complete_ms": _ms(t0, srv.get("complete_ns")),
        "prep_ms": _ms(srv.get("prep_start_ns"), srv.get("prep_end_ns")),
        "prep_overlapped": bool(srv.get("prep_end_ns") and srv.get("complete_ns") and srv["prep_start_ns"] < srv["complete_ns"]),
        "wait_final_byte_ms": _ms(srv.get("prefix_ready_ns"), srv.get("complete_ns")),
        "server_processing_ms": _ms(srv.get("proc_start_ns"), srv.get("proc_end_ns")),
        "complete_to_response_ms": _ms(srv.get("complete_ns"), srv.get("response_write_ns")),
        "decision_ms": _ms(t0, decision),
        "decision_to_response_ms": _ms(decision, done),
        "decision_to_accept_ms": _ms(decision, srv.get("proc_end_ns")),
        "ttfb_ms": _ms(t0, ttfb),
        "response_spread_ms": _ms(ttfb, done),
        "total_ms": _ms(t0, done),
        "client_nodelay": conn.nodelay,
        "client_nodelay_error": conn.nodelay_error,
        "server_nodelay": srv.get("server_nodelay_applied"),
        "bytes": srv.get("bytes"),
    }
    return result, keep


async def run_abort_trial(cfg: BenchmarkConfig, seq: int, host: str, port: int) -> dict[str, Any]:
    """Send everything except the last byte, then decide NOT to trade and close the connection.

    The server must discard the incomplete message and never act on it."""
    t0 = time.monotonic_ns()
    conn = await connect(host, port, cfg.tcp_nodelay)
    if cfg.transport == "raw_tcp":
        head, body = b"", build_message(cfg.payload_size, seq, prep_ms=cfg.prep_ms, proc_ms=cfg.server_processing_ms, early=True)
    else:
        head, body = http_request(cfg, seq, keep_alive=False)
    conn.writer.write(head + body[:-1])
    await conn.writer.drain()
    first_write = time.monotonic_ns()
    if cfg.split_delay_ms > 0:
        await asyncio.sleep(cfg.split_delay_ms / 1000)
    decision = time.monotonic_ns()
    await conn.close()  # decided not to trade: abandon the half-sent order
    done = time.monotonic_ns()
    return {"seq": seq, "ok": True, "error": None, "aborted": True, "writes": 1, "first_write_ms": _ms(t0, first_write),
            "decision_ms": _ms(t0, decision), "total_ms": _ms(t0, done), "client_nodelay": conn.nodelay}


def _race_message(cfg: BenchmarkConfig, seq: int) -> tuple[bytes, bytes]:
    if cfg.transport == "raw_tcp":
        # Both messages carry the same instructions; "early" lets the server prepare as soon as it has all but one byte.
        return b"", build_message(cfg.payload_size, seq, prep_ms=cfg.prep_ms, proc_ms=cfg.server_processing_ms, early=True, nodelay=cfg.tcp_nodelay)
    early_cfg = cfg.model_copy(update={"mode": "early_work"})
    return http_request(early_cfg, seq, keep_alive=True)


async def run_race_trial(cfg: BenchmarkConfig, seq: int, pre: Conn, full: Conn, pre_first: bool) -> dict[str, Any]:
    """Two clients act on the same signal at the same instant.

    PRE already sent every byte except the last on its open connection; FULL sends the whole message when the
    signal fires. The server's acceptance time (end of processing) decides the winner; both share one clock.
    ``pre_first`` alternates which waiting task the event loop wakes first, so scheduling order is not a bias."""
    p_head, p_body = _race_message(cfg, 2 * seq)
    f_head, f_body = _race_message(cfg, 2 * seq + 1)
    pre.writer.write(p_head + p_body[:-1])
    await pre.writer.drain()
    if cfg.split_delay_ms > 0:
        await asyncio.sleep(cfg.split_delay_ms / 1000)
    signal = asyncio.Event()

    async def side(conn: Conn, data: bytes) -> tuple[int, int, int, dict[str, Any]]:
        await signal.wait()
        sent = time.monotonic_ns()
        conn.writer.write(data)
        await conn.writer.drain()
        if cfg.transport == "raw_tcp":
            ttfb, srv = await read_raw_response(conn.reader)
        else:
            ttfb, srv = await read_http_response(conn.reader)
        return sent, ttfb, time.monotonic_ns(), srv

    jobs = [("pre", pre, p_body[-1:]), ("full", full, f_head + f_body)]
    if not pre_first:
        jobs.reverse()
    tasks = {name: asyncio.create_task(side(conn, data)) for name, conn, data in jobs}
    await asyncio.sleep(0)  # let both tasks start waiting on the signal
    signal_ns = time.monotonic_ns()
    signal.set()
    (p_sent, p_ttfb, p_done, p_srv), (f_sent, f_ttfb, f_done, f_srv) = await asyncio.gather(tasks["pre"], tasks["full"])
    p_acc, f_acc = p_srv["proc_end_ns"], f_srv["proc_end_ns"]
    return {
        "seq": seq, "ok": True, "error": None, "pre_first_scheduled": pre_first,
        "winner": "pre_sent" if p_acc < f_acc else "full_payload" if f_acc < p_acc else "tie",
        "margin_ms": (f_acc - p_acc) / 1e6,  # positive = the pre-sent order was accepted first
        "pre_decision_to_accept_ms": _ms(signal_ns, p_acc), "full_decision_to_accept_ms": _ms(signal_ns, f_acc),
        "pre_decision_to_response_ms": _ms(signal_ns, p_done), "full_decision_to_response_ms": _ms(signal_ns, f_done),
        "pre_server_complete_ms": _ms(signal_ns, p_srv["complete_ns"]), "full_server_complete_ms": _ms(signal_ns, f_srv["complete_ns"]),
        "pre_prep_overlapped": bool(p_srv["prep_start_ns"] < p_srv["complete_ns"]),
        "total_ms": _ms(signal_ns, max(p_done, f_done)),
        "decision_to_response_ms": _ms(signal_ns, p_done),
    }
