"""Tests for openbb_agents.mcp_server — tool discovery & schema generation.

These tests exercise the in-process introspection helpers (no stdio transport,
no DB). They verify that public tool functions are auto-discovered, that JSON
schemas are derived from type hints, and that a discovered tool can be invoked.
"""

import sys
from pathlib import Path

# Ensure the extension package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestToolDiscovery:
    def test_collect_tools_finds_public_functions(self):
        from openbb_agents.mcp_server import collect_tools

        tools = collect_tools()
        names = {t["name"] for t in tools}
        # Portfolio tools layer is implemented; these must be registered.
        assert "get_positions" in names
        assert "get_sector_exposure" in names

    def test_private_functions_excluded(self):
        from openbb_agents.mcp_server import collect_tools

        tools = collect_tools()
        names = {t["name"] for t in tools}
        # Underscore-prefixed helpers must never be exposed as tools.
        assert not any(n.startswith("_") for n in names)
        assert "_default_fetch" not in names


class TestSchemaGeneration:
    def test_input_schema_is_valid_json_schema_object(self):
        from openbb_agents.mcp_server import build_input_schema

        def sample(symbol: str, limit: int = 4) -> dict:
            """Sample tool."""
            return {}

        schema = build_input_schema(sample)
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "symbol" in schema["properties"]
        assert schema["properties"]["symbol"]["type"] == "string"
        assert schema["properties"]["limit"]["type"] == "integer"
        # Required params (no default) listed; optional ones not.
        assert "symbol" in schema["required"]
        assert "limit" not in schema["required"]


class TestInvocation:
    def test_call_collected_tool_returns_result(self):
        from openbb_agents.mcp_server import collect_tools

        tools = {t["name"]: t for t in collect_tools()}
        # get_positions accepts an injected _fetch via kwargs passthrough.
        import pandas as pd

        fake = lambda: pd.DataFrame(
            [{"symbol": "MSFT", "total_quantity": 1, "total_cost_basis": 1.0,
              "total_current_value": 2.0, "pct_return": 100.0,
              "portfolio_weight_pct": 100.0}]
        )
        result = tools["get_positions"]["fn"](_fetch=fake)
        assert isinstance(result, list)
        assert result[0]["symbol"] == "MSFT"
