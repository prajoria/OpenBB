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
    headless: bool

    def summary(self) -> str:
        """Return a human-readable summary of all resolved paths."""
        return (
            f"repo_root       = {self.repo_root}\n"
            f"package_root    = {self.package_root}\n"
            f"snapshots_dir   = {self.snapshots_dir}\n"
            f"recordings_dir  = {self.recordings_dir}\n"
            f"profile_dir     = {self.profile_dir}\n"
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
    """snapshots_dir SHOULD be inside the package (checked-in canned data)."""
    if not _is_inside(path, package_root):
        raise ConfigError(
            f"snapshots_dir ({path}) resolves OUTSIDE the scrape_record "
            f"package ({package_root}). By design, scrape-record commits "
            "snapshots into the repo for reproducible offline fetching. "
            "If you really want external snapshots, subclass Config."
        )


def load_config(
    *,
    package_root: Path | None = None,
    profile_dir: str | Path | None = None,
    headless: bool | None = None,
    dotenv_path: str | Path | None = None,
) -> Config:
    """Build a validated Config from env + explicit overrides.

    Precedence: explicit kwargs > env var > default.

    Env vars:
    - ``SCRAPE_RECORD_PROFILE_DIR``
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

    if headless is None:
        raw = os.environ.get("SCRAPE_RECORD_HEADLESS", "false").lower()
        headless = raw in {"1", "true", "yes", "on"}

    _validate_snapshots_inside_package(snapshots_dir, pkg_root)
    _validate_profile_outside_repo(prof_path, repo_root)

    return Config(
        repo_root=repo_root,
        package_root=pkg_root,
        snapshots_dir=snapshots_dir,
        recordings_dir=recordings_dir,
        profile_dir=prof_path,
        headless=headless,
    )


def snapshot_path(cfg: Config, name: str, symbol: str) -> Path:
    """Return the on-disk path for a given (recording name, symbol) snapshot."""
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    return cfg.snapshots_dir / name / f"{safe_symbol}.json"


def recording_path(cfg: Config, name: str) -> Path:
    """Return the on-disk path for a recording script."""
    return cfg.recordings_dir / f"{name}.py"
