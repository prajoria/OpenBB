"""Unit tests for ``validation/report.py`` (component 08, §2/§3 assembler).

Covers the verdict gate and the :class:`ValidationReport` assembler:

- :func:`verdict` maps ``(pbo, dsr, oos_sharpe, thresholds)`` to
  ``robust | fragile | overfit`` using the design-08 §2 default thresholds, with
  documented precedence **overfit > robust > fragile** (so a metric that triggers
  overfit always wins, even if other metrics look robust).
- :func:`build_validation_report` fuses the already-computed T1 (DSR / MinBTL),
  T3 (per-fold OOS metrics) and T4 (PBO) pieces into a populated, design-§3
  :class:`ValidationReport`, deriving the verdict and recording the effective
  thresholds verbatim for auditability.

See ``docs/designs/backtest-design/08-validation.md`` §2 (verdict table) and §3
(report schema).
"""

from __future__ import annotations

from openbb_backtest.models import FoldResult, PerformanceMetrics, ValidationReport


def _metrics(sharpe: float = 1.0) -> PerformanceMetrics:
    return PerformanceMetrics(
        cagr=0.1,
        sharpe=sharpe,
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


# ---- verdict: the three regimes ------------------------------------------


def test_verdict_robust_requires_all_three_conditions():
    from openbb_backtest.validation.report import verdict

    # PBO < 0.2 AND DSR > 0.95 AND OOS Sharpe > 0.
    assert verdict(pbo=0.1, dsr=0.97, oos_sharpe=0.5) == "robust"


def test_verdict_fragile_middle_band():
    from openbb_backtest.validation.report import verdict

    # 0.2 <= PBO < 0.5 (DSR/OOS otherwise fine) ⇒ fragile.
    assert verdict(pbo=0.3, dsr=0.99, oos_sharpe=0.5) == "fragile"
    # DSR in [0.5, 0.95] ⇒ fragile.
    assert verdict(pbo=0.1, dsr=0.7, oos_sharpe=0.5) == "fragile"


def test_verdict_overfit_if_any_overfit_condition():
    from openbb_backtest.validation.report import verdict

    assert verdict(pbo=0.6, dsr=0.99, oos_sharpe=2.0) == "overfit"  # PBO >= 0.5
    assert verdict(pbo=0.1, dsr=0.4, oos_sharpe=2.0) == "overfit"  # DSR < 0.5
    assert verdict(pbo=0.1, dsr=0.99, oos_sharpe=-0.1) == "overfit"  # OOS <= 0


# ---- verdict: boundaries -------------------------------------------------


def test_verdict_pbo_boundaries():
    from openbb_backtest.validation.report import verdict

    # Exactly 0.2: not robust (needs < 0.2), not overfit ⇒ fragile.
    assert verdict(pbo=0.2, dsr=0.99, oos_sharpe=0.5) == "fragile"
    # Exactly 0.5: overfit (PBO >= 0.5).
    assert verdict(pbo=0.5, dsr=0.99, oos_sharpe=0.5) == "overfit"


def test_verdict_dsr_boundaries():
    from openbb_backtest.validation.report import verdict

    # Exactly 0.95: not robust (needs > 0.95) but in [0.5, 0.95] ⇒ fragile.
    assert verdict(pbo=0.1, dsr=0.95, oos_sharpe=0.5) == "fragile"
    # Exactly 0.5: in [0.5, 0.95] ⇒ fragile (not < 0.5, so not overfit).
    assert verdict(pbo=0.1, dsr=0.5, oos_sharpe=0.5) == "fragile"


def test_verdict_oos_sharpe_zero_is_overfit():
    from openbb_backtest.validation.report import verdict

    assert verdict(pbo=0.1, dsr=0.99, oos_sharpe=0.0) == "overfit"


# ---- verdict: documented precedence overfit > robust > fragile -----------


def test_overfit_precedence_beats_otherwise_robust_metrics():
    from openbb_backtest.validation.report import verdict

    # PBO and DSR look robust, but OOS Sharpe <= 0 forces overfit (precedence).
    assert verdict(pbo=0.05, dsr=0.99, oos_sharpe=0.0) == "overfit"
    # Low PBO + great OOS, but DSR < 0.5 forces overfit.
    assert verdict(pbo=0.05, dsr=0.49, oos_sharpe=3.0) == "overfit"


# ---- verdict: config-overridable thresholds ------------------------------


def test_verdict_thresholds_are_overridable():
    from openbb_backtest.validation.report import verdict

    # Default would call PBO 0.3 fragile; tighten pbo_overfit to 0.25 ⇒ overfit.
    assert verdict(pbo=0.3, dsr=0.99, oos_sharpe=1.0) == "fragile"
    assert (
        verdict(pbo=0.3, dsr=0.99, oos_sharpe=1.0, thresholds={"pbo_overfit": 0.25})
        == "overfit"
    )


def test_verdict_is_deterministic():
    from openbb_backtest.validation.report import verdict

    assert verdict(pbo=0.3, dsr=0.7, oos_sharpe=0.4) == verdict(
        pbo=0.3, dsr=0.7, oos_sharpe=0.4
    )


# ---- build_validation_report: assembly -----------------------------------


def test_build_report_populates_design_three_fields():
    from openbb_backtest.validation.report import build_validation_report

    folds = [
        FoldResult(fold=0, metrics=_metrics(0.8)),
        FoldResult(fold=1, metrics=_metrics(1.2)),
    ]
    report = build_validation_report(
        method="cpcv",
        folds=folds,
        oos_metrics=_metrics(0.5),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.5,
    )
    assert isinstance(report, ValidationReport)
    assert report.method == "cpcv"
    assert len(report.folds) == 2
    assert report.oos_metrics.sharpe == 0.5
    assert report.pbo == 0.1
    assert report.deflated_sharpe == 0.97
    assert report.min_backtest_length_years == 1.5


def test_build_report_derives_verdict_from_inputs():
    from openbb_backtest.validation.report import build_validation_report

    # PBO 0.1, DSR 0.97, OOS Sharpe 0.5 ⇒ robust.
    report = build_validation_report(
        method="wfo",
        folds=[FoldResult(fold=0, metrics=_metrics(0.5))],
        oos_metrics=_metrics(0.5),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.0,
    )
    assert report.verdict == "robust"

    # OOS Sharpe <= 0 ⇒ overfit regardless of PBO/DSR.
    overfit = build_validation_report(
        method="wfo",
        folds=[FoldResult(fold=0, metrics=_metrics(-0.2))],
        oos_metrics=_metrics(-0.2),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.0,
    )
    assert overfit.verdict == "overfit"


def test_build_report_records_effective_thresholds_verbatim():
    from openbb_backtest.validation.report import build_validation_report

    report = build_validation_report(
        method="cpcv",
        folds=[FoldResult(fold=0, metrics=_metrics(0.5))],
        oos_metrics=_metrics(0.5),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.0,
        thresholds={"pbo_robust": 0.15},
    )
    # The override is recorded verbatim and the verdict honours it.
    assert report.thresholds["pbo_robust"] == 0.15
    # Defaults for unspecified keys are still present (auditable full set).
    assert "pbo_overfit" in report.thresholds
    assert "dsr_robust" in report.thresholds


def test_build_report_is_deterministic():
    from openbb_backtest.validation.report import build_validation_report

    kwargs = dict(
        method="cpcv",
        folds=[FoldResult(fold=0, metrics=_metrics(0.5))],
        oos_metrics=_metrics(0.5),
        pbo=0.1,
        deflated_sharpe=0.97,
        min_backtest_length_years=1.0,
    )
    a = build_validation_report(**kwargs)
    b = build_validation_report(**kwargs)
    assert a.model_dump() == b.model_dump()
