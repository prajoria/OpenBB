#!/usr/bin/env python3
"""Refresh ``third_party/pynecore.license_manifest.json`` after a PyneCore bump.

This script is the *intentionally inconvenient* counterpart to
``verify_pynecore_license.py``. It refuses to run unless the operator passes
``--confirm-license-reviewed``, so that updating the SHAs is an explicit
attestation: *"I have read the upstream NOTICE/LICENSE diff and any new
compliance obligations are either absent or recorded in
``docs/designs/openbb-pine/D0-pynecore-pin.md`` and PRD §2.2/§2.6."*

Usage::

    python tools/pine/refresh_pynecore_manifest.py --confirm-license-reviewed

It prints a diff of the old vs new manifest so the reviewer can see exactly
what changed before committing.

See ``docs/designs/openbb-pine/D0-pynecore-pin.md`` for the full 4-step bump
procedure this tool participates in.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBMODULE_DIR = REPO_ROOT / "third_party" / "pynecore"
# Manifest lives as a sibling of the submodule directory (not inside it):
# the parent repo cannot track files inside a submodule. See the matching
# comment in verify_pynecore_license.py.
MANIFEST_PATH = REPO_ROOT / "third_party" / "pynecore.license_manifest.json"

# Files tracked for license drift. Add to this list if PyneCore upstream
# introduces a new file we must vet (e.g. a PATENTS or COPYRIGHT file).
TRACKED_FILES = ("NOTICE", "LICENSE")

ATTESTATION_FLAG = "--confirm-license-reviewed"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_pyproject_version() -> str | None:
    """Best-effort scrape of the submodule's pyproject ``version`` line."""
    pyproject = SUBMODULE_DIR / "pyproject.toml"
    if not pyproject.exists():
        return None
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("version") and "=" in stripped:
            # Strip the comment then split on '='.
            value = stripped.split("#", 1)[0].split("=", 1)[1].strip().strip('"').strip("'")
            return value or None
    return None


def current_submodule_commit() -> str:
    completed = subprocess.run(
        ["git", "-C", str(SUBMODULE_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    sha = completed.stdout.strip()
    if not sha:
        raise RuntimeError("git rev-parse HEAD returned empty output")
    return sha


def build_manifest() -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for name in TRACKED_FILES:
        path = SUBMODULE_DIR / name
        if not path.exists():
            raise SystemExit(
                f"ERROR: required file {path.relative_to(REPO_ROOT)} not found in submodule"
            )
        files[name] = {"sha256": sha256_of(path), "byte_size": path.stat().st_size}

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "pinned_commit": current_submodule_commit(),
        "pinned_version": read_pyproject_version() or "unknown",
        "files": files,
        "captured_at": _dt.date.today().isoformat(),
        "captured_by": "tools/pine/refresh_pynecore_manifest.py (--confirm-license-reviewed)",
        "rationale": (
            "PyneCore is Apache-2.0 with a §4(d) attribution requirement. Any upstream "
            "change to NOTICE or LICENSE must be reviewed (it may add new compliance "
            "obligations or relicense). This manifest is checked by "
            ".github/workflows/pynecore-license-check.yml on every PR that touches the "
            "submodule. Stored as a sibling of the submodule (not inside it) because "
            "the parent repo cannot track files inside a submodule — see "
            "docs/designs/openbb-pine/D0-pynecore-pin.md §1."
        ),
    }
    return manifest


def dump_manifest(manifest: dict[str, Any]) -> str:
    # Match the hand-authored manifest style (single-line per file entry) so the
    # diff stays small when only SHAs change.
    files_block_lines = []
    for name, info in manifest["files"].items():
        files_block_lines.append(
            f'    "{name}": {{"sha256": "{info["sha256"]}", "byte_size": {info["byte_size"]}}}'
        )
    files_block = "{\n" + ",\n".join(files_block_lines) + "\n  }"

    body = (
        "{\n"
        f'  "schema_version": {manifest["schema_version"]},\n'
        f'  "pinned_commit": "{manifest["pinned_commit"]}",\n'
        f'  "pinned_version": "{manifest["pinned_version"]}",\n'
        f'  "files": {files_block},\n'
        f'  "captured_at": "{manifest["captured_at"]}",\n'
        f'  "captured_by": "{manifest["captured_by"]}",\n'
        f'  "rationale": {json.dumps(manifest["rationale"])}\n'
        "}\n"
    )
    return body


def print_diff(old_text: str, new_text: str) -> None:
    diff = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile="old manifest",
            tofile="new manifest",
            n=3,
        )
    )
    if not diff:
        print("Manifest is already up to date — no changes.")
        return
    print("Manifest diff (old -> new):")
    sys.stdout.writelines(diff)
    if not diff[-1].endswith("\n"):
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the PyneCore license manifest. Requires "
            f"{ATTESTATION_FLAG} as an explicit reviewer attestation."
        )
    )
    parser.add_argument(
        ATTESTATION_FLAG,
        dest="confirmed",
        action="store_true",
        help=(
            "Required. By passing this flag you attest that you have reviewed "
            "the upstream NOTICE/LICENSE diff for new compliance obligations "
            "or relicensing, and documented any changes in "
            "docs/designs/openbb-pine/D0-pynecore-pin.md."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the new manifest and print the diff, but do not write it.",
    )
    args = parser.parse_args(argv)

    if not args.confirmed:
        print(
            f"ERROR: {ATTESTATION_FLAG} is required.\n\n"
            "This tool updates the license-drift manifest used by CI to gate\n"
            "PyneCore submodule bumps. Refresh is intentionally a two-key\n"
            "operation: the flag is an attestation that you have:\n"
            "  1. Inspected the upstream NOTICE/LICENSE diff\n"
            "       git -C third_party/pynecore diff <old-sha>..<new-sha> -- NOTICE LICENSE\n"
            "  2. Confirmed no new compliance obligations, OR documented them in\n"
            "       docs/designs/openbb-pine/D0-pynecore-pin.md\n"
            "       and PRD §2.2 / §2.6 as needed.\n\n"
            f"Re-run with {ATTESTATION_FLAG} once you have done both.\n",
            file=sys.stderr,
        )
        return 2

    new_manifest = build_manifest()
    new_text = dump_manifest(new_manifest)
    old_text = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else ""

    print_diff(old_text, new_text)

    if args.dry_run:
        print("\nDry run — not writing manifest.")
        return 0

    MANIFEST_PATH.write_text(new_text, encoding="utf-8")
    print(f"\nWrote {MANIFEST_PATH.relative_to(REPO_ROOT)}.")
    print(
        "Next: commit both the submodule bump AND this manifest in the same commit\n"
        "(see docs/designs/openbb-pine/D0-pynecore-pin.md step 4)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
