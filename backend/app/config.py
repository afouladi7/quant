"""Application configuration.

Every environment-specific value comes from environment variables prefixed with
``MARKETLAB_`` (or a local ``.env`` file in development). Nothing here is tied to
a particular cluster, hostname, or namespace.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class PersistenceMode(str, Enum):
    MEMORY = "memory"
    POSTGRES = "postgres"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARKETLAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field("local", max_length=32, description="Free-form label shown in /info")
    log_level: LogLevel = LogLevel.INFO
    log_json: bool = True

    persistence_mode: PersistenceMode = PersistenceMode.MEMORY
    database_url: str | None = Field(None, description="Full PostgreSQL URL; alternatively set the db_* parts")
    db_host: str | None = None
    db_port: int = Field(5432, ge=1, le=65535)
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = Field(None, repr=False)
    db_auto_migrate: bool = True
    db_connect_retries: int = Field(30, ge=1, le=300, description="Startup attempts (2 s apart) before giving up")

    # Simulation
    sim_seed: int = Field(42, ge=0, le=2**32 - 1)
    sim_tick_interval_ms: int = Field(250, ge=20, le=5000, description="Wall-clock ms per tick at speed 1.0")
    sim_default_speed: Decimal = Field(Decimal("1"), ge=Decimal("0.1"), le=Decimal("10"))
    sim_autostart: bool = False
    status_broadcast_interval_ms: int = Field(1000, ge=100, le=60000)

    # Bounds (spec §14)
    event_history_limit: int = Field(5000, ge=100, le=100_000)
    ws_queue_size: int = Field(500, ge=10, le=10_000)
    ws_max_clients: int = Field(20, ge=1, le=200)

    # TCP lab: the benchmark client may only target these loopback endpoints of this process.
    tcplab_host: str = Field("127.0.0.1", pattern=r"^(127\.0\.0\.1|::1|localhost)$")
    tcplab_port: int = Field(9500, ge=0, le=65535, description="Raw TCP benchmark listener (0 = pick a free port)")
    http_port: int = Field(8000, ge=1, le=65535, description="Port this backend's HTTP server listens on (HTTP benchmark target)")

    @model_validator(mode="after")
    def _validate_persistence(self) -> "Settings":
        if self.persistence_mode is PersistenceMode.POSTGRES and not self.dsn:
            raise ValueError(
                "persistence_mode=postgres needs MARKETLAB_DATABASE_URL or MARKETLAB_DB_HOST, _DB_NAME, _DB_USER and _DB_PASSWORD"
            )
        return self

    @property
    def dsn(self) -> str | None:
        if self.database_url:
            return self.database_url
        if self.db_host and self.db_name and self.db_user and self.db_password is not None:
            from psycopg.conninfo import make_conninfo

            return make_conninfo(host=self.db_host, port=self.db_port, dbname=self.db_name, user=self.db_user, password=self.db_password)
        return None

    @property
    def is_ephemeral(self) -> bool:
        return self.persistence_mode is PersistenceMode.MEMORY


@lru_cache
def get_settings() -> Settings:
    return Settings()
