"""Smart order router (pure function: depth snapshots in, routing plan out).

Every resting price level on every eligible book becomes a candidate. Each
candidate's *effective price* adds the costs the objective is told to care about:

    effective = price × (1 + s × (fee_bps + latency_bps) / 10,000)
    latency_bps = latency_penalty_bps_per_100ms × latency_ms / 100
    s = +1 for buys (costs raise what we pay), −1 for sells (costs reduce what we receive)

Candidates are ranked best-first (buys: lowest effective price; sells: highest),
ties broken by lower latency then book name, and quantity is allocated greedily
until the order is complete or eligible liquidity runs out. A limit price is
enforced on the *raw* execution price, so no child can ever trade through it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.markets.models import Side

TEN_K = Decimal(10_000)


@dataclass(frozen=True)
class BookDepth:
    book: str
    fee_bps: Decimal
    latency_ms: int
    levels: list[tuple[Decimal, int]]  # maker side, best first: (price, qty)
    label: str = ""  # e.g. "Book B (in-house book)" for explanations


@dataclass
class Candidate:
    book: str
    price: Decimal
    available: int
    fee_bps: Decimal
    latency_ms: int
    effective_price: Decimal
    rank: int = 0
    allocated: int = 0
    eligible: bool = True
    note: str = ""


@dataclass
class Allocation:
    book: str
    quantity: int
    worst_price: Decimal
    levels: list[tuple[Decimal, int]] = field(default_factory=list)


@dataclass
class RoutingPlan:
    side: Side
    quantity: int
    limit_price: Decimal | None
    mode: str
    include_fees: bool
    latency_penalty_bps_per_100ms: Decimal
    candidates: list[Candidate]
    allocations: list[Allocation]
    planned_qty: int
    expected_vwap: Decimal | None
    unfilled_qty: int
    explanation: str


def effective_price(side: Side, price: Decimal, fee_bps: Decimal, latency_ms: int, include_fees: bool, penalty: Decimal) -> Decimal:
    cost_bps = (fee_bps if include_fees else Decimal(0)) + penalty * Decimal(latency_ms) / Decimal(100)
    return price * (1 + side.sign * cost_bps / TEN_K)


def plan_route(
    side: Side,
    quantity: int,
    limit_price: Decimal | None,
    books: list[BookDepth],
    mode: str,
    include_fees: bool = True,
    latency_penalty_bps_per_100ms: Decimal = Decimal("0.1"),
) -> RoutingPlan:
    eligible_books = {b.book for b in books} if mode == "smart" else {mode}
    cands: list[Candidate] = []
    for b in books:
        for price, qty in b.levels:
            c = Candidate(
                book=b.book, price=price, available=qty, fee_bps=b.fee_bps, latency_ms=b.latency_ms,
                effective_price=effective_price(side, price, b.fee_bps, b.latency_ms, include_fees, latency_penalty_bps_per_100ms),
            )
            if b.book not in eligible_books:
                c.eligible, c.note = False, f"not selected (routing to Book {mode} only)"
            elif limit_price is not None and ((side is Side.BUY and price > limit_price) or (side is Side.SELL and price < limit_price)):
                c.eligible, c.note = False, f"beyond limit {limit_price}"
            cands.append(c)

    ordered = sorted(
        cands,
        key=lambda c: ((c.effective_price if side is Side.BUY else -c.effective_price), c.latency_ms, c.book),
    )
    remaining = quantity
    allocs: dict[str, Allocation] = {}
    rank = 0
    for c in ordered:
        if not c.eligible:
            continue
        rank += 1
        c.rank = rank
        if remaining == 0:
            c.note = "not needed"
            continue
        take = min(remaining, c.available)
        c.allocated = take
        remaining -= take
        a = allocs.setdefault(c.book, Allocation(c.book, 0, c.price))
        a.quantity += take
        a.levels.append((c.price, take))
        if (side is Side.BUY and c.price > a.worst_price) or (side is Side.SELL and c.price < a.worst_price):
            a.worst_price = c.price
        c.note = "fully used" if take == c.available else f"partly used ({take:,} of {c.available:,})"

    planned = quantity - remaining
    notional = sum((p * q for a in allocs.values() for p, q in a.levels), Decimal(0))
    vwap = (notional / planned) if planned else None
    plan = RoutingPlan(
        side=side, quantity=quantity, limit_price=limit_price, mode=mode, include_fees=include_fees,
        latency_penalty_bps_per_100ms=latency_penalty_bps_per_100ms,
        candidates=sorted(cands, key=lambda c: (not c.eligible, c.rank or 10**9, c.book)),
        allocations=sorted(allocs.values(), key=lambda a: a.book), planned_qty=planned, expected_vwap=vwap,
        unfilled_qty=remaining, explanation="",
    )
    plan.explanation = explain(plan, books)
    return plan


def explain(plan: RoutingPlan, books: list[BookDepth]) -> str:
    names = {b.book: (b.label or f"Book {b.book}") for b in books}
    side_word = "buy" if plan.side is Side.BUY else "sell"
    if not plan.allocations:
        why = "no eligible liquidity" + (f" at or better than the limit {plan.limit_price}" if plan.limit_price is not None else "")
        return f"Nothing could be routed to {'any book' if plan.mode == 'smart' else names.get(plan.mode, 'Book ' + plan.mode)}: {why}."
    parts = [f"{a.quantity:,} to {names[a.book]}" for a in plan.allocations]
    text = f"To {side_word} {plan.quantity:,}, the router sent " + ", ".join(parts) + "."
    if plan.mode == "smart" and len(plan.allocations) > 1:
        first = next(c for c in plan.candidates if c.rank == 1)
        depth_first = sum(c.available for c in plan.candidates if c.book == first.book and c.eligible and c.effective_price == first.effective_price)
        text += (
            f" {names[first.book]} had the best effective price ({first.price} raw, {first.effective_price.quantize(Decimal('0.0000001'))} after "
            f"{'fees and ' if plan.include_fees else ''}latency) but only {depth_first:,} available there, so the order was split."
        )
    elif plan.mode == "smart":
        text += f" {names[plan.allocations[0].book]} could fill it at the best effective price."
    if plan.mode == "smart":
        used = {a.book for a in plan.allocations}
        worst_used = max(a.worst_price for a in plan.allocations) if plan.side is Side.BUY else min(a.worst_price for a in plan.allocations)
        skipped = []
        for b in sorted({c.book for c in plan.candidates if c.eligible} - used):
            best = next(c for c in plan.candidates if c.book == b and c.eligible)
            better_raw = best.price < worst_used if plan.side is Side.BUY else best.price > worst_used
            if better_raw:
                skipped.append(f"{names[b]} (raw {best.price}, but {best.effective_price.quantize(Decimal('0.0000001'))} after costs)")
        if skipped:
            text += " Skipped despite a better raw price: " + "; ".join(skipped) + "."
    if plan.unfilled_qty:
        text += f" {plan.unfilled_qty:,} could not be placed against current liquidity."
    return text
