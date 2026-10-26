import asyncio

import pytest

from app.core.ids import IdGenerator
from app.events.bus import EventBus, TooManySubscribers
from app.persistence.repository import InMemoryEventRepository


def make_bus(capacity: int = 100, queue: int = 10, max_subs: int = 3) -> tuple[EventBus, InMemoryEventRepository]:
    repo = InMemoryEventRepository(capacity)
    return EventBus(repo, IdGenerator(), queue_size=queue, max_subscribers=max_subs), repo


def test_ids_are_sequential_per_prefix() -> None:
    ids = IdGenerator()
    a, b, c = ids.next("ORD"), ids.next("ORD"), ids.next("TRD")
    assert a.startswith("ORD-000001-") and b.startswith("ORD-000002-") and c.startswith("TRD-000001-")
    with pytest.raises(ValueError):
        ids.next("bad-prefix")


def test_publish_assigns_increasing_seq_and_records() -> None:
    bus, repo = make_bus()
    e1 = bus.publish("x.one", "test", "first")
    e2 = bus.publish("x.two", "test", "second", correlation_id="C1")
    assert (e1.seq, e2.seq) == (1, 2)
    assert e2.mono_ns >= e1.mono_ns
    assert [e.type for e in repo.query()] == ["x.one", "x.two"]
    assert [e.seq for e in repo.query(correlation_id="C1")] == [2]
    assert [e.seq for e in repo.query(after_seq=1)] == [2]
    assert [e.seq for e in repo.query(type_prefix="x.o")] == [1]


def test_history_is_bounded() -> None:
    bus, repo = make_bus(capacity=100)
    for i in range(250):
        bus.publish("t", "test", str(i))
    assert len(repo) == 100
    events = repo.query(limit=1000)
    assert events[0].seq == 151 and events[-1].seq == 250
    assert [e.seq for e in repo.query(limit=3)] == [248, 249, 250]


async def test_subscriber_queue_drops_oldest_when_full() -> None:
    bus, _ = make_bus(queue=5)
    sub = bus.subscribe()
    for i in range(12):
        bus.publish("t", "test", str(i))
    assert sub.queue.qsize() == 5
    assert sub.dropped == 7
    first = await asyncio.wait_for(sub.queue.get(), 1)
    assert first["event"]["message"] == "7"


async def test_subscriber_limit_and_unsubscribe() -> None:
    bus, _ = make_bus(max_subs=2)
    s1, _s2 = bus.subscribe(), bus.subscribe()
    with pytest.raises(TooManySubscribers):
        bus.subscribe()
    bus.unsubscribe(s1)
    assert bus.subscriber_count == 1
    bus.subscribe()
