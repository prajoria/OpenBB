"""``intraday_drift`` — pure intraday strategy calculations.

Consumes a long :class:`pandas.DataFrame` of hourly OHLC bars (columns:
``timestamp``, ``symbol``, ``open``, ``close``) and produces per-stock-day
observations plus a :class:`DriftSummary` rollup.

Entry price  = ``open`` of the noon (12:00 America/New_York) bar.
Exit price   = ``close`` of the 15:00 America/New_York bar.
A stock-day is included only when **both** bars are present and every price
is strictly positive.  Ties (exit == entry) are losses.

Input contract
--------------
``open`` and ``close`` in *bars* must be **adjusted** prices (split- and
dividend-adjusted OHLC as delivered by the data provider).  No further
adjustment is applied here; the caller is responsible for ensuring the
prices are on a consistent, comparable scale across the full history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

_NY = "America/New_York"
_ENTRY_HOUR = 12
_EXIT_HOUR = 15


@dataclass(frozen=True)
class DriftSummary:
    """Immutable rollup of intraday-drift observations."""

    start_session: date
    end_session: date
    sessions: int
    symbols_observed: int
    valid_stock_days: int
    expected_stock_days: int
    coverage_pct: float
    stock_day_win_rate_pct: float
    basket_day_win_rate_pct: float
    mean_stock_day_return_pct: float
    median_stock_day_return_pct: float
    cumulative_basket_return_pct: float


def build_observations(bars: pd.DataFrame) -> pd.DataFrame:
    """Return one row per complete stock-day from *bars*.

    Parameters
    ----------
    bars:
        Long DataFrame with columns ``timestamp``, ``symbol``, ``open``,
        ``close``.

        **Timestamp handling** — ``timestamp`` may be either tz-naive or
        tz-aware:

        * **Tz-naive**: assumed to already represent wall-clock time in
          America/New_York and localised directly with
          ``tz_localize("America/New_York")``.  No hour offset is applied.
        * **Tz-aware**: converted to America/New_York with
          ``tz_convert("America/New_York")`` before hour selection, so bars
          originally stamped in any timezone (e.g. UTC, Pacific) are correctly
          mapped to their New York hour.

        ``open`` and ``close`` must be **adjusted** prices (split- and
        dividend-adjusted OHLC).  No further adjustment is applied here.

    Returns
    -------
    pandas.DataFrame
        Columns: ``session``, ``symbol``, ``entry_price``, ``exit_price``,
        ``return``, ``win``, sorted by ``session, symbol``.

    Raises
    ------
    ValueError
        If any of the required columns are absent, or if duplicate hour-12 or
        hour-15 bars exist for the same ``session × symbol`` pair (which would
        otherwise silently inflate observations via a Cartesian join).
    """
    required = {"timestamp", "symbol", "open", "close"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"bars missing required columns: {sorted(missing)}")

    df = bars[list(required)].copy()

    # Normalise timestamps to America/New_York
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(_NY)
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(_NY)

    df["_hour"] = df["timestamp"].dt.hour
    df["session"] = df["timestamp"].dt.date

    # Drop non-positive prices before splitting into entry/exit
    df = df[(df["open"] > 0) & (df["close"] > 0)]

    entry = (
        df[df["_hour"] == _ENTRY_HOUR][["session", "symbol", "open"]]
        .rename(columns={"open": "entry_price"})
    )
    exit_ = (
        df[df["_hour"] == _EXIT_HOUR][["session", "symbol", "close"]]
        .rename(columns={"close": "exit_price"})
    )

    # Guard: duplicate bars for the same session×symbol×hour are a data error.
    # Silently taking the first would Cartesian-inflate the join; raise loudly.
    dup_entry = entry[entry.duplicated(subset=["session", "symbol"], keep=False)]
    if not dup_entry.empty:
        pairs = sorted(set(zip(dup_entry["session"], dup_entry["symbol"])))
        raise ValueError(
            f"duplicate hour-{_ENTRY_HOUR} bars detected for session/symbol pairs: {pairs}"
        )
    dup_exit = exit_[exit_.duplicated(subset=["session", "symbol"], keep=False)]
    if not dup_exit.empty:
        pairs = sorted(set(zip(dup_exit["session"], dup_exit["symbol"])))
        raise ValueError(
            f"duplicate hour-{_EXIT_HOUR} bars detected for session/symbol pairs: {pairs}"
        )

    obs = entry.merge(exit_, on=["session", "symbol"], how="inner")
    obs["return"] = obs["exit_price"] / obs["entry_price"] - 1.0
    obs["win"] = obs["exit_price"] > obs["entry_price"]  # strict: ties are False

    obs = obs[["session", "symbol", "entry_price", "exit_price", "return", "win"]]
    obs = obs.sort_values(["session", "symbol"]).reset_index(drop=True)
    return obs


def summarize_observations(
    observations: pd.DataFrame,
    expected_symbols: int,
) -> DriftSummary:
    """Summarise *observations* into a :class:`DriftSummary`.

    Parameters
    ----------
    observations:
        DataFrame produced by :func:`build_observations` (or structurally
        equivalent) with columns ``session``, ``symbol``, ``return``, ``win``.
    expected_symbols:
        Number of symbols expected per session, used to compute coverage.

    Raises
    ------
    ValueError
        If *expected_symbols* is not positive, *observations* is empty,
        required columns (``session``, ``symbol``, ``return``, ``win``) are
        absent, or ``valid_stock_days`` exceeds ``expected_stock_days`` (which
        would indicate duplicate stock-day rows or an incorrect
        *expected_symbols*).
    """
    if expected_symbols <= 0:
        raise ValueError("expected_symbols must be positive")
    if observations.empty:
        raise ValueError("no complete stock-days to summarize")

    required_obs = {"session", "symbol", "return", "win"}
    missing_obs = required_obs.difference(observations.columns)
    if missing_obs:
        raise ValueError(
            f"observations missing required columns: {sorted(missing_obs)}"
        )

    sessions_arr = sorted(observations["session"].unique())
    start_session: date = sessions_arr[0]
    end_session: date = sessions_arr[-1]
    n_sessions = len(sessions_arr)
    symbols_observed = int(observations["symbol"].nunique())
    valid_stock_days = len(observations)
    expected_stock_days = n_sessions * expected_symbols

    if valid_stock_days > expected_stock_days:
        raise ValueError(
            f"valid_stock_days ({valid_stock_days}) exceeds expected_stock_days "
            f"({expected_stock_days}); check for duplicate rows or incorrect "
            f"expected_symbols={expected_symbols}"
        )

    coverage_pct = 100.0 * valid_stock_days / expected_stock_days
    stock_day_win_rate_pct = 100.0 * observations["win"].sum() / valid_stock_days

    # Equal-weight basket: mean return across symbols each session
    daily_basket = observations.groupby("session")["return"].mean()
    basket_wins = (daily_basket > 0).sum()
    basket_day_win_rate_pct = 100.0 * basket_wins / n_sessions

    mean_stock_day_return_pct = 100.0 * observations["return"].mean()
    median_stock_day_return_pct = 100.0 * float(observations["return"].median())
    cumulative_basket_return_pct = 100.0 * ((1.0 + daily_basket).prod() - 1.0)

    return DriftSummary(
        start_session=start_session,
        end_session=end_session,
        sessions=n_sessions,
        symbols_observed=symbols_observed,
        valid_stock_days=valid_stock_days,
        expected_stock_days=expected_stock_days,
        coverage_pct=coverage_pct,
        stock_day_win_rate_pct=stock_day_win_rate_pct,
        basket_day_win_rate_pct=basket_day_win_rate_pct,
        mean_stock_day_return_pct=mean_stock_day_return_pct,
        median_stock_day_return_pct=median_stock_day_return_pct,
        cumulative_basket_return_pct=cumulative_basket_return_pct,
    )
