"""Sanitized, read-only FMP cache observability contracts."""

import builtins
from datetime import UTC, datetime, timedelta

import pymysql
import pytest
from fastapi import FastAPI
from openbb_mcp_server.adapters.cache_admin import (
    build_cache_coverage,
    build_cache_health,
)
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings


def test_available_cache_health_is_bounded_and_sanitized():
    """Health returns aggregates and freshness, never rows or connection data."""
    now = datetime.now(UTC)
    calls = []

    def query(sql, params=()):
        calls.append((sql, params))
        return [
            {
                "table_count": 12,
                "estimated_row_count": 345,
                "freshest_at": now,
                "stalest_at": now - timedelta(hours=2),
            }
        ]

    result = build_cache_health(query_fn=query, now=now)
    assert result.model_dump(mode="json") == {
        "availability": "available",
        "implementation_type": "mysql_read_only_aggregate",
        "table_count": 12,
        "estimated_row_count": 345,
        "freshest_at": now.isoformat().replace("+00:00", "Z"),
        "stalest_at": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "stale": False,
        "detail": None,
    }
    assert len(calls) == 1
    assert calls[0][0].lstrip().upper().startswith("SELECT")
    serialized = str(result.model_dump()).lower()
    assert not any(
        token in serialized
        for token in ("password", "connection", "select ", "host", "account")
    )


def test_empty_and_stale_cache_states_are_explicit():
    """Empty and stale stores never look like healthy populated caches."""
    now = datetime.now(UTC)
    empty = build_cache_health(
        query_fn=lambda *_: [
            {
                "table_count": 0,
                "estimated_row_count": 0,
                "freshest_at": None,
                "stalest_at": None,
            }
        ],
        now=now,
    )
    assert empty.availability == "empty"
    assert empty.stale is None
    initialized_empty = build_cache_health(
        query_fn=lambda *_: [
            {
                "table_count": 12,
                "estimated_row_count": 0,
                "freshest_at": None,
                "stalest_at": None,
            }
        ],
        now=now,
    )
    assert initialized_empty.availability == "empty"
    assert initialized_empty.table_count == 12

    old = now - timedelta(days=10)
    stale = build_cache_health(
        query_fn=lambda *_: [
            {
                "table_count": 2,
                "estimated_row_count": 4,
                "freshest_at": old,
                "stalest_at": old,
            }
        ],
        now=now,
        stale_after=timedelta(days=1),
    )
    assert stale.availability == "stale"
    assert stale.stale is True


@pytest.mark.parametrize(
    ("error", "availability"),
    [
        (ValueError("Missing MySQL credential(s)"), "unavailable"),
        (
            pymysql.err.OperationalError(1044, "permission denied"),
            "permission_denied",
        ),
    ],
)
def test_database_failures_are_explicit_and_redacted(error, availability):
    """Missing configuration and permissions never become empty success."""

    def fail(*_args, **_kwargs):
        raise error

    result = build_cache_health(query_fn=fail)
    assert result.availability == availability
    assert result.table_count is None
    assert result.estimated_row_count is None
    assert str(error) not in (result.detail or "")


def test_coverage_accounts_for_persistent_and_non_persistent_fetchers():
    """Coverage keeps the full 181 denominator and explicit persistence split."""
    result = build_cache_coverage()
    assert result.registered_models == 181
    assert result.routed_models == 181
    assert result.persistent_models == 123
    assert result.non_persistent_models == 58
    assert result.availability == "available"
    assert result.implementation_type == "provider_registration_metadata"


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
async def test_portfolio_profiles_expose_only_sanitized_cache_tools(profile):
    """Reviewed profiles expose bounded health and coverage through real MCP."""
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        FastAPI(),
        auth=("synthetic-user", "x" * 32),
    )
    names = {tool.name for tool in await mcp.list_tools()}
    assert {"cache_health", "cache_coverage"} <= names
    result = await mcp.call_tool("cache_coverage", {})
    text = str(result)
    assert "181" in text
    assert "password" not in text.lower()
    assert "connection" not in text.lower()


def test_standard_profile_does_not_import_optional_cache_provider(monkeypatch):
    """The optional provider remains absent-safe for the standard MCP."""
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "openbb_mcp_server.adapters.cache_admin":
            raise AssertionError("optional cache adapter imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="platform-standard",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    create_mcp_server(settings, FastAPI())
