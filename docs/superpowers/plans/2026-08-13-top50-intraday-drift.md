# S&P 500 Top-50 Intraday Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a reusable strategy script that measures how often current top-50 S&P 500 constituents rise from 9:00 AM to 1:00 PM Pacific over the requested window of available intraday data.

> **Review correction (2026-08-13):** Yahoo Finance anchors intraday bars to the 09:30 ET open, so the 60-minute grid has **no 12:00 bar** and `hour == 12` silently selects 12:30 ET (09:30 PT). The study therefore uses `interval="30m"` with exact hour+minute matching. Yahoo also retains only ~60 days of 30m bars, so a six-month intraday window is **unobtainable** from this source: the default run must fail loudly and `--allow-partial-window` produces a clearly labelled best-effort result.

**Architecture:** Keep timestamp normalization, session-price extraction, and aggregation in an importable strategy module. Keep constituent scraping, Yahoo Finance retrieval, CLI parsing, and console/CSV output in a thin example script so all financial calculations can be tested without network access.

**Tech Stack:** Python 3.10+, pandas, yfinance, pytest, `zoneinfo`, `dataclasses`

## Global Constraints

- "Top 50" is the first 50 holdings in the current S&P 500 weight table.
- Pacific times use `America/Los_Angeles`; matching is performed after conversion to `America/New_York`.
- Entry is the open of the **12:00 ET 30-minute bar**; exit is the close of the **15:30 ET 30-minute bar** (16:00 ET session close). Selection matches hour **and** minute exactly; `interval="30m"` is mandatory because the 09:30-aligned 60m grid contains no 12:00 bar.
- A session whose exit interval has not finished as of an injected timezone-aware `now` is dropped (no currently-forming bars).
- A run whose earliest returned session materially postdates the requested start (tolerance 7 calendar days) fails loudly unless `--allow-partial-window` is supplied.
- A win requires `exit_price > entry_price`; ties are not wins.
- Missing entry or exit bars are excluded and surfaced through coverage metrics.
- Use adjusted OHLC data and disclose current-constituent/survivorship bias.
- Do not add a hard runtime dependency to the backtest extension for an example-only network adapter.

---

## File Structure

- Create `openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py`: typed data model plus pure normalization, observation, and summary functions.
- Create `openbb_platform/extensions/backtest/examples/top50_intraday_drift.py`: public-data adapters and executable CLI.
- Create `openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py`: realistic 09:30-aligned 30-minute-frame regression tests.
- Modify `openbb_platform/extensions/backtest/README.md`: command and interpretation notes.

### Task 1: Pure intraday strategy calculations

**Files:**
- Create: `openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py`
- Test: `openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py`

**Interfaces:**
- Consumes: a long pandas `DataFrame` with columns `timestamp`, `symbol`, `open`, and `close`.
- Produces: `build_observations(bars: pd.DataFrame) -> pd.DataFrame`, `summarize_observations(observations: pd.DataFrame, expected_symbols: int) -> DriftSummary`, and immutable `DriftSummary`.

- [ ] **Step 1: Write failing extraction and summary tests**

Create realistic timezone-aware **09:30-aligned 30-minute** bars spanning winter and summer dates. Include one complete winner, one complete loser, and one missing-exit stock-day. Also include reverse-lock tests proving the 12:30 ET bar is never used as entry and that a 60-minute grid produces zero observations:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from openbb_backtest.strategies.intraday_drift import (
    build_observations,
    summarize_observations,
)

AS_OF = datetime(2026, 12, 31, 23, 59, tzinfo=ZoneInfo("America/New_York"))


def test_build_observations_uses_1200_open_and_1530_close():
    ny = ZoneInfo("America/New_York")
    bars = pd.DataFrame(
        [
            {"timestamp": datetime(2026, 2, 10, 12, 0, tzinfo=ny), "symbol": "AAA", "open": 100.0, "close": 101.0},
            {"timestamp": datetime(2026, 2, 10, 15, 30, tzinfo=ny), "symbol": "AAA", "open": 104.0, "close": 105.0},
            {"timestamp": datetime(2026, 7, 10, 12, 0, tzinfo=ny), "symbol": "BBB", "open": 200.0, "close": 198.0},
            {"timestamp": datetime(2026, 7, 10, 15, 30, tzinfo=ny), "symbol": "BBB", "open": 197.0, "close": 196.0},
            {"timestamp": datetime(2026, 7, 10, 12, 0, tzinfo=ny), "symbol": "CCC", "open": 50.0, "close": 51.0},
        ]
    )

    observations = build_observations(bars, now=AS_OF)

    assert observations[["symbol", "entry_price", "exit_price", "win"]].to_dict("records") == [
        {"symbol": "AAA", "entry_price": 100.0, "exit_price": 105.0, "win": True},
        {"symbol": "BBB", "entry_price": 200.0, "exit_price": 196.0, "win": False},
    ]


def test_summary_reports_stock_day_and_equal_weight_basket_rates():
    observations = pd.DataFrame(
        {
            "session": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-11", "2026-08-11"]).date,
            "symbol": ["AAA", "BBB", "AAA", "BBB"],
            "return": [0.02, -0.01, -0.02, -0.01],
            "win": [True, False, False, False],
        }
    )

    summary = summarize_observations(observations, expected_symbols=2)

    assert summary.stock_day_win_rate_pct == 25.0
    assert summary.basket_day_win_rate_pct == 50.0
    assert summary.valid_stock_days == 4
    assert summary.coverage_pct == 100.0
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
& ".venv_portfolio\Scripts\python.exe" -m pytest openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py -v
```

Expected: collection fails because `openbb_backtest.strategies.intraday_drift` does not exist.

- [ ] **Step 3: Implement the pure strategy module**

Implement:

```python
@dataclass(frozen=True)
class DriftSummary:
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


def build_observations(
    bars: pd.DataFrame,
    *,
    now: datetime | None = None,
    entry_hour: int = ENTRY_HOUR,
    entry_minute: int = ENTRY_MINUTE,
    exit_hour: int = EXIT_HOUR,
    exit_minute: int = EXIT_MINUTE,
) -> pd.DataFrame:
    required = {"timestamp", "symbol", "open", "close"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"bars missing required columns: {sorted(missing)}")
    # Convert/localize timestamps to New York, select the entry bar by matching
    # BOTH hour and minute (12:00) and the exit bar the same way (15:30) by
    # symbol/session, inner-join them, calculate return + strict win, then drop
    # sessions whose exit interval has not finished as of `now`.


def summarize_observations(
    observations: pd.DataFrame,
    expected_symbols: int,
) -> DriftSummary:
    if expected_symbols <= 0:
        raise ValueError("expected_symbols must be positive")
    if observations.empty:
        raise ValueError("no complete stock-days to summarize")
    # Group returns by session for the equal-weight basket. Compound daily basket
    # returns with (1 + r).prod() - 1 and calculate expected coverage as
    # unique_sessions * expected_symbols.
```

The implementation must reject non-positive prices, sort output by
`session, symbol`, and return observation columns:
`session, symbol, entry_price, exit_price, return, win`.

- [ ] **Step 4: Run focused tests and add edge-case assertions**

Add tests proving that ties are losses, missing required columns raise
`ValueError`, non-positive prices are excluded, and an empty observation frame
raises a loud error. Then run the focused test file again.

Expected: all tests pass.

- [ ] **Step 5: Commit the pure calculation layer**

```powershell
git add openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py
git commit -m "feat(backtest): add intraday drift calculations" -m "Refs #1986" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Live data adapter and strategy CLI

**Files:**
- Create: `openbb_platform/extensions/backtest/examples/top50_intraday_drift.py`
- Modify: `openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py`
- Modify: `openbb_platform/extensions/backtest/README.md`

**Interfaces:**
- Consumes: `build_observations` and `summarize_observations` from Task 1.
- Produces: `fetch_top_symbols(count: int) -> list[str]`, `normalize_yfinance_bars(raw: pd.DataFrame) -> pd.DataFrame`, `run_study(count: int, months: int) -> tuple[pd.DataFrame, DriftSummary, list[str]]`, and CLI `main() -> int`.

- [ ] **Step 1: Write failing adapter tests**

Use a realistic yfinance frame with two-level columns ordered
`(symbol, price_field)` and a UTC `DatetimeIndex`. Assert normalization returns
the long contract required by Task 1. Monkeypatch `pandas.read_html` with a
table containing `Symbol` and `Weight` columns and assert dots become Yahoo
dashes (`BRK.B` becomes `BRK-B`) while order is preserved.

```python
def test_normalize_yfinance_bars_returns_long_contract():
    index = pd.DatetimeIndex(["2026-08-10T16:00:00Z", "2026-08-10T19:00:00Z"])
    columns = pd.MultiIndex.from_product([["AAA", "BBB"], ["Open", "Close"]])
    raw = pd.DataFrame([[100.0, 101.0, 200.0, 201.0], [104.0, 105.0, 196.0, 196.0]], index=index, columns=columns)

    result = normalize_yfinance_bars(raw)

    assert list(result.columns) == ["timestamp", "symbol", "open", "close"]
    assert set(result["symbol"]) == {"AAA", "BBB"}
```

- [ ] **Step 2: Run adapter tests and verify failure**

Run the focused test file. Expected: import failure because the example module
and adapter functions do not exist.

- [ ] **Step 3: Implement adapters and CLI**

Implement `fetch_top_symbols` using `pandas.read_html` against
`https://www.slickcharts.com/sp500` with an explicit browser user agent. Validate
that the source returns at least `count` distinct symbols.

Implement `download_intraday_bars` with a lazy `import yfinance as yf`. Yahoo
rejects any request whose *start* falls outside its ~60-day intraday retention,
so split the range into **end-anchored** chunks of at most 59 days (newest
first) and stop at the first empty chunk once data has been collected:

```python
yf.download(
    tickers=symbols,
    start=chunk_start.isoformat(),
    end=chunk_end_exclusive.isoformat(),
    interval="30m",          # 60m is 09:30-aligned and has NO 12:00 bar
    auto_adjust=True,
    group_by="ticker",
    threads=True,
    progress=False,
)
```

If yfinance is unavailable, raise `RuntimeError` with the exact install hint
`pip install yfinance`. Normalize multi-index columns, identify symbols with no
complete observations, and print:

- actual first and last session;
- requested and observed symbol counts;
- valid/expected stock-days and coverage;
- headline stock-day win rate;
- equal-weight basket-day win rate;
- mean, median, and cumulative returns;
- the survivorship-bias and no-transaction-cost warnings.

Add `--top` (default `50`), `--months` (default `6`), `--allow-partial-window`,
and optional `--csv` arguments. Write only the derived observation rows, never
raw downloaded bars. Before reporting, compare the requested window start with
the earliest returned session: if the shortfall exceeds 7 calendar days, raise
`RuntimeError` starting with `INCOMPLETE WINDOW:` unless `--allow-partial-window`
was supplied, in which case the report is prefixed with
`*** PARTIAL WINDOW -- BEST-EFFORT RESULT, NOT A SIX-MONTH ANSWER ***` and each
headline percentage carries a `(PARTIAL WINDOW)` tag.

- [ ] **Step 4: Test CLI without network access**

Monkeypatch constituent and price loaders with deterministic frames, invoke
`main(["--top", "2", "--months", "6"])`, and assert exit code `0` plus report
labels `Stock-day accuracy` and `Basket-day accuracy`. Add failure tests for
fewer than the requested symbols and empty downloads.

Run:

```powershell
& ".venv_portfolio\Scripts\python.exe" -m pytest openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py -v
```

Expected: all tests pass without network access.

- [ ] **Step 5: Document and run the strategy**

Add this usage to the backtest README:

```powershell
& ".venv_portfolio\Scripts\python.exe" openbb_platform/extensions/backtest/examples/top50_intraday_drift.py
```

Run it against live data. Verify that the default run **fails loudly** with
`INCOMPLETE WINDOW` (because Yahoo cannot serve six months of 30m bars), and
that `--allow-partial-window` produces a report clearly labelled
`PARTIAL WINDOW` stating the actual first/last session, with 50 symbols
requested, at least one valid stock-day for every observed symbol, and both
accuracy percentages tagged as partial. A partial run must never be recorded as
a six-month answer.

- [ ] **Step 6: Run quality gates**

```powershell
& ".venv_portfolio\Scripts\python.exe" -m pytest openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py -v
& ".venv_portfolio\Scripts\python.exe" -m black --check openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py openbb_platform/extensions/backtest/examples/top50_intraday_drift.py openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py
& ".venv_portfolio\Scripts\python.exe" -m ruff check openbb_platform/extensions/backtest/openbb_backtest/strategies/intraday_drift.py openbb_platform/extensions/backtest/examples/top50_intraday_drift.py
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit the strategy script**

```powershell
git add openbb_platform/extensions/backtest/examples/top50_intraday_drift.py openbb_platform/extensions/backtest/tests/unit/test_intraday_drift.py openbb_platform/extensions/backtest/README.md
git commit -m "feat(backtest): add top-50 intraday drift strategy" -m "Closes #1986" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
