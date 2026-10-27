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
        assert {"equity_fundamental_metrics", "equity_fundamental_ratios"} <= set(
            required_tools
        )
        provider_argument = next(
            argument
            for argument in prompts[name]["arguments"]
            if argument["name"] == "provider"
        )
        assert provider_argument["default"] == "fmp"
        assert prompts[name]["dependencies"]["providers"] == ["fmp"]
        content = prompts[name]["content"]
        for tool in required_tools:
            invocation = content.split(f"`{tool}`", maxsplit=1)[1]
            invocation = invocation.split("`", maxsplit=1)[0]
            assert "provider={provider}" in invocation


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
    for required_boundary in (
        "inspection only",
        "never invokes cached provider fetchers",
        "cannot prove per-symbol freshness",
        "do not claim that {symbol} is fresh or stale",
        "read may initialize or refresh persisted cache data",
        "authenticated portfolio-ops operator",
        "maintenance operations explicitly enabled",
        "separately enqueue",
        "do not enqueue or execute maintenance",
    ):
        assert required_boundary in content
    for forbidden_call in (
        "limit=5",
        "equity_price_historical",
        "equity_fundamental_metrics",
    ):
        assert forbidden_call not in content


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


def _bundled_prompts() -> list[dict]:
    path = MCPSettings.get_default_assets_dir() / "server_prompts.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _declared_tools(prompt: dict) -> set[str]:
    dependencies = prompt["dependencies"]
    return set(dependencies["required_tools"]) | {
        tool for group in dependencies["any_tool_groups"] for tool in group
    }


def _package_installed(distribution: str) -> bool:
    import importlib.metadata  # pylint: disable=import-outside-toplevel

    try:
        importlib.metadata.distribution(distribution)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def test_prompt_text_names_only_declared_tools():
    """Every tool-shaped backticked name in prompt text is a declared dependency."""
    import re  # pylint: disable=import-outside-toplevel

    prompts = _bundled_prompts()
    prompt_names = {prompt["name"] for prompt in prompts}
    # A token is a tool reference when it starts with a tool namespace used by
    # the catalog; prompt-local variables such as `symbol_list` are not.
    namespaces = {
        tool.split("_", 1)[0] for prompt in prompts for tool in _declared_tools(prompt)
    }
    undeclared = {}
    for prompt in prompts:
        names = {
            token
            for token in re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)`", prompt["content"])
            if token not in prompt_names and token.split("_", 1)[0] in namespaces
        }
        if missing := names - _declared_tools(prompt):
            undeclared[prompt["name"]] = sorted(missing)
    assert not undeclared


@pytest.mark.asyncio
async def test_every_declared_prompt_tool_is_emitted_by_a_real_profile():
    """Bundled prompts never require a tool name that no profile emits (#2300).

    A missing tool is acceptable only when the prompt also declares an
    optional package that is not installed, which keeps its unavailable
    reason actionable.
    """
    # pylint: disable=import-outside-toplevel
    from openbb_core.api.rest_api import app as platform_app
    from openbb_mcp_server.app.app import create_mcp_server

    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile="portfolio-ops",
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    server = create_mcp_server(
        settings, platform_app, auth=("synthetic-user", "x" * 32)
    )
    emitted = {tool.name for tool in await server.list_tools()}
    unknown = {}
    for prompt in _bundled_prompts():
        missing = _declared_tools(prompt) - emitted
        packages = prompt["dependencies"]["optional_packages"]
        if missing and not (
            packages and not all(_package_installed(name) for name in packages)
        ):
            unknown[prompt["name"]] = sorted(missing)
    assert not unknown


def test_every_declared_prompt_provider_is_registered():
    """Bundled prompts never require a provider the platform cannot register."""
    # pylint: disable=import-outside-toplevel
    from openbb_core.provider.registry_map import RegistryMap

    known = set(RegistryMap().available_providers)
    unknown = {
        prompt["name"]: sorted(set(prompt["dependencies"]["providers"]) - known)
        for prompt in _bundled_prompts()
        if set(prompt["dependencies"]["providers"]) - known
    }
    assert not unknown
