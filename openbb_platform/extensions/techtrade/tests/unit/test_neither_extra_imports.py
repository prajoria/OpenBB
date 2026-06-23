"""Q-G guard 3: techtrade hot path imports + works with BOTH extras absent (#83 L9 + #85 discipline).

This sits next to the existing ``test_backtest_bridge.py`` degradation tests but
asserts a stricter property: with **both** ``tuneta`` *and* ``openbb_backtest``
forced absent, the L9 hot path (``build_indicator_panel`` with ``config=None``)
still produces a panel by falling through to ``DEFAULT_CONFIG``. And ``tune``
itself raises ``TechtradeDependencyError`` with a tuneta-specific message.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest


def _block_imports_of(monkeypatch: pytest.MonkeyPatch, *prefixes: str) -> None:
    """Force any future ``import <prefix>...`` to raise ImportError."""
    for module_name in list(sys.modules):
        if any(module_name == p or module_name.startswith(p + ".") for p in prefixes):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if any(name == p or name.startswith(p + ".") for p in prefixes):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)


def test_techtrade_hot_path_imports_with_both_extras_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Q-G guard 3: import openbb_techtrade + build_indicator_panel all work with neither extra."""
    _block_imports_of(monkeypatch, "tuneta", "openbb_backtest")
    # Pin the tuned file path at a fresh location so lookup_tuned_for_symbol
    # returns None and the L9 path falls through to DEFAULT_CONFIG.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    # Clear the lru_cache so the freshly-pinned tmp path is the one consulted.
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache
    _clear_cache()

    # 1. Top-level techtrade still imports.
    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.models",
        "openbb_techtrade.engine.indicators",
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        "openbb_techtrade.tuning.tuneta_adapter",
    ):
        importlib.import_module(module_name)

    # 2. The L9 hot path works.
    from openbb_techtrade.engine.indicators import build_indicator_panel
    rows = [
        {"open": 100.0 + i * 0.01, "high": 100.2 + i * 0.01,
         "low": 99.8 + i * 0.01, "close": 100.0 + i * 0.01,
         "volume": 1_000_000.0}
        for i in range(250)
    ]
    panel = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), ohlcv_rows=rows)
    assert "rsi" in panel.momentum  # built via DEFAULT_CONFIG fallback


def test_tune_raises_dependency_error_with_tuneta_absent(monkeypatch: pytest.MonkeyPatch):
    """Q-G: tune raises TechtradeDependencyError naming the [tuneta] extra (not [validation])."""
    _block_imports_of(monkeypatch, "tuneta")
    # openbb_backtest stays available so the failure is unambiguously about tuneta.

    import asyncio
    from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError
    from openbb_techtrade.tuning.tune_router import tune

    with pytest.raises(TechtradeDependencyError) as excinfo:
        asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    msg = str(excinfo.value)
    assert "tuneta" in msg
    assert "openbb-techtrade[tuneta]" in msg
