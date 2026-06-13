"""Unit tests for core data models (component 02)."""

from __future__ import annotations

import typing
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    BenchmarkStats,
    ComputeConfig,
    DrawdownPeriod,
    EquityPoint,
    FoldResult,
    MonthlyReturn,
    PerformanceMetrics,
    PositionSnapshot,
    TearSheet,
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
            folds=[FoldResult(fold=0, metrics=_metrics())],
            oos_metrics=_metrics(),
            pbo=1.5,
            deflated_sharpe=0.9,
            min_backtest_length_years=1.0,
            verdict="robust",
            thresholds={},
        )


def test_validation_report_carries_design_three_fields():
    report = ValidationReport(
        method="cpcv",
        folds=[
            FoldResult(fold=0, metrics=_metrics()),
            FoldResult(fold=1, metrics=_metrics()),
        ],
        oos_metrics=_metrics(),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.5,
        verdict="robust",
        thresholds={"pbo_robust": 0.2, "dsr_robust": 0.95},
    )
    assert report.method == "cpcv"
    assert len(report.folds) == 2
    assert report.oos_metrics.sharpe == _metrics().sharpe
    assert report.min_backtest_length_years == 1.5
    assert report.thresholds["pbo_robust"] == 0.2


def test_fold_result_roundtrips():
    fold = FoldResult(fold=3, metrics=_metrics(), path_id=2)
    dumped = fold.model_dump()
    restored = FoldResult(**dumped)
    assert restored.fold == 3
    assert restored.path_id == 2
    assert restored.metrics.sharpe == _metrics().sharpe
    # path_id is optional (WFO folds have none).
    assert FoldResult(fold=0, metrics=_metrics()).path_id is None


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


# ---- Tear-sheet models (component 07, §2) --------------------------------


def test_drawdown_period_fields():
    dd = DrawdownPeriod(
        start=date(2021, 1, 4),
        valley=date(2021, 1, 8),
        end=date(2021, 1, 15),
        depth=-0.123,
        length=8,
    )
    assert dd.depth == pytest.approx(-0.123)
    assert dd.length == 8
    # Round-trip invariant holds for the pure-data model.
    assert DrawdownPeriod(**dd.model_dump()) == dd


def test_monthly_return_fields():
    mr = MonthlyReturn(year=2021, month=3, ret=0.042)
    assert mr.year == 2021
    assert mr.month == 3
    assert mr.ret == pytest.approx(0.042)
    assert MonthlyReturn(**mr.model_dump()) == mr


def test_benchmark_stats_are_floats():
    bs = BenchmarkStats(alpha=0.03, beta=1.1, information_ratio=0.45)
    assert isinstance(bs.alpha, float)
    assert isinstance(bs.beta, float)
    assert isinstance(bs.information_ratio, float)
    assert BenchmarkStats(**bs.model_dump()) == bs


def test_tearsheet_minimal_defaults_none():
    ts = TearSheet(
        metrics=_metrics(),
        rolling_sharpe=[0.5, 0.7, 0.9],
        drawdown_periods=[],
        monthly_returns=[],
    )
    # Optional artifact path and benchmark-relative stats default to None.
    assert ts.html_path is None
    assert ts.benchmark_relative is None
    assert ts.rolling_sharpe == [0.5, 0.7, 0.9]


def test_tearsheet_full_design2_field_set():
    ts = TearSheet(
        metrics=_metrics(),
        rolling_sharpe=[1.0, 1.1],
        drawdown_periods=[
            DrawdownPeriod(
                start=date(2021, 1, 4),
                valley=date(2021, 1, 6),
                end=date(2021, 1, 9),
                depth=-0.08,
                length=5,
            )
        ],
        monthly_returns=[MonthlyReturn(year=2021, month=1, ret=0.01)],
        html_path="Analysis/exports/tearsheet_AAA.html",
        benchmark_relative=BenchmarkStats(alpha=0.02, beta=0.9, information_ratio=0.3),
    )
    assert ts.benchmark_relative is not None
    assert ts.benchmark_relative.beta == pytest.approx(0.9)
    assert ts.html_path.endswith(".html")
    assert TearSheet(**ts.model_dump()) == ts


def test_tearsheet_requires_metrics():
    with pytest.raises(ValidationError):
        TearSheet(
            rolling_sharpe=[],
            drawdown_periods=[],
            monthly_returns=[],
        )


def test_tearsheet_models_carry_no_money_or_decimal_fields():
    """Privacy: outward tear-sheet models expose floats only — no Decimal/money.

    The fork privacy rule forbids dollar amounts / account / lot detail on
    outward-facing analytics models. ``PerformanceMetrics`` is allowed as a
    nested sub-model (itself float-only); every *scalar* field on the four new
    models must be a plain float/int/str/bool/date, never ``Decimal``.
    """
    allowed_scalars = (float, int, str, bool, date, datetime, type(None))
    for model in (DrawdownPeriod, MonthlyReturn, BenchmarkStats, TearSheet):
        for name, field in model.model_fields.items():
            ann = field.annotation
            # No Decimal anywhere in the (possibly Optional/!list) annotation.
            assert Decimal not in _annotation_types(ann), f"{model.__name__}.{name}"
            # Scalar (non-list, non-submodel) fields must be in the allowed set.
            origin = typing.get_origin(ann)
            if origin is None and isinstance(ann, type) and not _is_data_model(ann):
                assert issubclass(ann, allowed_scalars), f"{model.__name__}.{name}={ann}"


def _annotation_types(ann: object) -> set:
    """Flatten a typing annotation into the set of concrete types it mentions."""
    found: set = set()
    args = typing.get_args(ann)
    if not args:
        if isinstance(ann, type):
            found.add(ann)
        return found
    for a in args:
        found |= _annotation_types(a)
    return found


def _is_data_model(tp: type) -> bool:
    """True for our nested Pydantic sub-models (allowed inside a tear sheet)."""
    return hasattr(tp, "model_fields")


def test_models_module_stays_import_leaf():
    """models.py must not import sibling backtest modules (no cycles)."""
    import openbb_backtest.models as m

    src = __import__("inspect").getsource(m)
    # No intra-package imports beyond the models module itself.
    assert "from openbb_backtest." not in src
    assert "import openbb_backtest." not in src
