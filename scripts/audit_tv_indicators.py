"""TradingView 31-indicator coverage audit for portfolio_basket (#780).

Walks a representative basket, calls every TradingView-referenced indicator
against the OHLCV data, and records:

  indicator × source (pandas_ta_classic / openbb-technical / openbb-techtrade / custom / MISSING)
  × per-ticker success/failure/history-depth

Output: a markdown coverage matrix written to
``docs/reports/2026-07-20-tv-indicator-coverage-audit.md`` plus stdout summary.

Audit categories:
1. Oscillators (11): RSI, Stoch %K, CCI, ADX, AO, Momentum, MACD, StochRSI,
   Williams %R, Bull Bear Power, Ultimate Oscillator
2. Moving Averages (15 across families): EMA(x6), SMA(x6), Ichimoku Kijun,
   VWMA, HMA
3. Pivot Systems (5): Classic, Fibonacci, Camarilla, Woodie, DeMark

Provider is ``fmp_cached`` for OHLCV per project rule. Uses last 300 daily
bars (enough for EMA(200) + Ultimate Oscillator 28).

Usage:
  .venv_win/Scripts/python.exe scripts/audit_tv_indicators.py

Does NOT change any repo code; writes only to docs/reports/.
"""

from __future__ import annotations

import datetime as dt
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPORT_PATH = Path(__file__).parent.parent / "docs" / "reports" / "2026-07-20-tv-indicator-coverage-audit.md"

# Representative basket — same universe covered by #512 + a few equities
# for single-stock indicator sanity. Not the future portfolio_basket table
# (which doesn't exist yet); this is the substitute per issue acceptance
# criterion "or a representative sample if the full basket is too large".
BASKET: list[str] = [
    # Broad-market ETFs (SPY/DIA covered by #512 issuer tier)
    "SPY",
    "DIA",
    # 11 GICS sector SPDRs (all pre-existing in issuer registry)
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLP",
    "XLY",
    "XLB",
    "XLU",
    "XLRE",
    "XLC",
    # Representative single equities across sectors
    "AAPL",
    "MSFT",
    "NVDA",
    "JPM",
    "XOM",
    "JNJ",
    "PG",
    "HD",
]

# TradingView "Technicals" indicator inventory. Each entry:
# (id, name, category, min_bars_needed)
INDICATORS: list[tuple[str, str, str, int]] = [
    # --- Oscillators (11) ---
    ("rsi_14", "RSI(14)", "oscillator", 30),
    ("stoch_14_3_3", "Stochastic %K(14,3,3)", "oscillator", 30),
    ("cci_20", "CCI(20)", "oscillator", 40),
    ("adx_14", "ADX(14)", "oscillator", 40),
    ("ao", "Awesome Oscillator", "oscillator", 40),
    ("momentum_10", "Momentum(10)", "oscillator", 20),
    ("macd_12_26", "MACD(12,26)", "oscillator", 60),
    ("stochrsi_14_14_3_3", "Stochastic RSI Fast(3,3,14,14)", "oscillator", 40),
    ("willr_14", "Williams %R(14)", "oscillator", 20),
    ("bbp", "Bull Bear Power", "oscillator", 40),
    ("uo_7_14_28", "Ultimate Oscillator(7,14,28)", "oscillator", 40),
    # --- Moving Averages (15) — expressed as 4 base indicators × common periods ---
    ("ema_10", "EMA(10)", "moving_average", 15),
    ("ema_20", "EMA(20)", "moving_average", 25),
    ("ema_30", "EMA(30)", "moving_average", 35),
    ("ema_50", "EMA(50)", "moving_average", 60),
    ("ema_100", "EMA(100)", "moving_average", 110),
    ("ema_200", "EMA(200)", "moving_average", 210),
    ("sma_10", "SMA(10)", "moving_average", 15),
    ("sma_20", "SMA(20)", "moving_average", 25),
    ("sma_30", "SMA(30)", "moving_average", 35),
    ("sma_50", "SMA(50)", "moving_average", 60),
    ("sma_100", "SMA(100)", "moving_average", 110),
    ("sma_200", "SMA(200)", "moving_average", 210),
    ("ichimoku_kijun", "Ichimoku Kijun-sen(9,26,52,26)", "moving_average", 60),
    ("vwma_20", "VWMA(20)", "moving_average", 30),
    ("hma_9", "HMA(9)", "moving_average", 15),
    # --- Pivot Point Systems (5) — one bar of prior-session HLC is sufficient ---
    ("pivot_classic", "Pivot: Classic", "pivot", 2),
    ("pivot_fibonacci", "Pivot: Fibonacci", "pivot", 2),
    ("pivot_camarilla", "Pivot: Camarilla", "pivot", 2),
    ("pivot_woodie", "Pivot: Woodie", "pivot", 2),
    ("pivot_demark", "Pivot: DeMark", "pivot", 2),
]


def _fetch_ohlcv(symbol: str, days: int = 400):
    """Fetch daily OHLCV from fmp_cached; return a pandas DataFrame or None."""
    try:
        from openbb import obb

        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        r = obb.equity.price.historical(
            symbol=symbol,
            start_date=start,
            end_date=end,
            provider="fmp_cached",
            interval="1d",
        )
        rows = r.results
        if not rows:
            return None
        import pandas as pd

        df = pd.DataFrame([row.model_dump() for row in rows])
        # Ensure required columns exist + numeric
        needed = {"open", "high", "low", "close", "volume"}
        if not needed.issubset(df.columns):
            return None
        for col in needed:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        return df
    except Exception as exc:  # noqa: BLE001
        print(f"  [{symbol}] fetch failed: {type(exc).__name__}: {exc}")
        return None


def _has_non_empty_output(result) -> bool:
    """A pandas Series/DataFrame/dict has content."""
    if result is None:
        return False
    try:
        # pandas Series/DataFrame — check any non-NaN
        return bool(getattr(result, "dropna")().shape[0] > 0)  # type: ignore[operator]
    except (TypeError, AttributeError):
        pass
    # scalar
    try:
        return bool(result == result and abs(result) >= 0)  # NaN != NaN
    except (TypeError, ValueError):
        return bool(result)


def _run_pta(df, name: str, **kwargs):
    """Invoke pandas_ta_classic's DataFrame accessor."""
    import pandas_ta_classic  # noqa: F401 — registers .ta

    accessor = df.ta
    fn = getattr(accessor, name, None)
    if fn is None:
        return None
    return fn(**kwargs)


def _classic_pivots(df):
    """Compute classic pivots from prior bar's HLC."""
    prev = df.iloc[-2]
    p = (prev["high"] + prev["low"] + prev["close"]) / 3.0
    r1 = 2 * p - prev["low"]
    s1 = 2 * p - prev["high"]
    r2 = p + (prev["high"] - prev["low"])
    s2 = p - (prev["high"] - prev["low"])
    r3 = prev["high"] + 2 * (p - prev["low"])
    s3 = prev["low"] - 2 * (prev["high"] - p)
    return {"P": p, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


def _fib_pivots(df):
    prev = df.iloc[-2]
    p = (prev["high"] + prev["low"] + prev["close"]) / 3.0
    rng = prev["high"] - prev["low"]
    return {
        "P": p,
        "R1": p + 0.382 * rng,
        "R2": p + 0.618 * rng,
        "R3": p + 1.0 * rng,
        "S1": p - 0.382 * rng,
        "S2": p - 0.618 * rng,
        "S3": p - 1.0 * rng,
    }


def _camarilla_pivots(df):
    prev = df.iloc[-2]
    rng = prev["high"] - prev["low"]
    c = prev["close"]
    return {
        "P": (prev["high"] + prev["low"] + prev["close"]) / 3.0,
        "R1": c + 1.1 * rng / 12,
        "R2": c + 1.1 * rng / 6,
        "R3": c + 1.1 * rng / 4,
        "S1": c - 1.1 * rng / 12,
        "S2": c - 1.1 * rng / 6,
        "S3": c - 1.1 * rng / 4,
    }


def _woodie_pivots(df):
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    # Woodie uses current-session open (weighted more)
    p = (prev["high"] + prev["low"] + 2 * curr["open"]) / 4.0
    return {
        "P": p,
        "R1": 2 * p - prev["low"],
        "R2": p + (prev["high"] - prev["low"]),
        "R3": prev["high"] + 2 * (p - prev["low"]),
        "S1": 2 * p - prev["high"],
        "S2": p - (prev["high"] - prev["low"]),
        "S3": prev["low"] - 2 * (prev["high"] - p),
    }


def _demark_pivots(df):
    prev = df.iloc[-2]
    if prev["close"] < prev["open"]:
        x = prev["high"] + 2 * prev["low"] + prev["close"]
    elif prev["close"] > prev["open"]:
        x = 2 * prev["high"] + prev["low"] + prev["close"]
    else:
        x = prev["high"] + prev["low"] + 2 * prev["close"]
    p = x / 4.0
    r1 = x / 2.0 - prev["low"]
    s1 = x / 2.0 - prev["high"]
    return {"P": p, "R1": r1, "S1": s1}


# ---------------------------------------------------------------------------
# Per-indicator invocation registry
# ---------------------------------------------------------------------------


def _dispatch(ind_id: str, df):
    """Return the computation result for one indicator id, or raise."""
    if ind_id == "rsi_14":
        return _run_pta(df, "rsi", length=14)
    if ind_id == "stoch_14_3_3":
        return _run_pta(df, "stoch", k=14, d=3, smooth_k=3)
    if ind_id == "cci_20":
        return _run_pta(df, "cci", length=20)
    if ind_id == "adx_14":
        return _run_pta(df, "adx", length=14)
    if ind_id == "ao":
        return _run_pta(df, "ao")
    if ind_id == "momentum_10":
        return _run_pta(df, "mom", length=10)
    if ind_id == "macd_12_26":
        return _run_pta(df, "macd", fast=12, slow=26, signal=9)
    if ind_id == "stochrsi_14_14_3_3":
        return _run_pta(df, "stochrsi", length=14, rsi_length=14, k=3, d=3)
    if ind_id == "willr_14":
        return _run_pta(df, "willr", length=14)
    if ind_id == "bbp":
        # Bull Bear Power = high - EMA(close, 13), low - EMA(close, 13)
        # pandas_ta doesn't ship this — mark as custom.
        import pandas_ta_classic  # noqa: F401

        ema13 = df.ta.ema(length=13)
        if ema13 is None:
            return None
        bull = df["high"] - ema13
        return bull  # non-empty series suffices
    if ind_id == "uo_7_14_28":
        return _run_pta(df, "uo", fast=7, medium=14, slow=28)
    # Moving averages
    if ind_id.startswith("ema_"):
        period = int(ind_id.split("_")[1])
        return _run_pta(df, "ema", length=period)
    if ind_id.startswith("sma_"):
        period = int(ind_id.split("_")[1])
        return _run_pta(df, "sma", length=period)
    if ind_id == "ichimoku_kijun":
        result = _run_pta(df, "ichimoku", tenkan=9, kijun=26, senkou=52)
        # ichimoku returns (visible_df, forward_df) — use the kijun column
        if result is None:
            return None
        try:
            visible = result[0] if isinstance(result, tuple) else result
            for col in visible.columns:
                if "KS_" in col or "ijun" in col.lower():
                    return visible[col]
            return visible.iloc[:, 0]  # first col fallback
        except Exception:  # noqa: BLE001
            return None
    if ind_id == "vwma_20":
        return _run_pta(df, "vwma", length=20)
    if ind_id == "hma_9":
        return _run_pta(df, "hma", length=9)
    # Pivots
    if ind_id == "pivot_classic":
        return _classic_pivots(df)
    if ind_id == "pivot_fibonacci":
        return _fib_pivots(df)
    if ind_id == "pivot_camarilla":
        return _camarilla_pivots(df)
    if ind_id == "pivot_woodie":
        return _woodie_pivots(df)
    if ind_id == "pivot_demark":
        return _demark_pivots(df)
    raise ValueError(f"unknown indicator id: {ind_id}")


def _source_for(ind_id: str) -> str:
    """Map indicator id → source label for the matrix."""
    if ind_id == "bbp":
        return "custom (EMA + high/low delta)"
    if ind_id.startswith("pivot_"):
        return "custom (pandas math)"
    return "pandas_ta_classic"


def main() -> int:
    print(f"TradingView 31-indicator coverage audit — basket size {len(BASKET)}")
    print(f"Fetching 400 days OHLCV per symbol from fmp_cached...\n")

    # Per-ticker fetch (cached across indicator loop)
    frames: dict[str, object] = {}
    fetch_failures: list[str] = []
    for sym in BASKET:
        print(f"  fetching {sym}...")
        df = _fetch_ohlcv(sym, days=400)
        if df is None:
            fetch_failures.append(sym)
        else:
            frames[sym] = df

    print(f"\nFetched {len(frames)}/{len(BASKET)} tickers; {len(fetch_failures)} failed.\n")

    # Coverage matrix: ind_id → sym → status ("ok" | "insufficient_history" | "error" | "no_data")
    coverage: dict[str, dict[str, str]] = defaultdict(dict)
    errors: dict[str, str] = {}

    for ind_id, ind_name, cat, min_bars in INDICATORS:
        print(f"  [{cat[:5]:>5}] {ind_id} ({ind_name})")
        for sym in BASKET:
            if sym not in frames:
                coverage[ind_id][sym] = "no_data"
                continue
            df = frames[sym]
            if len(df) < min_bars:
                coverage[ind_id][sym] = "insufficient_history"
                continue
            try:
                result = _dispatch(ind_id, df)
                coverage[ind_id][sym] = "ok" if _has_non_empty_output(result) else "empty_output"
            except Exception as exc:  # noqa: BLE001
                coverage[ind_id][sym] = "error"
                errors[f"{ind_id}::{sym}"] = f"{type(exc).__name__}: {exc}"

    # --- Report ---
    lines: list[str] = []
    lines.append(f"# TradingView 31-Indicator Coverage Audit")
    lines.append("")
    lines.append(f"- **Generated:** {dt.datetime.utcnow().isoformat()}Z")
    lines.append(f"- **Basket size:** {len(BASKET)} symbols (representative)")
    lines.append(f"- **Fetched:** {len(frames)}/{len(BASKET)} tickers")
    lines.append(f"- **Provider:** `fmp_cached` (400 days, 1d interval)")
    lines.append(f"- **Issue:** #780")
    lines.append("")

    if fetch_failures:
        lines.append(f"**Fetch failures:** {', '.join(fetch_failures)}")
        lines.append("")

    lines.append("## Coverage Matrix (Source)")
    lines.append("")
    lines.append("| # | Indicator | Category | Source | Coverage (ok / total) |")
    lines.append("|---|---|---|---|---|")
    for i, (ind_id, ind_name, cat, _) in enumerate(INDICATORS, 1):
        row = coverage.get(ind_id, {})
        ok = sum(1 for s in row.values() if s == "ok")
        total = len(row)
        lines.append(f"| {i} | {ind_name} | {cat} | {_source_for(ind_id)} | {ok}/{total} |")
    lines.append("")

    lines.append("## Per-Ticker × Indicator Detail")
    lines.append("")
    header = "| Indicator | " + " | ".join(BASKET) + " |"
    sep = "|" + "---|" * (len(BASKET) + 1)
    lines.append(header)
    lines.append(sep)

    def _cell(v: str) -> str:
        return {
            "ok": "✅",
            "insufficient_history": "⏳",
            "no_data": "❌",
            "empty_output": "⚠️",
            "error": "🔥",
        }.get(v, "?")

    for ind_id, ind_name, _, _ in INDICATORS:
        row = coverage.get(ind_id, {})
        cells = [_cell(row.get(s, "?")) for s in BASKET]
        lines.append(f"| {ind_name} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("Legend: ✅ ok · ⏳ insufficient history · ❌ no OHLCV · ⚠️ empty output · 🔥 exception")
    lines.append("")

    # Per-category totals
    lines.append("## Category Totals")
    lines.append("")
    lines.append("| Category | Indicators | Fully-covered (all tickers ok) | Partial | None |")
    lines.append("|---|---|---|---|---|")
    for cat in ("oscillator", "moving_average", "pivot"):
        ids = [i for i, _, c, _ in INDICATORS if c == cat]
        full = sum(1 for i in ids if all(coverage.get(i, {}).get(s) == "ok" for s in BASKET if s in frames))
        partial = sum(1 for i in ids if any(coverage.get(i, {}).get(s) == "ok" for s in BASKET if s in frames)) - full
        none = len(ids) - full - partial
        lines.append(f"| {cat} | {len(ids)} | {full} | {partial} | {none} |")
    lines.append("")

    # Missing indicators
    missing_ids = [
        i for i, _, _, _ in INDICATORS if not any(coverage.get(i, {}).get(s) == "ok" for s in BASKET if s in frames)
    ]
    lines.append("## Missing Indicators (0 tickers covered)")
    lines.append("")
    if missing_ids:
        for ind_id in missing_ids:
            name = next(n for i, n, _, _ in INDICATORS if i == ind_id)
            lines.append(f"- `{ind_id}` — {name} (needs implementation or provider gap)")
    else:
        lines.append("*None — every indicator has at least one successful ticker.*")
    lines.append("")

    if errors:
        lines.append("## Sample Errors (first 20)")
        lines.append("")
        for k, v in list(errors.items())[:20]:
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nReport written to {REPORT_PATH}")

    # Stdout summary
    total_ok = sum(sum(1 for s in coverage.get(i, {}).values() if s == "ok") for i, _, _, _ in INDICATORS)
    total_cells = sum(len(coverage.get(i, {})) for i, _, _, _ in INDICATORS)
    print(f"Overall coverage: {total_ok}/{total_cells} cells ok ({total_ok / max(total_cells, 1):.1%})")
    print(f"Missing indicators (0 coverage): {len(missing_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
