"""Minimal, dependency-free SQL migration runner.

Applies ``migrations/NNNN_*.sql`` in order, each in its own transaction, and
records them in ``schema_migrations``. Idempotent. Run automatically at startup
in persistent mode (MARKETLAB_DB_AUTO_MIGRATE=true) or manually:

    python -m app.persistence.migrate            # uses MARKETLAB_* settings
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)
MIGRATIONS = Path(__file__).parent / "migrations"


def migrate(dsn: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations").fetchall()}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            with conn.transaction():
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            applied.append(f.name)
            log.info("applied migration", extra={"migration": f.name})
    return applied


if __name__ == "__main__":  # pragma: no cover
    from app.config import get_settings

    s = get_settings()
    if not s.dsn:
        raise SystemExit("persistent mode is not configured (MARKETLAB_PERSISTENCE_MODE=postgres + database settings)")
    print("applied:", migrate(s.dsn) or "nothing (up to date)")
