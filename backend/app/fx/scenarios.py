"""Reproducible FX scenarios (spec §6.5), built around how a broker handles client orders:
A-book (pass to liquidity providers), B-book (the broker takes the other side) and
C-book (a hybrid). GBP/USD starts at 1.33000 and the simulation clock is paused.

Default quotes at mid 1.33000: A-book LPs 1.32996 / 1.33004 (+0.2 bp fee, 30 ms),
B-book desk 1.32997 / 1.33003, C-book desk 1.32996 / 1.33004 (no fee).
"""

from __future__ import annotations

from typing import Any


def _order(mode: str, qty: int, side: str = "buy", order_type: str = "market", limit: str | None = None) -> dict[str, Any]:
    a: dict[str, Any] = {"type": "order", "mode": mode, "quantity": qty, "side": side, "order_type": order_type}
    if limit:
        a["limit_price"] = limit
    return a


NO_AUTO_HEDGE = {"hedge_threshold": 0}

SCENARIOS: dict[str, dict[str, Any]] = {
    s["id"]: s
    for s in (
        {
            "id": "1",
            "title": "A-book: straight through to the liquidity providers",
            "expect": "The broker passes the fund's order to outside banks. They take the other side; the broker only earns its fee and carries no risk.",
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 1,000,000 GBP on Book A (A-book)", "action": _order("A", 1_000_000),
                 "observe": "Filled at the LPs' offer, 1.33004, plus a 0.2 bp fee (about $27). The broker's desk position stays at zero."},
            ],
        },
        {
            "id": "2",
            "title": "B-book: the broker bets against the client",
            "expect": "On the B-book the broker itself sells to the fund. If GBP then falls, the fund loses and the broker gains the same amount.",
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 1,000,000 GBP on Book B (B-book)", "action": _order("B", 1_000_000),
                 "observe": "Filled instantly at 1.33003 with no fee. The desk is now short 1,000,000 GBP: the mirror image of the fund."},
                {"title": "GBP/USD falls 3 pips", "action": {"type": "shift_mid", "pips": "-3", "refresh": False},
                 "observe": "The fund is losing on its pounds and the broker is gaining about $330 on its short. This is why brokers like B-booking clients who tend to lose."},
            ],
        },
        {
            "id": "3",
            "title": "B-book risk: the client is right, the broker hedges with 6B futures",
            "expect": "If the client keeps winning, the B-book loses. The desk protects itself by buying British pound futures (6B style, £62,500 each).",
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 1,000,000 GBP on Book B (B-book)", "action": _order("B", 1_000_000),
                 "observe": "The desk is short 1,000,000 GBP against the fund."},
                {"title": "GBP/USD rises 5 pips", "action": {"type": "shift_mid", "pips": "5", "refresh": False},
                 "observe": "The fund was right: the broker is now losing about $470 on its short."},
                {"title": "Desk hedges with 6B futures", "action": {"type": "desk_hedge"},
                 "observe": "The desk buys 16 futures (16 × £62,500 = £1,000,000). Its GBP exposure is now about zero."},
                {"title": "GBP/USD rises another 5 pips", "action": {"type": "shift_mid", "pips": "5", "refresh": False},
                 "observe": "The short spot position loses about $500 more, but the futures gain about the same, so the desk's total barely moves."},
            ],
        },
        {
            "id": "4",
            "title": "C-book: keep half, pass half to the liquidity providers",
            "expect": "On the C-book the broker sells the whole order to the fund at one price, then immediately buys half of it back from the LPs.",
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 1,000,000 GBP on Book C (C-book, keeps 50%)", "action": _order("C", 1_000_000),
                 "observe": "The fund gets one fill of 1,000,000 at 1.33004. Behind the scenes the desk bought 500,000 from the LPs, so it is only short 500,000: half the risk of a B-book trade."},
            ],
        },
        {
            "id": "5",
            "title": "Last look: a liquidity provider rejects the fill",
            "expect": "On the A-book, LPs may decline a trade during the round trip if the price moved (last look). Here they reject every time.",
            "books": {"A": {"last_look_reject_pct": "100"}},
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 500,000 GBP on Book A only", "action": _order("A", 500_000),
                 "observe": "The LP rejects the fill. Nothing trades: last look is a real cost of A-book liquidity."},
                {"title": "Same order with smart routing", "action": _order("smart", 500_000),
                 "observe": "The router prefers the broker's own books, which have no last look, so the order fills on the B-book."},
            ],
        },
        {
            "id": "6",
            "title": "Smart routing splits one order across A, B and C",
            "expect": "The B-book accepts up to 500,000 and the C-book up to 1,000,000, so a 2,000,000 buy needs all three books.",
            "books": {"B": {"max_client_order": 500_000}, "C": {"max_client_order": 1_000_000}},
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Smart-route a 2,000,000 GBP buy", "action": _order("smart", 2_000_000),
                 "observe": "The cheapest book fills first: 500,000 on the B-book, 1,000,000 on the C-book, and the last 500,000 goes to the A-book LPs. The fills add up exactly to the parent order."},
            ],
        },
        {
            "id": "7",
            "title": "A limit order rests until the market reaches it",
            "expect": "A buy limit at 1.32990 is below every offer, so it waits on the liquidity providers' book.",
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Buy 300,000 GBP with limit 1.32990 (smart)", "action": _order("smart", 300_000, order_type="limit", limit="1.32990"),
                 "observe": "No book offers 1.32990 or lower, so the order rests. Status: open."},
                {"title": "GBP/USD falls 2 pips", "action": {"type": "shift_mid", "pips": "-2", "refresh": False},
                 "observe": "The LPs' offers move down through 1.32990, so the resting order fills at its own limit price, never worse."},
            ],
        },
        {
            "id": "8",
            "title": "A market order is only partly filled",
            "expect": "The B-book accepts at most 500,000. A 1,000,000 market order sent only to the B-book cannot complete.",
            "books": {"B": {"max_client_order": 500_000}},
            "desk": NO_AUTO_HEDGE,
            "steps": [
                {"title": "Market buy 1,000,000 GBP on Book B only", "action": _order("B", 1_000_000),
                 "observe": "500,000 fill; the other 500,000 is canceled (immediate-or-cancel) rather than left waiting."},
            ],
        },
    )
}
