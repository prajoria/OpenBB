"""Verify one MCP runtime profile and write replayable local evidence."""

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from openbb_mcp_server.service.runtime_profiles import (
    InstallationKind,
    ProfileName,
    resolve_runtime_profile,
    write_runtime_resolution_artifact,
)


def main() -> int:
    """Resolve a selected checkout and return nonzero when it is not ready."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("platform-standard", "portfolio-read", "portfolio-ops"),
        required=True,
    )
    parser.add_argument(
        "--installation",
        choices=("isolated_uv", "portfolio_venv"),
        required=True,
    )
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()

    resolution = resolve_runtime_profile(
        cast(ProfileName, args.profile),
        active_installation=cast(InstallationKind, args.installation),
        repository_root=args.repository_root,
    )
    write_runtime_resolution_artifact(resolution, args.artifact)
    sys.stdout.write(
        json.dumps(
            {
                "conflicts": resolution.conflicts,
                "profile": resolution.name,
                "ready": resolution.ready,
            },
            sort_keys=True,
        )
        + "\n"
    )
    return 0 if resolution.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
