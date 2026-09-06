"""Top-50 S&P 500 intraday-drift study -- live data adapter and CLI.

Usage
-----
.. code-block:: powershell

    & ".venv_portfolio\\Scripts\\python.exe" \\
        openbb_platform/extensions/backtest/examples/top50_intraday_drift.py

    # Best-effort run over whatever intraday history the provider still holds
    & ".venv_portfolio\\Scripts\\python.exe" \\
        openbb_platform/extensions/backtest/examples/top50_intraday_drift.py \\
        --top 50 --months 6 --allow-partial-window --csv drift_obs.csv

Bar geometry
------------
Yahoo Finance intraday bars are aligned to the 09:30 America/New_York
regular-session open, so a 60-minute grid runs ``09:30, 10:30, 11:30,
12:30, …``.  There is **no 12:00 bar on a 60-minute grid**; selecting
``hour == 12`` would silently pick 12:30 ET (09:30 Pacific).  This script
therefore downloads **30-minute** bars (``interval="30m"``) and the pure layer
matches the exact wall-clock entry time 12:00 ET (09:00 Pacific) and exit time
15:30 ET (the 15:30–16:00 bar, whose close is the 16:00 regular-session close,
13:00 Pacific).

Warnings
--------
* **Provider retention** -- Yahoo Finance serves only ~60 calendar days of
  30-minute bars.  A default ``--months 6`` run therefore **fails loudly**
  rather than silently reporting a much shorter window as a six-month result.
  Pass ``--allow-partial-window`` to accept a clearly labelled best-effort
  PARTIAL WINDOW run.
* **Survivorship bias** -- constituents are fetched at run-time (current
  S&P 500 list).  Companies that *left* the index during the window are
  excluded; companies that *joined* after the window started are included.
* **No transaction costs** -- entry prices are adjusted opens; exit prices
  are adjusted closes.  Bid-ask spread, commission, and market-impact are
  not modelled.
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pandas as pd

if TYPE_CHECKING:
    from openbb_backtest.strategies.intraday_drift import DriftSummary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SLICKCHARTS_URL = "https://www.slickcharts.com/sp500"
_SLICKCHARTS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_NY = "America/New_York"

#: Bar interval requested from Yahoo Finance.  30 minutes is the coarsest grid
#: that contains a bar starting exactly at 12:00 ET (09:00 Pacific).
INTRADAY_INTERVAL = "30m"

#: Yahoo Finance serves roughly this many calendar days of 30-minute history.
YF_INTRADAY_RETENTION_DAYS = 60

#: Yahoo rejects an intraday request whose *start* is beyond retention, so the
#: download is chunked into windows no wider than this (anchored at the end).
YF_MAX_CHUNK_DAYS = 59

#: Slack allowed between the requested start and the earliest returned session
#: to absorb weekends/holidays before the window is declared partial.
WINDOW_TOLERANCE_DAYS = 7


@dataclass(frozen=True)
class StudyResult:
    """Everything the CLI needs to print an honest report."""

    observations: pd.DataFrame
    summary: DriftSummary
    missing_symbols: list[str]
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    partial_window: bool
    tolerance_days: int


# ---------------------------------------------------------------------------
# Constituent source
# ---------------------------------------------------------------------------


def _parse_weight(val) -> float:
    """Coerce a weight value to float.

    Accepts numeric values and percentage strings such as ``"7.12%"``.
    Returns ``-1.0`` for unparseable values so they sort last.
    """
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).rstrip("%").strip())
    except (ValueError, AttributeError):
        return -1.0


def fetch_top_symbols(count: int = 50) -> list[str]:
    """Return the top-*count* S&P 500 symbols ordered by descending index weight.

    Fetches the constituent table from Slickcharts using an explicit browser
    User-Agent.  Parses the ``Weight`` column robustly (numeric or percentage
    string), sorts descending, and deduplicates.  Dots in tickers are replaced
    with dashes (e.g. ``BRK.B`` -> ``BRK-B``) for Yahoo Finance compatibility.

    Parameters
    ----------
    count:
        Number of symbols to return (>= 1).

    Returns
    -------
    list[str]
        Exactly *count* symbols, ordered by descending weight.

    Raises
    ------
    RuntimeError
        If Slickcharts cannot provide at least *count* distinct weighted
        symbols.  No fallback is attempted; stale or unweighted sources
        would silently bias the study.
    """
    try:
        tables = pd.read_html(
            _SLICKCHARTS_URL,
            storage_options={"User-Agent": _SLICKCHARTS_UA},
        )
    except Exception as exc:
        raise RuntimeError(
            f"fetch_top_symbols: Slickcharts request failed ({exc}). "
            f"Check network access or retry."
        ) from exc

    for tbl in tables:
        if "Symbol" not in tbl.columns or "Weight" not in tbl.columns:
            continue

        ranked = tbl[["Symbol", "Weight"]].dropna(subset=["Symbol"]).copy()
        ranked["_w"] = ranked["Weight"].map(_parse_weight)
        ranked = ranked.sort_values("_w", ascending=False)

        # Deduplicate preserving weight order
        seen: set[str] = set()
        symbols: list[str] = []
        for raw_sym in ranked["Symbol"]:
            sym = str(raw_sym).replace(".", "-")
            if sym not in seen:
                seen.add(sym)
                symbols.append(sym)

        if len(symbols) >= count:
            print(
                f"[info] constituents sourced from {_SLICKCHARTS_URL}",
                file=sys.stderr,
            )
            return symbols[:count]

    raise RuntimeError(
        f"fetch_top_symbols: Slickcharts returned fewer than {count} "
        f"weighted symbols. Cannot proceed without a current weight-ordered list."
    )


# ---------------------------------------------------------------------------
# Price source
# ---------------------------------------------------------------------------


def normalize_yfinance_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance wide multi-index frame to the long contract expected by Task 1.

    Parameters
    ----------
    raw:
        Wide DataFrame with a two-level ``MultiIndex`` on columns:
        ``(price_field, symbol)`` or ``(symbol, price_field)`` -- both
        orderings are handled.  The index must be a ``DatetimeIndex``
        (tz-aware or tz-naive).

    Returns
    -------
    pandas.DataFrame
        Long frame with columns ``timestamp``, ``symbol``, ``open``, ``close``
        where ``open`` and ``close`` are adjusted prices and ``timestamp``
        preserves the original timezone from yfinance.

    Raises
    ------
    ValueError
        If *raw* does not have a ``MultiIndex`` on columns.
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError(
            "normalize_yfinance_bars: raw must have a MultiIndex on columns"
        )

    lvl0 = list(raw.columns.get_level_values(0).unique())

    # yfinance >=0.2 returns (price_field, symbol); older versions and
    # group_by="ticker" return (symbol, price_field)
    price_fields = {"Open", "High", "Low", "Close", "Volume"}
    if lvl0[0] in price_fields:
        # (price_field, symbol) layout -- stack symbols into a column
        raw = raw.stack(level=1, future_stack=True).reset_index()
    else:
        # (symbol, price_field) layout -- stack symbols, price fields become columns
        raw = raw.stack(level=0, future_stack=True).reset_index()

    # Normalise all column names to lower-case
    raw.columns = [str(c).lower() for c in raw.columns]

    # Rename the timestamp column.
    # yfinance uses 'datetime'; unnamed index becomes 'level_0' after reset_index.
    for _ts_candidate in ("datetime", "date"):
        if _ts_candidate in raw.columns and "timestamp" not in raw.columns:
            raw = raw.rename(columns={_ts_candidate: "timestamp"})

    # For fixtures with unnamed datetime index, 'level_0' holds the timestamp.
    if "timestamp" not in raw.columns and "level_0" in raw.columns:
        raw = raw.rename(columns={"level_0": "timestamp"})

    # Rename the symbol column.
    # yfinance uses 'ticker'; fixtures produce 'level_1'.
    for _sym_candidate in ("ticker", "level_1"):
        if _sym_candidate in raw.columns and "symbol" not in raw.columns:
            raw = raw.rename(columns={_sym_candidate: "symbol"})

    raw = raw[["timestamp", "symbol", "open", "close"]].copy()
    raw = raw.dropna(subset=["open", "close"])
    raw = raw.reset_index(drop=True)
    return raw


def _promote_single_ticker_columns(
    raw: pd.DataFrame,
    symbol: str,
) -> pd.DataFrame:
    """Promote a flat-column single-ticker yfinance result to a MultiIndex frame.

    When ``yf.download`` is called with exactly one ticker, some yfinance
    versions return a flat ``Index`` (e.g. ``['Open', 'High', ...]``) instead
    of a ``MultiIndex``.  This helper wraps the flat columns into the expected
    ``(symbol, price_field)`` two-level ``MultiIndex`` so that
    :func:`normalize_yfinance_bars` can process it uniformly.

    Parameters
    ----------
    raw:
        DataFrame with a flat (non-multi) ``Index`` on columns.
    symbol:
        The ticker symbol to use as the outer level.

    Returns
    -------
    pandas.DataFrame
        Same data with a two-level ``MultiIndex`` columns ``(symbol, price_field)``.
    """
    raw = raw.copy()
    raw.columns = pd.MultiIndex.from_product([[symbol], raw.columns])
    return raw


def intraday_chunks(
    start: date,
    end_exclusive: date,
    max_chunk_days: int = YF_MAX_CHUNK_DAYS,
) -> list[tuple[date, date]]:
    """Split ``[start, end_exclusive)`` into end-anchored download windows.

    Yahoo rejects an intraday request whose *start* predates its retention
    horizon -- even when part of the requested range is inside it.  Chunking
    backwards from *end_exclusive* guarantees the most recent chunk is fully
    inside retention, so the maximum available history is actually returned.

    Parameters
    ----------
    start:
        Inclusive first calendar day of the requested window.
    end_exclusive:
        Exclusive last calendar day.
    max_chunk_days:
        Maximum width of a single chunk in calendar days (>= 1).

    Returns
    -------
    list[tuple[date, date]]
        ``(chunk_start, chunk_end_exclusive)`` pairs, newest first.

    Raises
    ------
    ValueError
        If *max_chunk_days* is not positive or the range is empty.
    """
    if max_chunk_days <= 0:
        raise ValueError("max_chunk_days must be positive")
    if end_exclusive <= start:
        raise ValueError(f"empty range: start={start} end_exclusive={end_exclusive}")

    chunks: list[tuple[date, date]] = []
    cursor = end_exclusive
    while cursor > start:
        chunk_start = max(start, cursor - timedelta(days=max_chunk_days))
        chunks.append((chunk_start, cursor))
        cursor = chunk_start
    return chunks


@contextmanager
def _quiet_yfinance():
    """Silence yfinance's ``possibly delisted`` noise for out-of-retention chunks.

    Chunks older than the provider's intraday retention horizon are *expected*
    to come back empty; yfinance logs them as download failures, which reads
    like a data error.  The emptiness is still surfaced by this module's own
    ``[info]`` lines and by the window-completeness check, so nothing is
    hidden -- only the misleading wording is suppressed, and the logger level
    is restored afterwards.
    """
    logger = logging.getLogger("yfinance")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(previous)


def download_intraday_bars(
    symbols: list[str],
    start: date,
    end: date,
    interval: str = INTRADAY_INTERVAL,
    max_chunk_days: int = YF_MAX_CHUNK_DAYS,
) -> pd.DataFrame:
    """Download adjusted intraday OHLC bars for *symbols* over [*start*, *end*].

    The default ``interval`` is ``"30m"``: Yahoo's 60-minute grid is anchored
    at 09:30 ET and therefore has **no 12:00 ET bar**, which is the exact entry
    time this study requires.

    Parameters
    ----------
    symbols:
        Ticker symbols accepted by Yahoo Finance.
    start, end:
        Inclusive date range.  An extra day is appended to *end* so that the
        yfinance ``end`` (exclusive) covers the full final session.
    interval:
        yfinance interval string.
    max_chunk_days:
        Width of each end-anchored download window; see :func:`intraday_chunks`.

    Returns
    -------
    pandas.DataFrame
        Long frame with columns ``timestamp``, ``symbol``, ``open``, ``close``.
        Empty when the provider returns nothing for the whole range.

    Raises
    ------
    RuntimeError
        If yfinance is not installed, or a multi-ticker download returns an
        unexpected flat column index.
    """
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is required -- install it with: pip install yfinance"
        ) from exc

    empty = pd.DataFrame(columns=["timestamp", "symbol", "open", "close"])
    frames: list[pd.DataFrame] = []

    for chunk_start, chunk_end in intraday_chunks(
        start, end + timedelta(days=1), max_chunk_days
    ):
        with _quiet_yfinance():
            raw = yf.download(
                tickers=symbols,
                start=chunk_start.isoformat(),
                end=chunk_end.isoformat(),
                interval=interval,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )

        if raw is None or raw.empty:
            print(
                f"[info] no {interval} bars for {chunk_start}..{chunk_end} "
                f"(beyond the provider's ~{YF_INTRADAY_RETENTION_DAYS}-day "
                f"intraday retention)",
                file=sys.stderr,
            )
            if frames:
                # Retention horizon reached; older chunks cannot succeed.
                break
            continue

        # yfinance returns flat columns for a single-ticker download.
        if not isinstance(raw.columns, pd.MultiIndex):
            if len(symbols) != 1:
                raise RuntimeError(
                    "download_intraday_bars: unexpected flat columns for a "
                    "multi-ticker download"
                )
            raw = _promote_single_ticker_columns(raw, symbols[0])

        frames.append(normalize_yfinance_bars(raw))

    if not frames:
        return empty

    bars = pd.concat(frames, ignore_index=True)
    bars = bars.drop_duplicates(subset=["timestamp", "symbol"], keep="first")
    bars = bars.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return bars


# ---------------------------------------------------------------------------
# Requested-window accounting
# ---------------------------------------------------------------------------


def compute_requested_window(
    months: int,
    today: date | None = None,
) -> tuple[date, date]:
    """Return ``(start, end)`` for a *months*-long look-back ending *today*.

    Parameters
    ----------
    months:
        Look-back in calendar months (>= 1).
    today:
        End of the window; defaults to :meth:`datetime.date.today`.

    Returns
    -------
    tuple[datetime.date, datetime.date]
        Inclusive ``(start, end)``.  ``start`` is the first day of the month
        *months* months before *today*.

    Raises
    ------
    ValueError
        If *months* is not positive.
    """
    if months <= 0:
        raise ValueError("months must be positive")
    end_date = today if today is not None else date.today()
    m = end_date.month - months
    y = end_date.year
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1), end_date


def assess_window_completeness(
    requested_start: date,
    actual_start: date,
    tolerance_days: int = WINDOW_TOLERANCE_DAYS,
) -> tuple[bool, int]:
    """Report whether the returned history actually covers the requested window.

    Parameters
    ----------
    requested_start:
        First calendar day the caller asked for.
    actual_start:
        Earliest session the provider actually returned.
    tolerance_days:
        Slack (calendar days) allowed for weekends/holidays before the window
        is declared partial.

    Returns
    -------
    tuple[bool, int]
        ``(is_partial, shortfall_days)`` where *shortfall_days* is
        ``actual_start - requested_start`` in calendar days (never negative).

    Raises
    ------
    ValueError
        If *tolerance_days* is negative.
    """
    if tolerance_days < 0:
        raise ValueError("tolerance_days must be non-negative")
    shortfall = max((actual_start - requested_start).days, 0)
    return shortfall > tolerance_days, shortfall


def enforce_window_completeness(
    requested_start: date,
    actual_start: date,
    allow_partial: bool,
    tolerance_days: int = WINDOW_TOLERANCE_DAYS,
) -> bool:
    """Fail loudly when the provider covered materially less than requested.

    Parameters
    ----------
    requested_start, actual_start, tolerance_days:
        See :func:`assess_window_completeness`.
    allow_partial:
        When ``True`` a short window is permitted and reported as partial
        instead of raising.

    Returns
    -------
    bool
        ``True`` when the run is a partial window (only reachable with
        *allow_partial*), ``False`` when the requested window was covered.

    Raises
    ------
    RuntimeError
        If the window is partial and *allow_partial* is ``False``.
    """
    is_partial, shortfall = assess_window_completeness(
        requested_start, actual_start, tolerance_days
    )
    if is_partial and not allow_partial:
        raise RuntimeError(
            f"INCOMPLETE WINDOW: requested history from {requested_start} but the "
            f"earliest session returned by the provider is {actual_start} "
            f"({shortfall} calendar days later; tolerance {tolerance_days} days). "
            f"Yahoo Finance retains only ~{YF_INTRADAY_RETENTION_DAYS} days of "
            f"{INTRADAY_INTERVAL} bars, so a multi-month {INTRADAY_INTERVAL} study "
            f"is not possible from this source. Re-run with --allow-partial-window "
            f"to accept a clearly labelled best-effort PARTIAL WINDOW result "
            f"(which must NOT be reported as a six-month answer), or use a "
            f"provider with deeper intraday history."
        )
    return is_partial


# ---------------------------------------------------------------------------
# run_study
# ---------------------------------------------------------------------------


def run_study(
    count: int = 50,
    months: int = 6,
    allow_partial_window: bool = False,
    now: datetime | None = None,
    tolerance_days: int = WINDOW_TOLERANCE_DAYS,
) -> StudyResult:
    """Execute the full intraday-drift study and return results.

    Parameters
    ----------
    count:
        Number of top-weighted S&P 500 symbols to study.
    months:
        Requested look-back in calendar months.
    allow_partial_window:
        Accept (and label) a window shorter than requested instead of failing.
    now:
        Timezone-aware as-of instant; defaults to the current
        America/New_York time.  Drives both the requested window and the
        currently-forming-bar filter, so injecting it makes the whole study
        reproducible.
    tolerance_days:
        Calendar-day slack before the window counts as partial.

    Returns
    -------
    StudyResult
        Observations, summary, missing symbols, and window accounting.

    Raises
    ------
    RuntimeError
        If no bars are returned, no complete stock-days survive, or the
        returned window is materially shorter than requested and
        *allow_partial_window* is ``False``.
    """
    import os  # noqa: PLC0415

    # Make openbb_backtest importable when run as a script
    _backtest_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if _backtest_root not in sys.path:
        sys.path.insert(0, _backtest_root)

    from openbb_backtest.strategies.intraday_drift import (  # noqa: PLC0415
        build_observations,
        summarize_observations,
    )

    as_of = now if now is not None else datetime.now(tz=ZoneInfo(_NY))
    if as_of.tzinfo is None or as_of.tzinfo.utcoffset(as_of) is None:
        raise ValueError("now must be timezone-aware")

    start_date, end_date = compute_requested_window(months, as_of.date())

    symbols = fetch_top_symbols(count)
    bars = download_intraday_bars(symbols, start_date, end_date)

    if bars.empty:
        raise RuntimeError(
            f"No {INTRADAY_INTERVAL} bars downloaded for {start_date}..{end_date} "
            f"-- check network access and symbol list. Yahoo Finance serves only "
            f"~{YF_INTRADAY_RETENTION_DAYS} days of {INTRADAY_INTERVAL} history."
        )

    observations = build_observations(bars, now=as_of)
    if observations.empty:
        raise RuntimeError(
            "No complete stock-days: every session was missing an entry or exit "
            "bar, or its exit bar had not finished forming."
        )

    actual_start = min(observations["session"])
    actual_end = max(observations["session"])
    partial_window = enforce_window_completeness(
        start_date, actual_start, allow_partial_window, tolerance_days
    )

    observed_syms = set(observations["symbol"].unique())
    missing_symbols = [s for s in symbols if s not in observed_syms]

    summary = summarize_observations(observations, expected_symbols=count)
    return StudyResult(
        observations=observations,
        summary=summary,
        missing_symbols=missing_symbols,
        requested_start=start_date,
        requested_end=end_date,
        actual_start=actual_start,
        actual_end=actual_end,
        partial_window=partial_window,
        tolerance_days=tolerance_days,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_report(result: StudyResult, requested_symbols: int) -> None:
    """Print the console report for *result*."""
    summary = result.summary
    sep = "-" * 68
    print(sep)
    print("  Top-50 S&P 500 Intraday Drift Study")
    print(sep)

    if result.partial_window:
        print("  *** PARTIAL WINDOW -- BEST-EFFORT RESULT, NOT A SIX-MONTH ANSWER ***")
        print(
            f"  Requested window     : {result.requested_start} .. "
            f"{result.requested_end}"
        )
        print(f"  Actual window        : {result.actual_start} .. {result.actual_end}")
        print(
            f"  Provider retains only ~{YF_INTRADAY_RETENTION_DAYS} days of "
            f"{INTRADAY_INTERVAL} bars; every percentage below describes ONLY "
            f"{result.actual_start} .. {result.actual_end}."
        )
        print(sep)
    else:
        print(
            f"  Requested window     : {result.requested_start} .. "
            f"{result.requested_end}"
        )

    print(f"  Actual first session : {summary.start_session}")
    print(f"  Actual last session  : {summary.end_session}")
    print(f"  Sessions observed    : {summary.sessions}")
    print(f"  Symbols requested    : {requested_symbols}")
    print(f"  Symbols observed     : {summary.symbols_observed}")
    print(f"  Valid stock-days     : {summary.valid_stock_days}")
    print(f"  Expected stock-days  : {summary.expected_stock_days}")
    print(f"  Coverage             : {summary.coverage_pct:.1f}%")
    print(sep)
    label = " (PARTIAL WINDOW)" if result.partial_window else ""
    print(f"  Stock-day accuracy   : {summary.stock_day_win_rate_pct:.2f}%{label}")
    print(f"  Basket-day accuracy  : {summary.basket_day_win_rate_pct:.2f}%{label}")
    print(sep)
    print(f"  Mean stock-day ret   : {summary.mean_stock_day_return_pct:.4f}%{label}")
    print(f"  Median stock-day ret : {summary.median_stock_day_return_pct:.4f}%{label}")
    print(
        f"  Cumul. basket ret    : {summary.cumulative_basket_return_pct:.4f}%{label}"
    )
    print(sep)

    if result.missing_symbols:
        print(
            f"  Missing symbols ({len(result.missing_symbols)}) : "
            + ", ".join(result.missing_symbols[:20])
            + (" ..." if len(result.missing_symbols) > 20 else "")
        )
        print(sep)

    print()
    if result.partial_window:
        print(
            "  [!] PARTIAL WINDOW -- the requested"
            f" {result.requested_start} .. {result.requested_end} window was NOT"
            f" available. These numbers cover {result.actual_start} .."
            f" {result.actual_end} only and must never be quoted as a"
            " six-month result."
        )
    print(
        "  [!] SURVIVORSHIP BIAS -- constituents are the current S&P 500 list."
        " Companies that LEFT the index during the window are excluded;"
        " companies that JOINED after the window started are included."
    )
    print(
        "  [!] NO TRANSACTION COSTS -- entry price is the adjusted open of the"
        " 12:00 ET 30-minute bar (09:00 PT); exit price is the adjusted close"
        " of the 15:30 ET 30-minute bar (16:00 ET session close, 13:00 PT)."
        " Spread, commission, and market-impact are not modelled."
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on success, 1 on error."""
    parser = argparse.ArgumentParser(
        prog="top50_intraday_drift",
        description=(
            "Run the top-50 S&P 500 intraday-drift study on 30-minute bars "
            "(entry 12:00 ET open, exit 15:30 ET bar close)."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        metavar="N",
        help="Number of top-weighted S&P 500 symbols to study (default: 50).",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        metavar="M",
        help=(
            "Requested look-back in calendar months (default: 6). Yahoo Finance "
            f"retains only ~{YF_INTRADAY_RETENTION_DAYS} days of "
            f"{INTRADAY_INTERVAL} bars, so anything beyond that fails unless "
            "--allow-partial-window is passed."
        ),
    )
    parser.add_argument(
        "--allow-partial-window",
        action="store_true",
        help=(
            "Permit a best-effort run over whatever intraday history the "
            "provider still holds. Output is labelled PARTIAL WINDOW with the "
            "actual dates and must not be reported as a six-month result."
        ),
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        default=None,
        help="Write observation rows (not raw bars) to this CSV path.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_study(
            count=args.top,
            months=args.months,
            allow_partial_window=args.allow_partial_window,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    _print_report(result, requested_symbols=args.top)

    if args.csv:
        result.observations.to_csv(args.csv, index=False)
        print(f"\n  Observations written to: {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
