import random
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.marketmaker.config import MMConfig
from app.marketmaker.quoting import compute_quote
from app.markets.models import Side


# ---- quote engine -----------------------------------------------------------
def test_flat_inventory_quotes_around_fair() -> None:
    q = compute_quote(MMConfig(), D("100.00"), 0)
    assert (q.bid, q.ask) == (D("99.95"), D("100.05"))
    assert q.skew == 0 and q.bids[0].size == 100


def test_long_inventory_skews_quotes_down_short_up() -> None:
    cfg = MMConfig(inventory_sensitivity=D("1"), max_inventory=1000)
    long_q = compute_quote(cfg, D("100"), 500)   # skew = -1 * 0.5 * 0.10 = -0.05
    short_q = compute_quote(cfg, D("100"), -500)
    assert long_q.skew == D("-0.05") and (long_q.bid, long_q.ask) == (D("99.90"), D("100.00"))
    assert (short_q.bid, short_q.ask) == (D("100.00"), D("100.10"))


def test_quotes_respect_tick_and_inventory_limit() -> None:
    cfg = MMConfig(tick_size=D("0.05"), fair_value=D("100.00"), spread=D("0.07"), quote_levels=3, quote_size=300, max_inventory=1000)
    q = compute_quote(cfg, D("100.0123"), 900)
    for lv in q.bids + q.asks:
        assert lv.price % D("0.05") == 0 and lv.size > 0
    assert sum(lv.size for lv in q.bids) <= 100  # only 100 shares of buying capacity left
    assert compute_quote(cfg, D("100"), 1000).bids == []
    assert compute_quote(cfg, D("100"), -1000).asks == []
    assert all(b.price < a.price for b in q.bids for a in q.asks)


def test_config_validation() -> None:
    for bad in ({"spread": "0.001"}, {"fair_value": "100.005"}, {"quote_size": 2000}, {"lot_size": 10, "quote_size": 15}, {"buy_probability": "1.5"}):
        with pytest.raises(ValidationError):
            MMConfig(**bad)


# ---- service through the API --------------------------------------------------
def test_spread_capture_preset_exact_numbers(client: TestClient) -> None:
    assert client.post("/api/v1/mm/presets/spread-capture/load").status_code == 200
    expected = [
        # (position, realized, fees, unrealized)
        (100, "0", "0.50", "5.00"),
        (0, "10.00", "1.00", "0"),
        (100, "10.00", "1.50", "5.00"),
        (100, "10.00", "1.50", "-25.00"),
        (0, "-10.00", "2.00", "0"),
    ]
    for pos, realized, fees, unreal in expected:
        step = client.post("/api/v1/mm/presets/spread-capture/step").json()
        led = client.get("/api/v1/mm/ledger").json()
        assert led["position"] == pos, step["title"]
        assert D(led["realized_pnl"]) == D(realized)
        assert D(led["fees"]) == D(fees)
        assert D(led["unrealized_pnl"]) == D(unreal)
    assert D(led["gross_spread_captured"]) == D("20.00")
    assert D(led["net_pnl"]) == D("-12.00")
    assert client.post("/api/v1/mm/presets/spread-capture/step").status_code == 409


def test_limit_order_rests_and_cancels(client: TestClient) -> None:
    r = client.post("/api/v1/mm/orders", json={"side": "buy", "type": "limit", "quantity": 50, "limit_price": "99.90"})
    assert r.status_code == 201
    o = r.json()["order"]
    assert o["status"] == "open" and o["filled_qty"] == 0
    book = client.get("/api/v1/mm/book").json()
    assert any(lv["price"] == "99.90" and lv["by_owner"].get("customer") == 50 for lv in book["bids"])
    assert client.delete(f"/api/v1/mm/orders/{o['id']}").json()["status"] == "canceled"
    assert client.delete(f"/api/v1/mm/orders/{o['id']}").status_code == 409
    assert client.delete("/api/v1/mm/orders/ORD-999999-0000").status_code == 404


def test_limit_order_never_worse_than_limit(client: TestClient) -> None:
    r = client.post("/api/v1/mm/orders", json={"side": "buy", "type": "limit", "quantity": 300, "limit_price": "100.05"}).json()
    assert all(D(t["price"]) <= D("100.05") for t in r["trades"])
    assert r["order"]["filled_qty"] == 100 and r["order"]["status"] == "partially_filled"


def test_order_validation_errors(client: TestClient) -> None:
    assert client.post("/api/v1/mm/orders", json={"side": "buy", "type": "limit", "quantity": 10}).status_code == 422
    assert client.post("/api/v1/mm/orders", json={"side": "buy", "type": "market", "quantity": -1}).status_code == 422
    r = client.post("/api/v1/mm/orders", json={"side": "buy", "type": "limit", "quantity": 10, "limit_price": "100.001"})
    assert r.status_code == 200 and r.json()["order"]["status"] == "rejected"


def test_idempotency_prevents_duplicates(client: TestClient) -> None:
    body = {"side": "buy", "type": "market", "quantity": 10}
    h = {"Idempotency-Key": "abc-1"}
    first = client.post("/api/v1/mm/orders", json=body, headers=h).json()
    again = client.post("/api/v1/mm/orders", json=body, headers=h).json()
    assert again["idempotent_replay"] is True and again["order"]["id"] == first["order"]["id"]
    assert client.get("/api/v1/mm/ledger").json()["position"] == -10
    conflict = client.post("/api/v1/mm/orders", json={**body, "quantity": 20}, headers=h)
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def _run(client: TestClient, ticks: int) -> dict:
    client.put("/api/v1/mm/config", json={**client.get("/api/v1/mm/config").json(), "arrival_rate": "2", "limit_order_fraction": "0.3", "volatility": "0.03"})
    client.post("/api/v1/simulation/reset", json={"seed": 99})
    client.post("/api/v1/simulation/advance", json={"ticks": ticks})
    return client.get("/api/v1/mm/state").json()


def test_inventory_and_cash_reconcile_with_fills(client: TestClient) -> None:
    s = _run(client, 300)
    led = s["ledger"]
    mm = client.app.state.container.mm
    fills = [t for t in mm.venue.trades if "mm" in (t.taker_owner, t.maker_owner)]
    assert len(fills) == led["trade_count"] > 20
    pos = sum((1 if (t.aggressor_side is Side.BUY) == (t.taker_owner == "mm") else -1) * t.quantity for t in fills)
    assert pos == led["position"]
    cash = D(led["initial_cash"])
    for t in fills:
        mm_buys = (t.aggressor_side is Side.BUY) == (t.taker_owner == "mm")
        fee = t.taker_fee if t.taker_owner == "mm" else t.maker_fee
        cash += (-1 if mm_buys else 1) * t.price * t.quantity - fee
    assert cash == D(led["cash"])
    mark = D(led["mark_price"])
    assert D(led["equity"]) - D(led["initial_cash"]) == D(led["net_pnl"])
    assert abs(led["position"]) <= s["config"]["max_inventory"]
    assert D(led["equity"]) == cash + led["position"] * mark


def test_same_seed_is_reproducible(client: TestClient) -> None:
    a = _run(client, 120)["series"]
    b = _run(client, 120)["series"]
    assert a == b and len(a) > 100


def test_inventory_risk_preset_skews_quotes(client: TestClient) -> None:
    client.post("/api/v1/mm/presets/inventory-risk/load")
    for _ in range(3):
        client.post("/api/v1/mm/presets/inventory-risk/step")
    s = client.get("/api/v1/mm/state").json()
    assert s["ledger"]["position"] < -500
    assert D(s["quote"]["skew"]) > 0 and D(s["quote"]["bid"]) > D(s["fair_value"]) - D("0.05")


def test_reset_demo_restores_initial_state(client: TestClient) -> None:
    client.post("/api/v1/mm/orders", json={"side": "buy", "type": "market", "quantity": 100})
    s = client.post("/api/v1/mm/reset").json()
    assert s["ledger"]["position"] == 0 and D(s["ledger"]["cash"]) == D("1000000")
    assert s["quote"]["bid"] == "99.95" and s["trades"] == []
