"""Price-time priority limit order book on integer tick prices.

Bids: highest price first; asks: lowest price first; within a price level,
earliest arrival first (FIFO queue). The book itself knows nothing about
fees, events or accounting; :class:`app.markets.venue.Venue` adds those.
"""

from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass, field

from app.markets.models import Side


@dataclass
class Resting:
    order_id: str
    side: Side
    price: int  # ticks
    remaining: int
    owner: str
    seq: int = 0


@dataclass
class Match:
    maker: Resting
    price: int
    quantity: int


@dataclass
class MatchResult:
    fills: list[Match] = field(default_factory=list)
    self_trade_canceled: list[Resting] = field(default_factory=list)

    @property
    def filled(self) -> int:
        return sum(m.quantity for m in self.fills)


class OrderBook:
    def __init__(self) -> None:
        self._levels: dict[Side, dict[int, deque[Resting]]] = {Side.BUY: {}, Side.SELL: {}}
        self._prices: dict[Side, list[int]] = {Side.BUY: [], Side.SELL: []}  # ascending
        self._index: dict[str, Resting] = {}
        self._seq = 0

    # ---- queries --------------------------------------------------------
    def __len__(self) -> int:
        return len(self._index)

    def __contains__(self, order_id: str) -> bool:
        return order_id in self._index

    def best(self, side: Side) -> int | None:
        prices = self._prices[side]
        if not prices:
            return None
        return prices[-1] if side is Side.BUY else prices[0]

    def _ordered_prices(self, side: Side) -> list[int]:
        prices = self._prices[side]
        return list(reversed(prices)) if side is Side.BUY else list(prices)

    def levels(self, side: Side, depth: int = 10) -> list[tuple[int, int, int]]:
        """Aggregated levels best-first: (price_ticks, total_qty, order_count)."""
        out = []
        for p in self._ordered_prices(side)[:depth]:
            q = self._levels[side][p]
            out.append((p, sum(r.remaining for r in q), len(q)))
        return out

    def level_detail(self, side: Side, depth: int = 10) -> list[tuple[int, list[Resting]]]:
        return [(p, list(self._levels[side][p])) for p in self._ordered_prices(side)[:depth]]

    def resting(self, order_id: str) -> Resting | None:
        return self._index.get(order_id)

    @staticmethod
    def _crosses(taker_side: Side, limit: int | None, maker_price: int) -> bool:
        if limit is None:
            return True
        return maker_price <= limit if taker_side is Side.BUY else maker_price >= limit

    def available(self, taker_side: Side, limit: int | None = None, exclude_owner: str | None = None) -> int:
        """Quantity a taker could execute right now without exceeding ``limit``."""
        total = 0
        maker_side = taker_side.opposite
        for p in self._ordered_prices(maker_side):
            if not self._crosses(taker_side, limit, p):
                break
            total += sum(r.remaining for r in self._levels[maker_side][p] if r.owner != exclude_owner)
        return total

    # ---- mutations ------------------------------------------------------
    def add(self, r: Resting) -> None:
        if r.remaining <= 0:
            raise ValueError("resting quantity must be positive")
        if r.order_id in self._index:
            raise ValueError(f"duplicate order id {r.order_id}")
        self._seq += 1
        r.seq = self._seq
        levels = self._levels[r.side]
        if r.price not in levels:
            levels[r.price] = deque()
            bisect.insort(self._prices[r.side], r.price)
        levels[r.price].append(r)
        self._index[r.order_id] = r

    def remove(self, order_id: str) -> Resting | None:
        r = self._index.pop(order_id, None)
        if r is None:
            return None
        q = self._levels[r.side][r.price]
        q.remove(r)
        if not q:
            self._drop_level(r.side, r.price)
        return r

    def _drop_level(self, side: Side, price: int) -> None:
        del self._levels[side][price]
        prices = self._prices[side]
        prices.pop(bisect.bisect_left(prices, price))

    def match(self, taker_side: Side, quantity: int, limit: int | None, taker_owner: str) -> MatchResult:
        """Consume resting liquidity in price-time priority.

        Self-trade prevention: a resting order with the same owner as the taker
        is canceled (removed) instead of being traded against.
        """
        result = MatchResult()
        maker_side = taker_side.opposite
        remaining = quantity
        while remaining > 0:
            price = self.best(maker_side)
            if price is None or not self._crosses(taker_side, limit, price):
                break
            queue = self._levels[maker_side][price]
            while queue and remaining > 0:
                maker = queue[0]
                if maker.owner == taker_owner:
                    queue.popleft()
                    del self._index[maker.order_id]
                    result.self_trade_canceled.append(maker)
                    continue
                qty = min(remaining, maker.remaining)
                maker.remaining -= qty
                remaining -= qty
                result.fills.append(Match(maker=maker, price=price, quantity=qty))
                if maker.remaining == 0:
                    queue.popleft()
                    del self._index[maker.order_id]
            if not queue:
                self._drop_level(maker_side, price)
        return result
