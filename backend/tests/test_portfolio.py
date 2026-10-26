from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.markets.models import Side
from app.portfolio.futures import FuturesBook, FuturesSpec


def pnl_identity(s: dict) -> None:
    b = s["pnl_breakdown"]
    parts = sum(D(b[k]) for k in ("spot_realized_usd", "spot_unrealized_usd", "futures_realized_usd", "futures_unrealized_usd")) \
        - D(b["spot_fees_usd"]) - D(b["futures_fees_usd"])
    assert parts == D(s["total_pnl_usd"])


# ---- futures (unit) ------------------------------------------------------------------
def test_futures_price_basis_and_convergence() -> None:
    f = FuturesBook(FuturesSpec(days_total=90, days_to_expiry=45, initial_basis_pips=D("12")))
    assert f.basis() == D("0.0006")
    assert f.price(D("1.27000")) == D("1.2706")
    f.spec.days_to_expiry = 0
    assert f.price(D("1.27000")) == D("1.2700")


def test_futures_pnl_and_partial_fill() -> None:
    f = FuturesBook(FuturesSpec(max_fill_per_order=10, half_spread_ticks=0, initial_basis_pips=D("0")))
    fill = f.execute(Side.SELL, 16, D("1.2700"))
    assert fill.filled == 10 and fill.fee == D("20.00")
    assert f.gbp_equivalent() == -625_000
    assert f.unrealized_usd(D("1.2600")) == D("0.0100") * 10 * 62_500  # short gains when GBP falls
    realized = f.settle(D("1.2650"))
    assert realized == D("0.0050") * 10 * 62_500 and f.contracts == 0 and f.expired
    with pytest.raises(ValueError):
        f.execute(Side.BUY, 1, D("1.27"))


# ---- portfolio through the API ---------------------------------------------------------
def buy_gbp(client: TestClient, qty: int = 1_000_000) -> dict:
    client.post("/api/v1/portfolio/scenarios/gbp-hedge/reset")
    return client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": qty}).json()["parent"]


def test_fx_fill_updates_balances_and_exposure(client: TestClient) -> None:
    parent = buy_gbp(client)
    s = client.get("/api/v1/portfolio").json()
    bal = {b["currency"]: D(b["amount"]) for b in s["balances"]}
    assert bal["GBP"] == D(1_000_000)
    assert bal["USD"] == D(20_000_000) - D(parent["vwap"]) * 1_000_000 - D(parent["total_fees"])
    gbp = next(e for e in s["exposures"] if e["currency"] == "GBP")
    assert D(gbp["net_exposure"]) == D(1_000_000) and gbp["direction"] == "long"
    assert D(gbp["pnl_if_plus_1pct_usd"]) == D("12700.00")
    pnl_identity(s)


def test_rate_change_pnl(client: TestClient) -> None:
    buy_gbp(client)
    before = D(client.get("/api/v1/portfolio").json()["equity_usd"])
    client.post("/api/v1/fx/rates", json={"pair": "GBP/USD", "rate": "1.28000"})
    s = client.get("/api/v1/portfolio").json()
    assert D(s["equity_usd"]) - before == D("10000.00")  # 1,000,000 × (1.28 − 1.27)
    pnl_identity(s)


@pytest.mark.parametrize("instrument", ["futures", "fx_offset"])
def test_rule_hedge_neutralises_exposure(client: TestClient, instrument: str) -> None:
    buy_gbp(client)
    p = client.post("/api/v1/hedges/proposals", json={"instrument": instrument, "mode": "rule"}).json()
    assert p["status"] == "proposed" and p["direction"] == "sell"
    assert p["quantity"] == (16 if instrument == "futures" else 1_000_000)
    assert D(p["projected_residual"]) == 0
    e = client.post(f"/api/v1/hedges/proposals/{p['id']}/execute").json()
    assert e["status"] == "executed" and D(e["actual_exposure_after"]) == 0
    s = client.get("/api/v1/portfolio").json()
    gbp = next(x for x in s["exposures"] if x["currency"] == "GBP")
    assert D(gbp["pre_hedge_exposure"]) == D(1_000_000) and D(gbp["net_exposure"]) == 0
    bal = {b["currency"]: D(b["amount"]) for b in s["balances"]}
    assert bal["GBP"] == (D(1_000_000) if instrument == "futures" else 0)  # futures never touch GBP cash
    pnl_identity(s)
    risk = {r["id"]: r for r in client.get("/api/v1/portfolio/risk").json()["rows"]}
    assert D(risk["gbp_up"]["hedged"]) == 0 and D(risk["gbp_up"]["unhedged"]) > 0
    assert client.post(f"/api/v1/hedges/proposals/{p['id']}/execute").status_code == 409


def test_contract_rounding_leaves_residual(client: TestClient) -> None:
    buy_gbp(client, 1_030_000)
    p = client.post("/api/v1/hedges/proposals", json={"instrument": "futures", "mode": "rule"}).json()
    assert p["quantity"] == 16  # 1,030,000 / 62,500 = 16.48 -> 16
    assert D(p["projected_residual"]) == D(30_000)


def test_partial_hedge_fill(client: TestClient) -> None:
    buy_gbp(client)
    spec = client.get("/api/v1/portfolio").json()["futures"]["spec"] | {"max_fill_per_order": 10}
    assert client.put("/api/v1/portfolio/futures/spec", json=spec).status_code == 200
    p = client.post("/api/v1/hedges/proposals", json={"instrument": "futures", "mode": "rule"}).json()
    e = client.post(f"/api/v1/hedges/proposals/{p['id']}/execute").json()
    assert e["status"] == "partially_executed" and e["filled_quantity"] == 10
    assert D(e["actual_exposure_after"]) == D(1_000_000 - 625_000)
    assert client.put("/api/v1/portfolio/futures/spec", json=spec).status_code == 409  # position open


def test_basis_shock_and_expiry(client: TestClient) -> None:
    buy_gbp(client)
    p = client.post("/api/v1/hedges/proposals", json={"instrument": "futures", "mode": "rule"}).json()
    client.post(f"/api/v1/hedges/proposals/{p['id']}/execute")
    eq0 = D(client.get("/api/v1/portfolio").json()["equity_usd"])
    client.post("/api/v1/portfolio/futures/basis", json={"shock_pips": "5"})
    eq1 = D(client.get("/api/v1/portfolio").json()["equity_usd"])
    assert eq1 - eq0 == D("-500.00")  # short 16 × 62,500 loses 5 pips
    r = client.post("/api/v1/portfolio/futures/advance-days", json={"days": 100}).json()
    assert r["days_to_expiry"] == 0 and r["settled_realized_usd"] is not None
    s = client.get("/api/v1/portfolio").json()
    assert s["futures"]["contracts"] == 0 and s["futures"]["expired"]
    assert D(next(x for x in s["exposures"] if x["currency"] == "GBP")["net_exposure"]) == D(1_000_000)
    pnl_identity(s)


def test_rule_based_auto_hedge_and_threshold(client: TestClient) -> None:
    client.post("/api/v1/portfolio/scenarios/gbp-hedge/reset")
    client.put("/api/v1/hedges/rule", json={"enabled": True, "auto_execute": True, "instrument": "fx_offset", "target_exposure": "0", "max_exposure": "250000"})
    client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 200_000})
    assert client.get("/api/v1/hedges/proposals").json() == []  # within threshold
    client.post("/api/v1/fx/orders", json={"side": "buy", "quantity": 400_000})
    props = client.get("/api/v1/hedges/proposals").json()
    assert props[0]["status"] == "executed"
    gbp = next(x for x in client.get("/api/v1/portfolio").json()["exposures"] if x["currency"] == "GBP")
    assert D(gbp["net_exposure"]) == 0


def test_manual_hedge_risk_limit_and_validation(client: TestClient) -> None:
    buy_gbp(client)
    p = client.post("/api/v1/hedges/proposals", json={"instrument": "fx_offset", "mode": "manual", "direction": "sell", "quantity": 500_000,
                                                     "max_hedge_notional_usd": "100000"}).json()
    assert p["status"] == "rejected" and "risk limit" in p["result"]
    assert client.post("/api/v1/hedges/proposals", json={"instrument": "futures", "mode": "manual"}).status_code == 422
    ok = client.post("/api/v1/hedges/proposals", json={"instrument": "fx_offset", "mode": "manual", "direction": "sell", "quantity": 500_000}).json()
    assert D(ok["projected_exposure_after"]) == D(500_000)


def test_guided_scenario_runs_to_completion(client: TestClient) -> None:
    client.post("/api/v1/portfolio/scenarios/gbp-hedge/reset")
    for _ in range(5):
        assert client.post("/api/v1/portfolio/scenarios/gbp-hedge/step", json={"instrument": "futures"}).status_code == 200
    assert client.post("/api/v1/portfolio/scenarios/gbp-hedge/step").status_code == 409
    pnl_identity(client.get("/api/v1/portfolio").json())
