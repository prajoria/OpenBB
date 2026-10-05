"""Real FastMCP client regression matrix for reviewed profiles."""

# pylint: disable=protected-access

from collections.abc import AsyncIterator
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp.types import Tool
from openbb_mcp_server.app.app import (
    CAPABILITY_CATALOG_URI,
    create_mcp_server,
)
from openbb_mcp_server.models.settings import MCPSettings
from openbb_portfolio import portfolio_router


@dataclass(frozen=True)
class ProfileBaseline:
    """One profile's real-protocol expectations."""

    name: str
    profile: str | None
    category: str
    callable_tool: str
    callable_arguments: dict[str, Any]
    expected_result: dict[str, Any] | None
    denied_tool: str | None


BASELINES = (
    ProfileBaseline(
        name="compatibility",
        profile=None,
        category="equity",
        callable_tool="equity_price_quote",
        callable_arguments={"symbol": "AAPL"},
        expected_result={"symbol": "AAPL", "provider": "synthetic"},
        denied_tool=None,
    ),
    ProfileBaseline(
        name="platform-standard",
        profile="platform-standard",
        category="equity",
        callable_tool="equity_price_quote",
        callable_arguments={"symbol": "AAPL"},
        expected_result={"symbol": "AAPL", "provider": "synthetic"},
        denied_tool="uscongress_bill_info",
    ),
    ProfileBaseline(
        name="portfolio-read",
        profile="portfolio-read",
        category="portfolio",
        callable_tool="portfolio_portfolio_summary",
        callable_arguments={},
        expected_result=None,
        denied_tool="backtest_bundle_ingest",
    ),
)


def _protocol_app(calls: dict[str, int]) -> FastAPI:
    """Create reviewed allowed, denied, and failing synthetic operations."""
    app = FastAPI()

    def quote(symbol: str) -> dict[str, str]:
        if symbol == "FAIL":
            raise RuntimeError("synthetic handler failure")
        calls["quote"] += 1
        return {"symbol": symbol, "provider": "synthetic"}

    def historical(ready: bool = False) -> dict[str, bool]:
        if not ready:
            raise RuntimeError("synthetic prerequisite unavailable")
        return {"ready": True}

    def backtest_run() -> dict[str, bool]:
        calls["backtest"] += 1
        return {"ok": True}

    def denied_congress() -> dict[str, bool]:
        calls["denied"] += 1
        return {"called": True}

    def denied_ingest() -> dict[str, bool]:
        calls["denied"] += 1
        return {"called": True}

    app.add_api_route(
        "/api/v1/equity/price/quote",
        quote,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/v1/equity/price/historical",
        historical,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/v1/backtest/run",
        backtest_run,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/v1/uscongress/bill_info",
        denied_congress,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/v1/backtest/bundle/ingest",
        denied_ingest,
        methods=["POST"],
    )
    return app


def _profile_server(
    profile: str | None = "platform-standard",
    *,
    discovery: bool = True,
):
    """Build a profile server while keeping this matrix synthetic and offline."""
    calls = {
        "quote": 0,
        "backtest": 0,
        "denied": 0,
    }
    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        runtime_profile=profile,
        enable_tool_discovery=discovery,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    app = _protocol_app(calls)
    auth = ("synthetic-user", "x" * 32) if profile == "portfolio-read" else None
    server = create_mcp_server(settings, app, auth=auth)
    return server, calls


async def _all_tool_pages(client: Client) -> AsyncIterator[list[Tool]]:
    """Yield every tools/list page using protocol cursors."""
    cursor: str | None = None
    while True:
        page = await client.list_tools_mcp(cursor=cursor)
        yield page.tools
        if not page.nextCursor:
            break
        cursor = page.nextCursor


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", BASELINES, ids=lambda item: item.name)
async def test_profile_initialize_activate_list_call_and_deny(
    baseline: ProfileBaseline,
):
    """Each profile initializes, activates, invokes, and denies over MCP."""
    server, calls = _profile_server(baseline.profile)
    client = Client(
        server,
        name=f"{baseline.name}-matrix",
        auto_initialize=False,
    )

    async with client:
        initialize = await client.initialize()
        assert initialize.serverInfo.name == "OpenBB MCP"

        initial_names = {tool.name for tool in await client.list_tools()}
        assert baseline.callable_tool not in initial_names
        activation = await client.call_tool(
            "activate_category",
            {"category": baseline.category},
        )
        assert not activation.is_error

        tools = {tool.name: tool for tool in await client.list_tools()}
        assert baseline.callable_tool in tools
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
        backend = (
            patch.object(
                portfolio_router,
                "get_portfolio_basket_df",
                return_value=frame,
            )
            if baseline.profile == "portfolio-read"
            else nullcontext()
        )
        with backend:
            result = await client.call_tool(
                baseline.callable_tool,
                baseline.callable_arguments,
            )
        assert not result.is_error
        if baseline.expected_result is None:
            assert "SYNTH" in str(result.structured_content)
            assert "PRIVATE" not in str(result.structured_content)
        else:
            assert result.structured_content == baseline.expected_result

        if baseline.denied_tool is None:
            await client.call_tool(
                "activate_category",
                {"category": "uscongress"},
            )
            compatibility = await client.call_tool(
                "uscongress_bill_info",
                {},
            )
            assert compatibility.structured_content == {"called": True}
        else:
            with pytest.raises(ToolError, match="denied"):
                await client.call_tool(baseline.denied_tool, {})

    assert calls["denied"] == (1 if baseline.profile is None else 0)


@pytest.mark.asyncio
async def test_protocol_pagination_schema_prompt_and_resource_access():
    """Pagination and serialized schemas survive the real client boundary."""
    server, _ = _profile_server()

    async with Client(server, name="pagination-matrix") as client:
        expected_names = [tool.name for tool in await client.list_tools()]
        server._list_page_size = 2
        pages = [page async for page in _all_tool_pages(client)]
        names = [tool.name for page in pages for tool in page]
        assert len(pages) > 1
        assert names == expected_names

        await client.call_tool("activate_category", {"category": "equity"})
        server._list_page_size = None
        expected_active_names = [tool.name for tool in await client.list_tools()]
        server._list_page_size = 2
        active_pages = [page async for page in _all_tool_pages(client)]
        active_names = [tool.name for page in active_pages for tool in page]
        assert len(active_pages) > 1
        assert active_names == expected_active_names

        tools = {tool.name: tool for tool in await client.list_tools()}
        quote_schema = tools["equity_price_quote"].inputSchema
        assert quote_schema["required"] == ["symbol"]
        assert quote_schema["properties"]["symbol"]["type"] == "string"

        prompts = await client.list_prompts()
        assert len(prompts) == 43
        assert "system_prompt" in {prompt.name for prompt in prompts}
        rendered = await client.get_prompt("system_prompt")
        assert rendered.messages

        resources = await client.list_resources()
        assert CAPABILITY_CATALOG_URI in {str(resource.uri) for resource in resources}
        contents = await client.read_resource(CAPABILITY_CATALOG_URI)
        assert len(contents) == 1
        assert contents[0].mimeType == "application/json"
        assert '"schema_version": "1.0"' in contents[0].text


@pytest.mark.asyncio
async def test_two_clients_keep_activation_and_invocation_independent():
    """One client's activation never changes another client's tool surface."""
    server, calls = _profile_server()

    async with (
        Client(server, name="equity-session") as equity_client,
        Client(server, name="backtest-session") as backtest_client,
    ):
        await equity_client.call_tool(
            "activate_category",
            {"category": "equity"},
        )
        equity_names = {tool.name for tool in await equity_client.list_tools()}
        other_names = {tool.name for tool in await backtest_client.list_tools()}
        assert "equity_price_quote" in equity_names
        assert "equity_price_quote" not in other_names

        with pytest.raises(ToolError, match="Unknown tool"):
            await backtest_client.call_tool(
                "equity_price_quote",
                {"symbol": "MSFT"},
            )

        await backtest_client.call_tool(
            "activate_category",
            {"category": "backtest"},
        )
        backtest_names = {tool.name for tool in await backtest_client.list_tools()}
        equity_names = {tool.name for tool in await equity_client.list_tools()}
        assert "backtest_run" in backtest_names
        assert "backtest_run" not in equity_names

        quote = await equity_client.call_tool(
            "equity_price_quote",
            {"symbol": "MSFT"},
        )
        backtest = await backtest_client.call_tool("backtest_run", {})
        assert quote.structured_content == {
            "symbol": "MSFT",
            "provider": "synthetic",
        }
        assert backtest.structured_content == {"ok": True}

    assert calls["quote"] == 1
    assert calls["backtest"] == 1


@pytest.mark.asyncio
async def test_handler_and_prerequisite_failures_are_protocol_errors():
    """Handler faults and missing prerequisites never become success payloads."""
    server, calls = _profile_server()

    async with Client(server, name="error-matrix") as client:
        await client.call_tool("activate_category", {"category": "equity"})
        with pytest.raises(ToolError, match="synthetic handler failure"):
            await client.call_tool(
                "equity_price_quote",
                {"symbol": "FAIL"},
            )
        with pytest.raises(
            ToolError,
            match="synthetic prerequisite unavailable",
        ):
            await client.call_tool(
                "equity_price_historical",
                {"ready": False},
            )

    assert calls["quote"] == 0
