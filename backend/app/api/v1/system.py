from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import APP_VERSION
from app.state import AppContainer, get_container

router = APIRouter(tags=["system"])


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    simulation_mode: bool
    persistence_mode: str
    ephemeral: bool
    notice: str
    authentication: str
    limits: dict[str, int]
    persistence: dict


@router.get("/info", response_model=InfoResponse)
async def info(c: Annotated[AppContainer, Depends(get_container)]) -> InfoResponse:
    s = c.settings
    return InfoResponse(
        name="MarketLab",
        version=APP_VERSION,
        environment=s.environment,
        simulation_mode=True,
        persistence_mode=s.persistence_mode.value,
        ephemeral=s.is_ephemeral,
        notice="Every trade and price in MarketLab is hypothetical. No real orders, funds or market data are involved.",
        authentication="none (local-demo design decision: run only on an isolated, trusted network)",
        persistence=c.sink.status(),
        limits={
            "event_history_limit": s.event_history_limit,
            "ws_queue_size": s.ws_queue_size,
            "ws_max_clients": s.ws_max_clients,
        },
    )
