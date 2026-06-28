"""Unit tests for scaffolding: package imports, registry, settings, router."""

from __future__ import annotations

import pytest


def test_package_imports():
    import openbb_backtest

    assert openbb_backtest.__version__


def test_core_modules_import():
    # Leaf and near-leaf modules must import without heavy dependencies.
    import openbb_backtest.helpers  # noqa: F401
    import openbb_backtest.interfaces  # noqa: F401
    import openbb_backtest.models  # noqa: F401
    import openbb_backtest.registry  # noqa: F401
    import openbb_backtest.settings  # noqa: F401
    from openbb_backtest.engine import execution  # noqa: F401


def test_settings_defaults():
    from openbb_backtest.settings import BacktestSettings

    s = BacktestSettings()
    assert s.default_calendar == "XNYS"
    assert s.default_engine == "auto"
    assert s.reconcile_tolerance == pytest.approx(1e-6)


def test_strategy_registry_roundtrip():
    from openbb_backtest.registry import (
        get_strategy,
        list_strategies,
        register_strategy,
    )

    @register_strategy("unit_demo_strategy")
    class _Demo:
        id = "unit_demo_strategy"

    assert "unit_demo_strategy" in list_strategies()
    assert get_strategy("UNIT_DEMO_STRATEGY") is _Demo


def test_registry_duplicate_rejected():
    from openbb_backtest.registry import register_strategy

    @register_strategy("unit_dup_strategy")
    class _A:
        pass

    with pytest.raises(ValueError):

        @register_strategy("unit_dup_strategy")
        class _B:
            pass


def test_registry_unknown_lookup_raises():
    from openbb_backtest.registry import get_engine

    with pytest.raises(KeyError):
        get_engine("does_not_exist")
