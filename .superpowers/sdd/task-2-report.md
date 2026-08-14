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

## 2. Live Study Results — ⚠️ INVALIDATED BY REVIEW (see Section 9)

> **RETRACTED 2026-08-13.** The numbers in this section are **invalid** and must
> not be cited. Two defects were found during the full-branch review:
>
> 1. **Wrong entry bar.** Yahoo anchors intraday bars to the 09:30 ET open, so
>    the 60-minute grid is `09:30, 10:30, 11:30, 12:30, 14:30, 15:30` and
>    contains **no 12:00 bar**. Matching `hour == 12` therefore selected the
>    **12:30 ET** bar (09:30 PT) — 30 minutes after the intended 09:00 PT entry.
> 2. **Impossible window.** Yahoo retains only ~60 days of intraday bars, so the
>    "134 sessions / 2026-02-02 .. 2026-08-13" span below could not have come
>    from genuine 09:30-aligned intraday data for the whole period, and the
>    result was never a six-month intraday answer.
>
> The corrected 30-minute study and its **PARTIAL WINDOW** result are recorded in
> Section 9. Retained below for audit trail only.

**Constituent source:** Slickcharts (`https://www.slickcharts.com/sp500`) — browser `User-Agent` header sent; Slickcharts returned the weight-ordered S&P 500 constituent table successfully on the first attempt.

| Metric | Value (INVALID) |
|---|---|
| Actual first session | 2026-02-02 |
| Actual last session | 2026-08-13 |
| Sessions observed | 134 |
| Symbols requested | 50 |
| Symbols observed | 50 |
| Valid stock-days | 6,700 |
| Expected stock-days | 6,700 |
| Coverage | 100.0% |
| ~~Stock-day accuracy~~ | ~~50.24%~~ **INVALID — wrong entry bar (12:30 ET)** |
| ~~Basket-day accuracy~~ | ~~50.00%~~ **INVALID — wrong entry bar (12:30 ET)** |
| Mean stock-day return | +0.0240% (INVALID) |
| Median stock-day return | +0.0064% (INVALID) |
| Cumulative basket return | +3.1156% (INVALID) |

**Missing symbols:** None — all 50 requested symbols produced at least one valid stock-day.

**Warnings printed at runtime:**
- `[!] SURVIVORSHIP BIAS` — constituents are the current S&P 500 list; companies that left during the window are excluded.
- `[!] NO TRANSACTION COSTS` — entry/exit prices are adjusted closes; spread, commission, and market-impact are not modelled.

---

## 3. Methodology — ⚠️ SUPERSEDED (see Section 9)

*The methodology below is the original, defective one. The corrected
methodology is in Section 9.*

- **Entry bar (DEFECTIVE):** intended the open of the 12:00 America/New_York bar, but with `interval="60m"` the 09:30-aligned grid has no 12:00 bar, so `hour == 12` actually selected the **12:30 ET** bar.
- **Exit bar:** close of the 15:30 America/New_York bar (matched via `hour == 15`; accidentally correct because 15:30 is the only 15:xx bar).
- **Win condition:** exit price strictly greater than entry price (ties count as losses).  
- **Equal-weight basket:** mean return across all symbols for each session day; basket-day win = basket return > 0.  
- **Data source (DEFECTIVE):** Yahoo Finance via `yfinance 1.5.2`, `interval="60m"`, `auto_adjust=True`, `group_by="ticker"`. Corrected to `interval="30m"` in Section 9.
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

## 7. Concerns — ⚠️ SUPERSEDED (see Section 9)

*The concerns below were written against the invalidated 60m result. Retained
for audit trail; the current concerns are in Section 9.*

1. ~~**Basket-day accuracy at exactly 50.00%**~~ — INVALID (wrong entry bar, impossible window).

2. ~~**Stock-day accuracy 50.24%**~~ — INVALID (wrong entry bar, impossible window).

3. **Survivorship bias** — the top-50 list captured at run-time is current. Any constituent that left the index during the window is absent; any addition after the window started is included. This likely flatters performance for mega-cap tech (no ex-index names in the denominator). **Still applies.**

4. ~~**Data coverage is perfect (100%)** — 6,700 stock-days from 50 symbols × 134 sessions~~ — INVALID: Yahoo cannot serve six months of intraday bars, and the pairs matched were 12:30 ET / 15:30 ET, not noon-and-3pm.

5. **Static fallback accuracy** — `_FALLBACK_TOP50` was removed in commit 8385c139e; no longer applicable.


---

## 8. Review-Findings Fix Evidence (2026-08-13 — commit 8385c139e)

### Changes made

| Finding | Fix |
|---|---|
| Wikipedia + static-symbol fallbacks | Removed entirely. `fetch_top_symbols` raises `RuntimeError` if Slickcharts fails. |
| Weight parsing (numeric vs. % string) | `_parse_weight()` coerces both; `sort_values("_w", ascending=False)` applied before dedup. |
| Shuffled-weight order test | New `test_fetch_top_symbols_preserves_weight_order` feeds reverse-weight table and asserts sort. |
| Percentage-string weight test | New `test_fetch_top_symbols_percentage_string_weights`. |
| Dedup test | New `test_fetch_top_symbols_deduplicates`. |
| Slickcharts-fails error type | Now `RuntimeError` (was `ValueError`). Tests updated to match. |
| Single-ticker flat-column promotion | `_promote_single_ticker_columns(raw, symbol)` added to the download helper; two regression tests. |
| Survivorship warning | Both leavers (LEFT) and joiners (JOINED) now stated explicitly in CLI output and README. |
| Entry/exit wording | Corrected in this round to "adjusted open at noon ET" / "adjusted close at 15:00 ET" — **itself wrong**; superseded by Section 9 (12:00 ET 30m bar open / 15:30 ET 30m bar close). |

### Live study re-run (2026-08-13, same window) — ⚠️ INVALIDATED

> These figures repeat the defective 60m run and are **invalid**. See Section 9.

| Metric | Value (INVALID) |
|---|---|
| Actual first session | 2026-02-02 |
| Actual last session | 2026-08-13 |
| Sessions observed | 134 |
| Symbols requested | 50 |
| Symbols observed | 50 |
| Valid stock-days | 6,700 |
| Expected stock-days | 6,700 |
| Coverage | 100.0% |
| ~~Stock-day accuracy~~ | ~~50.24%~~ **INVALID** |
| ~~Basket-day accuracy~~ | ~~50.00%~~ **INVALID** |
| Mean stock-day return | +0.0240% (INVALID) |
| Median stock-day return | +0.0064% (INVALID) |
| Cumulative basket return | +3.1156% (INVALID) |

Headline values were identical to the original run — same defective bar selection.

### Quality gates (post-fix)

| Gate | Result |
|---|---|
| `pytest tests/unit/test_intraday_drift.py` (33 tests) | 33 passed |
| `black --check` (2 files) | all unchanged |
| `ruff check` (examples/top50_intraday_drift.py) | all checks passed |

---

## 9. Full-Branch Review Fix Evidence (2026-08-14)

**Interpreter used for every command in this section:**
`H:\masterswork\git\OpenBB-Portfolio-Validation\.venv_portfolio\Scripts\python.exe`
(Python 3.12.10, pandas 3.0.5, yfinance 1.5.2)

### 9.1 Critical finding — confirmed empirically before any code change

Yahoo/yfinance anchors intraday bars to the **09:30 ET regular-session open**,
not to the top of the hour. Probe against AAPL:

| Interval | Unique New-York bar times returned |
|---|---|
| `60m` | `09:30, 10:30, 11:30, 12:30, 13:30, 14:30, 15:30` — **no 12:00 bar exists** |
| `30m` | `09:30, 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, ..., 15:30` — 12:00 present |

Consequence of the old code: `bars["_hour"] == 12` matched the **12:30 ET** bar
(= 09:30 PT), i.e. the study measured 09:30 PT → 13:00 PT, **not** the requested
09:00 PT → 13:00 PT. The exit side (`hour == 15`) happened to match 15:30 ET,
whose close is the 16:00 ET session close — accidentally correct.

Second probe — retention:

```text
yf.download(..., start="2026-02-01", interval="30m")
  -> empty frame; Yahoo error: "The requested range must be within the last 60 days."
```

Yahoo also rejects a request whose *start* is out of retention even when part of
the range is inside it, so chunks must be **end-anchored** (walk backwards from
the requested end) to harvest the maximum available history.

### 9.2 Fixes applied

| # | Finding | Fix |
|---|---|---|
| 1 | **CRITICAL** — `hour == 12` selects 12:30 ET, not 12:00 ET | Download switched to `INTRADAY_INTERVAL = "30m"`. `build_observations` now matches **hour AND minute** exactly: `(_hour == entry_hour) & (_minute == entry_minute)`. Public constants `ENTRY_HOUR=12, ENTRY_MINUTE=0, EXIT_HOUR=15, EXIT_MINUTE=30, BAR_MINUTES=30`, all overridable as keyword parameters. |
| 2 | Exit wording claimed "15:00 ET close" | Exit is the **close of the 15:30-16:00 ET bar** (= 16:00 ET session close = 13:00 PT). Wording corrected in module, CLI, README, design, plan. |
| 3 | **IMPORTANT** — currently-forming final exit bar could be accepted | New pure `exit_interval_end(sessions, exit_hour, exit_minute, bar_minutes)` and `filter_incomplete_exit_sessions(observations, now, ...)`. A session is kept only when `exit_interval_end <= now`. `now` must be timezone-aware (`ValueError` otherwise); `build_observations(now=None)` defaults to `datetime.now(ZoneInfo("America/New_York"))` so live runs are safe by default while tests inject an as-of clock. Logic is fully pure and independently testable. |
| 4 | Six-month claim impossible under 60-day retention | `compute_requested_window`, `assess_window_completeness(requested_start, actual_start, tolerance_days=7)`, `enforce_window_completeness(...)`. Default run raises `RuntimeError` beginning `INCOMPLETE WINDOW:` naming both dates, the shortfall, the tolerance, and the retention limit. |
| 5 | No opt-in for best-effort runs | New `--allow-partial-window` flag. Report is prefixed `*** PARTIAL WINDOW -- BEST-EFFORT RESULT, NOT A SIX-MONTH ANSWER ***`, prints requested vs. actual window, and tags every headline percentage `(PARTIAL WINDOW)`. |
| 6 | Retention rejects whole ranges | `intraday_chunks()` produces **end-anchored** ≤59-day chunks (newest first); `download_intraday_bars` stops at the first empty chunk once data has been collected and prints an honest `[info] no 30m bars for X..Y (beyond the provider's ~60-day intraday retention)` line. `_quiet_yfinance()` suppresses yfinance's misleading "possibly delisted" noise for out-of-retention chunks. |
| 7 | `download_hourly_bars` name | Renamed `download_intraday_bars`. Duplicate-bar errors now read `duplicate 12:00 entry bars` / `duplicate 15:30 exit bars`. |
| 8 | Docs claimed hourly / top-of-hour / invalid result | Design spec, plan, README, and Sections 2/3/7/8 of this report corrected; the 50.24% / 50.00% figures are explicitly marked **INVALID** rather than deleted. |

### 9.3 Test suite — realistic 09:30-aligned grids and reverse-locks

`tests/unit/test_intraday_drift.py` rewritten. Fixtures use the real bar grids:

```python
GRID_30M = [(9, 30), (10, 0), (10, 30), (11, 0), (11, 30), (12, 0),
            (12, 30), (13, 0), (13, 30), (14, 0), (14, 30), (15, 0), (15, 30)]
GRID_60M = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]
```

Reverse-locks that prevent the bug from returning:

- `test_build_observations_does_not_use_1230_bar_as_entry` — a 30m session whose
  12:00 open and 12:30 open differ; asserts the entry price is the **12:00**
  open and is **not** the 12:30 open.
- `test_build_observations_hourly_grid_yields_no_observations` — a full
  09:30-aligned **60m** session produces **zero** observations (there is no
  12:00 bar to match), so a silent regression to `interval="60m"` cannot
  masquerade as a valid study.
- `test_download_intraday_bars_requests_30m_and_stops_at_retention` — asserts
  the download layer passes `interval="30m"`.
- `test_build_observations_drops_session_whose_exit_bar_is_still_forming`,
  `test_run_study_drops_forming_session_via_injected_now` — forming-bar filter.
- `test_enforce_window_completeness_raises_without_flag`,
  `test_cli_partial_window_fails_loudly_by_default`,
  `test_run_study_partial_window_raises_without_flag` — window enforcement.

### 9.4 Mutation testing (repo rule R7.11 — a regression test must FAIL on the reverted fix)

Each mutation was applied, the focused suite run, then the file restored exactly.

| Mutation | Change | Result |
|---|---|---|
| **A** | Entry mask reverted to hour-only (`_hour == entry_hour`) | **KILLED** — `test_build_observations_does_not_use_1230_bar_as_entry`, `test_build_observations_hourly_grid_yields_no_observations`, +18 others failed |
| **B** | Forming-bar filter loosened (`<= now + 1 day`) | **KILLED** — 3 failed: `test_build_observations_drops_session_whose_exit_bar_is_still_forming`, `test_filter_incomplete_exit_sessions_accepts_other_timezones`, `test_run_study_drops_forming_session_via_injected_now` |
| **C** | Window enforcement disabled (`if is_partial and not allow_partial and False:`) | **KILLED** — 3 failed: `test_enforce_window_completeness_raises_without_flag`, `test_cli_partial_window_fails_loudly_by_default`, `test_run_study_partial_window_raises_without_flag` |
| **D** | `INTRADAY_INTERVAL = "60m"` | **KILLED** — 2 failed: `test_download_intraday_bars_requests_30m_and_stops_at_retention`, `test_cli_empty_download_exits_error` |

After restoring each mutation: **68 passed**.

### 9.5 Quality gates

```powershell
& $py -m pytest openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py -q
& $py -m black --check openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py `
                       openbb_platform/extensions/backtest/examples/top50_intraday_drift.py `
                       openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py
& $py -m ruff check openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py `
                    openbb_platform/extensions/backtest/examples/top50_intraday_drift.py
```

| Gate | Result |
|---|---|
| `pytest` (focused, 68 tests) | **68 passed** in 0.95s, exit 0 |
| `black --check` (3 files) | **3 files would be left unchanged**, exit 0 |
| `ruff check` (2 production files) | **All checks passed!**, exit 0 |

### 9.6 Live run A — default six-month request (loud failure verified)

```powershell
& $py openbb_platform/extensions/backtest/examples/top50_intraday_drift.py
```

Exit code: **1**. Verbatim output:

```text
[info] constituents sourced from https://www.slickcharts.com/sp500
[info] no 30m bars for 2026-04-19..2026-06-17 (beyond the provider's ~60-day intraday retention)
[error] INCOMPLETE WINDOW: requested history from 2026-02-01 but the earliest session returned by the provider is 2026-06-17 (136 calendar days later; tolerance 7 days). Yahoo Finance retains only ~60 days of 30m bars, so a multi-month 30m study is not possible from this source. Re-run with --allow-partial-window to accept a clearly labelled best-effort PARTIAL WINDOW result (which must NOT be reported as a six-month answer), or use a provider with deeper intraday history.
```

The default six-month study **cannot** produce a number. This is the intended
behaviour: the previously reported six-month result was never obtainable.

### 9.7 Live run B — `--allow-partial-window` (PARTIAL WINDOW result)

```powershell
& $py openbb_platform/extensions/backtest/examples/top50_intraday_drift.py --allow-partial-window
```

Exit code: **0**. Verbatim output:

```text
[info] constituents sourced from https://www.slickcharts.com/sp500
[info] no 30m bars for 2026-04-19..2026-06-17 (beyond the provider's ~60-day intraday retention)
--------------------------------------------------------------------
  Top-50 S&P 500 Intraday Drift Study
--------------------------------------------------------------------
  *** PARTIAL WINDOW -- BEST-EFFORT RESULT, NOT A SIX-MONTH ANSWER ***
  Requested window     : 2026-02-01 .. 2026-08-14
  Actual window        : 2026-06-17 .. 2026-08-13
  Provider retains only ~60 days of 30m bars; every percentage below describes ONLY 2026-06-17 .. 2026-08-13.
--------------------------------------------------------------------
  Actual first session : 2026-06-17
  Actual last session  : 2026-08-13
  Sessions observed    : 40
  Symbols requested    : 50
  Symbols observed     : 50
  Valid stock-days     : 2000
  Expected stock-days  : 2000
  Coverage             : 100.0%
--------------------------------------------------------------------
  Stock-day accuracy   : 46.30% (PARTIAL WINDOW)
  Basket-day accuracy  : 50.00% (PARTIAL WINDOW)
--------------------------------------------------------------------
  Mean stock-day ret   : -0.0807% (PARTIAL WINDOW)
  Median stock-day ret : -0.0750% (PARTIAL WINDOW)
  Cumul. basket ret    : -3.2098% (PARTIAL WINDOW)
--------------------------------------------------------------------

  [!] PARTIAL WINDOW -- the requested 2026-02-01 .. 2026-08-14 window was NOT available. These numbers cover 2026-06-17 .. 2026-08-13 only and must never be quoted as a six-month result.
  [!] SURVIVORSHIP BIAS -- constituents are the current S&P 500 list. Companies that LEFT the index during the window are excluded; companies that JOINED after the window started are included.
  [!] NO TRANSACTION COSTS -- entry price is the adjusted open of the 12:00 ET 30-minute bar (09:00 PT); exit price is the adjusted close of the 15:30 ET 30-minute bar (16:00 ET session close, 13:00 PT). Spread, commission, and market-impact are not modelled.
```

**Headline result — PARTIAL WINDOW 2026-06-17 .. 2026-08-13 only (≈2 months, 40 sessions):**

| Metric | Value | Scope |
|---|---|---|
| Stock-day accuracy | **46.30%** | PARTIAL WINDOW |
| Basket-day accuracy | **50.00%** | PARTIAL WINDOW |
| Mean stock-day return | **-0.0807%** | PARTIAL WINDOW |
| Median stock-day return | **-0.0750%** | PARTIAL WINDOW |
| Cumulative basket return | **-3.2098%** | PARTIAL WINDOW |
| Sessions / symbols / stock-days | 40 / 50 / 2,000 (100.0% coverage) | PARTIAL WINDOW |

**These figures are NOT a six-month answer** and must never be quoted as one.
Both runs were executed at 2026-08-14 ~01:27 ET; the 2026-08-13 exit interval
had completed, so the forming-bar filter dropped nothing on this run (its
behaviour is proven by the unit tests, not by this run).

### 9.8 Concerns (current)

1. **The six-month question posed in #1986 cannot be answered from Yahoo.**
   ~60 days of 30-minute retention is a hard provider limit. Answering the
   original question requires a provider with deeper intraday history
   (e.g. Polygon, Databento, or an FMP intraday tier).
2. **The partial-window sample is far too small for inference.** 40 sessions /
   2,000 stock-days over ~2 months. The 46.30% stock-day rate and -3.21%
   cumulative basket return describe one short, specific, recent stretch of
   market conditions — they are not evidence about the drift theory.
3. **Basket-day accuracy landed on exactly 50.00%** (20 up / 20 down of 40).
   Coincidental at this sample size; carries no signal.
4. **Survivorship bias persists.** Constituents are the *current* top-50 list;
   index leavers are absent and post-window joiners are included.
5. **No transaction costs.** Spread, commission, and market impact are not
   modelled; a ~-0.08% mean per stock-day would be further eroded by them.
6. **All previously published figures for this study (50.24% / 50.00%) are
   retracted** — see Sections 2, 3, 7 and 8.
