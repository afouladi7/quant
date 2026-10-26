"""An ILLUSTRATIVE GBP currency future. Contract terms are configurable and are not
those of any real exchange product.

Model (documented simplifications):
- Quote: USD per GBP, like the spot pair. One contract = ``contract_size`` GBP,
  so a 0.0001 move is worth contract_size × 0.0001 USD per contract.
- Futures price F = spot S + basis. The basis starts at ``initial_basis_pips``
  and shrinks linearly to zero at expiry (convergence), plus any ``basis_shock_pips``
  applied in risk scenarios.
- Execution: fills at F ± half-spread, up to ``max_fill_per_order`` contracts per
  order (the rest is unfilled), fee per contract in USD.
- P&L: (F_now − F_entry) × contracts × contract_size, FIFO lots. Realized P&L is
  credited to USD cash when a position is reduced or settles at expiry.
- Margin: initial and maintenance margin are *reported* (required vs. available
  cash), but cash is not moved into a margin account and daily variation-margin
  cycles are not simulated.
- Expiry: when the remaining days reach zero the position is cash-settled at spot.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.money import round_to_tick
from app.markets.ledger import PositionLedger
from app.markets.models import Side


class FuturesSpec(BaseModel):
    symbol: str = "GBPUSD-FUT (illustrative)"
    underlying: str = "GBP/USD"
    contract_size: int = Field(62_500, ge=1000, le=10_000_000, description="GBP per contract")
    tick_size: Decimal = Field(Decimal("0.0001"), gt=0, le=Decimal("0.01"))
    days_total: int = Field(90, ge=1, le=730, description="Contract life in days (listing to expiry)")
    days_to_expiry: int = Field(75, ge=0, le=730)
    initial_basis_pips: Decimal = Field(Decimal("12"), ge=-500, le=500, description="Futures minus spot at listing, in pips")
    half_spread_ticks: int = Field(1, ge=0, le=50)
    fee_per_contract: Decimal = Field(Decimal("2.00"), ge=0, le=100)
    initial_margin: Decimal = Field(Decimal("3000"), ge=0, le=1_000_000, description="USD per contract (illustrative)")
    maintenance_margin: Decimal = Field(Decimal("2700"), ge=0, le=1_000_000)
    max_fill_per_order: int = Field(100, ge=1, le=100_000, description="Contracts available per order (liquidity)")
    label: str = "Illustrative contract terms. Real GBP futures differ by exchange and contract."


class FuturesFill(BaseModel):
    side: Side
    requested: int
    filled: int
    price: Decimal | None
    fee: Decimal
    realized_usd: Decimal


class FuturesBook:
    def __init__(self, spec: FuturesSpec) -> None:
        self.spec = spec
        self.basis_shock_pips = Decimal(0)
        self.ledger = PositionLedger()
        self.expired = False
        self.settlement_price: Decimal | None = None

    def basis(self) -> Decimal:
        s = self.spec
        frac = Decimal(s.days_to_expiry) / Decimal(s.days_total)
        return (s.initial_basis_pips * frac + self.basis_shock_pips) * Decimal("0.0001")

    def price(self, spot: Decimal) -> Decimal:
        if self.expired and self.settlement_price is not None:
            return self.settlement_price
        return round_to_tick(spot + self.basis(), self.spec.tick_size)

    def quote(self, spot: Decimal) -> tuple[Decimal, Decimal]:
        f = self.price(spot)
        h = self.spec.tick_size * self.spec.half_spread_ticks
        return f - h, f + h

    @property
    def contracts(self) -> int:
        return self.ledger.position

    def gbp_equivalent(self) -> int:
        return self.contracts * self.spec.contract_size

    def unrealized_usd(self, spot: Decimal) -> Decimal:
        return self.ledger.unrealized_pnl(self.price(spot)) * self.spec.contract_size

    def execute(self, side: Side, contracts: int, spot: Decimal) -> FuturesFill:
        if self.expired:
            raise ValueError("The contract has expired; no further trading.")
        if contracts <= 0:
            raise ValueError("contracts must be positive")
        filled = min(contracts, self.spec.max_fill_per_order)
        bid, ask = self.quote(spot)
        px = ask if side is Side.BUY else bid
        fee = self.spec.fee_per_contract * filled
        realized = self.ledger.apply(side, filled, px, fee=Decimal(0)) * self.spec.contract_size
        return FuturesFill(side=side, requested=contracts, filled=filled, price=px, fee=fee, realized_usd=realized)

    def settle(self, spot: Decimal) -> Decimal:
        """Cash-settle the open position at spot; returns realized USD."""
        self.settlement_price = round_to_tick(spot, self.spec.tick_size)
        realized = Decimal(0)
        pos = self.contracts
        if pos:
            realized = self.ledger.apply(Side.SELL if pos > 0 else Side.BUY, abs(pos), self.settlement_price) * self.spec.contract_size
        self.expired = True
        return realized

    def margin(self) -> dict[str, Decimal]:
        n = abs(self.contracts)
        return {"initial_required": self.spec.initial_margin * n, "maintenance_required": self.spec.maintenance_margin * n}
