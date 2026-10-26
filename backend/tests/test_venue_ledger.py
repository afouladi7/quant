from decimal import Decimal as D

import pytest

from app.markets.ledger import PositionLedger
from app.markets.models import OrderStatus, OrderType, Side, TimeInForce
from app.markets.venue import FeeSchedule
from tests.helpers import make_venue


def place(v, owner, side, qty, price=None, **kw):
    t = OrderType.LIMIT if price is not None else OrderType.MARKET
    return v.submit(owner=owner, side=side, type=t, quantity=qty, limit_price=D(price) if price else None, **kw)


def test_partial_fill_then_rest_then_cancel() -> None:
    v, repo = make_venue()
    place(v, "mm", Side.SELL, 100, "100.05")
    r = place(v, "customer", Side.BUY, 150, "100.05")
    assert r.order.filled_qty == 100 and r.order.status is OrderStatus.PARTIALLY_FILLED
    assert v.best_bid() == D("100.05")
    c = v.cancel(r.order.id)
    assert c.status is OrderStatus.CANCELED and c.filled_qty == 100
    with pytest.raises(Exception):
        v.cancel(r.order.id)
    types = [e.type for e in repo.query(limit=100)]
    assert "order.resting" in types and "order.canceled" in types and "trade.executed" in types


def test_market_order_ioc_remainder_canceled() -> None:
    v, _ = make_venue()
    place(v, "mm", Side.SELL, 60, "100.05")
    r = place(v, "customer", Side.BUY, 100)
    assert r.order.status is OrderStatus.CANCELED
    assert r.order.filled_qty == 60 and r.order.unfilled_qty == 40
    assert "unfilled 40 was canceled" in (r.order.reason or "")


def test_market_order_with_no_liquidity() -> None:
    v, _ = make_venue()
    r = place(v, "customer", Side.BUY, 100)
    assert r.order.status is OrderStatus.CANCELED and r.order.filled_qty == 0 and not r.trades


def test_fok_rejects_when_insufficient() -> None:
    v, _ = make_venue()
    place(v, "mm", Side.SELL, 60, "100.05")
    r = place(v, "customer", Side.BUY, 100, tif=TimeInForce.FOK)
    assert r.order.status is OrderStatus.REJECTED and v.book.available(Side.BUY) == 60


def test_validation_rejections() -> None:
    v, _ = make_venue(lot=10)
    assert place(v, "c", Side.BUY, 15, "100").order.status is OrderStatus.REJECTED
    assert place(v, "c", Side.BUY, 10, "100.001").order.status is OrderStatus.REJECTED
    assert place(v, "c", Side.BUY, 0, "100").order.status is OrderStatus.REJECTED
    r = v.submit(owner="c", side=Side.BUY, type=OrderType.LIMIT, quantity=10, limit_price=None)
    assert r.order.status is OrderStatus.REJECTED
    r = v.submit(owner="c", side=Side.BUY, type=OrderType.MARKET, quantity=10, tif=TimeInForce.GTC)
    assert r.order.status is OrderStatus.REJECTED


def test_fees_and_avg_price() -> None:
    v, _ = make_venue(fees=FeeSchedule(per_unit=D("0.005")))
    place(v, "mm", Side.SELL, 50, "100.05")
    place(v, "mm", Side.SELL, 50, "100.07")
    r = place(v, "customer", Side.BUY, 100)
    assert r.order.avg_fill_price == D("100.06")
    assert r.order.fees == D("0.5")
    assert [t.taker_fee for t in r.trades] == [D("0.25"), D("0.25")]


def test_listener_receives_fills() -> None:
    v, _ = make_venue()
    got = []
    v.on_fill(lambda t, taker, maker: got.append((t.quantity, taker.owner, maker.owner)))
    place(v, "mm", Side.BUY, 100, "99.95")
    place(v, "customer", Side.SELL, 40)
    assert got == [(40, "customer", "mm")]


def test_expiry() -> None:
    v, _ = make_venue()
    r = place(v, "c", Side.BUY, 10, "99", expires_tick=5)
    v.expire(4)
    assert r.order.status is OrderStatus.OPEN
    v.expire(5)
    assert r.order.status is OrderStatus.CANCELED and len(v.book) == 0


# ---- ledger -------------------------------------------------------------
def identity(l: PositionLedger, mark: D) -> None:
    assert l.equity(mark) - l.initial_cash == l.realized_pnl + l.unrealized_pnl(mark) - l.fees


def test_spread_capture_round_trip() -> None:
    l = PositionLedger.with_cash(D("1000000"))
    l.apply(Side.BUY, 100, D("99.95"), fee=D("0.50"), reference=D("100.00"))
    identity(l, D("100"))
    assert l.unrealized_pnl(D("100")) == D("5.00")
    l.apply(Side.SELL, 100, D("100.05"), fee=D("0.50"), reference=D("100.00"))
    assert l.position == 0
    assert l.realized_pnl == D("10.00")
    assert l.gross_spread_captured == D("10.00")
    assert l.fees == D("1.00")
    assert l.net_pnl(D("100")) == D("9.00")
    identity(l, D("123.45"))


def test_fifo_long_and_flip_to_short() -> None:
    l = PositionLedger.with_cash(D(0))
    l.apply(Side.BUY, 100, D("10"))
    l.apply(Side.BUY, 100, D("12"))
    assert l.avg_cost == D("11")
    r = l.apply(Side.SELL, 150, D("13"))
    assert r == D("100") * 3 + D("50") * 1  # 100 from the 10 lot, 50 from the 12 lot
    assert l.position == 50 and l.lots[0].price == D("12")
    r = l.apply(Side.SELL, 80, D("11"))  # closes 50 long (-50), opens 30 short @11
    assert r == D("-50") and l.position == -30
    assert l.unrealized_pnl(D("10")) == D("30")  # short gains when price falls
    l.apply(Side.BUY, 30, D("9"))
    assert l.position == 0 and l.realized_pnl == D("350") - D("50") + D("60")
    identity(l, D("10"))


def test_ledger_rejects_bad_quantity() -> None:
    with pytest.raises(ValueError):
        PositionLedger().apply(Side.BUY, 0, D("1"))
