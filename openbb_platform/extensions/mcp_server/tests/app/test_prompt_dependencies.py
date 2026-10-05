"""Structured prompt dependency readiness contracts."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import PromptError
from openbb_mcp_server.app.app import _add_prompts_from_json, _provider_values
from openbb_mcp_server.models.prompts import (
    PromptDependencies,
    evaluate_prompt_dependencies,
)
from openbb_mcp_server.models.settings import MCPSettings


def test_conditional_tools_resources_providers_and_packages():
    """Every structured dependency kind contributes to readiness."""
    dependencies = PromptDependencies(
        required_tools=("renamed_quote",),
        any_tool_groups=(("ratio_a", "ratio_b"),),
        providers=("fmp_cached",),
        optional_packages=("openbb-financialtoolkit",),
        resources=("resource://coverage",),
    )
    ready = evaluate_prompt_dependencies(
        dependencies,
        tools={"renamed_quote", "ratio_b"},
        providers={"fmp_cached"},
        packages={"openbb-financialtoolkit"},
        resources={"resource://coverage"},
    )
    assert ready.available

    missing = evaluate_prompt_dependencies(
        dependencies,
        tools={"renamed_quote"},
        providers=set(),
        packages=set(),
        resources=set(),
    )
    assert not missing.available
    assert set(missing.reasons) == {
        "missing one-of tools: ratio_a, ratio_b",
        "missing provider: fmp_cached",
        "missing optional package: openbb-financialtoolkit",
        "missing resource: resource://coverage",
    }


def test_optional_literal_provider_values_are_discovered():
    """Provider readiness handles FastAPI's optional Literal anyOf shape."""
    schema = {
        "anyOf": [
            {"type": "string", "enum": ["fmp", "fmp_cached"]},
            {"type": "null"},
        ]
    }
    assert _provider_values(schema) == {"fmp", "fmp_cached"}
    assert _provider_values({"enum": ["yfinance"]}) == {"yfinance"}


@pytest.mark.asyncio
async def test_unavailable_prompt_is_marked_and_refuses_render(tmp_path):
    """Missing operations are never presented as executable prompt guidance."""
    document = [
        {
            "name": "needs_missing",
            "description": "Needs a missing tool.",
            "content": "Call `missing_tool` for {symbol}.",
            "arguments": [
                {
                    "name": "symbol",
                    "type": "str",
                    "description": "Ticker",
                }
            ],
            "dependencies": {
                "required_tools": ["missing_tool"],
                "any_tool_groups": [],
                "providers": [],
                "optional_packages": [],
                "resources": [],
            },
        }
    ]
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    settings = MCPSettings(
        server_prompts_file=str(path),
        default_skills_dir=None,
    )
    mcp = MagicMock()
    _add_prompts_from_json(
        mcp,
        settings,
        available_tools={"renamed_quote"},
    )
    prompt = mcp.add_prompt.call_args.args[0]
    assert "unavailable" in prompt.tags
    assert "missing tool: missing_tool" in prompt.description
    with pytest.raises(PromptError, match="Prompt unavailable"):
        await prompt.render({"symbol": "SYNTH"})


def test_tool_renaming_and_full_discoverable_surface_drive_readiness(tmp_path):
    """Dependencies resolve against effective names beyond startup activation."""
    document = [
        {
            "name": "renamed",
            "description": "Uses a renamed discoverable tool.",
            "content": "Call `renamed_quote`.",
            "dependencies": {
                "required_tools": ["renamed_quote"],
                "any_tool_groups": [],
                "providers": ["fmp_cached"],
                "optional_packages": ["openbb-financialtoolkit"],
                "resources": ["resource://coverage"],
            },
        }
    ]
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    settings = MCPSettings(
        server_prompts_file=str(path),
        default_skills_dir=None,
    )
    mcp = MagicMock()
    with patch(
        "openbb_mcp_server.app.app.importlib.metadata.version",
        return_value="1.0",
    ):
        _add_prompts_from_json(
            mcp,
            settings,
            available_tools={"renamed_quote"},
            available_providers={"fmp_cached"},
            available_resources={"resource://coverage"},
        )
    prompt = mcp.add_prompt.call_args.args[0]
    assert prompt.readiness.available
    assert "unavailable" not in prompt.tags


def test_every_bundled_prompt_declares_structured_dependencies():
    """No bundled prompt relies on prose-only operation references."""
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert len(document) == 42
    assert "economy_economic_calendar" not in json.dumps(document)
    for prompt in document:
        dependencies = PromptDependencies.model_validate(prompt["dependencies"])
        assert isinstance(dependencies.required_tools, tuple)


def test_portfolio_and_refresh_prompts_declare_effective_dependencies():
    """Explicit adapter names and dual-provider requirements are locked."""
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    document = {
        prompt["name"]: prompt
        for prompt in json.loads(path.read_text(encoding="utf-8"))
    }
    portfolio = PromptDependencies.model_validate(
        document["portfolio_stock_deep_dive"]["dependencies"]
    )
    assert set(portfolio.required_tools) == {
        "portfolio_stock_context",
        "portfolio_stock_profile",
        "portfolio_stock_fundamentals",
        "portfolio_stock_technicals",
        "portfolio_stock_valuation",
        "portfolio_stock_risk",
        "portfolio_stock_relative",
        "portfolio_stock_decision",
    }
    assert "`stock_context`" not in document["portfolio_stock_deep_dive"]["content"]
    refresh = PromptDependencies.model_validate(
        document["fmp_cached_portfolio_refresh"]["dependencies"]
    )
    assert refresh.providers == ("fmp_cached", "fmp")
    global_market = PromptDependencies.model_validate(
        document["global_market_overview"]["dependencies"]
    )
    assert set(global_market.required_tools) == {
        "index_price_historical",
        "fixedincome_government_treasury_rates",
        "currency_price_historical",
        "commodity_price_spot",
        "economy_calendar",
    }
