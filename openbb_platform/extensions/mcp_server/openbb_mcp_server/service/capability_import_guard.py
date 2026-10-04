"""Isolation boundary for metadata-only OpenBB registration imports."""

from __future__ import annotations

import importlib.util
import os
import re
import socket
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from importlib_metadata import EntryPoints

from openbb_mcp_server.service.capability_provenance import (
    normalize_import_origin,
)

_IMPORT_GUARD_LOCK = threading.RLock()
_ENTRY_POINT_SECTION_RE = re.compile(
    r'^\[(?:tool\.poetry\.plugins|project\.entry-points)\."(?P<group>openbb_[^"]+)"\]'
    r"(?P<body>.*?)(?=^\[|\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
_ENTRY_POINT_VALUE_RE = re.compile(
    r'^\s*"?(?P<name>[A-Za-z0-9_.-]+)"?\s*=\s*"(?P<value>[^"]+)"',
    flags=re.MULTILINE,
)


def _checkout_declared_entry_points(repo_root: Path, group: str) -> dict[str, str]:
    """Return entry points declared by checkout package manifests."""
    declared = {}
    for manifest in sorted((repo_root / "openbb_platform").rglob("pyproject.toml")):
        content = manifest.read_text(encoding="utf-8")
        for section in _ENTRY_POINT_SECTION_RE.finditer(content):
            if section.group("group") != group:
                continue
            for entry in _ENTRY_POINT_VALUE_RE.finditer(section.group("body")):
                declared[entry.group("name")] = entry.group("value")
    return declared


def _checkout_entry_points(
    repo_root: Path,
    excluded: list[str],
    *,
    group: str,
    entry_point_reader: Any,
) -> EntryPoints:
    """Return installed entry points whose import package resolves in this checkout."""
    declared = _checkout_declared_entry_points(repo_root, group)
    allowed = []
    installed = {
        entry_point.name: entry_point for entry_point in entry_point_reader(group=group)
    }
    for name in sorted(set(declared) - set(installed)):
        excluded.append(f"entry-point:{group}:{name}:missing_from_environment")
    for entry_point in installed.values():
        if entry_point.name not in declared:
            excluded.append(
                f"entry-point:{group}:{entry_point.name}:not_declared_by_checkout"
            )
            continue
        if entry_point.value != declared[entry_point.name]:
            excluded.append(f"entry-point:{group}:{entry_point.name}:target_mismatch")
            continue
        top_level_module = entry_point.value.split(":", maxsplit=1)[0].split(".")[0]
        try:
            spec = importlib.util.find_spec(top_level_module)
        except (ImportError, AttributeError, ValueError):
            spec = None
        origin = (
            normalize_import_origin(
                getattr(spec, "origin", None),
                repo_root=repo_root,
            )
            if spec
            else None
        )
        if origin and origin.startswith("repo://"):
            allowed.append(entry_point)
        else:
            excluded.append(f"entry-point:{group}:{entry_point.name}:outside_repo_root")
    return EntryPoints(allowed)


def _checkout_source_roots(repo_root: Path) -> list[str]:
    """Return package roots declared by this checkout."""
    roots = [repo_root / "openbb_platform" / "core"]
    for parent in (
        repo_root / "openbb_platform" / "extensions",
        repo_root / "openbb_platform" / "providers",
        repo_root / "openbb_platform" / "obbject_extensions",
        repo_root / "openbb_platform" / "tools",
    ):
        if parent.exists():
            roots.extend(
                path
                for path in parent.iterdir()
                if path.is_dir() and (path / "pyproject.toml").exists()
            )
    return [str(path) for path in roots]


@contextmanager
def metadata_import_guard(repo_root: Path, excluded: list[str]) -> Iterator[None]:
    """Isolate registration imports from credentials, network, and foreign entry points."""
    # Importing the loader module does not load extension targets.
    # pylint: disable=import-outside-toplevel
    from openbb_core.app import extension_loader

    instances = getattr(type(extension_loader.ExtensionLoader), "_instances", {})
    if extension_loader.ExtensionLoader in instances:
        excluded.append("guard:extension_loader:already_initialized")
        raise RuntimeError(
            "ExtensionLoader was initialized before the metadata import guard"
        )
    installed_entry_points = extension_loader.entry_points
    allowed_environment = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
    }

    def filtered_entry_points(*, group: str) -> EntryPoints:
        return _checkout_entry_points(
            repo_root,
            excluded,
            group=group,
            entry_point_reader=installed_entry_points,
        )

    def block_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network access is blocked during metadata collection")

    with _IMPORT_GUARD_LOCK, tempfile.TemporaryDirectory(
        prefix="openbb-mcp-audit-"
    ) as home:
        environment_overrides = {
            "HOME": home,
            "USERPROFILE": home,
            "OPENBB_DEV_MODE": "false",
            "OPENBB_JOBS_ENABLED": "false",
        }
        original_overrides = {key: os.environ.get(key) for key in environment_overrides}
        removed_environment = {
            key: value
            for key, value in os.environ.items()
            if key not in allowed_environment
            and not key.startswith("GIT_CONFIG_")
            and value
        }
        try:
            for key in removed_environment:
                del os.environ[key]
            os.environ.update(environment_overrides)
            with (
                patch.object(
                    sys,
                    "path",
                    [*_checkout_source_roots(repo_root), *sys.path],
                ),
                patch.object(
                    extension_loader,
                    "entry_points",
                    filtered_entry_points,
                ),
                patch.object(socket, "socket", block_socket),
                patch.object(socket, "create_connection", block_socket),
            ):
                yield
        finally:
            for key, value in original_overrides.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            os.environ.update(removed_environment)


__all__ = ["metadata_import_guard"]
