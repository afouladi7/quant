from __future__ import annotations

from decimal import Decimal

from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.markets.venue import FeeSchedule, Venue
from app.persistence.repository import InMemoryEventRepository


def make_bus() -> tuple[EventBus, IdGenerator, InMemoryEventRepository]:
    repo = InMemoryEventRepository(10_000)
    ids = IdGenerator()
    return EventBus(repo, ids, queue_size=100, max_subscribers=5), ids, repo


def make_venue(tick: str = "0.01", lot: int = 1, fees: FeeSchedule | None = None, **kw: object) -> tuple[Venue, InMemoryEventRepository]:
    bus, ids, repo = make_bus()
    v = Venue(
        "TEST", "XYZ", tick_size=Decimal(tick), lot_size=lot, fees=fees or FeeSchedule(), bus=bus, ids=ids,
        tick_source=lambda: 0, module="test", max_order_qty=1_000_000, **kw,  # type: ignore[arg-type]
    )
    return v, repo
