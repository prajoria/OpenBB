"""Integration tests for the C03 data bundle against the live fmp_cached MySQL.

These run the *real* ``FmpCachedReader`` → ``BundleIngestor`` → parquet →
``Bundle`` pipeline end to end. They are marked ``integration`` and skip
cleanly when the ``openbb_fmp_cache`` database is unreachable, so the default
unit suite stays hermetic.

Anchored on stable facts: AAPL trades exactly 5 sessions in the holiday-free
week 2021-01-04..08, with a known close of 129.41 on 2021-01-04.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


def _db_available() -> bool:
    try:
        from openbb_fmp_cached.utils.database import execute_query

        execute_query("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip integration"
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _db_available(), reason="openbb_fmp_cache MySQL not reachable"
    ),
]


def test_ingest_aapl_ohlcv_end_to_end(tmp_path):
    from openbb_backtest.data.bundle import Bundle, BundleIngestor, FmpCachedReader

    reader = FmpCachedReader()  # live execute_query
    ingestor = BundleIngestor(reader=reader, calendar="XNYS")

    meta = ingestor.ingest(
        ["AAPL"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        name="it_aapl",
        root=tmp_path,
    )

    assert meta.symbols == ["AAPL"]
    assert meta.calendar == "XNYS"

    bundle = Bundle.load(tmp_path, name="it_aapl")
    out = bundle.history(["AAPL"], end=pd.Timestamp("2021-01-08"), lookback=10)
    out = out.sort_values("session").reset_index(drop=True)

    # Exactly five sessions in that holiday-free week.
    assert len(out) == 5
    # Concrete, stable cache fact.
    assert float(out.iloc[0]["close"]) == pytest.approx(129.41, abs=0.01)
    # Most recent adj_factor is unity (latest price == unadjusted close).
    assert float(out.iloc[-1]["adj_factor"]) == pytest.approx(1.0)


def test_history_look_ahead_guard_on_live_data(tmp_path):
    from openbb_backtest.data.bundle import Bundle, BundleIngestor, FmpCachedReader

    ingestor = BundleIngestor(reader=FmpCachedReader(), calendar="XNYS")
    ingestor.ingest(
        ["AAPL"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        name="it_guard",
        root=tmp_path,
    )
    bundle = Bundle.load(tmp_path, name="it_guard")

    out = bundle.history(["AAPL"], end=pd.Timestamp("2021-01-06"), lookback=10)
    # No future bars past the requested end, even with a generous lookback.
    assert out["session"].max() == pd.Timestamp("2021-01-06")
    assert pd.Timestamp("2021-01-07") not in set(out["session"])
