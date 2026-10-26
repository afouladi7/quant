"""Order and trade models shared by every venue (market-maker book, FX books A/B/C)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    GTC = "gtc"  # rest until filled or canceled
    IOC = "ioc"  # execute what is available now, cancel the rest
    FOK = "fok"  # execute in full immediately or not at all


class OrderStatus(str, Enum):
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"

    @property
    def terminal(self) -> bool:
        return self in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED)


class Order(BaseModel):
    id: str
    venue: str
    instrument: str
    owner: str = Field(description="customer, synthetic, mm, lp, fund …")
    side: Side
    type: OrderType
    tif: TimeInForce
    quantity: int
    limit_price: Decimal | None = None
    filled_qty: int = 0
    avg_fill_price: Decimal | None = None
    notional_filled: Decimal = Decimal(0)
    fees: Decimal = Decimal(0)
    status: OrderStatus = OrderStatus.OPEN
    reason: str | None = None
    parent_id: str | None = None
    correlation_id: str | None = None
    client_order_id: str | None = None
    expires_tick: int | None = None
    created_ts: datetime
    updated_ts: datetime

    @property
    def remaining_qty(self) -> int:
        return self.quantity - self.filled_qty if not self.status.terminal else 0

    @property
    def unfilled_qty(self) -> int:
        return self.quantity - self.filled_qty


class Trade(BaseModel):
    id: str
    venue: str
    instrument: str
    price: Decimal
    quantity: int
    aggressor_side: Side = Field(description="Side of the incoming (taker) order")
    taker_order_id: str
    maker_order_id: str
    taker_owner: str
    maker_owner: str
    taker_fee: Decimal
    maker_fee: Decimal
    correlation_id: str | None = None
    ts: datetime
    tick: int
