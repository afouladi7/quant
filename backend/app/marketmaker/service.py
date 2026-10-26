"""Market-maker simulator: quoting, synthetic customer flow, matching and accounting.

Per simulation tick (order matters, it is deterministic for a given seed):
  1. fair value takes a random-walk step (Gaussian, ``volatility`` per tick)
  2. expired synthetic limit orders are canceled
  3. the market maker re-quotes (cancel + replace its resting quote orders)
  4. synthetic customers send orders (Poisson arrivals)
  5. if the market maker traded, it re-quotes again for the new inventory
"""

from __future__ import annotations

import logging
import math
import random
from collections import deque
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.ids import IdGenerator
from app.core.money import dec, money, round_to_tick
from app.events.bus import EventBus
from app.marketmaker.config import MMConfig
from app.marketmaker.presets import PRESETS, Preset
from app.marketmaker.quoting import Quote, compute_quote
from app.markets.ledger import PositionLedger
from app.markets.models import Order, OrderType, Side, TimeInForce, Trade
from app.markets.venue import FeeSchedule, SubmitResult, Venue

log = logging.getLogger(__name__)

SYMBOL = "MARKETLAB-100"
MM = "mm"
CUSTOMER = "customer"
SYNTHETIC = "synthetic"
FAIR_Q = Decimal("0.0001")


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class MarketMakerService:
    name = "marketmaker"

    def __init__(
        self,
        bus: EventBus,
        ids: IdGenerator,
        tick_source: Callable[[], int],
        advance: Callable[[int], None],
        pause_sim: Callable[[], None],
        series_limit: int = 600,
    ) -> None:
        self._bus = bus
        self._ids = ids
        self._tick = tick_source
        self._advance = advance
        self._pause_sim = pause_sim
        self.config = MMConfig()
        self.rng = random.Random(0)
        self.series: deque[dict[str, Any]] = deque(maxlen=series_limit)
        self.preset: Preset | None = None
        self.preset_step = 0
        self._build()

    # ---- lifecycle --------------------------------------------------------
    def _build(self) -> None:
        cfg = self.config
        self.venue = Venue(
            "MM",
            SYMBOL,
            tick_size=cfg.tick_size,
            lot_size=cfg.lot_size,
            fees=FeeSchedule(per_unit=cfg.fee_per_share, money_places="0.0001"),
            bus=self._bus,
            ids=self._ids,
            tick_source=self._tick,
            module=self.name,
            max_order_qty=cfg.max_order_qty,
            quiet_owners=frozenset({MM}),
        )
        self.venue.on_fill(self._on_fill)
        self.ledger = PositionLedger.with_cash(cfg.initial_cash)
        self.fair = cfg.fair_value
        self.quote: Quote | None = None
        self._needs_requote = False
        self.series.clear()
        self._series_n = 0
        self._requote("initial quote")
        self._record()

    def on_reset(self, rng: random.Random) -> None:
        self.rng = rng
        self.preset = None
        self.preset_step = 0
        self._build()

    def reset_demo(self, rng: random.Random) -> None:
        """Restore default configuration and initial state."""
        self.config = MMConfig()
        self.on_reset(rng)
        self._bus.publish("marketmaker.reset", self.name, "Market-maker demo reset to its initial state.")

    def update_config(self, cfg: MMConfig) -> None:
        old = self.config
        self.config = cfg
        structural = any(
            getattr(old, f) != getattr(cfg, f) for f in ("tick_size", "lot_size", "fee_per_share", "max_order_qty", "initial_cash")
        )
        if structural:
            # Market structure changed: rebuild the venue and ledger from scratch.
            self._build()
            msg = "Market-maker configuration changed market structure; the book and ledger were rebuilt."
        else:
            if old.fair_value != cfg.fair_value:
                self.fair = cfg.fair_value
            self._requote("configuration changed")
            msg = "Market-maker configuration updated; quotes recalculated."
        self._bus.publish("marketmaker.config_changed", self.name, msg, data={"config": cfg.model_dump(mode="json")})

    # ---- simulation tick ----------------------------------------------------
    def on_tick(self, tick: int, sim_time: datetime) -> None:
        cfg = self.config
        if cfg.volatility > 0:
            step = dec(round(self.rng.gauss(0.0, float(cfg.volatility)), 4))
            self.fair = max(cfg.tick_size, (self.fair + step).quantize(FAIR_Q))
        self.venue.expire(tick)
        self._requote("market moved", only_if_changed=True)
        for _ in range(poisson(self.rng, float(cfg.arrival_rate))):
            self._synthetic_order(tick)
        self._settle()
        self._record()

    def _synthetic_order(self, tick: int) -> None:
        cfg = self.config
        side = Side.BUY if self.rng.random() < float(cfg.buy_probability) else Side.SELL
        is_limit = self.rng.random() < float(cfg.limit_order_fraction)
        mult = self.rng.choice((Decimal("0.5"), Decimal(1), Decimal(1), Decimal("1.5"), Decimal(2)))
        qty = int(Decimal(cfg.customer_order_size) * mult) // cfg.lot_size * cfg.lot_size or cfg.lot_size
        if is_limit:
            offset = self.rng.randint(0, 5) * cfg.tick_size
            raw = self.fair - offset if side is Side.BUY else self.fair + offset
            price = round_to_tick(raw, cfg.tick_size, "down" if side is Side.BUY else "up")
            self.venue.submit(
                owner=SYNTHETIC, side=side, type=OrderType.LIMIT, quantity=qty, limit_price=max(price, cfg.tick_size),
                expires_tick=tick + cfg.synthetic_limit_ttl_ticks,
            )
        else:
            self.venue.submit(owner=SYNTHETIC, side=side, type=OrderType.MARKET, quantity=qty, tif=TimeInForce(cfg.market_order_policy))
        self._settle()

    # ---- quoting --------------------------------------------------------------
    def _requote(self, reason: str, only_if_changed: bool = False) -> None:
        for _ in range(3):  # MM quotes may themselves trade against resting customer orders
            q = compute_quote(self.config, self.fair, self.ledger.position)
            prev = self.quote
            if only_if_changed and prev is not None and prev.bids == q.bids and prev.asks == q.asks:
                return
            self.venue.cancel_owner(MM)
            self._needs_requote = False
            for lv in q.bids:
                self.venue.submit(owner=MM, side=Side.BUY, type=OrderType.LIMIT, quantity=lv.size, limit_price=lv.price)
            for lv in q.asks:
                self.venue.submit(owner=MM, side=Side.SELL, type=OrderType.LIMIT, quantity=lv.size, limit_price=lv.price)
            self.quote = q
            if prev is None or prev.bid != q.bid or prev.ask != q.ask:
                self._bus.publish(
                    "quote.updated",
                    self.name,
                    self._quote_message(q, reason),
                    entity_id=SYMBOL,
                    data={k: (str(v) if isinstance(v, Decimal) else v) for k, v in q.as_dict().items() if k not in ("bids", "asks")},
                )
            if not self._needs_requote:
                return
            only_if_changed = False
            reason = "own quote traded"

    def _quote_message(self, q: Quote, reason: str) -> str:
        bid = f"${q.bid}" if q.bid is not None else "no bid"
        ask = f"${q.ask}" if q.ask is not None else "no offer"
        if q.inventory > 0:
            why = f"it is long {q.inventory:,} shares, so it shades prices down to encourage buyers"
        elif q.inventory < 0:
            why = f"it is short {-q.inventory:,} shares, so it shades prices up to encourage sellers"
        else:
            why = "its inventory is flat, so quotes are centred on fair value"
        return f"Quote {bid} / {ask} around fair value ${q.reference.quantize(Decimal('0.01'))} ({reason}); {why}."

    def _settle(self) -> None:
        if self._needs_requote:
            self._requote("inventory changed")

    # ---- fills / accounting ---------------------------------------------------
    def _on_fill(self, trade: Trade, taker: Order, maker: Order) -> None:
        if MM not in (taker.owner, maker.owner):
            return
        mm_is_taker = taker.owner == MM
        side = taker.side if mm_is_taker else maker.side
        fee = trade.taker_fee if mm_is_taker else trade.maker_fee
        counter = maker if mm_is_taker else taker
        before = self.ledger.position
        realized = self.ledger.apply(side, trade.quantity, trade.price, fee=fee, reference=self.fair)
        after = self.ledger.position
        self._needs_requote = True
        verb = "bought" if side is Side.BUY else "sold"
        direction = "rose" if after > before else "fell"
        hint = (
            "it will lower its quotes to attract buyers and discourage more selling to it"
            if after > 0
            else "it will raise its quotes to attract sellers and discourage more buying from it"
            if after < 0
            else "its quotes return to fair value"
        )
        corr = trade.correlation_id
        self._bus.publish(
            "inventory.changed",
            self.name,
            f"The market maker {verb} {trade.quantity:,} shares at ${trade.price} from a {counter.owner}. "
            f"Inventory {direction} from {before:,} to {after:,}; {hint}.",
            entity_id=trade.id,
            correlation_id=corr,
            data={"before": before, "after": after, "price": str(trade.price), "side": side.value, "fee": str(fee)},
        )
        snap = self.ledger.snapshot(self.fair)
        self._bus.publish(
            "pnl.updated",
            self.name,
            f"P&L updated: realized ${money(snap['realized_pnl'])}, unrealized ${money(snap['unrealized_pnl'])}, "
            f"fees ${money(snap['fees'])}, net ${money(snap['net_pnl'])}"
            + (f" (this trade realized ${money(realized)})." if realized else "."),
            entity_id=trade.id,
            correlation_id=corr,
            data={k: str(snap[k]) for k in ("realized_pnl", "unrealized_pnl", "fees", "net_pnl", "cash", "gross_spread_captured")},
        )

    def _record(self) -> None:
        q = self.quote
        self._series_n += 1
        self.series.append(
            {
                "n": self._series_n,
                "tick": self._tick(),
                "fair": self.fair,
                "bid": q.bid if q else None,
                "ask": q.ask if q else None,
                "inventory": self.ledger.position,
                "net_pnl": money(self.ledger.net_pnl(self.fair)),
            }
        )

    # ---- commands -----------------------------------------------------------
    def submit_customer_order(
        self, side: Side, type_: OrderType, quantity: int, limit_price: Decimal | None, tif: TimeInForce | None,
        client_order_id: str | None = None,
    ) -> tuple[SubmitResult, str]:
        if type_ is OrderType.MARKET and tif is None:
            tif = TimeInForce(self.config.market_order_policy)
        inv_before = self.ledger.position
        result = self.venue.submit(
            owner=CUSTOMER, side=side, type=type_, quantity=quantity, limit_price=limit_price, tif=tif,
            client_order_id=client_order_id,
        )
        self._settle()
        self._record()
        return result, self._explain(result, inv_before)

    def _explain(self, r: SubmitResult, inv_before: int) -> str:
        o = r.order
        if o.status.value == "rejected":
            return f"Your order was rejected: {o.reason}"
        parts = []
        if o.filled_qty:
            mm_qty = sum(t.quantity for t in r.trades if MM in (t.maker_owner, t.taker_owner))
            parts.append(
                f"Your {o.side.value} order executed {o.filled_qty:,} shares at an average ${o.avg_fill_price}"
                + (f", {mm_qty:,} of them against the market maker's quote" if mm_qty else "")
                + "."
            )
            inv = self.ledger.position
            if inv != inv_before:
                parts.append(
                    f"The market maker's inventory moved from {inv_before:,} to {inv:,}, so it re-quoted at "
                    f"${self.quote.bid if self.quote else '-'} / ${self.quote.ask if self.quote else '-'}."
                )
        if o.status.value in ("open", "partially_filled"):
            parts.append(f"{o.quantity - o.filled_qty:,} shares now rest in the book at ${o.limit_price} until matched or canceled.")
        elif o.status.value == "canceled":
            parts.append(o.reason or "")
        return " ".join(p for p in parts if p)

    def cancel_customer_order(self, order_id: str) -> Order:
        order = self.venue.orders.get(order_id)
        if order is not None and order.owner != CUSTOMER:
            from app.markets.venue import OrderError

            raise OrderError("not_cancelable", "Only your own (customer) orders can be canceled here.")
        o = self.venue.cancel(order_id)
        self._record()
        return o

    def shift_fair(self, amount: Decimal | None = None, value: Decimal | None = None) -> None:
        old = self.fair
        new = value if value is not None else self.fair + (amount or Decimal(0))
        self.fair = max(self.config.tick_size, new.quantize(FAIR_Q))
        self._bus.publish(
            "marketdata.fair_value_changed",
            self.name,
            f"Fair value moved from ${old.quantize(Decimal('0.01'))} to ${self.fair.quantize(Decimal('0.01'))}.",
            entity_id=SYMBOL,
            data={"old": str(old), "new": str(self.fair)},
        )
        self._requote("fair value changed")
        self._record()

    # ---- presets ------------------------------------------------------------
    def load_preset(self, preset_id: str) -> Preset:
        preset = PRESETS[preset_id]
        self._pause_sim()
        self.config = MMConfig(**preset.config)
        self.on_reset(random.Random(preset.seed))
        self.preset = preset
        self.preset_step = 0
        self._bus.publish("preset.loaded", self.name, f"Preset loaded: {preset.title}. {preset.summary}", entity_id=preset.id)
        return preset

    def step_preset(self) -> dict[str, Any]:
        if self.preset is None:
            raise LookupError("No preset is loaded.")
        if self.preset_step >= len(self.preset.steps):
            raise IndexError("All steps of this preset are complete. Reset or load it again.")
        step = self.preset.steps[self.preset_step]
        a = step.action
        result: dict[str, Any] = {}
        if a["type"] == "customer_order":
            r, explanation = self.submit_customer_order(Side(a["side"]), OrderType.MARKET, a["quantity"], None, None)
            result = {"order": r.order, "explanation": explanation}
        elif a["type"] == "shift_fair":
            self.shift_fair(amount=Decimal(a["amount"]))
        elif a["type"] == "advance":
            self._pause_sim()
            self._advance(int(a["ticks"]))
        self.preset_step += 1
        self._bus.publish(
            "preset.step", self.name, f"Step {self.preset_step}: {step.title}. {step.observe}", entity_id=self.preset.id,
            data={"step": self.preset_step},
        )
        return {"step": self.preset_step, "title": step.title, "observe": step.observe, **result}

    # ---- snapshot -------------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        cfg = self.config
        led = self.ledger.snapshot(self.fair)
        trades = list(self.venue.trades)[-40:]
        customer_orders = [o for o in self.venue.orders.values() if o.owner == CUSTOMER][-40:]
        requested = self.venue.stats["requested_qty"]
        return {
            "instrument": SYMBOL,
            "config": cfg,
            "fair_value": self.fair,
            "quote": self.quote.as_dict() if self.quote else None,
            "book": self.venue.depth(10),
            "ledger": {
                **led,
                "inventory_utilization": Decimal(led["position"]) / Decimal(cfg.max_inventory),
                "max_inventory": cfg.max_inventory,
            },
            "trades": [
                {**t.model_dump(), "mm_side": (t.aggressor_side if t.taker_owner == MM else t.aggressor_side.opposite) if MM in (t.taker_owner, t.maker_owner) else None}
                for t in reversed(trades)
            ],
            "customer_orders": list(reversed(customer_orders)),
            "series": list(self.series),
            "stats": {**self.venue.stats, "resting_orders": len(self.venue.book)},
            "preset": None
            if self.preset is None
            else {**self.preset.public(), "next_step": self.preset_step, "complete": self.preset_step >= len(self.preset.steps)},
            "requested_qty": requested,
        }
