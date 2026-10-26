from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.core.jsonresp import jsonify
from app.quant.options import OptionInput, analyse, implied_vol
from app.quant.risk import simulate, two_assets

router = APIRouter(prefix="/quant", tags=["quant labs"])


class OptionRequest(BaseModel):
    spot: float = Field(100, gt=0, le=1e6, description="Current stock price")
    strike: float = Field(100, gt=0, le=1e6, description="Price at which the option lets you buy (call) or sell (put)")
    days: float = Field(30, ge=1, le=3650, description="Calendar days until expiry")
    rate: float = Field(0.04, ge=-0.1, le=0.5, description="Risk-free interest rate, annual decimal (0.04 = 4%)")
    vol: float = Field(0.2, ge=0.01, le=3, description="Volatility, annual decimal (0.20 = 20%)")
    kind: Literal["call", "put"] = "call"
    dividend_yield: float = Field(0.0, ge=0, le=0.5)


class ImpliedVolRequest(OptionRequest):
    market_price: float = Field(gt=0, le=1e6, description="Observed option price to back out volatility from")


class RiskRequest(BaseModel):
    start: float = Field(100, gt=0, le=1e6)
    mu: float = Field(0.08, ge=-1, le=1, description="Expected annual return (drift), decimal")
    sigma: float = Field(0.2, ge=0.01, le=2, description="Annual volatility, decimal")
    days: int = Field(252, ge=20, le=2520, description="Trading days to simulate")
    seed: int = Field(7, ge=0, le=2**31)
    risk_free: float = Field(0.03, ge=-0.1, le=0.5)
    jumps: bool = Field(False, description="Add rare crash days (fat tails)")


class TwoAssetRequest(BaseModel):
    ret1: float = Field(0.08, ge=-1, le=1)
    vol1: float = Field(0.20, gt=0, le=2)
    ret2: float = Field(0.04, ge=-1, le=1)
    vol2: float = Field(0.10, gt=0, le=2)
    rho: float = Field(0.2, ge=-1, le=1, description="Correlation between the two assets")


def _opt(b: OptionRequest) -> OptionInput:
    return OptionInput(b.spot, b.strike, b.days, b.rate, b.vol, b.kind, b.dividend_yield)


@router.post("/options/price")
async def option_price(body: OptionRequest) -> Response:
    """Black-Scholes price, Greeks, payoff curve, time decay, binomial convergence and plain-English explanations."""
    return jsonify(analyse(_opt(body)))


@router.post("/options/implied-vol")
async def option_iv(body: ImpliedVolRequest) -> Response:
    """Solve for the volatility that reproduces an observed option price."""
    iv = implied_vol(body.market_price, _opt(body))
    if iv is None:
        raise ApiError(422, "no_solution", "No volatility between 0.01% and 500% reproduces that price (it may be below intrinsic value).")
    return jsonify({"implied_vol": iv, "check": analyse(_opt(body.model_copy(update={"vol": iv})))["result"]["price"]})


@router.post("/risk/simulate")
async def risk_simulate(body: RiskRequest) -> Response:
    """Simulate a price path and compute returns, volatility, Sharpe, drawdown and VaR."""
    return jsonify(simulate(body.start, body.mu, body.sigma, body.days, body.seed, body.risk_free, body.jumps))


@router.post("/risk/two-assets")
async def risk_two_assets(body: TwoAssetRequest) -> Response:
    """Risk and return of every mix of two assets: the diversification effect."""
    return jsonify(two_assets(body.ret1, body.vol1, body.ret2, body.vol2, body.rho))
