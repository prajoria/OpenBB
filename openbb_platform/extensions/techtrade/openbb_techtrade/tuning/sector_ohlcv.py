"""Pool a segment's OHLCV into the (date, symbol) MultiIndex tuneta consumes (#83 L4).

The bridge between techtrade's per-symbol OHLCV fetcher (the ``fmp_cached`` path
through :func:`openbb.obb.equity.price.historical`, lazy-imported on demand) and
the multi-symbol DataFrame tuneta's :meth:`fit` expects when run over a
segment's universe (tuneta README: *"For multi-symbol use, index the DataFrame
by both date and symbol"*).

The forward-cumulative-return target ``y`` (Q-B B3) aligns the tuneta
optimisation with the rule that will consume the tuned periods: the default
``forward_horizon_bars=20`` matches :attr:`EntryExitRule.max_holding_bars`, so
the tuned periods become good at predicting the *kind* of move the rule is
built to capture.

This module imports neither ``tuneta`` nor ``openbb_backtest``. It is safe to
import on a bare techtrade install (though calling :func:`pool_sector_ohlcv`
without an injected ``fetcher`` will lazy-import the default ``fmp_cached``
fetcher at call time, which itself requires fmp_cached to be configured).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date

import pandas as pd

# Best-effort universe resolver (PRD Q3 default = etf_holdings).
#
# We expose a small ``universe_for_segment(segment, source) -> list[str]`` wrapper
# around the canonical :func:`openbb_techtrade.engine.universe.resolve_universe`
# helper so callers (and tests) can ask for a segment's symbols by name without
# constructing a :class:`SegmentConfig` per call. The wrapper pre-bakes the
# config from :data:`GICS_SECTOR_ETFS`. Tests monkey-patch ``universe_for_segment``
# on this module directly to keep the unit tests offline.
try:
    from openbb_techtrade.engine.screener import GICS_SECTOR_ETFS
    from openbb_techtrade.engine.universe import resolve_universe
    from openbb_techtrade.models import SegmentConfig

    def universe_for_segment(segment: str, source: str = "etf_holdings") -> list[str]:
        """Resolve a GICS segment's symbol universe via the canonical resolver.

        Pre-bakes a :class:`SegmentConfig` from :data:`GICS_SECTOR_ETFS` so the
        rest of techtrade can ask for symbols by segment name only. Defers to
        :func:`resolve_universe` for the actual fetch (PRD §10, §20 Q3).
        """
        cfg = SegmentConfig(
            segment=segment,
            universe_source=source,  # type: ignore[arg-type]
            benchmark_etf=GICS_SECTOR_ETFS.get(segment),
        )
        return resolve_universe(cfg)
except ImportError:  # pragma: no cover - defensive; all the names exist today
    _FALLBACK_UNIVERSE: dict[str, list[str]] = {
        "Information Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ADBE"],
        "Financials": ["JPM", "BAC", "WFC", "GS", "MS"],
        "Health Care": ["UNH", "JNJ", "LLY", "PFE", "ABBV"],
        "Energy": ["XOM", "CVX", "COP", "EOG", "SLB"],
        "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
        "Consumer Staples": ["PG", "KO", "WMT", "COST", "PEP"],
        "Communication Services": ["GOOG", "META", "NFLX", "DIS", "VZ"],
        "Industrials": ["CAT", "BA", "HON", "GE", "UNP"],
        "Materials": ["LIN", "APD", "SHW", "ECL", "NEM"],
        "Utilities": ["NEE", "SO", "DUK", "AEP", "EXC"],
        "Real Estate": ["PLD", "AMT", "EQIX", "CCI", "PSA"],
    }

    def universe_for_segment(  # type: ignore[no-redef]
        segment: str, source: str = "etf_holdings"
    ) -> list[str]:
        return list(_FALLBACK_UNIVERSE.get(segment, []))


logger = logging.getLogger(__name__)

#: Forward-return horizon (bars) -- Q-B B3, matches EntryExitRule.max_holding_bars.
DEFAULT_FORWARD_HORIZON_BARS: int = 20

#: Fold-window length (years) -- Q-C, same as #82's DEFAULT_HORIZON_YEARS.
DEFAULT_HORIZON_YEARS: int = 5

# Canonical OHLCV column order expected by tuneta's multi-symbol fit.
_OHLCV_COLS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


Fetcher = Callable[..., pd.DataFrame]


def pool_sector_ohlcv(
    segment: str,
    *,
    as_of: date,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    forward_horizon_bars: int = DEFAULT_FORWARD_HORIZON_BARS,
    fetcher: Fetcher | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Pool ``segment``'s universe OHLCV into ``(X, y)`` for tuneta (L4 + Q-B + Q-C).

    Steps:

    1. Resolve the segment's symbol universe via :func:`universe_for_segment`
       (PRD Q3 default source = ``etf_holdings``).
    2. For each symbol, call ``fetcher(symbol, start=as_of - horizon_years,
       end=as_of)`` to get a per-symbol OHLCV DataFrame.
    3. Concatenate into a single DataFrame indexed by ``MultiIndex[(date,
       symbol)]`` with OHLCV columns.
    4. Compute ``y`` per ``(date, symbol)`` as the forward cumulative return
       over ``forward_horizon_bars`` business days: ``close[t + horizon] /
       close[t] - 1`` (Q-B B3).
    5. Drop the tail rows where ``y`` is NaN (the last ``forward_horizon_bars``
       rows per symbol have no forward return defined).

    Parameters
    ----------
    segment
        GICS sector name (e.g. ``"Information Technology"``).
    as_of
        End of the fold window (inclusive). Tail rows beyond this date are
        unreachable; the window is ``[as_of - horizon_years, as_of]``.
    horizon_years
        Length of the fold window in years (default :data:`DEFAULT_HORIZON_YEARS`).
    forward_horizon_bars
        Forward-return horizon in business days (default
        :data:`DEFAULT_FORWARD_HORIZON_BARS`, which matches
        :attr:`EntryExitRule.max_holding_bars`).
    fetcher
        Injectable OHLCV fetcher with signature
        ``fetcher(symbol, *, start: date, end: date) -> pd.DataFrame`` (OHLCV
        columns, date index). ``None`` (default) lazy-imports techtrade's
        ``fmp_cached``-backed fetcher -- only the network path of the function.
        Tests inject a synthetic fetcher to stay offline.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.Series]
        ``X`` is the MultiIndex OHLCV frame ready for ``tuneta.fit``; ``y`` is
        the same-indexed forward-cumulative-return series.

    Notes
    -----
    Empty universe (resolver returns ``[]``) yields empty ``X`` and ``y`` --
    callers handle the degenerate case rather than relying on a raise. A single
    symbol's fetch failure is logged and the symbol is skipped; the pool keeps
    going so one bad data point cannot abort an entire tune.
    """
    symbols = list(universe_for_segment(segment))
    cols = list(_OHLCV_COLS)
    if not symbols:
        return _empty_pool(cols)

    start = _start_for(as_of, horizon_years)
    use_fetcher = fetcher if fetcher is not None else _default_fetcher()

    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        try:
            df = use_fetcher(symbol, start=start, end=as_of)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the pool
            logger.warning("sector_ohlcv: %s fetch failed: %s", symbol, exc)
            continue
        if df is None or df.empty:
            continue
        df = df[[c for c in cols if c in df.columns]].copy()
        df.index.name = "date"
        df["symbol"] = symbol
        frames.append(df.set_index("symbol", append=True))

    if not frames:
        return _empty_pool(cols)

    X = pd.concat(frames).sort_index()
    # Forward cumulative return per symbol: close.shift(-horizon) / close - 1.
    # unstack -> per-symbol column -> shift within column -> stack back to long.
    closes = X["close"].unstack("symbol")
    forward = closes.shift(-forward_horizon_bars) / closes - 1.0
    y = forward.stack(future_stack=True).reorder_levels(["date", "symbol"]).sort_index()
    y.name = "y"
    # Align X to y's index (which has dropped the tail NaN rows).
    y = y.dropna()
    X = X.loc[y.index]
    return X, y


def _empty_pool(cols: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    """Build the canonical empty ``(X, y)`` pair for a degenerate universe.

    Centralised so the empty-frame shape (column order, index names, y dtype/name)
    stays in sync between the two early-return paths in :func:`pool_sector_ohlcv`.
    """
    empty_idx = pd.MultiIndex.from_tuples([], names=["date", "symbol"])
    X = pd.DataFrame(columns=cols, index=empty_idx)
    y = pd.Series([], index=empty_idx, dtype="float64", name="y")
    return X, y


def _start_for(as_of: date, horizon_years: int) -> date:
    """Subtract ``horizon_years`` from ``as_of`` (Feb-29 safe).

    Mirrors :func:`openbb_techtrade.validation.backtest_bridge._start_date`: when
    ``as_of`` is Feb 29 and the target year is non-leap, fall back to March 1.
    """
    try:
        return as_of.replace(year=as_of.year - horizon_years)
    except ValueError:
        return date(as_of.year - horizon_years, 3, 1)


def _default_fetcher() -> Fetcher:
    """Build the production OHLCV fetcher backed by ``obb.equity.price.historical``.

    Production callers get this; tests inject ``fetcher=`` and never reach here.
    ``openbb`` is imported lazily so importing :mod:`sector_ohlcv` does not pull
    in the platform (and therefore does not depend on ``fmp_cached`` being
    configured) on a bare ``import openbb_techtrade.tuning.sector_ohlcv``.
    """

    def _fetch(symbol: str, *, start: date, end: date) -> pd.DataFrame:
        from openbb import obb  # noqa: PLC0415 - lazy on purpose

        obj = obb.equity.price.historical(
            symbol=symbol,
            start_date=str(start),
            end_date=str(end),
            provider="fmp_cached",
        )
        df = obj.to_dataframe()
        # Normalise to lowercase OHLCV columns + a date index. obb usually
        # returns exactly this shape, but be defensive against provider variation.
        df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df = df.set_index("date")
        return df

    return _fetch
