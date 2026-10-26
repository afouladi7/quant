"""FX configuration: currency pairs and the three hypothetical books A, B, C.

Convention: a pair BASE/QUOTE is priced in QUOTE units per 1 BASE.
GBP/USD 1.27000 means 1 GBP costs 1.27 USD. Quantities are in BASE units.
A *pip* is 0.0001 for USD-quoted pairs and 0.01 for JPY-quoted pairs; prices
tick in tenths of a pip.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class PairSpec(BaseModel):
    symbol: str
    base: str
    quote: str
    pip: Decimal
    tick_size: Decimal
    initial_mid: Decimal
    volatility_pips: Decimal = Field(description="Std. dev. of mid move per tick, in pips")
    lot_size: int = 1000


PAIRS: dict[str, PairSpec] = {
    p.symbol: p
    for p in (
        PairSpec(symbol="GBP/USD", base="GBP", quote="USD", pip=Decimal("0.0001"), tick_size=Decimal("0.00001"),
                 initial_mid=Decimal("1.27000"), volatility_pips=Decimal("0.4")),
        PairSpec(symbol="EUR/USD", base="EUR", quote="USD", pip=Decimal("0.0001"), tick_size=Decimal("0.00001"),
                 initial_mid=Decimal("1.08500"), volatility_pips=Decimal("0.3")),
        PairSpec(symbol="USD/JPY", base="USD", quote="JPY", pip=Decimal("0.01"), tick_size=Decimal("0.001"),
                 initial_mid=Decimal("151.200"), volatility_pips=Decimal("0.5")),
    )
}


class BookConfig(BaseModel):
    """Hypothetical liquidity profile of one book (applies to every pair it lists)."""

    name: str = Field(pattern="^[ABC]$")
    description: str = ""
    spread_pips: Decimal = Field(gt=0, le=100, description="Liquidity-provider quoted spread")
    price_offset_pips: Decimal = Field(Decimal(0), ge=-50, le=50, description="Shift of this book's mid vs. the market mid")
    levels: int = Field(ge=1, le=20, description="Price levels per side")
    level_step_pips: Decimal = Field(gt=0, le=50, description="Distance between levels")
    qty_per_level: int = Field(ge=1000, le=100_000_000, description="Base-currency quantity per level")
    fee_bps: Decimal = Field(ge=0, le=50, description="Taker fee in basis points of notional (quote currency)")
    latency_ms: int = Field(ge=0, le=5000, description="Simulated one-way latency used by the router and recorded on fills")

    @model_validator(mode="after")
    def _lots(self) -> "BookConfig":
        if self.qty_per_level % 1000:
            raise ValueError("qty_per_level must be a multiple of 1,000")
        return self


DEFAULT_BOOKS: dict[str, BookConfig] = {
    "A": BookConfig(name="A", description="Tight spread, thin depth", spread_pips=Decimal("0.6"), levels=3,
                    level_step_pips=Decimal("0.5"), qty_per_level=200_000, fee_bps=Decimal("0.25"), latency_ms=2),
    "B": BookConfig(name="B", description="Deep liquidity, slightly wider spread", spread_pips=Decimal("1.0"), levels=5,
                    level_step_pips=Decimal("0.2"), qty_per_level=1_000_000, fee_bps=Decimal("0.20"), latency_ms=5),
    "C": BookConfig(name="C", description="Competitive prices, high latency", spread_pips=Decimal("0.7"), levels=4,
                    level_step_pips=Decimal("0.2"), qty_per_level=500_000, fee_bps=Decimal("0.15"), latency_ms=45),
}


class RoutingWeights(BaseModel):
    include_fees: bool = True
    latency_penalty_bps_per_100ms: Decimal = Field(
        Decimal("0.1"), ge=0, le=100,
        description="Cost charged per 100 ms of book latency, in bps of price (a proxy for the risk the price moves while the order travels)",
    )
