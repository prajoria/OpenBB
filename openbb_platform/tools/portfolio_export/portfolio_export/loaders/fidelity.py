"""fidelity.py — parse Fidelity `Portfolio_Positions_*.csv` into a DataFrame.

Handles Fidelity's quirks:
  - stray trailing comma on data rows (18 cells vs 17-col header)
  - footer / disclaimer / blank rows appended after real data
  - money formatted as `$88.80`, `-$0.55`, `+$3.23`
  - percentages formatted as `-0.62%`, `+4.42%`, `0.00%`
  - the optional `user_id` column (present after `pe tag`)

The loader is deliberately silent — no prints, no logs of row content.
Returns a typed DataFrame; caller decides what to display.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Column groups by target dtype. Any column outside these lists stays
# as string. Kept as constants so tests and downstream code agree.
MONEY_COLS: tuple[str, ...] = (
    "Last price",
    "Last price change",
    "Current value",
    "Today's gain/loss dollar",
    "Total gain/loss dollar",
    "Cost basis total",
    "Average cost basis",
)

PERCENT_COLS: tuple[str, ...] = (
    "Today's gain/loss percent",
    "Total gain/loss percent",
    "Percent of account",
)

NUMERIC_COLS: tuple[str, ...] = ("Quantity",)

# Every non-empty data row from Fidelity begins with an account number
# in the first cell (typically alphanumeric like ``X78542853`` or
# ``Z12345678``). Footer / disclaimer rows either have no cells,
# no first cell, or free-form text — never the account-number shape.
_ACCOUNT_CELL_RE = r"^[A-Za-z0-9]{6,}$"


def _clean_money(s: pd.Series) -> pd.Series:
    """`$88.80` / `+$3.23` / `-$0.55` → float."""
    return pd.to_numeric(
        s.astype("string")
        .str.replace(r"[,$\s+]", "", regex=True)
        .replace({"": pd.NA, "--": pd.NA, "n/a": pd.NA, "N/A": pd.NA}),
        errors="coerce",
    )


def _clean_percent(s: pd.Series) -> pd.Series:
    """`-0.62%` / `+4.42%` / `0.00%` → float (percentage-as-number, e.g. -0.62)."""
    return pd.to_numeric(
        s.astype("string")
        .str.replace(r"[%+\s]", "", regex=True)
        .replace({"": pd.NA, "--": pd.NA, "n/a": pd.NA, "N/A": pd.NA}),
        errors="coerce",
    )


def load_positions(path: str | Path) -> pd.DataFrame:
    """Load a Fidelity Positions export.

    Returns a DataFrame where money and percent columns are floats,
    Quantity is float, and identifier columns (Account number, Symbol,
    Description, Type, user_id) are strings.

    Footer / disclaimer / blank rows are dropped. Column order is
    preserved from the source file.
    """
    path = Path(path)

    # engine="python" tolerates rows with a different number of fields
    # than the header (Fidelity's stray trailing comma). We keep the
    # extra columns and filter to the header set below.
    df = pd.read_csv(
        path,
        engine="python",
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        on_bad_lines="skip",
    )

    # If the trailing-comma quirk produced an unnamed extra column
    # (usually named ``Unnamed: 17`` or the last col is all-NA), drop
    # columns that have no header name.
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]

    # Drop footer rows: any row whose first cell doesn't look like an
    # account identifier. This also drops all-blank rows.
    if len(df.columns) == 0:
        return df
    first_col = df.columns[0]
    mask = df[first_col].astype("string").fillna("").str.match(_ACCOUNT_CELL_RE)
    df = df.loc[mask].reset_index(drop=True)

    # Type coercion — only for columns actually present.
    for col in MONEY_COLS:
        if col in df.columns:
            df[col] = _clean_money(df[col])
    for col in PERCENT_COLS:
        if col in df.columns:
            df[col] = _clean_percent(df[col])
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # String columns: force pandas nullable string dtype for the rest.
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype("string")

    return df


def describe(df: pd.DataFrame) -> dict[str, object]:
    """Return schema-only aggregates safe to print.

    Includes: shape, dtypes, per-account row counts, per-type row
    counts, and — importantly — NO dollar totals, no per-symbol data,
    no row content. Callers wanting dollar aggregates should compute
    them explicitly on the returned DataFrame.
    """
    out: dict[str, object] = {
        "shape": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
        "columns": {c: str(df[c].dtype) for c in df.columns},
    }
    if "Account number" in df.columns:
        out["accounts"] = {
            "count": int(df["Account number"].nunique(dropna=True)),
            "rows_per_account": {
                str(k): int(v)
                for k, v in df["Account number"].value_counts(dropna=False).items()
            },
        }
    if "Type" in df.columns:
        out["type_breakdown"] = {
            str(k): int(v) for k, v in df["Type"].value_counts(dropna=False).items()
        }
    if "user_id" in df.columns:
        out["user_id_values"] = sorted(
            {str(v) for v in df["user_id"].dropna().unique().tolist()}
        )
    return out
