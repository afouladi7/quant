"""Exact price/money helpers.

Prices are ``Decimal``; inside order books they become integer *ticks*
(price / tick_size) so comparisons and price-time priority are exact.
Binary floating point is never used for accounting.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Literal

ZERO = Decimal(0)
_ROUNDING = {"down": ROUND_FLOOR, "up": ROUND_CEILING, "nearest": ROUND_HALF_EVEN}


def dec(value: object) -> Decimal:
    """Convert to Decimal via ``str`` so floats do not leak binary artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def is_on_tick(price: Decimal, tick: Decimal) -> bool:
    return (price % tick) == 0


def to_ticks(price: Decimal, tick: Decimal) -> int:
    if not is_on_tick(price, tick):
        raise ValueError(f"price {price} is not a multiple of tick size {tick}")
    return int(price / tick)


def from_ticks(ticks: int, tick: Decimal) -> Decimal:
    return (Decimal(ticks) * tick).quantize(tick)


def round_to_tick(price: Decimal, tick: Decimal, mode: Literal["down", "up", "nearest"] = "nearest") -> Decimal:
    return ((price / tick).to_integral_value(rounding=_ROUNDING[mode]) * tick).quantize(tick)


def ticks_round(price: Decimal, tick: Decimal, mode: Literal["down", "up", "nearest"] = "nearest") -> int:
    return int((price / tick).to_integral_value(rounding=_ROUNDING[mode]))


def money(value: Decimal, places: str = "0.01") -> Decimal:
    """Round a monetary amount for display/settlement (half-up)."""
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
