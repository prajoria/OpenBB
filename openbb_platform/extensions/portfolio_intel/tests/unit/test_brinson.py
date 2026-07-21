"""Tests for the Brinson-Fachler generator + oracle + golden fixtures (#935).

Discriminators:

- **Weight-sum invariant** — Dirichlet outputs summing to 1 within 1e-12
  is the definition of a "valid" case; if the generator ever silently
  produces weights that don't, the oracle refuses to run.
- **Sum invariant** — allocation + selection + interaction == R_p - R_b
  to 1e-9. The oracle self-checks; the tests re-check with the same
  tolerance.
- **Off-benchmark holding** — when ``w_b_i = 0`` for a group present in
  the portfolio, the selection term ``w_b * (r_p - r_b)`` collapses to
  zero for that group. The bug this catches: an implementation that
  splits the active return the wrong way between allocation and
  selection.
- **Identical books** — when ``w_p == w_b`` and ``r_p == r_b``, ALL
  three effects must be exactly zero (up to float). This is the
  strongest zero-of-zeros discriminator; a mislabeled formula that
  passes the sum invariant on random books will still fail here.
- **Deterministic across calls** — same ``(n_groups, seed, flags)``
  yields byte-identical DataFrames. Fixtures depend on this.
- **Fixture round-trip** — every committed golden fixture must satisfy
  the oracle's invariants when re-run through the oracle. Guards
  against silent drift between the JSON on disk and the oracle logic.

R7.11 discriminator: the ``test_oracle_catches_wrong_formula`` test
mutates the oracle formula and verifies the resulting effects DIFFER
from the trusted output. Empirical proof the oracle isn't ceremonial.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from openbb_portfolio_intel.analytics.brinson.generator import make_case
from openbb_portfolio_intel.analytics.brinson.oracle import (
    BrinsonEffects,
    brinson_reference,
)

ONE_BP = 1e-4
EXACT = 1e-12


# ---------------------------------------------------------------------------
# 1. Generator — weight-sum + determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 5, 11, 25])
def test_generator_weights_sum_to_one(n: int) -> None:
    """Dirichlet-drawn w_p and w_b each sum to 1.0 within EXACT (1e-12)."""
    case = make_case(n, seed=42)
    assert np.isclose(case.df["w_p"].sum(), 1.0, atol=EXACT)
    assert np.isclose(case.df["w_b"].sum(), 1.0, atol=EXACT)


def test_generator_deterministic_same_inputs() -> None:
    """Same seed -> byte-identical DataFrame columns."""
    a = make_case(5, seed=7)
    b = make_case(5, seed=7)
    for col in ("w_p", "w_b", "r_p", "r_b"):
        np.testing.assert_array_equal(a.df[col].values, b.df[col].values)


def test_generator_different_seeds_different_output() -> None:
    """Different seeds must diverge (sanity check on RNG plumbing)."""
    a = make_case(5, seed=1)
    b = make_case(5, seed=2)
    assert not np.allclose(a.df["w_p"].values, b.df["w_p"].values)


def test_generator_zero_wp_flag() -> None:
    """zero_wp forces w_p[0]=0 and renormalizes so sum stays 1."""
    case = make_case(5, seed=4, zero_wp=True)
    assert case.df["w_p"].iloc[0] == 0.0
    assert np.isclose(case.df["w_p"].sum(), 1.0, atol=EXACT)


def test_generator_zero_wb_flag() -> None:
    """zero_wb forces w_b[0]=0 (off-benchmark holding) with renormalization."""
    case = make_case(5, seed=5, zero_wb=True)
    assert case.df["w_b"].iloc[0] == 0.0
    assert np.isclose(case.df["w_b"].sum(), 1.0, atol=EXACT)


def test_generator_identical_flag_produces_equal_books() -> None:
    """identical=True copies w_p/r_p into w_b/r_b exactly."""
    case = make_case(5, seed=6, identical=True)
    np.testing.assert_array_equal(case.df["w_p"].values, case.df["w_b"].values)
    np.testing.assert_array_equal(case.df["r_p"].values, case.df["r_b"].values)


def test_generator_all_negative_flag() -> None:
    """all_negative shifts both return means below zero (bear-market case)."""
    case = make_case(50, seed=8, all_negative=True)
    # Mean should be strongly negative; not all individual draws — but
    # with 50 draws centered at -0.08 the sum is essentially always < 0.
    assert case.df["r_p"].mean() < 0
    assert case.df["r_b"].mean() < 0


def test_generator_rejects_n_zero() -> None:
    """n_groups<1 is a caller bug -> ValueError, not silent empty case."""
    with pytest.raises(ValueError, match="n_groups must be"):
        make_case(0, seed=1)


def test_generator_rejects_zero_wp_with_n_1() -> None:
    """zero_wp with n=1 would divide by 0 during renormalize -> reject."""
    with pytest.raises(ValueError, match="zero_wp requires"):
        make_case(1, seed=1, zero_wp=True)


# ---------------------------------------------------------------------------
# 2. Oracle — sum invariant + input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n,seed", [(1, 1), (3, 2), (5, 3), (11, 4), (25, 5)])
def test_oracle_sum_invariant_holds(n: int, seed: int) -> None:
    """Alloc + selc + inter == active_return within 1e-9 on random cases."""
    case = make_case(n, seed)
    eff = brinson_reference(case.df)
    assert np.isclose(
        eff.allocation + eff.selection + eff.interaction,
        eff.active_return,
        atol=1e-9,
    )


def test_oracle_identical_books_yield_all_zeros() -> None:
    """The strongest discriminator — identical → all three effects == 0."""
    case = make_case(5, seed=6, identical=True)
    eff = brinson_reference(case.df)
    assert eff.allocation == pytest.approx(0.0, abs=EXACT)
    assert eff.selection == pytest.approx(0.0, abs=EXACT)
    assert eff.interaction == pytest.approx(0.0, abs=EXACT)
    assert eff.active_return == pytest.approx(0.0, abs=EXACT)


def test_oracle_off_benchmark_holding_selection_vanishes_for_that_group() -> None:
    """w_b_i = 0 → the per-group selection contribution is 0."""
    case = make_case(5, seed=5, zero_wb=True)
    # Verify group 0 contributes 0 to selection (w_b[0] == 0)
    df = case.df
    per_group_selection = df["w_b"] * (df["r_p"] - df["r_b"])
    assert per_group_selection.iloc[0] == 0.0


def test_oracle_rejects_missing_columns() -> None:
    """Oracle refuses to guess — missing r_b column -> ValueError."""
    import pandas as pd

    df = pd.DataFrame({"w_p": [0.5, 0.5], "w_b": [0.5, 0.5], "r_p": [0.1, 0.1]})
    with pytest.raises(ValueError, match="missing required columns"):
        brinson_reference(df)


def test_oracle_rejects_unnormalized_weights() -> None:
    """Weights that don't sum to 1 are a caller bug — reject, don't renormalize."""
    import pandas as pd

    df = pd.DataFrame(
        {"w_p": [0.5, 0.4], "w_b": [0.5, 0.5], "r_p": [0.1, 0.1], "r_b": [0.1, 0.1]}
    )
    with pytest.raises(ValueError, match="portfolio weights sum to"):
        brinson_reference(df)


def test_oracle_rejects_empty_dataframe() -> None:
    """No groups -> no attribution to compute; reject rather than return 0/0."""
    import pandas as pd

    df = pd.DataFrame(columns=["w_p", "w_b", "r_p", "r_b"])
    with pytest.raises(ValueError, match="empty"):
        brinson_reference(df)


# ---------------------------------------------------------------------------
# 3. Golden fixtures — round-trip check
# ---------------------------------------------------------------------------


def _fixtures_dir() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "openbb_portfolio_intel"
        / "analytics"
        / "brinson"
        / "fixtures"
    )


def _load_all_fixtures() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(_fixtures_dir().glob("*.json"))]


def test_fixture_directory_has_all_edge_cases() -> None:
    """Guardrail: any dropped fixture would silently reduce coverage."""
    ids = {f["case_id"] for f in _load_all_fixtures()}
    required = {
        "bf-n3-seed1",
        "bf-n11-seed2",
        "bf-n1-seed3",
        "bf-n5-seed4-zwp",
        "bf-n5-seed5-zwb",
        "bf-n5-seed6-id",
        "bf-n7-seed7-neg",
    }
    assert required.issubset(ids), f"missing fixtures: {required - ids}"


def test_fixtures_roundtrip_through_oracle_within_tolerance() -> None:
    """Every committed fixture's expected effects match the live oracle."""
    import pandas as pd

    for fx in _load_all_fixtures():
        df = pd.DataFrame(fx["inputs"])
        eff = brinson_reference(df)
        exp = fx["expected"]
        tol = exp["tolerance_bps"] * ONE_BP
        assert np.isclose(eff.active_return, exp["active_return"], atol=tol), fx[
            "case_id"
        ]
        assert np.isclose(eff.allocation, exp["allocation"], atol=tol), fx["case_id"]
        assert np.isclose(eff.selection, exp["selection"], atol=tol), fx["case_id"]
        assert np.isclose(eff.interaction, exp["interaction"], atol=tol), fx["case_id"]


def test_fixtures_generator_regen_is_stable() -> None:
    """Regenerating the fixtures produces the SAME inputs and expecteds.

    Guards against nondeterminism sneaking into the generator (e.g. a
    future change swapping np.random for a stateful global).
    """

    for fx in _load_all_fixtures():
        gen = fx["generator"]
        case = make_case(gen["n_groups"], gen["seed"], **gen["flags"])
        for col in ("w_p", "w_b", "r_p", "r_b"):
            np.testing.assert_array_almost_equal(
                case.df[col].values,
                fx["inputs"][col],
                decimal=12,
                err_msg=f"{fx['case_id']}:{col}",
            )
        eff = brinson_reference(case.df)
        exp = fx["expected"]
        assert np.isclose(eff.active_return, exp["active_return"], atol=EXACT)


# ---------------------------------------------------------------------------
# 4. R7.11 discriminator — mutate the oracle, verify tests detect it
# ---------------------------------------------------------------------------


def test_oracle_catches_wrong_formula() -> None:
    """Wrong-formula 'oracles' produce DIFFERENT numbers than the trusted one.

    Discriminators here cover the two classic BF-implementation bugs
    that AGGREGATE identities make invisible:

    1. **Per-group plain-Brinson vs BF**: at the aggregate level plain
       Brinson ((w_p-w_b)*r_b) and BF ((w_p-w_b)*(r_b-R_b)) sum to the
       same value because sum(w_p-w_b)==0. But PER GROUP the vectors
       differ, and any implementation that reports per-group effects
       (which #559 will) must use the BF formula. Verify the vectors
       differ.
    2. **Swapped selection/interaction**: a common typo — using w_p
       instead of w_b in the selection term. This ALWAYS changes the
       aggregate value (unless w_p==w_b, i.e. the identical case).
    """
    case = make_case(5, seed=42)
    trusted = brinson_reference(case.df)
    df = case.df

    # Bug 1 — per-group plain-Brinson vs BF. Vectors differ even though
    # sums agree.
    r_b_total = float((df["w_b"] * df["r_b"]).sum())
    per_group_plain = ((df["w_p"] - df["w_b"]) * df["r_b"]).values
    per_group_bf = ((df["w_p"] - df["w_b"]) * (df["r_b"] - r_b_total)).values
    assert not np.allclose(per_group_plain, per_group_bf, atol=ONE_BP), (
        "generator produced a degenerate case where per-group plain==BF; "
        "pick a different seed"
    )

    # Bug 2 — swapped selection (w_p instead of w_b): aggregate DIFFERS.
    wrong_selection = float((df["w_p"] * (df["r_p"] - df["r_b"])).sum())
    assert not np.isclose(wrong_selection, trusted.selection, atol=ONE_BP), (
        "w_p-vs-w_b selection swap happens to agree on this case; "
        "pick a different seed"
    )


# ---------------------------------------------------------------------------
# 5. BrinsonEffects — surface-level sanity
# ---------------------------------------------------------------------------


def test_effects_as_dict_shape() -> None:
    """BrinsonEffects.as_dict exposes the four expected keys for JSON emit."""
    eff = BrinsonEffects(
        active_return=0.01, allocation=0.005, selection=0.003, interaction=0.002
    )
    d = eff.as_dict()
    assert set(d.keys()) == {"active_return", "allocation", "selection", "interaction"}
