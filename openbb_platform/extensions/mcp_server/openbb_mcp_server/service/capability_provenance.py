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
LineageState = Literal[
    "available",
    "comparison_missing",
    "comparison_ref_missing",
    "history_incomplete",
    "unrelated_history",
]
LineageRelation = Literal[
    "equal",
    "ahead",
    "behind",
    "diverged",
    "unknown",
]

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


class LineageMetadata(BaseModel):
    """Reproducible HEAD-to-explicit-base comparison evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: LineageState
    head: str | None = None
    comparison_sha: str | None = None
    comparison_source: Literal["explicit", "github_base_sha", "missing"]
    base_ref: str | None = None
    base_is_portfolio: bool | None = None
    merge_base: str | None = None
    ahead: int | None = None
    behind: int | None = None
    relation: LineageRelation = "unknown"
    shallow: bool | None = None
    warnings: tuple[str, ...] = ()


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
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
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


def collect_lineage_metadata(
    repo_root: Path,
    *,
    comparison_sha: str | None = None,
    base_ref: str | None = None,
    environment: dict[str, str] | None = None,
) -> LineageMetadata:
    """Compare HEAD with an explicit or GitHub-provided base without fetching."""
    env = environment or {}
    explicit = (comparison_sha or "").strip() or None
    github_sha = (env.get("GITHUB_BASE_SHA") or "").strip() or None
    github_ref = (env.get("GITHUB_BASE_REF") or "").strip() or None
    event_path = (env.get("GITHUB_EVENT_PATH") or "").strip()
    if not github_sha and event_path:
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            event = {}
        pull_request = event.get("pull_request", {}) if isinstance(event, dict) else {}
        base = pull_request.get("base", {}) if isinstance(pull_request, dict) else {}
        if isinstance(base, dict):
            github_sha = str(base.get("sha") or "").strip() or None
            github_ref = github_ref or str(base.get("ref") or "").strip() or None
    selected = explicit or github_sha
    source: Literal["explicit", "github_base_sha", "missing"] = (
        "explicit" if explicit else "github_base_sha" if github_sha else "missing"
    )
    selected_base_ref = (base_ref or github_ref or "").strip() or None
    head = _git_output(repo_root, "rev-parse", "HEAD")
    shallow_text = _git_output(repo_root, "rev-parse", "--is-shallow-repository")
    shallow = shallow_text.lower() == "true" if shallow_text is not None else None
    warnings = []
    normalized_base_ref = selected_base_ref
    for prefix in ("refs/heads/", "refs/remotes/origin/", "origin/"):
        if normalized_base_ref and normalized_base_ref.startswith(prefix):
            normalized_base_ref = normalized_base_ref.removeprefix(prefix)
            break
    base_is_portfolio = (
        normalized_base_ref == "portfolio" if normalized_base_ref else None
    )
    if selected_base_ref and not base_is_portfolio:
        warnings.append(f"non_portfolio_base:{selected_base_ref}")
    if selected is None:
        return LineageMetadata(
            state="comparison_missing",
            head=head,
            comparison_source=source,
            base_ref=selected_base_ref,
            base_is_portfolio=base_is_portfolio,
            shallow=shallow,
            warnings=tuple(warnings),
        )
    if _git_output(repo_root, "cat-file", "-e", f"{selected}^{{commit}}") is None:
        warnings.append("history_incomplete" if shallow else "comparison_ref_missing")
        return LineageMetadata(
            state=("history_incomplete" if shallow else "comparison_ref_missing"),
            head=head,
            comparison_sha=selected,
            comparison_source=source,
            base_ref=selected_base_ref,
            base_is_portfolio=base_is_portfolio,
            shallow=shallow,
            warnings=tuple(warnings),
        )
    merge_base = _git_output(repo_root, "merge-base", selected, "HEAD")
    counts = _git_output(
        repo_root, "rev-list", "--left-right", "--count", f"{selected}...HEAD"
    )
    if merge_base is None or counts is None:
        state: LineageState = "history_incomplete" if shallow else "unrelated_history"
        warnings.append(state)
        return LineageMetadata(
            state=state,
            head=head,
            comparison_sha=selected,
            comparison_source=source,
            base_ref=selected_base_ref,
            base_is_portfolio=base_is_portfolio,
            shallow=shallow,
            warnings=tuple(warnings),
        )
    behind, ahead = (int(value) for value in counts.split())
    relation: LineageRelation = (
        "equal"
        if ahead == 0 and behind == 0
        else (
            "ahead"
            if ahead and not behind
            else "behind" if behind and not ahead else "diverged"
        )
    )
    return LineageMetadata(
        state="available",
        head=head,
        comparison_sha=selected,
        comparison_source=source,
        base_ref=selected_base_ref,
        base_is_portfolio=base_is_portfolio,
        merge_base=merge_base,
        ahead=ahead,
        behind=behind,
        relation=relation,
        shallow=shallow,
        warnings=tuple(warnings),
    )


__all__ = [
    "DEFAULT_MODULES",
    "DistributionMetadata",
    "EnvironmentFlag",
    "ImportMetadata",
    "LineageMetadata",
    "RepositoryMetadata",
    "RuntimeMetadata",
    "ServiceMetadata",
    "SubmoduleMetadata",
    "collect_runtime_metadata",
    "collect_lineage_metadata",
    "normalize_import_origin",
]
