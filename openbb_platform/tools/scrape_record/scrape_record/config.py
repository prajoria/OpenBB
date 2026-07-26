"""Configuration + path validation for scrape-record.

**Contrast with ``portfolio_export.config``**:

- ``portfolio_export`` forces its download/profile paths to be OUTSIDE
  the repo (because brokerage exports contain private user data).
- ``scrape-record`` puts ``snapshots_dir`` INSIDE the repo (because
  we WANT public provider data checked into git for reproducible
  builds), but keeps ``profile_dir`` OUTSIDE (Yahoo login cookies are
  still per-user, not shareable).

Everything else (repo-root detection, env overrides, dotenv loading) is
kept parallel to ``portfolio_export`` so an operator who knows one
knows the other.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    _HAS_DOTENV = True
except ImportError:  # pragma: no cover - dotenv is a declared dep
    _HAS_DOTENV = False


DEFAULT_PROFILE_DIR = "~/.scrape_record/chrome_profile"
DEFAULT_DB_PATH = "~/.scrape_record/snapshots.db"


class ConfigError(RuntimeError):
    """Raised when configuration is invalid or violates safety rules."""


@dataclass(frozen=True)
class Config:
    """Resolved runtime paths for a scrape-record session."""

    repo_root: Path
    package_root: Path
    snapshots_dir: Path
    recordings_dir: Path
    profile_dir: Path
    db_path: Path
    headless: bool

    def summary(self) -> str:
        """Return a human-readable summary of all resolved paths."""
        return (
            f"repo_root       = {self.repo_root}\n"
            f"package_root    = {self.package_root}\n"
            f"snapshots_dir   = {self.snapshots_dir}\n"
            f"recordings_dir  = {self.recordings_dir}\n"
            f"profile_dir     = {self.profile_dir}\n"
            f"db_path         = {self.db_path}\n"
            f"headless        = {self.headless}"
        )


def _find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` looking for ``.git``. Raise if not found."""
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise ConfigError(
        f"Could not locate a git repo root walking up from {start}. "
        "scrape-record requires a git repo so it can enforce that "
        "profile paths are outside it while snapshots_dir sits inside."
    )


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _validate_profile_outside_repo(path: Path, repo_root: Path) -> None:
    """profile_dir MUST be outside the repo (contains cookies/session state)."""
    if _is_inside(path, repo_root):
        raise ConfigError(
            f"profile_dir ({path}) resolves inside the repo ({repo_root}). "
            "scrape-record refuses to write browser profile state inside a "
            "git tree. Set SCRAPE_RECORD_PROFILE_DIR to a path OUTSIDE the "
            f"repo (default: {DEFAULT_PROFILE_DIR})."
        )


def _validate_snapshots_inside_package(path: Path, package_root: Path) -> None:
    """snapshots_dir SHOULD be inside the package (checked-in canned data).

    NOTE post-#1425: `snapshots/` is being retired as a distribution
    channel — real snapshots live in the user-local SQLite DB. But the
    dir may still exist for (a) the migration window, (b) explicit
    synthetic fixtures. Whichever way, its layout constraint is unchanged.
    """
    if not _is_inside(path, package_root):
        raise ConfigError(
            f"snapshots_dir ({path}) resolves OUTSIDE the scrape_record "
            f"package ({package_root}). By design, scrape-record's legacy "
            "snapshots dir sits inside the package. "
            "If you really want external snapshots, subclass Config."
        )


def _validate_db_outside_repo(path: Path, repo_root: Path) -> None:
    """db_path MUST be outside the repo.

    Rationale (#1425): the DB holds Yahoo-shaped provider data. Even
    though it is per-user, putting it inside the repo makes it trivial
    to `git add` accidentally. The check is defense-in-depth on top of
    the ``.gitignore`` entry.
    """
    if _is_inside(path, repo_root):
        raise ConfigError(
            f"db_path ({path}) resolves inside the repo ({repo_root}). "
            "scrape-record refuses to write its snapshot DB inside a git "
            "tree — see GH #1425. Set SCRAPE_RECORD_DB_PATH to a path "
            f"OUTSIDE the repo (default: {DEFAULT_DB_PATH})."
        )


def _validate_snapshots_inside_package_LEGACY(path: Path, package_root: Path) -> None:
    """Retained no-op stub — the primary check is above."""
    return None


def load_config(
    *,
    package_root: Path | None = None,
    profile_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    headless: bool | None = None,
    dotenv_path: str | Path | None = None,
) -> Config:
    """Build a validated Config from env + explicit overrides.

    Precedence: explicit kwargs > env var > default.

    Env vars:
    - ``SCRAPE_RECORD_PROFILE_DIR``
    - ``SCRAPE_RECORD_DB_PATH``
    - ``SCRAPE_RECORD_HEADLESS`` (any of ``1/true/yes/on`` = True)
    """
    if _HAS_DOTENV:
        if dotenv_path:
            load_dotenv(dotenv_path=dotenv_path)
        else:
            load_dotenv()

    pkg_root = (package_root or Path(__file__).resolve().parent.parent).resolve()
    repo_root = _find_repo_root(pkg_root)

    snapshots_dir = (pkg_root / "snapshots").resolve()
    recordings_dir = (pkg_root / "recordings").resolve()

    prof_str = profile_dir or os.environ.get(
        "SCRAPE_RECORD_PROFILE_DIR", DEFAULT_PROFILE_DIR
    )
    prof_path = Path(str(prof_str)).expanduser().resolve()

    db_str = db_path or os.environ.get("SCRAPE_RECORD_DB_PATH", DEFAULT_DB_PATH)
    db_resolved = Path(str(db_str)).expanduser().resolve()

    if headless is None:
        raw = os.environ.get("SCRAPE_RECORD_HEADLESS", "false").lower()
        headless = raw in {"1", "true", "yes", "on"}

    # NB: snapshots_dir may or may not exist on disk post-#1425. It is
    # still a legitimate _fallback_ read location during the migration
    # window, so we keep the layout check but no longer require the
    # directory to actually contain any files.
    _validate_snapshots_inside_package(snapshots_dir, pkg_root)
    _validate_profile_outside_repo(prof_path, repo_root)
    _validate_db_outside_repo(db_resolved, repo_root)

    return Config(
        repo_root=repo_root,
        package_root=pkg_root,
        snapshots_dir=snapshots_dir,
        recordings_dir=recordings_dir,
        profile_dir=prof_path,
        db_path=db_resolved,
        headless=headless,
    )


def snapshot_path(cfg: Config, name: str, symbol: str) -> Path:
    """Return the on-disk path for a given (recording name, symbol) snapshot.

    **Path-traversal hardening**: ``symbol`` and ``name`` are user-facing
    inputs (accepted from fetchers' QueryParams). We enforce strict
    allowlists and then re-assert the resolved path is inside
    ``cfg.snapshots_dir`` — a defense-in-depth check so a future refactor
    that widens the character allowlist can't accidentally re-open a
    traversal.
    """
    _validate_snapshot_component("name", name)
    _validate_snapshot_component("symbol", symbol)
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    out = (cfg.snapshots_dir / name / f"{safe_symbol}.json").resolve()
    # Defense-in-depth: even after sanitizing, confirm the resolved path
    # is inside the snapshots dir. Blocks `..` escapes, NUL tricks, and
    # any future validator regression.
    try:
        out.relative_to(cfg.snapshots_dir.resolve())
    except ValueError as exc:
        raise ConfigError(
            f"snapshot_path({name!r}, {symbol!r}) resolved to {out}, "
            f"which is OUTSIDE snapshots_dir ({cfg.snapshots_dir}). "
            "Refusing — this is a path-traversal attempt."
        ) from exc
    return out


def recording_path(cfg: Config, name: str) -> Path:
    """Return the on-disk path for a recording script."""
    _validate_snapshot_component("name", name)
    return cfg.recordings_dir / f"{name}.py"


# ---------------------------------------------------------------------------
# Path-traversal hardening for user-facing components
# ---------------------------------------------------------------------------


# Symbol allowlist: uppercase alnum + a few finance-legit punctuation chars
# (dot for BRK.B, dash for BRK-B, caret for ^GSPC, equals for CL=F).
# Deliberately excludes: slashes (dir sep), NUL, dots-only, empty, and
# anything > 32 chars (real tickers are < 12; leave headroom for OCC option
# symbols like AAPL251230C00325000).
_SAFE_COMPONENT_MAX_LEN = 64
_SAFE_COMPONENT_ALLOWED = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-_^="
)


def _validate_snapshot_component(field: str, value: str) -> None:
    """Reject values that could escape the snapshots directory.

    Rules:
    - non-empty
    - length ≤ 64
    - only chars in _SAFE_COMPONENT_ALLOWED
    - not "." or ".." (even though allowlist would let a bare "." through)
    - no NUL bytes
    """
    if not isinstance(value, str) or not value:
        raise ConfigError(f"snapshot {field} must be a non-empty string, got {value!r}")
    if len(value) > _SAFE_COMPONENT_MAX_LEN:
        raise ConfigError(
            f"snapshot {field} exceeds max length {_SAFE_COMPONENT_MAX_LEN}: "
            f"{value!r}"
        )
    if "\x00" in value:
        raise ConfigError(f"snapshot {field} contains NUL byte: {value!r} — rejected.")
    if value in (".", ".."):
        raise ConfigError(
            f"snapshot {field} may not be '.' or '..': {value!r} — rejected."
        )
    bad = [c for c in value if c not in _SAFE_COMPONENT_ALLOWED]
    if bad:
        raise ConfigError(
            f"snapshot {field} contains disallowed characters "
            f"{sorted(set(bad))!r} in {value!r}. Allowed: alnum + . - _ ^ ="
        )
