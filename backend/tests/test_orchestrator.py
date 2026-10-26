import random
from datetime import datetime
from decimal import Decimal

import pytest

from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.persistence.repository import InMemoryEventRepository
from app.simulation.orchestrator import SIM_EPOCH, InvalidTransition, SimState, SimulationOrchestrator


class Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.ticks: list[int] = []
        self.draws: list[float] = []
        self.rng = random.Random(0)

    def on_tick(self, tick: int, sim_time: datetime) -> None:
        self.ticks.append(tick)
        self.draws.append(self.rng.random())

    def on_reset(self, rng: random.Random) -> None:
        self.ticks.clear()
        self.draws.clear()
        self.rng = rng


def make_sim(seed: int = 42) -> tuple[SimulationOrchestrator, InMemoryEventRepository]:
    repo = InMemoryEventRepository(1000)
    bus = EventBus(repo, IdGenerator(), queue_size=100, max_subscribers=5)
    sim = SimulationOrchestrator(bus, seed=seed, tick_interval_ms=20, speed=Decimal(1), status_interval_ms=1000)
    return sim, repo


def test_state_machine_transitions_and_events() -> None:
    sim, repo = make_sim()
    assert sim.state is SimState.STOPPED
    with pytest.raises(InvalidTransition):
        sim.pause()
    sim.start()
    with pytest.raises(InvalidTransition):
        sim.start()
    sim.pause()
    assert sim.status().state is SimState.PAUSED
    sim.start()
    sim.reset()
    assert sim.state is SimState.STOPPED and sim.tick == 0
    assert [e.type for e in repo.query()] == [
        "simulation.started",
        "simulation.paused",
        "simulation.resumed",
        "simulation.reset",
    ]


def test_advance_moves_simulated_time() -> None:
    sim, _ = make_sim()
    rec = Recorder()
    sim.register(rec)
    for _ in range(3):
        sim.advance()
    assert rec.ticks == [1, 2, 3]
    assert (sim.status().sim_time - SIM_EPOCH).total_seconds() == 3


def test_reset_with_same_seed_is_reproducible() -> None:
    sim, _ = make_sim(seed=123)
    rec = Recorder()
    sim.register(rec)
    for _ in range(5):
        sim.advance()
    first = list(rec.draws)
    sim.reset()
    for _ in range(5):
        sim.advance()
    assert rec.draws == first
    sim.reset(seed=124)
    for _ in range(5):
        sim.advance()
    assert rec.draws != first


def test_speed_bounds() -> None:
    sim, _ = make_sim()
    sim.set_speed(Decimal("2.5"))
    assert sim.status().speed == Decimal("2.5")
    for bad in (Decimal("0"), Decimal("11")):
        with pytest.raises(ValueError):
            sim.set_speed(bad)


async def test_loop_advances_only_while_running() -> None:
    import asyncio

    sim, _ = make_sim()
    await sim.start_loop()
    try:
        assert sim.is_alive()
        await asyncio.sleep(0.1)
        assert sim.tick == 0
        sim.start()
        await asyncio.sleep(0.15)
        sim.pause()
        ticks = sim.tick
        assert ticks >= 2
        await asyncio.sleep(0.1)
        assert sim.tick == ticks
    finally:
        await sim.stop_loop()
    assert not sim.is_alive()
