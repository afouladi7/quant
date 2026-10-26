from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MMConfig(BaseModel):
    """Market-maker teaching model parameters. All validated; nonsense is rejected."""

    fair_value: Decimal = Field(Decimal("100.00"), gt=0, le=Decimal("100000"), description="Starting reference price ($)")
    spread: Decimal = Field(Decimal("0.10"), gt=0, le=Decimal("100"), description="Target quoted spread ($)")
    quote_size: int = Field(100, ge=1, le=100_000, description="Shares offered at each quote level")
    quote_levels: int = Field(1, ge=1, le=10, description="Price levels quoted on each side")
    level_step_ticks: int = Field(1, ge=1, le=100, description="Ticks between quote levels")
    max_inventory: int = Field(1000, ge=1, le=1_000_000, description="Absolute inventory limit (shares)")
    inventory_sensitivity: Decimal = Field(
        Decimal("1.0"), ge=0, le=10, description="Skew strength: at full inventory, quotes shift by sensitivity × spread"
    )
    volatility: Decimal = Field(Decimal("0.02"), ge=0, le=10, description="Std. dev. of fair-value change per tick ($)")
    arrival_rate: Decimal = Field(Decimal("0.5"), ge=0, le=20, description="Mean synthetic customer orders per tick")
    buy_probability: Decimal = Field(Decimal("0.5"), ge=0, le=1, description="Probability a synthetic order is a buy")
    limit_order_fraction: Decimal = Field(Decimal("0.2"), ge=0, le=1, description="Share of synthetic orders that are limit orders")
    customer_order_size: int = Field(100, ge=1, le=100_000, description="Typical synthetic order size")
    synthetic_limit_ttl_ticks: int = Field(20, ge=1, le=10_000, description="Synthetic limit orders expire after this many ticks")
    fee_per_share: Decimal = Field(Decimal("0.005"), ge=0, le=1, description="Venue fee per share, charged to each side")
    tick_size: Decimal = Field(Decimal("0.01"), gt=0, le=1, description="Minimum price increment")
    lot_size: int = Field(1, ge=1, le=1000, description="Order quantities must be multiples of this")
    max_order_qty: int = Field(100_000, ge=1, le=1_000_000)
    market_order_policy: Literal["ioc", "fok"] = Field(
        "ioc", description="Unfilled market-order remainder: ioc = cancel the rest, fok = all-or-nothing"
    )
    initial_cash: Decimal = Field(Decimal("1000000"), ge=0, le=Decimal("1000000000"))

    @model_validator(mode="after")
    def _check(self) -> "MMConfig":
        if self.spread < self.tick_size:
            raise ValueError("spread must be at least one tick")
        if (self.fair_value % self.tick_size) != 0:
            raise ValueError("fair_value must be a multiple of tick_size")
        for name in ("quote_size", "customer_order_size"):
            if getattr(self, name) % self.lot_size:
                raise ValueError(f"{name} must be a multiple of lot_size")
        if self.quote_size > self.max_inventory:
            raise ValueError("quote_size cannot exceed max_inventory")
        return self
