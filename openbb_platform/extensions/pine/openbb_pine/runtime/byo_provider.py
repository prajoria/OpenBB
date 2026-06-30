"""Bring-your-own-data (BYO) primary-series provider for the Pine runtime.

D2 section 3 -- wraps a caller-supplied ``pandas.DataFrame`` as the primary
OHLCV stream. Secondary lookups (``request.security``, extended ``syminfo.*``)
still route through ``FMPOHLCVProvider`` unless a Python-API ``data_resolver``
callable is supplied (handled by the dispatcher in a later bead).

Schema validation collects **every** defect into a single
``PineDataValidationError`` -- never first-error-wins. Per D2 section 3.1
this makes BYO mode usable from a CLI that hands the user a one-shot
fix list (PRD section 4.10).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

import pandas as pd

from openbb_pine.errors import PineDataValidationError

if TYPE_CHECKING:  # pragma: no cover -- typing-only imports
    from pynecore.types.ohlcv import OHLCV


REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {"open", "high", "low", "close", "volume"}
)

# Intervals that require a tz-aware index (D2 section 3.1).
INTRADAY_INTERVALS: frozenset[str] = frozenset(
    {
        # FMP / OBB-shape
        "1m", "2m", "3m", "5m", "15m", "30m", "1h", "2h", "4h",
        # Pine-shape (digit-only minute counts + lowercase aliases)
        "1", "2", "3", "5", "15", "30", "60", "120", "240",
    }
)


def _is_intraday(interval: str | None) -> bool:
    """Return True if ``interval`` is a sub-daily timeframe."""
    if interval is None:
        return False
    return interval in INTRADAY_INTERVALS or interval.lower() in INTRADAY_INTERVALS


def _make_ohlcv(timestamp: int, open_: float, high: float, low: float,
                close: float, volume: float) -> "OHLCV":
    """Construct the PyneCore NamedTuple lazily (so sys.path bridge runs first)."""
    from pynecore.types.ohlcv import OHLCV  # noqa: PLC0415

    return OHLCV(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _to_utc_seconds(ts: Any) -> int:
    """Convert a pandas ``Timestamp`` to integer UTC seconds.

    Tz-naive values are assumed to be UTC (daily+ data only -- intraday
    tz-naive is rejected at validation time).
    """
    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            ts = ts.tz_localize(timezone.utc)
        return int(ts.timestamp())
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int(ts.timestamp())
    raise TypeError(f"Cannot coerce {type(ts).__name__} to UTC seconds")


class BYODataProvider:
    """Wrap a caller DataFrame as the primary OHLCV stream.

    See module docstring for the validation contract. ``interval`` is used
    only to decide whether a tz-naive index is acceptable.
    """

    def __init__(
        self,
        df: Any,
        *,
        symbol: str = "BYO",
        interval: str | None = None,
        asset_class: str = "equity",
    ) -> None:
        defects = self._validate(df, interval=interval)
        if defects:
            raise PineDataValidationError(
                f"BYO data validation failed (context: symbol={symbol}): "
                + "; ".join(defects)
            )
        self.df: pd.DataFrame = df
        self.symbol: str = symbol
        self.interval: str | None = interval
        self.asset_class: str = asset_class
        self.provider_used: str = "byo"
        self.bars_consumed: int = 0

    # --- Validation -----------------------------------------------------------

    @staticmethod
    def _validate(df: Any, *, interval: str | None) -> list[str]:
        """Collect every schema defect. Returns ``[]`` when df is well-formed.

        Each defect string is human-actionable and self-contained. The
        accumulator pattern is deliberate -- see D2 section 3.1.
        """
        defects: list[str] = []

        if not isinstance(df, pd.DataFrame):
            return [
                f"data must be a pandas.DataFrame, got {type(df).__name__}"
            ]

        # Empty frame is its own defect -- distinct from missing columns.
        if df.empty:
            defects.append("DataFrame is empty (zero rows)")

        # Required-column check -- list every missing column in one message.
        missing = sorted(REQUIRED_COLUMNS - set(df.columns))
        if missing:
            defects.append(f"missing required column(s): {missing}")

        # Index shape + ordering + tz checks.
        if not isinstance(df.index, pd.DatetimeIndex):
            defects.append(
                f"index must be pandas.DatetimeIndex, got {type(df.index).__name__}"
            )
        else:
            if not df.index.is_monotonic_increasing:
                defects.append("index must be strictly monotonically increasing")
            if df.index.has_duplicates:
                defects.append("index must not contain duplicates")
            if df.index.tz is None and _is_intraday(interval):
                defects.append(
                    f"index is timezone-naive but interval {interval!r} is "
                    "intraday -- tz-aware DatetimeIndex required (PRD section 4.10)"
                )

        # NaN check across the required columns that ARE present (so we don't
        # double-report a column already flagged missing).
        present_required = REQUIRED_COLUMNS & set(df.columns)
        if present_required and not df.empty:
            nan_cols = sorted(
                c for c in present_required if df[c].isna().any()
            )
            if nan_cols:
                defects.append(f"NaN values in required column(s): {nan_cols}")

        return defects

    # --- PyneCore-facing surface ---------------------------------------------

    def iter_ohlcv(self) -> Iterator["OHLCV"]:
        """Yield ``OHLCV`` NamedTuples in time order.

        Bumps ``self.bars_consumed`` per yield. Volume is coerced from
        ``None`` / ``NaN`` to ``0.0`` defensively, though validation already
        rejects NaN in required columns.
        """
        for ts, row in self.df.iterrows():
            self.bars_consumed += 1
            volume = row["volume"]
            try:
                volume = float(volume) if volume is not None and not pd.isna(volume) else 0.0
            except (TypeError, ValueError):
                volume = 0.0
            yield _make_ohlcv(
                timestamp=_to_utc_seconds(ts),
                open_=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=volume,
            )


__all__ = [
    "BYODataProvider",
    "INTRADAY_INTERVALS",
    "REQUIRED_COLUMNS",
]
