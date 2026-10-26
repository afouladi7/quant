from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.core.errors import ApiError
from app.core.jsonresp import jsonify
from app.state import AppContainer, get_container

router = APIRouter(prefix="/history", tags=["history (persistent mode)"])
Container = Annotated[AppContainer, Depends(get_container)]


@router.get("/status")
async def status(c: Container) -> Response:
    return jsonify(c.sink.status())


@router.get("/{kind}")
async def history(
    c: Container,
    kind: Literal["events", "trades", "benchmarks", "instances"],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    correlation_id: Annotated[str | None, Query(max_length=64)] = None,
    type: Annotated[str | None, Query(max_length=64)] = None,
    module: Annotated[str | None, Query(max_length=32)] = None,
) -> Response:
    """Archived history across restarts. Available only in persistent mode."""
    try:
        return jsonify(c.sink.query(kind, limit, correlation_id=correlation_id, type=type, module=module))
    except LookupError as exc:
        raise ApiError(404, "not_persistent", str(exc)) from exc
