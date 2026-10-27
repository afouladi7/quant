"""FX configuration: currency pairs and the three hypothetical books A, B, C.

Convention: a pair BASE/QUOTE is priced in QUOTE units per 1 BASE.
GBP/USD 1.33000 means 1 GBP costs 1.33 USD. Quantities are in BASE units.
A *pip* is 0.0001 for USD-quoted pairs and 0.01 for JPY-quoted pairs; prices
tick in tenths of a pip.
"""

from __future__ import annotations

from decimal import Decimal

from typing import Literal

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
                 initial_mid=Decimal("1.33000"), volatility_pips=Decimal("0.4")),
        PairSpec(symbol="EUR/USD", base="EUR", quote="USD", pip=Decimal("0.0001"), tick_size=Decimal("0.00001"),
                 initial_mid=Decimal("1.08500"), volatility_pips=Decimal("0.3")),
        PairSpec(symbol="USD/JPY", base="USD", quote="JPY", pip=Decimal("0.01"), tick_size=Decimal("0.001"),
                 initial_mid=Decimal("151.200"), volatility_pips=Decimal("0.5")),
    )
}


BookRole = Literal["a_book", "b_book", "c_book"]

# How a retail/institutional FX broker handles client orders. The simulated hedge fund is the
# broker's client; the broker's own trading desk runs the B-book and C-book.
ROLE_INFO: dict[str, dict[str, str]] = {
    "a_book": {
        "title": "A-book (straight through)",
        "who": "The broker passes your order straight to outside liquidity providers (banks).",
        "how": "The LPs take the other side. The broker carries no market risk and earns a fee. Deep liquidity, "
               "but you pay the LPs' spread plus the fee, wait for the round trip, and an LP may reject the fill on 'last look'.",
    },
    "b_book": {
        "title": "B-book (in-house)",
        "who": "The broker itself takes the other side of your trade: it bets against you.",
        "how": "Instant fills at a tight price, no fee. The broker profits when you lose and loses when you win, "
               "so it hedges its net exposure, here with British pound futures (CME 6B style, £62,500 per contract).",
    },
    "c_book": {
        "title": "C-book (hybrid)",
        "who": "A mix: the broker keeps part of your order on its own book and passes the rest to the LPs.",
        "how": "You get one price. Behind the scenes the broker keeps a set percentage of the risk and immediately "
               "offloads the rest to the A-book liquidity providers.",
    },
}


class BookConfig(BaseModel):
    """Hypothetical profile of one book (applies to every pair it lists)."""

    name: str = Field(pattern="^[ABC]$")
    role: BookRole
    description: str = ""
    spread_pips: Decimal = Field(Decimal("0.8"), ge=0, le=100, description="Quoted spread")
    price_offset_pips: Decimal = Field(Decimal(0), ge=-50, le=50, description="Shift of this book's mid vs. the market mid")
    fee_bps: Decimal = Field(Decimal(0), ge=0, le=50, description="Fee charged to the client, basis points of notional")
    latency_ms: int = Field(1, ge=0, le=5000, description="Simulated one-way latency used by the router and recorded on fills")
    # A-book: the liquidity providers' book
    levels: int = Field(5, ge=1, le=20, description="LP price levels per side")
    level_step_pips: Decimal = Field(Decimal("0.3"), gt=0, le=50, description="Distance between LP levels")
    qty_per_level: int = Field(2_000_000, ge=1000, le=100_000_000, description="LP quantity per level (base currency)")
    last_look_reject_pct: Decimal = Field(Decimal(0), ge=0, le=100, description="Chance (%) an LP rejects the fill on last look")
    # B-book and C-book: the broker's desk
    max_client_order: int = Field(3_000_000, ge=0, le=500_000_000, description="Largest client order this book accepts (base units)")
    keep_pct: Decimal = Field(Decimal(100), ge=0, le=100, description="Share of each client trade the broker keeps on its own book (C-book)")

    @model_validator(mode="after")
    def _lots(self) -> "BookConfig":
        for f in ("qty_per_level", "max_client_order"):
            if getattr(self, f) % 1000:
                raise ValueError(f"{f} must be a multiple of 1,000")
        if self.role == "b_book" and self.keep_pct != 100:
            raise ValueError("a B-book keeps 100% of the client's risk")
        return self

    @property
    def label(self) -> str:
        return f"Book {self.name}: {ROLE_INFO[self.role]['title']}"


DEFAULT_BOOKS: dict[str, BookConfig] = {
    "A": BookConfig(name="A", role="a_book", description=ROLE_INFO["a_book"]["who"], spread_pips=Decimal("0.8"), levels=5,
                    level_step_pips=Decimal("0.3"), qty_per_level=2_000_000, fee_bps=Decimal("0.20"), latency_ms=30),
    "B": BookConfig(name="B", role="b_book", description=ROLE_INFO["b_book"]["who"], spread_pips=Decimal("0.6"),
                    fee_bps=Decimal(0), latency_ms=1, max_client_order=3_000_000, keep_pct=Decimal(100)),
    "C": BookConfig(name="C", role="c_book", description=ROLE_INFO["c_book"]["who"], spread_pips=Decimal("0.7"),
                    fee_bps=Decimal(0), latency_ms=2, max_client_order=3_000_000, keep_pct=Decimal(50)),
}


class DeskConfig(BaseModel):
    """The broker's risk management for the B-book/C-book position."""

    hedge_threshold: int = Field(2_000_000, ge=0, le=500_000_000,
                                 description="Hedge GBP exposure with futures when it exceeds this (0 = only on request)")
    max_position: int = Field(20_000_000, ge=1000, le=1_000_000_000, description="Desk stops quoting a side beyond this position")


class RoutingWeights(BaseModel):
    include_fees: bool = True
    latency_penalty_bps_per_100ms: Decimal = Field(
        Decimal("0.1"), ge=0, le=100,
        description="Cost charged per 100 ms of book latency, in bps of price (a proxy for the risk the price moves while the order travels)",
    )
