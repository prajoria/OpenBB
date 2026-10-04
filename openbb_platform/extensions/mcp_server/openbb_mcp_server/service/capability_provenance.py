"""Normalized source and runtime provenance for capability inventories."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict

ComponentState = Literal["available", "missing", "unavailable"]
ServiceState = Literal["not_probed_metadata_only"]

DEFAULT_MODULES = (
    "openbb",
    "openbb_core",
    "openbb_mcp_server",
    "openbb_fmp_cached",
    "openbb_portfolio",
    "openbb_portfolio_intel",
    "openbb_agents",
    "openbb_techtrade",
    "fastmcp",
    "pydantic",
)
_DEFAULT_DISTRIBUTIONS = (
    "openbb",
    "openbb-core",
    "openbb-mcp-server",
    "openbb-fmp-cached",
    "openbb-portfolio-custom",
    "openbb-portfolio-intel",
    "openbb-agents",
    "openbb-techtrade",
    "fastmcp",
    "pydantic",
)


class RepositoryMetadata(BaseModel):
    """Repository source state without machine-local paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit: str | None = None
    dirty: bool | None = None
    untracked: bool | None = None
    state: ComponentState


class SubmoduleMetadata(BaseModel):
    """Pinned submodule provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    commit: str


class DistributionMetadata(BaseModel):
    """Installed distribution provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: ComponentState
    version: str | None = None
    editable: bool | None = None
    source: str | None = None


class ImportMetadata(BaseModel):
    """Normalized import availability and origin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module: str
    state: ComponentState
    origin: str | None = None


class ServiceMetadata(BaseModel):
    """Declared runtime service status without an active probe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: ServiceState


class EnvironmentFlag(BaseModel):
    """Route-affecting boolean environment state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: bool


class RuntimeMetadata(BaseModel):
    """Stable runtime and source provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    python_implementation: str
    python_version: str
    repository: RepositoryMetadata
    submodules: tuple[SubmoduleMetadata, ...]
    distributions: tuple[DistributionMetadata, ...]
    imports: tuple[ImportMetadata, ...]
    services: tuple[ServiceMetadata, ...]
    environment_flags: tuple[EnvironmentFlag, ...] = ()


def normalize_import_origin(
    origin: str | None,
    *,
    repo_root: Path,
) -> str | None:
    """Normalize a module origin without exposing an absolute machine path."""
    if origin is None or origin in {"built-in", "frozen"}:
        return origin
    normalized = origin.replace("\\", "/")
    root = repo_root.resolve().as_posix().rstrip("/")
    normalized_case = os.path.normcase(normalized)
    root_case = os.path.normcase(root)
    if normalized_case == root_case or normalized_case.startswith(
        f"{root_case}{os.sep}"
    ):
        relative = normalized[len(root) :].lstrip("/")
        return f"repo://{relative}"
    marker = "/site-packages/"
    if marker in normalized:
        return f"site-packages://{normalized.split(marker, maxsplit=1)[1]}"
    if normalized.endswith("/site-packages"):
        return "site-packages://"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    source_marker = "/openbb_platform/"
    suffix = (
        f"openbb_platform/{normalized.split(source_marker, maxsplit=1)[1]}"
        if source_marker in normalized
        else Path(normalized).name
    )
    return f"external://{digest}/{suffix}"


def _git_output(repo_root: Path, *args: str) -> str | None:
    """Return sanitized Git stdout or ``None`` when Git metadata is unavailable."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "-C", str(repo_root), *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _distribution_metadata(name: str, *, repo_root: Path) -> DistributionMetadata:
    """Read version/editable metadata for one expected distribution."""
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return DistributionMetadata(name=name, state="missing")
    editable = False
    source_path: str | None = None
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            payload = json.loads(direct_url)
        except (json.JSONDecodeError, TypeError):
            payload = {}
        directory = payload.get("dir_info") if isinstance(payload, dict) else None
        editable = isinstance(directory, dict) and directory.get("editable") is True
        url = payload.get("url") if isinstance(payload, dict) else None
        if isinstance(url, str) and url.startswith("file:"):
            parsed = urlparse(url)
            source_path = unquote(parsed.path)
            if re.match(r"^/[A-Za-z]:", source_path):
                source_path = source_path[1:]
            elif parsed.netloc:
                source_path = source_path.lstrip("/")
            if re.match(r"^[A-Za-z]:", source_path) is None and parsed.netloc:
                source_path = f"//{parsed.netloc}/{source_path}"
    if source_path is None:
        source_path = str(distribution.locate_file(""))
    return DistributionMetadata(
        name=name,
        state="available",
        version=distribution.version,
        editable=editable,
        source=normalize_import_origin(source_path, repo_root=repo_root),
    )


def collect_runtime_metadata(
    repo_root: Path,
    *,
    module_names: tuple[str, ...] = DEFAULT_MODULES,
) -> RuntimeMetadata:
    """Collect normalized local provenance without reading settings or secrets."""
    commit = _git_output(repo_root, "rev-parse", "HEAD")
    dirty_output = _git_output(
        repo_root, "status", "--porcelain", "--untracked-files=no"
    )
    complete_status = _git_output(
        repo_root, "status", "--porcelain", "--untracked-files=normal"
    )
    repository = RepositoryMetadata(
        commit=commit,
        dirty=bool(dirty_output) if dirty_output is not None else None,
        untracked=(
            any(line.startswith("??") for line in complete_status.splitlines())
            if complete_status is not None
            else None
        ),
        state="available" if commit else "unavailable",
    )
    submodules = []
    submodule_output = _git_output(repo_root, "submodule", "status", "--cached")
    for line in (submodule_output or "").splitlines():
        fields = line.lstrip(" +-U").split()
        if len(fields) >= 2:
            submodules.append(SubmoduleMetadata(path=fields[1], commit=fields[0]))
    imports = []
    for module in module_names:
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, AttributeError, ValueError):
            spec = None
        imports.append(
            ImportMetadata(
                module=module,
                state="available" if spec else "missing",
                origin=(
                    normalize_import_origin(
                        getattr(spec, "origin", None), repo_root=repo_root
                    )
                    if spec
                    else None
                ),
            )
        )
    return RuntimeMetadata(
        python_implementation=platform.python_implementation(),
        python_version=platform.python_version(),
        repository=repository,
        submodules=tuple(sorted(submodules, key=lambda item: item.path)),
        distributions=tuple(
            _distribution_metadata(name, repo_root=repo_root)
            for name in _DEFAULT_DISTRIBUTIONS
        ),
        imports=tuple(imports),
        services=(
            ServiceMetadata(name="platform-mcp", state="not_probed_metadata_only"),
            ServiceMetadata(name="workspace-mcp", state="not_probed_metadata_only"),
        ),
    )


__all__ = [
    "DEFAULT_MODULES",
    "DistributionMetadata",
    "EnvironmentFlag",
    "ImportMetadata",
    "RepositoryMetadata",
    "RuntimeMetadata",
    "ServiceMetadata",
    "SubmoduleMetadata",
    "collect_runtime_metadata",
    "normalize_import_origin",
]
