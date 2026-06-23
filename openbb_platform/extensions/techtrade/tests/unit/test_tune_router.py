"""Unit tests for openbb_techtrade.tuning.tune_router (#83 L2, L5, L7, Q-A, Q-F, §5.3 W2)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.models import TradePlan


# --- helpers ---------------------------------------------------------------------------------

def _config_a() -> IndicatorConfig:
    """A NON-default tuned candidate (distinct from DEFAULT_CONFIG)."""
    from dataclasses import replace
    return replace(DEFAULT_CONFIG, macd_fast=14, macd_slow=32, macd_signal=9,
                   adx_length=16, ema_fast=18, ema_slow=55, rsi_length=11, atr_length=18)


def _fake_pool(*a, **kw):
    import pandas as pd
    idx = pd.MultiIndex.from_tuples([], names=["date", "symbol"])
    return (
        pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=idx),
        pd.Series([], index=idx, dtype="float64"),
    )


def _setup_tuned_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the persistence file at a fresh tmp_path and clear caches."""
    path = tmp_path / "techtrade_tuned.json"
    monkeypatch.setattr("openbb_techtrade.tuning.tuned_defaults.TUNED_PATH", path)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tuned_defaults.segment_for_symbol",
        lambda sym: "Information Technology",
    )
    from openbb_techtrade.tuning.tuned_defaults import _clear_cache
    _clear_cache()
    return path


def _fake_validate(verdict: str):
    """Build an awaitable validate_plan replacement that returns (plan, fake_report)."""
    fake_report = SimpleNamespace(
        verdict=verdict,
        pbo=0.18 if verdict == "robust" else 0.31,
        deflated_sharpe=0.97 if verdict == "robust" else 0.62,
        oos_metrics=SimpleNamespace(sharpe=0.84 if verdict == "robust" else 0.10),
        method="wfo",
    )

    async def _validate(plan, *, method="wfo", thresholds=None, horizon_years=5, provider=None):
        return plan.model_copy(update={"validation": fake_report}), fake_report

    return _validate, fake_report


# --- Q-A A1: sample plan uses the segment's benchmark ETF ---------------------------------------

def test_sample_plan_uses_benchmark_etf():
    """Q-A A1: the TradePlan validate_plan receives has symbol == SEGMENT_BENCHMARK_ETFS[segment]."""
    from openbb_techtrade.tuning.tune_router import (
        SEGMENT_BENCHMARK_ETFS,
        _build_sample_plan,
    )
    # The sector ETF is XLK for IT; XLF for Financials; etc.
    plan = _build_sample_plan("Information Technology", as_of=date(2025, 6, 20))
    assert isinstance(plan, TradePlan)
    assert plan.symbol == SEGMENT_BENCHMARK_ETFS["Information Technology"] == "XLK"
    assert plan.segment == "Information Technology"
    assert plan.as_of == date(2025, 6, 20)


def test_segment_benchmark_etfs_covers_all_eleven_gics_sectors():
    """Q-A: every GICS sector has a benchmark ETF entry — no KeyError surprise mid-loop."""
    from openbb_techtrade.tuning.tune_router import SEGMENT_BENCHMARK_ETFS
    expected = {
        "Information Technology", "Financials", "Health Care",
        "Consumer Discretionary", "Consumer Staples", "Energy",
        "Communication Services", "Industrials", "Materials",
        "Utilities", "Real Estate",
    }
    assert set(SEGMENT_BENCHMARK_ETFS.keys()) == expected
    for sector, etf in SEGMENT_BENCHMARK_ETFS.items():
        assert isinstance(etf, str) and etf, f"{sector} has empty ETF"


# --- L2: robust verdict persists -----------------------------------------------------------------

def test_robust_verdict_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """L2 strict: verdict == 'robust' triggers write_tuned; TuningReport.persisted is True."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate("robust")
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))

    report = obb.results
    assert report.persisted is True
    assert "verdict=robust" in report.reason
    # The file now carries the segment.
    from openbb_techtrade.tuning.tuned_defaults import read_tuned
    on_disk = read_tuned()
    assert on_disk is not None and "Information Technology" in on_disk["segments"]


# --- L2: fragile / overfit verdicts do NOT persist (Q-F transparent non-persist) -----------------

@pytest.mark.parametrize("verdict", ["fragile", "overfit"])
def test_non_robust_verdict_does_not_persist(
    verdict: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """L2 + Q-F: fragile/overfit -> persisted=False; file is unchanged (or absent)."""
    path = _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate(verdict)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    assert not path.exists()  # no file before tune

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    report = obb.results

    assert report.persisted is False
    assert f"verdict={verdict}" in report.reason
    assert not path.exists()  # file STILL doesn't exist; no write happened


# --- Q-F guard 3: no-op tune (config equal to DEFAULT_CONFIG) does NOT persist ------------------

def test_no_op_tune_does_not_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-F guard 3: if fit returns DEFAULT_CONFIG, persisted=False, reason='no change from defaults'."""
    path = _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            DEFAULT_CONFIG,
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )
    fake_validate, _ = _fake_validate("robust")  # even a robust verdict shouldn't write a no-op.
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", fake_validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    obb = asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))
    report = obb.results

    assert report.persisted is False
    assert "no change from defaults" in report.reason
    assert not path.exists()


# --- Q-F guard 2: loop over mixed verdicts does NOT raise ---------------------------------------

def test_loop_over_mixed_verdicts_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-F guard 2: caller loops segments with mixed verdicts; nothing raises mid-loop."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            _config_a(),
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )

    verdicts = iter(["robust", "fragile", "overfit", "robust"])
    fake_report_factory = lambda: _fake_validate(next(verdicts))

    async def _validate(plan, **kwargs):
        v, _ = fake_report_factory()
        return await v(plan, **kwargs)

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", _validate,
    )

    from openbb_techtrade.tuning.tune_router import tune
    reports = []
    for seg in ["Information Technology", "Financials", "Energy", "Health Care"]:
        obb = asyncio.run(tune(segment=seg, as_of=date(2025, 6, 20)))
        reports.append(obb.results)

    assert len(reports) == 4
    assert [r.persisted for r in reports] == [True, False, False, True]


# --- §5.3 W2: contextvar override is set during the validate call -------------------------------

def test_override_visible_in_validate_fold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """§5.3 W2: while validate runs, lookup_tuned_for_symbol sees the candidate via contextvar."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    candidate = _config_a()
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.fit_segment",
        lambda X, y, *, trials=100, early_stop=20: (
            candidate,
            {"tuneta_version": "0.2.3-fake", "fit_seconds": 1.5, "tuned_columns": []},
        ),
    )

    observed: list[IndicatorConfig | None] = []

    async def _validate_observer(plan, *, method="wfo", thresholds=None, horizon_years=5, provider=None):
        # Mid-validate: the override must be visible to lookup_tuned_for_symbol.
        from openbb_techtrade.tuning.tuned_defaults import lookup_tuned_for_symbol
        observed.append(lookup_tuned_for_symbol("AAPL"))
        fake_report = SimpleNamespace(verdict="robust", pbo=0.18,
                                       deflated_sharpe=0.97,
                                       oos_metrics=SimpleNamespace(sharpe=0.84),
                                       method=method)
        return plan.model_copy(update={"validation": fake_report}), fake_report

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.validate_plan", _validate_observer,
    )

    from openbb_techtrade.tuning.tune_router import tune
    asyncio.run(tune(segment="Information Technology", as_of=date(2025, 6, 20)))

    assert observed == [candidate], (
        "the candidate must be visible mid-validate via the contextvar override; "
        "if this fails, either the router forgot the `with tune_override(...)`, or "
        "validate_plan started running in an executor/thread/process that "
        "doesn't propagate contextvars — see §5.3 W2 fallback to W1"
    )


# --- argument forwarding ---------------------------------------------------------------------

def test_tune_forwards_trials_and_early_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Q-D: tune(..., trials=N, early_stop=M) reaches fit_segment with those exact values."""
    _setup_tuned_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.pool_sector_ohlcv", _fake_pool,
    )
    captured: dict[str, Any] = {}

    def _fit_spy(X, y, *, trials=100, early_stop=20):
        captured["trials"] = trials
        captured["early_stop"] = early_stop
        return (DEFAULT_CONFIG,
                {"tuneta_version": "x", "fit_seconds": 0.0, "tuned_columns": []})

    monkeypatch.setattr("openbb_techtrade.tuning.tune_router.fit_segment", _fit_spy)
    fake_validate, _ = _fake_validate("robust")
    monkeypatch.setattr("openbb_techtrade.tuning.tune_router.validate_plan", fake_validate)

    from openbb_techtrade.tuning.tune_router import tune
    asyncio.run(tune(
        segment="Information Technology", as_of=date(2025, 6, 20),
        trials=37, early_stop=11,
    ))
    assert captured == {"trials": 37, "early_stop": 11}
