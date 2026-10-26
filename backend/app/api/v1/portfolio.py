from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.core.jsonresp import jsonify
from app.persistence.configs import save_all
from app.portfolio.futures import FuturesSpec
from app.portfolio.service import HedgeRequest, HedgeRule
from app.state import AppContainer, get_container

router = APIRouter(tags=["portfolio & hedging"])
Container = Annotated[AppContainer, Depends(get_container)]


class BasisShock(BaseModel):
    shock_pips: Decimal = Field(ge=-500, le=500)


class AdvanceDays(BaseModel):
    days: int = Field(ge=1, le=730)


class GuidedStep(BaseModel):
    instrument: Literal["fx_offset", "futures"] = "futures"
    rate_pct: Decimal | None = Field(None, ge=-20, le=20)


@router.get("/portfolio")
async def portfolio(c: Container) -> Response:
    return jsonify(c.portfolio.snapshot())


@router.get("/portfolio/exposure")
async def exposure(c: Container) -> Response:
    s = c.portfolio.snapshot()
    return jsonify({k: s[k] for k in ("valuation_currency", "rates", "exposures", "gross_exposure_usd", "net_exposure_usd")})


@router.get("/portfolio/risk")
async def risk(c: Container) -> Response:
    return jsonify(c.portfolio.risk())


@router.post("/portfolio/reset")
async def reset(c: Container) -> Response:
    c.portfolio.guided_reset(c.sim.rng_for("fx"))
    return jsonify(c.portfolio.snapshot())


@router.put("/portfolio/futures/spec")
async def put_spec(c: Container, spec: FuturesSpec) -> Response:
    try:
        c.portfolio.set_futures_spec(spec)
        save_all(c)
    except ValueError as exc:
        raise ApiError(409, "position_open", str(exc)) from exc
    return jsonify(c.portfolio.futures.spec)


@router.post("/portfolio/futures/basis")
async def basis(c: Container, body: BasisShock) -> Response:
    c.portfolio.shock_basis(body.shock_pips)
    return jsonify(c.portfolio.snapshot()["futures"])


@router.post("/portfolio/futures/advance-days")
async def advance_days(c: Container, body: AdvanceDays) -> Response:
    return jsonify(c.portfolio.advance_days(body.days))


@router.post("/hedges/proposals")
async def propose(c: Container, req: HedgeRequest) -> Response:
    return jsonify(c.portfolio.propose(req), 201)


@router.get("/hedges/proposals")
async def proposals(c: Container) -> Response:
    return jsonify(list(reversed(c.portfolio.proposals.values())))


@router.post("/hedges/proposals/{pid}/execute")
async def execute(c: Container, pid: str) -> Response:
    try:
        return jsonify(c.portfolio.execute(pid))
    except KeyError as exc:
        raise ApiError(404, "not_found", f"Unknown proposal {pid}") from exc
    except ValueError as exc:
        raise ApiError(409, "not_executable", str(exc)) from exc


@router.get("/hedges/rule", response_model=HedgeRule)
async def get_rule(c: Container) -> HedgeRule:
    return c.portfolio.rule


@router.put("/hedges/rule", response_model=HedgeRule)
async def put_rule(c: Container, rule: HedgeRule) -> HedgeRule:
    c.portfolio.rule = rule
    save_all(c)
    c.portfolio._evaluate_rule(source="rule updated")  # noqa: SLF001
    return rule


@router.post("/portfolio/scenarios/gbp-hedge/reset")
async def guided_reset(c: Container) -> Response:
    c.portfolio.guided_reset(c.sim.rng_for("fx"))
    return jsonify({"steps": c.portfolio.GUIDED_STEPS, "snapshot": c.portfolio.snapshot()})


@router.post("/portfolio/scenarios/gbp-hedge/step")
async def guided_step(c: Container, body: Annotated[GuidedStep | None, Body()] = None) -> Response:
    b = body or GuidedStep()
    try:
        return jsonify(c.portfolio.guided_next(b.instrument, b.rate_pct))
    except IndexError as exc:
        raise ApiError(409, "scenario_complete", str(exc)) from exc
    except LookupError as exc:
        raise ApiError(409, "nothing_to_execute", str(exc)) from exc
