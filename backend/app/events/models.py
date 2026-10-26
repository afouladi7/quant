from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    """An actual application event (never a UI-only annotation)."""

    seq: int = Field(description="Monotonically increasing per process lifetime; survives simulation reset")
    id: str
    ts: datetime = Field(description="Server UTC wall-clock time")
    mono_ns: int = Field(description="Server monotonic clock reading, for ordering/latency")
    type: str = Field(description="Dotted event type, e.g. 'simulation.started'")
    module: str = Field(description="Owning module: simulation, marketmaker, fx, portfolio, tcplab")
    entity_id: str | None = None
    correlation_id: str | None = None
    message: str = Field(description="Concise plain-English explanation")
    data: dict[str, Any] = Field(default_factory=dict, description="Technical metadata")
