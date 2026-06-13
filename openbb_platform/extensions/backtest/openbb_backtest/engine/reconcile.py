"""Engine reconciliation gate (component 04, §3).

The automatic correctness check that lets the fast vectorized engine be trusted:
run a single baseline config through two engines and assert their equity curves
agree within ``reconcile_tolerance`` (default ``1e-6``). A failure flags a
look-ahead leak or a cost-model divergence between the engines.

This module is engine-agnostic — it depends only on the
:class:`~openbb_backtest.interfaces.Engine` protocol and the canonical
:class:`~openbb_backtest.models.BacktestResult` — so it reconciles the
vectorized engine against the event-driven engine (component 05) without
importing either concretely.

See ``docs/designs/backtest-design/04-vectorized-engine.md`` §3.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from openbb_backtest.interfaces import Broker, DataFeed, Engine, Strategy
from openbb_backtest.models import BacktestConfig, BacktestResult
from openbb_backtest.settings import DEFAULT_SETTINGS


class ReconciliationError(AssertionError):
    """Raised in strict mode when two engines diverge beyond tolerance."""


@dataclass
class ReconciliationReport:
    """Outcome of a reconciliation run between two engines."""

    passed: bool
    max_divergence: float
    tolerance: float
    reference_engine: str
    candidate_engine: str


def equity_array(result: BacktestResult) -> np.ndarray:
    """Extract the equity curve of ``result`` as a float array."""
    return np.array([float(p.equity) for p in result.equity_curve], dtype=float)


def max_equity_divergence(
    reference: BacktestResult, candidate: BacktestResult
) -> float:
    """Largest absolute equity difference between two results, point for point.

    Curves of unequal length are compared over their overlapping prefix and the
    surplus tail counts as full divergence, so a truncated curve never passes by
    omission.
    """
    a = equity_array(reference)
    b = equity_array(candidate)
    n = min(a.shape[0], b.shape[0])
    if n == 0:
        return float("inf") if (a.shape[0] or b.shape[0]) else 0.0
    diff = float(np.max(np.abs(a[:n] - b[:n])))
    if a.shape[0] != b.shape[0]:
        longer = a if a.shape[0] > b.shape[0] else b
        diff = max(diff, float(np.max(np.abs(longer[n:]))))
    return diff


def reconcile(
    reference: Engine,
    candidate: Engine,
    strategy: Strategy,
    config: BacktestConfig,
    feed: DataFeed,
    broker: Broker,
    tolerance: float | None = None,
    strict: bool = False,
) -> ReconciliationReport:
    """Run ``strategy`` through both engines and compare their equity curves.

    ``reference`` is the source of truth (the event-driven engine in production);
    ``candidate`` is the fast engine under test. Returns a
    :class:`ReconciliationReport`; when ``strict`` is set, a divergence beyond
    ``tolerance`` raises :class:`ReconciliationError` instead.
    """
    tol = DEFAULT_SETTINGS.reconcile_tolerance if tolerance is None else tolerance
    ref_result = reference.run(strategy, config, feed, broker)
    cand_result = candidate.run(strategy, config, feed, broker)
    divergence = max_equity_divergence(ref_result, cand_result)
    passed = divergence <= tol
    report = ReconciliationReport(
        passed=passed,
        max_divergence=divergence,
        tolerance=tol,
        reference_engine=reference.name,
        candidate_engine=candidate.name,
    )
    if strict and not passed:
        raise ReconciliationError(
            f"engines diverged: max|Δequity|={divergence:.6g} > tol={tol:.6g} "
            f"({reference.name} vs {candidate.name})"
        )
    return report
