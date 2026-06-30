"""Tests for ``openbb_pine.runtime.byo_provider`` -- D2 section 3."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from openbb_pine.errors import PineDataValidationError
from openbb_pine.runtime.byo_provider import BYODataProvider, REQUIRED_COLUMNS


def _valid_daily_frame(rows: int = 5, *, tz_aware: bool = False) -> pd.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc if tz_aware else None)
    idx = pd.DatetimeIndex(
        [base + pd.Timedelta(days=i) for i in range(rows)], name="date"
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000_000.0 + i for i in range(rows)],
        },
        index=idx,
    )


def _valid_intraday_frame(rows: int = 5) -> pd.DataFrame:
    base = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    idx = pd.DatetimeIndex(
        [base + pd.Timedelta(minutes=5 * i) for i in range(rows)], name="date"
    )
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.5] * rows,
            "volume": [1000.0] * rows,
        },
        index=idx,
    )


# --- Required columns / required columns constant -----------------------------


class TestRequiredColumns:
    def test_required_columns_constant_is_frozenset(self):
        assert REQUIRED_COLUMNS == frozenset(
            {"open", "high", "low", "close", "volume"}
        )


# --- Construction with valid data --------------------------------------------


class TestValidConstruction:
    def test_tz_aware_daily_frame_accepted(self):
        df = _valid_daily_frame(tz_aware=True)
        prov = BYODataProvider(df, symbol="AAPL")
        assert prov.provider_used == "byo"
        assert prov.bars_consumed == 0
        assert prov.symbol == "AAPL"

    def test_tz_naive_daily_frame_accepted(self):
        """tz-naive index is only banned for intraday (D2 section 3.1)."""
        df = _valid_daily_frame(tz_aware=False)
        prov = BYODataProvider(df, symbol="AAPL", interval="1d")
        # Construction does not raise.
        assert prov.symbol == "AAPL"

    def test_intraday_tz_aware_accepted(self):
        df = _valid_intraday_frame()
        prov = BYODataProvider(df, symbol="AAPL", interval="5m")
        assert prov.bars_consumed == 0


# --- Schema validation: defect collection -------------------------------------


class TestDefectCollection:
    """Per D2 section 3.1 -- collect EVERY defect, never first-error-wins."""

    def test_missing_single_required_column_raises(self):
        df = _valid_daily_frame(tz_aware=True).drop(columns=["volume"])
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        msg = str(excinfo.value)
        assert "volume" in msg

    def test_multiple_missing_columns_all_reported_in_one_error(self):
        df = _valid_daily_frame(tz_aware=True).drop(columns=["volume", "high"])
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        msg = str(excinfo.value)
        assert "volume" in msg
        assert "high" in msg

    def test_tz_naive_intraday_rejected(self):
        # Build a tz-naive 5-minute frame.
        idx = pd.DatetimeIndex(
            [datetime(2024, 1, 1, 9, 30) + pd.Timedelta(minutes=5 * i) for i in range(3)],
            name="date",
        )
        df = pd.DataFrame(
            {
                "open": [1.0] * 3,
                "high": [1.0] * 3,
                "low": [1.0] * 3,
                "close": [1.0] * 3,
                "volume": [1.0] * 3,
            },
            index=idx,
        )
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL", interval="5m")
        # Defect message should name the offending interval / tz issue.
        msg = str(excinfo.value).lower()
        assert "tz" in msg or "timezone" in msg or "intraday" in msg

    def test_non_monotonic_index_rejected(self):
        df = _valid_daily_frame(tz_aware=True)
        # Reverse the index so it's strictly decreasing.
        df = df.iloc[::-1]
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        assert "monoton" in str(excinfo.value).lower()

    def test_non_datetime_index_rejected(self):
        df = pd.DataFrame(
            {
                "open": [1.0, 2.0],
                "high": [1.0, 2.0],
                "low": [1.0, 2.0],
                "close": [1.0, 2.0],
                "volume": [1.0, 2.0],
            },
            index=[0, 1],
        )
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        assert "datetimeindex" in str(excinfo.value).lower()

    def test_nan_in_required_column_rejected(self):
        df = _valid_daily_frame(tz_aware=True)
        df.iloc[1, df.columns.get_loc("close")] = float("nan")
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        assert "nan" in str(excinfo.value).lower()

    def test_duplicate_index_rejected(self):
        df = _valid_daily_frame(tz_aware=True)
        # Duplicate the first row.
        dup = df.iloc[[0]]
        df = pd.concat([dup, df])
        # Index now has duplicates AND may become non-monotonic; both are
        # legitimate defects. Either message is acceptable.
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        lower = str(excinfo.value).lower()
        assert "duplicate" in lower or "monoton" in lower

    def test_all_defects_surface_in_one_raise(self):
        """A frame with FOUR defects (missing col + non-monotonic + tz-naive
        intraday + NaN) emits ONE PineDataValidationError that mentions every
        defect. The whole point of D2 section 3.1's design."""
        idx = pd.DatetimeIndex(
            [
                datetime(2024, 1, 1, 9, 30),
                datetime(2024, 1, 1, 9, 25),  # out of order
                datetime(2024, 1, 1, 9, 35),
            ],
            name="date",
        )
        df = pd.DataFrame(
            {
                "open": [1.0, 2.0, float("nan")],  # NaN
                "high": [1.0, 2.0, 3.0],
                "low": [1.0, 2.0, 3.0],
                "close": [1.0, 2.0, 3.0],
                # volume missing
            },
            index=idx,
        )
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL", interval="5m")
        msg = str(excinfo.value).lower()
        # At least three different defect families surface in the SAME message.
        defect_signals = [
            "volume" in msg,                                      # missing column
            "monoton" in msg,                                     # ordering
            ("tz" in msg or "timezone" in msg or "intraday" in msg),  # tz-naive intraday
            "nan" in msg,                                         # NaN
        ]
        assert sum(defect_signals) >= 3, (
            f"expected >=3 defect families in one error; got message: {msg!r}"
        )

    def test_non_dataframe_input_rejected(self):
        with pytest.raises(PineDataValidationError):
            BYODataProvider([{"open": 1.0}], symbol="AAPL")  # type: ignore[arg-type]


# --- iter_ohlcv round-trip ----------------------------------------------------


class TestIterOHLCV:
    def test_valid_frame_round_trips(self):
        df = _valid_daily_frame(tz_aware=True, rows=4)
        prov = BYODataProvider(df, symbol="AAPL")
        bars = list(prov.iter_ohlcv())
        assert len(bars) == 4
        for i, bar in enumerate(bars):
            assert isinstance(bar.timestamp, int)
            assert bar.open == float(100.0 + i)
            assert bar.high == float(101.0 + i)
            assert bar.low == float(99.0 + i)
            assert bar.close == float(100.5 + i)
            assert bar.volume == float(1_000_000.0 + i)

    def test_bars_consumed_increments_per_yield(self):
        df = _valid_daily_frame(tz_aware=True, rows=3)
        prov = BYODataProvider(df, symbol="AAPL")
        it = prov.iter_ohlcv()
        next(it)
        assert prov.bars_consumed == 1
        list(it)
        assert prov.bars_consumed == 3

    def test_default_symbol_is_byo(self):
        df = _valid_daily_frame(tz_aware=True)
        prov = BYODataProvider(df)
        assert prov.symbol == "BYO"

    def test_provider_used_constant(self):
        df = _valid_daily_frame(tz_aware=True)
        prov = BYODataProvider(df, symbol="ANYTHING")
        assert prov.provider_used == "byo"

    def test_context_attached_to_validation_error(self):
        """``context=`` argument surfaces in the message for downstream
        dispatchers (D2 section 5.3 secondary-resolver path)."""
        df = pd.DataFrame()
        with pytest.raises(PineDataValidationError) as excinfo:
            BYODataProvider(df, symbol="AAPL")
        assert "AAPL" in str(excinfo.value) or "context" in str(excinfo.value).lower()
