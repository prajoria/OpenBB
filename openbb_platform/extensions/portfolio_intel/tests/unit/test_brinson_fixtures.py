"""Tests for the Brinson-Fachler synthetic fixture generator + oracle (#935).

## Two-layer verification

Layer 1: the ORACLE itself is verified against a hand-computed reference
on the golden fixtures. If we can't trust the oracle, we can't use it
to grade #559's production compute_brinson_fachler.

Layer 2: the oracle's own sum invariant — Σ (alloc + sel + inter) ≡
R_p − R_b — must hold algebraically on every generated case. This is
what makes the oracle "obviously correct" — the invariant follows from
the formulas by inspection, and we verify it numerically.

Layer 3 (in test_attribution_compute.py, once #935 lands): parametrized
test that runs compute_brinson_fachler on every SyntheticCase and
asserts within tolerance of oracle_bf. That closes #559's ±1bp
acceptance without Bloomberg.
"""

from __future__ import annotations

import numpy as np
import pytest
from openbb_portfolio_intel.testing import (
    GOLDEN_CASES,
    generate_case,
    iter_random_cases,
    oracle_bf,
)

# Numeric tolerance for the sum-invariant check.
TOL: float = 1e-9


# ---------------------------------------------------------------------------
# Generator — determinism + weight normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 5, 11])
def test_generator_weights_sum_to_one(n: int) -> None:
    case = generate_case(n, seed=42)
    assert case.portfolio_weight.sum() == pytest.approx(1.0, abs=1e-12)
    assert case.benchmark_weight.sum() == pytest.approx(1.0, abs=1e-12)
    assert case.portfolio_weight.shape == (n,)
    assert case.benchmark_weight.shape == (n,)


def test_generator_deterministic_across_calls() -> None:
    a = generate_case(5, seed=7)
    b = generate_case(5, seed=7)
    assert np.array_equal(a.portfolio_weight, b.portfolio_weight)
    assert np.array_equal(a.benchmark_weight, b.benchmark_weight)
    assert np.array_equal(a.portfolio_return, b.portfolio_return)
    assert np.array_equal(a.benchmark_return, b.benchmark_return)


def test_generator_different_seeds_produce_different_cases() -> None:
    a = generate_case(5, seed=7)
    b = generate_case(5, seed=8)
    assert not np.array_equal(a.portfolio_weight, b.portfolio_weight)


def test_generator_rejects_zero_groups() -> None:
    with pytest.raises(ValueError, match=r"n_groups"):
        generate_case(0, seed=1)


# ---------------------------------------------------------------------------
# Oracle sum invariant — the load-bearing check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.label for c in GOLDEN_CASES])
def test_oracle_sum_invariant_holds_on_golden_cases(case) -> None:
    """Σ (alloc + sel + inter) ≡ R_p − R_b on every golden fixture."""
    o = oracle_bf(case)
    total = float((o.allocation + o.selection + o.interaction).sum())
    assert total == pytest.approx(o.total_active_return, abs=TOL)


@pytest.mark.parametrize("i", range(20))
def test_oracle_sum_invariant_holds_on_random_cases(i: int) -> None:
    """Same invariant on 20 random cases across group-size ladder."""
    cases = list(iter_random_cases(n_cases=20, seed_start=0))
    o = oracle_bf(cases[i])
    total = float((o.allocation + o.selection + o.interaction).sum())
    assert total == pytest.approx(o.total_active_return, abs=TOL)


@pytest.mark.parametrize(
    ("label", "allocation", "selection", "interaction", "active_return"),
    [
        ("pure_allocation", [0.0168, 0.0072], [0.0, 0.0], [0.0, 0.0], 0.024),
        ("pure_selection", [0.0, 0.0], [0.02, 0.01], [0.0, 0.0], 0.03),
        (
            "negative_benchmark",
            [0.0066, 0.0054, 0.0],
            [0.015, -0.002, 0.012],
            [-0.003, -0.001, 0.0],
            0.033,
        ),
    ],
)
def test_oracle_matches_hand_calculated_nonzero_references(
    label, allocation, selection, interaction, active_return
) -> None:
    """Validate the oracle against references calculated outside its code path."""
    case = next(c for c in GOLDEN_CASES if c.label == label)
    result = oracle_bf(case)

    np.testing.assert_allclose(result.allocation, allocation, atol=TOL, rtol=0)
    np.testing.assert_allclose(result.selection, selection, atol=TOL, rtol=0)
    np.testing.assert_allclose(result.interaction, interaction, atol=TOL, rtol=0)
    assert result.total_active_return == pytest.approx(active_return, abs=TOL)


# ---------------------------------------------------------------------------
# Oracle behavior on the six §4.2 edge cases
# ---------------------------------------------------------------------------


def test_oracle_identical_case_yields_zero_effects() -> None:
    """portfolio == benchmark → all three effects exactly 0."""
    case = next(c for c in GOLDEN_CASES if c.label == "identical")
    o = oracle_bf(case)
    assert np.allclose(o.allocation, 0)
    assert np.allclose(o.selection, 0)
    assert np.allclose(o.interaction, 0)
    assert o.total_active_return == pytest.approx(0.0, abs=1e-12)


def test_oracle_pure_allocation_case_has_zero_selection() -> None:
    """Same per-group returns → all effect is allocation, selection == 0."""
    case = next(c for c in GOLDEN_CASES if c.label == "pure_allocation")
    o = oracle_bf(case)
    assert np.allclose(o.selection, 0)


def test_oracle_pure_selection_case_has_zero_allocation() -> None:
    """Identical weights → no allocation effect."""
    case = next(c for c in GOLDEN_CASES if c.label == "pure_selection")
    o = oracle_bf(case)
    assert np.allclose(o.allocation, 0)
    assert np.allclose(o.interaction, 0)


def test_oracle_negative_benchmark_case_produces_signed_effects() -> None:
    """Some groups negative → mixed signs across effects. Just check finite."""
    case = next(c for c in GOLDEN_CASES if c.label == "negative_benchmark")
    o = oracle_bf(case)
    assert np.all(np.isfinite(o.allocation))
    assert np.all(np.isfinite(o.selection))
    assert np.all(np.isfinite(o.interaction))


def test_oracle_empty_portfolio_sector_still_satisfies_invariant() -> None:
    """A zero portfolio weight in one group is allowed; invariant still holds."""
    case = next(c for c in GOLDEN_CASES if c.label == "empty_portfolio_sector")
    o = oracle_bf(case)
    total = float((o.allocation + o.selection + o.interaction).sum())
    assert total == pytest.approx(o.total_active_return, abs=TOL)


# ---------------------------------------------------------------------------
# Cross-check against production compute_brinson_fachler (#559)
# ---------------------------------------------------------------------------
#
# This closes the loop: production and oracle must agree on every fixture
# to within tolerance_bps. Failure = production impl regression.


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.label for c in GOLDEN_CASES])
def test_compute_bf_matches_oracle_on_golden_cases(case) -> None:
    """compute_brinson_fachler and oracle_bf agree on every golden fixture."""
    from openbb_portfolio_intel.analytics.attribution import (  # noqa: PLC0415
        SectorReturns,
        compute_brinson_fachler,
    )

    o = oracle_bf(case)
    sectors = [
        SectorReturns(
            sector=case.group_names[i],
            portfolio_weight=float(case.portfolio_weight[i]),
            portfolio_return=float(case.portfolio_return[i]),
            benchmark_weight=float(case.benchmark_weight[i]),
            benchmark_return=float(case.benchmark_return[i]),
        )
        for i in range(len(case.group_names))
    ]
    result = compute_brinson_fachler(sectors, window="synth", benchmark_symbol="SYNTH")
    # Sum sanity — production already asserts this internally, but explicit.
    row_sum = sum(r.allocation + r.selection + r.interaction for r in result.rows)
    assert row_sum == pytest.approx(o.total_active_return, abs=TOL)

    # Per-group cross-check
    for i, row in enumerate(result.rows):
        assert row.allocation == pytest.approx(float(o.allocation[i]), abs=TOL)
        assert row.selection == pytest.approx(float(o.selection[i]), abs=TOL)
        assert row.interaction == pytest.approx(float(o.interaction[i]), abs=TOL)


@pytest.mark.parametrize("i", range(20))
def test_compute_bf_matches_oracle_on_random_cases(i: int) -> None:
    """Same cross-check on 20 random cases — closes #559 acceptance."""
    from openbb_portfolio_intel.analytics.attribution import (  # noqa: PLC0415
        SectorReturns,
        compute_brinson_fachler,
    )

    cases = list(iter_random_cases(n_cases=20, seed_start=0))
    case = cases[i]
    o = oracle_bf(case)
    sectors = [
        SectorReturns(
            sector=case.group_names[j],
            portfolio_weight=float(case.portfolio_weight[j]),
            portfolio_return=float(case.portfolio_return[j]),
            benchmark_weight=float(case.benchmark_weight[j]),
            benchmark_return=float(case.benchmark_return[j]),
        )
        for j in range(len(case.group_names))
    ]
    result = compute_brinson_fachler(sectors, window="synth", benchmark_symbol="SYNTH")
    for j, row in enumerate(result.rows):
        assert row.allocation == pytest.approx(float(o.allocation[j]), abs=TOL)
        assert row.selection == pytest.approx(float(o.selection[j]), abs=TOL)
        assert row.interaction == pytest.approx(float(o.interaction[j]), abs=TOL)
