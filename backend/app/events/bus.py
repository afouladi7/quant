"""Event bus: records events in the repository and fans them out to live subscribers.

Each subscriber (e.g. one WebSocket client) gets its own bounded queue. If a slow
client lets its queue fill up, the oldest queued message is dropped and the
subscriber's ``dropped`` counter increments, so a stalled browser can never make
the server's memory grow without bound.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.clock import mono_ns, utc_now
from app.core.ids import IdGenerator
from app.events.models import Event
from app.persistence.repository import EventRepository

log = logging.getLogger(__name__)


@dataclass
class Subscription:
    queue: asyncio.Queue[dict[str, Any]]
    dropped: int = 0
    id: int = field(default=0)

    def offer(self, message: dict[str, Any]) -> None:
        while True:
            try:
                self.queue.put_nowait(message)
                return
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:  # pragma: no cover - race-free in single loop
                    pass


class TooManySubscribers(Exception):
    pass


class EventBus:
    def __init__(self, repository: EventRepository, ids: IdGenerator, queue_size: int, max_subscribers: int, sink: Any = None) -> None:
        self._repo = repository
        self.sink = sink
        self._ids = ids
        self._queue_size = queue_size
        self._max_subscribers = max_subscribers
        self._subs: dict[int, Subscription] = {}
        self._sub_ids = itertools.count(1)
        self._seq = itertools.count(1)
        self.last_seq = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(
        self,
        type: str,
        module: str,
        message: str,
        *,
        entity_id: str | None = None,
        correlation_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Event:
        seq = next(self._seq)
        self.last_seq = seq
        event = Event(
            seq=seq,
            id=self._ids.next("EVT"),
            ts=utc_now(),
            mono_ns=mono_ns(),
            type=type,
            module=module,
            entity_id=entity_id,
            correlation_id=correlation_id,
            message=message,
            data=data or {},
        )
        self._repo.append(event)
        if self.sink is not None:
            self.sink.record_event(event)
        self.broadcast({"kind": "event", "event": event.model_dump(mode="json")})
        log.debug(message, extra={"event_type": type, "event_seq": seq, "entity_id": entity_id})
        return event

    def broadcast(self, message: dict[str, Any]) -> None:
        """Send a non-event message (e.g. a status snapshot) to all subscribers."""
        for sub in self._subs.values():
            sub.offer(message)

    def subscribe(self) -> Subscription:
        if len(self._subs) >= self._max_subscribers:
            raise TooManySubscribers()
        sub = Subscription(queue=asyncio.Queue(maxsize=self._queue_size), id=next(self._sub_ids))
        self._subs[sub.id] = sub
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.pop(sub.id, None)
