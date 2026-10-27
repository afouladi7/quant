from __future__ import annotations

import asyncio
import time

from starlette.requests import ClientDisconnect
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.core.jsonresp import jsonify
from app.tcplab.client import BenchmarkConfig
from app.tcplab.protocol import MAX_MESSAGE
from app.tcplab.server import ECHO_STATS
from app.tcplab.service import SUITE_STANDARD
from app.tcplab.work import do_work
from app.state import AppContainer, get_container

router = APIRouter(prefix="/tcp", tags=["tcp lab"])
Container = Annotated[AppContainer, Depends(get_container)]


def _int_header(request: Request, name: str, lo: int, hi: int) -> int:
    raw = request.headers.get(name, "0")
    try:
        v = int(raw)
    except ValueError as exc:
        raise ApiError(400, "bad_header", f"{name} must be an integer") from exc
    if not lo <= v <= hi:
        raise ApiError(400, "bad_header", f"{name} must be {lo}..{hi}")
    return v


@router.post("/echo", summary="HTTP benchmark target: completes only after the full body has arrived")
async def echo(request: Request) -> JSONResponse:
    if "content-length" not in request.headers:
        raise ApiError(411, "length_required", "Content-Length is required so the server knows when the message is complete")
    length = _int_header(request, "content-length", 1, MAX_MESSAGE)
    prep = _int_header(request, "x-ml-prep-ms", 0, 200)
    proc = _int_header(request, "x-ml-proc-ms", 0, 200)
    early = request.headers.get("x-ml-early-work") == "1"
    buf = bytearray()
    first_rx = prefix_ns = None
    chunks = 0
    prep_task: asyncio.Task | None = None
    stream = request.stream()
    while True:
        try:
            chunk = await stream.__anext__()
        except StopAsyncIteration:
            break
        except ClientDisconnect:
            # The client sent part of the body, then closed the connection: abandoned, never processed.
            ECHO_STATS["discarded_incomplete"] += 1
            if prep_task is not None:
                prep_task.cancel()
            return JSONResponse({"aborted": True}, status_code=400)  # nobody is listening; nothing was processed
        if not chunk:
            continue
        now = time.monotonic_ns()
        chunks += 1
        first_rx = first_rx or now
        buf += chunk
        if len(buf) > length:
            raise ApiError(400, "body_too_long", "Body exceeds Content-Length")
        if prefix_ns is None and len(buf) >= length - 1:
            prefix_ns = now
            if early and prep:
                prep_task = asyncio.create_task(do_work(bytes(buf[: length - 1]), prep))
    complete_ns = time.monotonic_ns()
    if len(buf) != length:
        raise ApiError(400, "incomplete_body", f"Received {len(buf)} of {length} bytes")
    prep_start, prep_end, _ = await prep_task if prep_task else await do_work(bytes(buf), prep)
    proc_start, proc_end, digest = await do_work(bytes(buf), proc)
    ECHO_STATS["completed"] += 1
    return JSONResponse({
        "bytes": len(buf), "reads": chunks, "first_rx_ns": first_rx, "prefix_ready_ns": prefix_ns, "complete_ns": complete_ns,
        "prep_start_ns": prep_start, "prep_end_ns": prep_end, "proc_start_ns": proc_start, "proc_end_ns": proc_end,
        "response_write_ns": time.monotonic_ns(), "early_work": early, "server_nodelay_applied": None, "digest": digest,
    })


@router.get("/info")
async def info(c: Container) -> Response:
    return jsonify({
        "raw_tcp": {"host": c.tcplab.host, "port": c.tcp_server.port, "running": c.tcp_server.running,
                    "connections": c.tcp_server.connections, "messages": c.tcp_server.messages,
                    "premature_commits": c.tcp_server.premature_commits, "discarded_incomplete": c.tcp_server.discarded_incomplete},
        "http": {"host": c.tcplab.host, "port": c.tcplab.http_port, "path": "/api/v1/tcp/echo",
                 "discarded_incomplete": ECHO_STATS["discarded_incomplete"]},
        "busy": c.tcplab.busy,
        "limits": {"max_trials": 500, "max_warmup": 50, "max_concurrency": 8, "max_payload": MAX_MESSAGE, "max_delay_ms": 1000,
                   "max_run_seconds": 120},
        "suite": SUITE_STANDARD,
        "safety": "Benchmarks can only target this process's own loopback endpoints.",
    })


@router.post("/benchmarks", status_code=202)
async def start(c: Container, cfg: BenchmarkConfig) -> Response:
    try:
        run = c.tcplab.start(cfg)
    except RuntimeError as exc:
        raise ApiError(409, "busy", str(exc)) from exc
    return jsonify(run, 202)


class SuiteRequest(BaseModel):
    transport: Literal["raw_tcp", "http"] = "raw_tcp"
    trials: int = Field(40, ge=5, le=200)
    tcp_nodelay: bool = True


@router.post("/suites", status_code=202)
async def start_suite(c: Container, body: SuiteRequest) -> Response:
    try:
        suite = c.tcplab.start_suite(body.transport, {"trials": body.trials, "tcp_nodelay": body.tcp_nodelay})
    except RuntimeError as exc:
        raise ApiError(409, "busy", str(exc)) from exc
    return jsonify(suite, 202)


@router.get("/benchmarks")
async def list_runs(c: Container) -> Response:
    return jsonify([{k: v for k, v in r.model_dump().items() if k != "trials"} for r in reversed(c.tcplab.runs.values())])


@router.get("/benchmarks/{run_id}")
async def get_run(c: Container, run_id: str) -> Response:
    run = c.tcplab.runs.get(run_id)
    if run is None:
        raise ApiError(404, "not_found", f"Unknown run {run_id}")
    return jsonify(run)


@router.get("/suites/{suite_id}")
async def get_suite(c: Container, suite_id: str) -> Response:
    s = c.tcplab.suites.get(suite_id)
    if s is None:
        raise ApiError(404, "not_found", f"Unknown suite {suite_id}")
    return jsonify({"suite": s, "runs": [c.tcplab.runs[r] for r in s.run_ids if r in c.tcplab.runs]})


@router.post("/cancel")
async def cancel(c: Container) -> Response:
    await c.tcplab.cancel()
    return jsonify({"busy": c.tcplab.busy})


def _csv(text: str, name: str) -> Response:
    return Response(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/benchmarks/{run_id}/csv")
async def run_csv(c: Container, run_id: str) -> Response:
    run = c.tcplab.runs.get(run_id)
    if run is None:
        raise ApiError(404, "not_found", f"Unknown run {run_id}")
    return _csv(c.tcplab.csv([run]), run_id)


@router.get("/suites/{suite_id}/csv")
async def suite_csv(c: Container, suite_id: str) -> Response:
    s = c.tcplab.suites.get(suite_id)
    if s is None:
        raise ApiError(404, "not_found", f"Unknown suite {suite_id}")
    return _csv(c.tcplab.csv([c.tcplab.runs[r] for r in s.run_ids if r in c.tcplab.runs]), suite_id)
