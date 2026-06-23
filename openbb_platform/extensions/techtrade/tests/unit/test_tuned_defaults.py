"""Unit tests for openbb_techtrade.tuning.tuned_defaults (#83 L3, L9, Q-E, §5.3 W2)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig


# --- read_tuned / lookup ----------------------------------------------------------------------

def test_read_missing_file_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Absent file -> lookup_tuned_for_symbol returns None, no raise."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
    )
    _clear_cache()
    assert lookup_tuned_for_symbol("AAPL") is None


def test_schema_version_mismatch_returns_none_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """Q-E: a file with schema_version != '1.0' is treated as absent (returns None), logs WARNING."""
    path = tmp_path / "techtrade_tuned.json"
    path.write_text(json.dumps({"schema_version": "99.0", "segments": {}}))
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
    )
    _clear_cache()
    with caplog.at_level("WARNING"):
        result = lookup_tuned_for_symbol("AAPL")
    assert result is None
    assert "schema_version" in caplog.text


# --- write_tuned + read roundtrip -------------------------------------------------------------

def test_read_after_write_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L3: write_tuned(seg, cfg, meta) -> read_tuned recovers the segment entry."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    # Force the symbol-to-segment mapping to "Information Technology" for AAPL.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology" if sym == "AAPL" else None,
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    tuned = IndicatorConfig(
        macd_fast=14, macd_slow=32, macd_signal=9,
        adx_length=16, ema_fast=18, ema_slow=55,
        rsi_length=11, atr_length=18,
        # the 7 non-period knobs at DEFAULT_CONFIG values:
        stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
        stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
        bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
        kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
    )
    meta = {"verdict": "robust", "pbo": 0.18, "dsr": 0.97, "oos_sharpe": 0.84,
            "tuned_at": "2026-06-21T16:49:48Z", "tuneta_version": "0.2.3",
            "as_of": "2026-06-21", "horizon_years": 5}
    write_tuned("Information Technology", tuned, meta)
    looked_up = lookup_tuned_for_symbol("AAPL")
    assert looked_up == tuned
    # AAPL maps to IT; an unmapped symbol gets None even though IT exists.
    assert lookup_tuned_for_symbol("UNKNOWN") is None


def test_write_tuned_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """write_tuned must write via temp file + os.replace (no half-written state visible)."""
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
    with mock.patch("os.replace") as replace_spy:
        write_tuned("Information Technology", DEFAULT_CONFIG,
                    {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})
        assert replace_spy.called, "write_tuned must use os.replace for atomic write"


# --- Q-E mtime cache --------------------------------------------------------------------------

def test_mtime_cache_invalidates_on_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-E: writes twice in quick succession both visible (st_size tiebreaker for coarse-mtime FSes)."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    cfg_a = IndicatorConfig(macd_fast=10, macd_slow=20, macd_signal=5,
                            adx_length=10, ema_fast=10, ema_slow=30,
                            rsi_length=10, atr_length=10,
                            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    cfg_b = IndicatorConfig(macd_fast=15, macd_slow=25, macd_signal=8,
                            adx_length=15, ema_fast=15, ema_slow=40,
                            rsi_length=15, atr_length=15,
                            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    write_tuned("Information Technology", cfg_a,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:00Z"})
    assert lookup_tuned_for_symbol("AAPL") == cfg_a
    # Write again in the same mtime tick. write_tuned must clear cache explicitly
    # (Q-E guard 2) so the second read sees the new config even when mtime didn't tick.
    write_tuned("Information Technology", cfg_b,
                {"verdict": "robust", "tuned_at": "2026-06-21T00:00:01Z"})
    assert lookup_tuned_for_symbol("AAPL") == cfg_b


def test_lru_cache_maxsize_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-E guard 1: cache_info().maxsize is exactly CACHE_MAXSIZE; re-writes don't unbound it."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH",
        tmp_path / "techtrade_tuned.json",
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        CACHE_MAXSIZE,
        _clear_cache,
        _read_tuned_cached,
        lookup_tuned_for_symbol,
        write_tuned,
    )
    _clear_cache()
    for i in range(CACHE_MAXSIZE * 2):
        cfg = IndicatorConfig(
            macd_fast=8 + i, macd_slow=20 + i, macd_signal=5,
            adx_length=10, ema_fast=10, ema_slow=30,
            rsi_length=10, atr_length=10,
            stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
            stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
            bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
            kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
        )
        write_tuned("Information Technology", cfg,
                    {"verdict": "robust", "tuned_at": f"2026-06-21T00:00:{i:02d}Z"})
        lookup_tuned_for_symbol("AAPL")
    info = _read_tuned_cached.cache_info()
    assert info.maxsize == CACHE_MAXSIZE
    assert info.currsize <= CACHE_MAXSIZE


# --- §5.3 W2 contextvar override --------------------------------------------------------------

def test_contextvar_override_takes_precedence_over_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """§5.3 W2: a tune_override context sets the active candidate; the file is bypassed."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        tune_override,
        write_tuned,
    )
    _clear_cache()
    on_disk = IndicatorConfig(macd_fast=10, macd_slow=20, macd_signal=5,
                              adx_length=10, ema_fast=10, ema_slow=30,
                              rsi_length=10, atr_length=10,
                              stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                              stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                              bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                              kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    override = IndicatorConfig(macd_fast=99, macd_slow=99, macd_signal=99,
                               adx_length=99, ema_fast=99, ema_slow=99,
                               rsi_length=99, atr_length=99,
                               stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
                               stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
                               bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
                               kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar)
    write_tuned("Information Technology", on_disk, {"verdict": "robust",
                                                    "tuned_at": "2026-06-21T00:00:00Z"})
    # Without the override: file value wins.
    assert lookup_tuned_for_symbol("AAPL") == on_disk
    # Inside the override: contextvar wins.
    with tune_override({"Information Technology": override}):
        assert lookup_tuned_for_symbol("AAPL") == override
    # After the override: file value again.
    assert lookup_tuned_for_symbol("AAPL") == on_disk


def test_contextvar_override_for_missing_segment_returns_none(monkeypatch: pytest.MonkeyPatch):
    """A symbol whose segment is NOT in the override dict still resolves via file (or None)."""
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Energy" if sym == "XOM" else "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import (
        _clear_cache,
        lookup_tuned_for_symbol,
        tune_override,
    )
    _clear_cache()
    override = IndicatorConfig(
        macd_fast=99, macd_slow=99, macd_signal=99,
        adx_length=99, ema_fast=99, ema_slow=99,
        rsi_length=99, atr_length=99,
        stoch_k=DEFAULT_CONFIG.stoch_k, stoch_d=DEFAULT_CONFIG.stoch_d,
        stoch_smooth_k=DEFAULT_CONFIG.stoch_smooth_k,
        bb_length=DEFAULT_CONFIG.bb_length, bb_std=DEFAULT_CONFIG.bb_std,
        kc_length=DEFAULT_CONFIG.kc_length, kc_scalar=DEFAULT_CONFIG.kc_scalar,
    )
    with tune_override({"Information Technology": override}):
        # AAPL maps to IT (in the override) -> override wins.
        assert lookup_tuned_for_symbol("AAPL") == override
        # XOM maps to Energy (NOT in the override; no file either) -> None.
        assert lookup_tuned_for_symbol("XOM") is None
