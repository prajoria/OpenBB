"""``intraday_drift`` — pure intraday strategy calculations.

Consumes a long :class:`pandas.DataFrame` of **30-minute** OHLC bars (columns:
``timestamp``, ``symbol``, ``open``, ``close``) and produces per-stock-day
observations plus a :class:`DriftSummary` rollup.

Bar-alignment contract
----------------------
US equity intraday bars from Yahoo Finance (and most vendors) are aligned to
the 09:30 America/New_York regular-session open, **not** to the top of the
hour.  A 60-minute grid is therefore ``09:30, 10:30, 11:30, 12:30, …`` and a
30-minute grid is ``09:30, 10:00, 10:30, …, 15:30``.  Selecting bars by hour
alone (``timestamp.hour == 12``) picks the **12:30** bar on a 60-minute grid —
09:30 Pacific, not the intended 09:00 Pacific.  This module therefore matches
the **exact wall-clock hour *and* minute** of the bar.

Entry price  = ``open`` of the bar stamped :data:`ENTRY_HOUR`:
:data:`ENTRY_MINUTE` (12:00 America/New_York — the 12:00–12:30 bar, i.e.
09:00 America/Los_Angeles).

Exit price   = ``close`` of the bar stamped :data:`EXIT_HOUR`:
:data:`EXIT_MINUTE` (15:30 America/New_York — the 15:30–16:00 bar, whose close
is the 16:00 regular-session close, i.e. 13:00 America/Los_Angeles).

A stock-day is included only when **both** bars are present and every price is
strictly positive.  Ties (exit == entry) are losses.

Currently-forming bars
----------------------
A session whose exit interval (``EXIT_HOUR:EXIT_MINUTE`` + :data:`BAR_MINUTES`)
has **not yet elapsed** as of the caller-supplied ``now`` is dropped, so a
partially-formed final bar can never be treated as a settled close.  See
:func:`filter_incomplete_exit_sessions`.

Input contract
--------------
``open`` and ``close`` in *bars* must be **adjusted** prices (split- and
dividend-adjusted OHLC as delivered by the data provider).  No further
adjustment is applied here; the caller is responsible for ensuring the
prices are on a consistent, comparable scale across the full history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

_NY = "America/New_York"

#: Wall-clock (America/New_York) hour of the entry bar.
ENTRY_HOUR = 12
#: Wall-clock (America/New_York) minute of the entry bar.
ENTRY_MINUTE = 0
#: Wall-clock (America/New_York) hour of the exit bar.
EXIT_HOUR = 15
#: Wall-clock (America/New_York) minute of the exit bar.
EXIT_MINUTE = 30
#: Duration of one bar in minutes; used to decide whether the exit bar closed.
BAR_MINUTES = 30


def _fmt_clock(hour: int, minute: int) -> str:
    """Return ``HH:MM`` for use in messages."""
    return f"{hour:02d}:{minute:02d}"


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


def exit_interval_end(
    session: date,
    exit_hour: int = EXIT_HOUR,
    exit_minute: int = EXIT_MINUTE,
    bar_minutes: int = BAR_MINUTES,
) -> pd.Timestamp:
    """Return the America/New_York instant at which *session*'s exit bar closes.

    Parameters
    ----------
    session:
        Calendar session date.
    exit_hour, exit_minute:
        Wall-clock start of the exit bar in America/New_York.
    bar_minutes:
        Bar duration in minutes.

    Returns
    -------
    pandas.Timestamp
        Tz-aware (America/New_York) end of the exit interval.  Localisation is
        per-session, so daylight-saving transitions are handled correctly.
    """
    start = pd.Timestamp(
        datetime.combine(session, time(exit_hour, exit_minute))
    ).tz_localize(_NY)
    return start + pd.Timedelta(minutes=bar_minutes)


def filter_incomplete_exit_sessions(
    observations: pd.DataFrame,
    now: datetime,
    exit_hour: int = EXIT_HOUR,
    exit_minute: int = EXIT_MINUTE,
    bar_minutes: int = BAR_MINUTES,
) -> pd.DataFrame:
    """Drop sessions whose exit bar has not finished forming as of *now*.

    A bar stamped ``15:30`` only represents a settled 16:00 close once
    ``15:30 + bar_minutes`` has elapsed.  Accepting it earlier would mix a
    partially-formed price into the study.

    Parameters
    ----------
    observations:
        Frame with a ``session`` column of :class:`datetime.date` values.
    now:
        **Timezone-aware** as-of instant.  Injected by the caller so the
        decision is deterministic and testable; this function never reads the
        system clock.
    exit_hour, exit_minute, bar_minutes:
        Exit-bar geometry; see :func:`exit_interval_end`.

    Returns
    -------
    pandas.DataFrame
        *observations* with incomplete-exit sessions removed, index reset.

    Raises
    ------
    ValueError
        If *now* is naive (no timezone) or ``session`` is absent.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(
            "now must be timezone-aware so exit-bar completion is unambiguous"
        )
    if observations.empty:
        return observations.reset_index(drop=True)
    if "session" not in observations.columns:
        raise ValueError("observations missing required columns: ['session']")

    now_ny = pd.Timestamp(now).tz_convert(_NY)
    ends = [
        exit_interval_end(s, exit_hour, exit_minute, bar_minutes)
        for s in observations["session"]
    ]
    complete = pd.Series(ends, index=observations.index) <= now_ny
    return observations[complete].reset_index(drop=True)


def build_observations(
    bars: pd.DataFrame,
    now: datetime | None = None,
    entry_hour: int = ENTRY_HOUR,
    entry_minute: int = ENTRY_MINUTE,
    exit_hour: int = EXIT_HOUR,
    exit_minute: int = EXIT_MINUTE,
    bar_minutes: int = BAR_MINUTES,
) -> pd.DataFrame:
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
          ``tz_convert("America/New_York")`` before bar selection, so bars
          originally stamped in any timezone (e.g. UTC, Pacific) are correctly
          mapped to their New York wall-clock time.

        ``open`` and ``close`` must be **adjusted** prices (split- and
        dividend-adjusted OHLC).  No further adjustment is applied here.
    now:
        **Timezone-aware** as-of instant used to discard sessions whose exit
        bar is still forming.  ``None`` (default) reads the current
        America/New_York time — the safe default for live runs.  Tests and
        reproducible pipelines should inject an explicit value.
    entry_hour, entry_minute:
        Exact America/New_York wall-clock time of the entry bar.  Defaults
        select the 12:00–12:30 bar (09:00 Pacific).
    exit_hour, exit_minute:
        Exact America/New_York wall-clock time of the exit bar.  Defaults
        select the 15:30–16:00 bar, whose close is the 16:00 regular-session
        close (13:00 Pacific).
    bar_minutes:
        Bar duration in minutes, used only for exit-bar completion.

    Returns
    -------
    pandas.DataFrame
        Columns: ``session``, ``symbol``, ``entry_price``, ``exit_price``,
        ``return``, ``win``, sorted by ``session, symbol``.

    Raises
    ------
    ValueError
        If any of the required columns are absent, if the bar geometry is
        invalid, or if duplicate entry/exit bars exist for the same
        ``session × symbol`` pair (which would otherwise silently inflate
        observations via a Cartesian join).
    """
    if not 0 <= entry_hour <= 23 or not 0 <= exit_hour <= 23:
        raise ValueError("entry_hour and exit_hour must be in [0, 23]")
    if not 0 <= entry_minute <= 59 or not 0 <= exit_minute <= 59:
        raise ValueError("entry_minute and exit_minute must be in [0, 59]")
    if bar_minutes <= 0:
        raise ValueError("bar_minutes must be positive")

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
    df["_minute"] = df["timestamp"].dt.minute
    df["session"] = df["timestamp"].dt.date

    # Drop non-positive prices before splitting into entry/exit
    df = df[(df["open"] > 0) & (df["close"] > 0)]

    entry_mask = (df["_hour"] == entry_hour) & (df["_minute"] == entry_minute)
    exit_mask = (df["_hour"] == exit_hour) & (df["_minute"] == exit_minute)

    entry = df[entry_mask][["session", "symbol", "open"]].rename(
        columns={"open": "entry_price"}
    )
    exit_ = df[exit_mask][["session", "symbol", "close"]].rename(
        columns={"close": "exit_price"}
    )

    # Guard: duplicate bars for the same session×symbol×time are a data error.
    # Silently taking the first would Cartesian-inflate the join; raise loudly.
    dup_entry = entry[entry.duplicated(subset=["session", "symbol"], keep=False)]
    if not dup_entry.empty:
        pairs = sorted(set(zip(dup_entry["session"], dup_entry["symbol"])))
        raise ValueError(
            f"duplicate {_fmt_clock(entry_hour, entry_minute)} entry bars "
            f"detected for session/symbol pairs: {pairs}"
        )
    dup_exit = exit_[exit_.duplicated(subset=["session", "symbol"], keep=False)]
    if not dup_exit.empty:
        pairs = sorted(set(zip(dup_exit["session"], dup_exit["symbol"])))
        raise ValueError(
            f"duplicate {_fmt_clock(exit_hour, exit_minute)} exit bars "
            f"detected for session/symbol pairs: {pairs}"
        )

    obs = entry.merge(exit_, on=["session", "symbol"], how="inner")
    obs["return"] = obs["exit_price"] / obs["entry_price"] - 1.0
    obs["win"] = obs["exit_price"] > obs["entry_price"]  # strict: ties are False

    obs = obs[["session", "symbol", "entry_price", "exit_price", "return", "win"]]
    obs = obs.sort_values(["session", "symbol"]).reset_index(drop=True)

    as_of = now if now is not None else datetime.now(tz=ZoneInfo(_NY))
    obs = filter_incomplete_exit_sessions(
        obs,
        as_of,
        exit_hour=exit_hour,
        exit_minute=exit_minute,
        bar_minutes=bar_minutes,
    )
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
