"""Validated deterministic MCP installation and runtime profiles."""

import importlib.metadata
import importlib.util
import json
import os
import platform
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeAlias
from urllib.parse import unquote, urlparse

from packaging.specifiers import SpecifierSet
from pydantic import BaseModel, ConfigDict

from ..models.settings import CapabilityProfile, MCPSettings
from .mcp_service import MCPService

ProfileName: TypeAlias = CapabilityProfile

InstallationKind = Literal["isolated_uv", "portfolio_venv"]
AppKind = Literal["core", "custom"]
SettingsSource = Literal["explicit", "effective_service"]


class AppComposition(BaseModel):
    """FastAPI application composition required by a profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AppKind
    target: str


class RuntimeProfile(BaseModel):
    """Explicit package, app and policy manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    installation: InstallationKind
    python: str
    policy_profile: ProfileName
    app: AppComposition
    required_distributions: tuple[str, ...]
    required_modules: tuple[str, ...]
    required_versions: dict[str, str]
    distribution_sources: dict[str, str]
    module_sources: dict[str, str]
    optional_module_sources: dict[str, dict[str, str]]
    optional_analytics: tuple[str, ...]
    operator_access: bool
    maintenance_enabled: bool


class RuntimeProfilesDocument(BaseModel):
    """Versioned runtime profile asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    profiles: dict[ProfileName, RuntimeProfile]


class RuntimeProfileResolution(BaseModel):
    """Local resolution evidence for one selected profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: ProfileName
    profile: RuntimeProfile
    missing_distributions: tuple[str, ...]
    missing_modules: tuple[str, ...]
    conflicts: tuple[str, ...]
    python_version: str
    python_compatible: bool
    installation_matches: bool
    optional_available: tuple[str, ...]
    optional_missing: tuple[str, ...]
    selected_analytics: tuple[str, ...]
    distribution_versions: dict[str, str]
    distribution_origins: dict[str, str]
    module_origins: dict[str, str]
    source_conflicts: tuple[str, ...]
    configuration: "RuntimeConfigurationEvidence"
    provenance_checked: bool
    ready: bool


class RuntimeConfigurationEvidence(BaseModel):
    """Policy-relevant effective settings used by profile resolution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SettingsSource
    runtime_profile: ProfileName | None
    capability_profile: ProfileName | None
    app_target: str | None
    installation_kind: InstallationKind | None
    maintenance_requested: bool
    selected_analytics: tuple[str, ...]


def load_runtime_profiles(path: Path | None = None) -> RuntimeProfilesDocument:
    """Load the committed versioned runtime profile asset."""
    asset = path or (
        Path(__file__).resolve().parents[1] / "assets" / "runtime_profiles.json"
    )
    return RuntimeProfilesDocument.model_validate_json(
        asset.read_text(encoding="utf-8")
    )


def _distribution_available(name: str) -> bool:
    try:
        importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _distribution_origin(name: str) -> Path | None:
    """Return an installed distribution's editable source or install location."""
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            payload = json.loads(direct_url)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        parsed = urlparse(payload.get("url", ""))
        directory = payload.get("dir_info")
        editable = isinstance(directory, dict) and directory.get("editable") is True
        if editable and parsed.scheme == "file":
            path = unquote(parsed.path)
            if parsed.netloc:
                path = f"//{parsed.netloc}{path}"
            if os.name == "nt" and path.startswith("/") and path[2:3] == ":":
                path = path[1:]
            return Path(path).resolve()
    return Path(str(distribution.locate_file(""))).resolve()


def _module_origin(name: str) -> Path | None:
    """Return the import root for a module without importing it."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).resolve()
    if spec.origin and spec.origin not in {"built-in", "frozen"}:
        return Path(spec.origin).resolve().parent
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _display_origin(path: Path | None, repository_root: Path) -> str:
    if path is None:
        return "unresolved"
    if _is_relative_to(path, repository_root):
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    return "outside_repository"


def _display_app_target(
    target: str | None,
    repository_root: Path | None,
) -> str | None:
    if not target:
        return target
    candidate = Path(target)
    if not candidate.is_absolute():
        return target.replace("\\", "/")
    if repository_root is not None and _is_relative_to(candidate, repository_root):
        return candidate.resolve().relative_to(repository_root.resolve()).as_posix()
    return "outside_repository"


def _resolve_source_evidence(
    expected_sources: dict[str, str],
    origin: Callable[[str], Path | None],
    repository_root: Path,
    kind: str,
) -> tuple[dict[str, str], tuple[str, ...]]:
    evidence: dict[str, str] = {}
    conflicts: list[str] = []
    for name, relative_source in expected_sources.items():
        actual = origin(name)
        expected = repository_root / relative_source
        evidence[name] = _display_origin(actual, repository_root)
        if actual is None or not _is_relative_to(actual, expected):
            conflicts.append(f"{kind}:{name}")
    return evidence, tuple(conflicts)


# Explicit probes keep clean-install and mismatch scenarios deterministic in tests.
# pylint: disable=too-many-arguments,too-many-locals
def resolve_runtime_profile(
    name: ProfileName,
    *,
    settings: MCPSettings | None = None,
    document: RuntimeProfilesDocument | None = None,
    distribution_available: Callable[[str], bool] = _distribution_available,
    module_available: Callable[[str], bool] = _module_available,
    active_installation: InstallationKind | None = None,
    python_version: str | None = None,
    repository_root: Path | None = None,
    distribution_origin: Callable[[str], Path | None] = _distribution_origin,
    distribution_version: Callable[[str], str | None] = _distribution_version,
    module_origin: Callable[[str], Path | None] = _module_origin,
) -> RuntimeProfileResolution:
    """Resolve required components and reject conflicting runtime config."""
    profiles = document or load_runtime_profiles()
    if name not in profiles.profiles:
        raise KeyError(f"Unknown runtime profile: {name}")
    profile = profiles.profiles[name]
    if settings is None:
        config = MCPService.read_with_overrides()
        settings_source: SettingsSource = "effective_service"
    else:
        config = settings
        settings_source = "explicit"
    conflict_items: list[str] = []
    selected_policy = getattr(config, "capability_profile", None)
    if selected_policy and selected_policy != profile.policy_profile:
        conflict_items.append(
            f"capability_profile:{selected_policy}!={profile.policy_profile}"
        )
    selected_runtime = getattr(config, "runtime_profile", None)
    if selected_runtime and selected_runtime != name:
        conflict_items.append(f"runtime_profile:{selected_runtime}!={name}")
    selected_app = _display_app_target(config.app_target, repository_root)
    if selected_app and selected_app != profile.app.target:
        conflict_items.append(f"app_target:{selected_app}!={profile.app.target}")
    maintenance_requested = bool(
        getattr(config, "enable_maintenance_operations", False)
    )
    if maintenance_requested and not profile.maintenance_enabled:
        conflict_items.append("maintenance_not_enabled_by_profile")
    if profile.operator_access and profile.maintenance_enabled:
        conflict_items.append("operator_profile_must_not_implicitly_enable_maintenance")

    missing_distributions = tuple(
        name
        for name in profile.required_distributions
        if not distribution_available(name)
    )
    configured_installation = config.installation_kind
    if (
        active_installation is not None
        and configured_installation is not None
        and active_installation != configured_installation
    ):
        conflict_items.append(
            "installation_kind_override:"
            f"{configured_installation}!={active_installation}"
        )
    selected_installation = active_installation or configured_installation
    installation_matches = selected_installation == profile.installation
    if selected_installation is None:
        conflict_items.append("installation_kind_missing")
    elif not installation_matches:
        conflict_items.append(
            f"installation_kind:{selected_installation}!={profile.installation}"
        )
    current_python = python_version or platform.python_version()
    python_compatible = current_python in SpecifierSet(profile.python)
    if not python_compatible:
        conflict_items.append(f"python_version:{current_python}!={profile.python}")
    missing_modules = tuple(
        name for name in profile.required_modules if not module_available(name)
    )
    optional_available = tuple(
        item for item in profile.optional_analytics if distribution_available(item)
    )
    optional_missing = tuple(
        item for item in profile.optional_analytics if item not in optional_available
    )
    selected_analytics = tuple(sorted(getattr(config, "selected_analytics", ())))
    inspected_distributions = (*profile.required_distributions, *selected_analytics)
    distribution_versions = {
        item: version
        for item in inspected_distributions
        if (version := distribution_version(item)) is not None
    }
    for distribution, expected_version in profile.required_versions.items():
        actual_version = distribution_versions.get(distribution)
        if actual_version != expected_version:
            conflict_items.append(
                "distribution_version:"
                f"{distribution}:{actual_version or 'missing'}!={expected_version}"
            )
    unknown_analytics = set(selected_analytics) - set(profile.optional_analytics)
    if unknown_analytics:
        conflict_items.append(
            "unknown_analytics:" + ",".join(sorted(unknown_analytics))
        )
    selected_missing = set(selected_analytics) & set(optional_missing)
    if selected_missing:
        conflict_items.append(
            "selected_analytics_missing:" + ",".join(sorted(selected_missing))
        )
    distribution_origins: dict[str, str] = {}
    module_origins: dict[str, str] = {}
    source_conflicts: tuple[str, ...] = ()
    if repository_root is not None:
        distribution_sources = {
            item: source
            for item, source in profile.distribution_sources.items()
            if item in profile.required_distributions or item in selected_analytics
        }
        distribution_origins, distribution_conflicts = _resolve_source_evidence(
            distribution_sources,
            distribution_origin,
            repository_root,
            "distribution",
        )
        module_sources = {
            item: source
            for item, source in profile.module_sources.items()
            if item in profile.required_modules
        }
        for analytic in selected_analytics:
            module_sources.update(profile.optional_module_sources.get(analytic, {}))
        module_origins, module_conflicts = _resolve_source_evidence(
            module_sources,
            module_origin,
            repository_root,
            "module",
        )
        source_conflicts = tuple(sorted(distribution_conflicts + module_conflicts))
        conflict_items.extend(f"source_origin:{item}" for item in source_conflicts)
    conflicts = tuple(sorted(conflict_items))
    configuration = RuntimeConfigurationEvidence(
        source=settings_source,
        runtime_profile=config.runtime_profile,
        capability_profile=config.capability_profile,
        app_target=selected_app,
        installation_kind=config.installation_kind,
        maintenance_requested=maintenance_requested,
        selected_analytics=selected_analytics,
    )
    return RuntimeProfileResolution(
        name=name,
        profile=profile,
        missing_distributions=missing_distributions,
        missing_modules=missing_modules,
        conflicts=conflicts,
        python_version=current_python,
        python_compatible=python_compatible,
        installation_matches=installation_matches,
        optional_available=optional_available,
        optional_missing=optional_missing,
        selected_analytics=selected_analytics,
        distribution_versions=distribution_versions,
        distribution_origins=distribution_origins,
        module_origins=module_origins,
        source_conflicts=source_conflicts,
        configuration=configuration,
        provenance_checked=repository_root is not None,
        ready=not missing_distributions and not missing_modules and not conflicts,
    )


# pylint: enable=too-many-arguments,too-many-locals


def write_runtime_resolution_artifact(
    resolution: RuntimeProfileResolution,
    path: Path,
) -> None:
    """Write replayable, machine-path-free runtime resolution evidence."""
    payload = {
        "schema_version": 1,
        "profile": resolution.name,
        "python": resolution.python_version,
        "python_constraint": resolution.profile.python,
        "installation": resolution.profile.installation,
        "ready": resolution.ready,
        "missing_distributions": resolution.missing_distributions,
        "missing_modules": resolution.missing_modules,
        "conflicts": resolution.conflicts,
        "distribution_versions": resolution.distribution_versions,
        "distribution_origins": resolution.distribution_origins,
        "module_origins": resolution.module_origins,
        "source_conflicts": resolution.source_conflicts,
        "configuration": resolution.configuration.model_dump(mode="json"),
        "provenance_checked": resolution.provenance_checked,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


__all__ = [
    "AppComposition",
    "RuntimeProfile",
    "RuntimeConfigurationEvidence",
    "RuntimeProfileResolution",
    "RuntimeProfilesDocument",
    "load_runtime_profiles",
    "resolve_runtime_profile",
    "write_runtime_resolution_artifact",
]
