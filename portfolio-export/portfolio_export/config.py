"""
Configuration + strict path validation.

All runtime paths (downloads, browser profile) are resolved and validated
to live OUTSIDE the containing git repo. If any path is inside the repo,
the tool refuses to run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    from dotenv import load_dotenv
    _HAS_DOTENV = True
except ImportError:  # pragma: no cover - dotenv is a declared dep
    _HAS_DOTENV = False


DEFAULT_DOWNLOAD_DIR = "~/portfolio_exports"
DEFAULT_PROFILE_DIR = "~/.portfolio_export/chrome_profile"
DEFAULT_RECORDINGS_DIR = "~/portfolio_export_recordings"


class ConfigError(RuntimeError):
    """Raised when configuration is invalid or violates safety rules."""


@dataclass(frozen=True)
class Config:
    repo_root: Path
    package_root: Path
    bundled_recordings_dir: Path
    user_recordings_dir: Path
    download_dir: Path
    profile_dir: Path
    headless: bool

    def summary(self) -> str:
        return (
            f"repo_root              = {self.repo_root}\n"
            f"package_root           = {self.package_root}\n"
            f"bundled_recordings_dir = {self.bundled_recordings_dir}\n"
            f"user_recordings_dir    = {self.user_recordings_dir}\n"
            f"download_dir           = {self.download_dir}\n"
            f"profile_dir            = {self.profile_dir}\n"
            f"headless               = {self.headless}"
        )


def _find_repo_root(start: Path) -> Path:
    """Walk up from `start` looking for `.git`. Raise if not found."""
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise ConfigError(
        f"Could not locate a git repo root walking up from {start}. "
        "portfolio_export requires a git repo so it can enforce that "
        "download/profile paths are outside it."
    )


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _validate_outside_repo(name: str, path: Path, repo_root: Path) -> None:
    if _is_inside(path, repo_root):
        raise ConfigError(
            f"{name} ({path}) resolves inside the repo ({repo_root}). "
            "portfolio_export refuses to write downloads or browser state "
            "inside the source tree. Move it to a path outside the repo "
            f"(e.g. ~/portfolio_exports) or set {name.upper()} env var."
        )


def _resolve_path(env_val: str | None, default: str) -> Path:
    raw = env_val if env_val else default
    return Path(os.path.expanduser(raw)).resolve()


def load_config(package_root: Path | None = None) -> Config:
    """
    Load config from env (with .env auto-load), resolve paths, validate
    everything is outside the repo.
    """
    package_root = (package_root or Path(__file__).resolve().parent.parent).resolve()

    # Auto-load a local .env next to pyproject.toml if present.
    if _HAS_DOTENV:
        env_file = package_root / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    repo_root = _find_repo_root(package_root)

    download_dir = _resolve_path(
        os.environ.get("PORTFOLIO_EXPORT_DIR"), DEFAULT_DOWNLOAD_DIR
    )
    profile_dir = _resolve_path(
        os.environ.get("PORTFOLIO_EXPORT_PROFILE_DIR"), DEFAULT_PROFILE_DIR
    )
    user_recordings_dir = _resolve_path(
        os.environ.get("PORTFOLIO_EXPORT_RECORDINGS_DIR"), DEFAULT_RECORDINGS_DIR
    )
    headless = os.environ.get("PORTFOLIO_EXPORT_HEADLESS", "0").strip() in {
        "1",
        "true",
        "True",
        "yes",
    }

    _validate_outside_repo("PORTFOLIO_EXPORT_DIR", download_dir, repo_root)
    _validate_outside_repo("PORTFOLIO_EXPORT_PROFILE_DIR", profile_dir, repo_root)
    _validate_outside_repo(
        "PORTFOLIO_EXPORT_RECORDINGS_DIR", user_recordings_dir, repo_root
    )

    bundled_recordings_dir = package_root / "recordings"

    return Config(
        repo_root=repo_root,
        package_root=package_root,
        bundled_recordings_dir=bundled_recordings_dir,
        user_recordings_dir=user_recordings_dir,
        download_dir=download_dir,
        profile_dir=profile_dir,
        headless=headless,
    )


def dated_download_dir(base: Path) -> Path:
    """Return `<base>/YYYY-MM-DD/`, creating it if needed."""
    out = base / date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    return out
