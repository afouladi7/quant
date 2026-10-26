"""Kubernetes/OpenShift probe endpoints (unversioned, outside /api/v1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.state import AppContainer, get_container

router = APIRouter(tags=["health"])


@router.get("/healthz/live")
async def live() -> dict[str, str]:
    """Liveness: the event loop is responsive enough to answer."""
    return {"status": "ok"}


@router.get("/healthz/ready")
async def ready(c: Annotated[AppContainer, Depends(get_container)]) -> JSONResponse:
    """Readiness: the simulation loop, in-memory repository and TCP lab listener are up.

    The PostgreSQL archive is reported but deliberately NOT a readiness gate: a database
    outage degrades history archiving, it must not take the whole (in-memory) app offline.
    """
    checks = {
        "simulation_loop": c.sim.is_alive(),
        "repository": c.events.healthy(),
        "tcp_lab_server": c.tcp_server.running,
    }
    ok = all(checks.values())
    degraded = c.sink.persistent and not c.sink.healthy()
    status = "unavailable" if not ok else "degraded" if degraded else "ok"
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": status, "checks": checks, "persistence": {"enabled": c.sink.persistent, "connected": c.sink.healthy()}},
    )
