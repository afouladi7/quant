"""FX module: synthetic rates, three independent books (A, B, C) and order routing.

Each book holds one :class:`Venue` per currency pair, so the books never share
orders, liquidity, fees or trade history. Liquidity in each book comes from a
hypothetical liquidity provider ("lp") that re-quotes around the market mid on
every tick (and whenever the mid is changed). The simulated hedge fund ("fund")
is the only other participant; its fills are forwarded to the portfolio.
"""

from __future__ import annotations

import random
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.clock import utc_now
from app.core.ids import IdGenerator
from app.core.money import dec, money, round_to_tick
from app.events.bus import EventBus
from app.fx.config import DEFAULT_BOOKS, PAIRS, BookConfig, PairSpec, RoutingWeights
from app.fx.router import BookDepth, RoutingPlan, plan_route
from app.markets.models import Order, OrderStatus, OrderType, Side, TimeInForce, Trade
from app.markets.venue import FeeSchedule, Venue

FUND = "fund"
LP = "lp"
AVG_Q = Decimal("0.0000001")

FundFillListener = Callable[[Trade, Order, "ParentOrder"], None]


class ChildInfo(BaseModel):
    order_id: str
    book: str
    quantity: int
    limit_price: Decimal | None
    tif: str
    status: str
    filled_qty: int = 0
    avg_price: Decimal | None = None
    fees: Decimal = Decimal(0)
    sim_latency_ms: int
    sent_ts: datetime
    sim_arrival_ts: datetime
    reason: str | None = None


class ParentOrder(BaseModel):
    id: str
    pair: str
    side: Side
    type: OrderType
    quantity: int
    limit_price: Decimal | None
    routing_mode: str
    purpose: str = "trade"
    hedge_id: str | None = None
    status: str = "open"
    filled_qty: int = 0
    notional: Decimal = Decimal(0)
    vwap: Decimal | None = None
    total_fees: Decimal = Decimal(0)
    unfilled_qty: int = 0
    resting_qty: int = 0
    children: list[ChildInfo] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    created_ts: datetime
    updated_ts: datetime


def plan_to_dict(plan: RoutingPlan) -> dict[str, Any]:
    return {
        "mode": plan.mode,
        "side": plan.side.value,
        "quantity": plan.quantity,
        "limit_price": plan.limit_price,
        "include_fees": plan.include_fees,
        "latency_penalty_bps_per_100ms": plan.latency_penalty_bps_per_100ms,
        "planned_qty": plan.planned_qty,
        "expected_vwap": None if plan.expected_vwap is None else plan.expected_vwap.quantize(AVG_Q),
        "unfilled_qty": plan.unfilled_qty,
        "explanation": plan.explanation,
        "allocations": [
            {"book": a.book, "quantity": a.quantity, "worst_price": a.worst_price, "levels": [{"price": p, "quantity": q} for p, q in a.levels]}
            for a in plan.allocations
        ],
        "candidates": [
            {
                "book": c.book, "price": c.price, "available": c.available, "fee_bps": c.fee_bps, "latency_ms": c.latency_ms,
                "effective_price": c.effective_price.quantize(Decimal("0.000000001")), "rank": c.rank,
                "allocated": c.allocated, "eligible": c.eligible, "note": c.note,
            }
            for c in plan.candidates
        ],
    }


class Book:
    def __init__(self, cfg: BookConfig, bus: EventBus, ids: IdGenerator, tick_source: Callable[[], int]) -> None:
        self.config = cfg
        self.venues: dict[str, Venue] = {}
        for sym, spec in PAIRS.items():
            v = Venue(
                f"Book {cfg.name}", sym, tick_size=spec.tick_size, lot_size=spec.lot_size,
                fees=FeeSchedule(taker_bps=cfg.fee_bps, money_places="0.01"), bus=bus, ids=ids,
                tick_source=tick_source, module="fx", max_order_qty=100_000_000, quiet_owners=frozenset({LP}),
            )
            self.venues[sym] = v

    def refresh_liquidity(self, spec: PairSpec, mid: Decimal) -> None:
        cfg = self.config
        v = self.venues[spec.symbol]
        v.cancel_owner(LP)
        center = mid + cfg.price_offset_pips * spec.pip
        half = cfg.spread_pips * spec.pip / 2
        bid = round_to_tick(center - half, spec.tick_size, "down")
        ask = round_to_tick(center + half, spec.tick_size, "up")
        if ask <= bid:
            ask = bid + spec.tick_size
        step = round_to_tick(cfg.level_step_pips * spec.pip, spec.tick_size, "up")
        for i in range(cfg.levels):
            v.submit(owner=LP, side=Side.SELL, type=OrderType.LIMIT, quantity=cfg.qty_per_level, limit_price=ask + step * i)
            px = bid - step * i
            if px > 0:
                v.submit(owner=LP, side=Side.BUY, type=OrderType.LIMIT, quantity=cfg.qty_per_level, limit_price=px)

    def set_config(self, cfg: BookConfig) -> None:
        self.config = cfg
        for v in self.venues.values():
            v.fees = FeeSchedule(taker_bps=cfg.fee_bps, money_places="0.01")

    def reset(self) -> None:
        for v in self.venues.values():
            v.reset()


class FXService:
    name = "fx"

    def __init__(self, bus: EventBus, ids: IdGenerator, tick_source: Callable[[], int], pause_sim: Callable[[], None]) -> None:
        self._bus = bus
        self._ids = ids
        self._tick = tick_source
        self._pause_sim = pause_sim
        self.rng = random.Random(0)
        self.weights = RoutingWeights()
        self.mids: dict[str, Decimal] = {s: p.initial_mid for s, p in PAIRS.items()}
        self.books: dict[str, Book] = {n: Book(c.model_copy(), bus, ids, tick_source) for n, c in DEFAULT_BOOKS.items()}
        self.parents: OrderedDict[str, ParentOrder] = OrderedDict()
        self._child_parent: dict[str, str] = {}
        self.fund_fill_listeners: list[FundFillListener] = []
        self.reset_listeners: list[Callable[[], None]] = []
        self.parent_listeners: list[Callable[[ParentOrder], None]] = []
        self.scenario: dict[str, Any] | None = None
        self.scenario_step = 0
        self.rate_series: dict[str, list[dict[str, Any]]] = {s: [] for s in PAIRS}
        for b in self.books.values():
            for v in b.venues.values():
                v.on_fill(self._on_fill)
                v.on_cancel(self._on_cancel)
        for sym in PAIRS:
            self._record_rate(sym)
        self.refresh_all()

    # ---- lifecycle --------------------------------------------------------
    def on_reset(self, rng: random.Random) -> None:
        self.rng = rng
        self.mids = {s: p.initial_mid for s, p in PAIRS.items()}
        self.parents.clear()
        self._child_parent.clear()
        self.scenario = None
        self.scenario_step = 0
        for b in self.books.values():
            b.reset()
        self.rate_series = {s: [] for s in PAIRS}
        for sym in PAIRS:
            self._record_rate(sym)
        self.refresh_all()
        for fn in self.reset_listeners:
            fn()

    def restore_defaults(self, rng: random.Random) -> None:
        for n, c in DEFAULT_BOOKS.items():
            self.books[n].set_config(c.model_copy())
        self.weights = RoutingWeights()
        self.on_reset(rng)

    def on_tick(self, tick: int, sim_time: datetime) -> None:
        for sym, spec in PAIRS.items():
            move = dec(round(self.rng.gauss(0.0, float(spec.volatility_pips)), 2)) * spec.pip
            self.mids[sym] = round_to_tick(self.mids[sym] + move, spec.tick_size)
            self._record_rate(sym)
        self.refresh_all()

    def _record_rate(self, sym: str) -> None:
        series = self.rate_series[sym]
        series.append({"tick": self._tick(), "mid": self.mids[sym]})
        if len(series) > 600:
            del series[: len(series) - 600]

    def refresh_all(self, pair: str | None = None) -> None:
        for sym, spec in PAIRS.items():
            if pair is None or sym == pair:
                for b in self.books.values():
                    b.refresh_liquidity(spec, self.mids[sym])

    def set_mid(self, pair: str, mid: Decimal, reason: str = "set by user") -> Decimal:
        spec = PAIRS[pair]
        old = self.mids[pair]
        new = round_to_tick(mid, spec.tick_size)
        if new <= 0:
            raise ValueError("rate must be positive")
        self.mids[pair] = new
        self._record_rate(pair)
        pct = (new - old) / old * 100
        self._bus.publish(
            "marketdata.rate_changed", "fx",
            f"{pair} moved from {old} to {new} ({pct:+.2f}%, {reason}). Books re-quote around the new rate.",
            entity_id=pair, data={"old": str(old), "new": str(new), "pct": str(pct.quantize(Decimal('0.0001')))},
        )
        self.refresh_all(pair)
        return new

    def set_book_config(self, cfg: BookConfig) -> None:
        self.books[cfg.name].set_config(cfg)
        self.refresh_all()
        self._bus.publish("fx.book_config_changed", "fx", f"Book {cfg.name} configuration updated (hypothetical).",
                          entity_id=f"Book {cfg.name}", data=cfg.model_dump(mode="json"))

    # ---- routing ------------------------------------------------------------
    def depths(self, pair: str, side: Side) -> list[BookDepth]:
        out = []
        maker = side.opposite
        for name, b in self.books.items():
            v = b.venues[pair]
            levels = [(v.price(p), q) for p, q, _ in v.book.levels(maker, depth=50)]
            out.append(BookDepth(name, b.config.fee_bps, b.config.latency_ms, levels))
        return out

    def preview(self, pair: str, side: Side, qty: int, limit: Decimal | None, mode: str, weights: RoutingWeights | None = None) -> RoutingPlan:
        w = weights or self.weights
        return plan_route(side, qty, limit, self.depths(pair, side), mode, w.include_fees, w.latency_penalty_bps_per_100ms)

    def submit_parent(
        self, pair: str, side: Side, type_: OrderType, quantity: int, limit_price: Decimal | None, mode: str,
        weights: RoutingWeights | None = None, purpose: str = "trade", hedge_id: str | None = None,
    ) -> ParentOrder:
        if pair not in PAIRS:
            raise ValueError(f"unknown pair {pair}")
        spec = PAIRS[pair]
        if mode not in ("A", "B", "C", "smart"):
            raise ValueError("routing mode must be A, B, C or smart")
        if quantity <= 0 or quantity % spec.lot_size:
            raise ValueError(f"quantity must be a positive multiple of {spec.lot_size:,}")
        if type_ is OrderType.LIMIT:
            if limit_price is None or limit_price <= 0 or (limit_price % spec.tick_size) != 0:
                raise ValueError(f"limit orders need a positive limit price on the {spec.tick_size} tick")
        elif limit_price is not None:
            raise ValueError("market orders must not have a limit price")
        w = weights or self.weights
        now = utc_now()
        parent = ParentOrder(
            id=self._ids.next("PAR"), pair=pair, side=side, type=type_, quantity=quantity, limit_price=limit_price,
            routing_mode=mode, purpose=purpose, hedge_id=hedge_id, created_ts=now, updated_ts=now,
        )
        self.parents[parent.id] = parent
        while len(self.parents) > 1000:
            self.parents.popitem(last=False)
        plan = self.preview(pair, side, quantity, limit_price, mode, w)
        parent.plan = plan_to_dict(plan)
        self._bus.publish(
            "order.received", "fx",
            f"Fund {purpose} order received: {side.value} {quantity:,} {spec.base} ({pair}, {type_.value}"
            f"{' limit ' + str(limit_price) if limit_price is not None else ''}), routing: {'smart' if mode == 'smart' else 'Book ' + mode}.",
            entity_id=parent.id, correlation_id=parent.id, data={"owner": FUND, "pair": pair, "mode": mode, "purpose": purpose},
        )
        self._bus.publish(
            "order.routed", "fx", plan.explanation, entity_id=parent.id, correlation_id=parent.id,
            data={"allocations": [{"book": a.book, "quantity": a.quantity, "worst_price": str(a.worst_price)} for a in plan.allocations],
                  "expected_vwap": str(plan.expected_vwap) if plan.expected_vwap else None},
        )

        # 1. Immediate children per the plan (IOC at the worst planned price, which also respects the limit).
        for a in plan.allocations:
            self._send_child(parent, a.book, a.quantity, a.worst_price, TimeInForce.IOC)
        # 2. A limit order's remainder rests on one book at the limit price.
        remaining = quantity - parent.filled_qty
        if type_ is OrderType.LIMIT and remaining > 0:
            rest_book = mode if mode != "smart" else self._rest_book(plan, side)
            self._send_child(parent, rest_book, remaining, limit_price, TimeInForce.GTC)  # type: ignore[arg-type]
            parent.explanation = (
                f"{remaining:,} could not trade at {limit_price} or better right now, so it rests on Book {rest_book} "
                f"as a limit order and will fill only if that book's price reaches the limit."
            )
        self._reconcile(parent)
        filled_part = (
            f"Filled {parent.filled_qty:,} of {quantity:,} at a weighted-average {parent.vwap} with fees {parent.total_fees} {spec.quote}."
            if parent.filled_qty else f"Nothing filled yet."
        )
        unfilled_part = (
            f" {parent.unfilled_qty:,} unfilled and canceled: there was not enough liquidity"
            f"{' within the limit' if limit_price is not None else ''} on the eligible book(s)." if parent.unfilled_qty and not parent.resting_qty else ""
        )
        parent.explanation = " ".join(x for x in (plan.explanation, filled_part + unfilled_part, parent.explanation) if x)
        for fn in self.parent_listeners:
            fn(parent)
        return parent

    def _rest_book(self, plan: RoutingPlan, side: Side) -> str:
        best: dict[str, Decimal] = {}
        for c in plan.candidates:
            best.setdefault(c.book, c.effective_price)
        if not best:
            return "B"
        return sorted(best, key=lambda b: (best[b] if side is Side.BUY else -best[b], self.books[b].config.latency_ms))[0]

    def _send_child(self, parent: ParentOrder, book: str, qty: int, limit: Decimal, tif: TimeInForce) -> None:
        cfg = self.books[book].config
        sent = utc_now()
        from datetime import timedelta

        info = ChildInfo(
            order_id="pending", book=book, quantity=qty, limit_price=limit, tif=tif.value, status="open",
            sim_latency_ms=cfg.latency_ms, sent_ts=sent, sim_arrival_ts=sent + timedelta(milliseconds=cfg.latency_ms),
        )
        parent.children.append(info)
        venue = self.books[book].venues[parent.pair]
        res = venue.submit(
            owner=FUND, side=parent.side, type=OrderType.LIMIT, quantity=qty, limit_price=limit, tif=tif,
            parent_id=parent.id, correlation_id=parent.id,
        )
        info.order_id = res.order.id
        self._child_parent[res.order.id] = parent.id
        self._sync_child(info, res.order)
        self._bus.publish(
            "order.child_sent", "fx",
            f"Child order {res.order.id} → Book {book}: {parent.side.value} {qty:,} limit {limit} {tif.value.upper()} "
            f"(simulated latency {cfg.latency_ms} ms) — {res.order.status.value.replace('_', ' ')}, filled {res.order.filled_qty:,}.",
            entity_id=res.order.id, correlation_id=parent.id,
            data={"book": book, "parent_id": parent.id, "status": res.order.status.value, "filled": res.order.filled_qty, "latency_ms": cfg.latency_ms},
        )

    @staticmethod
    def _sync_child(info: ChildInfo, o: Order) -> None:
        info.status = o.status.value
        info.filled_qty = o.filled_qty
        info.avg_price = o.avg_fill_price
        info.fees = o.fees
        info.reason = o.reason

    def _reconcile(self, parent: ParentOrder) -> None:
        orders = {}
        for c in parent.children:
            v = self.books[c.book].venues[parent.pair]
            o = v.orders.get(c.order_id)
            if o is not None:
                orders[c.order_id] = o
                self._sync_child(c, o)
        parent.filled_qty = sum(c.filled_qty for c in parent.children)
        parent.notional = sum((o.notional_filled for o in orders.values()), Decimal(0))
        parent.total_fees = sum((c.fees for c in parent.children), Decimal(0))
        parent.vwap = (parent.notional / parent.filled_qty).quantize(AVG_Q) if parent.filled_qty else None
        parent.resting_qty = sum(c.quantity - c.filled_qty for c in parent.children if c.status in ("open", "partially_filled"))
        parent.unfilled_qty = parent.quantity - parent.filled_qty
        if parent.filled_qty == parent.quantity:
            parent.status = "filled"
        elif parent.resting_qty:
            parent.status = "partially_filled" if parent.filled_qty else "open"
        else:
            parent.status = "canceled"  # nothing resting: any unfilled remainder was canceled (IOC)
        parent.updated_ts = utc_now()

    def _on_fill(self, trade: Trade, taker: Order, maker: Order) -> None:
        fund_order = taker if taker.owner == FUND else maker if maker.owner == FUND else None
        if fund_order is None:
            return
        pid = self._child_parent.get(fund_order.id) or fund_order.parent_id
        parent = self.parents.get(pid) if pid else None
        if parent is None:
            return
        if fund_order.id not in self._child_parent:
            self._child_parent[fund_order.id] = parent.id
        resting_fill = fund_order is maker
        if resting_fill:
            self._reconcile(parent)
            self._bus.publish(
                "order.parent_updated", "fx",
                f"Resting child on {trade.venue} filled {trade.quantity:,} at {trade.price}; parent {parent.id} now "
                f"{parent.filled_qty:,}/{parent.quantity:,} filled (VWAP {parent.vwap}).",
                entity_id=parent.id, correlation_id=parent.id, data={"filled": parent.filled_qty, "vwap": str(parent.vwap)},
            )
        for fn in self.fund_fill_listeners:
            fn(trade, fund_order, parent)

    def _on_cancel(self, order: Order) -> None:
        pid = self._child_parent.get(order.id)
        if pid and pid in self.parents and order.owner == FUND:
            self._reconcile(self.parents[pid])

    def cancel_parent(self, parent_id: str) -> ParentOrder:
        parent = self.parents.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        n = 0
        for c in parent.children:
            v = self.books[c.book].venues[parent.pair]
            if c.order_id in v.book:
                v.cancel(c.order_id, "Parent order canceled by request.")
                n += 1
        if n == 0:
            raise ValueError(f"Parent {parent_id} has no resting child orders to cancel.")
        self._reconcile(parent)
        return parent

    # ---- snapshots ----------------------------------------------------------
    def book_snapshot(self, name: str, pair: str, depth: int = 10) -> dict[str, Any]:
        b = self.books[name]
        v = b.venues[pair]
        d = v.depth(depth)
        fund_trades = [t for t in v.trades if FUND in (t.taker_owner, t.maker_owner)]
        requested = v.stats["requested_qty"]
        bid_depth = sum(q for _, q, _ in v.book.levels(Side.BUY, 100))
        ask_depth = sum(q for _, q, _ in v.book.levels(Side.SELL, 100))
        resting = [o for o in v.orders.values() if o.owner == FUND and o.id in v.book]
        return {
            "name": name,
            "config": b.config,
            "pair": pair,
            **d,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "fill_rate": (Decimal(v.stats["filled_qty"]) / Decimal(requested)) if requested else None,
            "fund_requested_qty": requested,
            "fund_filled_qty": v.stats["filled_qty"],
            "recent_trades": list(reversed(fund_trades[-20:])),
            "resting_fund_orders": resting,
            "latency_ms": b.config.latency_ms,
        }

    def snapshot(self, pair: str) -> dict[str, Any]:
        spec = PAIRS[pair]
        return {
            "pair": spec,
            "pairs": list(PAIRS),
            "mid": self.mids[pair],
            "mids": self.mids,
            "weights": self.weights,
            "books": [self.book_snapshot(n, pair) for n in self.books],
            "parents": [p for p in reversed(self.parents.values()) if p.pair == pair][:20],
            "rate_series": self.rate_series[pair][-300:],
            "scenario": None if self.scenario is None else {**self.scenario, "next_step": self.scenario_step,
                                                             "complete": self.scenario_step >= len(self.scenario["steps"])},
            "notice": "All rates and book configurations are synthetic and hypothetical, not live market data.",
        }

    # ---- scenarios ------------------------------------------------------------
    def load_scenario(self, scenario: dict[str, Any], rng: random.Random) -> None:
        self._pause_sim()
        self.restore_defaults(rng)
        for name, overrides in scenario.get("books", {}).items():
            self.books[name].set_config(self.books[name].config.model_copy(update=overrides))
        self.mids["GBP/USD"] = Decimal("1.27000")
        self.rate_series["GBP/USD"] = []
        self._record_rate("GBP/USD")
        self.refresh_all()
        self.scenario = scenario
        self.scenario_step = 0
        self._bus.publish("scenario.loaded", "fx", f"FX scenario loaded: {scenario['title']}. {scenario['expect']}", entity_id=scenario["id"])

    def step_scenario(self) -> dict[str, Any]:
        if self.scenario is None:
            raise LookupError("No FX scenario loaded.")
        steps = self.scenario["steps"]
        if self.scenario_step >= len(steps):
            raise IndexError("All steps of this scenario are complete. Reset it to run again.")
        step = steps[self.scenario_step]
        a = step["action"]
        out: dict[str, Any] = {"title": step["title"], "observe": step["observe"]}
        if a.get("refresh", True):
            self.refresh_all("GBP/USD")
        if a["type"] == "order":
            w = RoutingWeights(**a.get("weights", {})) if a.get("weights") else None
            parent = self.submit_parent(
                "GBP/USD", Side(a["side"]), OrderType(a["order_type"]), a["quantity"],
                Decimal(a["limit_price"]) if a.get("limit_price") else None, a["mode"], weights=w,
            )
            out["parent"] = parent
        elif a["type"] == "shift_mid":
            self.set_mid("GBP/USD", self.mids["GBP/USD"] + Decimal(a["pips"]) * PAIRS["GBP/USD"].pip, "scenario step")
        self.scenario_step += 1
        self._bus.publish("scenario.step", "fx", f"Scenario step {self.scenario_step}: {step['title']}. {step['observe']}",
                          entity_id=self.scenario["id"])
        return out


def fmt_money(v: Decimal) -> str:
    return str(money(v))
