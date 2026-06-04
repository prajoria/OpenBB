"""Unit tests for core data models (component 02)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    ComputeConfig,
    EquityPoint,
    PerformanceMetrics,
    PositionSnapshot,
    Trade,
    ValidationReport,
)
from pydantic import ValidationError


def _metrics() -> PerformanceMetrics:
    return PerformanceMetrics(
        cagr=0.1,
        sharpe=1.2,
        sortino=1.5,
        calmar=0.8,
        max_drawdown=-0.2,
        volatility=0.15,
        var_95=-0.03,
        cvar_95=-0.05,
        win_rate=0.55,
        profit_factor=1.4,
        turnover=2.0,
    )


def test_config_valid():
    cfg = BacktestConfig(
        strategy="buy_and_hold",
        universe=["AAPL", "MSFT"],
        start=date(2020, 1, 1),
        end=date(2021, 1, 1),
    )
    assert cfg.engine == "auto"
    assert cfg.initial_cash == Decimal("100000")
    assert isinstance(cfg.compute, ComputeConfig)


def test_config_end_before_start_rejected():
    with pytest.raises(ValidationError):
        BacktestConfig(
            strategy="s",
            universe=["AAPL"],
            start=date(2021, 1, 1),
            end=date(2020, 1, 1),
        )


def test_config_empty_universe_rejected():
    with pytest.raises(ValidationError):
        BacktestConfig(
            strategy="s",
            universe=[],
            start=date(2020, 1, 1),
            end=date(2021, 1, 1),
        )


def test_config_non_positive_cash_rejected():
    with pytest.raises(ValidationError):
        BacktestConfig(
            strategy="s",
            universe=["AAPL"],
            start=date(2020, 1, 1),
            end=date(2021, 1, 1),
            initial_cash=Decimal("0"),
        )


def test_compute_headroom_validation():
    with pytest.raises(ValidationError):
        ComputeConfig(gpu_vram_headroom=1.0)
    assert ComputeConfig(gpu_vram_headroom=0.0).gpu_vram_headroom == 0.0


def test_validation_report_pbo_range():
    with pytest.raises(ValidationError):
        ValidationReport(
            method="wfo",
            in_sample=_metrics(),
            out_of_sample=_metrics(),
            pbo=1.5,
            deflated_sharpe=0.9,
            n_trials=10,
            verdict="robust",
        )


def test_result_roundtrip_equivalence():
    cfg = BacktestConfig(
        strategy="buy_and_hold",
        universe=["AAPL"],
        start=date(2020, 1, 1),
        end=date(2021, 1, 1),
    )
    ts = datetime(2020, 6, 1, tzinfo=timezone.utc)
    result = BacktestResult(
        equity_curve=[
            EquityPoint(date=ts, equity=Decimal("100000"), cash=Decimal("0"), exposure=1.0)
        ],
        trades=[
            Trade(
                timestamp=ts,
                symbol="AAPL",
                side="buy",
                quantity=Decimal("10"),
                price=Decimal("100"),
            )
        ],
        positions=[
            PositionSnapshot(
                date=ts,
                symbol="AAPL",
                quantity=Decimal("10"),
                market_value=Decimal("1000"),
                weight=1.0,
            )
        ],
        metrics=_metrics(),
        engine_used="vectorized",
        config=cfg,
    )
    # Round-trip invariant: Model(**m.model_dump()) == m
    assert BacktestResult(**result.model_dump()) == result
