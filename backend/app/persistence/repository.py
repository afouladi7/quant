"""Repository interfaces.

The application talks only to these interfaces so the ephemeral (in-memory)
and persistent (PostgreSQL, planned) implementations are interchangeable.
Later phases add order/trade/benchmark repositories alongside EventRepository.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque

from app.events.models import Event


class EventRepository(ABC):
    @abstractmethod
    def append(self, event: Event) -> None: ...

    @abstractmethod
    def query(
        self,
        *,
        limit: int = 100,
        after_seq: int | None = None,
        type_prefix: str | None = None,
        correlation_id: str | None = None,
        module: str | None = None,
    ) -> list[Event]:
        """Return matching events, oldest first, at most ``limit`` (the newest ones)."""

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def healthy(self) -> bool: ...


class InMemoryEventRepository(EventRepository):
    """Bounded ring buffer; the oldest events are discarded beyond ``capacity``."""

    def __init__(self, capacity: int) -> None:
        self._events: deque[Event] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        assert self._events.maxlen is not None
        return self._events.maxlen

    def __len__(self) -> int:
        return len(self._events)

    def append(self, event: Event) -> None:
        self._events.append(event)

    def query(
        self,
        *,
        limit: int = 100,
        after_seq: int | None = None,
        type_prefix: str | None = None,
        correlation_id: str | None = None,
        module: str | None = None,
    ) -> list[Event]:
        matched = [
            e
            for e in self._events
            if (after_seq is None or e.seq > after_seq)
            and (type_prefix is None or e.type.startswith(type_prefix))
            and (correlation_id is None or e.correlation_id == correlation_id)
            and (module is None or e.module == module)
        ]
        return matched[-limit:] if limit > 0 else []

    def clear(self) -> None:
        self._events.clear()

    def healthy(self) -> bool:
        return True
