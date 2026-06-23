"""Entry-point plugin discovery + ``resolve`` seam (component 10.2).

Builds on :mod:`openbb_backtest.registry` to let third-party packages ship
strategies without touching this codebase: any class advertised under the
``openbb_backtest_strategies`` entry-point group is imported and registered by
name, and :func:`resolve` instantiates a registered class from a validated
params dict.

- :func:`load_plugins` (alias :func:`discover`) walks the entry-point group,
  importing + registering each class. It is **idempotent** (re-registering the
  same class under the same name is a no-op), raises :class:`ValueError` on a
  genuine name clash (two *different* classes under one name), and never lets a
  single broken plugin abort discovery — the failure is logged and skipped.
- :func:`resolve` returns a live ``Strategy`` instance for ``(name, params)``,
  raising :class:`KeyError` for an unknown name and a clear :class:`ValueError`
  for invalid params.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from openbb_backtest.interfaces import Strategy
from openbb_backtest.registry import get_strategy, register_strategy

logger = logging.getLogger(__name__)

#: Entry-point group third-party packages advertise strategy classes under.
STRATEGY_ENTRY_POINT_GROUP = "openbb_backtest_strategies"


def load_plugins() -> list[str]:
    """Import + register every ``openbb_backtest_strategies`` entry point.

    Returns
    -------
    list of str
        Names of the entry points resolved this call (broken plugins excluded).

    Raises
    ------
    ValueError
        When two *different* classes are advertised under the same name.
    """
    loaded: list[str] = []
    for ep in entry_points(group=STRATEGY_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001 - one bad plugin must not be fatal
            logger.warning("skipping strategy plugin %r: %s", ep.name, exc)
            continue
        _register(ep.name, cls)
        loaded.append(ep.name)
    return loaded


def discover() -> list[str]:
    """Alias for :func:`load_plugins` (discovery reads like a verb at call sites)."""
    return load_plugins()


def resolve(name: str, params: dict[str, object] | None = None) -> Strategy:
    """Instantiate the registered strategy ``name`` from ``params``.

    Parameters
    ----------
    name
        Registered strategy name (case-insensitive).
    params
        Keyword arguments forwarded to the class constructor.

    Returns
    -------
    Strategy
        A live strategy instance.

    Raises
    ------
    KeyError
        When ``name`` is not registered.
    ValueError
        When ``params`` do not match the class constructor.
    """
    cls = get_strategy(name)  # KeyError for unknown name (registry contract)
    kwargs = dict(params or {})
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise ValueError(f"invalid params for strategy '{name}': {exc}") from exc


def _register(name: str, cls: type) -> None:
    """Register ``cls`` under ``name``, idempotent on a re-register of the same class."""
    try:
        existing: type | None = get_strategy(name)
    except KeyError:
        existing = None
    if existing is not None:
        if existing is cls:
            return  # idempotent: same class, same name -> no-op
        raise ValueError(
            f"duplicate strategy plugin name '{name}': "
            f"{existing!r} already registered, refusing to overwrite with {cls!r}"
        )
    register_strategy(name)(cls)
