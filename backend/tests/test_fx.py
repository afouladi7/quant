import random
from decimal import Decimal as D

from fastapi.testclient import TestClient

from app.fx.router import BookDepth, plan_route
from app.markets.models import Side


def books() -> list[BookDepth]:
    return [
        BookDepth("A", D("0.25"), 2, [(D("1.33003"), 200_000), (D("1.33008"), 200_000)]),
        BookDepth("B", D("0.20"), 5, [(D("1.33005"), 1_000_000)]),
        BookDepth("C", D("0.15"), 45, [(D("1.33004"), 500_000)]),
    ]


# ---- router (pure) -------------------------------------------------------------
def test_single_book_mode_uses_only_that_book() -> None:
    p = plan_route(Side.BUY, 300_000, None, books(), "A")
    assert [(a.book, a.quantity) for a in p.allocations] == [("A", 300_000)]
    assert p.allocations[0].worst_price == D("1.33008")
    assert p.expected_vwap == (D("1.33003") * 200_000 + D("1.33008") * 100_000) / 300_000


def test_smart_route_ranks_by_effective_price_and_splits() -> None:
    p = plan_route(Side.BUY, 1_000_000, None, books(), "smart", True, D("0.1"))
    assert {a.book: a.quantity for a in p.allocations} == {"A": 200_000, "C": 500_000, "B": 300_000}
    assert p.planned_qty == 1_000_000 and p.unfilled_qty == 0
    ranked = [c for c in p.candidates if c.rank]
    assert [c.rank for c in ranked] == sorted(c.rank for c in ranked)
    assert all(ranked[i].effective_price <= ranked[i + 1].effective_price for i in range(len(ranked) - 1))


def test_latency_penalty_changes_decision() -> None:
    cheap = plan_route(Side.BUY, 500_000, None, books(), "smart", True, D("0"))
    assert [a.book for a in cheap.allocations] == ["C"]
    slow = plan_route(Side.BUY, 500_000, None, books(), "smart", True, D("1"))
    assert "C" not in [a.book for a in slow.allocations]


def test_limit_respected_and_sell_side() -> None:
    p = plan_route(Side.BUY, 1_000_000, D("1.33004"), books(), "smart")
    assert all(lv[0] <= D("1.33004") for a in p.allocations for lv in a.levels)
    assert p.planned_qty == 700_000 and p.unfilled_qty == 300_000
    bids = [BookDepth("A", D("0.25"), 2, [(D("1.32997"), 200_000)]), BookDepth("B", D("0.2"), 5, [(D("1.32995"), 1_000_000)])]
    s = plan_route(Side.SELL, 500_000, D("1.32996"), bids, "smart")
    assert [(a.book, a.quantity) for a in s.allocations] == [("A", 200_000)] and s.unfilled_qty == 300_000


def test_no_liquidity_explained() -> None:
    p = plan_route(Side.BUY, 100_000, D("1.2"), books(), "smart")
    assert p.planned_qty == 0 and "no eligible liquidity" in p.explanation


# ---- service through the API ------------------------------------------------------
def run_scenario(client: TestClient, sid: str) -> list[dict]:
    assert client.post(f"/api/v1/fx/scenarios/{sid}/reset").status_code == 200
    out = []
    while (r := client.post(f"/api/v1/fx/scenarios/{sid}/step")).status_code == 200:
        out.append(r.json())
    assert r.json()["error"]["code"] == "scenario_complete"
    return out


def desk(client: TestClient) -> dict:
    return client.get("/api/v1/fx/state").json()["desk"]


def desk_pos(client: TestClient) -> int:
    return next((p["position"] for p in desk(client)["pairs"] if p["pair"] == "GBP/USD"), 0)


def test_scenarios_produce_documented_outcomes(client: TestClient) -> None:
    s1 = run_scenario(client, "1")[0]["parent"]
    assert (s1["vwap"], s1["total_fees"]) == ("1.3300400", "26.60") and desk_pos(client) == 0  # A-book: no broker risk

    s2 = run_scenario(client, "2")
    assert s2[0]["parent"]["vwap"] == "1.3300300" and s2[0]["parent"]["total_fees"] == "0.00"
    assert desk_pos(client) == -1_000_000 and D(desk(client)["total_pnl_usd"]) == D("330.00")  # client lost, broker gained

    run_scenario(client, "3")
    d = desk(client)
    assert d["futures"]["contracts"] == 16 and d["gbp_exposure"] == 0  # 16 × £62,500 = £1,000,000
    assert D(d["total_pnl_usd"]) == D("-602.00")  # unchanged by the final +5 pip move: the hedge offsets it

    s4 = run_scenario(client, "4")[0]["parent"]
    assert s4["filled_qty"] == 1_000_000 and desk_pos(client) == -500_000  # kept 50%, passed 50% to the LPs
    detail = client.get(f"/api/v1/fx/orders/{s4['id']}").json()
    assert sum(t["quantity"] for t in detail["desk_trades"]) == 500_000

    s5 = run_scenario(client, "5")
    assert s5[0]["parent"]["children"][0]["status"] == "rejected" and s5[0]["parent"]["filled_qty"] == 0
    assert [c["book"] for c in s5[1]["parent"]["children"]] == ["B"] and s5[1]["parent"]["status"] == "filled"

    s6 = run_scenario(client, "6")[0]["parent"]
    assert {c["book"]: c["filled_qty"] for c in s6["children"]} == {"A": 500_000, "B": 500_000, "C": 1_000_000}

    s7 = run_scenario(client, "7")
    assert s7[0]["parent"]["status"] == "open"
    filled = client.get(f"/api/v1/fx/orders/{s7[0]['parent']['id']}").json()
    assert filled["parent"]["status"] == "filled" and {t["price"] for t in filled["trades"]} == {"1.32990"}

    s8 = run_scenario(client, "8")[0]["parent"]
    assert (s8["status"], s8["filled_qty"], s8["unfilled_qty"]) == ("canceled", 500_000, 500_000)


def test_b_book_mirrors_the_client_and_auto_hedges_with_futures(client: TestClient) -> None:
    client.post("/api/v1/fx/reset")
    client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 1_000_000, "routing_mode": "B"})
    assert desk_pos(client) == -1_000_000 and desk(client)["futures"]["contracts"] == 0  # below the 2,000,000 threshold
    client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 1_500_000, "routing_mode": "B"})
    d = desk(client)
    assert desk_pos(client) == -2_500_000 and d["futures"]["contracts"] == 40  # auto hedge: 2.5m / 62,500
    assert d["gbp_exposure"] == 0


def test_desk_hedge_endpoint(client: TestClient) -> None:
    client.post("/api/v1/fx/reset")
    client.post("/api/v1/fx/orders", json={"side": "sell", "quantity": 1_030_000, "routing_mode": "B"})
    r = client.post("/api/v1/fx/desk/hedge", json={"pair": "GBP/USD"}).json()
    assert r["before"] == 1_030_000 and r["after"] == 30_000  # 16 contracts sold, £30,000 left over (whole contracts)


def reconcile(client: TestClient, parent: dict) -> None:
    detail = client.get(f"/api/v1/fx/orders/{parent['id']}").json()
    p, trades = detail["parent"], detail["trades"]
    assert p["filled_qty"] == sum(c["filled_qty"] for c in p["children"]) == sum(t["quantity"] for t in trades)
    assert D(p["total_fees"]) == sum(D(c["fees"]) for c in p["children"]) == sum(D(t["taker_fee"] if t["taker_owner"] == "fund" else t["maker_fee"]) for t in trades)
    if p["filled_qty"]:
        notional = sum(D(t["price"]) * t["quantity"] for t in trades)
        assert D(p["vwap"]) == (notional / p["filled_qty"]).quantize(D("0.0000001"))
    assert p["filled_qty"] + p["unfilled_qty"] == p["quantity"]
    if p["limit_price"]:
        lim = D(p["limit_price"])
        assert all((D(t["price"]) <= lim) if p["side"] == "buy" else (D(t["price"]) >= lim) for t in trades)


def test_random_orders_always_reconcile(client: TestClient) -> None:
    rng = random.Random(5)
    client.post("/api/v1/simulation/reset", json={"seed": 3})
    for i in range(40):
        side = rng.choice(["buy", "sell"])
        mid = D(client.get("/api/v1/fx/state").json()["mid"])
        body = {"pair": "GBP/USD", "side": side, "quantity": rng.randrange(1, 300) * 10_000, "routing_mode": rng.choice(["A", "B", "C", "smart"])}
        if rng.random() < 0.5:
            off = D(rng.randint(-8, 8)) * D("0.00001")
            body |= {"type": "limit", "limit_price": str(mid + off)}
        r = client.post("/api/v1/fx/orders", json=body)
        assert r.status_code == 201, r.text
        reconcile(client, r.json()["parent"])
        if i % 5 == 0:
            client.post("/api/v1/simulation/advance", json={"ticks": 3})
    for p in client.get("/api/v1/fx/orders", params={"limit": 100}).json():
        reconcile(client, p)


def test_books_are_independent(client: TestClient) -> None:
    client.post("/api/v1/fx/scenarios/8/reset")
    before = {n: client.get(f"/api/v1/fx/books/{n}").json() for n in "ABC"}
    client.post("/api/v1/fx/scenarios/8/step")  # 500,000 traded on the B-book only
    after = {n: client.get(f"/api/v1/fx/books/{n}").json() for n in "ABC"}
    assert after["A"]["asks"] == before["A"]["asks"] and after["A"]["recent_trades"] == []
    assert after["B"]["recent_trades"] and not after["C"]["recent_trades"]
    cfg = after["C"]["config"] | {"keep_pct": "25"}
    assert client.put("/api/v1/fx/books/C/config", json=cfg).status_code == 200
    assert client.get("/api/v1/fx/books/B").json()["config"]["keep_pct"] == "100"
    bad = after["B"]["config"] | {"keep_pct": "50"}
    assert client.put("/api/v1/fx/books/B/config", json=bad).status_code == 422  # a B-book keeps all the risk


def test_fx_validation_and_idempotency(client: TestClient) -> None:
    bad = client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 1500})
    assert bad.status_code == 422 and "multiple" in bad.json()["error"]["message"]
    assert client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 1000, "pair": "XXX/YYY"}).status_code == 404
    h = {"Idempotency-Key": "fx-1"}
    body = {"side": "buy", "quantity": 100_000}
    a = client.post("/api/v1/fx/orders", json=body, headers=h).json()
    b = client.post("/api/v1/fx/orders", json=body, headers=h).json()
    assert b["idempotent_replay"] and a["parent"]["id"] == b["parent"]["id"]
    assert len(client.get("/api/v1/fx/orders").json()) == 1
