"""Quote generation with a linear inventory-skew model (a teaching model, not an optimal strategy).

    utilization  u = clamp(inventory / max_inventory, -1, 1)
    skew           = -sensitivity × u × spread
    reservation    = reference + skew
    bid            = round_down(reservation - spread/2)   to the tick
    ask            = round_up  (reservation + spread/2)   to the tick

Long inventory (u > 0) moves both quotes DOWN: the ask becomes more attractive
(helping the market maker sell) and the bid less attractive (discouraging more
buying). Short inventory moves them UP. Additional levels sit
``level_step_ticks`` further away. Sizes are capped so that a complete fill of
every level could never push inventory beyond ``max_inventory``; at the limit
that side is not quoted at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import round_to_tick
from app.marketmaker.config import MMConfig


@dataclass
class QuoteLevel:
    price: Decimal
    size: int


@dataclass
class Quote:
    reference: Decimal
    inventory: int
    utilization: Decimal
    skew: Decimal
    reservation: Decimal
    bids: list[QuoteLevel] = field(default_factory=list)
    asks: list[QuoteLevel] = field(default_factory=list)

    @property
    def bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    def as_dict(self) -> dict:
        spread = (self.ask - self.bid) if self.bid is not None and self.ask is not None else None
        return {
            "reference": self.reference,
            "inventory": self.inventory,
            "utilization": self.utilization,
            "skew": self.skew,
            "reservation": self.reservation,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bids[0].size if self.bids else 0,
            "ask_size": self.asks[0].size if self.asks else 0,
            "spread": spread,
            "bids": [{"price": lv.price, "size": lv.size} for lv in self.bids],
            "asks": [{"price": lv.price, "size": lv.size} for lv in self.asks],
        }


def _sizes(capacity: int, cfg: MMConfig) -> list[int]:
    sizes = []
    for _ in range(cfg.quote_levels):
        s = min(cfg.quote_size, capacity)
        s -= s % cfg.lot_size
        if s <= 0:
            break
        sizes.append(s)
        capacity -= s
    return sizes


def compute_quote(cfg: MMConfig, reference: Decimal, inventory: int) -> Quote:
    tick = cfg.tick_size
    u = Decimal(inventory) / Decimal(cfg.max_inventory)
    u = max(Decimal(-1), min(Decimal(1), u))
    skew = -(cfg.inventory_sensitivity * u * cfg.spread)
    reservation = reference + skew
    half = cfg.spread / 2
    bid = round_to_tick(reservation - half, tick, "down")
    ask = round_to_tick(reservation + half, tick, "up")
    if ask <= bid:
        ask = bid + tick
    step = tick * cfg.level_step_ticks
    q = Quote(reference=reference, inventory=inventory, utilization=u, skew=skew, reservation=reservation)
    for i, size in enumerate(_sizes(cfg.max_inventory - inventory, cfg)):
        price = bid - step * i
        if price >= tick:
            q.bids.append(QuoteLevel(price, size))
    for i, size in enumerate(_sizes(cfg.max_inventory + inventory, cfg)):
        q.asks.append(QuoteLevel(ask + step * i, size))
    return q
