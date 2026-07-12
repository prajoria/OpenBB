"""Test fixtures for the techtrade extension.

**Fixture files are recorded, not generated on-the-fly** — they need
to be reproducible across environments (same bytes → same test results).
This module provides loaders that skip cleanly when a fixture is
absent, so the test suite continues to run in bare environments and
missing fixtures fail the specific tests that need them, not the
whole collection.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent

BASKET_SYMBOLS = ("NVDA", "PG", "XOM", "PLTR", "SPY")
"""Single-name basket for the IC harness / decorrelation gates
(bd-7ct spec §D8 / §10 N1). One hi-beta tech + one lo-vol staple +
one cyclical + one recent-IPO + market baseline. Recorded via
``tools/record_basket_fixture.py`` for 2020-01-01 → 2025-12-31."""

BASKET_PARQUET = FIXTURES_DIR / "basket_2020_2025.parquet"


def load_basket() -> dict[str, pd.DataFrame]:
    """Return the recorded basket as ``{symbol: DataFrame}``.

    The DataFrame has a DatetimeIndex and lowercase OHLCV columns
    (``open``, ``high``, ``low``, ``close``, ``volume``). Skips the
    calling test with a clear reason when the parquet is absent so
    a bare / unrecorded environment doesn't fail on collection.
    """
    if not BASKET_PARQUET.exists():
        pytest.skip(
            f"basket fixture not recorded — run tools/record_basket_fixture.py "
            f"to generate {BASKET_PARQUET.name}"
        )
    df = pd.read_parquet(BASKET_PARQUET)
    # Ensure the date column is a DatetimeIndex after group-splitting.
    result: dict[str, pd.DataFrame] = {}
    for sym, g in df.groupby("symbol"):
        # Drop the symbol column, then promote 'date' to a DatetimeIndex.
        # The date column may be datetime or string depending on the
        # parquet round-trip; coerce defensively.
        symbol_df = g.drop(columns=["symbol"]).copy()
        symbol_df["date"] = pd.to_datetime(symbol_df["date"])
        symbol_df = symbol_df.set_index("date").sort_index()
        result[sym] = symbol_df
    return result
