from decimal import Decimal as D

import pytest

from app.core.money import from_ticks, is_on_tick, round_to_tick, to_ticks
from app.markets.book import OrderBook, Resting
from app.markets.models import Side


def test_tick_conversion_and_rounding() -> None:
    t = D("0.01")
    assert to_ticks(D("100.05"), t) == 10005
    assert from_ticks(10005, t) == D("100.05")
    with pytest.raises(ValueError):
        to_ticks(D("100.005"), t)
    assert round_to_tick(D("99.957"), t, "down") == D("99.95")
    assert round_to_tick(D("100.041"), t, "up") == D("100.05")
    assert round_to_tick(D("100.045"), t) == D("100.04")  # banker's rounding at exact half
    assert is_on_tick(D("1.27005"), D("0.00001")) and not is_on_tick(D("1.270005"), D("0.00001"))


def test_price_time_priority() -> None:
    b = OrderBook()
    b.add(Resting("a1", Side.SELL, 101, 100, "x"))
    b.add(Resting("a2", Side.SELL, 100, 50, "y"))   # better price
    b.add(Resting("a3", Side.SELL, 100, 70, "z"))   # same price, later
    r = b.match(Side.BUY, 150, None, "taker")
    assert [(m.maker.order_id, m.price, m.quantity) for m in r.fills] == [("a2", 100, 50), ("a3", 100, 70), ("a1", 101, 30)]
    assert b.levels(Side.SELL) == [(101, 70, 1)]


def test_limit_is_never_exceeded() -> None:
    b = OrderBook()
    b.add(Resting("a1", Side.SELL, 100, 10, "x"))
    b.add(Resting("a2", Side.SELL, 102, 10, "x"))
    r = b.match(Side.BUY, 50, 101, "taker")
    assert r.filled == 10 and all(m.price <= 101 for m in r.fills)
    b.add(Resting("b1", Side.BUY, 99, 10, "y"))
    b.add(Resting("b2", Side.BUY, 97, 10, "y"))
    r = b.match(Side.SELL, 50, 98, "taker")
    assert r.filled == 10 and all(m.price >= 98 for m in r.fills)


def test_bids_best_is_highest_and_remove() -> None:
    b = OrderBook()
    for i, p in enumerate([95, 99, 97]):
        b.add(Resting(f"b{i}", Side.BUY, p, 1, "x"))
    assert b.best(Side.BUY) == 99
    assert [lvl[0] for lvl in b.levels(Side.BUY)] == [99, 97, 95]
    b.remove("b1")
    assert b.best(Side.BUY) == 97 and len(b) == 2
    assert b.available(Side.SELL, 96) == 1


def test_self_trade_prevention_cancels_resting() -> None:
    b = OrderBook()
    b.add(Resting("mine", Side.SELL, 100, 10, "fund"))
    b.add(Resting("other", Side.SELL, 100, 10, "lp"))
    r = b.match(Side.BUY, 10, None, "fund")
    assert [m.maker.order_id for m in r.fills] == ["other"]
    assert [x.order_id for x in r.self_trade_canceled] == ["mine"]
    assert len(b) == 0
