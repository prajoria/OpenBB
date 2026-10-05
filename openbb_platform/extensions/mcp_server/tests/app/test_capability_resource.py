"""Unified cross-surface capability resource contracts."""

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from openbb_mcp_server.app.app import (
    CAPABILITY_CATALOG_URI,
    _build_capability_catalog,
    create_mcp_server,
)
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.exposure_policy import ExposurePolicy

_REPOSITORY_ROOT = Path(__file__).parents[5]


def _capabilities_by_id(document: dict) -> dict[str, dict]:
    return {capability["id"]: capability for capability in document["capabilities"]}


def _connections_by_id(document: dict) -> dict[str, dict]:
    return {connection["id"]: connection for connection in document["connections"]}


def test_catalog_owns_each_capability_and_does_not_infer_live_sessions():
    """Separate MCP sessions remain unprobed until their own clients connect."""
    document = _build_capability_catalog(
        MCPSettings(
            capability_profile="platform-standard",
            default_skills_dir=None,
        ),
        registered_tools={"equity_price_quote"},
        enabled_tools={"equity_price_quote"},
    )
    capabilities = _capabilities_by_id(document)
    connections = _connections_by_id(document)

    assert document["schema_version"] == "1.0"
    assert document["resource_uri"] == CAPABILITY_CATALOG_URI
    assert document["availability_policy"] == (
        "Only the current Platform MCP registration is runtime-observed. "
        "Client configuration never proves another MCP session is live."
    )
    assert set(capabilities) == {
        "platform-openapi",
        "platform-portfolio-adapters",
        "platform-cache-observability",
        "platform-cache-maintenance",
        "workspace-browser-control",
        "agents-portfolio-qa",
        "daytrade-read-tools",
    }
    assert len(
        {capability["verification_scope"] for capability in capabilities.values()}
    ) == len(capabilities)

    for capability in capabilities.values():
        assert capability["owner_surface"] in {
            "platform",
            "workspace",
            "agents",
            "daytrade",
        }
        assert capability["connection_prerequisites"]
        assert capability["mapping"] in {"direct", "indirect"}
        assert capability["verification_level"]

    assert capabilities["platform-openapi"]["availability"]["state"] == "available"
    assert (
        capabilities["platform-portfolio-adapters"]["availability"]["state"]
        == "disabled"
    )
    for capability_id in (
        "workspace-browser-control",
        "agents-portfolio-qa",
        "daytrade-read-tools",
    ):
        assert capabilities[capability_id]["availability"] == {
            "state": "not_probed",
            "basis": "separate_session",
        }

    assert connections["workspace-integrated"]["endpoint"] == (
        "http://127.0.0.1:8000/mcp"
    )
    assert connections["workspace-integrated"]["mode"] == "integrated"
    assert connections["workspace-standalone"]["endpoint"] == (
        "http://127.0.0.1:8787/mcp"
    )
    assert connections["workspace-standalone"]["mode"] == "optional_standalone"
    assert all(
        connection["availability"]["state"] == "not_probed"
        for connection in connections.values()
    )
    assert connections["platform-http"]["mode"] == "configured_example"


def test_platform_tool_availability_uses_runtime_inventory():
    """An empty or inactive application is never reported as live coverage."""
    settings = MCPSettings(
        capability_profile="platform-standard",
        default_skills_dir=None,
    )

    absent = _capabilities_by_id(
        _build_capability_catalog(
            settings,
            registered_tools=set(),
            enabled_tools=set(),
        )
    )
    disabled = _capabilities_by_id(
        _build_capability_catalog(
            settings,
            registered_tools={"equity_price_quote"},
            enabled_tools=set(),
        )
    )
    unknown = _capabilities_by_id(_build_capability_catalog(settings))

    assert absent["platform-openapi"]["availability"] == {
        "state": "absent",
        "basis": "no_registered_tools",
    }
    assert disabled["platform-openapi"]["availability"] == {
        "state": "disabled",
        "basis": "registered_not_enabled",
    }
    assert unknown["platform-openapi"]["availability"] == {
        "state": "not_evaluated",
        "basis": "no_runtime_inventory",
    }


def test_portfolio_profile_reports_adapter_admission_without_probing_peers():
    """Profile admission is local state and does not upgrade other sessions."""
    document = _build_capability_catalog(
        MCPSettings(
            capability_profile="portfolio-read",
            runtime_profile="portfolio-read",
            default_skills_dir=None,
        ),
        registered_tools={"portfolio_stock_context"},
        enabled_tools={"portfolio_stock_context"},
    )
    capabilities = _capabilities_by_id(document)

    assert (
        capabilities["platform-portfolio-adapters"]["availability"]["state"]
        == "available"
    )
    assert (
        capabilities["platform-portfolio-adapters"]["availability"]["basis"]
        == "enabled_tool_inventory"
    )
    assert {
        capabilities[name]["availability"]["state"]
        for name in (
            "workspace-browser-control",
            "agents-portfolio-qa",
            "daytrade-read-tools",
        )
    } == {"not_probed"}


def test_cache_tools_have_distinct_policy_owned_capabilities():
    """Cache tools do not inflate core API or Portfolio adapter availability."""
    policy = ExposurePolicy.load()
    reviewed = policy.document.traceability.reviewed_capability_members
    observability_policy = reviewed["platform-cache-observability"]
    maintenance_policy = reviewed["platform-cache-maintenance"]
    observability = set(observability_policy.members)
    maintenance = set(maintenance_policy.members)
    registered = observability | maintenance
    document = _build_capability_catalog(
        MCPSettings(
            capability_profile="portfolio-ops",
            runtime_profile="portfolio-ops",
            enable_maintenance_operations=True,
            default_skills_dir=None,
        ),
        registered_tools=registered,
        enabled_tools=registered,
    )
    capabilities = _capabilities_by_id(document)

    assert observability.isdisjoint(maintenance)
    assert capabilities["platform-openapi"]["availability"]["state"] == "absent"
    assert (
        capabilities["platform-portfolio-adapters"]["availability"]["state"] == "absent"
    )
    assert (
        capabilities["platform-cache-observability"]["availability"]["state"]
        == "available"
    )
    assert (
        capabilities["platform-cache-maintenance"]["availability"]["state"]
        == "available"
    )
    assert (
        set(capabilities["platform-cache-observability"]["verified_members"])
        == observability
    )
    assert (
        set(capabilities["platform-cache-maintenance"]["verified_members"])
        == maintenance
    )
    assert set(observability_policy.verification_evidence).isdisjoint(
        maintenance_policy.verification_evidence
    )
    assert capabilities["platform-cache-observability"][
        "verification_evidence"
    ] == list(observability_policy.verification_evidence)
    assert capabilities["platform-cache-maintenance"]["verification_evidence"] == list(
        maintenance_policy.verification_evidence
    )


@pytest.mark.asyncio
async def test_catalog_is_registered_as_one_versioned_json_resource():
    """Clients receive one deterministic resource rather than duplicated tools."""
    settings = MCPSettings(
        capability_profile="platform-standard",
        default_skills_dir=None,
    )
    mcp = create_mcp_server(settings, FastAPI())

    resources = await mcp.list_resources()
    matching = [
        resource
        for resource in resources
        if str(resource.uri) == CAPABILITY_CATALOG_URI
    ]
    assert len(matching) == 1
    assert matching[0].mime_type == "application/json"

    result = await mcp.read_resource(CAPABILITY_CATALOG_URI)
    assert len(result.contents) == 1
    document = json.loads(result.contents[0].content)
    assert document == _build_capability_catalog(
        settings,
        registered_tools=set(),
        enabled_tools=set(),
    )


@pytest.mark.asyncio
async def test_discovery_mode_does_not_claim_session_activated_tools():
    """Session-scoped activation is not frozen into the global resource."""
    app = FastAPI()

    @app.get("/api/v1/equity/price/quote")
    async def quote(symbol: str) -> dict[str, str]:
        return {"symbol": symbol}

    mcp = create_mcp_server(
        MCPSettings(
            api_prefix="/api/v1",
            default_tool_categories=["all"],
            default_skills_dir=None,
            enable_tool_discovery=True,
        ),
        app,
    )
    result = await mcp.read_resource(CAPABILITY_CATALOG_URI)
    document = json.loads(result.contents[0].content)

    assert _capabilities_by_id(document)["platform-openapi"]["availability"] == {
        "state": "not_evaluated",
        "basis": "session_scoped_activation",
    }


def test_specialist_verification_is_derived_from_reviewed_policy():
    """The catalog cannot disagree with the policy source of truth."""
    document = _build_capability_catalog(MCPSettings(default_skills_dir=None))
    capabilities = _capabilities_by_id(document)
    policy = ExposurePolicy.load()

    for surface, capability_id in (
        ("agents", "agents-portfolio-qa"),
        ("daytrade", "daytrade-read-tools"),
    ):
        rule = policy.document.specialists[surface]
        capability = capabilities[capability_id]
        assert capability["mapping"] == rule.disposition == "direct"
        assert capability["verification_level"] == rule.verification_level
        assert capability["verification_evidence"] == list(rule.verification_evidence)
        assert capability["verified_members"] == list(
            policy.document.traceability.reviewed_specialists[surface]
        )
    assert (
        policy.document.traceability.work_families[
            "jobs-and-cache-operations"
        ].implementation_state
        == "implemented_product"
    )


def test_client_examples_cover_distinct_credential_free_connections():
    """Static examples describe transports but do not claim availability."""
    document = json.loads(
        (_REPOSITORY_ROOT / ".mcp.json.example").read_text(encoding="utf-8")
    )
    servers = document["mcpServers"]

    assert set(servers) == {
        "openbb-platform-standard",
        "openbb-workspace-integrated",
        "openbb-workspace-standalone-optional",
        "openbb-agents",
        "openbb-daytrade",
    }
    assert servers["openbb-platform-standard"] == {
        "type": "http",
        "url": "http://127.0.0.1:8001/mcp",
    }
    assert servers["openbb-workspace-integrated"]["url"] == (
        "http://127.0.0.1:8000/mcp"
    )
    assert servers["openbb-workspace-standalone-optional"]["url"] == (
        "http://127.0.0.1:8787/mcp"
    )
    assert servers["openbb-agents"]["args"] == [
        "-m",
        "openbb_agents.mcp_server",
    ]
    assert servers["openbb-daytrade"] == {
        "command": "openbb-daytrade",
        "args": ["mcp-serve"],
        "cwd": "${workspaceFolder}",
    }
    assert not any(
        token in json.dumps(document).lower()
        for token in ("api_key", "password", "secret", "bearer", "authorization")
    )


def test_cross_repository_documentation_indexes_the_resource():
    """The workflow index keeps the machine and human views connected."""
    index = (_REPOSITORY_ROOT / "docs" / "cross_repo_workflow" / "README.md").read_text(
        encoding="utf-8"
    )

    assert "resource://openbb/capabilities/v1" in index
    assert "http://127.0.0.1:8000/mcp" in index
    assert "http://127.0.0.1:8787/mcp" in index
    assert "mcp-capability-decisions.md" in index
