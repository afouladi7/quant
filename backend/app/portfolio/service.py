"""Educational hedge-fund portfolio: currency balances, exposure, valuation and hedging.

Valuation currency is USD. Conversions use the current synthetic mid rates:
GBP→USD and EUR→USD multiply by GBP/USD and EUR/USD; JPY→USD divides by USD/JPY.

Distinctions kept explicit (spec §7.1):
- *cash balances*: amounts held per currency (spot FX fills move these)
- *currency exposure*: what changes in USD value when a currency moves; spot
  balances plus the GBP-equivalent of futures contracts
- *derivative positions*: futures contracts (never added to cash balances)
- *P&L*: equity (USD value of balances + futures unrealized) minus initial equity
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.clock import utc_now
from app.core.ids import IdGenerator
from app.core.money import money
from app.events.bus import EventBus
from app.fx.config import PAIRS
from app.fx.service import FXService, ParentOrder
from app.markets.ledger import PositionLedger
from app.markets.models import Order, OrderType, Side, Trade
from app.portfolio.futures import FuturesBook, FuturesSpec

USD = "USD"
INITIAL_USD = Decimal("20000000")
ANNUAL_VOL = Decimal("0.08")  # illustrative GBP/USD annualised volatility for VaR
Z95 = Decimal("1.645")


class HedgeRequest(BaseModel):
    instrument: Literal["fx_offset", "futures"]
    mode: Literal["manual", "rule"] = "rule"
    currency: Literal["GBP", "EUR"] = "GBP"
    # manual
    direction: Side | None = None
    quantity: int | None = Field(None, gt=0, le=1_000_000_000, description="Currency units (fx_offset) or contracts (futures)")
    routing_mode: str = Field("smart", pattern="^(A|B|C|smart)$")
    limit_price: Decimal | None = Field(None, gt=0)
    max_hedge_notional_usd: Decimal | None = Field(None, gt=0, description="Optional risk limit: refuse larger hedges")
    # rule
    target_exposure: Decimal = Field(Decimal(0), description="Desired net exposure in currency units")
    max_exposure: Decimal = Field(Decimal(0), ge=0, description="Hedge only when |exposure - target| exceeds this")

    @model_validator(mode="after")
    def _check(self) -> "HedgeRequest":
        if self.mode == "manual" and (self.direction is None or self.quantity is None):
            raise ValueError("manual hedges need direction and quantity")
        if self.instrument == "futures" and self.currency != "GBP":
            raise ValueError("only GBP futures are modelled")
        return self


class HedgeRule(BaseModel):
    enabled: bool = False
    auto_execute: bool = False
    instrument: Literal["fx_offset", "futures"] = "futures"
    target_exposure: Decimal = Decimal(0)
    max_exposure: Decimal = Field(Decimal(250_000), ge=0)


class HedgeProposal(BaseModel):
    id: str
    status: str = "proposed"  # proposed | executed | partially_executed | failed | not_needed | rejected
    request: HedgeRequest
    currency: str
    instrument: str
    direction: Side | None
    quantity: int
    unit: str
    gbp_equivalent: int
    exposure_before: Decimal
    projected_exposure_after: Decimal
    projected_residual: Decimal
    est_price: Decimal | None
    est_fees_usd: Decimal
    est_notional_usd: Decimal
    pnl_plus1_before: Decimal
    pnl_plus1_after: Decimal
    explanation: str
    assumptions: list[str]
    created_ts: datetime
    executed_ts: datetime | None = None
    filled_quantity: int = 0
    exec_price: Decimal | None = None
    exec_fees_usd: Decimal = Decimal(0)
    actual_exposure_after: Decimal | None = None
    parent_order_id: str | None = None
    result: str | None = None


class PortfolioService:
    name = "portfolio"

    def __init__(self, bus: EventBus, ids: IdGenerator, fx: FXService, pause_sim: Callable[[], None]) -> None:
        self._bus = bus
        self._ids = ids
        self.fx = fx
        self._pause_sim = pause_sim
        self.futures_spec = FuturesSpec()
        self.rule = HedgeRule()
        fx.fund_fill_listeners.append(self._on_fund_fill)
        fx.reset_listeners.append(self.reset)
        fx.parent_listeners.append(self._after_parent)
        self.guided_step = 0
        self.reset()

    # ---- lifecycle --------------------------------------------------------------
    def reset(self) -> None:
        self.balances: dict[str, Decimal] = {USD: INITIAL_USD, "GBP": Decimal(0), "EUR": Decimal(0), "JPY": Decimal(0)}
        self.hedge_spot: dict[str, Decimal] = {c: Decimal(0) for c in self.balances}
        self.spot: dict[str, PositionLedger] = {p: PositionLedger() for p in PAIRS}
        self.futures = FuturesBook(self.futures_spec.model_copy())
        self.futures_fees = Decimal(0)
        self.futures_realized = Decimal(0)
        self.fills: deque[dict[str, Any]] = deque(maxlen=500)
        self.proposals: OrderedDict[str, HedgeProposal] = OrderedDict()
        self.history: deque[dict[str, Any]] = deque(maxlen=600)
        self._n = 0
        self._record()

    def on_reset(self, rng: random.Random) -> None:  # registered with the orchestrator
        self.guided_step = 0
        # FXService.on_reset already triggers self.reset via reset_listeners.

    def on_tick(self, tick: int, sim_time: datetime) -> None:
        self._evaluate_rule(source="tick")
        self._record()

    # ---- rates & valuation -----------------------------------------------------
    def rate_to_usd(self, ccy: str) -> Decimal:
        if ccy == USD:
            return Decimal(1)
        if ccy == "JPY":
            return Decimal(1) / self.fx.mids["USD/JPY"]
        return self.fx.mids[f"{ccy}/USD"]

    @property
    def gbp_spot_rate(self) -> Decimal:
        return self.fx.mids["GBP/USD"]

    def futures_price(self) -> Decimal:
        return self.futures.price(self.gbp_spot_rate)

    def exposure(self, ccy: str, include_hedges: bool = True) -> Decimal:
        spot = self.balances[ccy] - (Decimal(0) if include_hedges else self.hedge_spot[ccy])
        fut = Decimal(self.futures.gbp_equivalent()) if (ccy == "GBP" and include_hedges) else Decimal(0)
        return spot + fut

    def equity_usd(self) -> Decimal:
        cash = sum((amt * self.rate_to_usd(c) for c, amt in self.balances.items()), Decimal(0))
        return cash + self.futures.unrealized_usd(self.gbp_spot_rate)

    def _exposure_rows(self) -> list[dict[str, Any]]:
        rows = []
        for ccy in ("GBP", "EUR", "JPY"):
            rate = self.rate_to_usd(ccy)
            spot = self.balances[ccy]
            fut = Decimal(self.futures.gbp_equivalent()) if ccy == "GBP" else Decimal(0)
            net = spot + fut
            pre = self.exposure(ccy, include_hedges=False)
            rows.append({
                "currency": ccy,
                "rate_to_usd": rate,
                "spot_balance": spot,
                "hedge_spot": self.hedge_spot[ccy],
                "futures_equivalent": fut,
                "net_exposure": net,
                "net_exposure_usd": money(net * rate),
                "pre_hedge_exposure": pre,
                "pre_hedge_exposure_usd": money(pre * rate),
                "direction": "long" if net > 0 else "short" if net < 0 else "flat",
                "pnl_if_plus_1pct_usd": money(net * rate * Decimal("0.01")),
                "pnl_if_plus_1pct_pre_hedge_usd": money(pre * rate * Decimal("0.01")),
            })
        return rows

    def snapshot(self) -> dict[str, Any]:
        eq = self.equity_usd()
        rows = self._exposure_rows()
        spot_rows = []
        for sym, led in self.spot.items():
            spec = PAIRS[sym]
            mark = self.fx.mids[sym]
            conv = self.rate_to_usd(spec.quote)
            if led.trade_count == 0:
                continue
            spot_rows.append({
                "pair": sym, "position": led.position, "avg_price": led.avg_cost, "mark": mark,
                "realized": led.realized_pnl, "unrealized": led.unrealized_pnl(mark), "fees": led.fees, "quote_ccy": spec.quote,
                "realized_usd": money(led.realized_pnl * conv), "unrealized_usd": money(led.unrealized_pnl(mark) * conv),
                "fees_usd": money(led.fees * conv),
            })
        spot_r = sum((Decimal(r["realized_usd"]) for r in spot_rows), Decimal(0))
        spot_u = sum((Decimal(r["unrealized_usd"]) for r in spot_rows), Decimal(0))
        spot_f = sum((Decimal(r["fees_usd"]) for r in spot_rows), Decimal(0))
        fut_u = self.futures.unrealized_usd(self.gbp_spot_rate)
        f_bid, f_ask = self.futures.quote(self.gbp_spot_rate)
        gross = sum((abs(Decimal(r["net_exposure_usd"])) for r in rows), Decimal(0))
        net = sum((Decimal(r["net_exposure_usd"]) for r in rows), Decimal(0))
        return {
            "valuation_currency": USD,
            "rates": {s: self.fx.mids[s] for s in PAIRS},
            "balances": [{"currency": c, "amount": a, "usd_value": money(a * self.rate_to_usd(c))} for c, a in self.balances.items()],
            "exposures": rows,
            "gross_exposure_usd": gross,
            "net_exposure_usd": net,
            "equity_usd": money(eq),
            "initial_equity_usd": INITIAL_USD,
            "total_pnl_usd": money(eq - INITIAL_USD),
            "pnl_breakdown": {
                "spot_realized_usd": spot_r, "spot_unrealized_usd": spot_u, "spot_fees_usd": spot_f,
                "futures_realized_usd": money(self.futures_realized), "futures_unrealized_usd": money(fut_u),
                "futures_fees_usd": money(self.futures_fees),
                "note": "Non-USD-quoted P&L is converted at current rates, so components can differ from the total by small translation effects.",
            },
            "spot_positions": spot_rows,
            "futures": {
                "spec": self.futures.spec,
                "contracts": self.futures.contracts,
                "gbp_equivalent": self.futures.gbp_equivalent(),
                "price": self.futures_price(),
                "bid": f_bid, "ask": f_ask,
                "basis": self.futures.basis(),
                "basis_shock_pips": self.futures.basis_shock_pips,
                "avg_entry": self.futures.ledger.avg_cost,
                "unrealized_usd": money(fut_u),
                "realized_usd": money(self.futures_realized),
                "fees_usd": money(self.futures_fees),
                "expired": self.futures.expired,
                "margin": self.futures.margin(),
                "margin_note": "Margin is reported, not moved; daily variation margin is not simulated.",
            },
            "rule": self.rule,
            "proposals": list(reversed(self.proposals.values()))[:20],
            "fills": list(reversed(self.fills))[:40],
            "history": list(self.history),
            "guided_step": self.guided_step,
            "notice": "Hypothetical portfolio. Hedging reduces specific risks; it does not guarantee a profit or remove all risk.",
        }

    def _record(self) -> None:
        self._n += 1
        self.history.append({
            "n": self._n, "gbp_usd": self.gbp_spot_rate, "equity": money(self.equity_usd()),
            "pnl": money(self.equity_usd() - INITIAL_USD), "gbp_exposure": self.exposure("GBP"),
        })

    # ---- fills -----------------------------------------------------------------------
    def _on_fund_fill(self, trade: Trade, order: Order, parent: ParentOrder) -> None:
        spec = PAIRS[trade.instrument]
        fee = trade.taker_fee if trade.taker_owner == "fund" else trade.maker_fee
        sign = order.side.sign
        base_amt = Decimal(sign * trade.quantity)
        quote_amt = -sign * trade.price * trade.quantity
        self.balances[spec.base] += base_amt
        self.balances[spec.quote] += quote_amt - fee
        if parent.purpose == "hedge":
            self.hedge_spot[spec.base] += base_amt
            self.hedge_spot[spec.quote] += quote_amt - fee
        self.spot[trade.instrument].apply(order.side, trade.quantity, trade.price, fee=fee)
        self.fills.append({
            "ts": trade.ts, "instrument": trade.instrument, "kind": "spot", "purpose": parent.purpose, "side": order.side,
            "quantity": trade.quantity, "price": trade.price, "fee": fee, "fee_ccy": spec.quote, "venue": trade.venue,
            "parent_id": parent.id, "hedge_id": parent.hedge_id, "trade_id": trade.id,
        })
        self._bus.publish(
            "portfolio.updated", self.name,
            f"Portfolio: {'hedge' if parent.purpose == 'hedge' else 'trade'} fill {order.side.value} {trade.quantity:,} {spec.base} at {trade.price} on {trade.venue}. "
            f"{spec.base} balance {self.balances[spec.base]:,.0f}, {spec.quote} balance {self.balances[spec.quote]:,.2f}; "
            f"net {spec.base} exposure {self.exposure(spec.base) if spec.base != USD else self.exposure(spec.quote):,.0f}.",
            entity_id=trade.id, correlation_id=parent.id,
            data={"pair": trade.instrument, "purpose": parent.purpose, "base_delta": str(base_amt), "quote_delta": str(quote_amt - fee)},
        )

    def _after_parent(self, parent: ParentOrder) -> None:
        self._record()
        if parent.purpose == "trade":
            self._evaluate_rule(source=f"trade {parent.id}", correlation_id=parent.id)

    # ---- hedging -------------------------------------------------------------------------
    def _currency_pair(self, ccy: str) -> str:
        return f"{ccy}/USD"

    def propose(self, req: HedgeRequest, correlation_id: str | None = None) -> HedgeProposal:
        ccy = req.currency
        e = self.exposure(ccy)
        rate = self.rate_to_usd(ccy)
        size = self.futures.spec.contract_size
        assumptions = [
            f"Valuation in USD at the current mid {ccy}/USD {rate}.",
            "Prices, liquidity and fees are synthetic and hypothetical.",
        ]
        if req.mode == "rule":
            gap = e - req.target_exposure
            if abs(gap) <= req.max_exposure:
                return self._store(HedgeProposal(
                    id=self._ids.next("HDG"), status="not_needed", request=req, currency=ccy, instrument=req.instrument, direction=None,
                    quantity=0, unit="", gbp_equivalent=0, exposure_before=e, projected_exposure_after=e, projected_residual=gap,
                    est_price=None, est_fees_usd=Decimal(0), est_notional_usd=Decimal(0),
                    pnl_plus1_before=money(e * rate / 100), pnl_plus1_after=money(e * rate / 100),
                    explanation=f"No hedge needed: exposure {e:,.0f} {ccy} is within ±{req.max_exposure:,.0f} of the target {req.target_exposure:,.0f}.",
                    assumptions=assumptions, created_ts=utc_now(),
                ), correlation_id)
            direction = Side.SELL if gap > 0 else Side.BUY
            if req.instrument == "fx_offset":
                lot = PAIRS[self._currency_pair(ccy)].lot_size
                qty = int((abs(gap) / lot).to_integral_value(rounding=ROUND_HALF_UP)) * lot
            else:
                qty = int((abs(gap) / size).to_integral_value(rounding=ROUND_HALF_UP))
        else:
            direction, qty = req.direction, req.quantity  # type: ignore[assignment]
        assert direction is not None and qty is not None

        if req.instrument == "fx_offset":
            pair = self._currency_pair(ccy)
            plan = self.fx.preview(pair, direction, qty, req.limit_price, req.routing_mode)
            est_price = plan.expected_vwap
            fee_bps = {a.book: self.fx.books[a.book].config.fee_bps for a in plan.allocations}
            est_fees = sum((p * q * fee_bps[a.book] / 10_000 for a in plan.allocations for p, q in a.levels), Decimal(0))
            equiv = direction.sign * plan.planned_qty
            unit = ccy
            assumptions += [
                f"Offset trade routed {'smartly across books A/B/C' if req.routing_mode == 'smart' else 'to Book ' + req.routing_mode}; "
                f"expected average price {est_price} for the {plan.planned_qty:,} {ccy} currently available.",
                "Fills could differ if liquidity changes before execution.",
            ]
            if plan.unfilled_qty:
                assumptions.append(f"Only {plan.planned_qty:,} of {qty:,} {ccy} is available now; the rest would stay unhedged.")
            notional = (est_price or rate) * qty
        else:
            bid, ask = self.futures.quote(self.gbp_spot_rate)
            est_price = ask if direction is Side.BUY else bid
            avail = min(qty, self.futures.spec.max_fill_per_order)
            equiv = direction.sign * avail * size
            est_fees = self.futures.spec.fee_per_contract * avail
            unit = "contracts"
            notional = est_price * qty * size
            assumptions += [
                f"{qty} contract(s) × {size:,} GBP = {qty * size:,} GBP equivalent; contracts are whole numbers, so the hedge is rounded.",
                f"Futures price {self.futures_price()} = spot {self.gbp_spot_rate} + basis {self.futures.basis():+.5f}. The basis can move (basis risk) and shrinks to zero at expiry in {self.futures.spec.days_to_expiry} days.",
                f"Initial margin {money(self.futures.spec.initial_margin * qty)} USD would be required (reported only).",
                "Futures P&L is credited in USD; the contract does not change the fund's GBP cash balance.",
            ]
            if avail < qty:
                assumptions.append(f"Only {avail} contracts are available per order; {qty - avail} would remain unfilled.")
        after = e + equiv
        residual = after - (req.target_exposure if req.mode == "rule" else Decimal(0))
        prop = HedgeProposal(
            id=self._ids.next("HDG"), request=req, currency=ccy, instrument=req.instrument, direction=direction, quantity=qty, unit=unit,
            gbp_equivalent=int(equiv) if ccy == "GBP" else 0, exposure_before=e, projected_exposure_after=after, projected_residual=residual,
            est_price=est_price, est_fees_usd=money(est_fees * (1 if req.instrument == "futures" else 1)), est_notional_usd=money(notional),
            pnl_plus1_before=money(e * rate / 100), pnl_plus1_after=money(after * rate / 100),
            explanation=self._explain(ccy, e, after, direction, qty, unit, req),
            assumptions=assumptions, created_ts=utc_now(),
        )
        if req.max_hedge_notional_usd is not None and notional > req.max_hedge_notional_usd:
            prop.status = "rejected"
            prop.result = f"Rejected by risk limit: notional {money(notional):,} USD exceeds the limit {req.max_hedge_notional_usd:,} USD."
        return self._store(prop, correlation_id)

    def _explain(self, ccy: str, e: Decimal, after: Decimal, direction: Side, qty: int, unit: str, req: HedgeRequest) -> str:
        dir_word = "long" if e > 0 else "short" if e < 0 else "flat"
        what = (f"{direction.value} {qty:,} {ccy} against USD" if req.instrument == "fx_offset"
                else f"{direction.value} {qty} {self.futures.spec.symbol} contract(s)")
        gains = "rises" if e > 0 else "falls"
        return (
            f"The fund is {dir_word} {abs(e):,.0f} {ccy}, so it gains when {ccy} {gains} and loses in the opposite case. "
            f"Proposed hedge: {what}. Exposure would move from {e:,.0f} to {after:,.0f} {ccy}. "
            "The hedge reduces this currency risk but adds costs and, for futures, basis risk."
        )

    def _store(self, p: HedgeProposal, correlation_id: str | None) -> HedgeProposal:
        self.proposals[p.id] = p
        while len(self.proposals) > 200:
            self.proposals.popitem(last=False)
        self._bus.publish("hedge.proposed", self.name, f"Hedge proposal {p.id} ({p.status}): {p.result or p.explanation}",
                          entity_id=p.id, correlation_id=correlation_id or p.id,
                          data={"instrument": p.instrument, "quantity": p.quantity, "direction": p.direction.value if p.direction else None,
                                "projected_residual": str(p.projected_residual)})
        return p

    def execute(self, proposal_id: str) -> HedgeProposal:
        p = self.proposals.get(proposal_id)
        if p is None:
            raise KeyError(proposal_id)
        if p.status != "proposed":
            raise ValueError(f"Proposal {proposal_id} is {p.status}; only proposed hedges can be executed.")
        assert p.direction is not None
        if p.instrument == "fx_offset":
            parent = self.fx.submit_parent(
                self._currency_pair(p.currency), p.direction, OrderType.LIMIT if p.request.limit_price else OrderType.MARKET,
                p.quantity, p.request.limit_price, p.request.routing_mode, purpose="hedge", hedge_id=p.id,
            )
            p.parent_order_id = parent.id
            p.filled_quantity = parent.filled_qty
            p.exec_price = parent.vwap
            p.exec_fees_usd = money(parent.total_fees)
            corr = parent.id
        else:
            fill = self.futures.execute(p.direction, p.quantity, self.gbp_spot_rate)
            self.futures_fees += fill.fee
            self.futures_realized += fill.realized_usd
            self.balances[USD] += fill.realized_usd - fill.fee
            p.filled_quantity = fill.filled
            p.exec_price = fill.price
            p.exec_fees_usd = fill.fee
            corr = p.id
            self.fills.append({
                "ts": utc_now(), "instrument": self.futures.spec.symbol, "kind": "futures", "purpose": "hedge", "side": p.direction,
                "quantity": fill.filled, "price": fill.price, "fee": fill.fee, "fee_ccy": USD, "venue": "futures", "hedge_id": p.id,
            })
        p.executed_ts = utc_now()
        p.status = "executed" if p.filled_quantity == p.quantity else "partially_executed" if p.filled_quantity else "failed"
        p.actual_exposure_after = self.exposure(p.currency)
        unit = p.unit
        p.result = (
            f"Filled {p.filled_quantity:,} of {p.quantity:,} {unit} at {p.exec_price}. "
            f"{p.currency} exposure is now {p.actual_exposure_after:,.0f} (was {p.exposure_before:,.0f})."
            + (f" Partially filled: {p.quantity - p.filled_quantity:,} {unit} unfilled, so residual exposure is larger than planned." if p.status == "partially_executed" else "")
        )
        self._bus.publish("hedge.executed", self.name, f"Hedge {p.id} {p.status.replace('_', ' ')}: {p.result}",
                          entity_id=p.id, correlation_id=corr,
                          data={"filled": p.filled_quantity, "price": str(p.exec_price), "exposure_after": str(p.actual_exposure_after)})
        self._record()
        return p

    def _evaluate_rule(self, source: str, correlation_id: str | None = None) -> None:
        r = self.rule
        if not r.enabled:
            return
        if any(p.status == "proposed" for p in self.proposals.values()):
            return
        e = self.exposure("GBP")
        if abs(e - r.target_exposure) <= r.max_exposure:
            return
        p = self.propose(HedgeRequest(instrument=r.instrument, mode="rule", target_exposure=r.target_exposure, max_exposure=r.max_exposure),
                         correlation_id)
        if r.auto_execute and p.status == "proposed":
            self.execute(p.id)

    # ---- futures controls --------------------------------------------------------------------
    def set_futures_spec(self, spec: FuturesSpec) -> None:
        if self.futures.contracts != 0:
            raise ValueError("Close the futures position before changing contract terms.")
        self.futures_spec = spec
        self.futures = FuturesBook(spec.model_copy())

    def shock_basis(self, pips: Decimal) -> None:
        self.futures.basis_shock_pips = pips
        self._bus.publish("futures.basis_changed", self.name,
                          f"Futures basis shocked by {pips:+} pips: the future now moves differently from spot (basis risk).",
                          data={"shock_pips": str(pips)})
        self._record()

    def advance_days(self, days: int) -> dict[str, Any]:
        s = self.futures.spec
        s.days_to_expiry = max(0, s.days_to_expiry - days)
        msg = f"Calendar advanced {days} day(s); {s.days_to_expiry} day(s) to futures expiry. Basis now {self.futures.basis():+.5f}."
        realized = None
        if s.days_to_expiry == 0 and not self.futures.expired:
            realized = self.futures.settle(self.gbp_spot_rate)
            self.futures_realized += realized
            self.balances[USD] += realized
            msg += f" The contract expired and was cash-settled at spot {self.futures.settlement_price}; realized {money(realized)} USD. The hedge no longer exists — exposure is back unless it is rolled."
        self._bus.publish("futures.calendar", self.name, msg, data={"days_to_expiry": s.days_to_expiry})
        self._record()
        return {"message": msg, "days_to_expiry": s.days_to_expiry, "settled_realized_usd": realized}

    # ---- risk scenarios ----------------------------------------------------------------------
    def risk(self) -> dict[str, Any]:
        S = self.gbp_spot_rate
        size = Decimal(self.futures.spec.contract_size)
        contracts = Decimal(self.futures.contracts)
        spot_total = self.balances["GBP"]
        pre = self.exposure("GBP", include_hedges=False)
        post = self.exposure("GBP")
        d1 = S * Decimal("0.01")

        def hedged_pnl(spot_move: Decimal, fut_move: Decimal) -> Decimal:
            return money(spot_total * spot_move + contracts * size * fut_move)

        daily = ANNUAL_VOL / Decimal(math.sqrt(252))
        var = lambda e, vol: money(Z95 * vol * abs(e) * S)  # noqa: E731
        hedge_gbp = post - pre
        half = pre + hedge_gbp / 2
        basis_now = self.futures.basis()
        rows = [
            {"id": "gbp_up", "title": "GBP appreciates 1%", "unhedged": money(pre * d1), "hedged": hedged_pnl(d1, d1),
             "explain": "Spot GBP gains; a short hedge loses about the same, so the hedged result is close to zero."},
            {"id": "gbp_down", "title": "GBP depreciates 1%", "unhedged": money(-pre * d1), "hedged": hedged_pnl(-d1, -d1),
             "explain": "Spot GBP loses; the hedge gains. The hedge gives up upside in exchange for protection."},
            {"id": "vol_normal", "title": f"1-day 95% VaR at {ANNUAL_VOL:.0%}/yr volatility", "unhedged": -var(pre, daily), "hedged": -var(post, daily),
             "explain": "Value-at-Risk: a loss the portfolio should exceed on only 1 day in 20, if the illustrative volatility assumption holds."},
            {"id": "vol_high", "title": f"Volatility doubles ({2 * ANNUAL_VOL:.0%}/yr): 1-day 95% VaR", "unhedged": -var(pre, 2 * daily), "hedged": -var(post, 2 * daily),
             "explain": "Higher volatility scales risk up for whatever exposure remains. A good hedge shrinks the exposure being scaled."},
            {"id": "partial", "title": "Hedge only 50% filled, then GBP +1%", "unhedged": money(pre * d1), "hedged": money(half * d1),
             "explain": "If only half the hedge executes, half the exposure remains." if hedge_gbp else "No hedge in place yet, so a partial fill has nothing to halve."},
            {"id": "basis", "title": "GBP +1% but futures rise only 0.8% (basis risk)", "unhedged": money(pre * d1),
             "hedged": hedged_pnl(d1, S * Decimal("0.008")),
             "explain": "The future and the currency do not move exactly together; the mismatch is basis risk." if contracts else "No futures position: basis risk does not apply."},
            {"id": "expiry", "title": f"Futures converge to spot by expiry ({self.futures.spec.days_to_expiry} days)", "unhedged": Decimal("0.00"),
             "hedged": money(contracts * size * (-basis_now)),
             "explain": "With spot unchanged, the basis shrinks to zero; a short future gains (or a long loses) the remaining basis. At expiry the hedge ends and must be rolled to keep protection." if contracts else "No futures position."},
        ]
        return {
            "spot": S, "futures_price": self.futures_price(), "pre_hedge_exposure_gbp": pre, "post_hedge_exposure_gbp": post,
            "rows": rows,
            "assumptions": [
                "Hypothetical instantaneous moves; no re-hedging, financing or carry other than the modelled basis.",
                f"VaR uses an illustrative {ANNUAL_VOL:.0%} annual volatility, normal distribution, z = {Z95}.",
                "Unhedged = the fund's non-hedge positions only; hedged = everything including hedges.",
            ],
        }

    # ---- guided GBP scenario (preset 4) -------------------------------------------------------
    GUIDED_STEPS = [
        "The fund buys GBP 1,000,000 against USD",
        "GBP/USD moves (default +1%)",
        "Calculate the hedge",
        "Execute the hedge",
        "Compare: GBP/USD moves again (default −1%)",
    ]

    def guided_reset(self, rng: random.Random) -> None:
        self._pause_sim()
        self.futures_spec = FuturesSpec()
        self.rule = HedgeRule()
        self.fx.restore_defaults(rng)  # also resets this portfolio via reset_listeners
        self.guided_step = 0
        self._bus.publish("scenario.loaded", self.name, "GBP hedging scenario reset: USD 20,000,000 cash, no positions, GBP/USD 1.33000.")

    def guided_next(self, instrument: str = "futures", rate_pct: Decimal | None = None) -> dict[str, Any]:
        step = self.guided_step
        if step >= len(self.GUIDED_STEPS):
            raise IndexError("The guided scenario is complete. Reset it to run again.")
        out: dict[str, Any] = {"step": step + 1, "title": self.GUIDED_STEPS[step]}
        if step == 0:
            parent = self.fx.submit_parent("GBP/USD", Side.BUY, OrderType.MARKET, 1_000_000, None, "smart")
            out["parent"] = parent
            out["observe"] = (f"The fund now holds {self.balances['GBP']:,.0f} GBP and paid {-(self.balances['USD'] - INITIAL_USD):,.2f} USD "
                              "(including fees). It is long GBP: it profits if GBP rises and loses if GBP falls.")
        elif step == 1:
            pct = rate_pct if rate_pct is not None else Decimal("1")
            before = self.equity_usd()
            self.fx.set_mid("GBP/USD", self.gbp_spot_rate * (1 + pct / 100), "guided scenario")
            out["observe"] = (f"GBP/USD moved {pct:+}% to {self.gbp_spot_rate}. Portfolio value changed by "
                              f"{money(self.equity_usd() - before):,} USD — this is unhedged currency risk.")
        elif step == 2:
            p = self.propose(HedgeRequest(instrument=instrument, mode="rule"))  # type: ignore[arg-type]
            out["proposal"] = p
            out["observe"] = p.explanation + f" Projected residual exposure: {p.projected_residual:,.0f} GBP."
        elif step == 3:
            pending = [p for p in self.proposals.values() if p.status == "proposed"]
            if not pending:
                raise LookupError("No pending proposal to execute.")
            p = self.execute(pending[-1].id)
            out["proposal"] = p
            out["observe"] = p.result
        else:
            pct = rate_pct if rate_pct is not None else Decimal("-1")
            risk_before = self.equity_usd()
            unhedged_change = self.exposure("GBP", include_hedges=False) * self.gbp_spot_rate * pct / 100
            self.fx.set_mid("GBP/USD", self.gbp_spot_rate * (1 + pct / 100), "guided scenario")
            out["observe"] = (f"GBP/USD moved {pct:+}%. Without the hedge the fund would have changed by about {money(unhedged_change):,} USD; "
                              f"with it, the change was {money(self.equity_usd() - risk_before):,} USD. The remaining difference is residual "
                              "exposure (rounding to whole contracts or lots), fees and basis.")
        self.guided_step += 1
        self._bus.publish("scenario.step", self.name, f"GBP hedging step {step + 1}: {out['title']}. {out['observe']}")
        self._record()
        return out
