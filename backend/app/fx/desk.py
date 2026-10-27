"""The broker's trading desk: the risk it takes on the B-book and C-book, and how it hedges.

When a client trades on the B-book the desk takes the opposite side, so the desk's
position is always the mirror image of the client's. On the C-book the desk does the
same but immediately passes a share of each trade to the A-book liquidity providers.

The desk hedges its GBP exposure with British pound futures (modelled on CME 6B:
£62,500 per contract, quoted in USD per GBP). Other currencies are hedged by
trading spot with the liquidity providers.
"""

from __future__ import annotations

from collections import deque
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.money import money
from app.fx.config import PAIRS, DeskConfig
from app.markets.ledger import PositionLedger
from app.markets.models import Side
from app.portfolio.futures import FuturesBook, FuturesSpec

SIXB = FuturesSpec(
    symbol="6B-style GBP future (illustrative)", contract_size=62_500, max_fill_per_order=1000,
    label="Modelled on CME British pound futures (6B): £62,500 per contract, quoted in USD per GBP. Terms simplified.",
)


class Desk:
    def __init__(self, cfg: DeskConfig | None = None) -> None:
        self.config = cfg or DeskConfig()
        self.reset()

    def reset(self) -> None:
        self.spot: dict[str, PositionLedger] = {p: PositionLedger() for p in PAIRS}
        self.spread_earned: dict[str, Decimal] = {p: Decimal(0) for p in PAIRS}
        self.client_volume: dict[str, int] = {p: 0 for p in PAIRS}
        self.externalised: dict[str, int] = {p: 0 for p in PAIRS}
        self.futures = FuturesBook(SIXB.model_copy())
        self.futures_fees = Decimal(0)
        self.futures_realized = Decimal(0)
        self.log: deque[dict[str, Any]] = deque(maxlen=60)

    def position(self, pair: str) -> int:
        return self.spot[pair].position

    def gbp_exposure(self) -> int:
        return self.spot["GBP/USD"].position + self.futures.gbp_equivalent()

    # ---- trades -----------------------------------------------------------------
    def client_fill(self, pair: str, desk_side: Side, qty: int, price: Decimal, mid: Decimal, book: str) -> None:
        """The desk took the other side of a client trade on the B-book or C-book."""
        led = self.spot[pair]
        led.apply(desk_side, qty, price)
        self.spread_earned[pair] += (mid - price) * desk_side.sign * qty
        self.client_volume[pair] += qty
        self.log.append({"kind": "client", "book": book, "pair": pair, "side": desk_side, "quantity": qty, "price": price})

    def lp_fill(self, pair: str, side: Side, qty: int, price: Decimal, fee: Decimal, purpose: str) -> None:
        """The desk traded with the A-book liquidity providers (pass-through share or a spot hedge)."""
        self.spot[pair].apply(side, qty, price, fee=fee)
        self.externalised[pair] += qty
        self.log.append({"kind": purpose, "book": "A", "pair": pair, "side": side, "quantity": qty, "price": price, "fee": fee})

    def futures_hedge(self, spot_mid: Decimal) -> dict[str, Any] | None:
        """Trade 6B futures so the desk's GBP exposure is as close to zero as whole contracts allow."""
        size = Decimal(self.futures.spec.contract_size)
        target = -int((Decimal(self.spot["GBP/USD"].position) / size).to_integral_value(rounding=ROUND_HALF_UP))
        delta = target - self.futures.contracts
        if delta == 0:
            return None
        side = Side.BUY if delta > 0 else Side.SELL
        fill = self.futures.execute(side, abs(delta), spot_mid)
        self.futures_fees += fill.fee
        self.futures_realized += fill.realized_usd
        entry = {"kind": "futures", "book": "6B", "pair": "GBP/USD", "side": side, "quantity": fill.filled, "price": fill.price, "fee": fill.fee}
        self.log.append(entry)
        return entry

    # ---- valuation ----------------------------------------------------------------
    @staticmethod
    def _to_usd(pair: str, amount_quote: Decimal, mids: dict[str, Decimal]) -> Decimal:
        quote = PAIRS[pair].quote
        return amount_quote if quote == "USD" else amount_quote / mids["USD/JPY"]

    def snapshot(self, mids: dict[str, Decimal]) -> dict[str, Any]:
        pairs = []
        total = Decimal(0)
        for p, led in self.spot.items():
            mid = mids[p]
            realized, unreal, fees = led.realized_pnl, led.unrealized_pnl(mid), led.fees
            pnl_usd = self._to_usd(p, realized + unreal - fees, mids)
            total += pnl_usd
            if led.trade_count == 0:
                continue
            pairs.append({
                "pair": p, "position": led.position, "avg_price": led.avg_cost, "mid": mid,
                "spread_earned": money(self.spread_earned[p], "0.01"), "realized": money(realized), "unrealized": money(unreal),
                "fees": money(fees), "pnl_usd": money(pnl_usd), "client_volume": self.client_volume[p], "externalised": self.externalised[p],
                "direction": "short" if led.position < 0 else "long" if led.position > 0 else "flat",
            })
        fut_unreal = self.futures.unrealized_usd(mids["GBP/USD"])
        total += fut_unreal + self.futures_realized - self.futures_fees
        return {
            "config": self.config,
            "pairs": pairs,
            "gbp_exposure": self.gbp_exposure(),
            "futures": {
                "spec": self.futures.spec, "contracts": self.futures.contracts, "gbp_equivalent": self.futures.gbp_equivalent(),
                "price": self.futures.price(mids["GBP/USD"]), "unrealized_usd": money(fut_unreal),
                "realized_usd": money(self.futures_realized), "fees_usd": money(self.futures_fees),
            },
            "total_pnl_usd": money(total),
            "log": list(reversed(self.log))[:25],
        }
