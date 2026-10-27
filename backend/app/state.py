"""Process-wide application container, created once in the app lifespan."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, WebSocket

from app.config import Settings
from app.core.idempotency import IdempotencyStore
from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.fx.service import FXService
from app.marketmaker.service import MarketMakerService
from app.playground.service import Playground
from app.portfolio.service import PortfolioService
from app.persistence.repository import EventRepository, InMemoryEventRepository
from app.persistence.sink import NullSink, PostgresSink
from app.simulation.orchestrator import SimulationOrchestrator
from app.tcplab.server import TCPBenchServer
from app.tcplab.service import TCPLabService


@dataclass
class AppContainer:
    settings: Settings
    ids: IdGenerator
    events: EventRepository
    bus: EventBus
    sim: SimulationOrchestrator
    idempotency: IdempotencyStore
    mm: MarketMakerService
    fx: FXService
    portfolio: PortfolioService
    tcp_server: TCPBenchServer
    tcplab: TCPLabService
    sink: NullSink | PostgresSink
    playground: Playground


def build_container(settings: Settings) -> AppContainer:
    ids = IdGenerator()
    # Live state and recent events are always in memory (authoritative). In persistent
    # mode a PostgresSink additionally archives events, trades, benchmarks and configs.
    sink: NullSink | PostgresSink = (
        PostgresSink(settings.dsn, settings.environment) if not settings.is_ephemeral and settings.dsn else NullSink()
    )
    events = InMemoryEventRepository(capacity=settings.event_history_limit)
    bus = EventBus(events, ids, queue_size=settings.ws_queue_size, max_subscribers=settings.ws_max_clients, sink=sink)
    sim = SimulationOrchestrator(
        bus,
        seed=settings.sim_seed,
        tick_interval_ms=settings.sim_tick_interval_ms,
        speed=settings.sim_default_speed,
        status_interval_ms=settings.status_broadcast_interval_ms,
    )
    mm = MarketMakerService(bus, ids, tick_source=lambda: sim.tick, advance=sim.advance_many, pause_sim=sim.pause_if_running)
    sim.register(mm)
    fx = FXService(bus, ids, tick_source=lambda: sim.tick, pause_sim=sim.pause_if_running)
    sim.register(fx)
    portfolio = PortfolioService(bus, ids, fx, pause_sim=sim.pause_if_running)
    sim.register(portfolio)
    tcp_server = TCPBenchServer(settings.tcplab_host, settings.tcplab_port)
    tcplab = TCPLabService(bus, ids, settings.tcplab_host, lambda: tcp_server.port, settings.http_port)
    tcplab.on_finished = sink.record_benchmark
    from app.tcplab.server import ECHO_STATS

    tcplab.counters = lambda: {
        "raw_tcp": {"discarded": tcp_server.discarded_incomplete, "completed": tcp_server.messages, "premature": tcp_server.premature_commits},
        "http": {"discarded": ECHO_STATS["discarded_incomplete"], "completed": ECHO_STATS["completed"], "premature": 0},
    }
    return AppContainer(
        settings=settings, ids=ids, events=events, bus=bus, sim=sim, idempotency=IdempotencyStore(), mm=mm, fx=fx,
        portfolio=portfolio, tcp_server=tcp_server, tcplab=tcplab, sink=sink, playground=Playground(bus, ids),
    )


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_container_ws(websocket: WebSocket) -> AppContainer:
    return websocket.app.state.container
