"""A trading venue: one instrument, one order book, its own fees, orders and trades.

The market-maker module owns one Venue; the FX module owns one Venue per
(book, currency pair), so books A, B and C never share state.

Execution rules (documented in docs/finance-guide.md):
- Limit orders never execute at a price worse than their limit.
- Matching is price-time priority.
- Market orders are IOC by default: they take what liquidity exists and the
  unfilled remainder is canceled. FOK executes fully or not at all.
- Limit GTC orders rest any remainder in the book; IOC/FOK limit orders do not.
- Self-trade prevention cancels the resting order of the same owner.
"""

from __future__ import annotations

import logging
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.clock import utc_now
from app.core.ids import IdGenerator
from app.core.money import ZERO, from_ticks, is_on_tick, money, to_ticks
from app.events.bus import EventBus
from app.markets.book import OrderBook, Resting
from app.markets.models import Order, OrderStatus, OrderType, Side, TimeInForce, Trade

log = logging.getLogger(__name__)

AVG_PRICE_Q = Decimal("0.00000001")

FillListener = Callable[[Trade, Order, Order], None]
CancelListener = Callable[[Order], None]


@dataclass
class FeeSchedule:
    """Fees charged per fill. ``bps`` is basis points of notional; ``per_unit`` per share/unit."""

    taker_bps: Decimal = ZERO
    maker_bps: Decimal = ZERO
    per_unit: Decimal = ZERO
    money_places: str = "0.0001"

    def fee(self, notional: Decimal, quantity: int, maker: bool) -> Decimal:
        bps = self.maker_bps if maker else self.taker_bps
        return money(notional * bps / Decimal(10_000) + self.per_unit * quantity, self.money_places)


@dataclass
class SubmitResult:
    order: Order
    trades: list[Trade] = field(default_factory=list)


class OrderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Venue:
    def __init__(
        self,
        name: str,
        instrument: str,
        *,
        tick_size: Decimal,
        lot_size: int,
        fees: FeeSchedule,
        bus: EventBus,
        ids: IdGenerator,
        tick_source: Callable[[], int],
        module: str,
        max_order_qty: int,
        max_resting_orders: int = 2000,
        order_history: int = 5000,
        trade_history: int = 2000,
        quiet_owners: frozenset[str] = frozenset({"lp", "mm"}),
    ) -> None:
        self.name = name
        self.instrument = instrument
        self.tick_size = tick_size
        self.lot_size = lot_size
        self.fees = fees
        self.max_order_qty = max_order_qty
        self.max_resting_orders = max_resting_orders
        self._bus = bus
        self._ids = ids
        self._tick = tick_source
        self._module = module
        self._quiet_owners = quiet_owners
        self._order_history = order_history
        self.book = OrderBook()
        self.orders: OrderedDict[str, Order] = OrderedDict()
        self.trades: deque[Trade] = deque(maxlen=trade_history)
        self._fill_listeners: list[FillListener] = []
        self._cancel_listeners: list[CancelListener] = []
        self.stats = {"orders": 0, "rejected": 0, "filled_qty": 0, "requested_qty": 0}

    # ---- listeners ------------------------------------------------------
    def on_fill(self, fn: FillListener) -> None:
        self._fill_listeners.append(fn)

    def on_cancel(self, fn: CancelListener) -> None:
        self._cancel_listeners.append(fn)

    # ---- helpers --------------------------------------------------------
    def price(self, ticks: int) -> Decimal:
        return from_ticks(ticks, self.tick_size)

    def best_bid(self) -> Decimal | None:
        b = self.book.best(Side.BUY)
        return None if b is None else self.price(b)

    def best_ask(self) -> Decimal | None:
        a = self.book.best(Side.SELL)
        return None if a is None else self.price(a)

    def _quiet(self, owner: str) -> bool:
        return owner in self._quiet_owners

    def _publish(self, order: Order, type_: str, message: str, data: dict | None = None) -> None:
        if self._quiet(order.owner):
            return
        self._bus.publish(
            type_,
            self._module,
            message,
            entity_id=order.id,
            correlation_id=order.correlation_id or order.id,
            data={"venue": self.name, "instrument": self.instrument, "status": order.status.value, **(data or {})},
        )

    def _remember(self, order: Order) -> None:
        self.orders[order.id] = order
        if len(self.orders) > self._order_history:
            for oid in list(self.orders):
                if len(self.orders) <= self._order_history:
                    break
                if self.orders[oid].status.terminal:
                    del self.orders[oid]

    def validate(self, side: Side, type_: OrderType, quantity: int, limit_price: Decimal | None) -> None:
        if quantity <= 0:
            raise OrderError("invalid_quantity", "Quantity must be positive.")
        if quantity % self.lot_size:
            raise OrderError("invalid_quantity", f"Quantity must be a multiple of the lot size {self.lot_size}.")
        if quantity > self.max_order_qty:
            raise OrderError("invalid_quantity", f"Quantity exceeds the maximum order size {self.max_order_qty}.")
        if type_ is OrderType.LIMIT:
            if limit_price is None:
                raise OrderError("invalid_price", "A limit order needs a limit price.")
            if limit_price <= 0:
                raise OrderError("invalid_price", "Limit price must be positive.")
            if not is_on_tick(limit_price, self.tick_size):
                raise OrderError("invalid_price", f"Limit price must be a multiple of the tick size {self.tick_size}.")
        elif limit_price is not None:
            raise OrderError("invalid_price", "A market order must not have a limit price.")

    # ---- order entry ----------------------------------------------------
    def submit(
        self,
        *,
        owner: str,
        side: Side,
        type: OrderType,
        quantity: int,
        limit_price: Decimal | None = None,
        tif: TimeInForce | None = None,
        parent_id: str | None = None,
        correlation_id: str | None = None,
        client_order_id: str | None = None,
        expires_tick: int | None = None,
    ) -> SubmitResult:
        now = utc_now()
        if tif is None:
            tif = TimeInForce.IOC if type is OrderType.MARKET else TimeInForce.GTC
        order = Order(
            id=self._ids.next("ORD"),
            venue=self.name,
            instrument=self.instrument,
            owner=owner,
            side=side,
            type=type,
            tif=tif,
            quantity=quantity,
            limit_price=limit_price,
            parent_id=parent_id,
            correlation_id=correlation_id,
            client_order_id=client_order_id,
            expires_tick=expires_tick,
            created_ts=now,
            updated_ts=now,
        )
        self.stats["orders"] += 1
        quiet = self._quiet(owner)
        if not quiet:
            self.stats["requested_qty"] += quantity
        desc = f"{side.value} {type.value} order for {quantity:,} {self.instrument}" + (
            f" with limit {limit_price}" if limit_price is not None else ""
        )
        self._publish(order, "order.received", f"{self.name} received a {desc}.", {"owner": owner, "tif": tif.value})

        try:
            self.validate(side, type, quantity, limit_price)
            if type is OrderType.MARKET and tif is TimeInForce.GTC:
                raise OrderError("invalid_tif", "Market orders cannot rest (use IOC or FOK).")
        except OrderError as exc:
            return self._reject(order, str(exc))

        limit_ticks = to_ticks(limit_price, self.tick_size) if limit_price is not None else None
        if tif is TimeInForce.FOK and self.book.available(side, limit_ticks, exclude_owner=owner) < quantity:
            return self._reject(order, "Fill-or-kill: not enough liquidity to fill the whole order at once.")
        if (
            tif is TimeInForce.GTC
            and len(self.book) >= self.max_resting_orders
            and self.book.available(side, limit_ticks, exclude_owner=owner) < quantity
        ):
            return self._reject(order, f"Venue resting-order limit ({self.max_resting_orders}) reached.")

        self._remember(order)
        result = self.book.match(side, quantity, limit_ticks, owner)
        for r in result.self_trade_canceled:
            self._cancel_resting(r.order_id, "Self-trade prevention: canceled because the same owner sent an opposite order.")

        trades: list[Trade] = []
        for m in result.fills:
            maker = self.orders[m.maker.order_id]
            trades.append(self._execute(order, maker, m.price, m.quantity))

        if order.filled_qty == order.quantity:
            order.status = OrderStatus.FILLED
        elif tif is TimeInForce.GTC:
            self.book.add(Resting(order.id, side, limit_ticks, order.quantity - order.filled_qty, owner))  # type: ignore[arg-type]
            order.status = OrderStatus.PARTIALLY_FILLED if order.filled_qty else OrderStatus.OPEN
            self._publish(
                order,
                "order.resting",
                f"{order.quantity - order.filled_qty:,} {self.instrument} rest in the {self.name} book at {limit_price} "
                "until the market reaches that price or the order is canceled.",
                {"price": str(limit_price), "remaining": order.quantity - order.filled_qty},
            )
        else:
            unfilled = order.quantity - order.filled_qty
            order.status = OrderStatus.CANCELED
            order.reason = (
                f"Only {order.filled_qty:,} of {order.quantity:,} could execute; the unfilled {unfilled:,} was canceled ({tif.value.upper()})."
                if order.filled_qty
                else f"No liquidity available{' within the limit' if limit_ticks is not None else ''}; order canceled ({tif.value.upper()})."
            )
            self._publish(order, "order.canceled", order.reason, {"unfilled": unfilled, "filled": order.filled_qty})
            for fn in self._cancel_listeners:
                fn(order)
        order.updated_ts = utc_now()
        if order.status is OrderStatus.FILLED:
            self._publish(
                order,
                "order.filled",
                f"Order fully filled: {order.filled_qty:,} at an average price of {order.avg_fill_price}.",
                {"avg_price": str(order.avg_fill_price), "filled": order.filled_qty},
            )
        return SubmitResult(order, trades)

    def _execute(self, taker: Order, maker: Order, price_ticks: int, qty: int) -> Trade:
        price = self.price(price_ticks)
        notional = price * qty
        taker_fee = self.fees.fee(notional, qty, maker=False)
        maker_fee = self.fees.fee(notional, qty, maker=True)
        trade = Trade(
            id=self._ids.next("TRD"),
            venue=self.name,
            instrument=self.instrument,
            price=price,
            quantity=qty,
            aggressor_side=taker.side,
            taker_order_id=taker.id,
            maker_order_id=maker.id,
            taker_owner=taker.owner,
            maker_owner=maker.owner,
            taker_fee=taker_fee,
            maker_fee=maker_fee,
            correlation_id=taker.correlation_id or taker.id,
            ts=utc_now(),
            tick=self._tick(),
        )
        self.trades.append(trade)
        for o, fee in ((taker, taker_fee), (maker, maker_fee)):
            o.filled_qty += qty
            o.notional_filled += notional
            o.fees += fee
            o.avg_fill_price = (o.notional_filled / o.filled_qty).quantize(AVG_PRICE_Q).normalize()
            o.updated_ts = trade.ts
        if not self._quiet(taker.owner):
            self.stats["filled_qty"] += qty
        if not self._quiet(maker.owner):
            self.stats["filled_qty"] += qty
        maker.status = OrderStatus.FILLED if maker.filled_qty == maker.quantity else OrderStatus.PARTIALLY_FILLED
        if not (self._quiet(taker.owner) and self._quiet(maker.owner)):
            self._bus.publish(
                "trade.executed",
                self._module,
                f"Trade on {self.name}: {qty:,} {self.instrument} at {price} "
                f"({taker.owner} {taker.side.value}s from {maker.owner}).",
                entity_id=trade.id,
                correlation_id=trade.correlation_id,
                data={
                    "venue": self.name,
                    "price": str(price),
                    "quantity": qty,
                    "taker_order_id": taker.id,
                    "maker_order_id": maker.id,
                    "taker_owner": taker.owner,
                    "maker_owner": maker.owner,
                    "taker_fee": str(taker_fee),
                    "maker_fee": str(maker_fee),
                },
            )
        if maker.status is OrderStatus.FILLED:
            self._publish(maker, "order.filled", f"Resting order {maker.id} fully filled.", {"filled": maker.filled_qty})
        for fn in self._fill_listeners:
            fn(trade, taker, maker)
        return trade

    def _reject(self, order: Order, reason: str) -> SubmitResult:
        order.status = OrderStatus.REJECTED
        order.reason = reason
        self.stats["rejected"] += 1
        self._remember(order)
        self._publish(order, "order.rejected", f"Order rejected: {reason}", {"reason": reason})
        return SubmitResult(order)

    def _cancel_resting(self, order_id: str, reason: str) -> Order:
        self.book.remove(order_id)
        order = self.orders[order_id]
        order.status = OrderStatus.CANCELED
        order.reason = reason
        order.updated_ts = utc_now()
        self._publish(order, "order.canceled", f"Order {order.id} canceled: {reason}", {"filled": order.filled_qty})
        for fn in self._cancel_listeners:
            fn(order)
        return order

    def cancel(self, order_id: str, reason: str = "Canceled by request.") -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderError("not_found", f"Unknown order {order_id}.")
        if order_id not in self.book:
            raise OrderError("not_cancelable", f"Order {order_id} is {order.status.value} and cannot be canceled.")
        return self._cancel_resting(order_id, reason)

    def cancel_owner(self, owner: str) -> int:
        ids = [oid for oid, o in self.orders.items() if o.owner == owner and oid in self.book]
        for oid in ids:
            self.book.remove(oid)
            o = self.orders[oid]
            o.status = OrderStatus.CANCELED
            o.reason = "Replaced by a new quote."
            if self._quiet(owner):
                del self.orders[oid]  # quote churn is not order history
        return len(ids)

    def expire(self, tick: int) -> None:
        for oid, o in list(self.orders.items()):
            if o.expires_tick is not None and o.expires_tick <= tick and oid in self.book:
                self._cancel_resting(oid, f"Expired after its time-to-live (tick {tick}).")

    # ---- snapshots ------------------------------------------------------
    def depth(self, levels: int = 10) -> dict:
        def side(s: Side) -> list[dict]:
            out = []
            for price, resting in self.book.level_detail(s, levels):
                by_owner: dict[str, int] = {}
                for r in resting:
                    by_owner[r.owner] = by_owner.get(r.owner, 0) + r.remaining
                out.append(
                    {
                        "price": self.price(price),
                        "quantity": sum(by_owner.values()),
                        "orders": len(resting),
                        "by_owner": by_owner,
                        "order_ids": [r.order_id for r in resting if not self._quiet(r.owner)],
                    }
                )
            return out

        bid, ask = self.best_bid(), self.best_ask()
        return {
            "venue": self.name,
            "instrument": self.instrument,
            "best_bid": bid,
            "best_ask": ask,
            "spread": (ask - bid) if bid is not None and ask is not None else None,
            "bids": side(Side.BUY),
            "asks": side(Side.SELL),
        }

    def reset(self) -> None:
        self.book = OrderBook()
        self.orders.clear()
        self.trades.clear()
        self.stats = {"orders": 0, "rejected": 0, "filled_qty": 0, "requested_qty": 0}
