"""MarketLab backend application factory."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import health, metrics
from app.api.v1 import events, fx, history, marketmaker, portfolio, simulation, system, tcplab
from app.config import APP_VERSION, Settings, get_settings
from app.core.errors import install_error_handlers
from app.logging_setup import configure_logging
from app.state import build_container

log = logging.getLogger("marketlab")


def _connect_persistence(settings: Settings, container) -> None:  # noqa: ANN001
    """Run migrations and start the writer, retrying while the database comes up."""
    from app.persistence.configs import restore_all
    from app.persistence.migrate import migrate

    for attempt in range(1, settings.db_connect_retries + 1):
        try:
            if settings.db_auto_migrate:
                applied = migrate(settings.dsn)  # type: ignore[arg-type]
                if applied:
                    log.info("database migrations applied", extra={"migrations": applied})
            container.sink.start()
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("database not ready", extra={"attempt": attempt, "error": f"{type(exc).__name__}: {exc}"})
            if attempt == settings.db_connect_retries:
                raise RuntimeError("could not connect to PostgreSQL; check MARKETLAB_DB_* settings") from exc
            time.sleep(2)
    restored = restore_all(container)
    log.info("persistent mode active", extra={"instance_id": str(container.sink.instance_id), "restored_configs": restored})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level.value, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings)
        app.state.container = container
        if container.sink.persistent:
            await asyncio.to_thread(_connect_persistence, settings, container)
        await container.sim.start_loop()
        await container.tcp_server.start()
        if settings.sim_autostart:
            container.sim.start()
        log.info(
            "MarketLab backend started",
            extra={"version": APP_VERSION, "persistence": settings.persistence_mode.value, "seed": settings.sim_seed},
        )
        try:
            yield
        finally:
            await container.tcplab.cancel()
            await container.tcp_server.stop()
            await container.sim.stop_loop()
            await asyncio.to_thread(container.sink.stop)
            log.info("MarketLab backend stopped cleanly")

    app = FastAPI(
        title="MarketLab API",
        version=APP_VERSION,
        description="Educational market simulation. All data is hypothetical.",
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        # The default Swagger/ReDoc pages load assets from public CDNs; disabled
        # so the app makes no runtime internet calls (air-gap requirement).
        docs_url=None,
        redoc_url=None,
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(system.router)
    v1.include_router(simulation.router)
    v1.include_router(events.router)
    v1.include_router(marketmaker.router)
    v1.include_router(fx.router)
    v1.include_router(portfolio.router)
    v1.include_router(tcplab.router)
    v1.include_router(history.router)
    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(v1)
    return app


def factory() -> FastAPI:
    """Entry point for ``uvicorn --factory app.main:factory``."""
    return create_app()
