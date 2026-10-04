"""Validated deterministic MCP installation and runtime profiles."""

import importlib.metadata
import importlib.util
import os
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypeAlias

from packaging.specifiers import SpecifierSet
from pydantic import BaseModel, ConfigDict

from ..models.settings import CapabilityProfile, MCPSettings

ProfileName: TypeAlias = CapabilityProfile

InstallationKind = Literal["isolated_uv", "portfolio_venv"]
AppKind = Literal["core", "custom"]


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
    python_compatible: bool
    installation_matches: bool
    optional_available: tuple[str, ...]
    optional_missing: tuple[str, ...]
    selected_analytics: tuple[str, ...]
    ready: bool


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


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def resolve_runtime_profile(
    name: ProfileName,
    *,
    settings: MCPSettings | None = None,
    document: RuntimeProfilesDocument | None = None,
    distribution_available: Callable[[str], bool] = _distribution_available,
    module_available: Callable[[str], bool] = _module_available,
    active_installation: InstallationKind | None = None,
    python_version: str | None = None,
) -> RuntimeProfileResolution:
    """Resolve required components and reject conflicting runtime config."""
    profiles = document or load_runtime_profiles()
    if name not in profiles.profiles:
        raise KeyError(f"Unknown runtime profile: {name}")
    profile = profiles.profiles[name]
    if settings is None:
        aliases = {
            field.alias for field in MCPSettings.model_fields.values() if field.alias
        }
        config = MCPSettings.model_validate(
            {alias: os.environ[alias] for alias in aliases if alias in os.environ}
        )
    else:
        config = settings
    conflict_items: list[str] = []
    selected_policy = getattr(config, "capability_profile", None)
    if selected_policy and selected_policy != profile.policy_profile:
        conflict_items.append(
            f"capability_profile:{selected_policy}!={profile.policy_profile}"
        )
    selected_runtime = getattr(config, "runtime_profile", None)
    if selected_runtime and selected_runtime != name:
        conflict_items.append(f"runtime_profile:{selected_runtime}!={name}")
    selected_app = getattr(config, "app_target", None)
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
    selected_installation = active_installation or getattr(
        config, "installation_kind", None
    )
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
    conflicts = tuple(sorted(conflict_items))
    return RuntimeProfileResolution(
        name=name,
        profile=profile,
        missing_distributions=missing_distributions,
        missing_modules=missing_modules,
        conflicts=conflicts,
        python_compatible=python_compatible,
        installation_matches=installation_matches,
        optional_available=optional_available,
        optional_missing=optional_missing,
        selected_analytics=selected_analytics,
        ready=not missing_distributions and not missing_modules and not conflicts,
    )


__all__ = [
    "AppComposition",
    "RuntimeProfile",
    "RuntimeProfileResolution",
    "RuntimeProfilesDocument",
    "load_runtime_profiles",
    "resolve_runtime_profile",
]
