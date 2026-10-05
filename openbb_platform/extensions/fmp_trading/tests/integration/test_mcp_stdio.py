"""Real stdio protocol verification for the Daytrade MCP CLI."""

import os
import subprocess
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_TOOLS = {
    "quote_batch",
    "market_movers",
    "company_news",
    "session_status",
    "journal_summary",
    "fills_for_session",
}


def _server_script(*, fail_tool: str | None = None) -> str:
    failure = repr(fail_tool)
    return f"""
import sys
import openbb_fmp_trading.agent as agent
agent._AGENT_EXTRA_AVAILABLE = True
from openbb_fmp_trading.agent import tool_registry
def make_dispatch(name):
    def dispatch(**arguments):
        if name == {failure}:
            raise RuntimeError(
                "C:/private/journal.ndjson password=SECRET"
            )
        return {{"tool": name, "arguments": arguments}}
    return dispatch
for schema in tool_registry.PRE_OPEN_TOOLS + tool_registry.POST_CLOSE_TOOLS:
    if schema.mcp_exposed:
        schema.dispatch = make_dispatch(schema.name)
from openbb_fmp_trading.cli.main import main
raise SystemExit(main(["mcp-serve"]))
"""


@pytest.mark.asyncio
async def test_real_cli_lists_invokes_and_terminates_cleanly():
    """Initialize, list and invoke every tool over a real owned subprocess."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", _server_script()],
        env=os.environ.copy(),
    )
    with anyio.fail_after(30):
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "openbb-daytrade"
            listed = await session.list_tools()
            assert {tool.name for tool in listed.tools} == _TOOLS
            calls = {
                "quote_batch": {"symbols": ["SYNTH"]},
                "market_movers": {"direction": "gainers", "limit": 1},
                "company_news": {"symbol": "SYNTH", "limit": 1},
                "session_status": {},
                "journal_summary": {"session_id": "s20260101120000"},
                "fills_for_session": {"session_id": "s20260101120000"},
            }
            for name, arguments in calls.items():
                result = await session.call_tool(name, arguments)
                assert result.isError is False
                assert name in result.content[0].text


@pytest.mark.asyncio
async def test_handler_failure_and_schema_mismatch_are_protocol_errors():
    """Errors remain bounded and never expose journal paths or credentials."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", _server_script(fail_tool="company_news")],
        env=os.environ.copy(),
    )
    with anyio.fail_after(30):
        async with (
            stdio_client(parameters) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            failed = await session.call_tool(
                "company_news",
                {"symbol": "SYNTH", "limit": 1},
            )
            text = failed.content[0].text
            assert failed.isError is True
            assert "tool_failed" in text
            assert "journal.ndjson" not in text
            assert "SECRET" not in text

            invalid = await session.call_tool(
                "market_movers",
                {"direction": "invalid"},
            )
            assert invalid.isError is True

            for forbidden in ("submit_order", "submit_daily_plan"):
                denied = await session.call_tool(forbidden, {})
                assert denied.isError is True


def test_missing_agent_extra_exits_cleanly_on_stderr():
    """Missing extras never corrupt stdout with non-protocol text."""
    script = """
import sys
import openbb_fmp_trading.agent as agent
agent._AGENT_EXTRA_AVAILABLE = False
from openbb_fmp_trading.cli.main import main
raise SystemExit(main(["mcp-serve"]))
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "[agent] extra dependencies missing" in result.stderr
