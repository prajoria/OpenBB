"""Top-50 S&P 500 intraday-drift study — live data adapter and CLI.

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
* **Survivorship bias** — constituents are fetched at run-time (current
  list), so the study excludes companies that left the S&P 500 during the
  window and includes companies that joined after the window started.
* **No transaction costs** — entry and exit prices are adjusted closes;
  bid-ask spread, commission, and market-impact are not modelled.
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
_FALLBACK_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Transparent, checked fallback: top-50 S&P 500 constituents by weight as of
# August 2026.  Used only when Slickcharts and Wikipedia both block automated
# requests.  Order preserves approximate weight rank; dots converted to Yahoo
# dashes.  Provenance: manually transcribed from
# https://www.slickcharts.com/sp500 (public page, 2026-08-13).
_FALLBACK_TOP50 = [
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "GOOGL",
    "GOOG",
    "TSLA",
    "BRK-B",
    "AVGO",
    "JPM",
    "LLY",
    "V",
    "COST",
    "UNH",
    "MA",
    "NFLX",
    "XOM",
    "WMT",
    "ORCL",
    "PG",
    "ABBV",
    "JNJ",
    "HD",
    "CRM",
    "BAC",
    "CVX",
    "TMUS",
    "AMD",
    "MRK",
    "KO",
    "PEP",
    "ACN",
    "NOW",
    "ADBE",
    "IBM",
    "WFC",
    "PM",
    "MS",
    "GS",
    "DIS",
    "LIN",
    "ISRG",
    "TXN",
    "MCD",
    "GE",
    "RTX",
    "UBER",
    "CAT",
    "INTU",
]


def fetch_top_symbols(count: int = 50) -> list[str]:
    """Return the top-*count* S&P 500 symbols ordered by index weight.

    Tries Slickcharts first, then Wikipedia, then a static fallback.  Any
    dot in a ticker (e.g. ``BRK.B``) is replaced with a dash (``BRK-B``) so
    the symbol is valid for Yahoo Finance.

    Parameters
    ----------
    count:
        Number of symbols to return (≥ 1).

    Returns
    -------
    list[str]
        Exactly *count* symbols, ordered by descending weight.

    Raises
    ------
    ValueError
        If no source returns at least *count* distinct symbols.
    """
    symbols = _try_slickcharts(count) or _try_wikipedia(count) or []
    if len(symbols) < count:
        print(
            f"[warn] live sources returned {len(symbols)} symbol(s); "
            f"padding from static fallback list (provenance: "
            f"slickcharts.com 2026-08-13).",
            file=sys.stderr,
        )
        seen = set(symbols)
        for s in _FALLBACK_TOP50:
            if s not in seen:
                symbols.append(s)
                seen.add(s)
            if len(symbols) >= count:
                break

    if len(symbols) < count:
        raise ValueError(
            f"fetch_top_symbols: needed {count} symbols but only found "
            f"{len(symbols)} across all sources"
        )

    return symbols[:count]


def _try_slickcharts(count: int) -> list[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        tables = pd.read_html(
            _SLICKCHARTS_URL, storage_options={"User-Agent": headers["User-Agent"]}
        )
        for tbl in tables:
            if "Symbol" in tbl.columns and "Weight" in tbl.columns:
                syms = [
                    str(s).replace(".", "-") for s in tbl["Symbol"].dropna().tolist()
                ]
                if len(syms) >= count:
                    print(
                        f"[info] constituents sourced from {_SLICKCHARTS_URL}",
                        file=sys.stderr,
                    )
                    return syms
    except Exception as exc:  # noqa: BLE001
        print(
            f"[warn] Slickcharts unavailable ({exc}); trying Wikipedia.",
            file=sys.stderr,
        )
    return []


def _try_wikipedia(count: int) -> list[str]:
    try:
        tables = pd.read_html(_FALLBACK_URL)
        for tbl in tables:
            if "Symbol" in tbl.columns:
                syms = [
                    str(s).replace(".", "-") for s in tbl["Symbol"].dropna().tolist()
                ]
                if len(syms) >= count:
                    print(
                        f"[info] constituents sourced from {_FALLBACK_URL}",
                        file=sys.stderr,
                    )
                    return syms
    except Exception as exc:  # noqa: BLE001
        print(
            f"[warn] Wikipedia unavailable ({exc}); falling back to static list.",
            file=sys.stderr,
        )
    return []


def normalize_yfinance_bars(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance wide multi-index frame to the long contract expected by Task 1.

    Parameters
    ----------
    raw:
        Wide DataFrame with a two-level ``MultiIndex`` on columns:
        ``(price_field, symbol)`` or ``(symbol, price_field)`` — both
        orderings are handled.  The index must be a ``DatetimeIndex``
        (tz-aware or tz-naive).

    Returns
    -------
    pandas.DataFrame
        Long frame with columns ``timestamp``, ``symbol``, ``open``, ``close``
        where ``open`` and ``close`` are adjusted prices and ``timestamp``
        preserves the original timezone from yfinance (UTC).
    """
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError(
            "normalize_yfinance_bars: raw must have a MultiIndex on columns"
        )

    lvl0 = list(raw.columns.get_level_values(0).unique())

    # yfinance ≥0.2 returns (price_field, symbol); older versions and
    # group_by="ticker" return (symbol, price_field)
    price_fields = {"Open", "High", "Low", "Close", "Volume"}
    if lvl0[0] in price_fields:
        # (price_field, symbol) layout — stack symbols into a column
        raw = raw.stack(level=1, future_stack=True).reset_index()
    else:
        # (symbol, price_field) layout — stack price fields, symbols become column
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
    # yfinance uses 'ticker'; fixtures produce 'level_1' (or 'level_0' if
    # the symbol was the first stacked level).
    for _sym_candidate in ("ticker", "level_1"):
        if _sym_candidate in raw.columns and "symbol" not in raw.columns:
            raw = raw.rename(columns={_sym_candidate: "symbol"})

    raw = raw[["timestamp", "symbol", "open", "close"]].copy()
    raw = raw.dropna(subset=["open", "close"])
    raw = raw.reset_index(drop=True)
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
            "yfinance is required — install it with: pip install yfinance"
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
        * *missing_symbols* is the list of requested symbols that produced
          zero valid stock-days.
    """
    import os
    import sys

    # Make openbb_backtest importable when run as a script
    _backtest_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if _backtest_root not in sys.path:
        sys.path.insert(0, _backtest_root)

    from openbb_backtest.strategies.intraday_drift import (  # noqa: PLC0415
        build_observations,
        summarize_observations,
    )

    end_date = date.today()
    start_date = date(end_date.year, end_date.month, 1)
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
        raise RuntimeError("No bars downloaded — check network access and symbol list.")

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
        "  [!] SURVIVORSHIP BIAS -- constituents are the current S&P 500 list;"
        " companies that left the index during the window are excluded."
    )
    print(
        "  [!] NO TRANSACTION COSTS -- entry/exit prices are adjusted closes;"
        " spread, commission, and market-impact are not modelled."
    )

    if args.csv:
        observations.to_csv(args.csv, index=False)
        print(f"\n  Observations written to: {args.csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
