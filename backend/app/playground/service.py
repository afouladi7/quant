"""Order Book Playground: a small sandbox book for learning how matching works.

It reuses the real matching engine (app.markets.venue.Venue), so every result is
what the engine actually did. Around it, this module builds a numbered,
plain-English explanation of each step: why an order traded with a particular
resting order, at what price, how much, and why it stopped.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from app.core.ids import IdGenerator
from app.events.bus import EventBus
from app.markets.models import Order, OrderType, Side, TimeInForce
from app.markets.venue import FeeSchedule, OrderError, Venue

TRADERS = ("you", "alice", "bob", "carol")
INSTRUMENT = "TOY"
TICK = Decimal("1")


def _px(p: Decimal) -> str:
    return f"${p.normalize():f}" if p == p.to_integral_value() else f"${p}"


class Playground:
    def __init__(self, bus: EventBus, ids: IdGenerator) -> None:
        self._bus = bus
        self._ids = ids
        self.reset(seed=True)

    # ---- setup ------------------------------------------------------------
    def reset(self, seed: bool = True) -> None:
        self.venue = Venue(
            "Playground", INSTRUMENT, tick_size=TICK, lot_size=1, fees=FeeSchedule(), bus=self._bus, ids=self._ids,
            tick_source=lambda: 0, module="playground", max_order_qty=1000, max_resting_orders=200, quiet_owners=frozenset(),
        )
        self.labels: dict[str, str] = {}
        self._n = 0
        self.history: deque[dict[str, Any]] = deque(maxlen=50)
        if seed:
            # A small, readable starting book: two sellers at $101 (Alice first, then Bob),
            # one at $103, and two buyers below the market.
            for trader, side, qty, price in (
                ("alice", Side.SELL, 5, 101), ("bob", Side.SELL, 3, 101), ("carol", Side.SELL, 10, 103),
                ("bob", Side.BUY, 4, 99), ("alice", Side.BUY, 6, 98),
            ):
                self.place(trader, side, OrderType.LIMIT, qty, Decimal(price), explain=False)

    def _label(self, order_id: str) -> str:
        if order_id not in self.labels:
            self._n += 1
            self.labels[order_id] = f"#{self._n}"
        return self.labels[order_id]

    # ---- snapshot -----------------------------------------------------------
    def _queue(self, side: Side) -> list[tuple[Decimal, list[dict[str, Any]]]]:
        out = []
        for price_ticks, resting in self.venue.book.level_detail(side, depth=100):
            out.append((self.venue.price(price_ticks), [
                {"id": r.order_id, "label": self._label(r.order_id), "trader": r.owner, "remaining": r.remaining} for r in resting
            ]))
        return out

    def snapshot(self) -> dict[str, Any]:
        def side(s: Side) -> list[dict[str, Any]]:
            return [{"price": p, "total": sum(o["remaining"] for o in orders), "orders": orders} for p, orders in self._queue(s)]

        bid, ask = self.venue.best_bid(), self.venue.best_ask()
        return {
            "instrument": INSTRUMENT,
            "tick_size": TICK,
            "traders": TRADERS,
            "best_bid": bid,
            "best_ask": ask,
            "spread": (ask - bid) if bid is not None and ask is not None else None,
            "bids": side(Side.BUY),
            "asks": side(Side.SELL),
            "trades": [
                {"id": t.id, "price": t.price, "quantity": t.quantity, "buyer": t.taker_owner if t.aggressor_side is Side.BUY else t.maker_owner,
                 "seller": t.maker_owner if t.aggressor_side is Side.BUY else t.taker_owner, "aggressor": t.aggressor_side,
                 "taker_label": self._label(t.taker_order_id), "maker_label": self._label(t.maker_order_id)}
                for t in reversed(self.venue.trades)
            ][:30],
            "history": list(reversed(self.history)),
        }

    # ---- commands -----------------------------------------------------------
    def place(self, trader: str, side: Side, type_: OrderType, quantity: int, price: Decimal | None,
              explain: bool = True) -> dict[str, Any]:
        if trader not in TRADERS:
            raise OrderError("invalid_trader", f"Trader must be one of {', '.join(TRADERS)}.")
        opposite = side.opposite
        before = self._queue(opposite)
        result = self.venue.submit(owner=trader, side=side, type=type_, quantity=quantity, limit_price=price,
                                   tif=TimeInForce.IOC if type_ is OrderType.MARKET else TimeInForce.GTC)
        order = result.order
        label = self._label(order.id)
        steps = self._explain(trader, side, type_, quantity, price, order, result.trades, before) if explain else []
        record = {"label": label, "trader": trader, "side": side, "type": type_, "quantity": quantity, "price": price,
                  "status": order.status, "filled": order.filled_qty, "steps": steps}
        if explain:
            self.history.append(record)
        return {"order": order, "label": label, "steps": steps, "trades": result.trades}

    def cancel(self, order_id: str) -> Order:
        return self.venue.cancel(order_id, "Canceled from the playground.")

    # ---- explanation ----------------------------------------------------------
    def _explain(self, trader: str, side: Side, type_: OrderType, quantity: int, price: Decimal | None, order: Order,
                 trades: list, before: list[tuple[Decimal, list[dict[str, Any]]]]) -> list[str]:
        who = "You" if trader == "you" else trader.capitalize()
        verb = "buy" if side is Side.BUY else "sell"
        other = "sellers" if side is Side.BUY else "buyers"
        best_word = "lowest asking price" if side is Side.BUY else "highest bid"
        kind = "a market order (take whatever is available now)" if type_ is OrderType.MARKET else \
            f"a limit order (never {'pay more' if side is Side.BUY else 'accept less'} than {_px(price)})"  # type: ignore[arg-type]
        steps = [f"{who} sent {kind} to {verb} {quantity} {INSTRUMENT}. It is labelled {self._label(order.id)}."]
        if order.status.value == "rejected":
            steps.append(f"The engine rejected it before matching: {order.reason}")
            return steps

        if not before:
            steps.append(f"There were no {other} in the book at all, so nothing could trade.")
        else:
            steps.append(f"The engine looks at the {other} best-first. The {best_word} was {_px(before[0][0])}.")

        remaining = quantity
        by_maker = {t.maker_order_id: t for t in trades}  # each resting order trades at most once per incoming order
        stp = set()
        for _, os in before:
            for o in os:
                ro = self.venue.orders.get(o["id"])
                if o["trader"] == trader and ro is not None and "Self-trade" in (ro.reason or ""):
                    stp.add(o["id"])
        filled_ids = set(by_maker) | stp
        for level_price, orders in before:
            if remaining == 0 or not any(o["id"] in filled_ids for o in orders):
                break  # the engine never reached this price level
            if len(orders) > 1:
                queue_desc = ", ".join(f"{o['label']} ({o['trader']}, {o['remaining']})" for o in orders)
                steps.append(f"At {_px(level_price)} several orders were waiting, in arrival order: {queue_desc}. "
                             "Same price means first come, first served (price-time priority).")
            for o in orders:
                if o["id"] in stp:
                    owner = "yours" if trader == "you" else f"{trader.capitalize()}'s"
                    steps.append(f"{o['label']} at {_px(level_price)} was also {owner}. Nobody may trade with themselves "
                                 "(self-trade prevention), so that resting order was canceled and the engine moved on.")
                elif o["id"] in by_maker:
                    t = by_maker[o["id"]]
                    steps.append(f"Matched with {o['label']} from {o['trader'].capitalize()} at {_px(t.price)}: {t.quantity} traded "
                                 f"(the smaller of the {remaining} still wanted and the {o['remaining']} offered). "
                                 "The price is the resting order's price, not the newcomer's.")
                    remaining -= t.quantity
        if order.filled_qty:
            avg = order.avg_fill_price
            steps.append(f"In total {order.filled_qty} of {quantity} traded at an average price of {_px(avg)}." if avg else "")
        if remaining > 0:
            nxt = next((p for p, os in before if not all(o["id"] in filled_ids for o in os)), None)
            if type_ is OrderType.LIMIT and nxt is not None and (
                (side is Side.BUY and nxt > price) or (side is Side.SELL and nxt < price)  # type: ignore[operator]
            ):
                steps.append(f"It stopped because the next price available, {_px(nxt)}, is worse than the limit {_px(price)}.")  # type: ignore[arg-type]
            elif order.filled_qty:
                steps.append(f"It stopped because there were no more {other} left.")
            if order.status.value in ("open", "partially_filled"):
                ahead = sum(1 for p, os in self._queue(side) if p == price for o in os if o["id"] != order.id)
                steps.append(f"The remaining {remaining} now rests in the book as a {'bid' if side is Side.BUY else 'ask'} at {_px(price)}"  # type: ignore[arg-type]
                             + (f", behind {ahead} earlier order(s) at that price." if ahead else ", first in line at that price.")
                             + " It will trade when someone arrives willing to meet that price.")
            else:
                steps.append(f"Because it was a market order, the unfilled {remaining} was canceled rather than left waiting.")
        elif order.filled_qty == quantity:
            steps.append("The order is completely filled.")
        return [s for s in steps if s]
