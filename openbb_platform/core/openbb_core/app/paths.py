"""Path-sandboxing helpers for OpenBB Core.

This module exposes ``safe_join`` — a hardened alternative to ``os.path.join``
or ``pathlib.Path.__truediv__`` for the case where the caller has an approved
root directory and a user-supplied path fragment that must NOT escape it.

The Round 1 QC sweep of this fork surfaced 3+ sites where user-supplied
filenames or subpaths were concatenated onto an approved root without any
containment check, producing potential file-write path-traversal vulnerabilities
(e.g. ``export_dir + user_name`` where ``user_name == "../../etc/passwd"``).

Every site that concatenates a user-controlled fragment onto an approved root
SHOULD route through ``safe_join`` instead. The helper:

* Rejects ``..`` fragments that escape the root
* Rejects absolute-path children that would override the root
* Rejects Windows drive-relative children (``C:foo``) that would silently
  redirect to another drive
* Rejects symlinks-inside-root that point outside the root (via ``resolve``)
* Rejects null bytes, empty strings, and ``.``-only children outright
* Requires the root to exist AND be a directory (distinguishes
  configuration bugs from attack attempts via distinct error types)

Callers who need a distinct exception type for "attack attempt" vs
"benign parse error" should catch ``PathTraversalError`` specifically —
it subclasses ``ValueError`` so existing broad ``except ValueError:`` clauses
around path building continue to catch it.
"""

from __future__ import annotations

from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a child path would escape the approved root directory.

    Subclasses ``ValueError`` so existing code that catches ``ValueError``
    around path building continues to work without change. Callers that
    want to log attack attempts distinctly should catch this class first.
    """


def safe_join(root: str | Path, child: str | Path) -> Path:
    """Safely join ``child`` onto ``root``, refusing to escape the sandbox.

    Parameters
    ----------
    root : str | Path
        The approved parent directory. Must exist on disk (raises
        ``FileNotFoundError`` otherwise). Symlinks in the root itself
        are resolved to their target before the containment check.
    child : str | Path
        A relative path fragment supplied by an untrusted caller. May be
        a plain filename, a nested subpath, or a ``Path`` object.

    Returns
    -------
    Path
        The resolved absolute path ``(root / child).resolve()``, guaranteed
        to be inside ``root`` after symlink resolution.

    Raises
    ------
    ValueError
        If ``child`` is empty, ``.``, contains a null byte, or is
        ``Path('')`` (which stringifies to ``'.'``).
        ``PathTraversalError`` (a subclass) is also raised when the
        child would escape the root, so ``except ValueError:`` will catch
        both cases.
    FileNotFoundError
        If ``root`` does not exist on disk. Distinct from
        ``PathTraversalError`` so callers can tell configuration bugs
        (misconfigured export dir) from attack attempts.
    NotADirectoryError
        If ``root`` exists but is a regular file (or any non-directory
        entry). Prevents silently 'succeeding' on a misconfigured root
        that happens to accept path composition.
    PathTraversalError
        If the resolved child path is not inside ``root`` — covers
        ``..`` traversal, absolute-path overrides, Windows drive-relative
        children (``C:foo``), and symlink escapes.

    Examples
    --------
    Happy path — nested filename inside root::

        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     out = safe_join(d, "sub/report.html")
        ...     out.parent == Path(d).resolve() / "sub"
        True

    Rejects parent-directory traversal::

        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     try:
        ...         safe_join(d, "../etc/passwd")
        ...     except PathTraversalError:
        ...         print("blocked")
        blocked

    Notes
    -----
    Uses ``Path.resolve(strict=False)`` on the joined path so that
    non-existent leaf files (typical for "write output here" cases) do
    not raise, but symlinks that DO exist in intermediate directories
    are followed and validated. The containment check compares the
    resolved parents, not path strings, to avoid false positives from
    case-only or trailing-slash differences.

    The empty-string and ``.``-only guards are tighter than the pathlib
    default: ``str(Path(''))`` returns ``'.'`` (not ``''``), and
    ``root / Path('')`` resolves to root itself. Silently returning root
    as if it were an in-root filename is almost never what a caller
    wants, so both patterns are rejected as ambiguous.
    """
    # Coerce to string ONCE for validation checks (Path('') stringifies to '.')
    # then use Path for path-shape checks.
    child_str = str(child)

    # Empty string ("") and dot-only (".") both reduce to "no filename".
    # str(Path("")) == "." so the two collapse into the same guard.
    if child_str in ("", "."):
        raise ValueError("safe_join: child path is empty or refers to the root itself")
    if "\x00" in child_str:
        raise ValueError("safe_join: null byte in child path is not allowed")

    root_path = Path(root)
    if not root_path.exists():
        raise FileNotFoundError(f"safe_join: root does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"safe_join: root is not a directory: {root_path}")

    # Resolve the root to its canonical form so the containment check is
    # symlink-aware. strict=True is safe here — we just verified existence.
    root_resolved = root_path.resolve(strict=True)

    # Reject absolute child paths outright. Under naive Path/os.path.join
    # semantics an absolute child overrides the root entirely, which is
    # never what the caller wants when calling safe_join.
    child_path = Path(child)
    if child_path.is_absolute():
        raise PathTraversalError(
            f"safe_join: absolute child path escapes root: {child!r}"
        )

    # Reject Windows drive-relative paths ("C:foo") that have a drive
    # component but are NOT absolute. Joining them REPLACES the root, so
    # the containment check would still catch the escape if the drives
    # differ — but if root and child happen to share a drive, the escape
    # is silent. Belt-and-braces: reject any child with a drive component.
    if child_path.drive:
        raise PathTraversalError(
            f"safe_join: child path has a drive component "
            f"(drive-relative or absolute): {child!r}"
        )

    # Compose then resolve — strict=False so non-existent leaf files
    # (typical for "write output here") don't raise.
    candidate = (root_resolved / child_path).resolve(strict=False)

    # Containment check: candidate must be root_resolved or a descendant.
    # Path.is_relative_to (3.9+) does the parent-walk correctly and treats
    # the root itself as "relative to itself" — which is what we want.
    if not candidate.is_relative_to(root_resolved):
        raise PathTraversalError(
            f"safe_join: child path escapes root: {child!r} "
            f"(resolved to {candidate}, outside {root_resolved})"
        )

    return candidate
