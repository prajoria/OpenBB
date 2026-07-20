"""Unit tests for Brinson-Fachler compute (#559).

The algorithm's load-bearing correctness check is the sum invariant:
Σ (allocation + selection + interaction) ≡ portfolio_return − benchmark_return.
By the algebra of Brinson-Fachler, this always holds when the formulas
are implemented correctly. compute_brinson_fachler calls
verify_sums_to_active_return before returning; if a maintainer breaks
the formulas, the verify raises.

The ±1bp Bloomberg acceptance criterion from the #559 body is deferred
to a follow-up once #557 (Bloomberg reference fixtures) lands. A
@pytest.mark.integration placeholder documents the gap.
"""

from __future__ import annotations

import math

import pytest
from openbb_portfolio_intel.analytics.attribution import (
    AttributionWaterfall,
    SectorReturns,
    compute_brinson_fachler,
    verify_sums_to_active_return,
)

# ---------------------------------------------------------------------------
# Happy path — sum invariant + envelope shape
# ---------------------------------------------------------------------------


def test_compute_returns_waterfall_shape() -> None:
    sectors = [
        SectorReturns("Tech", 0.5, 0.10, 0.4, 0.08),
        SectorReturns("Financials", 0.5, 0.02, 0.6, 0.03),
    ]
    result = compute_brinson_fachler(sectors, window="3M", benchmark_symbol="SPY")
    assert isinstance(result, AttributionWaterfall)
    assert result.window == "3M"
    assert result.benchmark_symbol == "SPY"
    assert len(result.rows) == 2
    assert {r.sector for r in result.rows} == {"Tech", "Financials"}


def test_compute_populates_provenance_warning() -> None:
    sectors = [SectorReturns("Tech", 1.0, 0.05, 1.0, 0.03)]
    result = compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")
    assert any("brinson-fachler" in w.lower() for w in result.warnings)
    # Explicit pointer to the Bloomberg-blocked acceptance criterion
    assert any("#557" in w for w in result.warnings)


def test_compute_sum_invariant_holds_by_construction() -> None:
    """The whole point: Σ (alloc + sel + inter) ≡ portfolio - benchmark_return."""
    sectors = [
        SectorReturns("Tech", 0.35, 0.12, 0.30, 0.10),
        SectorReturns("Financials", 0.25, 0.03, 0.20, 0.02),
        SectorReturns("Energy", 0.15, -0.05, 0.20, -0.03),
        SectorReturns("Healthcare", 0.15, 0.06, 0.15, 0.04),
        SectorReturns("Consumer", 0.10, 0.08, 0.15, 0.05),
    ]
    result = compute_brinson_fachler(sectors, window="6M", benchmark_symbol="ACWI")
    # Redundant with the verify inside compute, but explicit here so the
    # test file itself documents the load-bearing invariant.
    verify_sums_to_active_return(result)
    row_sum = sum(r.total() for r in result.rows)
    active = result.portfolio_return - result.benchmark_return
    assert math.isclose(row_sum, active, rel_tol=1e-9, abs_tol=1e-12)


def test_compute_totals_agree_with_row_sums() -> None:
    sectors = [
        SectorReturns("A", 0.5, 0.10, 0.4, 0.08),
        SectorReturns("B", 0.5, 0.02, 0.6, 0.03),
    ]
    result = compute_brinson_fachler(sectors, window="3M", benchmark_symbol="SPY")
    assert math.isclose(
        result.total_allocation, sum(r.allocation for r in result.rows), rel_tol=1e-12
    )
    assert math.isclose(
        result.total_selection, sum(r.selection for r in result.rows), rel_tol=1e-12
    )
    assert math.isclose(
        result.total_interaction,
        sum(r.interaction for r in result.rows),
        rel_tol=1e-12,
    )


# ---------------------------------------------------------------------------
# Sign-convention property tests — allocation/selection interpretation
# ---------------------------------------------------------------------------


def test_pure_overweight_of_outperforming_sector_gives_positive_allocation() -> None:
    """Overweight a sector that beats the benchmark → positive allocation.

    Setup: Tech return 10%, Financials return 0%. Benchmark 50/50, so
    R_b = 5%. Portfolio overweights Tech at 80% and underweights
    Financials at 20%. With sector returns identical to benchmark
    on each side (r_p_i = r_b_i), selection is 0 for both sectors and
    all of the active return comes from allocation.
    """
    sectors = [
        SectorReturns("Tech", 0.80, 0.10, 0.5, 0.10),
        SectorReturns("Financials", 0.20, 0.00, 0.5, 0.00),
    ]
    result = compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")
    tech = next(r for r in result.rows if r.sector == "Tech")
    fin = next(r for r in result.rows if r.sector == "Financials")
    # Tech: (0.8-0.5) * (0.10-0.05) = 0.3 * 0.05 = 0.015
    assert math.isclose(tech.allocation, 0.015, abs_tol=1e-9)
    # Selection zero (same per-sector return on both sides)
    assert math.isclose(tech.selection, 0.0, abs_tol=1e-9)
    assert math.isclose(fin.selection, 0.0, abs_tol=1e-9)


def test_pure_selection_when_weights_match_benchmark() -> None:
    """Weights identical to benchmark → allocation = 0, all effect is selection.

    Setup: 50/50 weights on both sides, but portfolio picks better Tech
    names (12% vs 10%) and worse Financials (1% vs 3%).
    """
    sectors = [
        SectorReturns("Tech", 0.5, 0.12, 0.5, 0.10),
        SectorReturns("Financials", 0.5, 0.01, 0.5, 0.03),
    ]
    result = compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")
    for row in result.rows:
        assert math.isclose(
            row.allocation, 0.0, abs_tol=1e-9
        ), "matched weights → zero allocation on every sector"
        assert math.isclose(
            row.interaction, 0.0, abs_tol=1e-9
        ), "matched weights → zero interaction on every sector"
    tech = next(r for r in result.rows if r.sector == "Tech")
    fin = next(r for r in result.rows if r.sector == "Financials")
    # Tech selection: 0.5 * (0.12-0.10) = 0.01
    assert math.isclose(tech.selection, 0.01, abs_tol=1e-9)
    # Financials selection: 0.5 * (0.01-0.03) = -0.01
    assert math.isclose(fin.selection, -0.01, abs_tol=1e-9)


def test_no_active_bet_gives_zero_active_return() -> None:
    """Portfolio == benchmark → active return exactly zero."""
    sectors = [
        SectorReturns("Tech", 0.5, 0.10, 0.5, 0.10),
        SectorReturns("Fin", 0.5, 0.03, 0.5, 0.03),
    ]
    result = compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")
    assert math.isclose(result.portfolio_return, result.benchmark_return, abs_tol=1e-12)
    for row in result.rows:
        assert math.isclose(row.allocation, 0.0, abs_tol=1e-12)
        assert math.isclose(row.selection, 0.0, abs_tol=1e-12)
        assert math.isclose(row.interaction, 0.0, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_empty_sector_list_raises() -> None:
    with pytest.raises(ValueError, match=r"empty"):
        compute_brinson_fachler([], window="1M", benchmark_symbol="SPY")


def test_nan_input_raises() -> None:
    sectors = [SectorReturns("Tech", 0.5, float("nan"), 0.5, 0.05)]
    with pytest.raises(ValueError, match=r"not finite"):
        compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")


def test_inf_input_raises() -> None:
    sectors = [SectorReturns("Tech", 0.5, float("inf"), 0.5, 0.05)]
    with pytest.raises(ValueError, match=r"not finite"):
        compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")


def test_negative_weight_raises() -> None:
    sectors = [
        SectorReturns("Tech", -0.1, 0.05, 0.5, 0.05),
        SectorReturns("Fin", 1.1, 0.03, 0.5, 0.03),
    ]
    with pytest.raises(ValueError, match=r"negative"):
        compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")


def test_weights_not_summing_to_one_raises() -> None:
    sectors = [
        SectorReturns("Tech", 0.3, 0.10, 0.5, 0.08),
        SectorReturns("Fin", 0.3, 0.02, 0.5, 0.03),
    ]
    with pytest.raises(ValueError, match=r"weights sum"):
        compute_brinson_fachler(sectors, window="1M", benchmark_symbol="SPY")


# ---------------------------------------------------------------------------
# R7.11 reverse-verify — mutate the formula, watch the invariant fire
# ---------------------------------------------------------------------------


def test_r711_broken_allocation_formula_would_fail_verify() -> None:
    """Prove verify_sums_to_active_return is load-bearing.

    Build a manually-perturbed result (as if the allocation formula
    were broken) and confirm verify_sums_to_active_return raises. This
    guards the invariant test that lives inside compute_brinson_fachler.
    """
    from openbb_portfolio_intel.analytics.attribution import AttributionRow

    # Real portfolio_return / benchmark_return, but rows deliberately off
    # by 100bp on allocation.
    result = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.05,
        benchmark_return=0.03,  # active return = 0.02
        rows=[
            AttributionRow("Tech", allocation=0.01 + 0.01, selection=0.0),
            AttributionRow("Fin", allocation=0.0, selection=0.0),
        ],  # Σ = 0.02 + 0 = 0.02 ... this DOES sum correctly, need harder mutation
    )
    # This particular fixture happens to sum right; construct one that
    # DOESN'T:
    result_bad = AttributionWaterfall(
        window="1M",
        benchmark_symbol="SPY",
        portfolio_return=0.05,
        benchmark_return=0.03,
        rows=[
            AttributionRow("Tech", allocation=0.005, selection=0.0),
            AttributionRow("Fin", allocation=0.0, selection=0.0),
        ],  # Σ = 0.005, active = 0.02 → 150bp drift
    )
    with pytest.raises(ValueError, match=r"does not sum to active return"):
        verify_sums_to_active_return(result_bad)


# ---------------------------------------------------------------------------
# ±1bp Bloomberg acceptance — placeholder (blocked by #557)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_bloomberg_reference_matches_within_1bp() -> None:
    """Placeholder for the #559 acceptance criterion.

    Skipped today because Bloomberg reference fixtures (#557) are not
    yet available. When #557 lands, this test loads the fixture and
    asserts every per-sector (allocation, selection) matches Bloomberg
    to ±1bp. Marked ``integration`` so unit-only CI still passes.
    """
    pytest.skip(
        "Bloomberg reference fixtures blocked by #557; will unblock when "
        "reference values land under tests/fixtures/brinson/."
    )
