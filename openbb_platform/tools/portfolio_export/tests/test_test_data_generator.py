"""Smoke tests for portfolio_export.test_data_generator.

Round-trip contract: generator output → load_positions() → shape + dtypes
+ definitional invariants. If this breaks, either the generator has
drifted from the loader's expected columns or Fidelity's field semantics
have changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from portfolio_export.loaders.fidelity import load_positions
from portfolio_export.test_data_generator import FIDELITY_HEADER, main


@pytest.fixture
def generated_csv(tmp_path: Path) -> Path:
    """Run the generator with a fixed seed into a tempdir; return the CSV path."""
    out_path = tmp_path / "Portfolio_Positions_Jul-19-2026_alice.csv"
    exit_code = main(
        [
            "--user-ids",
            "alice,bob",
            "--accounts",
            "X78542853,Z12345678",
            "--date",
            "2026-07-19",
            "--seed",
            "42",
            "--out",
            str(out_path),
        ]
    )
    assert exit_code == 0
    assert out_path.exists()
    return out_path


def test_generator_output_loads_via_fidelity_loader(generated_csv: Path) -> None:
    """load_positions() must accept generator output without errors."""
    df = load_positions(generated_csv)
    # Default preset has 10 rows; loader may drop trailing-quirk column so
    # the visible column count is one less than FIDELITY_HEADER length when
    # the trailing-comma quirk is on. Generator defaults to quirk OFF, so
    # all header columns land.
    assert df.shape[0] == 10, f"expected 10 rows, got {df.shape[0]}"
    assert df.shape[1] == len(
        FIDELITY_HEADER
    ), f"column count mismatch: got {df.shape[1]}, expected {len(FIDELITY_HEADER)}"


def test_generator_output_contains_all_named_columns(generated_csv: Path) -> None:
    """Every FIDELITY_HEADER column must survive round-trip through the loader."""
    df = load_positions(generated_csv)
    for col in FIDELITY_HEADER:
        assert col in df.columns, f"loader dropped expected column: {col}"


def test_current_value_invariant_holds_within_precision(generated_csv: Path) -> None:
    """Current value = Quantity * Last price (definitional; machine-precision exact)."""
    df = load_positions(generated_csv)
    for _, row in df.iterrows():
        q = float(row["Quantity"])
        lp = float(row["Last price"])
        cv = float(row["Current value"])
        expected = q * lp
        assert abs(cv - expected) < 0.01, (
            f"Current value invariant broken on {row['Symbol']}: "
            f"got {cv}, expected {expected} (q={q}, lp={lp})"
        )


def test_multi_user_round_robin(generated_csv: Path) -> None:
    """--user-ids alice,bob must produce rows for both users in the file."""
    df = load_positions(generated_csv)
    unique_users = set(df["user_id"].dropna().unique())
    assert unique_users == {"alice", "bob"}, (
        f"user_id round-robin failed: got {unique_users}, expected " "{alice, bob}"
    )


def test_multi_account_round_robin(generated_csv: Path) -> None:
    """--accounts X78542853,Z12345678 must produce rows for both accounts."""
    df = load_positions(generated_csv)
    unique_accts = set(df["Account number"].dropna().unique())
    assert unique_accts == {
        "X78542853",
        "Z12345678",
    }, f"account round-robin failed: got {unique_accts}"


def test_percent_of_account_sums_to_100_per_account(generated_csv: Path) -> None:
    """Fidelity convention: per-account % of account cells sum to 100 (within display precision)."""
    df = load_positions(generated_csv)
    for acct, group in df.groupby("Account number"):
        total = group["Percent of account"].sum()
        assert (
            abs(float(total) - 100.0) < 0.05
        ), f"account {acct}: % of account sum = {total}, expected ~100.0"


def test_money_market_row_has_blank_gain_loss(generated_csv: Path) -> None:
    """SPAXX (in default preset) should have blank gain/loss cells per Fidelity convention."""
    df = load_positions(generated_csv)
    mmkt_rows = df[df["Symbol"] == "SPAXX"]
    assert (
        len(mmkt_rows) == 1
    ), f"expected 1 SPAXX row in default preset, got {len(mmkt_rows)}"
    row = mmkt_rows.iloc[0]
    # These fields must be NA (Fidelity blanks them on money-market positions).
    for col in [
        "Today's gain/loss dollar",
        "Today's gain/loss percent",
        "Total gain/loss dollar",
        "Total gain/loss percent",
        "Cost basis total",
        "Average cost basis",
    ]:
        assert bool(pd_isna(row[col])), f"MMKT row {col}={row[col]!r}, expected NA"


def pd_isna(v) -> bool:  # noqa: ANN001 — small local helper
    """pandas.isna wrapper that tolerates non-scalar edge cases in dropna'd cells."""
    import pandas as pd

    return bool(pd.isna(v))
