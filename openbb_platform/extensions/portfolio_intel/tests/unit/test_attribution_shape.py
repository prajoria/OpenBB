"""Unit tests for the attribution waterfall response shape (#560).

Pure-shape tests — no math is exercised, only the invariants of the
data model:
  1. ``verify_sums_to_active_return`` enforces
     ``Σ row.total() == portfolio_return - benchmark_return`` within tolerance.
  2. ``verify_aggregates_match_rows`` enforces
     ``total_{allocation,selection,interaction} == Σ row.<field>``.
  3. NaN / Inf on any effect or on the returns raises.
  4. ``AttributionRow.total()`` sums the three effects.
  5. Empty waterfall (no rows) is valid only if
     ``portfolio_return == benchmark_return`` (active return == 0).
  6. Interaction is optional (defaults to 0) and doesn't perturb the
     invariant when unused.

R7.11 note: for each behavioral assertion below, there is a companion
mutation check (introduce a small drift → verify the helper raises).
"""

from __future__ import annotations

import math

import pytest
from openbb_portfolio_intel.analytics.attribution import (
    SUM_INVARIANT_TOLERANCE,
    AttributionRow,
    AttributionWaterfall,
    active_return,
    verify_aggregates_match_rows,
    verify_sums_to_active_return,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plain_waterfall(
    *,
    portfolio_return: float,
    benchmark_return: float,
    rows: list[AttributionRow],
) -> AttributionWaterfall:
    """Build a waterfall with aggregates auto-populated from rows."""
    alloc = sum(r.allocation for r in rows)
    sel = sum(r.selection for r in rows)
    inter = sum(r.interaction for r in rows)
    return AttributionWaterfall(
        window="3M",
        benchmark_symbol="SPY",
        portfolio_return=portfolio_return,
        benchmark_return=benchmark_return,
        rows=rows,
        total_allocation=alloc,
        total_selection=sel,
        total_interaction=inter,
    )


# ---------------------------------------------------------------------------
# AttributionRow.total()
# ---------------------------------------------------------------------------


def test_row_total_sums_three_effects() -> None:
    r = AttributionRow(
        sector="Tech", allocation=0.01, selection=0.005, interaction=0.001
    )
    assert math.isclose(r.total(), 0.016, abs_tol=1e-12)


def test_row_total_defaults_interaction_to_zero() -> None:
    r = AttributionRow(sector="Tech", allocation=0.01, selection=0.005)
    assert r.interaction == 0.0
    assert math.isclose(r.total(), 0.015, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# active_return
# ---------------------------------------------------------------------------


def test_active_return_is_portfolio_minus_benchmark() -> None:
    w = _plain_waterfall(portfolio_return=0.08, benchmark_return=0.05, rows=[])
    # Empty rows OK because active_return happens to be 0.03 — separate
    # invariant test guards the empty-rows sum
    assert math.isclose(active_return(w), 0.03, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# verify_sums_to_active_return — happy path
# ---------------------------------------------------------------------------


def test_verify_happy_path_two_sectors() -> None:
    """Two sectors summing exactly to active return: no raise."""
    rows = [
        AttributionRow("Tech", allocation=0.02, selection=0.01),
        AttributionRow("Financials", allocation=-0.005, selection=0.005),
    ]
    # Σ row.total() = 0.03  → portfolio - benchmark = 0.03
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=rows)
    verify_sums_to_active_return(w)


def test_verify_within_tolerance_is_accepted() -> None:
    """Drift smaller than tolerance is allowed."""
    tiny = SUM_INVARIANT_TOLERANCE / 10  # well inside tolerance
    rows = [AttributionRow("Tech", allocation=0.03 + tiny, selection=0.0)]
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=rows)
    verify_sums_to_active_return(w)  # no raise


def test_verify_interaction_folded_in_when_populated() -> None:
    """A caller reporting interaction separately still satisfies the invariant."""
    rows = [
        AttributionRow("Tech", allocation=0.015, selection=0.010, interaction=0.005),
        AttributionRow(
            "Financials", allocation=0.000, selection=0.000, interaction=0.000
        ),
    ]
    # Σ row.total = 0.030
    w = _plain_waterfall(portfolio_return=0.03, benchmark_return=0.00, rows=rows)
    verify_sums_to_active_return(w)


# ---------------------------------------------------------------------------
# verify_sums_to_active_return — failure paths (R7.11 mutation-verify)
# ---------------------------------------------------------------------------


def test_verify_raises_on_off_by_one_basis_point() -> None:
    """1bp drift is well past tolerance — must raise."""
    rows = [
        AttributionRow("Tech", allocation=0.03 + 1e-4, selection=0.0)
    ]  # 100bp drift
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=rows)
    with pytest.raises(ValueError, match=r"does not sum to active return"):
        verify_sums_to_active_return(w)


def test_verify_raises_when_rows_undershoot() -> None:
    """Rows summing to less than active return → raise."""
    rows = [AttributionRow("Tech", allocation=0.01, selection=0.005)]  # sum=0.015
    w = _plain_waterfall(
        portfolio_return=0.05, benchmark_return=0.02, rows=rows
    )  # active=0.03
    with pytest.raises(ValueError, match=r"drift"):
        verify_sums_to_active_return(w)


def test_verify_raises_on_nan_in_row() -> None:
    rows = [AttributionRow("Tech", allocation=float("nan"), selection=0.03)]
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=rows)
    with pytest.raises(ValueError, match=r"finite"):
        verify_sums_to_active_return(w)


def test_verify_raises_on_inf_in_row() -> None:
    rows = [AttributionRow("Tech", allocation=float("inf"), selection=0.0)]
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=rows)
    with pytest.raises(ValueError, match=r"finite"):
        verify_sums_to_active_return(w)


def test_verify_raises_on_nan_portfolio_return() -> None:
    w = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=float("nan"),
        benchmark_return=0.02,
        rows=[],
    )
    with pytest.raises(ValueError, match=r"finite"):
        verify_sums_to_active_return(w)


# ---------------------------------------------------------------------------
# Empty waterfall (edge case)
# ---------------------------------------------------------------------------


def test_verify_empty_rows_ok_when_active_return_is_zero() -> None:
    """Empty waterfall is valid iff active return is also zero."""
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.05, rows=[])
    verify_sums_to_active_return(w)  # active_return == 0 == Σ empty


def test_verify_empty_rows_raises_when_active_return_nonzero() -> None:
    """Non-zero active return with no rows → invariant violated."""
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.02, rows=[])
    with pytest.raises(ValueError, match=r"does not sum to active return"):
        verify_sums_to_active_return(w)


# ---------------------------------------------------------------------------
# verify_aggregates_match_rows
# ---------------------------------------------------------------------------


def test_aggregates_match_rows_happy_path() -> None:
    """Aggregates populated correctly → no raise."""
    rows = [
        AttributionRow("Tech", allocation=0.02, selection=0.01, interaction=0.001),
        AttributionRow("Financials", allocation=-0.005, selection=0.005),
    ]
    w = _plain_waterfall(portfolio_return=0.031, benchmark_return=0.0, rows=rows)
    verify_aggregates_match_rows(w)


def test_aggregates_stale_allocation_raises() -> None:
    """Producer bug: aggregate doesn't match Σ rows.allocation → raise."""
    rows = [AttributionRow("Tech", allocation=0.02, selection=0.01)]
    w = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.03,
        benchmark_return=0.00,
        rows=rows,
        total_allocation=0.99,  # WRONG
        total_selection=0.01,
        total_interaction=0.0,
    )
    with pytest.raises(ValueError, match=r"total_allocation"):
        verify_aggregates_match_rows(w)


def test_aggregates_stale_selection_raises() -> None:
    rows = [AttributionRow("Tech", allocation=0.02, selection=0.01)]
    w = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.03,
        benchmark_return=0.00,
        rows=rows,
        total_allocation=0.02,
        total_selection=0.99,  # WRONG
        total_interaction=0.0,
    )
    with pytest.raises(ValueError, match=r"total_selection"):
        verify_aggregates_match_rows(w)


def test_aggregates_stale_interaction_raises() -> None:
    rows = [AttributionRow("Tech", allocation=0.02, selection=0.01, interaction=0.005)]
    w = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.035,
        benchmark_return=0.00,
        rows=rows,
        total_allocation=0.02,
        total_selection=0.01,
        total_interaction=0.99,  # WRONG
    )
    with pytest.raises(ValueError, match=r"total_interaction"):
        verify_aggregates_match_rows(w)


# ---------------------------------------------------------------------------
# Shape identity — frozen, defaults, field ordering
# ---------------------------------------------------------------------------


def test_waterfall_is_frozen_dataclass() -> None:
    """AttributionWaterfall is frozen — no accidental in-place mutation."""
    w = _plain_waterfall(portfolio_return=0.05, benchmark_return=0.05, rows=[])
    with pytest.raises(Exception):
        w.portfolio_return = 0.10  # type: ignore[misc]


def test_row_is_frozen_dataclass() -> None:
    r = AttributionRow("Tech", 0.01, 0.005)
    with pytest.raises(Exception):
        r.allocation = 0.99  # type: ignore[misc]


def test_waterfall_defaults() -> None:
    """Aggregates and warnings default to zero / empty."""
    w = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.0,
        benchmark_return=0.0,
    )
    assert w.rows == []
    assert w.warnings == []
    assert w.total_allocation == 0.0
    assert w.total_selection == 0.0
    assert w.total_interaction == 0.0
