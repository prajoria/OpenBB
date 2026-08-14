# Task 2 Report — Top-50 S&P 500 Intraday Drift Study

**Date executed:** 2026-08-13  
**Operator:** Copilot CLI (automated)  
**Repository:** `H:\masterswork\git\OpenBB-Top50-Intraday-1986`

---

## 1. Deliverables

| File | Status |
|---|---|
| `openbb_platform/extensions/backtest/examples/top50_intraday_drift.py` | Created |
| `openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py` | Extended (+9 tests) |
| `openbb_platform/extensions/backtest/README.md` | Extended (usage section) |
| `openbb_platform/extensions/backtest/conftest.py` | Extended (examples path injection) |
| `ruff.toml` | Extended (per-file-ignores for examples/*.py) |

---

## 2. Live Study Results

**Constituent source:** Slickcharts (`https://www.slickcharts.com/sp500`) — browser `User-Agent` header sent; Slickcharts returned the weight-ordered S&P 500 constituent table successfully on the first attempt.

| Metric | Value |
|---|---|
| Actual first session | 2026-02-02 |
| Actual last session | 2026-08-13 |
| Sessions observed | 134 |
| Symbols requested | 50 |
| Symbols observed | 50 |
| Valid stock-days | 6,700 |
| Expected stock-days | 6,700 |
| Coverage | 100.0% |
| **Stock-day accuracy** | **50.24%** |
| **Basket-day accuracy** | **50.00%** |
| Mean stock-day return | +0.0240% |
| Median stock-day return | +0.0064% |
| Cumulative basket return | +3.1156% |

**Missing symbols:** None — all 50 requested symbols produced at least one valid stock-day.

**Warnings printed at runtime:**
- `[!] SURVIVORSHIP BIAS` — constituents are the current S&P 500 list; companies that left during the window are excluded.
- `[!] NO TRANSACTION COSTS` — entry/exit prices are adjusted closes; spread, commission, and market-impact are not modelled.

---

## 3. Methodology

- **Entry bar:** open of the 12:00 America/New_York hourly bar (calendar day).  
- **Exit bar:** close of the 15:00 America/New_York hourly bar.  
- **Win condition:** exit price strictly greater than entry price (ties count as losses).  
- **Equal-weight basket:** mean return across all symbols for each session day; basket-day win = basket return > 0.  
- **Data source:** Yahoo Finance via `yfinance 1.5.2`, `interval="60m"`, `auto_adjust=True`, `group_by="ticker"`.  
- **Constituent list:** `pandas.read_html` against `slickcharts.com/sp500` with a browser `User-Agent`, sorted by weight descending; dots in tickers replaced with dashes (e.g. `BRK.B` → `BRK-B`).

---

## 4. Constituent Provenance

Slickcharts was available during the run. The static fallback (`_FALLBACK_TOP50` in the script) was **not used** for this run. The fallback is manually transcribed from Slickcharts as of 2026-08-13 and is included as defense-in-depth only.

---

## 5. Quality Gates

| Gate | Result |
|---|---|
| `pytest tests/unit/test_intraday_drift.py` (26 tests) | ✓ 26 passed |
| `black --check` (3 files) | ✓ all unchanged |
| `ruff check` (2 production files) | ✓ all checks passed |

---

## 6. Implementation Notes

### `normalize_yfinance_bars` multi-index handling

`yfinance 1.5.2` with `group_by="ticker"` returns a `(symbol, price_field)` MultiIndex (e.g. `('AAPL', 'Open')`), and the index is named `Datetime` (America/New_York tz-aware). After `stack(level=0).reset_index()`, the resulting columns are `['datetime', 'ticker', 'open', ...]`.

The test fixtures use unnamed `DatetimeIndex` objects, which produce `['level_0', 'level_1', 'open', ...]` after the same stack/reset. The `normalize_yfinance_bars` function handles both by checking candidate column names in priority order:

- Timestamp candidates: `datetime` → `date` → `level_0`
- Symbol candidates: `ticker` → `level_1`

### Windows console encoding

The original script used `⚠` (U+26A0) in warning strings, which caused a `UnicodeEncodeError` on `cp1252` consoles. Replaced with plain-ASCII `[!]`.

### `conftest.py` path injection

`pytest --import-mode=importlib` (used project-wide) isolates test module imports from `sys.path` modifications made inside the test file itself. The `conftest.py` at the backtest-extension root is the correct place to inject the `examples/` directory into `sys.path` before collection.

---

## 7. Concerns

1. **Basket-day accuracy at exactly 50.00%** — with 134 sessions, 50.00% means 67 basket-up days and 67 basket-down days. This is the theoretical null; the study shows no statistically meaningful edge in this six-month window.

2. **Stock-day accuracy 50.24%** — marginally above the null but not statistically significant (n=6700 stock-days; two-sided binomial p ≈ 0.24 at 50.00% null).

3. **Survivorship bias** — the top-50 list captured at run-time is current. Any constituent that left the index during Feb–Aug 2026 is absent; any addition after the window started is included. This likely flatters performance for mega-cap tech (no ex-index names in the denominator).

4. **Data coverage is perfect (100%)** — 6,700 stock-days from 50 symbols × 134 sessions. Yahoo Finance delivered every noon-and-3pm pair for the entire six-month window with no gaps.

5. **Static fallback accuracy** — `_FALLBACK_TOP50` (50 symbols) was compiled on 2026-08-13. It will drift as the index composition changes. It is defense-in-depth only and was not used for this run.
