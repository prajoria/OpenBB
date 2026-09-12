"""Typed access to Portfolio Intelligence environment configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

Engine = Literal["mysql", "sqlite"]

_ENGINES = ("mysql", "sqlite")
_ORDER_SINKS = ("paper", "fidelity_csv")
_USER_DATA_DIR = ".portfolio_intel"


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
    return _path("PI_SNAPSHOT_DB", default, "snapshot.db")
