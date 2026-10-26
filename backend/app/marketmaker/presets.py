"""Deterministic guided demo presets for the market-maker module (spec §13, presets 1–2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Step:
    title: str
    action: dict[str, Any]
    observe: str


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    summary: str
    seed: int
    config: dict[str, Any]
    steps: tuple[Step, ...] = field(default_factory=tuple)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "seed": self.seed,
            "config": self.config,
            "steps": [{"title": s.title, "action": s.action, "observe": s.observe} for s in self.steps],
        }


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        Preset(
            id="spread-capture",
            title="Spread Capture",
            summary=(
                "The market maker buys at its bid ($99.95) and sells at its ask ($100.05). Each round trip earns "
                "the $0.10 spread per share before fees — until the market price moves against an open position."
            ),
            seed=1,
            config={
                "fair_value": Decimal("100.00"),
                "spread": Decimal("0.10"),
                "quote_size": 100,
                "quote_levels": 1,
                "inventory_sensitivity": Decimal("0"),
                "volatility": Decimal("0"),
                "arrival_rate": Decimal("0"),
                "fee_per_share": Decimal("0.005"),
                "max_inventory": 1000,
            },
            steps=(
                Step(
                    "A customer sells 100 shares at market",
                    {"type": "customer_order", "side": "sell", "quantity": 100},
                    "The customer's sell meets the market maker's bid. The market maker BUYS 100 at $99.95. "
                    "Inventory is now +100; nothing is realized yet, but marked at $100.00 the position shows +$5 unrealized.",
                ),
                Step(
                    "A customer buys 100 shares at market",
                    {"type": "customer_order", "side": "buy", "quantity": 100},
                    "The market maker SELLS 100 at $100.05. Inventory is back to 0 and the round trip realized "
                    "$10.00 (100 × $0.10). Fees were $0.50 per trade, so net P&L is $9.00 — gross spread capture is not net profit.",
                ),
                Step(
                    "Another customer sells 100 shares",
                    {"type": "customer_order", "side": "sell", "quantity": 100},
                    "The market maker buys again at $99.95 and is long 100 shares. It is now exposed to the price moving.",
                ),
                Step(
                    "Bad news: fair value falls by $0.30",
                    {"type": "shift_fair", "amount": "-0.30"},
                    "Quotes move down to $99.65 / $99.75. The 100 shares bought at $99.95 are now worth $99.70 each: "
                    "an unrealized loss of $25, wiping out the earlier spread profit. Capturing the spread does not guarantee a profit.",
                ),
                Step(
                    "A customer buys 100 at market",
                    {"type": "customer_order", "side": "buy", "quantity": 100},
                    "The market maker sells at its new ask $99.75. It still captured $0.05/share versus the new fair value, "
                    "but realized a $20 loss on the position because it bought before the price fell.",
                ),
            ),
        ),
        Preset(
            id="inventory-risk",
            title="Inventory Risk",
            summary=(
                "Customers keep buying (85% of orders). The market maker keeps selling, its inventory goes short, "
                "and its quoting logic raises prices to slow the selling and attract sellers."
            ),
            seed=7,
            config={
                "fair_value": Decimal("100.00"),
                "spread": Decimal("0.10"),
                "quote_size": 100,
                "quote_levels": 2,
                "max_inventory": 1000,
                "inventory_sensitivity": Decimal("1.0"),
                "volatility": Decimal("0.01"),
                "arrival_rate": Decimal("0.5"),
                "buy_probability": Decimal("0.85"),
                "limit_order_fraction": Decimal("0"),
                "customer_order_size": 100,
                "fee_per_share": Decimal("0.005"),
            },
            steps=(
                Step(
                    "Run 10 seconds of customer flow",
                    {"type": "advance", "ticks": 10},
                    "Most customer orders are buys, so the market maker sells and its inventory turns negative (short). "
                    "Watch the skew: quotes rise above fair value.",
                ),
                Step(
                    "Run 20 more seconds",
                    {"type": "advance", "ticks": 20},
                    "Inventory reaches the -1,000 share limit. The market maker stops offering shares (no ask at all), "
                    "and its bid now sits above fair value, paying up to attract sellers who would reduce its short position.",
                ),
                Step(
                    "Run 30 more seconds",
                    {"type": "advance", "ticks": 30},
                    "With no offer from the market maker, customer buy orders find no liquidity and are canceled, so inventory "
                    "stays pinned at the limit. Every cent fair value rises now costs $10 on the short position: inventory is risk.",
                ),
            ),
        ),
    )
}
