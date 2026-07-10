"""Bring-your-own-data (BYO) primary-series provider for the Pine runtime.

D2 section 3 -- wraps a caller-supplied ``pandas.DataFrame`` as the primary
OHLCV stream. Secondary lookups (``request.security``, extended ``syminfo.*``)
still route through ``FMPOHLCVProvider`` unless a Python-API ``data_resolver``
callable is supplied (handled by the dispatcher in a later bead).

Schema validation collects **every** defect into a single
``PineDataValidationError`` -- never first-error-wins. Per D2 section 3.1
this makes BYO mode usable from a CLI that hands the user a one-shot
fix list (PRD section 4.10).

E3.3 (bd-tzm): inherits :class:`pynecore.providers.Provider` (mode-1 per
Pine Extraction Design §5.2). The class is scoped at construction to a
single ``(symbol, interval)``; call-time mismatches in :meth:`stream`
raise :class:`ValueError`, and the pynecore behavioral conformance
suite (E1.4, bd-cko) runs against it via
``test_byo_provider_conformance.py``. Legacy attributes / methods
(``iter_ohlcv``, ``bars_consumed``, ``provider_used``, ``df``) are
preserved for the existing BYO call path — the base-class contract is
additive.

Clean-room: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterator

import pandas as pd

from openbb_pine.errors import PineDataValidationError
from openbb_pine.runtime import pynecore_bridge  # noqa: F401 -- sys.path install
from pynecore.providers.provider import Provider
from pynecore.types.ohlcv import OHLCV

if TYPE_CHECKING:  # pragma: no cover -- typing-only imports
    pass


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
                close: float, volume: float) -> OHLCV:
    """Construct the PyneCore NamedTuple."""
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


class BYODataProvider(Provider):
    """Wrap a caller DataFrame as the primary OHLCV stream.

    See module docstring for the validation contract. ``interval`` is used
    both to decide whether a tz-naive index is acceptable AND as the
    :class:`~pynecore.providers.provider.Provider` ``timeframe`` for
    mode-1 call-time verification (spec §5.2).

    Deliberately does NOT invoke ``super().__init__`` — the base
    constructor requires an ``ohlv_dir`` / ``config_dir`` and eagerly
    opens ``providers.toml``. BYO is a memory-only provider driven by a
    caller-supplied DataFrame; there is no on-disk config to load and no
    ``.ohlcv`` file to round-trip through. We set the base-class fields
    the API surface reads (``symbol``, ``timeframe``, ``config``)
    manually. Pattern mirrors :class:`pynecore.providers.csv.CSVProvider`
    which faces the same "file IS the data" problem.
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
                defects=defects,
                context=f"symbol={symbol}",
            )
        self.df: pd.DataFrame = df
        # Legacy BYO surface preserved for the existing call path
        # (executor_shell wraps and reads these attrs).
        self.symbol: str = symbol
        self.interval: str | None = interval
        self.asset_class: str = asset_class
        self.provider_used: str = "byo"
        self.bars_consumed: int = 0
        # Provider-base surface: mode-1 uses ``timeframe`` as the
        # construction-scoped identity check inside ``stream``. Reuse
        # ``interval`` so a legacy caller that passed ``interval="5m"``
        # gets the mode-1 guard for free.
        self.timeframe: str | None = interval
        # No providers.toml — BYO has no exchange config knobs.
        self.config = {}

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

    # --- Provider ABC surface (no-op / identity for a memory-only source) ----

    @classmethod
    def to_tradingview_timeframe(cls, timeframe: str) -> str:
        return timeframe

    @classmethod
    def to_exchange_timeframe(cls, timeframe: str) -> str:
        return timeframe

    def get_list_of_symbols(self, *args, **kwargs) -> list[str]:
        assert self.symbol is not None
        return [self.symbol]

    def update_symbol_info(self):  # pragma: no cover -- BYO has no exchange metadata
        raise NotImplementedError(
            "BYODataProvider does not model exchange metadata; supply the "
            "OHLCV bars directly via the DataFrame constructor argument."
        )

    @classmethod
    def get_opening_hours_and_sessions(cls):
        return [], [], []

    def load_config(self) -> None:  # pragma: no cover -- overridden to no-op
        self.config = {}

    def download_ohlcv(  # type: ignore[override]
        self,
        time_from: datetime | None = None,
        time_to: datetime | None = None,
        on_progress: Callable[[datetime], None] | None = None,
        limit: int | None = None,
    ) -> None:
        # No-op: the DataFrame IS the data. stream()/fetch() below read
        # directly from ``self.df`` — nothing to download.
        return

    # --- PyneCore-facing surface ---------------------------------------------

    def iter_ohlcv(self) -> Iterator[OHLCV]:
        """Yield ``OHLCV`` NamedTuples in time order.

        Bumps ``self.bars_consumed`` per yield. Volume is coerced from
        ``None`` / ``NaN`` to ``0.0`` defensively, though validation already
        rejects NaN in required columns.

        Retained for the existing BYO call path (executor_shell) — the
        base-class :meth:`stream` is what pyne_compiler-consumers use.
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

    def stream(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        include_gaps: bool = False,  # accepted for API parity; BYO has no gap sentinels
    ) -> Iterator[OHLCV]:
        """Yield OHLCV bars from the wrapped DataFrame, filtered to ``[start, end]``.

        Mode-1 (spec §5.2): instance is construction-scoped to a single
        ``(symbol, interval)``. Call-time mismatches raise ``ValueError``.
        Replicates the base-class guards (naive datetime → ``TypeError``,
        reversed range → ``[]``) so the pynecore conformance suite sees
        identical behavior across providers.

        ``include_gaps`` is accepted for API parity but has no effect —
        the DataFrame carries no gap-fill sentinel.
        """
        # Mode-1 symbol/timeframe mismatch → typed ValueError (spec §5.4 check #5).
        if self.symbol is not None and symbol != self.symbol:
            raise ValueError(
                f"call-time symbol {symbol!r} does not match construction-time "
                f"{self.symbol!r}; BYODataProvider is mode-1 (single-symbol per "
                "instance, spec §5.2)."
            )
        if self.timeframe is not None and timeframe != self.timeframe:
            raise ValueError(
                f"call-time timeframe {timeframe!r} does not match construction-"
                f"time {self.timeframe!r}; BYODataProvider is mode-1 (single-"
                "timeframe per instance, spec §5.2)."
            )

        # Naive datetimes are ambiguous cross-machine (spec §5).
        if start is not None and start.tzinfo is None:
            raise TypeError(
                "start must be a timezone-aware datetime (spec §5); "
                "got naive datetime which is ambiguous across timezones."
            )
        if end is not None and end.tzinfo is None:
            raise TypeError(
                "end must be a timezone-aware datetime (spec §5); "
                "got naive datetime which is ambiguous across timezones."
            )

        # Reversed range → empty (spec §5.4 check #4). Early-return inside
        # a generator terminates it immediately.
        if start is not None and end is not None and start > end:
            return

        start_ts = int(start.timestamp()) if start is not None else None
        end_ts = int(end.timestamp()) if end is not None else None

        # Stream from a fresh iteration each call (statelessness — spec
        # §5.4 check #7). We deliberately do NOT bump ``bars_consumed``
        # here — that counter tracks the legacy iter_ohlcv path only.
        for ts, row in self.df.iterrows():
            bar_ts = _to_utc_seconds(ts)
            if start_ts is not None and bar_ts < start_ts:
                continue
            if end_ts is not None and bar_ts > end_ts:
                # The validated DataFrame is monotonically increasing
                # (checked in ``_validate``), so a strict break here is
                # safe — no in-range rows can follow.
                break
            volume = row["volume"]
            try:
                volume = float(volume) if volume is not None and not pd.isna(volume) else 0.0
            except (TypeError, ValueError):
                volume = 0.0
            yield _make_ohlcv(
                timestamp=bar_ts,
                open_=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=volume,
            )

    def fetch(  # type: ignore[override]
        self,
        symbol: str,
        timeframe: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        include_gaps: bool = False,
    ) -> list[OHLCV]:
        """Materialize :meth:`stream` as a list. Behavior identical."""
        return list(self.stream(
            symbol, timeframe, start=start, end=end, include_gaps=include_gaps,
        ))


__all__ = [
    "BYODataProvider",
    "INTRADAY_INTERVALS",
    "REQUIRED_COLUMNS",
]
