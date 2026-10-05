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
    assert refresh.providers == ()
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


def test_catalog_uses_supported_fundamental_tools():
    """Corrected prompts reference exact emitted fundamental tool names."""
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    prompts = {prompt["name"]: prompt for prompt in document}
    corrected_prompts = {
        "equity_deep_dive",
        "equity_peer_comparison",
        "factor_exposure_analysis",
    }

    for prompt in document:
        assert "equity_fundamental_overview" not in prompt["content"]
        assert (
            "equity_fundamental_overview"
            not in prompt["dependencies"]["required_tools"]
        )

    for name in corrected_prompts:
        required_tools = prompts[name]["dependencies"]["required_tools"]
        assert "equity_fundamental_metrics" in required_tools

    for name in corrected_prompts:
        assert (
            "equity_fundamental_ratios"
            in prompts[name]["dependencies"]["required_tools"]
        )

    deep_dive = prompts["equity_deep_dive"]
    provider_argument = next(
        argument
        for argument in deep_dive["arguments"]
        if argument["name"] == "provider"
    )
    assert provider_argument["default"] == "fmp"
    assert deep_dive["dependencies"]["providers"] == ["fmp"]
    assert (
        "`equity_fundamental_metrics` with symbol={symbol}, " "provider={provider}"
    ) in deep_dive["content"]
    assert (
        "`equity_fundamental_ratios` with symbol={symbol}, " "provider={provider}"
    ) in deep_dive["content"]
    peer_content = prompts["equity_peer_comparison"]["content"]
    assert (
        "`equity_fundamental_metrics` with symbol set to that peer and "
        "provider={provider}"
    ) in peer_content
    assert (
        "`equity_fundamental_ratios` with symbol set to that peer and "
        "provider={provider}"
    ) in peer_content


def test_cache_refresh_prompt_is_inspection_only():
    """Cache inspection cannot imply that prompt rendering runs maintenance."""
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    document = {
        prompt["name"]: prompt
        for prompt in json.loads(path.read_text(encoding="utf-8"))
    }
    prompt = document["fmp_cached_portfolio_refresh"]
    content = prompt["content"].lower()

    assert set(prompt["dependencies"]["required_tools"]) == {
        "cache_health",
        "cache_coverage",
    }
    assert prompt["dependencies"]["providers"] == []
    assert "limit=5" not in content
    assert "inspection only" in content
    assert "never invokes cached provider fetchers" in content
    assert "cannot prove per-symbol freshness" in content
    assert "do not claim that {symbol} is fresh or stale" in content
    assert "read may initialize or refresh persisted cache data" in content
    assert "authenticated portfolio-ops operator" in content
    assert "maintenance operations explicitly enabled" in content
    assert "separately enqueue" in content
    assert "equity_price_historical" not in content
    assert "equity_fundamental_metrics" not in content


def test_financialtoolkit_prompts_require_optional_package():
    """Toolkit-specific prompts fail readiness when the package is absent."""
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    document = {
        prompt["name"]: prompt
        for prompt in json.loads(path.read_text(encoding="utf-8"))
    }

    for name in (
        "financialtoolkit_performance_scorecard",
        "financialtoolkit_valuation_screen",
    ):
        dependencies = document[name]["dependencies"]
        assert dependencies["optional_packages"] == ["openbb-financialtoolkit"]
        assert dependencies["required_tools"]
        assert all(
            tool.startswith("financialtoolkit_")
            for tool in dependencies["required_tools"]
        )

    performance_content = document["financialtoolkit_performance_scorecard"]["content"]
    assert "JSON string array named `symbol_list`" in performance_content
    assert "symbols=symbol_list" in performance_content
    assert "symbols={symbols}" not in performance_content

    valuation_content = document["financialtoolkit_valuation_screen"]["content"]
    assert "weighted_average_cost_of_capital=0.10" in valuation_content
    assert "wacc=" not in valuation_content.lower()


def test_instruction_assets_avoid_unsupported_provider_claims():
    """User-facing MCP instructions avoid invalid names and provider promises."""
    assets_dir = MCPSettings.get_default_assets_dir()
    instruction_text = "\n".join(
        (
            (assets_dir / "server_prompts.json").read_text(encoding="utf-8"),
            (assets_dir / "system_prompt.txt").read_text(encoding="utf-8"),
            (assets_dir / "profiles" / "portfolio.json").read_text(encoding="utf-8"),
        )
    ).lower()

    for unsupported_claim in (
        "equity_fundamental_overview",
        "limit=5",
        "local-only",
        "local only",
        "no quota limits",
        "unlimited quota",
    ):
        assert unsupported_claim not in instruction_text
