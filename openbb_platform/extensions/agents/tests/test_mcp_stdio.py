"""Real stdio validation for sanitized Agents portfolio tools."""

import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _script(mode: str = "data") -> str:
    return f"""
import pandas as pd
from openbb_agents.tools import portfolio_tools
mode = {mode!r}
if mode == "data":
    portfolio_tools._default_fetch = lambda: pd.DataFrame([{{
        "symbol": "SYNTH",
        "total_quantity": 2,
        "total_cost_basis": 10.0,
        "total_current_value": 12.0,
        "pct_return": 20.0,
        "portfolio_weight_pct": 100.0,
        "owner": "PRIVATE_OWNER",
        "account_name": "PRIVATE_ACCOUNT",
        "avg_cost_basis": 5.0,
    }}])
    portfolio_tools._default_profile = lambda symbol: {{
        "symbol": symbol, "sector": "Synthetic Sector"
    }}
elif mode == "empty":
    portfolio_tools._default_fetch = lambda: pd.DataFrame()
elif mode == "basket_error":
    def fail_fetch():
        raise RuntimeError("C:/private/basket.db password=SECRET")
    portfolio_tools._default_fetch = fail_fetch
elif mode == "profile_error":
    portfolio_tools._default_fetch = lambda: pd.DataFrame([{{
        "symbol": "SYNTH", "total_current_value": 12.0
    }}])
    def fail_profile(symbol):
        raise RuntimeError(
            "C:/private/profile.db credential=SECRET " + symbol
        )
    portfolio_tools._default_profile = fail_profile
from openbb_agents.mcp_server import main
main()
"""


async def _call(mode: str, tool: str):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", _script(mode)],
        env=os.environ.copy(),
    )
    with anyio.fail_after(30):
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "openbb-agents"
            listed = await session.list_tools()
            assert {item.name for item in listed.tools} == {
                "get_positions",
                "get_sector_exposure",
            }
            return await session.call_tool(tool, {})


@pytest.mark.asyncio
async def test_positions_and_sector_exposure_are_sanitized_over_stdio():
    """Direct MCP calls remain safe without relying on ADK callbacks."""
    positions = await _call("data", "get_positions")
    sector = await _call("data", "get_sector_exposure")
    assert positions.isError is False
    assert sector.isError is False
    combined = positions.content[0].text + sector.content[0].text
    assert "SYNTH" in combined
    assert "Synthetic Sector" in combined
    assert not any(
        value in combined
        for value in (
            "PRIVATE_OWNER",
            "PRIVATE_ACCOUNT",
            "account_name",
            "owner",
            "avg_cost_basis",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "tool"),
    [
        ("basket_error", "get_positions"),
        ("profile_error", "get_sector_exposure"),
    ],
)
async def test_dependency_failures_are_sanitized_over_stdio(mode: str, tool: str):
    """Unavailable basket/profile dependencies signal errors without leaks."""
    result = await _call(mode, tool)
    assert result.isError is True
    text = result.content[0].text
    assert "tool_failed" in text
    assert "private" not in text.lower()
    assert "SECRET" not in text


@pytest.mark.asyncio
async def test_empty_basket_is_an_explicit_empty_success():
    """An available but empty sanitized basket returns empty lists."""
    positions = await _call("empty", "get_positions")
    sector = await _call("empty", "get_sector_exposure")
    assert positions.isError is sector.isError is False
    assert positions.content[0].text == "[]"
    assert sector.content[0].text == "[]"
