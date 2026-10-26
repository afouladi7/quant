from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field

from app.core.errors import ApiError
from app.core.idempotency import IdempotencyConflict, fingerprint
from app.core.jsonresp import jsonify
from app.persistence.configs import save_all
from app.fx.config import PAIRS, BookConfig, RoutingWeights
from app.fx.router import RoutingPlan
from app.fx.scenarios import SCENARIOS
from app.fx.service import plan_to_dict
from app.markets.models import OrderType, Side
from app.state import AppContainer, get_container

router = APIRouter(prefix="/fx", tags=["fx"])
Container = Annotated[AppContainer, Depends(get_container)]
PairQ = Annotated[str, Query(description="Currency pair, e.g. GBP/USD")]


class FXOrderRequest(BaseModel):
    pair: str = "GBP/USD"
    side: Side
    type: OrderType = OrderType.MARKET
    quantity: int = Field(gt=0, le=100_000_000)
    limit_price: Decimal | None = Field(None, gt=0)
    routing_mode: str = Field("smart", pattern="^(A|B|C|smart)$")
    weights: RoutingWeights | None = None


class RateRequest(BaseModel):
    pair: str = "GBP/USD"
    rate: Decimal | None = Field(None, gt=0)
    shift_pct: Decimal | None = Field(None, ge=-50, le=50)


def _pair(pair: str) -> str:
    if pair not in PAIRS:
        raise ApiError(404, "not_found", f"Unknown pair {pair}. Supported: {', '.join(PAIRS)}")
    return pair


@router.get("/state")
async def state(c: Container, pair: PairQ = "GBP/USD") -> Response:
    return jsonify(c.fx.snapshot(_pair(pair)))


@router.get("/books/{name}")
async def book(c: Container, name: str, pair: PairQ = "GBP/USD", depth: Annotated[int, Query(ge=1, le=50)] = 10) -> Response:
    if name not in c.fx.books:
        raise ApiError(404, "not_found", "Books are A, B and C")
    return jsonify(c.fx.book_snapshot(name, _pair(pair), depth))


@router.put("/books/{name}/config")
async def put_book_config(c: Container, name: str, cfg: BookConfig) -> Response:
    if name not in c.fx.books or cfg.name != name:
        raise ApiError(422, "invalid_book", "Book name in path and body must match (A, B or C)")
    c.fx.set_book_config(cfg)
    save_all(c)
    return jsonify(c.fx.books[name].config)


@router.put("/routing-weights")
async def put_weights(c: Container, w: RoutingWeights) -> Response:
    c.fx.weights = w
    save_all(c)
    return jsonify(w)


@router.post("/route-preview")
async def preview(c: Container, body: FXOrderRequest) -> Response:
    plan: RoutingPlan = c.fx.preview(_pair(body.pair), body.side, body.quantity, body.limit_price, body.routing_mode, body.weights)
    return jsonify(plan_to_dict(plan))


@router.post("/orders")
async def submit(c: Container, body: FXOrderRequest, idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)] = None) -> Response:
    _pair(body.pair)
    payload: dict[str, Any] = body.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = c.idempotency.lookup("fx:orders", idempotency_key, fingerprint(payload))
        except IdempotencyConflict as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        if cached is not None:
            return jsonify({"parent": c.fx.parents.get(cached, cached), "idempotent_replay": True})
    try:
        parent = c.fx.submit_parent(body.pair, body.side, body.type, body.quantity, body.limit_price, body.routing_mode, body.weights)
    except ValueError as exc:
        raise ApiError(422, "invalid_order", str(exc)) from exc
    if idempotency_key:
        c.idempotency.store("fx:orders", idempotency_key, fingerprint(payload), parent.id)
    return jsonify({"parent": parent, "idempotent_replay": False}, 201)


@router.get("/orders")
async def list_orders(c: Container, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> Response:
    return jsonify(list(reversed(c.fx.parents.values()))[:limit])


@router.get("/orders/{parent_id}")
async def get_order(c: Container, parent_id: str) -> Response:
    p = c.fx.parents.get(parent_id)
    if p is None:
        raise ApiError(404, "not_found", f"Unknown parent order {parent_id}")
    trades = [t for b in c.fx.books.values() for t in b.venues[p.pair].trades if t.correlation_id == p.id
              or any(ch.order_id in (t.taker_order_id, t.maker_order_id) for ch in p.children)]
    return jsonify({"parent": p, "trades": sorted(trades, key=lambda t: t.ts)})


@router.delete("/orders/{parent_id}")
async def cancel_order(c: Container, parent_id: str) -> Response:
    try:
        return jsonify(c.fx.cancel_parent(parent_id))
    except KeyError as exc:
        raise ApiError(404, "not_found", f"Unknown parent order {parent_id}") from exc
    except ValueError as exc:
        raise ApiError(409, "not_cancelable", str(exc)) from exc


@router.post("/rates")
async def set_rate(c: Container, body: RateRequest) -> Response:
    pair = _pair(body.pair)
    if (body.rate is None) == (body.shift_pct is None):
        raise ApiError(422, "validation_error", "Provide exactly one of rate or shift_pct")
    new = body.rate if body.rate is not None else c.fx.mids[pair] * (1 + body.shift_pct / 100)  # type: ignore[operator]
    try:
        c.fx.set_mid(pair, new)
    except ValueError as exc:
        raise ApiError(422, "invalid_rate", str(exc)) from exc
    return jsonify({"pair": pair, "mid": c.fx.mids[pair]})


@router.post("/reset")
async def reset(c: Container) -> Response:
    c.fx.restore_defaults(c.sim.rng_for(c.fx.name))
    return jsonify(c.fx.snapshot("GBP/USD"))


@router.get("/scenarios")
async def scenarios() -> Response:
    return jsonify(list(SCENARIOS.values()))


@router.post("/scenarios/{sid}/reset")
async def load_scenario(c: Container, sid: str) -> Response:
    if sid not in SCENARIOS:
        raise ApiError(404, "not_found", f"Unknown scenario {sid}")
    c.fx.load_scenario(SCENARIOS[sid], c.sim.rng_for(c.fx.name))
    return jsonify(c.fx.snapshot("GBP/USD"))


@router.post("/scenarios/{sid}/step")
async def step_scenario(c: Container, sid: str) -> Response:
    if c.fx.scenario is None or c.fx.scenario["id"] != sid:
        raise ApiError(409, "scenario_not_loaded", f"Reset (load) scenario {sid} first.")
    try:
        return jsonify(c.fx.step_scenario())
    except IndexError as exc:
        raise ApiError(409, "scenario_complete", str(exc)) from exc
