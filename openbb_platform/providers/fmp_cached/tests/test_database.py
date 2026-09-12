"""Unit tests for synchronous MySQL database utilities."""

import asyncio
import os
from unittest.mock import patch

import pytest
from openbb_fmp_cached.utils import database
from openbb_fmp_cached.utils.database import (
    ConnectionPool,
    DatabaseConfig,
    get_connection_pool,
)


def _configured_pool(database_name: str = "configured_db") -> ConnectionPool:
    config = DatabaseConfig.__new__(DatabaseConfig)
    config.config = {
        "host": "localhost",
        "port": 3306,
        "user": "tester",
        "password": "secret",
        "database": database_name,
        "charset": "utf8mb4",
        "test_mode": False,
    }
    return ConnectionPool(config)


def test_database_override_is_scoped_and_nested(monkeypatch):
    """Explicit database selection must restore the prior request scope."""
    configured_pool = _configured_pool()
    monkeypatch.setattr(database, "_connection_pool", configured_pool)

    assert get_connection_pool().connection_params["database"] == "configured_db"
    with database.database_override("alternate_db"):
        assert get_connection_pool().connection_params["database"] == "alternate_db"
        with database.database_override("nested_db"):
            assert get_connection_pool().connection_params["database"] == "nested_db"
        assert get_connection_pool().connection_params["database"] == "alternate_db"
    assert get_connection_pool() is configured_pool
    assert get_connection_pool().connection_params["database"] == "configured_db"


def test_database_override_rejects_invalid_identifier(monkeypatch):
    """A caller-controlled database name is rejected before any DB connection."""
    monkeypatch.setattr(database, "_connection_pool", _configured_pool())

    with (
        pytest.raises(ValueError, match="Invalid SQL identifier"),
        database.database_override("alternate; DROP DATABASE configured_db"),
    ):
        pass


def test_database_override_isolated_between_async_tasks(monkeypatch):
    """Concurrent provider calls must not observe each other's database."""
    monkeypatch.setattr(database, "_connection_pool", _configured_pool())

    async def read_scoped_database(name: str) -> str:
        with database.database_override(name):
            await asyncio.sleep(0)
            return get_connection_pool().connection_params["database"]

    async def gather_results() -> list[str]:
        return list(
            await asyncio.gather(
                read_scoped_database("request_a"),
                read_scoped_database("request_b"),
            )
        )

    assert asyncio.run(gather_results()) == ["request_a", "request_b"]
    assert get_connection_pool().connection_params["database"] == "configured_db"


class TestDatabaseConfig:
    """Test database configuration management."""

    def test_missing_credentials_fail_fast(self):
        """No settings + no env vars must raise (no hardcoded credential defaults)."""
        with patch("os.path.exists", return_value=False), \
             patch.dict(os.environ, {}, clear=True), pytest.raises(ValueError):
            DatabaseConfig()

    def test_credentials_from_env(self):
        """Credentials are sourced from DB_USER/DB_PASSWORD env vars."""
        env = {"DB_USER": "tester", "DB_PASSWORD": "secret"}
        with patch("os.path.exists", return_value=False), \
             patch.dict(os.environ, env, clear=True):
            config = DatabaseConfig()
            assert config.config["host"] == "localhost"
            assert config.config["port"] == 3306
            assert config.config["user"] == "tester"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
