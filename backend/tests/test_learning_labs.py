import math

import pytest
from fastapi.testclient import TestClient

from app.quant.options import OptionInput, binomial, black_scholes, implied_vol
from app.quant.risk import simulate, two_assets


# ---- order book playground ---------------------------------------------------------------
def test_playground_seed_book_and_price_time_explanation(client: TestClient) -> None:
    s = client.get("/api/v1/playground").json()
    assert s["best_bid"] == "99" and s["best_ask"] == "101"
    assert [o["trader"] for o in s["asks"][0]["orders"]] == ["alice", "bob"]  # time priority at $101
    r = client.post("/api/v1/playground/orders", json={"side": "buy", "type": "limit", "quantity": 7, "price": "102"}).json()
    assert r["order"]["status"] == "filled" and len(r["trades"]) == 2
    assert [t["maker_owner"] for t in r["trades"]] == ["alice", "bob"]
    text = " ".join(r["steps"])
    assert "first come, first served" in text and "Matched with #1 from Alice at $101: 5 traded" in text
    assert "Matched with #2 from Bob at $101: 2 traded" in text


def test_playground_limit_rests_and_explains_why(client: TestClient) -> None:
    r = client.post("/api/v1/playground/orders", json={"side": "buy", "type": "limit", "quantity": 5, "price": "100"}).json()
    assert r["order"]["status"] == "open" and not r["trades"]
    assert any("worse than the limit $100" in s for s in r["steps"])
    assert any("rests in the book as a bid at $100" in s for s in r["steps"])
    assert client.delete(f"/api/v1/playground/orders/{r['order']['id']}").json()["status"] == "canceled"


def test_playground_self_trade_and_market_remainder(client: TestClient) -> None:
    r = client.post("/api/v1/playground/orders", json={"trader": "bob", "side": "sell", "type": "market", "quantity": 20}).json()
    steps = r["steps"]
    i_stp = next(i for i, s in enumerate(steps) if "self-trade prevention" in s)
    i_match = next(i for i, s in enumerate(steps) if s.startswith("Matched with #5"))
    assert i_stp < i_match  # explained in the order the engine processed the book
    assert r["order"]["filled_qty"] == 6 and any("unfilled 14 was canceled" in s for s in steps)


def test_playground_validation_and_reset(client: TestClient) -> None:
    assert client.post("/api/v1/playground/orders", json={"side": "buy", "quantity": 1}).status_code == 422  # limit needs price
    assert client.post("/api/v1/playground/orders", json={"trader": "mallory", "side": "buy", "quantity": 1, "price": "1"}).status_code == 422
    assert client.post("/api/v1/playground/orders", json={"side": "buy", "quantity": 1, "price": "100.5"}).json()["order"]["status"] == "rejected"
    empty = client.post("/api/v1/playground/reset", json={"seed": False}).json()
    assert empty["bids"] == [] and empty["asks"] == []


# ---- options -----------------------------------------------------------------------------------
def test_black_scholes_textbook_value() -> None:
    # Hull's classic example: S=42, K=40, r=10%, sigma=20%, T=0.5y -> call 4.76, put 0.81
    o = OptionInput(42, 40, 0.5 * 365, 0.10, 0.20, "call")
    assert black_scholes(o)["price"] == pytest.approx(4.76, abs=0.01)
    assert black_scholes(OptionInput(42, 40, 0.5 * 365, 0.10, 0.20, "put"))["price"] == pytest.approx(0.81, abs=0.01)


def test_greeks_match_finite_differences() -> None:
    o = OptionInput(100, 105, 60, 0.03, 0.25, "call")
    g = black_scholes(o)
    h = 0.01
    up = black_scholes(OptionInput(100 + h, 105, 60, 0.03, 0.25, "call"))["price"]
    dn = black_scholes(OptionInput(100 - h, 105, 60, 0.03, 0.25, "call"))["price"]
    assert g["delta"] == pytest.approx((up - dn) / (2 * h), rel=1e-4)
    assert g["gamma"] == pytest.approx((up - 2 * g["price"] + dn) / h**2, rel=1e-3)
    v_up = black_scholes(OptionInput(100, 105, 60, 0.03, 0.26, "call"))["price"]
    assert g["vega"] == pytest.approx(v_up - g["price"], rel=0.02)  # per 1 vol point
    one_day = black_scholes(OptionInput(100, 105, 59, 0.03, 0.25, "call"))["price"]
    assert g["theta"] == pytest.approx(one_day - g["price"], rel=0.02)  # per calendar day


def test_binomial_converges_and_iv_round_trips() -> None:
    o = OptionInput(100, 100, 90, 0.05, 0.3, "put")
    bs = black_scholes(o)["price"]
    assert abs(binomial(o, 400) - bs) < 0.02 < abs(binomial(o, 2) - bs)
    assert binomial(o, 200, american=True) >= binomial(o, 200)  # early exercise is worth >= 0
    assert implied_vol(bs, o) == pytest.approx(0.3, abs=1e-5)
    assert implied_vol(0.0001, OptionInput(150, 100, 30, 0.0, 0.2, "call")) is None  # below intrinsic


def test_option_api(client: TestClient) -> None:
    r = client.post("/api/v1/quant/options/price", json={"spot": 110, "strike": 100, "kind": "call"}).json()
    assert r["moneyness"] == "in the money" and r["parity"]["holds"]
    assert r["result"]["intrinsic"] == pytest.approx(10) and r["result"]["time_value"] > 0
    assert len(r["curve"]) == 41 and len(r["explain"]) >= 8
    assert client.post("/api/v1/quant/options/price", json={"vol": -1}).status_code == 422
    assert client.post("/api/v1/quant/options/implied-vol", json={"market_price": 0.00001, "spot": 150}).status_code == 422


# ---- risk & returns -------------------------------------------------------------------------------
def test_risk_statistics_are_consistent() -> None:
    r = simulate(100, 0.08, 0.2, 504, seed=3, risk_free=0.02)
    s, p = r["stats"], r["prices"]
    assert len(p) == 505 and r == simulate(100, 0.08, 0.2, 504, seed=3, risk_free=0.02)  # deterministic
    assert s["total_return"] == pytest.approx(p[-1] / p[0] - 1)
    assert s["annual_vol"] == pytest.approx(s["daily_stdev"] * math.sqrt(252))
    peak, worst = p[0], 0.0
    for x in p:
        peak = max(peak, x)
        worst = min(worst, x / peak - 1)
    assert s["max_drawdown"] == pytest.approx(worst)
    assert r["var"]["0.99"]["historical"] >= r["var"]["0.95"]["historical"] > 0
    assert sum(b["count"] for b in r["histogram"]) == 504
    assert 0.1 < s["annual_vol"] < 0.3


def test_fat_tails_switch_raises_kurtosis() -> None:
    calm = simulate(100, 0.05, 0.2, 2520, seed=11, risk_free=0.0)["stats"]["excess_kurtosis"]
    jumpy = simulate(100, 0.05, 0.2, 2520, seed=11, risk_free=0.0, jumps=True)["stats"]["excess_kurtosis"]
    assert jumpy > calm + 1


def test_diversification_limits() -> None:
    plus = two_assets(0.08, 0.2, 0.04, 0.1, 1.0)
    assert plus["points"][10]["vol"] == pytest.approx(plus["points"][10]["naive_vol"])  # rho=+1: no benefit
    minus = two_assets(0.08, 0.2, 0.04, 0.1, -1.0)
    assert minus["min_variance"]["vol"] == pytest.approx(0.0, abs=1e-9)  # rho=-1: risk can be cancelled
    assert minus["min_variance"]["w1"] == pytest.approx(1 / 3)


def test_risk_api(client: TestClient) -> None:
    r = client.post("/api/v1/quant/risk/simulate", json={"days": 100}).json()
    assert len(r["prices"]) == 101 and len(r["explain"]) == 6
    assert client.post("/api/v1/quant/risk/simulate", json={"days": 5}).status_code == 422
    assert len(client.post("/api/v1/quant/risk/two-assets", json={"rho": 0}).json()["points"]) == 21
