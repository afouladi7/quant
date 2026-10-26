"""Simulation orchestrator: the global clock behind Start / Pause / Reset / Speed.

One asyncio task runs for the lifetime of the process. While the simulation is
``running`` it advances one tick every ``tick_interval / speed`` of wall time and
calls every registered :class:`Tickable` module in registration order. While
``stopped`` or ``paused`` the task keeps running (so readiness can verify it is
alive) but does not advance simulated time.

Determinism: each module obtains its own ``random.Random`` from
:meth:`SimulationOrchestrator.rng_for`, seeded from the global seed and the
module name. Resetting with the same seed reproduces the same sequence.
"""

from __future__ import annotations

import asyncio
import logging
import random
import zlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from app.events.bus import EventBus

log = logging.getLogger(__name__)

# Simulated time starts at a fixed instant so runs are reproducible.
SIM_EPOCH = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SIM_SECONDS_PER_TICK = 1
MIN_SPEED = Decimal("0.1")
MAX_SPEED = Decimal("10")
MAX_MANUAL_TICKS = 1000


class SimState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class SimulationStatus(BaseModel):
    state: SimState
    tick: int
    sim_time: datetime
    speed: Decimal
    seed: int
    tick_interval_ms: int


class Tickable(Protocol):
    name: str

    def on_tick(self, tick: int, sim_time: datetime) -> None: ...

    def on_reset(self, rng: random.Random) -> None: ...


class InvalidTransition(Exception):
    pass


class SimulationOrchestrator:
    def __init__(
        self,
        bus: EventBus,
        *,
        seed: int,
        tick_interval_ms: int,
        speed: Decimal,
        status_interval_ms: int,
    ) -> None:
        self._bus = bus
        self._seed = seed
        self._tick_interval_ms = tick_interval_ms
        self._speed = speed
        self._status_interval_s = status_interval_ms / 1000
        self._state = SimState.STOPPED
        self._tick = 0
        self._modules: list[Tickable] = []
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    # ---- module registration & determinism -------------------------------
    def register(self, module: Tickable) -> None:
        self._modules.append(module)
        module.on_reset(self.rng_for(module.name))

    def rng_for(self, name: str) -> random.Random:
        return random.Random(self._seed ^ zlib.crc32(name.encode()))

    # ---- status ------------------------------------------------------------
    @property
    def state(self) -> SimState:
        return self._state

    @property
    def tick(self) -> int:
        return self._tick

    def status(self) -> SimulationStatus:
        return SimulationStatus(
            state=self._state,
            tick=self._tick,
            sim_time=SIM_EPOCH + timedelta(seconds=self._tick * SIM_SECONDS_PER_TICK),
            speed=self._speed,
            seed=self._seed,
            tick_interval_ms=self._tick_interval_ms,
        )

    def is_alive(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---- controls ------------------------------------------------------------
    def start(self) -> SimulationStatus:
        if self._state is SimState.RUNNING:
            raise InvalidTransition("simulation is already running")
        previous = self._state
        self._state = SimState.RUNNING
        verb = "resumed" if previous is SimState.PAUSED else "started"
        self._bus.publish(
            f"simulation.{verb}",
            "simulation",
            f"Simulation {verb} at tick {self._tick}.",
            data={"from_state": previous.value, "tick": self._tick, "speed": str(self._speed)},
        )
        self._wake.set()
        return self._broadcast_status()

    def pause(self) -> SimulationStatus:
        if self._state is not SimState.RUNNING:
            raise InvalidTransition(f"cannot pause from state '{self._state.value}'")
        self._state = SimState.PAUSED
        self._bus.publish(
            "simulation.paused", "simulation", f"Simulation paused at tick {self._tick}.", data={"tick": self._tick}
        )
        return self._broadcast_status()

    def reset(self, seed: int | None = None) -> SimulationStatus:
        if seed is not None:
            self._seed = seed
        previous_tick = self._tick
        self._state = SimState.STOPPED
        self._tick = 0
        for module in self._modules:
            module.on_reset(self.rng_for(module.name))
        self._bus.publish(
            "simulation.reset",
            "simulation",
            f"Simulation reset to its initial state (seed {self._seed}).",
            data={"seed": self._seed, "previous_tick": previous_tick},
        )
        return self._broadcast_status()

    def set_speed(self, speed: Decimal) -> SimulationStatus:
        if not (MIN_SPEED <= speed <= MAX_SPEED):
            raise ValueError(f"speed must be between {MIN_SPEED} and {MAX_SPEED}")
        old = self._speed
        self._speed = speed
        self._bus.publish(
            "simulation.speed_changed",
            "simulation",
            f"Simulation speed changed from {old}x to {speed}x.",
            data={"old": str(old), "new": str(speed)},
        )
        self._wake.set()
        return self._broadcast_status()

    def _broadcast_status(self) -> SimulationStatus:
        status = self.status()
        self._bus.broadcast({"kind": "status", "status": status.model_dump(mode="json")})
        return status

    # ---- loop ----------------------------------------------------------------
    def advance(self) -> None:
        """Advance exactly one tick (used by the loop and by deterministic tests)."""
        self._tick += 1
        sim_time = SIM_EPOCH + timedelta(seconds=self._tick * SIM_SECONDS_PER_TICK)
        for module in self._modules:
            try:
                module.on_tick(self._tick, sim_time)
            except Exception:
                log.exception("module tick failed", extra={"module": module.name, "tick": self._tick})

    def advance_many(self, ticks: int) -> None:
        """Advance ``ticks`` ticks synchronously (deterministic stepping while not running)."""
        if self._state is SimState.RUNNING:
            raise InvalidTransition("pause the simulation before stepping it manually")
        if not 1 <= ticks <= MAX_MANUAL_TICKS:
            raise ValueError(f"ticks must be between 1 and {MAX_MANUAL_TICKS}")
        for _ in range(ticks):
            self.advance()
        if self._state is SimState.STOPPED:
            self._state = SimState.PAUSED
        self._bus.publish(
            "simulation.advanced", "simulation", f"Simulation stepped forward {ticks} tick(s) to tick {self._tick}.",
            data={"ticks": ticks, "tick": self._tick},
        )
        self._broadcast_status()

    def pause_if_running(self) -> None:
        if self._state is SimState.RUNNING:
            self.pause()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_status = loop.time()
        while True:
            interval = float(Decimal(self._tick_interval_ms) / Decimal(1000) / self._speed)
            if self._state is SimState.RUNNING:
                self.advance()
            now = loop.time()
            if now >= next_status:
                self._broadcast_status()
                next_status = now + self._status_interval_s
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=interval)
            except TimeoutError:
                pass

    async def start_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="simulation-loop")

    async def stop_loop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
