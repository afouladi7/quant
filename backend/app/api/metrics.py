"""Prometheus text-format metrics (no client library needed). Unauthenticated, like the rest of the demo."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.state import AppContainer, get_container

router = APIRouter(tags=["health"])


def _line(name: str, help_: str, kind: str, value: float, labels: str = "") -> str:
    return f"# HELP {name} {help_}\n# TYPE {name} {kind}\n{name}{labels} {value}\n"


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(c: Annotated[AppContainer, Depends(get_container)]) -> str:
    out = [
        _line("marketlab_events_published_total", "Events published since start", "counter", c.bus.last_seq),
        _line("marketlab_stream_clients", "Connected WebSocket clients", "gauge", c.bus.subscriber_count),
        _line("marketlab_simulation_tick", "Current simulation tick", "gauge", c.sim.tick),
        _line("marketlab_simulation_running", "1 if the simulation clock is running", "gauge", int(c.sim.state.value == "running")),
        _line("marketlab_mm_trades_in_memory", "Market-maker trades held in memory", "gauge", len(c.mm.venue.trades)),
        _line("marketlab_mm_inventory_shares", "Market-maker inventory", "gauge", c.mm.ledger.position),
        _line("marketlab_fx_parent_orders_in_memory", "FX parent orders held in memory", "gauge", len(c.fx.parents)),
        _line("marketlab_tcplab_runs_in_memory", "Benchmark runs held in memory", "gauge", len(c.tcplab.runs)),
        _line("marketlab_tcplab_busy", "1 while a benchmark runs", "gauge", int(c.tcplab.busy)),
        _line("marketlab_tcplab_premature_commits_total", "Raw TCP messages committed before complete (must be 0)", "counter", c.tcp_server.premature_commits),
    ]
    st = c.sink.status()
    if st.get("persistent"):
        out += [
            _line("marketlab_persistence_connected", "1 if PostgreSQL archive is connected", "gauge", int(bool(st["connected"]))),
            _line("marketlab_persistence_written_total", "Records written to PostgreSQL", "counter", st["written"]),
            _line("marketlab_persistence_dropped_total", "Records dropped (queue overflow or shutdown)", "counter", st["dropped"]),
            _line("marketlab_persistence_queued", "Records waiting to be written", "gauge", st["queued"]),
        ]
    return "".join(out)
