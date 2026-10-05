"""Portfolio MCP private-data and availability boundaries."""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp.server.auth import AuthProvider
from openbb_mcp_server.adapters.portfolio import compose_portfolio_app
from openbb_mcp_server.app.app import (
    _validate_portfolio_transport_security,
    create_mcp_server,
)
from openbb_mcp_server.app.auth import get_auth_provider
from openbb_mcp_server.models.settings import MCPSettings
from openbb_portfolio import portfolio_router


def _client() -> TestClient:
    return TestClient(compose_portfolio_app(FastAPI()))


@pytest.mark.parametrize(
    "path",
    [
        "/portfolio/positions",
        "/portfolio/allocation",
        "/portfolio/cost_basis",
        "/portfolio/tax_summary",
    ],
)
def test_raw_private_operations_remain_explicitly_blocked(path):
    """Raw lot, owner, account, cost, and tax operations never return data."""
    response = _client().get(
        path,
        params={"owner": "PRIVATE", "account": "PRIVATE", "symbol": "SYNTH"},
    )
    assert response.status_code == 403
    assert "Raw lot-level portfolio access is disabled" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "patch_name"),
    [
        ("/portfolio/summary", "get_portfolio_basket_df"),
        ("/portfolio/performance", "get_portfolio_basket_df"),
        ("/espp/purchases", "get_espp_df"),
    ],
)
def test_private_direct_operations_omit_owner_and_account_fields(path, patch_name):
    """Defense-in-depth strips identifiers even if an upstream frame adds them."""
    frame = pd.DataFrame(
        [
            {
                "symbol": "SYNTH",
                "pct_return": 0.1,
                "portfolio_weight_pct": 100.0,
                "owner": "PRIVATE",
                "account": "PRIVATE",
                "account_name": "PRIVATE",
                "purchase_deposit_to": "PRIVATE",
            }
        ]
    )
    with patch.object(portfolio_router, patch_name, return_value=frame):
        response = _client().get(path)
    assert response.status_code == 200
    assert response.json()
    assert {
        "owner",
        "account",
        "account_name",
        "purchase_deposit_to",
    }.isdisjoint(response.json()[0])


@pytest.mark.parametrize(
    ("path", "patch_name"),
    [
        ("/portfolio/summary", "get_portfolio_basket_df"),
        ("/portfolio/performance", "get_portfolio_basket_df"),
        ("/portfolio/snapshots", "get_all_basket_snapshots_df"),
        ("/espp/purchases", "get_espp_df"),
        ("/equity/historical", "get_equity_historical_df"),
    ],
)
def test_database_unavailability_is_not_reported_as_empty_success(path, patch_name):
    """Missing credentials surface an explicit failure rather than an empty portfolio."""
    with patch.object(
        portfolio_router,
        patch_name,
        side_effect=ValueError("Missing MySQL credential(s): MYSQL_USER"),
    ), pytest.raises(ValueError, match="Missing MySQL credential"):
        _client().get(path)


@pytest.mark.asyncio
async def test_sanitized_portfolio_summary_invokes_through_mcp():
    """An admitted private read completes MCP conversion without leaking identifiers."""
    frame = pd.DataFrame(
        [
            {
                "symbol": "SYNTH",
                "total_current_value": 123.0,
                "pct_return": 0.1,
                "portfolio_weight_pct": 100.0,
                "owner": "PRIVATE",
                "account_name": "PRIVATE",
            }
        ]
    )
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-read",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    mcp = create_mcp_server(
        settings,
        FastAPI(),
        auth=("synthetic-user", "x" * 32),
    )
    with patch.object(
        portfolio_router,
        "get_portfolio_basket_df",
        return_value=frame,
    ):
        result = await mcp.call_tool("portfolio_portfolio_summary", {})
    payload = str(result)
    assert "SYNTH" in payload
    assert "PRIVATE" not in payload


def test_espp_widget_does_not_request_private_deposit_account():
    """Workspace metadata stays aligned with the sanitized ESPP response."""
    path = Path(__file__).parents[3] / "portfolio" / "assets" / "widgets.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert "purchase_deposit_to" not in json.dumps(document)


@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
@pytest.mark.parametrize(
    "server_auth",
    [
        None,
        ("", "x" * 32),
        ("synthetic-user", ""),
        ("   ", "x" * 32),
        ("synthetic-user", "\t"),
    ],
)
def test_portfolio_network_transports_require_authentication(
    profile,
    server_auth,
):
    """Private profiles cannot bind an unauthenticated HTTP MCP service."""
    settings = MCPSettings(capability_profile=profile, server_auth=server_auth)
    with pytest.raises(RuntimeError, match="requires server authentication"):
        _validate_portfolio_transport_security(settings, "streamable-http")


@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
def test_portfolio_stdio_and_authenticated_network_transports_are_allowed(profile):
    """Local stdio remains usable while network access requires credentials."""
    local = MCPSettings(capability_profile=profile, server_auth=None)
    authenticated = MCPSettings(
        capability_profile=profile,
        server_auth=("synthetic-user", "x" * 32),
    )
    _validate_portfolio_transport_security(local, "stdio")
    _validate_portfolio_transport_security(authenticated, "streamable-http")


def test_programmatic_portfolio_server_requires_effective_auth_by_default():
    """The public factory fails closed because callers may start network transport."""
    settings = MCPSettings(capability_profile="portfolio-read")
    with pytest.raises(RuntimeError, match="requires effective authentication"):
        create_mcp_server(settings, FastAPI())


def test_programmatic_portfolio_server_accepts_token_auth_provider():
    """The repository TokenAuthProvider is retained as effective authentication."""
    settings = MCPSettings(capability_profile="portfolio-read")
    auth_settings = MCPSettings(server_auth=("synthetic-user", "x" * 32))
    provider = get_auth_provider(auth_settings)
    mcp = create_mcp_server(settings, FastAPI(), auth=provider)
    assert mcp.auth is provider


def test_programmatic_portfolio_server_treats_custom_provider_as_opaque():
    """Custom AuthProvider implementation details are not misinterpreted."""

    class CustomProvider(AuthProvider):
        server_auth = object()

        async def verify_token(self, token: str):
            return None

    settings = MCPSettings(capability_profile="portfolio-read")
    provider = CustomProvider()
    mcp = create_mcp_server(settings, FastAPI(), auth=provider)
    assert mcp.auth is provider


def test_programmatic_portfolio_server_uses_explicit_credentials():
    """Credential tuples protect the server even when settings contain no auth."""
    settings = MCPSettings(capability_profile="portfolio-read")
    credentials = ("explicit-user", "y" * 32)
    mcp = create_mcp_server(settings, FastAPI(), auth=credentials)
    assert mcp.auth.server_auth == credentials


def test_programmatic_portfolio_server_rejects_ineffective_known_provider():
    """Known TokenAuthProvider instances cannot hide blank credentials."""
    settings = MCPSettings(capability_profile="portfolio-read")
    provider = get_auth_provider(
        MCPSettings(server_auth=("   ", "\t")),
    )
    with pytest.raises(RuntimeError, match="requires effective authentication"):
        create_mcp_server(settings, FastAPI(), auth=provider)
