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


def _try_make_symlink(link: Path, target: Path) -> bool:
    """Attempt to create a symlink; return True on success, False if OS refuses.

    Windows only allows unprivileged symlink creation under Developer Mode
    (and some CI configurations). On POSIX this virtually always succeeds.
    Using a capability probe instead of ``sys.platform == 'win32'`` skip
    means the symlink-escape guard is verified wherever symlinks work,
    not blindly bypassed on every Windows CI run.
    """
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return True


def test_safe_join_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink INSIDE root that points OUT of root is rejected on resolve().

    Uses a capability probe (not a platform skip) so this security-critical
    behavior is verified wherever the OS allows symlink creation — including
    Windows Developer Mode, which is where the drive-relative guard also
    matters. Regression test for pr-test-analyzer high-severity finding.
    """
    outside = tmp_path.parent / "outside_root"
    outside.mkdir(exist_ok=True)
    try:
        link = tmp_path / "escape_link"
        if not _try_make_symlink(link, outside):
            pytest.skip("OS does not permit symlink creation in this environment")
        with pytest.raises(PathTraversalError):
            safe_join(tmp_path, "escape_link/passwd")
    finally:
        if outside.exists():
            outside.rmdir()


def test_safe_join_accepts_symlink_inside_root(tmp_path: Path) -> None:
    """A symlink INSIDE root pointing to another location INSIDE root is accepted.

    Regression test for pr-test-analyzer finding — every prior symlink
    test asserted REJECTION, so an over-broad implementation that
    rejects any symlink component would have silently passed.
    """
    target_dir = tmp_path / "target_dir"
    target_dir.mkdir()
    link = tmp_path / "link_to_target"
    if not _try_make_symlink(link, target_dir):
        pytest.skip("OS does not permit symlink creation in this environment")
    # A file under the symlink must resolve to a legitimate in-root path.
    result = safe_join(tmp_path, "link_to_target/report.html")
    assert result == (target_dir / "report.html").resolve()


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


# ---------------------------------------------------------------------------
# QC self-review findings (added after Phase-6 QC pass on the branch)
# ---------------------------------------------------------------------------


def test_safe_join_rejects_empty_path_object(tmp_path: Path) -> None:
    """``Path('')`` collapses to '.' via str() — must be caught by the empty guard.

    Regression test for QC finding #4 — the old code checked ``if not str(child)``
    which is False for ``Path('')`` since ``str(Path('')) == '.'``. That silently
    returned the root directory itself, letting a caller accidentally treat the
    root as an output filename.
    """
    with pytest.raises(ValueError, match="empty"):
        safe_join(tmp_path, Path(""))


def test_safe_join_rejects_dot_only_child(tmp_path: Path) -> None:
    """A literal ``.`` child means 'the root itself' — reject as ambiguous.

    Same class of bug as Path('') — resolving to the root directory is almost
    never what a caller of safe_join wants (they're building an artefact path,
    not asking 'is this the root?').
    """
    with pytest.raises(ValueError, match="empty|dot"):
        safe_join(tmp_path, ".")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-letter semantics")
def test_safe_join_rejects_windows_drive_relative_child(tmp_path: Path) -> None:
    """``C:foo`` is drive-relative on Windows — is_absolute() is False but joining escapes.

    Regression test for QC finding #1 — the highest-severity finding. On Windows,
    ``PureWindowsPath('C:foo')`` has ``is_absolute() == False`` (it's relative to
    the CWD of drive C:), so the old absolute-path guard let it through. Path-
    concatenation then REPLACES the root entirely (``root / 'C:foo' → 'C:foo'``),
    landing anywhere on drive C: that the CWD points to.
    """
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, "C:foo")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-letter semantics")
def test_safe_join_rejects_windows_drive_relative_path_object(tmp_path: Path) -> None:
    """Same rejection when the caller passes a Path object."""
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, Path("C:foo"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UNC semantics")
def test_safe_join_rejects_windows_unc_child(tmp_path: Path) -> None:
    r"""UNC paths ``\\server\share`` are absolute on Windows — must be rejected."""
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, r"\\server\share\file.txt")


def test_safe_join_root_with_trailing_slash(tmp_path: Path) -> None:
    """Trailing slash on root string is normalised — child still lands inside."""
    root_with_slash = str(tmp_path) + os.sep
    result = safe_join(root_with_slash, "report.html")
    assert result == (tmp_path / "report.html").resolve()


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows extended-length path semantics"
)
def test_safe_join_rejects_windows_extended_length_path(tmp_path: Path) -> None:
    r"""Extended-length paths ``\\?\C:\...`` are absolute on Windows — must reject.

    Regression test for pr-test-analyzer finding — the ``\\?\`` prefix
    bypasses most path normalization and is semantically absolute. Both
    ``is_absolute()`` and the drive-component guard should fire; this
    test locks that in.
    """
    with pytest.raises(PathTraversalError):
        safe_join(tmp_path, r"\\?\C:\Windows\notepad.exe")


def test_safe_join_rejects_root_that_is_a_file(tmp_path: Path) -> None:
    """Root must be a directory — a file used as root raises NotADirectoryError.

    Regression test for pr-test-analyzer finding — without this guard,
    ``exists()`` succeeded on a file root, ``resolve(strict=True)`` returned
    the file path, and ``(file / 'child')`` produced a plausible-looking
    descendant that ``is_relative_to`` accepted. Silently 'succeeded' on
    a misconfigured root.
    """
    file_as_root = tmp_path / "not_a_directory.txt"
    file_as_root.write_text("hello")
    with pytest.raises(NotADirectoryError):
        safe_join(file_as_root, "child.txt")
