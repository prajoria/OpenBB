"""Metadata-only capability inventory tests."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import runpy
import socket
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from openbb_mcp_server.models.capability import CapabilityInventory
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.capability_import_guard import (
    _checkout_entry_points,
    metadata_import_guard,
)
from openbb_mcp_server.service.capability_traceability import (
    build_traceability_report,
)
from openbb_mcp_server.service.capability_inventory import (
    DistributionMetadata,
    ImportMetadata,
    InventorySources,
    ProfileMetadata,
    ProviderModelMetadata,
    RepositoryMetadata,
    RuntimeMetadata,
    ServiceMetadata,
    SubmoduleMetadata,
    build_inventory,
    collect_capabilities,
    config_fingerprint,
    load_profile_metadata,
    normalize_import_origin,
    validate_inventory_evidence,
    write_inventory,
)
from openbb_mcp_server.service.exposure_policy import ExposurePolicy


class DedicatedQuoteFetcher:
    """Synthetic dedicated fetcher that must never execute."""

    @classmethod
    def test(cls, *_args, **_kwargs):
        """Fail if metadata collection invokes the fetcher."""
        raise AssertionError("fetcher execution is forbidden")


class FallbackUnroutedFetcher:
    """Synthetic fallback fetcher that must never execute."""

    @classmethod
    def aextract_data(cls, *_args, **_kwargs):
        """Fail if metadata collection invokes the fetcher."""
        raise AssertionError("fetcher execution is forbidden")


DedicatedQuoteFetcher.__module__ = "openbb_fmp_cached.models.equity_quote"
FallbackUnroutedFetcher.__module__ = "openbb_fmp_cached.models.base_cached"


@pytest.fixture
def synthetic_sources() -> tuple[InventorySources, dict[str, int]]:
    """Build source metadata whose business functions fail if called."""
    calls = {"endpoint": 0}
    app = FastAPI()

    def quote_endpoint():
        calls["endpoint"] += 1
        raise AssertionError("endpoint execution is forbidden")

    def mutation_endpoint():
        calls["endpoint"] += 1
        raise AssertionError("endpoint execution is forbidden")

    def resource_endpoint():
        calls["endpoint"] += 1
        raise AssertionError("endpoint execution is forbidden")

    app.add_api_route(
        "/api/v1/equity/quote",
        quote_endpoint,
        methods=["GET"],
        openapi_extra={
            "model": "EquityQuote",
            "mcp_config": {
                "prompts": [
                    {
                        "name": "quote_research",
                        "content": "Research {symbol}",
                    }
                ]
            },
        },
    )
    app.add_api_route(
        "/api/v1/equity/quote_alias",
        quote_endpoint,
        methods=["GET"],
        openapi_extra={"model": "EquityQuote"},
    )
    app.add_api_route(
        "/api/v1/equity/invalid_config",
        quote_endpoint,
        methods=["GET"],
        openapi_extra={
            "model": "EquityQuote",
            "mcp_config": {
                "name": "must_not_apply",
                "methods": 123,
            },
        },
    )
    app.add_api_route(
        "/api/v1/equity/x_alias",
        quote_endpoint,
        methods=["GET"],
        openapi_extra={
            "model": "EquityQuote",
            "x-mcp": {
                "name": "x_quote",
                "prompts": [
                    {
                        "name": "x_quote_research",
                        "content": "Research {symbol}",
                    }
                ],
            },
        },
    )
    app.add_api_route(
        "/api/v1/equity/quote",
        quote_endpoint,
        methods=["GET"],
        openapi_extra={"model": "EquityQuote"},
    )
    for path in ("/api/v1/equity/duplicate_a", "/api/v1/equity/duplicate_b"):
        app.add_api_route(
            path,
            quote_endpoint,
            methods=["GET"],
            openapi_extra={
                "model": "EquityQuote",
                "mcp_config": {"name": "duplicate_quote"},
            },
        )
    app.add_api_route(
        "/api/v1/portfolio/order",
        mutation_endpoint,
        methods=["POST"],
        openapi_extra={"model": "PaperOrder"},
    )
    app.add_api_route(
        "/api/v1/catalog/stories",
        resource_endpoint,
        methods=["GET"],
        openapi_extra={"mcp_config": {"mcp_type": "resource"}},
    )
    app.add_api_route(
        "/api/v1/private/positions",
        resource_endpoint,
        methods=["GET"],
        openapi_extra={
            "mcp_config": {
                "expose": False,
                "prompts": [
                    {
                        "name": "private_prompt",
                        "content": "Never register this prompt",
                    }
                ],
            }
        },
    )

    profile = ProfileMetadata(
        selected_name="portfolio-read",
        source_profile="portfolio.json",
        alias_group="portfolio",
        api_prefix="/api/v1",
        config_fingerprint="a" * 64,
        default_tool_categories=("equity", "portfolio"),
        enable_tool_discovery=True,
    )
    runtime = RuntimeMetadata(
        python_implementation="CPython",
        python_version="3.12.10",
        repository=RepositoryMetadata(
            commit="1" * 40,
            dirty=False,
            state="available",
        ),
        submodules=(SubmoduleMetadata(path="third_party/example", commit="2" * 40),),
        distributions=(
            DistributionMetadata(
                name="openbb-core",
                state="available",
                version="1.2.3",
                editable=True,
            ),
            DistributionMetadata(name="optional-package", state="missing"),
        ),
        imports=(
            ImportMetadata(
                module="openbb_core",
                state="available",
                origin="repo://openbb_platform/core/openbb_core/__init__.py",
            ),
        ),
        services=(ServiceMetadata(name="workspace", state="not_probed_metadata_only"),),
    )
    sources = InventorySources(
        app=app,
        settings=MCPSettings(
            api_prefix="/api/v1",
            default_tool_categories=["equity"],
            enable_tool_discovery=True,
        ),
        profile=profile,
        command_models={
            "/equity/quote": "EquityQuote",
            "/portfolio/order": "PaperOrder",
        },
        model_providers={
            "EquityQuote": ("fmp_cached", "yfinance"),
            "PaperOrder": (),
            "UnroutedModel": ("fmp_cached",),
            "=2+2": ("fmp_cached",),
        },
        provider_credentials={"fmp_cached": ("fmp_cached_api_key",)},
        provider_fetchers={
            "fmp_cached": {
                "EquityQuote": DedicatedQuoteFetcher,
                "UnroutedModel": FallbackUnroutedFetcher,
                "=2+2": DedicatedQuoteFetcher,
                "\tCMD": DedicatedQuoteFetcher,
                "FetcherOnlyModel": DedicatedQuoteFetcher,
            }
        },
        static_prompts=(
            {
                "name": "market_brief",
                "description": "Synthetic market brief",
                "content": "Summarize the market",
                "arguments": [],
                "tags": ["research"],
            },
            {
                "name": "quote_research",
                "description": "Duplicate prompt declaration",
                "content": "Research a quote",
                "arguments": [],
                "tags": ["research"],
            },
        ),
        runtime=runtime,
        unavailable_components=("agents:package_missing",),
    )
    return sources, calls


def test_collect_capabilities_is_metadata_only(synthetic_sources):
    """Route, provider and prompt metadata are inspected without business calls."""
    sources, calls = synthetic_sources
    capabilities = collect_capabilities("portfolio-read", sources=sources)
    assert calls == {"endpoint": 0}
    by_tool = {record.tool_name: record for record in capabilities if record.tool_name}
    assert by_tool["equity_quote"].source_model == "EquityQuote"
    assert by_tool["x_quote"].source_model == "EquityQuote"
    assert by_tool["equity_invalid_config"].source_model == "EquityQuote"
    assert "must_not_apply" not in by_tool
    assert by_tool["portfolio_order"].access_class == "financial_mutation"
    assert by_tool["equity_quote"].access_class == "provider_read"
    assert "fixed-toolset-enabled:true" in by_tool["equity_quote"].requirements
    assert "startup-enabled:false" in by_tool["equity_quote"].requirements
    assert "tool-discovery:true" in by_tool["equity_quote"].requirements
    assert "fixed-toolset-enabled:false" in by_tool["portfolio_order"].requirements
    assert "startup-enabled:false" in by_tool["portfolio_order"].requirements
    assert (
        "access-classification:provisional-method-derived"
        in by_tool["portfolio_order"].requirements
    )
    assert any(
        record.disposition == "restricted"
        and record.operation
        and record.operation.path.endswith("/private/positions")
        for record in capabilities
    )
    assert any(
        record.disposition == "metadata_only"
        and record.id.startswith("platform:prompt:")
        for record in capabilities
    )
    prompt_requirements = {
        requirement
        for record in capabilities
        for requirement in record.requirements
        if requirement.startswith(
            ("prompt-name:", "runtime-tool-key:", "effective-component:")
        )
    }
    assert "prompt-name:quote_research" in prompt_requirements
    assert "runtime-tool-key:equity_quote" in prompt_requirements
    assert "effective-component:equity_quote" in prompt_requirements
    assert "runtime-tool-key:equity_x_alias" in prompt_requirements
    assert "effective-component:x_quote" in prompt_requirements
    assert "prompt-name:private_prompt" not in prompt_requirements


def test_build_inventory_joins_provider_models_and_tools(synthetic_sources):
    """FMP registrations retain persistence and routed/unrouted truth."""
    sources, _ = synthetic_sources
    document = build_inventory("portfolio-read", sources=sources)
    rows = {row.model: row for row in document.provider_models}
    assert rows["EquityQuote"].commands == ("/equity/quote",)
    assert rows["EquityQuote"].tool_names == ("equity_quote",)
    assert rows["EquityQuote"].persistence == "dedicated"
    assert rows["EquityQuote"].provider_registered is True
    assert rows["EquityQuote"].credential_fields == ("fmp_cached_api_key",)
    assert rows["UnroutedModel"].commands == ()
    assert rows["UnroutedModel"].tool_names == ()
    assert rows["UnroutedModel"].persistence == "fallback_none"
    assert rows["UnroutedModel"].provider_registered is True
    assert rows["UnroutedModel"].status == "unrouted"
    assert rows["FetcherOnlyModel"].provider_registered is False
    assert rows["FetcherOnlyModel"].status == "unrouted"


def test_collisions_aliases_and_unavailable_components_are_explicit(
    synthetic_sources,
):
    """Name collisions and aliases cannot silently replace inventory rows."""
    sources, _ = synthetic_sources
    document = build_inventory("portfolio-read", sources=sources)
    assert any(
        collision.kind == "tool_name" and collision.key == "duplicate_quote"
        for collision in document.collisions
    )
    assert any(
        collision.kind == "operation" and collision.key == "GET /api/v1/equity/quote"
        for collision in document.collisions
    )
    assert any(
        collision.kind == "component_name" and collision.key == "equity_quote"
        for collision in document.collisions
    )
    assert any(
        collision.kind == "prompt_name" and collision.key == "quote_research"
        for collision in document.collisions
    )
    counts = document.capabilities.coverage_counts()
    assert counts.implementation_aliases >= 1
    assert document.unavailable_components == ("agents:package_missing",)
    assert any(
        distribution.name == "optional-package" and distribution.state == "missing"
        for distribution in document.runtime.distributions
    )
    assert document.runtime.services[0].state == "not_probed_metadata_only"


def test_unknown_catchall_type_matches_runtime_tool_fallback(synthetic_sources):
    """Unknown catch-all values use the runtime's tool fallback."""
    sources, _ = synthetic_sources
    sources = replace(
        sources,
        settings=MCPSettings(
            api_prefix="/api/v1",
            default_catchall_mcp_type="unknown",
        ),
    )
    capabilities = collect_capabilities("portfolio-read", sources=sources)
    assert any(
        record.tool_name == "equity_quote" and record.disposition == "direct"
        for record in capabilities
    )


def test_repeated_writes_are_byte_identical(tmp_path, synthetic_sources):
    """Stable input produces byte-identical sorted JSON and CSV outputs."""
    sources, _ = synthetic_sources
    document = build_inventory("portfolio-read", sources=sources)
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_inventory(document, first)
    write_inventory(document, second)
    expected = {"inventory.json", "capabilities.csv", "provider_models.csv"}
    assert {path.name for path in first.iterdir()} == expected
    assert {path.name for path in second.iterdir()} == expected
    for name in expected:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    payload = json.loads((first / "inventory.json").read_text(encoding="utf-8"))
    assert payload["profile"]["selected_name"] == "portfolio-read"
    assert payload["denominators"]["route_records"] == sum(
        record["operation"] is not None for record in payload["capabilities"]["records"]
    )
    assert payload["denominators"]["prompt_records"] == 4
    assert payload["denominators"]["profile_records"] == 1
    assert any(row["model"] == "=2+2" for row in payload["provider_models"])
    with (first / "capabilities.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows == sorted(rows, key=lambda row: row["id"])
    assert any(
        row["exclusion_reason"] == "Route declares expose=false." for row in rows
    )
    with (first / "provider_models.csv").open(encoding="utf-8", newline="") as stream:
        provider_rows = list(csv.DictReader(stream))
    assert any(row["model"] == "'=2+2" for row in provider_rows)
    assert any(row["model"] == "'\tCMD" for row in provider_rows)


def test_profile_fingerprint_excludes_sensitive_fields(tmp_path):
    """Profile hashes never derive from auth, headers or secret values."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "portfolio.json").write_text(
        json.dumps(
            {
                "_comment": "ignored",
                "OPENBB_MCP_DEFAULT_TOOL_CATEGORIES": ["equity"],
                "OPENBB_MCP_ENABLE_TOOL_DISCOVERY": True,
                "OPENBB_MCP_SERVER_AUTH": ["user", "DO_NOT_HASH"],
                "OPENBB_MCP_HTTPX_CLIENT_KWARGS": {
                    "headers": {"Authorization": "DO_NOT_HASH"}
                },
            }
        ),
        encoding="utf-8",
    )
    profile = load_profile_metadata("portfolio-read", profiles_dir=profiles)
    expected = config_fingerprint(
        {
            "OPENBB_MCP_API_PREFIX": "/api/v1",
            "OPENBB_MCP_DEFAULT_TOOL_CATEGORIES": ["equity"],
            "OPENBB_MCP_ENABLE_TOOL_DISCOVERY": True,
        }
    )
    assert profile.config_fingerprint == expected
    assert "DO_NOT_HASH" not in profile.model_dump_json()


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        (
            "REPO/openbb_platform/core/openbb_core/__init__.py",
            "repo://openbb_platform/core/openbb_core/__init__.py",
        ),
        (
            "ENV/Lib/site-packages/fastmcp/__init__.py",
            "site-packages://fastmcp/__init__.py",
        ),
        ("EXTERNAL/private/module.py", "external"),
        (None, None),
    ],
)
def test_import_origins_never_expose_machine_paths(tmp_path, origin, expected):
    """Import origins use normalized provenance schemes."""
    repo = tmp_path / "repo"
    environment = tmp_path / "environment"
    external = tmp_path / "private"
    substitutions = {
        "REPO": repo.as_posix(),
        "ENV": environment.as_posix(),
        "EXTERNAL": external.as_posix(),
    }
    value = origin
    if value:
        for marker, replacement in substitutions.items():
            value = value.replace(marker, replacement)
    normalized = normalize_import_origin(value, repo_root=repo)
    if expected == "external":
        assert normalized
        assert normalized.startswith("external://")
        assert normalized.endswith("/module.py")
        assert external.as_posix() not in normalized
    else:
        assert normalized == expected


def test_config_fingerprint_is_stable_and_order_independent():
    """Canonical configuration hashes do not depend on mapping order."""
    first = {"categories": ["equity"], "discovery": True}
    second = {"discovery": True, "categories": ["equity"]}
    assert config_fingerprint(first) == config_fingerprint(second)


def test_import_guard_blocks_network_and_restores_environment(tmp_path, monkeypatch):
    """Guard behavior is verified without any optional provider package."""
    from openbb_core.app.extension_loader import ExtensionLoader

    instances = getattr(type(ExtensionLoader), "_instances")
    existing = instances.pop(ExtensionLoader, None)
    monkeypatch.setenv("OPENBB_API_KEY", "RESTORE_THIS_VALUE")
    try:
        with pytest.raises(RuntimeError, match="synthetic body failure"):
            with metadata_import_guard(tmp_path, []):
                assert "OPENBB_API_KEY" not in os.environ
                with pytest.raises(RuntimeError, match="network access is blocked"):
                    socket.socket()
                raise RuntimeError("synthetic body failure")
        assert os.environ["OPENBB_API_KEY"] == "RESTORE_THIS_VALUE"
    finally:
        if existing is not None:
            instances[ExtensionLoader] = existing


def test_import_guard_rejects_preinitialized_extension_loader():
    """A library caller cannot bypass filtering through a cached singleton."""
    from openbb_core.app.extension_loader import ExtensionLoader

    instances = getattr(type(ExtensionLoader), "_instances")
    existing = instances.get(ExtensionLoader)
    instances[ExtensionLoader] = object()
    excluded = []
    try:
        with pytest.raises(RuntimeError, match="initialized before"):
            with metadata_import_guard(Path.cwd(), excluded):
                pass
    finally:
        if existing is None:
            instances.pop(ExtensionLoader, None)
        else:
            instances[ExtensionLoader] = existing
    assert excluded == ["guard:extension_loader:already_initialized"]


def test_foreign_entry_point_is_excluded_before_load(tmp_path, monkeypatch):
    """A foreign entry-point target is never admitted to registration loading."""
    excluded = []
    package = tmp_path / "openbb_platform" / "extensions" / "fake"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        """
[tool.poetry.plugins."openbb_core_extension"]
foreign = "foreign_package.plugin:extension"
missing = "missing_package.plugin:extension"
""".strip(),
        encoding="utf-8",
    )
    entry_point = SimpleNamespace(
        name="foreign",
        value="foreign_package.plugin:extension",
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(
            origin=str(tmp_path.parent / "foreign_package" / "__init__.py")
        ),
    )
    allowed = _checkout_entry_points(
        tmp_path,
        excluded,
        group="openbb_core_extension",
        entry_point_reader=lambda **_kwargs: [entry_point],
    )
    assert list(allowed) == []
    assert excluded == [
        "entry-point:openbb_core_extension:missing:missing_from_environment",
        "entry-point:openbb_core_extension:foreign:outside_repo_root",
    ]


def test_stale_entry_point_target_is_excluded(tmp_path, monkeypatch):
    """Installed metadata must match the checkout-declared callable target."""
    package = tmp_path / "openbb_platform" / "extensions" / "example"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        """
[tool.poetry.plugins."openbb_core_extension"]
example = "checkout_package.new:router"
""".strip(),
        encoding="utf-8",
    )
    entry_point = SimpleNamespace(
        name="example",
        value="checkout_package.old:router",
    )
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(
            origin=str(
                tmp_path
                / "openbb_platform"
                / "extensions"
                / "example"
                / "checkout_package"
                / "__init__.py"
            )
        ),
    )
    excluded = []
    allowed = _checkout_entry_points(
        tmp_path,
        excluded,
        group="openbb_core_extension",
        entry_point_reader=lambda **_kwargs: [entry_point],
    )
    assert list(allowed) == []
    assert excluded == ["entry-point:openbb_core_extension:example:target_mismatch"]


def test_truncated_or_foreign_inventory_cannot_be_parity_evidence(
    synthetic_sources,
):
    """Evidence validation fails closed on missing routes or foreign sources."""
    sources, _ = synthetic_sources
    document = build_inventory("portfolio-read", sources=sources)
    validate_inventory_evidence(document)
    foreign = document.model_copy(
        update={
            "unavailable_components": (
                "entry-point:openbb_core_extension:foreign:outside_repo_root",
            )
        }
    )
    with pytest.raises(RuntimeError, match="outside the checkout"):
        validate_inventory_evidence(foreign)
    non_route_extension = document.model_copy(
        update={
            "unavailable_components": (
                "entry-point:openbb_obbject_extension:charting:outside_repo_root",
            )
        }
    )
    validate_inventory_evidence(non_route_extension)
    missing_optional = document.model_copy(
        update={
            "unavailable_components": (
                "entry-point:openbb_core_extension:optional:missing_from_environment",
            )
        }
    )
    validate_inventory_evidence(missing_optional)
    safely_excluded_extra = document.model_copy(
        update={
            "unavailable_components": (
                "entry-point:openbb_core_extension:extra:not_declared_by_checkout",
            )
        }
    )
    validate_inventory_evidence(safely_excluded_extra)
    empty = document.model_copy(
        update={"capabilities": CapabilityInventory(records=())}
    )
    with pytest.raises(RuntimeError, match="no direct route"):
        validate_inventory_evidence(empty)


def test_provisional_portfolio_profile_aliases_are_explicit():
    """Read and ops labels disclose their shared pre-profile source."""
    read_profile = load_profile_metadata("portfolio-read")
    ops_profile = load_profile_metadata("portfolio-ops")
    assert read_profile.selected_name != ops_profile.selected_name
    assert read_profile.alias_group == ops_profile.alias_group == "portfolio"
    assert read_profile.config_fingerprint == ops_profile.config_fingerprint


@pytest.mark.skipif(
    importlib.util.find_spec("openbb_fmp_cached") is None,
    reason="FMP Cached is an optional inventory source",
)
def test_default_inventory_accounts_for_every_fmp_cached_registration(
    tmp_path,
):
    """The live metadata join preserves the audited routed-gap denominator."""
    repo_root = Path(__file__).resolve().parents[5]
    output_dir = tmp_path / "inventory"
    environment = os.environ.copy()
    environment["OPENBB_API_KEY"] = "DO_NOT_READ_THIS_VALUE"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "audit_mcp_capabilities.py"),
            "--profile",
            "portfolio-read",
            "--metadata-only",
            "--output-dir",
            str(output_dir),
        ],
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads((output_dir / "inventory.json").read_text(encoding="utf-8"))
    fmp_rows = [
        row for row in document["provider_models"] if row["provider"] == "fmp_cached"
    ]
    manifest_path = (
        Path(__file__).parents[1] / "fixtures" / "capability_audit" / "manifest.json"
    )
    baseline = json.loads(manifest_path.read_text(encoding="utf-8"))["counts"]
    assert len(fmp_rows) == baseline["fmp_models"]
    assert Counter(row["status"] for row in fmp_rows) == {
        "routed": baseline["fmp_routed_models"],
        "unrouted": baseline["fmp_unrouted_models"],
    }
    assert all(
        row["provider_registered"] for row in fmp_rows if row["status"] == "routed"
    )
    assert {flag["name"] for flag in document["runtime"]["environment_flags"]} == {
        "DEV_MODE_EFFECTIVE",
        "JOBS_ENABLED_EFFECTIVE",
    }
    assert document["runtime"]["repository"]["untracked"] is not None
    assert "DO_NOT_READ_THIS_VALUE" not in json.dumps(document)
    assert document["unavailable_components"]
    assert all(
        component.endswith(":missing_from_environment")
        or component.startswith("profile-category:")
        for component in document["unavailable_components"]
    )
    assert {
        "profile-category:financialtoolkit:no_matching_routes",
        "profile-category:portfolio:no_matching_routes",
    } <= set(document["unavailable_components"])
    assert set(document["denominators"]["missing_core_entry_points"]) >= {
        "financialtoolkit",
        "fmp_trading",
    }
    assert document["denominators"]["route_records"] == sum(
        record["operation"] is not None
        for record in document["capabilities"]["records"]
    )
    assert tuple(document["scope_limitations"]) == (
        "access-class:provisional-method-derived-2154",
        "agents-composed-routes:not-enumerated",
        "dev-mode-and-jobs-routes:forced-disabled",
        "fastmcp-admin-tools:not-enumerated",
        "owner-lane:provisional-placeholder-2154",
        "portfolio-launch-composed-routes:not-enumerated",
        "provider-fetchers:fmp_cached-only",
        "skills-derived-prompts:not-enumerated",
    )
    assert document["profile"]["api_prefix"] == "/api/v1"

    assert all(
        distribution["source"] is None
        or distribution["source"].startswith(
            ("repo://", "site-packages://", "external://")
        )
        for distribution in document["runtime"]["distributions"]
    )


def test_cli_requires_explicit_metadata_only_confirmation(tmp_path):
    """The audit script has no implicit active-probe mode."""
    repo_root = Path(__file__).resolve().parents[5]
    namespace = runpy.run_path(str(repo_root / "scripts" / "audit_mcp_capabilities.py"))
    with pytest.raises(SystemExit):
        namespace["parse_args"](
            [
                "--profile",
                "portfolio-read",
                "--output-dir",
                str(tmp_path),
            ]
        )
    namespace["validate_output_dir"](tmp_path, repo_root)
    with pytest.raises(ValueError, match="must be ignored"):
        namespace["validate_output_dir"](
            repo_root / "unignored-audit-output",
            repo_root,
        )


def test_every_audited_operation_has_accountable_traceability():
    """All reviewed operations map to owner issues and source evidence."""
    policy = ExposurePolicy.load()
    catalog = (
        Path(__file__).parents[2]
        / "openbb_mcp_server"
        / "assets"
        / "capability_policy_operations.csv"
    )
    with catalog.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    operations = [(row["scope"], row["method"], row["path"]) for row in rows]
    report = build_traceability_report(policy, operations=operations)
    assert len(report.items) == len(rows) == 317
    assert report.unowned == ()
    assert "implemented_product" in {item.implementation_state for item in report.items}
    by_rule = {item.rule_id: item for item in report.items}
    assert by_rule["portfolio-custom-private"].implementation_state == "adapter_gap"
    assert (
        by_rule["deny-execution-actions"].implementation_state == "approved_exclusion"
    )
    assert all(
        item.owner_issues
        and item.rationale
        and item.source_evidence
        and item.review_triggers
        for item in report.items
    )
    repo_root = Path(__file__).resolve().parents[5]
    evidence_paths = {
        evidence
        for family in policy.document.traceability.work_families.values()
        for evidence in family.source_evidence
    }
    assert all((repo_root / evidence).exists() for evidence in evidence_paths)


def test_dynamic_route_inventory_surfaces_unreviewed_registrations(
    synthetic_sources,
):
    """Dynamically registered routes feed traceability rather than a fixed list."""
    sources, _ = synthetic_sources
    document = build_inventory("portfolio-read", sources=sources)
    operations = [
        (
            "portfolio-venv-core-in-process",
            record.operation.method,
            record.operation.path,
        )
        for record in document.capabilities.records
        if record.operation
    ]
    report = build_traceability_report(ExposurePolicy.load(), operations=operations)
    assert any("invalid_config" in capability_id for capability_id in report.unowned)


def test_new_operation_cannot_hide_behind_stale_denominator():
    """Newly discovered routes remain visible as unowned policy drift."""
    policy = ExposurePolicy.load()
    report = build_traceability_report(
        policy,
        operations=[
            (
                "portfolio-venv-core-in-process",
                "GET",
                "/api/v1/new_family/new_route",
            )
        ],
    )
    assert report.items == ()
    assert report.unowned == (
        "operation:portfolio-venv-core-in-process:GET:/api/v1/new_family/new_route",
    )


def test_new_provider_is_counted_and_unknown_specialist_is_unowned():
    """Provider growth remains counted while specialist identity requires review."""
    provider = ProviderModelMetadata(
        provider="fmp_cached",
        model="BrandNewModel",
        fetcher_class="BrandNewFetcher",
        fetcher_module="openbb_fmp_cached.models.brand_new",
        implementation_id="python:brand-new",
        persistence="dedicated",
        commands=(),
        tool_names=(),
        credential_fields=("fmp_cached_api_key",),
        provider_registered=True,
        status="unrouted",
    )
    report = build_traceability_report(
        ExposurePolicy.load(),
        provider_models=[provider],
        specialists=[("agents", "brand_new_tool")],
    )
    assert len(report.items) == 1
    assert report.items[0].capability_id == ("provider:fmp_cached:BrandNewModel")
    assert report.items[0].implementation_state == "adapter_gap"
    assert report.unowned == ("specialist:agents:brand_new_tool",)


def test_every_exclusion_and_gap_rule_has_an_accountable_family():
    """Restricted/unimplemented rules cannot exist without ownership."""
    policy = ExposurePolicy.load()
    owners = policy.document.traceability.rule_owners
    excluded = {
        rule.id
        for rule in policy.document.rules
        if rule.disposition in {"restricted", "unimplemented"}
    }
    excluded.update({"provider-unrouted", "specialist-agents", "specialist-daytrade"})
    assert excluded <= set(owners)
