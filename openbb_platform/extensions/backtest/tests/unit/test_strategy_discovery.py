"""Unit tests for ``strategies/discovery.py`` (component 10.2, plugin mechanism).

Covers entry-point auto-discovery and the ``resolve`` instantiation seam built on
the existing :mod:`openbb_backtest.registry`:

- :func:`load_plugins` / :func:`discover` import every class advertised under the
  ``openbb_backtest_strategies`` entry-point group and register it by name. It is
  idempotent (re-running is a no-op), raises :class:`ValueError` on a genuine
  duplicate name, and never lets one broken plugin abort discovery (it is logged
  and skipped).
- :func:`resolve` turns ``(name, params)`` into a live ``Strategy`` instance,
  raising :class:`KeyError` for an unknown name and a clear :class:`ValueError`
  for invalid params.

Discovery is exercised with a monkeypatched fake ``EntryPoint`` — no real package
install is required.

See ``docs/designs/backtest-design/10-strategy-library.md``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from openbb_backtest.interfaces import Strategy
from openbb_backtest.strategies.base import WeightStrategy


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot/restore the global strategy registry around each test."""
    from openbb_backtest import registry
    from openbb_backtest.strategies import discovery

    saved = dict(registry._STRATEGIES)
    # Reset the lazy-load latch so each test starts from a clean "haven't
    # scanned entry_points yet" state — the new lazy-load contract in
    # ``resolve()`` is observable only on the first call.
    saved_latch = discovery._PLUGINS_LOADED
    discovery._PLUGINS_LOADED = False
    try:
        yield
    finally:
        registry._STRATEGIES.clear()
        registry._STRATEGIES.update(saved)
        discovery._PLUGINS_LOADED = saved_latch


# ---- fake entry points (no real install) ---------------------------------


class _FakeEP:
    """A minimal stand-in for :class:`importlib.metadata.EntryPoint`."""

    def __init__(self, name: str, cls: type | None = None, error: Exception | None = None) -> None:
        self.name = name
        self._cls = cls
        self._error = error

    def load(self) -> type:
        if self._error is not None:
            raise self._error
        assert self._cls is not None
        return self._cls


def _patch_entry_points(monkeypatch, eps: list[_FakeEP]) -> None:
    from openbb_backtest.strategies import discovery

    def _fake(group: str) -> list[_FakeEP]:
        return list(eps) if group == discovery.STRATEGY_ENTRY_POINT_GROUP else []

    monkeypatch.setattr(discovery, "entry_points", _fake)


class _PluginA(WeightStrategy):
    def target_weights(self, data):  # noqa: ANN001
        return pd.Series({"AAA": 1.0})


class _PluginB(WeightStrategy):
    def target_weights(self, data):  # noqa: ANN001
        return pd.Series({"BBB": 1.0})


# ---- load_plugins / discover ---------------------------------------------


def test_load_plugins_registers_entry_point_classes(monkeypatch):
    from openbb_backtest.registry import get_strategy
    from openbb_backtest.strategies.discovery import load_plugins

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    loaded = load_plugins()

    assert "plugin_a" in loaded
    assert get_strategy("plugin_a") is _PluginA


def test_discover_is_alias_for_load_plugins(monkeypatch):
    from openbb_backtest.strategies import discovery

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    out = discovery.discover()
    assert "plugin_a" in out


def test_load_plugins_is_idempotent(monkeypatch):
    from openbb_backtest.registry import get_strategy
    from openbb_backtest.strategies.discovery import load_plugins

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    load_plugins()
    # Second call must not raise and must not double-register.
    load_plugins()
    assert get_strategy("plugin_a") is _PluginA


def test_duplicate_plugin_names_raise_value_error(monkeypatch):
    from openbb_backtest.strategies.discovery import load_plugins

    _patch_entry_points(
        monkeypatch,
        [_FakeEP("clash", _PluginA), _FakeEP("clash", _PluginB)],
    )
    with pytest.raises(ValueError, match="clash"):
        load_plugins()


def test_bad_plugin_is_logged_and_skipped_not_fatal(monkeypatch, caplog):
    from openbb_backtest.registry import get_strategy, list_strategies
    from openbb_backtest.strategies.discovery import load_plugins

    _patch_entry_points(
        monkeypatch,
        [
            _FakeEP("broken", error=ImportError("boom")),
            _FakeEP("good", _PluginA),
        ],
    )
    with caplog.at_level("WARNING"):
        loaded = load_plugins()

    # The good plugin survives; the broken one is absent (not fatal).
    assert get_strategy("good") is _PluginA
    assert "broken" not in list_strategies()
    assert "good" in loaded
    assert any("broken" in rec.message for rec in caplog.records)


# ---- resolve -------------------------------------------------------------


def test_resolve_returns_strategy_instance(monkeypatch):
    from openbb_backtest.strategies.discovery import load_plugins, resolve

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    load_plugins()

    obj = resolve("plugin_a", {"id": "custom_id"})
    assert isinstance(obj, Strategy)
    assert isinstance(obj, _PluginA)
    assert obj.id == "custom_id"


def test_resolve_without_params_uses_defaults(monkeypatch):
    from openbb_backtest.strategies.discovery import load_plugins, resolve

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    load_plugins()

    obj = resolve("plugin_a")
    assert isinstance(obj, _PluginA)


def test_resolve_unknown_name_raises_key_error():
    from openbb_backtest.strategies.discovery import resolve

    with pytest.raises(KeyError):
        resolve("does_not_exist")


def test_resolve_invalid_params_raises_clear_value_error(monkeypatch):
    from openbb_backtest.strategies.discovery import load_plugins, resolve

    _patch_entry_points(monkeypatch, [_FakeEP("plugin_a", _PluginA)])
    load_plugins()

    with pytest.raises(ValueError, match="plugin_a"):
        resolve("plugin_a", {"not_a_real_param": 123})


# ---- pyproject declares the entry-point group ----------------------------


def test_pyproject_declares_entry_point_group():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'plugins."openbb_backtest_strategies"' in text


# ---- regression guard: resolve() lazy-loads entry-point plugins ----------


def test_resolve_lazy_loads_entry_point_plugins_on_first_call(monkeypatch):
    """resolve(name) must auto-load entry-point plugins on first use.

    Regression guard for bd OpenBBTechnical-498 — the notebook §5.1 validate
    cell failed with `KeyError: no strategy registered as 'techtrade_confluence'`
    because resolve() went straight to get_strategy() without calling
    load_plugins() first, even though the validate_router._strategy_factory
    docstring promised "loading entry-point plugins on demand."
    """
    from openbb_backtest.strategies.discovery import resolve

    # Latch starts False (fixture reset); the plugin is NOT pre-registered.
    _patch_entry_points(monkeypatch, [_FakeEP("lazy_plugin", _PluginA)])

    # resolve() should auto-load via the latch.
    obj = resolve("lazy_plugin")
    assert isinstance(obj, _PluginA)


def test_resolve_does_not_re_scan_entry_points_after_first_call(monkeypatch):
    """The _PLUGINS_LOADED latch makes repeated resolve() calls free.

    Regression guard for the second half of bd OpenBBTechnical-498's fix —
    if the latch were missing, every resolve() would walk entry_points()
    which is non-zero cost on a hot loop.
    """
    import contextlib

    from openbb_backtest.strategies import discovery

    call_count = {"n": 0}
    original = discovery.entry_points

    def _counting(group: str):
        if group == discovery.STRATEGY_ENTRY_POINT_GROUP:
            call_count["n"] += 1
        return original(group=group)

    monkeypatch.setattr(discovery, "entry_points", _counting)

    # First call triggers the scan. The strategy may or may not be installed
    # in this test env — what we care about is the SCAN count, not resolution.
    with contextlib.suppress(KeyError):
        discovery.resolve("techtrade_confluence", {"symbols": ["MSFT"]})
    first_count = call_count["n"]
    assert first_count == 1

    # Second call must NOT re-scan (latch already flipped).
    with contextlib.suppress(KeyError):
        discovery.resolve("techtrade_confluence", {"symbols": ["MSFT"]})
    assert call_count["n"] == 1, "resolve() re-scanned entry_points after first call"
