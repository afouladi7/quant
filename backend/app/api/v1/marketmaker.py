from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field, model_validator

from app.core.errors import ApiError
from app.core.idempotency import IdempotencyConflict, fingerprint
from app.core.jsonresp import jsonify
from app.persistence.configs import save_all
from app.marketmaker.config import MMConfig
from app.marketmaker.presets import PRESETS
from app.markets.models import OrderType, Side, TimeInForce
from app.markets.venue import OrderError
from app.state import AppContainer, get_container

router = APIRouter(prefix="/mm", tags=["market maker"])
Container = Annotated[AppContainer, Depends(get_container)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]


class OrderRequest(BaseModel):
    side: Side
    type: OrderType
    quantity: int = Field(gt=0, le=1_000_000)
    limit_price: Decimal | None = Field(None, gt=0, le=Decimal("1000000"))
    tif: TimeInForce | None = None

    @model_validator(mode="after")
    def _check(self) -> "OrderRequest":
        if self.type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require limit_price")
        if self.type is OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market orders must not have limit_price")
        return self


class FairValueRequest(BaseModel):
    value: Decimal | None = Field(None, gt=0, le=Decimal("100000"))
    shift: Decimal | None = Field(None, ge=Decimal("-10000"), le=Decimal("10000"))

    @model_validator(mode="after")
    def _one(self) -> "FairValueRequest":
        if (self.value is None) == (self.shift is None):
            raise ValueError("provide exactly one of value or shift")
        return self


def _order_error(exc: OrderError) -> ApiError:
    status = {"not_found": 404, "not_cancelable": 409}.get(exc.code, 422)
    return ApiError(status, exc.code, str(exc))


@router.get("/state")
async def state(c: Container) -> Response:
    return jsonify(c.mm.snapshot())


@router.get("/config", response_model=MMConfig)
async def get_config(c: Container) -> MMConfig:
    return c.mm.config


@router.put("/config", response_model=MMConfig)
async def put_config(c: Container, cfg: MMConfig) -> MMConfig:
    c.mm.update_config(cfg)
    save_all(c)
    return c.mm.config


@router.get("/quote")
async def quote(c: Container) -> Response:
    return jsonify(c.mm.quote.as_dict() if c.mm.quote else None)


@router.get("/book")
async def book(c: Container, depth: Annotated[int, Query(ge=1, le=50)] = 10) -> Response:
    return jsonify(c.mm.venue.depth(depth))


@router.get("/ledger")
async def ledger(c: Container) -> Response:
    return jsonify(c.mm.snapshot()["ledger"])


@router.get("/trades")
async def trades(c: Container, limit: Annotated[int, Query(ge=1, le=1000)] = 100) -> Response:
    return jsonify(list(c.mm.venue.trades)[-limit:][::-1])


@router.post("/orders")
async def submit_order(c: Container, body: OrderRequest, idempotency_key: IdemKey = None) -> Response:
    payload: dict[str, Any] = body.model_dump(mode="json")
    if idempotency_key:
        try:
            cached = c.idempotency.lookup("mm:orders", idempotency_key, fingerprint(payload))
        except IdempotencyConflict as exc:
            raise ApiError(409, "idempotency_conflict", str(exc)) from exc
        if cached is not None:
            return jsonify({**cached, "idempotent_replay": True})
    result, explanation = c.mm.submit_customer_order(
        body.side, body.type, body.quantity, body.limit_price, body.tif, client_order_id=idempotency_key
    )
    response = {"order": result.order, "trades": result.trades, "explanation": explanation, "idempotent_replay": False}
    if idempotency_key:
        c.idempotency.store("mm:orders", idempotency_key, fingerprint(payload), response)
    return jsonify(response, 201 if result.order.status.value != "rejected" else 200)


@router.get("/orders")
async def list_orders(
    c: Container,
    owner: Annotated[str | None, Query(max_length=32)] = "customer",
    status: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> Response:
    orders = [
        o for o in c.mm.venue.orders.values()
        if (owner is None or o.owner == owner) and (status is None or o.status.value == status)
    ]
    return jsonify(orders[-limit:][::-1])


@router.get("/orders/{order_id}")
async def get_order(c: Container, order_id: str) -> Response:
    order = c.mm.venue.orders.get(order_id)
    if order is None:
        raise ApiError(404, "not_found", f"Unknown order {order_id}")
    fills = [t for t in c.mm.venue.trades if order_id in (t.taker_order_id, t.maker_order_id)]
    return jsonify({"order": order, "trades": fills})


@router.delete("/orders/{order_id}")
async def cancel_order(c: Container, order_id: str) -> Response:
    try:
        return jsonify(c.mm.cancel_customer_order(order_id))
    except OrderError as exc:
        raise _order_error(exc) from exc


@router.post("/fair-value")
async def fair_value(c: Container, body: FairValueRequest) -> Response:
    c.mm.shift_fair(amount=body.shift, value=body.value)
    return jsonify({"fair_value": c.mm.fair, "quote": c.mm.quote.as_dict() if c.mm.quote else None})


@router.post("/reset")
async def reset(c: Container) -> Response:
    c.mm.reset_demo(c.sim.rng_for(c.mm.name))
    return jsonify(c.mm.snapshot())


@router.get("/presets")
async def presets() -> Response:
    return jsonify([p.public() for p in PRESETS.values()])


@router.post("/presets/{preset_id}/load")
async def load_preset(c: Container, preset_id: str) -> Response:
    if preset_id not in PRESETS:
        raise ApiError(404, "not_found", f"Unknown preset {preset_id}")
    c.mm.load_preset(preset_id)
    return jsonify(c.mm.snapshot())


@router.post("/presets/{preset_id}/step")
async def step_preset(c: Container, preset_id: str) -> Response:
    if c.mm.preset is None or c.mm.preset.id != preset_id:
        raise ApiError(409, "preset_not_loaded", f"Load preset '{preset_id}' first.")
    try:
        return jsonify(c.mm.step_preset())
    except IndexError as exc:
        raise ApiError(409, "preset_complete", str(exc)) from exc
