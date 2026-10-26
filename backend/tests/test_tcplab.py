import asyncio
import socket
import struct
import threading
import time

import pytest
import uvicorn
from pydantic import ValidationError

from app.main import create_app
from app.tcplab.client import BenchmarkConfig, connect, run_trial
from app.tcplab.protocol import HEADER_LEN, MessageAssembler, ProtocolError, build_message, parse_header
from app.tcplab.server import TCPBenchServer
from app.tcplab.service import TCPLabService
from app.tcplab.stats import percentile, summarize
from tests.conftest import make_settings
from tests.helpers import make_bus


# ---- framing ---------------------------------------------------------------------------
def test_message_framing_roundtrip() -> None:
    m = build_message(500, 7, prep_ms=3, proc_ms=4, early=True, nodelay=True)
    assert len(m) == 500
    h = parse_header(m)
    assert (h.total_len, h.seq, h.prep_ms, h.proc_ms, h.early, h.nodelay) == (500, 7, 3, 4, True, True)
    with pytest.raises(ProtocolError):
        parse_header(b"XX" + m[2:])
    with pytest.raises(ProtocolError):
        build_message(HEADER_LEN, 1)


@pytest.mark.parametrize("chunks", [[500], [499, 1], [1] * 500, [10, 6, 300, 183, 1]])
def test_assembler_never_completes_early(chunks: list[int]) -> None:
    msg = build_message(500, 1)
    asm, pos = MessageAssembler(), 0
    for n in chunks:
        assert not asm.complete
        asm.feed(msg[pos:pos + n])
        pos += n
        assert asm.complete == (pos == 500)
        assert asm.prefix_ready == (pos >= 499)


def test_assembler_rejects_overflow() -> None:
    asm = MessageAssembler()
    with pytest.raises(ProtocolError):
        asm.feed(build_message(100, 1) + b"extra")


# ---- statistics ------------------------------------------------------------------------
def test_percentiles_and_summary() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2.5
    s = summarize([float(i) for i in range(1, 11)], errors=1, timeouts=1)
    assert (s["n"], s["min"], s["max"], s["median"]) == (10, 1.0, 10.0, 5.5)
    assert s["p90"] == pytest.approx(9.1) and s["p95"] is None and s["p99"] is None
    assert s["error_rate"] == pytest.approx(1 / 12)
    assert summarize([])["median"] is None


def test_config_bounds() -> None:
    with pytest.raises(ValidationError):
        BenchmarkConfig(mode="early_work", prep_ms=0)
    with pytest.raises(ValidationError):
        BenchmarkConfig(trials=500, warmup=0, split_delay_ms=1000)
    with pytest.raises(ValidationError):
        BenchmarkConfig(concurrency=50)


# ---- raw TCP integration ---------------------------------------------------------------------
async def test_server_waits_for_final_byte() -> None:
    srv = TCPBenchServer("127.0.0.1", 0)
    await srv.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", srv.port)
        msg = build_message(500, 1)
        writer.write(msg[:499])
        await writer.drain()
        await asyncio.sleep(0.05)
        early = asyncio.ensure_future(reader.readexactly(4))
        await asyncio.sleep(0.05)
        assert not early.done(), "server responded before the final byte arrived"
        sent_last = time.monotonic_ns()
        writer.write(msg[499:])
        await writer.drain()
        (n,) = struct.unpack("!I", await asyncio.wait_for(early, 2))
        import json
        r = json.loads(await reader.readexactly(n))
        assert r["complete_ns"] >= sent_last and r["proc_start_ns"] >= r["complete_ns"]
        assert r["bytes"] == 500 and srv.premature_commits == 0
        writer.close()
    finally:
        await srv.stop()


async def test_early_work_overlaps_and_reused_connection_is_faster() -> None:
    srv = TCPBenchServer("127.0.0.1", 0)
    await srv.start()
    try:
        port = srv.port
        late = BenchmarkConfig(mode="split", connection="reused", split_delay_ms=30, prep_ms=20, trials=1, warmup=0)
        early = late.model_copy(update={"mode": "early_work"})
        conn = await connect("127.0.0.1", port, True)
        r_late, conn = await run_trial(late, 1, "127.0.0.1", port, conn)
        r_early, conn = await run_trial(early, 2, "127.0.0.1", port, conn)
        assert not r_late["prep_overlapped"] and r_early["prep_overlapped"]
        assert r_late["total_ms"] >= 30 + 20 and r_early["total_ms"] < r_late["total_ms"] - 10
        assert r_early["server_complete_ms"] >= r_early["last_write_ms"] - 0.5
        await conn.close()
        cold, _ = await run_trial(BenchmarkConfig(connection="cold", trials=1, warmup=0), 3, "127.0.0.1", port, None)
        assert cold["connect_ms"] is not None and cold["connect_ms"] > 0
        assert cold["client_nodelay"] is True
    finally:
        await srv.stop()


async def test_service_run_summary_and_csv() -> None:
    srv = TCPBenchServer("127.0.0.1", 0)
    await srv.start()
    bus, ids, repo = make_bus()
    svc = TCPLabService(bus, ids, "127.0.0.1", lambda: srv.port, 1)
    try:
        run = svc.start(BenchmarkConfig(trials=12, warmup=2, concurrency=3, connection="reused"))
        with pytest.raises(RuntimeError):
            svc.start(BenchmarkConfig())
        await svc._task  # noqa: SLF001
        assert run.status == "completed" and run.summary["n"] == 12 and run.summary["p90"] is not None
        assert len(run.trials) == 14 and sum(t["warmup"] for t in run.trials) == 2
        csv = svc.csv([run]).splitlines()
        assert len(csv) == 15 and csv[0].startswith("run_id,")
        assert any(e.type == "benchmark.completed" for e in repo.query())
    finally:
        await srv.stop()


# ---- HTTP integration (real uvicorn server, real sockets) ----------------------------------------
@pytest.fixture
def live_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(make_settings(http_port=port))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield port
    server.should_exit = True
    t.join(5)


def test_http_split_body_is_not_processed_early(live_server: int) -> None:
    cfg = BenchmarkConfig(transport="http", mode="split", connection="cold", split_delay_ms=40, trials=1, warmup=0)

    async def go():
        return await run_trial(cfg, 1, "127.0.0.1", live_server, None)

    r, _ = asyncio.run(go())
    assert r["ok"] and r["writes"] == 2
    assert r["server_complete_ms"] >= r["last_write_ms"] - 0.5 >= 40 - 0.5
    # Over HTTP, server timestamps are when the ASGI app *consumes* body chunks from uvicorn's buffer,
    # so only the completion guarantee is asserted, not socket-arrival ordering.
    assert r["bytes"] == 500


def test_http_echo_rejects_bad_framing(live_server: int) -> None:
    s = socket.create_connection(("127.0.0.1", live_server))
    s.sendall(b"POST /api/v1/tcp/echo HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n")
    assert b" 400 " in s.recv(4096).split(b"\r\n")[0]
    s.close()
