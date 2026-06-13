"""Per-session cross-sectional pipeline runner (component 05, §2).

:func:`pipeline` walks the trading calendar one session at a time and, at each
session, builds a point-in-time trailing window for every :class:`Factor` and
evaluates it cross-sectionally. The result is a :class:`FactorPanel` with one
row per ``(session, symbol)`` and one column per factor.

It is **look-ahead-free by construction**: each factor's window is fetched with
``feed.history(symbols, end=session, lookback=window_length)``, so only bars at
or before the current session are ever visible, and point-in-time fundamentals
are joined via ``feed.as_of(symbol, field, session)``. The investable universe
may be static (a fixed symbol list) or a callable resolved per session for
survivorship-safe membership (e.g. ``bundle.universe_at``).

See ``docs/designs/backtest-design/05-event-driven-engine.md`` §2.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

import pandas as pd

from openbb_backtest.interfaces import DataFeed
from openbb_backtest.pipeline.factor import Factor
from openbb_backtest.pipeline.panel import FactorPanel

# Columns delivered by ``DataFeed.history``; any other declared factor input is
# treated as a point-in-time fundamental joined via ``DataFeed.as_of``.
_MARKET_INPUTS = frozenset({"open", "high", "low", "close", "volume", "adj_factor"})

Universe = Sequence[str] | Callable[[pd.Timestamp], Sequence[str]]


def _resolve_universe(universe: Universe, when: pd.Timestamp) -> list[str]:
    """Resolve the investable symbols at ``when`` (static list or callable)."""
    members = universe(when) if callable(universe) else universe
    return list(members)


def _attach_fundamentals(
    window: pd.DataFrame,
    factor: Factor,
    feed: DataFeed,
    session: pd.Timestamp,
    symbols: list[str],
) -> pd.DataFrame:
    """Join any non-market factor inputs as point-in-time ``as_of`` columns.

    For each declared input that is not an OHLCV column, the latest value
    available at ``session`` is looked up per symbol and broadcast across that
    symbol's window rows (``NaN`` when no value is yet available — never a
    look-ahead-biased fill).
    """
    fundamental_inputs = [c for c in factor.inputs if c not in _MARKET_INPUTS]
    if not fundamental_inputs or window.empty:
        return window
    window = window.copy()
    for field in fundamental_inputs:
        per_symbol = {}
        for sym in symbols:
            value = feed.as_of(sym, field, session)
            per_symbol[sym] = float("nan") if value is None else value
        window[field] = window["symbol"].map(per_symbol)
    return window


def pipeline(
    factors: Sequence[Factor],
    universe: Universe,
    start: date,
    end: date,
    feed: DataFeed,
) -> FactorPanel:
    """Run ``factors`` cross-sectionally per session over ``[start, end]``.

    Parameters
    ----------
    factors
        Concrete :class:`Factor` instances to evaluate each session.
    universe
        Either a fixed symbol list or a callable ``universe(when) -> symbols``
        resolved per session (for survivorship-safe point-in-time membership).
    start, end
        Inclusive calendar bounds; sessions come from ``feed.sessions``.
    feed
        A point-in-time :class:`~openbb_backtest.interfaces.DataFeed`.

    Returns
    -------
    FactorPanel
        ``(date, asset)`` MultiIndex with one column per factor. Assets present
        in the universe but lacking sufficient history resolve to ``NaN`` rather
        than being dropped, so the panel is a full per-session grid.

    Raises
    ------
    ValueError
        When the calendar yields no trading sessions in ``[start, end]``.
    """
    sessions = pd.DatetimeIndex(feed.sessions(start, end))
    if len(sessions) == 0:
        raise ValueError(f"no trading sessions in [{start}, {end}]")

    columns = [f.name for f in factors]
    dates_col: list[pd.Timestamp] = []
    assets_col: list[str] = []
    records: list[dict[str, float]] = []

    for sess in sessions:
        session = pd.Timestamp(sess)
        symbols = _resolve_universe(universe, session)
        if not symbols:
            continue

        per_factor: dict[str, pd.Series] = {}
        for factor in factors:
            window = feed.history(symbols, end=session, lookback=factor.window_length)
            window = _attach_fundamentals(window, factor, feed, session, symbols)
            per_factor[factor.name] = factor.compute(window)

        for sym in symbols:
            dates_col.append(session)
            assets_col.append(sym)
            records.append(
                {name: _value_for(values, sym) for name, values in per_factor.items()}
            )

    index = pd.MultiIndex.from_arrays([dates_col, assets_col], names=["date", "asset"])
    if records:
        frame = pd.DataFrame(records, index=index)[columns]
    else:
        frame = pd.DataFrame({c: [] for c in columns}, index=index)
    return FactorPanel.from_frame(frame)


def _value_for(values: pd.Series, symbol: str) -> float:
    """Factor value for ``symbol`` (``NaN`` when the factor produced none)."""
    if symbol in values.index:
        return float(values.loc[symbol])
    return float("nan")
