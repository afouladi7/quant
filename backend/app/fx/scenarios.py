"""Reproducible FX routing scenarios (spec §6.5). GBP/USD mid is fixed at 1.27000 and the
simulation is paused, so every run produces identical prices and fills."""

from __future__ import annotations

from typing import Any


def _order(mode: str, qty: int, side: str = "buy", order_type: str = "market", limit: str | None = None, weights: dict | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"type": "order", "mode": mode, "quantity": qty, "side": side, "order_type": order_type}
    if limit:
        a["limit_price"] = limit
    if weights:
        a["weights"] = weights
    return a


SCENARIOS: dict[str, dict[str, Any]] = {
    s["id"]: s
    for s in (
        {
            "id": "1",
            "title": "Book A has the best price but little liquidity",
            "expect": "Book A shows the best offer (1.27003) but only 200,000 GBP at each price. A small order fills at the best "
                      "price; a larger one must 'walk the book' to worse prices.",
            "steps": [
                {"title": "Buy 200,000 GBP on Book A only", "action": _order("A", 200_000),
                 "observe": "Fully filled at Book A's best offer, 1.27003."},
                {"title": "Buy 500,000 GBP on Book A only", "action": _order("A", 500_000),
                 "observe": "Book A runs out at 1.27003 and 1.27008, so the last 100,000 fill at 1.27013. The average price is worse than the headline price."},
            ],
        },
        {
            "id": "2",
            "title": "Book B is deeper at a slightly worse price",
            "expect": "Book B's best offer (1.27005) is 0.2 pips worse than A's, but it has 1,000,000 GBP at that price, so a larger order can do better there.",
            "steps": [
                {"title": "Buy 500,000 GBP on Book B only", "action": _order("B", 500_000),
                 "observe": "All 500,000 fill at 1.27005 — one price, no walking."},
                {"title": "Same order on Book A only", "action": _order("A", 500_000),
                 "observe": "Book A's average price is about 1.27007: the 'better' book is worse for this size."},
            ],
        },
        {
            "id": "3",
            "title": "Book C is competitive but slow",
            "expect": "Book C quotes 1.27004 with the lowest fee, but its simulated latency is 45 ms. How much the router "
                      "penalises latency decides whether it uses C.",
            "steps": [
                {"title": "Smart-route 500,000 GBP, latency ignored", "action": _order("smart", 500_000, weights={"latency_penalty_bps_per_100ms": "0"}),
                 "observe": "With no latency penalty, Book C has the lowest cost after fees, so the router sends the order to C."},
                {"title": "Smart-route 500,000 GBP, latency penalised (1 bp per 100 ms)", "action": _order("smart", 500_000, weights={"latency_penalty_bps_per_100ms": "1"}),
                 "observe": "Now each 100 ms of latency costs 1 bp. C's effective price becomes the worst, so the router avoids it."},
            ],
        },
        {
            "id": "4",
            "title": "Smart routing splits one parent order",
            "expect": "A 1,000,000 GBP buy is larger than any single best level, so the router splits it into child orders across books, cheapest effective price first.",
            "steps": [
                {"title": "Smart-route a 1,000,000 GBP buy", "action": _order("smart", 1_000_000),
                 "observe": "One parent order becomes several child orders. Their fills add up exactly to the parent's quantity, and the parent's average price is the weighted average of the children."},
            ],
        },
        {
            "id": "5",
            "title": "A limit order rests until the market reaches it",
            "expect": "A buy limit at 1.26990 is below every offer, so nothing trades and the order waits in a book.",
            "steps": [
                {"title": "Buy 300,000 GBP with limit 1.26990 (smart)", "action": _order("smart", 300_000, order_type="limit", limit="1.26990"),
                 "observe": "No offer is at or below 1.26990, so the whole order rests as a limit order. Status: open."},
                {"title": "GBP/USD falls 2 pips", "action": {"type": "shift_mid", "pips": "-2", "refresh": False},
                 "observe": "Offers move down through 1.26990, so the resting order fills — at its own limit price, never worse."},
            ],
        },
        {
            "id": "6",
            "title": "A market order is only partially filled",
            "expect": "Book A holds 600,000 GBP in total. A 1,000,000 market order sent only to A cannot complete.",
            "steps": [
                {"title": "Market buy 1,000,000 GBP on Book A only", "action": _order("A", 1_000_000),
                 "observe": "600,000 fill across Book A's three levels; the remaining 400,000 are canceled (immediate-or-cancel), not left hanging."},
            ],
        },
    )
}
