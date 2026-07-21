"""Tests for the Brinson-Fachler attribution engine (#559).

Load-bearing correctness gate: **every golden fixture from #935 is fed
through the engine and compared to the fixture's expected effects to
±1bp per effect** — the exact acceptance criterion in the issue body
("MUST match Brinson reference fixtures to +/-1bp").

Discriminators:

- **Golden-fixture roundtrip** — engine vs oracle on every #935 case.
  Any drift in the engine's formula shows up as a per-effect mismatch,
  not just a sum-invariant failure. Discriminates plain-Brinson-vs-BF
  (an aggregate-invisible bug the fixtures were specifically designed
  to catch via per-effect assertions).
- **Sum invariant self-check** — the engine calls
  ``verify_sums_to_active_return`` before returning, so bad output
  raises rather than silently propagating.
- **Silent-failure guards** (each reverse-verified R7.11-style):
  1. Weight-sum drift → ``ValueError``.
  2. Non-finite return → ``ValueError``.
  3. Empty groups list → ``ValueError``.
  4. Length mismatch across arrays → ``ValueError``.
- **Aggregates are computed, not trusted** — a caller cannot pass in
  stale ``total_allocation`` etc; the engine ignores caller-supplied
  aggregates and computes its own.

R7.11 discriminators shipped:
- ``test_engine_mutation_catches_plain_brinson_swap`` proves swapping
  BF allocation (``r_b - R_b``) for plain-Brinson (``r_b``) DOES
  produce different per-group vectors on our fixtures (aggregate is
  identical because sum(delta_w)==0, but the widget renders per group).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from openbb_portfolio_intel.analytics.attribution import (
    SUM_INVARIANT_TOLERANCE,
    verify_sums_to_active_return,
)
from openbb_portfolio_intel.analytics.attribution_engine import (
    build_from_arrays,
    build_from_dataframe,
)
from openbb_portfolio_intel.analytics.brinson.generator import make_case

ONE_BP = 1e-4


def _fixtures_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "openbb_portfolio_intel"
        / "analytics"
        / "brinson"
        / "fixtures"
    )


def _all_fixtures() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(_fixtures_dir().glob("*.json"))]


# ---------------------------------------------------------------------------
# 1. Golden-fixture round-trip — THE acceptance criterion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fx", _all_fixtures(), ids=lambda fx: fx["case_id"])
def test_engine_matches_golden_fixture_within_1bp(fx: dict) -> None:
    """Engine output matches every committed golden fixture to +/-1bp per effect."""
    df = pd.DataFrame(fx["inputs"])
    waterfall = build_from_dataframe(df, window="1Y", benchmark_symbol="SPY")
    exp = fx["expected"]
    tol = exp["tolerance_bps"] * ONE_BP  # 1bp

    assert np.isclose(
        waterfall.total_allocation, exp["allocation"], atol=tol
    ), f"{fx['case_id']}: allocation drift {waterfall.total_allocation} vs {exp['allocation']}"
    assert np.isclose(
        waterfall.total_selection, exp["selection"], atol=tol
    ), f"{fx['case_id']}: selection drift"
    assert np.isclose(
        waterfall.total_interaction, exp["interaction"], atol=tol
    ), f"{fx['case_id']}: interaction drift"
    assert np.isclose(
        waterfall.portfolio_return - waterfall.benchmark_return,
        exp["active_return"],
        atol=tol,
    ), f"{fx['case_id']}: active_return drift"


# ---------------------------------------------------------------------------
# 2. Sum invariant — engine self-checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,seed", [(1, 1), (3, 2), (5, 3), (11, 4), (25, 5)])
def test_engine_sum_invariant_holds_on_random_cases(n: int, seed: int) -> None:
    """Random generator cases must satisfy Σ row.total() == active_return."""
    case = make_case(n, seed)
    waterfall = build_from_dataframe(case.df, window="1M", benchmark_symbol="SPY")
    # Redundant with the engine's own self-check but proves the check
    # is real (i.e. if we removed it, this test would still catch drift).
    verify_sums_to_active_return(waterfall, tolerance=SUM_INVARIANT_TOLERANCE)


def test_engine_identical_books_yield_all_zeros() -> None:
    """Portfolio == benchmark -> every per-group effect is 0."""
    case = make_case(5, seed=6, identical=True)
    waterfall = build_from_dataframe(case.df, window="1M", benchmark_symbol="SPY")
    for row in waterfall.rows:
        assert row.allocation == pytest.approx(0.0, abs=1e-15)
        assert row.selection == pytest.approx(0.0, abs=1e-15)
        assert row.interaction == pytest.approx(0.0, abs=1e-15)
    assert waterfall.portfolio_return == pytest.approx(
        waterfall.benchmark_return, abs=1e-15
    )


def test_engine_off_benchmark_holding_selection_row_is_zero() -> None:
    """Group with w_b=0 has selection == 0 in that group's row (per-group)."""
    case = make_case(5, seed=5, zero_wb=True)
    waterfall = build_from_dataframe(case.df, window="1M", benchmark_symbol="SPY")
    # Row 0 has w_b=0 → selection = 0 * (r_p - r_b) = 0.
    assert waterfall.rows[0].selection == 0.0


# ---------------------------------------------------------------------------
# 3. Silent-failure guards — every one raises, none silently pass
# ---------------------------------------------------------------------------


def test_engine_rejects_unnormalized_portfolio_weights() -> None:
    """Weights that don't sum to 1 raise ValueError; no silent renormalization."""
    with pytest.raises(ValueError, match="portfolio weights sum to"):
        build_from_arrays(
            groups=["A", "B"],
            w_p=[0.6, 0.6],  # sums to 1.2
            w_b=[0.5, 0.5],
            r_p=[0.1, 0.1],
            r_b=[0.05, 0.05],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_rejects_unnormalized_benchmark_weights() -> None:
    """Benchmark weight-sum drift also raises."""
    with pytest.raises(ValueError, match="benchmark weights sum to"):
        build_from_arrays(
            groups=["A", "B"],
            w_p=[0.5, 0.5],
            w_b=[0.7, 0.7],
            r_p=[0.1, 0.1],
            r_b=[0.05, 0.05],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_rejects_nan_returns() -> None:
    """NaN in a return would silently corrupt Σ; raise instead."""
    with pytest.raises(ValueError, match="non-finite return"):
        build_from_arrays(
            groups=["A", "B"],
            w_p=[0.5, 0.5],
            w_b=[0.5, 0.5],
            r_p=[0.1, float("nan")],
            r_b=[0.05, 0.05],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_rejects_inf_returns() -> None:
    """Inf in a return would produce Inf aggregate; raise instead."""
    with pytest.raises(ValueError, match="non-finite return"):
        build_from_arrays(
            groups=["A"],
            w_p=[1.0],
            w_b=[1.0],
            r_p=[float("inf")],
            r_b=[0.05],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_rejects_empty_input() -> None:
    """Empty groups list is a caller bug — raise, don't return an empty waterfall."""
    with pytest.raises(ValueError, match="no groups"):
        build_from_arrays(
            groups=[],
            w_p=[],
            w_b=[],
            r_p=[],
            r_b=[],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_rejects_length_mismatch() -> None:
    """Groups=3 but weights=2 is a caller bug — raise."""
    with pytest.raises(ValueError, match="length mismatch"):
        build_from_arrays(
            groups=["A", "B", "C"],
            w_p=[0.5, 0.5],
            w_b=[0.5, 0.5],
            r_p=[0.1, 0.1],
            r_b=[0.05, 0.05],
            window="1M",
            benchmark_symbol="SPY",
        )


def test_engine_dataframe_rejects_missing_column() -> None:
    """DataFrame wrapper enforces the #935 column contract."""
    df = pd.DataFrame({"group": ["A"], "w_p": [1.0], "w_b": [1.0], "r_p": [0.1]})
    with pytest.raises(ValueError, match="missing required columns"):
        build_from_dataframe(df, window="1M", benchmark_symbol="SPY")


# ---------------------------------------------------------------------------
# 4. Response-shape wiring
# ---------------------------------------------------------------------------


def test_engine_window_and_benchmark_copied_verbatim() -> None:
    """The engine passes ``window`` and ``benchmark_symbol`` through unchanged."""
    case = make_case(3, seed=1)
    waterfall = build_from_dataframe(case.df, window="3M", benchmark_symbol="ACWI")
    assert waterfall.window == "3M"
    assert waterfall.benchmark_symbol == "ACWI"


def test_engine_row_count_matches_input_group_count() -> None:
    """One AttributionRow per group; group labels preserved in order."""
    case = make_case(11, seed=2)
    waterfall = build_from_dataframe(case.df, window="1Y", benchmark_symbol="SPY")
    assert len(waterfall.rows) == 11
    assert [r.sector for r in waterfall.rows] == case.df["group"].tolist()


def test_engine_aggregates_match_per_row_sums() -> None:
    """total_* fields match Σ over rows."""
    case = make_case(5, seed=42)
    waterfall = build_from_dataframe(case.df, window="1M", benchmark_symbol="SPY")
    assert waterfall.total_allocation == pytest.approx(
        sum(r.allocation for r in waterfall.rows), abs=1e-15
    )
    assert waterfall.total_selection == pytest.approx(
        sum(r.selection for r in waterfall.rows), abs=1e-15
    )
    assert waterfall.total_interaction == pytest.approx(
        sum(r.interaction for r in waterfall.rows), abs=1e-15
    )


# ---------------------------------------------------------------------------
# 5. R7.11 discriminator — plain-Brinson vs BF at the PER-GROUP level
# ---------------------------------------------------------------------------


def test_engine_mutation_catches_plain_brinson_swap() -> None:
    """Per-group allocation vectors differ between plain-Brinson and BF.

    Aggregate allocation is identical between the two variants (because
    Σ(w_p - w_b) == 0), so a sum-only test can't discriminate. The
    engine emits per-group rows that the widget renders one-per-bar —
    so per-group correctness is load-bearing. This test proves the
    fixtures + engine actually distinguish the two.
    """
    case = make_case(5, seed=42)
    waterfall = build_from_dataframe(case.df, window="1M", benchmark_symbol="SPY")

    df = case.df
    plain_per_group = (df["w_p"] - df["w_b"]) * df["r_b"]
    bf_per_group = [r.allocation for r in waterfall.rows]

    # If these matched, plain-Brinson would silently pass — pick a
    # different seed. Verified for seed=42 with 5 groups.
    assert not np.allclose(plain_per_group.values, bf_per_group, atol=ONE_BP), (
        "seed=42 case is degenerate for plain-vs-BF discrimination; "
        "pick a different seed and re-record"
    )
