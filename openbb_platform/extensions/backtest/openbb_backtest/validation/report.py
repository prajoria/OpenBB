"""Verdict gate + :class:`ValidationReport` assembler (component 08, §2/§3).

Two pure, deterministic functions that turn the already-computed overfitting
pieces into the auditable robustness verdict:

- :func:`verdict` maps ``(pbo, dsr, oos_sharpe)`` to ``robust | fragile |
  overfit`` using the design-08 §2 default thresholds (config-overridable). The
  precedence is **overfit > robust > fragile**: any overfit trigger wins, then a
  fully-robust reading, else fragile.
- :func:`build_validation_report` fuses the T1 (DSR / MinBTL), T3 (per-fold OOS
  metrics) and T4 (PBO) outputs into a populated, design-§3
  :class:`~openbb_backtest.models.ValidationReport`, deriving the verdict and
  recording the *effective* thresholds verbatim so the verdict is auditable.

Default thresholds (design-08 §2):

================  ======  ====================================================
Key               Value   Meaning
================  ======  ====================================================
``pbo_robust``    0.2     PBO must be ``< 0.2`` for ``robust``.
``pbo_overfit``   0.5     PBO ``>= 0.5`` ⇒ ``overfit``.
``dsr_robust``    0.95    DSR must be ``> 0.95`` for ``robust``.
``dsr_overfit``   0.5     DSR ``< 0.5`` ⇒ ``overfit``.
================  ======  ====================================================

See ``docs/designs/backtest-design/08-validation.md`` §2 (verdict table) & §3.
"""

from __future__ import annotations

from openbb_backtest.models import (
    FoldResult,
    PerformanceMetrics,
    ValidationReport,
    Verdict as VerdictLiteral,
)

#: Default, config-overridable verdict thresholds (design-08 §2).
DEFAULT_THRESHOLDS: dict[str, float] = {
    "pbo_robust": 0.2,
    "pbo_overfit": 0.5,
    "dsr_robust": 0.95,
    "dsr_overfit": 0.5,
}


def verdict(
    *,
    pbo: float,
    dsr: float,
    oos_sharpe: float,
    thresholds: dict[str, float] | None = None,
) -> VerdictLiteral:
    """Classify robustness as ``robust | fragile | overfit`` (design-08 §2).

    Precedence is **overfit > robust > fragile**: an ``overfit`` trigger (high
    PBO, low DSR, or non-positive OOS Sharpe) always wins, even when the other
    metrics look robust; otherwise a fully-robust reading (low PBO **and** high
    DSR **and** positive OOS Sharpe) gives ``robust``; anything in between is
    ``fragile``.

    Parameters
    ----------
    pbo
        Probability of Backtest Overfitting in ``[0, 1]``.
    dsr
        Deflated Sharpe Ratio in ``[0, 1]``.
    oos_sharpe
        Aggregated out-of-sample Sharpe ratio.
    thresholds
        Optional overrides merged over :data:`DEFAULT_THRESHOLDS`.

    Returns
    -------
    str
        One of ``"robust"``, ``"fragile"``, ``"overfit"``.
    """
    cut = _effective_thresholds(thresholds)

    # Overfit takes precedence: any single trigger condemns the strategy.
    if pbo >= cut["pbo_overfit"] or dsr < cut["dsr_overfit"] or oos_sharpe <= 0.0:
        return "overfit"
    # Robust requires all three favourable conditions simultaneously.
    if pbo < cut["pbo_robust"] and dsr > cut["dsr_robust"] and oos_sharpe > 0.0:
        return "robust"
    # Everything else is the fragile middle band.
    return "fragile"


def build_validation_report(
    *,
    method: VerdictLiteral | str,
    folds: list[FoldResult],
    oos_metrics: PerformanceMetrics,
    pbo: float,
    deflated_sharpe: float,
    min_backtest_length_years: float,
    thresholds: dict[str, float] | None = None,
) -> ValidationReport:
    """Assemble a populated, design-§3 :class:`ValidationReport`.

    Fuses the precomputed pieces — T3 per-fold OOS ``folds`` + aggregated
    ``oos_metrics``, T4 ``pbo``, and T1 ``deflated_sharpe`` /
    ``min_backtest_length_years`` — and derives the ``verdict`` from
    ``(pbo, deflated_sharpe, oos_metrics.sharpe)`` via :func:`verdict`. The
    *effective* thresholds (defaults merged with any overrides) are recorded
    verbatim on the report so the verdict is auditable.

    Parameters
    ----------
    method
        Resampling method, ``"wfo"`` or ``"cpcv"``.
    folds
        Per-fold out-of-sample results.
    oos_metrics
        Aggregated out-of-sample metrics (its ``sharpe`` drives the verdict).
    pbo, deflated_sharpe, min_backtest_length_years
        The overfitting statistics from components 08.4 / 08.1.
    thresholds
        Optional verdict-threshold overrides.

    Returns
    -------
    ValidationReport
        The fully populated report, including the derived verdict and the
        effective thresholds.
    """
    effective = _effective_thresholds(thresholds)
    decided = verdict(
        pbo=pbo,
        dsr=deflated_sharpe,
        oos_sharpe=oos_metrics.sharpe,
        thresholds=effective,
    )
    return ValidationReport(
        method=method,  # type: ignore[arg-type]  # validated by the model Literal
        folds=folds,
        oos_metrics=oos_metrics,
        pbo=pbo,
        deflated_sharpe=deflated_sharpe,
        min_backtest_length_years=min_backtest_length_years,
        verdict=decided,
        thresholds=effective,
    )


def _effective_thresholds(thresholds: dict[str, float] | None) -> dict[str, float]:
    """Merge caller overrides over :data:`DEFAULT_THRESHOLDS` (defaults win gaps)."""
    merged = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        merged.update(thresholds)
    return merged
