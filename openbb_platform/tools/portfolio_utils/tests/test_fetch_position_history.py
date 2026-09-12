"""Regression tests for explicit database propagation in position-history warmers."""

from __future__ import annotations

from typing import Any

from openbb_fmp_cached.utils import database as database_module
from openbb_fmp_cached.utils.database import (
    ConnectionPool,
    DatabaseConfig,
    get_connection_pool,
)
from portfolio_utils import fetch_position_history as tool


def test_run_position_history_warm_threads_database_to_default_fetcher(monkeypatch):
    """The default fmp_cached fetch path scopes cache work to the explicit DB."""
    config = DatabaseConfig.__new__(DatabaseConfig)
    config.config = {
        "host": "localhost",
        "port": 3306,
        "user": "tester",
        "password": "secret",
        "database": "configured_db",
        "charset": "utf8mb4",
        "test_mode": False,
    }
    monkeypatch.setattr(database_module, "_connection_pool", ConnectionPool(config))
    observed: list[str] = []

    def fake_scoped_fetch(
        symbol: str,
        *,
        start_date: Any,
        end_date: Any,
        credentials: dict | None,
    ) -> dict[str, Any]:
        observed.append(get_connection_pool().connection_params["database"])
        return {
            "rows": 1,
            "first": str(start_date),
            "last": str(end_date),
            "cache_tag": "FETCH",
        }

    monkeypatch.setattr(tool, "_fetch_one_symbol_history_in_scope", fake_scoped_fetch)

    result = tool.run_position_history_warm(
        symbols=["MSFT"],
        years=1,
        database="alternate_db",
        skip_holiday_prestep=True,
        api_key_resolver=lambda: "test-key",
        readiness_fn=lambda symbols, database: {},
    )

    assert result.success == ["MSFT"]
    assert observed == ["alternate_db"]
    assert get_connection_pool().connection_params["database"] == "configured_db"


def test_injected_position_fetcher_keeps_existing_signature():
    """Database plumbing must not break injected job/test collaborators."""

    def injected_fetch(
        symbol: str,
        *,
        start_date: Any,
        end_date: Any,
        credentials: dict | None,
    ) -> dict[str, Any]:
        return {
            "rows": 1,
            "first": str(start_date),
            "last": str(end_date),
            "cache_tag": "FETCH",
        }

    result = tool.run_position_history_warm(
        symbols=["MSFT"],
        database="alternate_db",
        skip_holiday_prestep=True,
        fetch_one_fn=injected_fetch,
        api_key_resolver=lambda: "test-key",
        readiness_fn=lambda symbols, database: {},
    )

    assert result.success == ["MSFT"]
