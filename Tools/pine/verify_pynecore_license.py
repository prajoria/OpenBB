#!/usr/bin/env python3
"""Verify the vendored PyneCore submodule's NOTICE / LICENSE match the pinned manifest.

This is the runtime side of the license-drift defense documented in
``docs/designs/openbb-pine/D0-pynecore-pin.md``. It is invoked from
``.github/workflows/pynecore-license-check.yml`` on every PR that touches the
submodule, and can also be run locally via ``python tools/pine/verify_pynecore_license.py``.

What it checks:

1. ``third_party/pynecore/.license_manifest.json`` exists and parses.
2. For every file listed in the manifest's ``files`` map:
   - the file exists on disk under ``third_party/pynecore/``,
   - its byte size matches ``byte_size``,
   - its SHA-256 matches ``sha256``.
3. The submodule's current ``HEAD`` matches ``pinned_commit``.

Exit code 0 on full match, exit code 1 on any defect. Prints a machine-readable
JSON summary in either case (final line of stdout is the JSON object).

The error message on mismatch is intentionally verbose and names every defect
on the first failure so a reviewer can see the full picture without rerunning.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUBMODULE_DIR = REPO_ROOT / "third_party" / "pynecore"
# Manifest lives as a sibling of the submodule directory (not inside it):
# the parent repo cannot track files inside a submodule, so a manifest at
# ``third_party/pynecore/.license_manifest.json`` would be unversioned and
# wiped on every ``git submodule update``. Keeping it next to the submodule
# means the parent repo owns it and CI can compare against a stable baseline.
MANIFEST_PATH = REPO_ROOT / "third_party" / "pynecore.license_manifest.json"

# This is the documented reviewer remediation message — keep in sync with the
# wording in docs/designs/openbb-pine/D0-pynecore-pin.md so a CI failure points
# the reviewer to the exact procedure.
DRIFT_ERROR_MESSAGE = (
    "PyneCore NOTICE or LICENSE has changed from the pinned manifest. "
    "Review the upstream change for new compliance obligations or relicensing, "
    "then update third_party/pynecore.license_manifest.json via "
    "tools/pine/refresh_pynecore_manifest.py and document the change in "
    "docs/designs/openbb-pine/D0-pynecore-pin.md."
)


def sha256_of(path: Path) -> str:
    """Return hex sha256 of file contents, streaming to bound memory.

    Line endings are canonicalized to LF before hashing so a working-tree
    checkout on Windows (which converts LF → CRLF at checkout time via
    ``core.autocrlf``) produces the same hash as CI on Linux. Without
    this, the manifest — necessarily captured on ONE platform — would
    always mismatch on the other, and the check would either silently
    pass on one platform or always fail on the other. The canonicalization
    happens in-stream so we still bound memory on the LICENSE-sized files.
    See docs/designs/openbb-pine/D0-pynecore-pin.md for the rationale.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        # Read one chunk larger than the CRLF window (2 bytes) so a
        # split-across-chunk-boundary ``\r\n`` doesn't slip through.
        # 65536 is comfortably larger; we carry over a trailing ``\r`` to
        # the next chunk just in case one lands at the very end.
        carry = b""
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            buf = carry + chunk
            # If the buffer ends with ``\r``, hold it for the next chunk
            # in case the next chunk starts with ``\n`` (which would form
            # a CRLF that should collapse to LF).
            if buf.endswith(b"\r"):
                carry = b"\r"
                buf = buf[:-1]
            else:
                carry = b""
            h.update(buf.replace(b"\r\n", b"\n"))
        if carry:
            # Trailing lone ``\r`` (unusual — typically classic Mac line
            # ending); hash as-is, no normalization applies.
            h.update(carry)
    return h.hexdigest()


def byte_size_of(path: Path) -> int:
    """Return LF-normalized byte size of the file (mirror of :func:`sha256_of`).

    See :func:`sha256_of` for the CRLF-vs-LF rationale.
    """
    size = 0
    with path.open("rb") as fh:
        carry = b""
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            buf = carry + chunk
            if buf.endswith(b"\r"):
                carry = b"\r"
                buf = buf[:-1]
            else:
                carry = b""
            size += len(buf.replace(b"\r\n", b"\n"))
        if carry:
            size += 1
    return size


def current_submodule_commit() -> str | None:
    """Return ``git rev-parse HEAD`` for the submodule, or None if unavailable."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(SUBMODULE_DIR), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip() or None


def emit(summary: dict[str, Any]) -> None:
    """Print a machine-readable JSON summary as the last line of stdout."""
    print(json.dumps(summary, indent=2, sort_keys=True))


def fail(defects: list[str], extra: dict[str, Any] | None = None) -> int:
    payload: dict[str, Any] = {
        "status": "fail",
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
        "defects": defects,
        "error_message": DRIFT_ERROR_MESSAGE,
    }
    if extra:
        payload.update(extra)
    print("ERROR: " + DRIFT_ERROR_MESSAGE, file=sys.stderr)
    for defect in defects:
        print(f"  - {defect}", file=sys.stderr)
    emit(payload)
    return 1


def main() -> int:
    if not MANIFEST_PATH.exists():
        return fail([f"manifest not found at {MANIFEST_PATH.relative_to(REPO_ROOT)}"])

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail([f"manifest is not valid JSON: {exc}"])

    schema_version = manifest.get("schema_version")
    if schema_version != 1:
        return fail([f"unsupported manifest schema_version: {schema_version!r} (expected 1)"])

    files = manifest.get("files", {})
    if not isinstance(files, dict) or not files:
        return fail(["manifest 'files' is missing or empty"])

    pinned_commit = manifest.get("pinned_commit")
    if not isinstance(pinned_commit, str) or not pinned_commit:
        return fail(["manifest 'pinned_commit' is missing"])

    defects: list[str] = []
    file_results: dict[str, dict[str, Any]] = {}

    for filename, expected in sorted(files.items()):
        target = SUBMODULE_DIR / filename
        result: dict[str, Any] = {"path": str(target.relative_to(REPO_ROOT))}
        if not target.exists():
            defects.append(f"{filename}: missing on disk at {target.relative_to(REPO_ROOT)}")
            result["status"] = "missing"
            file_results[filename] = result
            continue

        actual_size = byte_size_of(target)
        actual_sha = sha256_of(target)
        expected_size = expected.get("byte_size")
        expected_sha = expected.get("sha256")
        result.update(
            {
                "actual_sha256": actual_sha,
                "expected_sha256": expected_sha,
                "actual_byte_size": actual_size,
                "expected_byte_size": expected_size,
            }
        )

        size_ok = actual_size == expected_size
        sha_ok = actual_sha == expected_sha
        if size_ok and sha_ok:
            result["status"] = "ok"
        else:
            result["status"] = "mismatch"
            if not size_ok:
                defects.append(
                    f"{filename}: byte_size mismatch (expected {expected_size}, got {actual_size})"
                )
            if not sha_ok:
                defects.append(
                    f"{filename}: sha256 mismatch "
                    f"(expected {expected_sha}, got {actual_sha})"
                )
        file_results[filename] = result

    actual_commit = current_submodule_commit()
    commit_status = "ok"
    if actual_commit is None:
        defects.append(
            "submodule HEAD could not be read; "
            "ensure the submodule is checked out (e.g. `git submodule update --init`)"
        )
        commit_status = "unknown"
    elif actual_commit != pinned_commit:
        defects.append(
            f"submodule HEAD {actual_commit} does not match pinned_commit {pinned_commit}"
        )
        commit_status = "mismatch"

    summary: dict[str, Any] = {
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
        "pinned_commit": pinned_commit,
        "actual_commit": actual_commit,
        "commit_status": commit_status,
        "files": file_results,
    }

    if defects:
        return fail(defects, extra=summary)

    summary["status"] = "ok"
    emit(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
