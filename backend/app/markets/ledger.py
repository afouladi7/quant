"""Position ledger with FIFO lot accounting, in exact Decimal arithmetic.

Conventions (see docs/finance-guide.md):
- A buy of q at price p: cash -= q*p, position += q.  A sell: cash += q*p, position -= q.
- Fees are paid in cash and accumulated separately.
- Realized P&L: when a trade reduces an open position, the closed quantity is
  matched against the oldest open lots first (FIFO):
      long lot closed by a sell:  (sell_price - lot_price) * q
      short lot closed by a buy:  (lot_price - buy_price) * q
- Unrealized P&L marks every open lot at a reference (mark) price:
      sum(lot_qty * (mark - lot_price))   (lot_qty negative for shorts)
- Reconciliation identity (tested):
      cash + position*mark - initial_cash == realized + unrealized - fees
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import ZERO
from app.markets.models import Side


@dataclass
class Lot:
    quantity: int  # signed: + long, - short
    price: Decimal


@dataclass
class PositionLedger:
    initial_cash: Decimal = ZERO
    cash: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    gross_spread_captured: Decimal = ZERO
    traded_quantity: int = 0
    buy_quantity: int = 0
    sell_quantity: int = 0
    trade_count: int = 0
    lots: deque[Lot] = field(default_factory=deque)

    @classmethod
    def with_cash(cls, cash: Decimal) -> "PositionLedger":
        return cls(initial_cash=cash, cash=cash)

    @property
    def position(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    @property
    def cost_basis(self) -> Decimal:
        return sum((lot.price * lot.quantity for lot in self.lots), ZERO)

    @property
    def avg_cost(self) -> Decimal | None:
        pos = self.position
        return None if pos == 0 else self.cost_basis / pos

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        return sum((lot.quantity * (mark - lot.price) for lot in self.lots), ZERO)

    def equity(self, mark: Decimal) -> Decimal:
        return self.cash + self.position * mark

    def net_pnl(self, mark: Decimal) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl(mark) - self.fees

    def apply(self, side: Side, quantity: int, price: Decimal, fee: Decimal = ZERO, reference: Decimal | None = None) -> Decimal:
        """Apply one fill; returns the realized P&L produced by this fill."""
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")
        signed = side.sign * quantity
        self.cash -= signed * price
        self.cash -= fee
        self.fees += fee
        self.trade_count += 1
        self.traded_quantity += quantity
        if side is Side.BUY:
            self.buy_quantity += quantity
        else:
            self.sell_quantity += quantity
        if reference is not None:
            # Edge versus the reference price: positive when buying below / selling above it.
            self.gross_spread_captured += (reference - price) * signed

        realized = ZERO
        remaining = signed
        while remaining != 0 and self.lots and (self.lots[0].quantity > 0) != (remaining > 0):
            lot = self.lots[0]
            closed = min(abs(remaining), abs(lot.quantity))
            if lot.quantity > 0:  # closing long with a sell
                realized += (price - lot.price) * closed
                lot.quantity -= closed
                remaining += closed
            else:  # closing short with a buy
                realized += (lot.price - price) * closed
                lot.quantity += closed
                remaining -= closed
            if lot.quantity == 0:
                self.lots.popleft()
        if remaining != 0:
            self.lots.append(Lot(remaining, price))
        self.realized_pnl += realized
        return realized

    def snapshot(self, mark: Decimal) -> dict:
        unreal = self.unrealized_pnl(mark)
        return {
            "position": self.position,
            "avg_cost": self.avg_cost,
            "cost_basis": self.cost_basis,
            "cash": self.cash,
            "initial_cash": self.initial_cash,
            "mark_price": mark,
            "market_value": self.position * mark,
            "equity": self.equity(mark),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": unreal,
            "fees": self.fees,
            "gross_pnl": self.realized_pnl + unreal,
            "net_pnl": self.realized_pnl + unreal - self.fees,
            "gross_spread_captured": self.gross_spread_captured,
            "trade_count": self.trade_count,
            "traded_quantity": self.traded_quantity,
            "buy_quantity": self.buy_quantity,
            "sell_quantity": self.sell_quantity,
            "open_lots": [{"quantity": lot.quantity, "price": lot.price} for lot in self.lots],
        }
