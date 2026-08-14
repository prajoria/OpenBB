"""Top-50 S&P 500 intraday-drift study -- live data adapter and CLI.

Usage
-----
.. code-block:: powershell

    & ".venv_portfolio\\Scripts\\python.exe" \\
        openbb_platform/extensions/backtest/examples/top50_intraday_drift.py

    # Custom run
    & ".venv_portfolio\\Scripts\\python.exe" \\
        openbb_platform/extensions/backtest/examples/top50_intraday_drift.py \\
        --top 50 --months 6 --csv drift_obs.csv

Warnings
--------
* **Survivorship bias** -- constituents are fetched at run-time (current
  S&P 500 list).  Companies that *left* the index during the window are
  excluded; companies that *joined* after the window started are included.
* **No transaction costs** -- entry prices are adjusted opens; exit prices
  are adjusted closes.  Bid-ask spread, commission, and market-impact are
  not modelled.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import pandas as pd

# ---------------------------------------------------------------------------
# Public adapters
# ---------------------------------------------------------------------------

_SLICKCHARTS_URL = "https://www.slickcharts.com/sp500"
_SLICKCHARTS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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


def download_hourly_bars(
    symbols: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Download 60-minute adjusted OHLC bars for *symbols* over [*start*, *end*].

    Parameters
    ----------
    symbols:
        Ticker symbols accepted by Yahoo Finance.
    start, end:
        Inclusive date range.  An extra day is appended to *end* so that the
        yfinance ``end`` (exclusive) covers the full final session.

    Returns
    -------
    pandas.DataFrame
        Long frame with columns ``timestamp``, ``symbol``, ``open``, ``close``.

    Raises
    ------
    RuntimeError
        If yfinance is not installed.
    """
    try:
        import yfinance as yf  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "yfinance is required -- install it with: pip install yfinance"
        ) from exc

    raw = yf.download(
        tickers=symbols,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="60m",
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame(columns=["timestamp", "symbol", "open", "close"])

    # yfinance returns flat columns for a single-ticker download; promote to MultiIndex.
    if not isinstance(raw.columns, pd.MultiIndex):
        if len(symbols) != 1:
            raise RuntimeError(
                "download_hourly_bars: unexpected flat columns for a multi-ticker download"
            )
        raw = _promote_single_ticker_columns(raw, symbols[0])

    return normalize_yfinance_bars(raw)


# ---------------------------------------------------------------------------
# run_study
# ---------------------------------------------------------------------------


def run_study(
    count: int = 50,
    months: int = 6,
) -> tuple[pd.DataFrame, object, list[str]]:
    """Execute the full intraday-drift study and return results.

    Parameters
    ----------
    count:
        Number of top-weighted S&P 500 symbols to study.
    months:
        Approximate look-back in calendar months.

    Returns
    -------
    tuple
        ``(observations, summary, missing_symbols)`` where

        * *observations* is the long DataFrame from :func:`build_observations`,
        * *summary* is the :class:`~openbb_backtest.strategies.intraday_drift.DriftSummary`,
        * *missing_symbols* is the list of requested symbols with zero valid stock-days.
    """
    import os

    # Make openbb_backtest importable when run as a script
    _backtest_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if _backtest_root not in sys.path:
        sys.path.insert(0, _backtest_root)

    from openbb_backtest.strategies.intraday_drift import (  # noqa: PLC0415
        build_observations,
        summarize_observations,
    )

    end_date = date.today()
    # Subtract ~months calendar months
    m = end_date.month - months
    y = end_date.year
    while m <= 0:
        m += 12
        y -= 1
    start_date = date(y, m, 1)

    symbols = fetch_top_symbols(count)
    bars = download_hourly_bars(symbols, start_date, end_date)

    if bars.empty:
        raise RuntimeError(
            "No bars downloaded -- check network access and symbol list."
        )

    observations = build_observations(bars)

    observed_syms = set(observations["symbol"].unique())
    missing_symbols = [s for s in symbols if s not in observed_syms]

    summary = summarize_observations(observations, expected_symbols=count)
    return observations, summary, missing_symbols


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point.  Returns 0 on success, 1 on error."""
    parser = argparse.ArgumentParser(
        prog="top50_intraday_drift",
        description="Run the top-50 S&P 500 intraday-drift study.",
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
        help="Approximate look-back in calendar months (default: 6).",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        default=None,
        help="Write observation rows (not raw bars) to this CSV path.",
    )
    args = parser.parse_args(argv)

    try:
        observations, summary, missing_symbols = run_study(
            count=args.top,
            months=args.months,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    sep = "-" * 60
    print(sep)
    print("  Top-50 S&P 500 Intraday Drift Study")
    print(sep)
    print(f"  Actual first session : {summary.start_session}")
    print(f"  Actual last session  : {summary.end_session}")
    print(f"  Sessions observed    : {summary.sessions}")
    print(f"  Symbols requested    : {args.top}")
    print(f"  Symbols observed     : {summary.symbols_observed}")
    print(f"  Valid stock-days     : {summary.valid_stock_days}")
    print(f"  Expected stock-days  : {summary.expected_stock_days}")
    print(f"  Coverage             : {summary.coverage_pct:.1f}%")
    print(sep)
    print(f"  Stock-day accuracy   : {summary.stock_day_win_rate_pct:.2f}%")
    print(f"  Basket-day accuracy  : {summary.basket_day_win_rate_pct:.2f}%")
    print(sep)
    print(f"  Mean stock-day ret   : {summary.mean_stock_day_return_pct:.4f}%")
    print(f"  Median stock-day ret : {summary.median_stock_day_return_pct:.4f}%")
    print(f"  Cumul. basket ret    : {summary.cumulative_basket_return_pct:.4f}%")
    print(sep)

    if missing_symbols:
        print(
            f"  Missing symbols ({len(missing_symbols)}) : "
            + ", ".join(missing_symbols[:20])
            + (" ..." if len(missing_symbols) > 20 else "")
        )
        print(sep)

    print()
    print(
        "  [!] SURVIVORSHIP BIAS -- constituents are the current S&P 500 list."
        " Companies that LEFT the index during the window are excluded;"
        " companies that JOINED after the window started are included."
    )
    print(
        "  [!] NO TRANSACTION COSTS -- entry price is the adjusted open at"
        " noon ET; exit price is the adjusted close at 15:00 ET."
        " Spread, commission, and market-impact are not modelled."
    )

    if args.csv:
        observations.to_csv(args.csv, index=False)
        print(f"\n  Observations written to: {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
