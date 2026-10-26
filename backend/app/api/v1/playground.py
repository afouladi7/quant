from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel, Field, model_validator

from app.core.errors import ApiError
from app.core.jsonresp import jsonify
from app.markets.models import OrderType, Side
from app.markets.venue import OrderError
from app.state import AppContainer, get_container

router = APIRouter(prefix="/playground", tags=["order book playground"])
Container = Annotated[AppContainer, Depends(get_container)]


class PlaygroundOrder(BaseModel):
    trader: str = Field("you", description="you, alice, bob or carol")
    side: Side
    type: OrderType = OrderType.LIMIT
    quantity: int = Field(gt=0, le=1000)
    price: Decimal | None = Field(None, gt=0, le=10000, description="Whole dollars for limit orders")

    @model_validator(mode="after")
    def _check(self) -> "PlaygroundOrder":
        if self.type is OrderType.LIMIT and self.price is None:
            raise ValueError("a limit order needs a price")
        if self.type is OrderType.MARKET:
            self.price = None
        return self


class ResetRequest(BaseModel):
    seed: bool = Field(True, description="Start with a small example book (otherwise empty)")


@router.get("")
async def state(c: Container) -> Response:
    """The playground book with every resting order in queue order, recent trades and explained history."""
    return jsonify(c.playground.snapshot())


@router.post("/orders")
async def place(c: Container, body: PlaygroundOrder) -> Response:
    """Send an order; the response explains, step by step, how the matching engine handled it."""
    try:
        return jsonify(c.playground.place(body.trader, body.side, body.type, body.quantity, body.price))
    except OrderError as exc:
        raise ApiError(422, exc.code, str(exc)) from exc


@router.delete("/orders/{order_id}")
async def cancel(c: Container, order_id: str) -> Response:
    """Cancel a resting playground order."""
    try:
        return jsonify(c.playground.cancel(order_id))
    except OrderError as exc:
        raise ApiError(404 if exc.code == "not_found" else 409, exc.code, str(exc)) from exc


@router.post("/reset")
async def reset(c: Container, body: Annotated[ResetRequest | None, Body()] = None) -> Response:
    """Restore the example book (or an empty one)."""
    c.playground.reset(seed=body.seed if body else True)
    return jsonify(c.playground.snapshot())
