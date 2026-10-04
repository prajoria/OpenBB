#!/usr/bin/env python3
"""Export deterministic metadata-only MCP capability inventories."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap_source_paths() -> None:
    """Prefer this checkout's source packages over another editable worktree."""
    paths = [
        REPO_ROOT / "openbb_platform" / "extensions" / "mcp_server",
        REPO_ROOT / "openbb_platform" / "core",
    ]
    paths.extend(
        path
        for parent in (
            REPO_ROOT / "openbb_platform" / "extensions",
            REPO_ROOT / "openbb_platform" / "providers",
            REPO_ROOT / "openbb_platform" / "obbject_extensions",
            REPO_ROOT / "openbb_platform" / "tools",
        )
        if parent.exists()
        for path in parent.iterdir()
        if path.is_dir()
    )
    for path in reversed(paths):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


_bootstrap_source_paths()

# Source bootstrap must run before importing the checkout-local package.
# pylint: disable=wrong-import-position
from openbb_mcp_server.service.capability_inventory import (  # noqa: E402
    build_inventory,
    validate_inventory_evidence,
    write_inventory,
)
from openbb_mcp_server.service.capability_provenance import (  # noqa: E402
    collect_lineage_metadata,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse explicit metadata-only inventory arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        required=True,
        choices=("platform-standard", "portfolio-read", "portfolio-ops"),
        help="committed MCP profile alias to inventory",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory for stable JSON/CSV artifacts",
    )
    parser.add_argument(
        "--metadata-only",
        required=True,
        action="store_true",
        help="confirm that no providers, services, or transports may be probed",
    )
    parser.add_argument(
        "--comparison-sha",
        help="explicit commit SHA to compare with HEAD (preferred outside CI)",
    )
    parser.add_argument(
        "--base-ref",
        help="descriptive base branch name; does not resolve or fetch the ref",
    )
    parser.add_argument(
        "--require-lineage",
        action="store_true",
        help="fail unless lineage comparison state is available",
    )
    return parser.parse_args(argv)


def validate_output_dir(output_dir: Path, repo_root: Path = REPO_ROOT) -> None:
    """Require in-repository output directories to be ignored by Git."""
    resolved_output = output_dir.resolve()
    resolved_root = repo_root.resolve()
    try:
        relative = resolved_output.relative_to(resolved_root)
    except ValueError:
        return
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("git is required to validate an in-repository output path")
    result = subprocess.run(  # noqa: S603
        [
            git_executable,
            "-C",
            str(resolved_root),
            "check-ignore",
            "--no-index",
            "-q",
            "--",
            relative.as_posix(),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            "output directory inside the repository must be ignored by Git"
        )


def run(argv: Sequence[str] | None = None) -> int:
    """Build and write one metadata-only inventory."""
    args = parse_args(argv)
    validate_output_dir(args.output_dir)
    document = build_inventory(
        args.profile,
        repo_root=REPO_ROOT,
    )
    lineage = collect_lineage_metadata(
        REPO_ROOT,
        comparison_sha=args.comparison_sha,
        base_ref=args.base_ref,
        environment={
            key: os.environ[key]
            for key in ("GITHUB_BASE_SHA", "GITHUB_BASE_REF", "GITHUB_EVENT_PATH")
            if key in os.environ
        },
    )
    if args.require_lineage and lineage.state != "available":
        raise RuntimeError(f"required lineage evidence is unavailable: {lineage.state}")
    document = document.model_copy(update={"lineage": lineage})
    validate_inventory_evidence(document)
    paths = write_inventory(document, args.output_dir)
    summary = {
        "metadata_only": True,
        "profile": document.profile.selected_name,
        "capabilities": len(document.capabilities.records),
        "denominators": document.denominators.model_dump(mode="json"),
        "lineage": lineage.model_dump(mode="json"),
        "provider_models": len(document.provider_models),
        "collisions": len(document.collisions),
        "unavailable_components": list(document.unavailable_components),
        "scope_limitations": list(document.scope_limitations),
        "outputs": [path.name for path in paths],
    }
    print(json.dumps(summary, sort_keys=True))  # noqa: T201
    return 0


def main() -> int:
    """Configure UTF-8 output and run the inventory CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
