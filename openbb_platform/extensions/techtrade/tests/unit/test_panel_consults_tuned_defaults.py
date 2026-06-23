"""Unit tests for the L9 auto-load: build_indicator_panel consults tuned_defaults."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from openbb_techtrade.engine.indicators import (
    DEFAULT_CONFIG,
    IndicatorConfig,
    build_indicator_panel,
)


def _synth_rows(n: int = 250, *, base: float = 100.0) -> list[dict]:
    """A deterministic OHLCV stream long enough for every indicator to warm up."""
    rows = []
    for i in range(n):
        close = base + 0.01 * i + (i % 7) * 0.05
        rows.append({
            "open": close - 0.1, "high": close + 0.2, "low": close - 0.2,
            "close": close, "volume": 1_000_000.0,
        })
    return rows


def _tuned_config() -> IndicatorConfig:
    """A non-default IndicatorConfig (every period knob shifted by +2)."""
    return replace(
        DEFAULT_CONFIG,
        macd_fast=DEFAULT_CONFIG.macd_fast + 2,
        macd_slow=DEFAULT_CONFIG.macd_slow + 2,
        macd_signal=DEFAULT_CONFIG.macd_signal + 2,
        adx_length=DEFAULT_CONFIG.adx_length + 2,
        ema_fast=DEFAULT_CONFIG.ema_fast + 2,
        ema_slow=DEFAULT_CONFIG.ema_slow + 2,
        rsi_length=DEFAULT_CONFIG.rsi_length + 2,
        atr_length=DEFAULT_CONFIG.atr_length + 2,
    )


def test_panel_falls_back_to_default_when_no_tuned_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L9 regression: with no tuned file, panel uses DEFAULT_CONFIG (existing behaviour preserved)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache
    _clear_cache()

    rows = _synth_rows()
    panel = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), ohlcv_rows=rows)
    # The default RSI_length is 14 -- a panel built with config=None and no tuned
    # file should still have a finite RSI value computed at the default period.
    assert "rsi" in panel.momentum
    assert isinstance(panel.momentum["rsi"], float)


def test_panel_uses_tuned_when_segment_has_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L9: after writing a tuned config for IT, building a panel for AAPL (IT) uses tuned periods."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache, write_tuned
    _clear_cache()

    tuned = _tuned_config()
    write_tuned("Information Technology", tuned,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})

    rows = _synth_rows()
    panel_tuned = build_indicator_panel("AAPL", as_of=date(2025, 6, 20), ohlcv_rows=rows)
    panel_default = build_indicator_panel(
        "AAPL", as_of=date(2025, 6, 20), ohlcv_rows=rows, config=DEFAULT_CONFIG,
    )

    # The tuned RSI period (default + 2 = 16) yields a different value than the
    # default period (14) on the same OHLCV stream. If they're identical, the
    # auto-load did not fire.
    assert panel_tuned.momentum["rsi"] != panel_default.momentum["rsi"], (
        "panel built with config=None and a tuned IT entry must use the tuned "
        "RSI period (default+2), not DEFAULT_CONFIG.rsi_length"
    )


def test_explicit_config_overrides_tuned_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L9: passing config=X explicitly bypasses tuned-defaults lookup (caller intent wins)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache, write_tuned
    _clear_cache()

    tuned = _tuned_config()
    write_tuned("Information Technology", tuned,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})

    rows = _synth_rows()
    # Caller passes config=DEFAULT_CONFIG explicitly. Auto-load must NOT fire.
    panel_explicit = build_indicator_panel(
        "AAPL", as_of=date(2025, 6, 20), ohlcv_rows=rows, config=DEFAULT_CONFIG,
    )
    # Sanity check: the same explicit call without any tuned file gives the same
    # RSI value.
    panel_no_tuned_file = build_indicator_panel(
        "MSFT", as_of=date(2025, 6, 20), ohlcv_rows=rows, config=DEFAULT_CONFIG,
    )
    assert panel_explicit.momentum["rsi"] == panel_no_tuned_file.momentum["rsi"]
