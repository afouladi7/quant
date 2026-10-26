import pytest
from pydantic import ValidationError

from tests.conftest import make_settings


def test_defaults_are_ephemeral() -> None:
    s = make_settings()
    assert s.persistence_mode.value == "memory"
    assert s.is_ephemeral


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETLAB_SIM_SEED", "7")
    monkeypatch.setenv("MARKETLAB_LOG_LEVEL", "DEBUG")
    s = make_settings()
    assert s.sim_seed == 7
    assert s.log_level.value == "DEBUG"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sim_tick_interval_ms": 5},
        {"event_history_limit": 10},
        {"ws_queue_size": 0},
        {"sim_default_speed": "50"},
        {"sim_seed": -1},
        {"log_level": "LOUD"},
    ],
)
def test_rejects_nonsense(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_postgres_requires_connection_settings() -> None:
    with pytest.raises(ValidationError, match="needs MARKETLAB_DATABASE_URL"):
        make_settings(persistence_mode="postgres")


def test_postgres_dsn_from_parts() -> None:
    s = make_settings(persistence_mode="postgres", db_host="db", db_name="ml", db_user="u", db_password="p w")
    assert s.dsn is not None and "host=db" in s.dsn and "dbname=ml" in s.dsn
    assert "p w" not in repr(s)  # password excluded from repr
