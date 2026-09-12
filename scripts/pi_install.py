#!/usr/bin/env python3
"""Install Portfolio Intelligence packages without losing editability."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTIONS = ("openbb-portfolio-intel", "openbb-techtrade")


def is_editable(distribution_name: str) -> bool:
    """Return whether an installed distribution has PEP 610 editable metadata."""
    try:
        direct_url = importlib.metadata.distribution(distribution_name).read_text(
            "direct_url.json"
        )
    except importlib.metadata.PackageNotFoundError:
        return False
    if direct_url is None:
        return False
    try:
        metadata = json.loads(direct_url)
    except (json.JSONDecodeError, TypeError):
        return False
    return metadata.get("dir_info", {}).get("editable") is True


def require_editable(names: tuple[str, ...] = DISTRIBUTIONS) -> None:
    """Raise unless every named distribution is installed editable."""
    not_editable = [name for name in names if not is_editable(name)]
    if not_editable:
        packages = ", ".join(not_editable)
        raise RuntimeError(f"{packages} not installed as editable")


def install(repo_root: Path = REPO_ROOT, *, dry_run: bool = False) -> None:
    """Install portfolio-intel, restore techtrade editable, then verify both."""
    extensions = repo_root / "openbb_platform" / "extensions"
    packages = (extensions / "portfolio_intel", extensions / "techtrade")
    commands = [
        [sys.executable, "-m", "pip", "install", "-e", str(package)]
        for package in packages
    ]

    for command in commands:
        print(f"$ {subprocess.list2cmdline(command)}")  # noqa: T201
        if not dry_run:
            subprocess.run(command, check=True)  # noqa: S603

    if dry_run:
        print("Dry run complete; no packages were installed.")  # noqa: T201
        return

    require_editable()
    print(  # noqa: T201
        "Editable install verified: openbb-portfolio-intel, openbb-techtrade"
    )


def main() -> int:
    """Run the guarded installer from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print pip commands without running them",
    )
    args = parser.parse_args()
    install(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
