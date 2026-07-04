"""OpenBB Platform Core app paths tests.

Tests for ``safe_join`` — a path-sandboxing helper that ensures user-supplied
path fragments never escape a caller-approved root directory.

The helper defends against three classes of vulnerability observed in the
Round 1 QC sweep of this fork:

1. ``..`` traversal ("../etc/passwd")
2. Absolute-path override (user_input="/etc/passwd" absorbs the root)
3. Symlink-based traversal (target directory contains a symlink pointing out
   of the sandbox)

Every branch of the helper must be covered — this is security-critical code
and the Tier-0 remediation plan targets ≥ 90 % coverage on the new helpers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from openbb_core.app.paths import PathTraversalError, safe_join

# ---------------------------------------------------------------------------
# Happy-path cases
# ---------------------------------------------------------------------------


def test_safe_join_returns_child_when_inside_root(tmp_path: Path) -> None:
    """A plain relative filename inside root resolves to root / name."""
    result = safe_join(tmp_path, "report.html")
    assert result == (tmp_path / "report.html").resolve()


def test_safe_join_accepts_nested_relative_paths(tmp_path: Path) -> None:
    """Nested relative paths are permitted as long as they stay inside root."""
    (tmp_path / "sub").mkdir()
    result = safe_join(tmp_path, "sub/report.html")
    assert result == (tmp_path / "sub" / "report.html").resolve()


def test_safe_join_string_root_and_string_child(tmp_path: Path) -> None:
    """Both root and child can be plain strings (matches os.path.join API)."""
    result = safe_join(str(tmp_path), "report.html")
    assert result == (tmp_path / "report.html").resolve()


def test_safe_join_returns_path_object(tmp_path: Path) -> None:
    """Return type is always Path, regardless of input type."""
    result = safe_join(str(tmp_path), "report.html")
    assert isinstance(result, Path)


def test_safe_join_normalizes_redundant_separators(tmp_path: Path) -> None:
    """Redundant separators ('./', doubled slashes) collapse without escaping."""
    result = safe_join(tmp_path, "./sub/../report.html")
    # ./sub/../report.html normalises to root/report.html — still inside root.
    assert result == (tmp_path / "report.html").resolve()


# ---------------------------------------------------------------------------
# Traversal-rejection cases (security-critical)
# ---------------------------------------------------------------------------


def test_safe_join_rejects_parent_traversal(tmp_path: Path) -> None:
    """``..`` fragments that escape root are rejected."""
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "../etc/passwd")


def test_safe_join_rejects_deep_parent_traversal(tmp_path: Path) -> None:
    """Multiple ``..`` fragments are still rejected."""
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "../../../../etc/passwd")


def test_safe_join_rejects_absolute_path_child(tmp_path: Path) -> None:
    """An absolute-path child would override root under naive os.path.join."""
    absolute = "/etc/passwd" if os.name != "nt" else "C:/Windows/System32/hosts"
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, absolute)


def test_safe_join_rejects_absolute_path_child_via_pathobj(tmp_path: Path) -> None:
    """Same rejection when the caller passes a Path object, not a string."""
    absolute = (
        Path("/etc/passwd") if os.name != "nt" else Path("C:/Windows/System32/hosts")
    )
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, absolute)


def test_safe_join_rejects_mixed_traversal(tmp_path: Path) -> None:
    """A path that stays inside for the first segments but escapes at the end."""
    (tmp_path / "safe").mkdir()
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "safe/../../escape.txt")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink perms differ on Windows")
def test_safe_join_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink INSIDE root that points OUT of root is rejected on resolve()."""
    outside = tmp_path.parent / "outside_root"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "escape_link"
        link.symlink_to(outside)
        with pytest.raises(PathTraversalError):
            safe_join(tmp_path, "escape_link/passwd")
    finally:
        # tmp_path is auto-cleaned, but its sibling isn't — clean up manually.
        if outside.exists():
            outside.rmdir()


# ---------------------------------------------------------------------------
# Argument-validation cases
# ---------------------------------------------------------------------------


def test_safe_join_rejects_empty_child(tmp_path: Path) -> None:
    """An empty child string is meaningless — reject with ValueError."""
    with pytest.raises(ValueError, match="empty"):
        safe_join(tmp_path, "")


def test_safe_join_rejects_null_bytes_in_child(tmp_path: Path) -> None:
    """Null bytes in filenames are historically dangerous — reject outright."""
    with pytest.raises(ValueError, match="null"):
        safe_join(tmp_path, "report\x00.html")


def test_safe_join_root_must_exist(tmp_path: Path) -> None:
    """Root directory that does not exist raises FileNotFoundError.

    Distinct from PathTraversalError so callers can distinguish
    configuration bugs (missing root) from attack attempts (traversal).
    """
    missing_root = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        safe_join(missing_root, "report.html")


# ---------------------------------------------------------------------------
# Error-type invariants
# ---------------------------------------------------------------------------


def test_path_traversal_error_is_a_value_error() -> None:
    """PathTraversalError inherits from ValueError so existing except-clauses catch it.

    This is a soft compatibility promise — code that already does
    ``except ValueError:`` around path-building continues to work.
    """
    assert issubclass(PathTraversalError, ValueError)


def test_path_traversal_error_message_includes_offending_child(tmp_path: Path) -> None:
    """The exception message names the offending fragment for easy debugging."""
    try:
        safe_join(tmp_path, "../escape.txt")
    except PathTraversalError as exc:
        assert "../escape.txt" in str(exc) or "escape.txt" in str(exc)
    else:
        pytest.fail("safe_join did not raise on ../escape.txt")
