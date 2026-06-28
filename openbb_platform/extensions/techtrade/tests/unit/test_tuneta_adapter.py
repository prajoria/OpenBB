"""Unit tests for openbb_techtrade.tuning.tuneta_adapter (#83 L6, L8, Q-G)."""

from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any

import pandas as pd
import pytest

from openbb_core.app.model.abstract.error import OpenBBError

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.validation.backtest_bridge import TechtradeDependencyError


# --- TechtradeDependencyError reuse (L8 Q-G) -----------------------------------------------------

def test_dependency_error_when_tuneta_absent(monkeypatch: pytest.MonkeyPatch):
    """Q-G: with `tuneta` forced un-importable, fit_segment raises TechtradeDependencyError."""
    # Drop any cached tuneta module so the next import goes through the blocker.
    for module_name in list(sys.modules):
        if module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocker)

    from openbb_techtrade.tuning.tuneta_adapter import _require_tuneta

    with pytest.raises(TechtradeDependencyError) as excinfo:
        _require_tuneta()
    msg = str(excinfo.value)
    assert "tuneta" in msg
    assert "pip install" in msg
    assert "'openbb-techtrade[tuneta]'" in msg


def test_dependency_error_subclasses_openbb_error():
    """L8: reuses #82's TechtradeDependencyError (which subclasses OpenBBError)."""
    assert issubclass(TechtradeDependencyError, OpenBBError)


def test_degradation_other_modules_still_import(monkeypatch: pytest.MonkeyPatch):
    """Q-G + #85: with tuneta absent, every other techtrade module still imports cleanly."""
    real_import = builtins.__import__

    def _blocker(name: str, *args: Any, **kwargs: Any):
        if name.startswith("tuneta"):
            raise ImportError(f"forced absent: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if module_name.startswith("tuneta"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(builtins, "__import__", _blocker)

    for module_name in (
        "openbb_techtrade",
        "openbb_techtrade.models",
        "openbb_techtrade.engine.indicators",
        "openbb_techtrade.tuning",
        "openbb_techtrade.tuning.tuned_defaults",
        "openbb_techtrade.tuning.sector_ohlcv",
        # The adapter itself must be importable too — only _require_tuneta touches tuneta.
        "openbb_techtrade.tuning.tuneta_adapter",
    ):
        importlib.import_module(module_name)


# --- KNOB_TABLE shape (L6) ---------------------------------------------------------------------

def test_knob_table_has_exactly_eight_period_knobs():
    """L6: tuneta search space is exactly 8 period knobs with the documented ranges."""
    from openbb_techtrade.tuning.tuneta_adapter import KNOB_TABLE

    assert len(KNOB_TABLE) == 8
    by_field = {row[0]: row for row in KNOB_TABLE}
    expected = {
        "macd_fast": ("tta.MACD", (8, 20)),
        "macd_slow": ("tta.MACD", (20, 40)),
        "macd_signal": ("tta.MACD", (5, 15)),
        "adx_length": ("tta.ADX", (10, 30)),
        "ema_fast": ("tta.EMA", (10, 30)),
        "ema_slow": ("tta.EMA", (30, 80)),
        "rsi_length": ("tta.RSI", (8, 30)),
        "atr_length": ("tta.ATR", (10, 30)),
    }
    assert set(by_field.keys()) == set(expected.keys())
    for field, (indicator, rng) in expected.items():
        assert by_field[field][1] == indicator
        assert by_field[field][2] == rng


# --- parse_tuned_columns (round-trip, fallback, EMA binding) ------------------------------------

def test_parse_columns_recovers_indicator_config():
    """L6: a known set of tuneta column names parses into the expected IndicatorConfig fields."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = [
        "tta_RSI_timeperiod_19",
        "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
        "tta_ADX_timeperiod_16",
        "tta_ATR_timeperiod_18",
        "tta_EMA_timeperiod_15",   # in (10, 30) -> ema_fast
        "tta_EMA_timeperiod_55",   # in (30, 80) -> ema_slow
    ]
    cfg = parse_tuned_columns(cols)
    assert cfg.rsi_length == 19
    assert cfg.macd_fast == 14
    assert cfg.macd_slow == 32
    assert cfg.macd_signal == 9
    assert cfg.adx_length == 16
    assert cfg.atr_length == 18
    assert cfg.ema_fast == 15
    assert cfg.ema_slow == 55
    # Untouched (non-period) knobs equal DEFAULT_CONFIG.
    assert cfg.stoch_k == DEFAULT_CONFIG.stoch_k
    assert cfg.stoch_d == DEFAULT_CONFIG.stoch_d
    assert cfg.stoch_smooth_k == DEFAULT_CONFIG.stoch_smooth_k
    assert cfg.bb_length == DEFAULT_CONFIG.bb_length
    assert cfg.bb_std == DEFAULT_CONFIG.bb_std
    assert cfg.kc_length == DEFAULT_CONFIG.kc_length
    assert cfg.kc_scalar == DEFAULT_CONFIG.kc_scalar


def test_parse_unknown_column_falls_back_to_default(caplog: pytest.LogCaptureFixture):
    """An unrecognised column name -> that knob stays at DEFAULT_CONFIG; logs WARNING; no raise."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = ["pta_something_weird_42", "tta_RSI_timeperiod_19"]
    with caplog.at_level("WARNING"):
        cfg = parse_tuned_columns(cols)
    # Recognised column was still applied:
    assert cfg.rsi_length == 19
    # Unrecognised one is mentioned in the WARNING:
    assert "pta_something_weird_42" in caplog.text
    # Untuned knobs (no MACD column at all) stay at DEFAULT_CONFIG.
    assert cfg.macd_fast == DEFAULT_CONFIG.macd_fast


def test_parse_only_macd_keeps_other_periods_at_default():
    """A tune that returns only a MACD column leaves rsi/adx/atr/ema at DEFAULT_CONFIG."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cols = ["tta_MACD_fastperiod_10_slowperiod_30_signalperiod_7"]
    cfg = parse_tuned_columns(cols)
    assert cfg.macd_fast == 10
    assert cfg.macd_slow == 30
    assert cfg.macd_signal == 7
    assert cfg.rsi_length == DEFAULT_CONFIG.rsi_length
    assert cfg.adx_length == DEFAULT_CONFIG.adx_length
    assert cfg.atr_length == DEFAULT_CONFIG.atr_length
    assert cfg.ema_fast == DEFAULT_CONFIG.ema_fast
    assert cfg.ema_slow == DEFAULT_CONFIG.ema_slow


def test_ema_binding_by_range():
    """L6 EMA sharp edge: two EMA columns -> period in (10,30) is ema_fast, period in (30,80) is ema_slow."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cfg = parse_tuned_columns([
        "tta_EMA_timeperiod_25",
        "tta_EMA_timeperiod_60",
    ])
    assert cfg.ema_fast == 25
    assert cfg.ema_slow == 60
    # Reversed input order — binding by range, not order:
    cfg2 = parse_tuned_columns([
        "tta_EMA_timeperiod_60",
        "tta_EMA_timeperiod_25",
    ])
    assert cfg2.ema_fast == 25
    assert cfg2.ema_slow == 60


def test_ema_single_period_in_fast_range_only_binds_fast():
    """Only one EMA column in (10,30) — ema_slow stays at DEFAULT_CONFIG."""
    from openbb_techtrade.tuning.tuneta_adapter import parse_tuned_columns

    cfg = parse_tuned_columns(["tta_EMA_timeperiod_20"])
    assert cfg.ema_fast == 20
    assert cfg.ema_slow == DEFAULT_CONFIG.ema_slow


# --- fit_segment (uses a faked TuneTA so test stays offline + tuneta-absent-safe) ---------------

def test_fit_segment_returns_candidate_config_and_meta(monkeypatch: pytest.MonkeyPatch):
    """fit_segment(X, y) -> (IndicatorConfig, meta-dict) via a faked TuneTA."""

    class _FakeTuneTA:
        def __init__(self, *a, **kw): self._fitted = False
        def fit(self, X, y, **kwargs):
            self._fitted = True
            self._kwargs = kwargs
        def transform(self, X):
            # Mimic tuneta's column-name encoding.
            cols = [
                "tta_RSI_timeperiod_19",
                "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
                "tta_ADX_timeperiod_16",
                "tta_ATR_timeperiod_18",
                "tta_EMA_timeperiod_15",
                "tta_EMA_timeperiod_55",
            ]
            return pd.DataFrame({c: [0.0] for c in cols})

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._require_tuneta",
        lambda: _FakeTuneTA,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._tuneta_version",
        lambda: "0.2.3-fake",
    )

    from openbb_techtrade.tuning.tuneta_adapter import fit_segment

    X = pd.DataFrame({"close": [1.0, 2.0, 3.0]})  # shape doesn't matter for the fake
    y = pd.Series([0.01, 0.02, -0.01])
    candidate, meta = fit_segment(X, y, trials=50, early_stop=10)

    assert isinstance(candidate, IndicatorConfig)
    assert candidate.rsi_length == 19
    assert candidate.macd_fast == 14
    assert candidate.ema_fast == 15
    assert candidate.ema_slow == 55
    assert meta["tuneta_version"] == "0.2.3-fake"
    assert "fit_seconds" in meta and meta["fit_seconds"] >= 0
    assert meta["tuned_columns"] == [
        "tta_RSI_timeperiod_19",
        "tta_MACD_fastperiod_14_slowperiod_32_signalperiod_9",
        "tta_ADX_timeperiod_16",
        "tta_ATR_timeperiod_18",
        "tta_EMA_timeperiod_15",
        "tta_EMA_timeperiod_55",
    ]


def test_fit_segment_forwards_trials_and_early_stop(monkeypatch: pytest.MonkeyPatch):
    """trials/early_stop arguments reach the TuneTA.fit() call verbatim."""

    captured: dict[str, Any] = {}

    class _FakeTuneTA:
        def __init__(self, *a, **kw): pass
        def fit(self, X, y, **kwargs): captured.update(kwargs)
        def transform(self, X): return pd.DataFrame({"tta_RSI_timeperiod_14": [0.0]})

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._require_tuneta",
        lambda: _FakeTuneTA,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuneta_adapter._tuneta_version",
        lambda: "0.2.3-fake",
    )

    from openbb_techtrade.tuning.tuneta_adapter import fit_segment
    fit_segment(pd.DataFrame({"close": [1.0]}), pd.Series([0.0]), trials=37, early_stop=11)

    assert captured["trials"] == 37
    assert captured["early_stop"] == 11
