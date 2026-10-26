from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.simulation.orchestrator import MAX_SPEED, MIN_SPEED, InvalidTransition, SimulationStatus
from app.state import AppContainer, get_container

router = APIRouter(prefix="/simulation", tags=["simulation"])

Container = Annotated[AppContainer, Depends(get_container)]


class ResetRequest(BaseModel):
    seed: int | None = Field(None, ge=0, le=2**32 - 1, description="Optional new seed; omit to keep the current one")


class SpeedRequest(BaseModel):
    speed: Decimal = Field(ge=MIN_SPEED, le=MAX_SPEED, decimal_places=2)


@router.get("", response_model=SimulationStatus)
async def get_status(c: Container) -> SimulationStatus:
    return c.sim.status()


@router.post("/start", response_model=SimulationStatus)
async def start(c: Container) -> SimulationStatus:
    try:
        return c.sim.start()
    except InvalidTransition as exc:
        raise ApiError(409, "invalid_transition", str(exc)) from exc


@router.post("/pause", response_model=SimulationStatus)
async def pause(c: Container) -> SimulationStatus:
    try:
        return c.sim.pause()
    except InvalidTransition as exc:
        raise ApiError(409, "invalid_transition", str(exc)) from exc


@router.post("/reset", response_model=SimulationStatus)
async def reset(c: Container, body: Annotated[ResetRequest | None, Body()] = None) -> SimulationStatus:
    # Reset is naturally idempotent: repeating it yields the same initial state.
    return c.sim.reset(seed=body.seed if body else None)


class AdvanceRequest(BaseModel):
    ticks: int = Field(1, ge=1, le=1000)


@router.post("/advance", response_model=SimulationStatus)
async def advance(c: Container, body: AdvanceRequest) -> SimulationStatus:
    """Step the simulation forward deterministically (only while stopped or paused)."""
    try:
        c.sim.advance_many(body.ticks)
    except InvalidTransition as exc:
        raise ApiError(409, "invalid_transition", str(exc)) from exc
    return c.sim.status()


@router.put("/speed", response_model=SimulationStatus)
async def set_speed(c: Container, body: SpeedRequest) -> SimulationStatus:
    return c.sim.set_speed(body.speed)
