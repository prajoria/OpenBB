"""Typed access to Portfolio Intelligence environment configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

Engine = Literal["mysql", "sqlite"]

_ENGINES = ("mysql", "sqlite")
_ORDER_SINKS = ("paper", "fidelity_csv")
_USER_DATA_DIR = ".portfolio_intel"


class ConfigError(ValueError):
    """A configured local-data path violates a repository safety boundary."""


def _repository_root() -> Path | None:
    """Return the containing Git checkout, or ``None`` for an installed wheel."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists():
            return parent
    return None


def _validate_outside_repo(
    name: str, path: Path | str, repo_root: Path | str | None = None
) -> Path:
    """Resolve ``path`` and refuse the repository root or any descendant."""
    resolved = Path(path).expanduser().resolve()
    root = (
        Path(repo_root).expanduser().resolve()
        if repo_root is not None
        else _repository_root()
    )
    if root is not None:
        try:
            resolved.relative_to(root)
        except ValueError:
            pass
        else:
            raise ConfigError(
                f"{name} must resolve outside the repository; "
                "choose a user-local data path"
            )
    if resolved.exists() and resolved.stat().st_nlink > 1:
        raise ConfigError(
            f"{name} must not be a hard link; choose a dedicated user-local file"
        )
    return resolved


def _choice(env_name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.environ.get(env_name, default).strip().lower()
    if value not in allowed:
        choices = " | ".join(f"'{choice}'" for choice in allowed)
        raise ValueError(f"{env_name} must be one of {choices}; got {value!r}")
    return value


def _path(
    env_name: str,
    default: Path | str | None,
    fallback_name: str,
) -> Path:
    override = os.environ.get(env_name)
    if override:
        return Path(override)
    if default is not None:
        return Path(default)
    return Path.home() / _USER_DATA_DIR / fallback_name


def paper_engine(default: Engine = "mysql") -> Engine:
    """Return the configured paper backend."""
    return cast(Engine, _choice("PI_PAPER_ENGINE", default, _ENGINES))


def paper_db_path(default: Path | str | None = None) -> Path:
    """Return the configured SQLite paper-ledger path."""
    return _path("PI_PAPER_DB", default, "paper.db")


def order_sink(default: str = "paper") -> str:
    """Return the configured order-sink kind."""
    return _choice("PI_ORDER_SINK", default, _ORDER_SINKS)


def order_sink_paper_dir(default: Path | str | None = None) -> Path:
    """Return the configured paper order-batch directory."""
    return _path("PI_ORDER_SINK_PAPER_DIR", default, "order_batches")


def snapshot_engine(default: Engine = "mysql") -> Engine:
    """Return the configured EOD snapshot backend."""
    return cast(Engine, _choice("PI_SNAPSHOT_ENGINE", default, _ENGINES))


def snapshot_db_path(default: Path | str | None = None) -> Path:
    """Return the configured SQLite EOD snapshot path."""
    path = _path("PI_SNAPSHOT_DB", default, "snapshot.db")
    _validate_outside_repo("PI_SNAPSHOT_DB", path)
    return path
