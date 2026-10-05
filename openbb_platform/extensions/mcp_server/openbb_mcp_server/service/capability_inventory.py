"""Deterministic metadata-only MCP capability inventory."""

# pylint: disable=too-many-lines,too-many-instance-attributes

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import secrets
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.routing import APIRoute
from openbb_core.app.model.api_settings import APISettings
from pydantic import BaseModel, ConfigDict, Field

from openbb_mcp_server.models.capability import (
    CapabilityInventory,
    CapabilityRecord,
    OperationKey,
    Persistence,
    VerificationState,
)
from openbb_mcp_server.models.mcp_config import is_valid_mcp_config
from openbb_mcp_server.models.settings import MCPSettings
from openbb_mcp_server.service.capability_import_guard import metadata_import_guard
from openbb_mcp_server.service.capability_provenance import (
    DEFAULT_MODULES,
    DistributionMetadata,
    EnvironmentFlag,
    ImportMetadata,
    LineageMetadata,
    RepositoryMetadata,
    RuntimeMetadata,
    ServiceMetadata,
    SubmoduleMetadata,
    collect_runtime_metadata,
    normalize_import_origin,
)

from ..utils.fastapi import (
    _create_prompt_definitions_for_route,
    _resolve_mcp_type,
    _should_exclude_by_module_and_path,
    get_api_prefix,
    get_mcp_config,
    get_mcp_route_identity,
)

ProfileName = Literal["platform-standard", "portfolio-read", "portfolio-ops"]
ProviderStatus = Literal["routed", "unrouted"]
CollisionKind = Literal["operation", "component_name", "tool_name", "prompt_name"]

_PROFILE_ALIASES: dict[ProfileName, str] = {
    "platform-standard": "full.json",
    "portfolio-read": "portfolio.json",
    "portfolio-ops": "portfolio.json",
}
_SENSITIVE_CONFIG_KEY = re.compile(
    r"(?i)(?:auth|token|secret|password|api[_-]?key|headers?)"
)


class ProfileMetadata(BaseModel):
    """Sanitized selected-profile metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_name: ProfileName
    source_profile: str
    alias_group: str
    api_prefix: str
    config_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    default_tool_categories: tuple[str, ...]
    enable_tool_discovery: bool


class ProviderModelMetadata(BaseModel):
    """One provider/model registration joined to commands and MCP tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    fetcher_class: str
    fetcher_module: str
    implementation_id: str
    persistence: Persistence
    commands: tuple[str, ...]
    tool_names: tuple[str, ...]
    credential_fields: tuple[str, ...]
    provider_registered: bool
    status: ProviderStatus


class CollisionMetadata(BaseModel):
    """An explicit duplicate operation, tool, or prompt identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CollisionKind
    key: str
    capability_ids: tuple[str, ...]


class InventoryDenominators(BaseModel):
    """Explicit record-type and environment-conditioned denominators."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    route_records: int
    direct_route_records: int
    restricted_route_records: int
    prompt_records: int
    profile_records: int
    missing_core_entry_points: tuple[str, ...]


class InventoryDocument(BaseModel):
    """Complete deterministic inventory output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    metadata_only: Literal[True] = True
    profile: ProfileMetadata
    capabilities: CapabilityInventory
    denominators: InventoryDenominators
    provider_models: tuple[ProviderModelMetadata, ...]
    collisions: tuple[CollisionMetadata, ...]
    runtime: RuntimeMetadata
    lineage: LineageMetadata | None = None
    unavailable_components: tuple[str, ...]
    scope_limitations: tuple[str, ...]


@dataclass(frozen=True)
class InventorySources:
    """Dependency-injected source registries for metadata collection."""

    app: FastAPI
    settings: MCPSettings
    profile: ProfileMetadata
    command_models: Mapping[str, str]
    model_providers: Mapping[str, tuple[str, ...]]
    provider_credentials: Mapping[str, tuple[str, ...]]
    provider_fetchers: Mapping[str, Mapping[str, type]]
    static_prompts: tuple[dict[str, Any], ...]
    runtime: RuntimeMetadata
    unavailable_components: tuple[str, ...] = ()
    scope_limitations: tuple[str, ...] = ()
    specialists: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    source_operations: tuple[tuple[str, str, str], ...] = ()


def _canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value deterministically."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def config_fingerprint(config: Mapping[str, Any]) -> str:
    """Return a deterministic SHA256 for already-sanitized profile metadata."""
    return hashlib.sha256(_canonical_json(config).encode("utf-8")).hexdigest()


def _sanitize_profile_config(value: Any) -> Any:
    """Remove comments and credential-bearing configuration branches."""
    if isinstance(value, dict):
        sanitized = {}
        for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key = str(raw_key)
            if key.startswith("_") or _SENSITIVE_CONFIG_KEY.search(key):
                continue
            safe_item = _sanitize_profile_config(item)
            if isinstance(item, dict) and not safe_item:
                continue
            sanitized[key] = safe_item
        return sanitized
    if isinstance(value, list):
        return [_sanitize_profile_config(item) for item in value]
    return value


def _profile_config(
    profile_name: ProfileName,
    *,
    profiles_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Load one committed profile and remove unsafe/non-contract fields."""
    directory = profiles_dir or (
        Path(__file__).resolve().parents[1] / "assets" / "profiles"
    )
    source_name = _PROFILE_ALIASES[profile_name]
    raw = json.loads((directory / source_name).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("MCP profile must be a JSON object")
    config = _sanitize_profile_config(raw)
    config.setdefault("OPENBB_MCP_API_PREFIX", APISettings().prefix)
    return source_name, config


def load_profile_metadata(
    profile_name: ProfileName,
    *,
    profiles_dir: Path | None = None,
) -> ProfileMetadata:
    """Load sanitized metadata for one inventory profile alias."""
    source_name, config = _profile_config(profile_name, profiles_dir=profiles_dir)
    categories = config.get("OPENBB_MCP_DEFAULT_TOOL_CATEGORIES", [])
    return ProfileMetadata(
        selected_name=profile_name,
        source_profile=source_name,
        alias_group=Path(source_name).stem,
        api_prefix=str(config["OPENBB_MCP_API_PREFIX"]),
        config_fingerprint=config_fingerprint(config),
        default_tool_categories=tuple(str(item) for item in categories),
        enable_tool_discovery=bool(
            config.get("OPENBB_MCP_ENABLE_TOOL_DISCOVERY", False)
        ),
    )


def _source_ref(endpoint: Any) -> str:
    """Return a stable module-level source reference for a callable."""
    module = getattr(endpoint, "__module__", "unknown")
    return f"{str(module).replace('.', '/')}.py"


def _implementation_id(endpoint: Any) -> str:
    """Return a stable opaque Python implementation identity."""
    identity = (
        f"{getattr(endpoint, '__module__', 'unknown')}:"
        f"{getattr(endpoint, '__qualname__', getattr(endpoint, '__name__', 'unknown'))}"
    )
    return f"python:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


def _record_id(*parts: str) -> str:
    """Return a stable opaque record ID from normalized identity parts."""
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"platform:capability:{digest}"


def _local_command_path(path: str, settings: MCPSettings) -> str:
    """Strip the configured API prefix while retaining a leading slash."""
    prefix = get_api_prefix(settings)
    local_path = path[len(prefix) :] if prefix and path.startswith(prefix) else path
    return "/" + local_path.lstrip("/")


def _route_kind(route: APIRoute, method: str, settings: MCPSettings) -> str:
    """Resolve explicit per-method MCP type or the catch-all type."""
    config = get_mcp_config(route)
    if config.mcp_type:
        methods = tuple(item.value for item in config.methods or ())
        if not methods or "*" in methods or method in methods:
            return config.mcp_type.value
    resolved = _resolve_mcp_type(
        str(getattr(settings, "default_catchall_mcp_type", "tool") or "tool")
    )
    return str(resolved.value).lower() if resolved else "tool"


def _requirements_for_model(
    model: str | None, sources: InventorySources
) -> tuple[str, ...]:
    """Return provider and credential field names without reading values."""
    if not model:
        return ()
    requirements = []
    for provider in sorted(sources.model_providers.get(model, ())):
        requirements.append(f"provider:{provider}")
        requirements.extend(
            f"credential-field:{provider}:{field}"
            for field in sorted(sources.provider_credentials.get(provider, ()))
        )
    return tuple(requirements)


def _collect_route_records(
    sources: InventorySources,
) -> tuple[list[CapabilityRecord], dict[str, list[str]], list[dict[str, Any]]]:
    """Collect route records, command-path tool joins and inline prompts."""
    records: list[CapabilityRecord] = []
    tools_by_command: dict[str, list[str]] = defaultdict(list)
    inline_prompts: list[dict[str, Any]] = []
    occurrences: Counter[str] = Counter()
    for route in sources.app.router.routes:
        if not isinstance(route, APIRoute):
            continue
        config = get_mcp_config(route)
        extra = route.openapi_extra or {}
        raw_mcp_config = extra.get("mcp_config") or extra.get("x-mcp") or {}
        if not isinstance(raw_mcp_config, dict) or isinstance(
            is_valid_mcp_config(raw_mcp_config), Exception
        ):
            raw_mcp_config = {}
        name_override = (
            raw_mcp_config.get("name") if isinstance(raw_mcp_config, dict) else None
        )
        excluded_by_config = config.expose is False
        excluded_by_module = _should_exclude_by_module_and_path(
            route.path, sources.settings
        )
        excluded = excluded_by_config or excluded_by_module
        model = (route.openapi_extra or {}).get("model")
        identity = get_mcp_route_identity(
            route.path,
            sources.settings,
            name_override=name_override,
        )
        category = identity.category
        subcategory = identity.subcategory
        effective_name = identity.component_name
        implementation_id = _implementation_id(route.endpoint)
        command_path = _local_command_path(route.path, sources.settings)
        enable_override = (
            raw_mcp_config.get("enable")
            if isinstance(raw_mcp_config, dict)
            and isinstance(raw_mcp_config.get("enable"), bool)
            else None
        )
        extra_tags = tuple(
            str(tag)
            for tag in (
                raw_mcp_config.get("tags", ())
                if isinstance(raw_mcp_config, dict)
                else ()
            )
        )
        fixed_toolset_enabled = (
            enable_override
            if enable_override is not None
            else "all" in sources.settings.default_tool_categories
            or bool(
                {category, *extra_tags} & set(sources.settings.default_tool_categories)
            )
        )
        startup_enabled = (
            fixed_toolset_enabled and not sources.settings.enable_tool_discovery
        )
        if excluded:
            fixed_toolset_enabled = False
            startup_enabled = False
        prompt_definitions = _create_prompt_definitions_for_route(
            route, sources.settings
        )
        if not excluded:
            inline_prompts.extend(
                {**prompt, "effective_component": effective_name}
                for prompt in prompt_definitions
            )
        for raw_method in sorted(route.methods or ()):
            method = raw_method.upper()
            if method in {"HEAD", "OPTIONS"}:
                continue
            base_identity = "\0".join(
                (method, route.path, effective_name, implementation_id)
            )
            occurrence = occurrences[base_identity]
            occurrences[base_identity] += 1
            capability_id = _record_id(base_identity, str(occurrence))
            route_kind = _route_kind(route, method, sources.settings)
            is_tool = route_kind == "tool" and not excluded
            record_fixed_toolset_enabled = fixed_toolset_enabled if is_tool else False
            record_startup_enabled = startup_enabled if is_tool else False
            disposition = (
                "restricted" if excluded else "direct" if is_tool else "metadata_only"
            )
            if is_tool:
                tools_by_command[command_path].append(effective_name)
            records.append(
                CapabilityRecord(
                    id=capability_id,
                    surface="platform",
                    owner_lane="D-Widgets+QA",
                    source_refs=(_source_ref(route.endpoint),),
                    exclusion_reason=(
                        "Route declares expose=false."
                        if excluded_by_config
                        else (
                            "Route module is excluded from MCP composition."
                            if excluded_by_module
                            else None
                        )
                    ),
                    source_model=str(model) if model else None,
                    implementation_id=implementation_id,
                    operation=OperationKey(method=method, path=route.path),
                    tool_name=effective_name if is_tool else None,
                    disposition=disposition,
                    access_class=(
                        "provider_read" if method == "GET" else "financial_mutation"
                    ),
                    persistence="unverified",
                    requirements=(
                        *_requirements_for_model(
                            str(model) if model else None, sources
                        ),
                        f"mcp-type:{route_kind}",
                        f"category:{category}",
                        f"subcategory:{subcategory}",
                        f"effective-component:{effective_name}",
                        *(f"tag:{tag}" for tag in sorted(extra_tags)),
                        (
                            "fixed-toolset-enabled:"
                            f"{str(record_fixed_toolset_enabled).lower()}"
                        ),
                        f"startup-enabled:{str(record_startup_enabled).lower()}",
                        (
                            "tool-discovery:"
                            f"{str(sources.settings.enable_tool_discovery).lower()}"
                        ),
                        (
                            f"route-enable-override:{str(enable_override).lower()}"
                            if enable_override is not None
                            else "route-enable-override:unset"
                        ),
                        "access-classification:provisional-method-derived",
                        "owner-classification:provisional-placeholder",
                    ),
                    verification=VerificationState(schema=True),
                )
            )
    return records, tools_by_command, inline_prompts


def _prompt_records(
    prompts: list[dict[str, Any]],
    *,
    source_ref: str,
) -> list[CapabilityRecord]:
    """Convert prompt declarations into metadata-only capability records."""
    records = []
    occurrences: Counter[str] = Counter()
    for prompt in prompts:
        name = str(prompt.get("name") or "unnamed_prompt")
        occurrence = occurrences[name]
        occurrences[name] += 1
        identity = hashlib.sha256(
            f"{name}\0{source_ref}\0{occurrence}".encode()
        ).hexdigest()
        records.append(
            CapabilityRecord(
                id=f"platform:prompt:{identity}",
                surface="platform",
                owner_lane="D-Widgets+QA",
                source_refs=(source_ref,),
                implementation_id=f"prompt:{hashlib.sha256(name.encode()).hexdigest()}",
                disposition="metadata_only",
                access_class="public_metadata",
                persistence="not_applicable",
                requirements=(
                    f"prompt-name:{name}",
                    *(
                        (f"runtime-tool-key:{prompt['tool']}",)
                        if prompt.get("tool")
                        else ()
                    ),
                    *(
                        (f"effective-component:{prompt['effective_component']}",)
                        if prompt.get("effective_component")
                        else ()
                    ),
                ),
                verification=VerificationState(schema=True),
            )
        )
    return records


def _profile_record(profile: ProfileMetadata) -> CapabilityRecord:
    """Return the selected profile as a metadata capability."""
    return CapabilityRecord(
        id=f"platform:profile:{profile.selected_name}",
        surface="platform",
        owner_lane="PM",
        source_refs=(f"openbb_mcp_server/assets/profiles/{profile.source_profile}",),
        implementation_id=f"profile:{profile.config_fingerprint}",
        disposition="metadata_only",
        access_class="public_metadata",
        persistence="not_applicable",
        requirements=(
            f"profile-alias-group:{profile.alias_group}",
            f"api-prefix:{profile.api_prefix}",
            *(f"category:{category}" for category in profile.default_tool_categories),
        ),
        verification=VerificationState(schema=True),
    )


def _specialist_records(
    specialists: Mapping[str, tuple[str, ...]],
) -> list[CapabilityRecord]:
    """Represent source-discovered separate MCP registries."""
    records = []
    source_refs = {
        "agents": ("openbb_platform/extensions/agents/openbb_agents/mcp_server.py",),
        "daytrade": (
            "openbb_platform/extensions/fmp_trading/"
            "openbb_fmp_trading/agent/mcp_server.py",
        ),
    }
    access_classes = {
        "agents": "private_portfolio_read",
        "daytrade": "provider_read",
    }
    for surface, names in sorted(specialists.items()):
        for name in sorted(names):
            records.append(
                CapabilityRecord(
                    id=f"{surface}:tool:{name}",
                    surface=surface,
                    owner_lane="D-Widgets+QA",
                    source_refs=source_refs[surface],
                    implementation_id=f"{surface}:{name}",
                    tool_name=name,
                    disposition="direct",
                    access_class=access_classes[surface],
                    persistence="not_applicable",
                    requirements=(f"specialist-registry:{surface}",),
                    verification=VerificationState(schema=True),
                )
            )
    return records


def _source_operation_records(
    operations: tuple[tuple[str, str, str], ...],
    existing: set[tuple[str, str]],
) -> list[CapabilityRecord]:
    """Retain raw source operations removed by reviewed runtime adapters."""
    records = []
    for method, path, source_ref in operations:
        identity = (method, path)
        if identity in existing:
            continue
        records.append(
            CapabilityRecord(
                id=_record_id("raw-source-operation", method, path),
                surface="platform",
                owner_lane="D-Widgets+QA",
                source_refs=(source_ref,),
                decision_ref="source-registry-audit",
                operation=OperationKey(method=method, path=path),
                disposition="restricted",
                access_class=(
                    "provider_read" if method == "GET" else "financial_mutation"
                ),
                persistence="unverified",
                requirements=("raw-source-registry:portfolio",),
                verification=VerificationState(schema=True),
            )
        )
    return records


def collect_capabilities(
    profile_name: ProfileName,
    *,
    sources: InventorySources | None = None,
    repo_root: Path | None = None,
) -> list[CapabilityRecord]:
    """Collect stable capability records without executing business functions."""
    return list(
        build_inventory(
            profile_name,
            sources=sources,
            repo_root=repo_root,
        ).capabilities.records
    )


def _provider_model_rows(
    sources: InventorySources,
    tools_by_command: Mapping[str, list[str]],
) -> tuple[ProviderModelMetadata, ...]:
    """Join provider fetcher registrations to command and effective tool metadata."""
    commands_by_model: dict[str, list[str]] = defaultdict(list)
    for command, model in sources.command_models.items():
        commands_by_model[model].append(command)
    rows = []
    for provider, fetchers in sorted(sources.provider_fetchers.items()):
        credentials = tuple(sorted(sources.provider_credentials.get(provider, ())))
        for model, fetcher in sorted(fetchers.items()):
            module = str(getattr(fetcher, "__module__", "unknown"))
            class_name = str(getattr(fetcher, "__name__", "unknown"))
            commands = tuple(sorted(commands_by_model.get(model, ())))
            tool_names = tuple(
                sorted(
                    {
                        tool
                        for command in commands
                        for tool in tools_by_command.get(command, ())
                    }
                )
            )
            if provider == "fmp_cached":
                persistence: Persistence = (
                    "fallback_none"
                    if module == "openbb_fmp_cached.models.base_cached"
                    else "dedicated"
                )
            else:
                persistence = "unverified"
            provider_registered = provider in sources.model_providers.get(model, ())
            rows.append(
                ProviderModelMetadata(
                    provider=provider,
                    model=model,
                    fetcher_class=class_name,
                    fetcher_module=module,
                    implementation_id=(
                        f"python:{hashlib.sha256(f'{module}:{class_name}'.encode()).hexdigest()}"
                    ),
                    persistence=persistence,
                    commands=commands,
                    tool_names=tool_names,
                    credential_fields=credentials,
                    provider_registered=provider_registered,
                    status=(
                        "routed" if commands and provider_registered else "unrouted"
                    ),
                )
            )
    return tuple(sorted(rows, key=lambda row: (row.provider, row.model)))


def _collisions(records: list[CapabilityRecord]) -> tuple[CollisionMetadata, ...]:
    """Return duplicate operation, tool, and prompt identities."""
    groups: dict[tuple[CollisionKind, str], list[str]] = defaultdict(list)
    for record in records:
        if record.operation:
            key = f"{record.operation.method} {record.operation.path}"
            groups[("operation", key)].append(record.id)
            component_name = next(
                (
                    requirement.removeprefix("effective-component:")
                    for requirement in record.requirements
                    if requirement.startswith("effective-component:")
                ),
                None,
            )
            if component_name:
                groups[("component_name", component_name)].append(record.id)
        if record.tool_name:
            groups[("tool_name", record.tool_name)].append(record.id)
        if record.implementation_id and record.implementation_id.startswith("prompt:"):
            prompt_name = next(
                (
                    requirement.removeprefix("prompt-name:")
                    for requirement in record.requirements
                    if requirement.startswith("prompt-name:")
                ),
                record.implementation_id,
            )
            groups[("prompt_name", prompt_name)].append(record.id)
    return tuple(
        CollisionMetadata(
            kind=kind,
            key=key,
            capability_ids=tuple(sorted(capability_ids)),
        )
        for (kind, key), capability_ids in sorted(groups.items())
        if len(capability_ids) > 1
    )


def build_inventory(
    profile_name: ProfileName,
    *,
    sources: InventorySources | None = None,
    repo_root: Path | None = None,
    validate: bool = True,
) -> InventoryDocument:
    """Build a complete deterministic metadata-only inventory."""
    resolved_sources = sources or load_default_sources(
        profile_name, repo_root=repo_root
    )
    route_records, tools_by_command, inline_prompts = _collect_route_records(
        resolved_sources
    )
    source_operation_records = _source_operation_records(
        resolved_sources.source_operations,
        {
            (record.operation.method, record.operation.path)
            for record in route_records
            if record.operation
        },
    )
    records = [
        *route_records,
        *source_operation_records,
        *_prompt_records(
            inline_prompts,
            source_ref="openbb_mcp_server/utils/fastapi.py",
        ),
        *_prompt_records(
            list(resolved_sources.static_prompts),
            source_ref="openbb_mcp_server/assets/server_prompts.json",
        ),
        *_specialist_records(resolved_sources.specialists),
        _profile_record(resolved_sources.profile),
    ]
    records = sorted(records, key=lambda record: record.id)
    route_categories = {
        requirement.removeprefix("category:")
        for record in records
        if record.operation
        for requirement in record.requirements
        if requirement.startswith("category:")
    }
    unavailable_components = list(resolved_sources.unavailable_components)
    unavailable_components.extend(
        f"profile-category:{category}:no_matching_routes"
        for category in resolved_sources.profile.default_tool_categories
        if category != "all" and category not in route_categories
    )
    document = InventoryDocument(
        profile=resolved_sources.profile,
        capabilities=CapabilityInventory(records=records),
        denominators=InventoryDenominators(
            route_records=sum(record.operation is not None for record in records),
            direct_route_records=sum(
                record.operation is not None and record.disposition == "direct"
                for record in records
            ),
            restricted_route_records=sum(
                record.operation is not None and record.disposition == "restricted"
                for record in records
            ),
            prompt_records=sum(
                record.id.startswith("platform:prompt:") for record in records
            ),
            profile_records=sum(
                record.id.startswith("platform:profile:") for record in records
            ),
            missing_core_entry_points=tuple(
                sorted(
                    component.split(":", maxsplit=3)[2]
                    for component in unavailable_components
                    if component.startswith("entry-point:openbb_core_extension:")
                    and component.endswith(":missing_from_environment")
                )
            ),
        ),
        provider_models=_provider_model_rows(resolved_sources, tools_by_command),
        collisions=_collisions(records),
        runtime=resolved_sources.runtime,
        unavailable_components=tuple(sorted(unavailable_components)),
        scope_limitations=tuple(sorted(resolved_sources.scope_limitations)),
    )
    if validate:
        validate_inventory_evidence(document)
    return document


def validate_inventory_evidence(document: InventoryDocument) -> None:
    """Refuse truncated or foreign-source documents as parity evidence."""
    foreign_sources = [
        component
        for component in document.unavailable_components
        if component.startswith("source:")
        or (
            component.startswith(
                (
                    "entry-point:openbb_core_extension:",
                    "entry-point:openbb_provider_extension:",
                )
            )
            and component.endswith((":outside_repo_root", ":target_mismatch"))
        )
    ]
    if foreign_sources:
        raise RuntimeError("Inventory contains foreign entry points or sources")
    if not any(
        record.disposition == "direct" for record in document.capabilities.records
    ):
        raise RuntimeError("Inventory contains no direct route capabilities")
    provider_missing = (
        "provider:fmp_cached:package_missing" in document.unavailable_components
    )
    if not document.provider_models and not provider_missing:
        raise RuntimeError(
            "Inventory contains no provider models and no explicit missing package"
        )


def load_default_sources(
    profile_name: ProfileName,
    *,
    repo_root: Path | None = None,
) -> InventorySources:
    """Load source registries without executing business or transport functions."""
    # pylint: disable=too-many-locals
    root = (repo_root or Path(__file__).resolve().parents[5]).resolve()
    _, safe_config = _profile_config(profile_name)
    settings = MCPSettings.model_validate(safe_config)
    settings = settings.model_copy(
        update={
            "capability_profile": profile_name,
            "runtime_profile": profile_name,
        }
    )
    profile = load_profile_metadata(profile_name)

    provider_fetchers: dict[str, Mapping[str, type]] = {}
    specialists: dict[str, tuple[str, ...]] = {}
    source_operations: list[tuple[str, str, str]] = []
    unavailable: list[str] = []
    with metadata_import_guard(root, unavailable):
        # Keep optional/heavy registries outside synthetic metadata-only imports.
        # pylint: disable=import-outside-toplevel
        from openbb_core.api.rest_api import app
        from openbb_core.app.provider_interface import ProviderInterface
        from openbb_core.app.router import CommandMap

        provider_interface = ProviderInterface()
        command_map = CommandMap()
        command_models = dict(command_map.commands_model)
        model_providers = {}
        for model, choices in provider_interface.model_providers.items():
            annotation = getattr(choices, "__annotations__", {}).get("provider")
            model_providers[model] = tuple(get_args(annotation)) if annotation else ()
        provider_credentials = {
            provider: tuple(sorted(fields))
            for provider, fields in provider_interface.credentials.items()
        }
        if importlib.util.find_spec("openbb_fmp_cached") is None:
            unavailable.append("provider:fmp_cached:package_missing")
        else:
            from openbb_fmp_cached import fmp_cached_provider
            from openbb_fmp_cached.fmp_cached_router import router as fmp_cached_router

            provider_fetchers["fmp_cached"] = fmp_cached_provider.fetcher_dict
            prefix = f"{settings.api_prefix}/fmp_cached"
            if not any(route.path.startswith(prefix) for route in app.router.routes):
                app.include_router(fmp_cached_router.api_router, prefix=prefix)
            for route in app.router.routes:
                if (
                    isinstance(route, APIRoute)
                    and route.openapi_extra
                    and route.openapi_extra.get("model")
                ):
                    command = route.path.removeprefix(settings.api_prefix)
                    command_models[command] = route.openapi_extra["model"]

        if profile_name in {"portfolio-read", "portfolio-ops"}:
            from openbb_portfolio import portfolio_router

            from openbb_mcp_server.adapters.cache_admin import (
                compose_cache_observability_app,
            )
            from openbb_mcp_server.adapters.portfolio import compose_portfolio_app

            for route in portfolio_router.router.routes:
                if not isinstance(route, APIRoute):
                    continue
                for method in sorted(route.methods or ()):
                    if method not in {"HEAD", "OPTIONS"}:
                        source_operations.append(
                            (method.upper(), route.path, _source_ref(route.endpoint))
                        )

            app = compose_portfolio_app(app, settings)
            app = compose_cache_observability_app(app)
            if profile_name == "portfolio-ops":
                from openbb_mcp_server.adapters.cache_jobs import (
                    compose_cache_jobs_app,
                )

                app = compose_cache_jobs_app(app)
            if settings.enable_intelligence_adapter:
                from openbb_mcp_server.adapters.portfolio_intel import (
                    compose_portfolio_intel_app,
                )
                from openbb_mcp_server.service.exposure_policy import ExposurePolicy

                metadata_token = secrets.token_urlsafe(32)
                with patch.dict(
                    "os.environ",
                    {"PI_WIDGET_BACKEND_TOKEN": metadata_token},
                ):
                    from openbb_portfolio_intel.widget_backend.main import (
                        app as intelligence_app,
                    )

                app = compose_portfolio_intel_app(
                    app,
                    intelligence_app,
                    settings,
                    ExposurePolicy.load(),
                    upstream_token=metadata_token,
                )

        if importlib.util.find_spec("openbb_agents") is None:
            unavailable.append("specialist:agents:package_missing")
        else:
            from openbb_agents.mcp_server import collect_tools

            specialists["agents"] = tuple(
                sorted(str(tool["name"]) for tool in collect_tools())
            )
        if importlib.util.find_spec("openbb_fmp_trading") is None:
            unavailable.append("specialist:daytrade:package_missing")
        else:
            from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

            specialists["daytrade"] = tuple(sorted(mcp_tool_names()))

        for route in app.router.routes:
            if (
                isinstance(route, APIRoute)
                and route.openapi_extra
                and route.openapi_extra.get("model")
            ):
                command = route.path.removeprefix(settings.api_prefix)
                command_models[command] = route.openapi_extra["model"]

    prompts_file = (
        Path(__file__).resolve().parents[1] / "assets" / "server_prompts.json"
    )
    prompts_payload = json.loads(prompts_file.read_text(encoding="utf-8"))
    static_prompts = tuple(prompts_payload) if isinstance(prompts_payload, list) else ()
    route_paths = {
        route.path for route in app.router.routes if isinstance(route, APIRoute)
    }
    route_modules = {
        str(getattr(route.endpoint, "__module__", "")).split(".", maxsplit=1)[0]
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }
    fetcher_modules = {
        str(getattr(fetcher, "__module__", "")).split(".", maxsplit=1)[0]
        for fetchers in provider_fetchers.values()
        for fetcher in fetchers.values()
    }
    specialist_modules = {
        "openbb_agents" if surface == "agents" else "openbb_fmp_trading"
        for surface, names in specialists.items()
        if names
    }
    contributing_modules = tuple(
        sorted(
            {
                *DEFAULT_MODULES,
                *(module for module in route_modules if module),
                *(module for module in fetcher_modules if module),
                *specialist_modules,
            }
        )
    )
    runtime = collect_runtime_metadata(root, module_names=contributing_modules)
    runtime = RuntimeMetadata.model_validate(
        {
            **runtime.model_dump(),
            "environment_flags": (
                {
                    "name": "DEV_MODE_EFFECTIVE",
                    "value": any("/system/" in path for path in route_paths),
                },
                {
                    "name": "JOBS_ENABLED_EFFECTIVE",
                    "value": any("/jobs/" in path for path in route_paths),
                },
            ),
        }
    )
    for import_metadata in runtime.imports:
        if (
            import_metadata.module
            in {*route_modules, *fetcher_modules, *specialist_modules}
            and import_metadata.origin
            and not import_metadata.origin.startswith("repo://")
        ):
            unavailable.append(f"source:{import_metadata.module}:outside_repo_root")
    return InventorySources(
        app=app,
        settings=settings,
        profile=profile,
        command_models=command_models,
        model_providers=model_providers,
        provider_credentials=provider_credentials,
        provider_fetchers=provider_fetchers,
        static_prompts=static_prompts,
        runtime=runtime,
        unavailable_components=tuple(unavailable),
        scope_limitations=(
            "access-class:provisional-method-derived-2154",
            "dev-mode-routes:forced-disabled",
            "fastmcp-admin-tools:not-enumerated",
            "owner-lane:provisional-placeholder-2154",
            "skills-derived-prompts:not-enumerated",
            "provider-fetchers:fmp_cached-only",
        ),
        specialists=specialists,
        source_operations=tuple(sorted(set(source_operations))),
    )


def _atomic_write(path: Path, content: str) -> None:
    """Atomically replace one UTF-8/LF inventory artifact."""
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
    temporary.replace(path)


def _csv_text(fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    """Return deterministic CSV text."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fieldnames,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(
        {
            key: (
                f"'{value}"
                if isinstance(value, str)
                and (
                    value.startswith(("\t", "\r", "\n"))
                    or value.lstrip().startswith(("=", "+", "-", "@"))
                )
                else value
            )
            for key, value in row.items()
        }
        for row in rows
    )
    return stream.getvalue()


def write_inventory(document: InventoryDocument, output_dir: Path) -> tuple[Path, ...]:
    """Write stable JSON and CSV inventory artifacts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = output_dir / "inventory.json"
    capabilities_path = output_dir / "capabilities.csv"
    provider_models_path = output_dir / "provider_models.csv"
    _atomic_write(
        inventory_path,
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    capability_rows = []
    for record in sorted(document.capabilities.records, key=lambda item: item.id):
        capability_rows.append(
            {
                "id": record.id,
                "surface": record.surface,
                "owner_lane": record.owner_lane,
                "source_refs": "|".join(record.source_refs),
                "source_model": record.source_model or "",
                "implementation_id": record.implementation_id or "",
                "exclusion_reason": record.exclusion_reason or "",
                "method": record.operation.method if record.operation else "",
                "path": record.operation.path if record.operation else "",
                "tool_name": record.tool_name or "",
                "disposition": record.disposition,
                "access_class": record.access_class,
                "persistence": record.persistence,
                "requirements": "|".join(record.requirements),
                "schema_verified": str(record.verification.schema_verified).lower(),
                "offline_call": str(record.verification.offline_call).lower(),
                "live_call": str(record.verification.live_call).lower(),
            }
        )
    _atomic_write(
        capabilities_path,
        _csv_text(
            (
                "id",
                "surface",
                "owner_lane",
                "source_refs",
                "source_model",
                "implementation_id",
                "exclusion_reason",
                "method",
                "path",
                "tool_name",
                "disposition",
                "access_class",
                "persistence",
                "requirements",
                "schema_verified",
                "offline_call",
                "live_call",
            ),
            capability_rows,
        ),
    )
    provider_rows = [
        {
            "provider": row.provider,
            "model": row.model,
            "fetcher_class": row.fetcher_class,
            "fetcher_module": row.fetcher_module,
            "implementation_id": row.implementation_id,
            "persistence": row.persistence,
            "commands": "|".join(row.commands),
            "tool_names": "|".join(row.tool_names),
            "credential_fields": "|".join(row.credential_fields),
            "provider_registered": str(row.provider_registered).lower(),
            "status": row.status,
        }
        for row in document.provider_models
    ]
    _atomic_write(
        provider_models_path,
        _csv_text(
            (
                "provider",
                "model",
                "fetcher_class",
                "fetcher_module",
                "implementation_id",
                "persistence",
                "commands",
                "tool_names",
                "credential_fields",
                "provider_registered",
                "status",
            ),
            provider_rows,
        ),
    )
    return inventory_path, capabilities_path, provider_models_path


__all__ = [
    "CollisionMetadata",
    "DistributionMetadata",
    "EnvironmentFlag",
    "ImportMetadata",
    "InventoryDenominators",
    "InventoryDocument",
    "InventorySources",
    "ProfileMetadata",
    "ProviderModelMetadata",
    "RepositoryMetadata",
    "RuntimeMetadata",
    "ServiceMetadata",
    "SubmoduleMetadata",
    "build_inventory",
    "collect_capabilities",
    "collect_runtime_metadata",
    "config_fingerprint",
    "load_default_sources",
    "load_profile_metadata",
    "normalize_import_origin",
    "validate_inventory_evidence",
    "write_inventory",
]
