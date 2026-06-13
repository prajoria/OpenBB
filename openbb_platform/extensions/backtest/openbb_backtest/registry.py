"""Strategy and engine registries.

A decorator registry maps a string name to a class so ``obb.backtest.run`` can
accept either a concrete object or a registered name, and third-party plugins can
register via the same decorator. See
``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

_T = TypeVar("_T")

_STRATEGIES: dict[str, type] = {}
_ENGINES: dict[str, type] = {}


def register_strategy(name: str) -> Callable[[type[_T]], type[_T]]:
    """Register a strategy class under ``name``."""

    def _decorator(cls: type[_T]) -> type[_T]:
        key = name.lower()
        if key in _STRATEGIES:
            raise ValueError(f"strategy '{name}' is already registered")
        _STRATEGIES[key] = cls
        return cls

    return _decorator


def register_engine(name: str) -> Callable[[type[_T]], type[_T]]:
    """Register an engine class under ``name``."""

    def _decorator(cls: type[_T]) -> type[_T]:
        key = name.lower()
        if key in _ENGINES:
            raise ValueError(f"engine '{name}' is already registered")
        _ENGINES[key] = cls
        return cls

    return _decorator


def get_strategy(name: str) -> type:
    """Return the strategy class registered under ``name``."""
    try:
        return _STRATEGIES[name.lower()]
    except KeyError as exc:
        raise KeyError(f"no strategy registered as '{name}'") from exc


def get_engine(name: str) -> type:
    """Return the engine class registered under ``name``."""
    try:
        return _ENGINES[name.lower()]
    except KeyError as exc:
        raise KeyError(f"no engine registered as '{name}'") from exc


def list_strategies() -> list[str]:
    """Return all registered strategy names."""
    return sorted(_STRATEGIES)


def list_engines() -> list[str]:
    """Return all registered engine names."""
    return sorted(_ENGINES)
