from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect

from app.events.bus import TooManySubscribers
from app.events.models import Event
from app.state import AppContainer, get_container, get_container_ws

router = APIRouter(tags=["events"])
log = logging.getLogger(__name__)


@router.get("/events", response_model=list[Event])
async def list_events(
    c: Annotated[AppContainer, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    after_seq: Annotated[int | None, Query(ge=0)] = None,
    type: Annotated[str | None, Query(max_length=64, description="Event type prefix, e.g. 'simulation.'")] = None,
    module: Annotated[str | None, Query(max_length=32)] = None,
    correlation_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[Event]:
    return c.events.query(
        limit=limit, after_seq=after_seq, type_prefix=type, module=module, correlation_id=correlation_id
    )


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    """Live stream of ``event`` and ``status`` messages.

    Messages: ``hello`` (once, with current status and last event seq),
    ``event``, ``status``, and ``dropped`` (count of messages discarded because
    this client fell behind; the client should refetch /events if it cares).
    """
    c: AppContainer = get_container_ws(websocket)
    await websocket.accept()
    try:
        sub = c.bus.subscribe()
    except TooManySubscribers:
        await websocket.close(code=1013, reason="too many stream clients")
        return
    reported_drops = 0
    try:
        await websocket.send_json(
            {"kind": "hello", "status": c.sim.status().model_dump(mode="json"), "last_seq": c.bus.last_seq}
        )
        receiver = asyncio.create_task(_drain_client(websocket))
        while not receiver.done():
            getter = asyncio.create_task(sub.queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in done:
                getter.cancel()
                break
            if sub.dropped != reported_drops:
                await websocket.send_json({"kind": "dropped", "count": sub.dropped - reported_drops})
                reported_drops = sub.dropped
            await websocket.send_json(getter.result())
        receiver.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        c.bus.unsubscribe(sub)


async def _drain_client(websocket: WebSocket) -> None:
    """Consume (and ignore) client frames; returns when the client disconnects."""
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        return
