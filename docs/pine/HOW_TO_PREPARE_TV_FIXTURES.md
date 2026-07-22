# Pine Fixture Prep + TradingView Export — Step-by-Step Guide

**Purpose:** get real TradingView Strategy Tester outputs into the OpenBB-Pine
conformance suite so its parity tests can run against your Pine v6 strategies.
This unblocks GH issues **#578** (5 pilot fixtures), **#584** (request.security
corpus), and **#586** (v5 roundtrip fixtures).

**Time estimate:** ~30 min for your first export (learning the TV UI + our
CSV format). ~10 min per fixture after that.

**What you need:**

- TradingView account with **Essential tier or higher** (Free tier cannot
  export the Strategy Tester CSVs — this is a hard TV paywall).
- Local checkout of `H:\masterswork\git\OpenBB-Pine` on `openbb_pine_support`.
- The `.venv_pine_support` venv already set up (see CLAUDE.md §"Python
  environment isolation").

> **Design in flux — see brainstorm:**
> [`docs/superpowers/brainstorms/2026-07-20-pine-hybrid-fixture-suite.md`](../superpowers/brainstorms/2026-07-20-pine-hybrid-fixture-suite.md)
> proposes reducing this 4-CSV workflow to a 1-CSV workflow (TV trades
> only, bars from fmp_cached at test time, equity/stats derived by our
> runtime). If that proposal is approved, this guide will be updated to
> describe the hybrid workflow as the default, keeping the 4-CSV path
> only for one "full-parity canary" fixture. Read the brainstorm if
> you're about to invest in generating fixtures under the current
> design — you may want to wait or scope your work accordingly.

---

## Part 1 — Understand what "a fixture" is

Every fixture lives in
`openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/<name>/`
and consists of **four required files** plus **one optional bars file**:

```
fixtures/<name>/
├── <name>.pine          # Pine v5/v6 source code you'll paste into TV
├── <name>.equity.csv    # Reference equity curve (from TV Strategy Tester)
├── <name>.trades.csv    # Reference closed-trade list (from TV Strategy Tester)
├── <name>.stats.csv     # Reference performance summary (from TV Strategy Tester)
└── <name>.bars.csv      # OPTIONAL — Exact OHLCV bars TV ran against
```

**How the harness picks them up:** the discovery walker at
`tests/conformance_strategy/conftest.py:_discover_strategy_triples`
scans every `fixtures/<name>/` subdir at test time. If all four required
files exist with matching stems, the fixture becomes a live conformance
test. If any of the four is missing, the fixture is skipped with a
WARNING log (never silently dropped — deliberate).

**Why the bars.csv matters:** if you provide it, the test harness feeds
your exact TV bars to our runtime, so parity failures cleanly isolate to
"compiler bug" or "runtime bug." If you don't, the harness generates a
deterministic 500-bar synthetic series — which means your TV output
computed from real historical bars will NEVER match. **You should always
ship `bars.csv` for real-symbol fixtures.**

---

## Part 2 — The 5 pilot fixtures waiting for you

These `.pine` sources already exist in the repo; you only need to produce
the CSV outputs from TradingView. Each fixture directory also ships a
short `HOW_TO_EXPORT_FROM_TV.md` stub — the fixture-specific quick-
reference for the steps you'll take. **`rsi_reversal` additionally has a
`GUIDE.md`** — a deep-dive visual walkthrough of the TradingView UI (~325
lines with screenshot placeholders, pre-flight checklist, and per-click
navigation). If you've never used TV's Strategy Tester before, read
`rsi_reversal/GUIDE.md` first — this document (`HOW_TO_PREPARE_TV_FIXTURES.md`)
gives you the workflow overview and CSV-schema details, but `GUIDE.md`
gives you the exact TradingView clicks.

| Fixture | Fixture-specific docs | Symbol suggestion | Timeframe | What the strategy does |
|---|---|---|---|---|
| `rsi_reversal` | [`GUIDE.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/GUIDE.md) (deep-dive) · [`HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/HOW_TO_EXPORT_FROM_TV.md) (quick ref) | SPY / AAPL / MSFT / QQQ | 1D | Buys on RSI(14) crossover of 30; closes on RSI crossunder of 70 |
| `sma_crossover` | [`HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/sma_crossover/HOW_TO_EXPORT_FROM_TV.md) | (check the .pine) | 1D | Fast/slow SMA crossover |
| `bb_squeeze` | [`HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/bb_squeeze/HOW_TO_EXPORT_FROM_TV.md) | (check the .pine) | 1D | Bollinger Bands squeeze breakout |
| `breakout_atr_trail` | [`HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/breakout_atr_trail/HOW_TO_EXPORT_FROM_TV.md) | (check the .pine) | 1D | Breakout entry + ATR trailing stop |
| `macd_histogram_signal` | [`HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/macd_histogram_signal/HOW_TO_EXPORT_FROM_TV.md) | (check the .pine) | 1D | MACD histogram signal |

**Recommendation:** start with `rsi_reversal`. It has the most complete
per-fixture documentation, its Pine source is the simplest of the five
(~15 lines), and every step in that fixture's `GUIDE.md` transfers
directly to the other four. Once you have the workflow down, the other
4 take ~10 min each — you'll only need each one's `HOW_TO_EXPORT_FROM_TV.md`
stub as a quick reference.

---

## Part 3 — Step-by-step TV export for ONE fixture

Using `rsi_reversal` as the working example. Same steps apply to any
fixture; only the .pine source you paste and the output filenames change.

**Complementary reads for this section:**

- **[`fixtures/rsi_reversal/GUIDE.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/GUIDE.md)**
  — the visual walkthrough. If any TradingView UI step in §3 below is
  unclear, that document has the exact clicks + screenshot placeholders
  for `rsi_reversal` specifically. Especially useful if you've never
  used TV's Strategy Tester before.
- **[`fixtures/rsi_reversal/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/HOW_TO_EXPORT_FROM_TV.md)**
  — the quick reference; ~30 lines summarizing the export step per
  fixture. Every fixture directory has one of these.

The three docs (this one, `GUIDE.md`, `HOW_TO_EXPORT_FROM_TV.md`) are
layered: **this doc** = workflow overview + CSV schema + PowerShell
massaging + troubleshooting; **`GUIDE.md`** = visual TV UI walkthrough
(single fixture); **`HOW_TO_EXPORT_FROM_TV.md`** = per-fixture quick
reference. Read whichever depth matches what you need.

### 3.1 — Open the Pine source

```powershell
# In Windows PowerShell
notepad H:\masterswork\git\OpenBB-Pine\openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\rsi_reversal\rsi_reversal.pine
```

Select all (`Ctrl+A`), copy (`Ctrl+C`). You'll paste it into TradingView
next.

### 3.2 — Open TradingView Pine Editor

1. Log in to https://www.tradingview.com/ (Essential tier or higher).
2. Open the Pine Editor: [https://www.tradingview.com/pine-script-editor/](https://www.tradingview.com/pine-script-editor/)
3. Click **New** → **Empty strategy script** (NOT "Empty indicator" —
   `strategy(...)` scripts need the strategy template).
4. Delete the boilerplate. Paste your `rsi_reversal.pine` contents (Ctrl+V).
5. Click **Save** — give it any name; TradingView saves in your account.

### 3.3 — Set up the chart with deterministic input

**This is the single most important step for parity.** TradingView's
Strategy Tester runs against whatever bars the chart is currently
showing. Small differences in the visible bar range = different trades =
failing parity assertions.

1. **Symbol**: `NASDAQ:AAPL` (or `NYSE:SPY`, or your choice — but be
   consistent — the same symbol goes in `bars.csv` later).
2. **Timeframe**: `1D` (daily bars — matches our tests' default).
3. **Bar range**: zoom to a fixed window. Recommendation:
   **500 bars ending on a specific past date** (e.g. bars from
   2022-01-03 through 2023-12-31 approximately). Two ways to lock the
   range:
   - **Easier**: right-click the price axis → **Scale price to
     visible range**, then use the horizontal-drag on the time axis
     to see exactly 500 bars.
   - **Deterministic**: use TradingView's **Go To** feature (`Alt+G`)
     to jump to a specific end date; zoom until you see ~500 bars.
4. **Verify bar count**: hover the leftmost visible bar → the tooltip
   should say something like "1/500" or the timestamp should be your
   intended start.

**Why 500 bars:** the existing `placeholder_smoke` fixture uses 500
deterministic synthetic bars. Matching that count keeps the sibling
fixtures' equity-curve arrays the same length, which makes debugging
easier.

### 3.4 — Add the strategy to the chart

1. In the Pine Editor, click **Add to Chart** (top-right of the editor
   panel).
2. Wait for the strategy to compile. If it errors, the `.pine` file
   isn't valid v6 — that's a code bug, tell Claude and stop here.
3. On success you'll see:
   - Indicator lines (RSI panel below the price for `rsi_reversal`)
   - Buy/sell triangles on the price chart at each trade
   - The **Strategy Tester** panel appears at the bottom of the screen

### 3.5 — Export the three required CSVs

Open the **Strategy Tester** panel (bottom of screen; if hidden, click
the panel-toggle icon or press `Alt+D`).

#### 3.5.1 — Performance Summary → `<name>.stats.csv`

1. Click the **Performance Summary** tab in the Strategy Tester panel.
2. Right-click anywhere in the metrics table → **Export data...** →
   **Export chart data** dialog opens.
   - If you don't see "Export data" in the right-click menu, look for
     the **⋮** (three-dot) icon in the top-right of the Performance
     Summary panel; it's the same "Export CSV" action.
3. In the export dialog:
   - Format: **CSV** (default)
   - Encoding: **UTF-8**
4. Save the file as `rsi_reversal.stats.csv` (exact name, note the dot
   between `rsi_reversal` and `stats`).

#### 3.5.2 — List of Trades → `<name>.trades.csv`

1. Click the **List of Trades** tab.
2. Same export flow as above.
3. Save as `rsi_reversal.trades.csv`.

#### 3.5.3 — Equity Curve → `<name>.equity.csv`

**This one is trickier — TV doesn't offer an "equity curve export" as a
first-class button in all UI versions.**

**Option A (recommended if available):**
1. In the Strategy Tester panel, click the **Overview** tab.
2. The equity curve chart is visible at the top of the tab.
3. Right-click the equity curve chart → **Export CSV** (may be labeled
   "Export data..." depending on TV UI version).

**Option B (if Option A isn't available in your TV version):**
1. Open your `.pine` file in the Pine Editor.
2. Add this line at the very end (temporarily):
   ```pine
   plot(strategy.equity, "equity_export", color=color.orange, display=display.data_window)
   ```
3. Click **Add to Chart** to re-run with the extra plot.
4. Right-click the price chart → **Export chart data...**
5. In the export dialog, select **All Charts** (or the equivalent
   "include indicator values").
6. Save the raw CSV; you'll trim it in the next step.

Save as `rsi_reversal.equity.csv` (before shape-cleanup).

#### 3.5.4 — Chart bars → `<name>.bars.csv` (STRONGLY RECOMMENDED)

1. Right-click anywhere on the **price chart** (not the strategy panel)
   → **Export chart data...**
2. In the dialog:
   - Format: **CSV**
   - Time range: **Visible range** (this ensures the exported bars
     match what the strategy ran against)
3. Save as `rsi_reversal.bars.csv`.

### 3.6 — Massage the CSVs to match our schema

TV's CSV output is close to what we need but not exact. Each file has a
required shape:

#### `<name>.stats.csv`

Our harness expects a **1-row CSV** whose header names each stat. TV
exports a 2-column "metric, value" layout — you'll need to pivot it.

**Manual pivot** (in Excel or PowerShell):
```powershell
# In PowerShell — this reads the TV metric/value CSV and pivots
$rows = Import-Csv rsi_reversal.stats.csv
$pivot = [ordered]@{}
foreach ($r in $rows) { $pivot[$r.'Metric'] = $r.'Value' }
[pscustomobject]$pivot | Export-Csv rsi_reversal.stats.csv -NoTypeInformation
```

Required columns (at minimum — extra columns are OK, missing ones fail):
`net_profit`, `net_profit_percent`, `total_closed_trades`,
`winning_trades`, `losing_trades`, `percent_profitable`, `profit_factor`,
`max_drawdown`, `max_drawdown_percent`, `sharpe_ratio`, `sortino_ratio`.

(The exact required set is enforced by the parity test — if you're
missing one, the test error message will name it.)

#### `<name>.trades.csv`

Our harness expects a **header + N rows**, one row per closed round-trip
trade. Required columns:
`trade_num, type, signal_entry, date_entry, price_entry, contracts_entry, signal_exit, date_exit, price_exit, contracts_exit, profit, profit_percent, cumulative_profit, cumulative_profit_percent, runup, drawdown, bars_in_trade`.

TV's List-of-Trades CSV export is close to this shape but uses different
column names (e.g. `Trade #`, `Type`, `Signal`, `Date/Time`, `Price`,
`Contracts`, `Profit USD`, etc.). Rename the columns via Excel's
find-and-replace on the header row, or in PowerShell:

```powershell
$c = @{'Trade #'='trade_num'; 'Type'='type'; 'Signal'='signal_entry';
       'Date/Time'='date_entry'; 'Price USD'='price_entry';
       'Contracts'='contracts_entry'; ...}  # extend to cover every col
Import-Csv rsi_reversal.trades.csv | ForEach-Object {
    $new = [ordered]@{}
    foreach ($p in $_.PSObject.Properties) {
        $key = if ($c.ContainsKey($p.Name)) { $c[$p.Name] } else { $p.Name }
        $new[$key] = $p.Value
    }
    [pscustomobject]$new
} | Export-Csv rsi_reversal.trades.csv -NoTypeInformation
```

#### `<name>.equity.csv`

Required shape: **3 columns, 500 rows, header**:
```
bar_index,equity,drawdown
0,1000000.0,0.0
1,1000000.0,0.0
2,1000000.0,0.0
...
499,1023450.5,1234.8
```

- `bar_index`: 0-indexed integer, one per bar (0..499 for 500 bars).
- `equity`: `strategy.equity` value at end of that bar.
- `drawdown`: running drawdown magnitude (non-negative) at that bar;
  `0.0` when equity is at a new high.

If TV's export gives you timestamps instead of bar indices, use PowerShell
to add a bar index:

```powershell
$i = 0
Import-Csv rsi_reversal.equity.csv | ForEach-Object {
    [pscustomobject]@{ bar_index=$i; equity=$_.equity; drawdown=$_.drawdown }
    $i++
} | Export-Csv rsi_reversal.equity.csv -NoTypeInformation
```

#### `<name>.bars.csv`

Required shape: **6 columns, header**:
```
date,open,high,low,close,volume
2022-01-03T00:00:00Z,178.09,182.88,177.71,182.01,104487900
...
```

- `date`: ISO 8601 timestamp, UTC (with `Z` suffix or `+00:00`).
- `open`, `high`, `low`, `close`: floats.
- `volume`: integer (or float — pandas handles both).

TV's chart-data export uses `time` as the date column and lowercase
OHLC. Rename `time`→`date` and confirm the timestamps are UTC.

### 3.7 — Drop the four CSVs into the fixture dir

```powershell
Move-Item rsi_reversal.stats.csv `
  H:\masterswork\git\OpenBB-Pine\openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\rsi_reversal\
Move-Item rsi_reversal.trades.csv `
  H:\masterswork\git\OpenBB-Pine\openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\rsi_reversal\
Move-Item rsi_reversal.equity.csv `
  H:\masterswork\git\OpenBB-Pine\openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\rsi_reversal\
Move-Item rsi_reversal.bars.csv `
  H:\masterswork\git\OpenBB-Pine\openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\rsi_reversal\
```

### 3.8 — Confirm the fixture registers with the harness

```powershell
cd H:\masterswork\git\OpenBB-Pine
.venv_pine_support\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\ `
  --collect-only -q
```

**Expected output:** you should see `rsi_reversal` in the collected
tests list alongside `placeholder_smoke`. Something like:

```
test_conformance_strategy.py::test_strategy_equity_parity[placeholder_smoke]
test_conformance_strategy.py::test_strategy_equity_parity[rsi_reversal]
test_conformance_strategy.py::test_strategy_trade_list_exact_match[placeholder_smoke]
test_conformance_strategy.py::test_strategy_trade_list_exact_match[rsi_reversal]
test_conformance_strategy.py::test_strategy_stats_parity[placeholder_smoke]
test_conformance_strategy.py::test_strategy_stats_parity[rsi_reversal]
6 tests collected
```

If `rsi_reversal` doesn't appear, one of the four CSVs is missing or
misnamed. Check the pytest warning log for
`conformance_strategy: skipping incomplete fixture 'rsi_reversal'
(missing: ...)` — the message names the missing file.

### 3.9 — Run the fixture and check parity

```powershell
.venv_pine_support\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\ `
  -k rsi_reversal -v
```

**Best case:** 3 tests pass (equity parity + trade list + stats). Ship
it — commit the four CSVs, PR to `openbb_pine_support`. Claude can auto-
merge under the Pine rule.

**Common failure modes:**
- `test_strategy_equity_parity` fails with a small delta near the end of
  the curve → floating-point drift; adjust the parity tolerance or the
  bars.csv precision.
- `test_strategy_trade_list_exact_match` fails with N trades vs M →
  either the bar range you exported doesn't match what TV ran against,
  or the runtime has a real bug (this is the interesting case).
- `test_strategy_stats_parity` fails on a specific stat like
  `profit_factor` → often a rounding difference; the parity test uses
  relative tolerance so small differences are OK.

**If parity fails but you're confident the CSVs are correct:** you've
found a real bug. Comment on the fixture's issue (#578) with a
one-liner and Claude will investigate.

---

## Part 4 — Preparing a NEW pilot Pine script (for #584 / #586)

If you want to expand beyond the 5 existing pilots — for example, to
cover `request.security` (#584) or v5 roundtrip scripts (#586) — follow
this workflow:

### 4.1 — Decide the strategy's shape

Pick one **archetype** the corpus doesn't cover yet. Good candidates:

- **request.security cross-timeframe** — e.g. "1D chart, but MACD
  computed on 1H bars via `request.security(syminfo.tickerid, "60",
  ta.macd(close, 12, 26, 9))`".
- **v5 roundtrip** — a legacy v5 script with `study()`, `iff()`,
  `security()`, `transp=`, `strategy.exit(when=…)` — every construct
  our v5→v6 shim rewrites.
- **Long-tail builtin** — a strategy using a builtin we've implemented
  but never exercised end-to-end (`ta.linreg`, `ta.sar`, position-history
  builtins like `strategy.opentrades`).

**Rule of thumb:** the strategy should trade **at least 5 times** on the
500-bar window so the trade-list parity assertion has signal.

### 4.2 — Write the .pine source

Convention: `<fixtures>/<name>/<name>.pine`. Follow the shape of
existing fixtures — see `rsi_reversal.pine`, ~15 lines:

```pine
//@version=6
strategy("<Human Name>", overlay=<true|false>, initial_capital=1000000)
// inputs
input1 = input.int(<default>, "<label>")
// signals
signal_up = <boolean expression>
signal_down = <boolean expression>
// orders
if signal_up
    strategy.entry("<id>", strategy.long)
if signal_down
    strategy.close("<id>")
// optional plots (helpful in TV, ignored by our runtime for output)
plot(<indicator series>)
```

### 4.3 — Verify it compiles in our extension BEFORE going to TV

```powershell
cd H:\masterswork\git\OpenBB-Pine
.venv_pine_support\Scripts\python.exe -c "
from pyne_compiler.compiler import compile_pine_to_program
from pathlib import Path
src = Path('openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/<name>/<name>.pine').read_text()
prog = compile_pine_to_program(src)
print(f'OK — compiled {type(prog).__name__} with {len(prog.body)} top-level statements')
"
```

If this errors, you've hit an unimplemented builtin or a v6 syntax we
don't support yet. Fix the Pine source (use a builtin we do support) or
file a compiler-side issue.

### 4.4 — Follow Part 3 for the TV export

Once the .pine compiles cleanly on our side, jump back to §3.1 with
your new `<name>` and produce the four CSVs.

---

## Part 5 — Committing your work

Once the fixture registers and its 3 parity tests pass:

```powershell
cd H:\masterswork\git\OpenBB-Pine
git checkout -b feat/pine-578/<name>-fixture openbb_pine_support
git add openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\fixtures\<name>\
git status  # confirm only the 4 new CSVs are staged (and .pine if new)
git commit -m "test(pine/conformance): add <name> fixture CSVs (#578)

Ships the equity + trades + stats + bars CSVs exported from TradingView
Strategy Tester on <symbol> <timeframe> for the <name> archetype.
Auto-registers with tests/conformance_strategy/conftest.py's discovery
walker; 3 parity tests now assert against real TV output.

TV export details:
- Symbol: <NASDAQ:AAPL / NYSE:SPY / etc>
- Timeframe: 1D
- Bar range: <YYYY-MM-DD> to <YYYY-MM-DD> (500 bars)
- TV account tier: Essential

Refs #578
"
git push -u origin feat/pine-578/<name>-fixture
gh pr create --repo prajoria/OpenBB --base openbb_pine_support \
  --title "test(pine/conformance): add <name> fixture CSVs (#578)" \
  --body "See commit message for details. Closes N of 5 fixture triples for #578."
```

If all 5 fixtures land in the same PR, use `Closes #578` in the body.
If you're shipping them one-by-one across multiple PRs, use `Refs #578`
until the last one and close manually with a summary comment.

---

## Part 6 — What to do when things go wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| TV Pine Editor won't compile the `.pine` | Copy-paste dropped a character; TV changed syntax | Re-paste from the file; check TV's error line number |
| Strategy Tester shows 0 trades | Signal condition never fires on your chart window | Widen the bar range or use a symbol with more volatility |
| CSV export button greyed out | Free-tier TV account | Upgrade to Essential ($15/mo, monthly cancellable) |
| Fixture doesn't appear in pytest collection | Missing or misnamed CSV | Check `pytest --collect-only -q` warning log for "missing: X" |
| Parity test fails with tiny numeric delta | Float precision or timestamp rounding | Compare our runtime output vs TV output side-by-side; may need a wider tolerance |
| Parity test fails with N vs M trade counts | Bar range differs, OR real runtime bug | If bar range matches, ping Claude with the CSVs — a bug worth investigating |
| `bars.csv` timestamps mismatch trade timestamps | TV export uses local timezone | Convert to UTC before saving: `2024-01-03T09:30:00-05:00` → `2024-01-03T14:30:00Z` |

---

## Part 7 — Quick reference

**Fixture location:**
`openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/<name>/`

**Per-fixture docs:**

- [`rsi_reversal/GUIDE.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/GUIDE.md) — deep-dive visual walkthrough (start here if new to TV)
- [`rsi_reversal/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/HOW_TO_EXPORT_FROM_TV.md)
- [`sma_crossover/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/sma_crossover/HOW_TO_EXPORT_FROM_TV.md)
- [`bb_squeeze/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/bb_squeeze/HOW_TO_EXPORT_FROM_TV.md)
- [`breakout_atr_trail/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/breakout_atr_trail/HOW_TO_EXPORT_FROM_TV.md)
- [`macd_histogram_signal/HOW_TO_EXPORT_FROM_TV.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/macd_histogram_signal/HOW_TO_EXPORT_FROM_TV.md)
- [`fixtures/README.md`](../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/README.md) — the parity-test intent doc (why we need these fixtures at all)

**Required files (all four):**
- `<name>.pine`
- `<name>.equity.csv` — 3 cols: `bar_index,equity,drawdown`, 500 rows
- `<name>.trades.csv` — see §3.6 for required columns
- `<name>.stats.csv` — 1 row, columns are the metric names

**Optional but strongly recommended:**
- `<name>.bars.csv` — 6 cols: `date,open,high,low,close,volume`

**Verify registration:**
```powershell
.venv_pine_support\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\ `
  --collect-only -q
```

**Run the fixture:**
```powershell
.venv_pine_support\Scripts\python.exe -m pytest `
  openbb_platform\extensions\pine\openbb_pine\tests\conformance_strategy\ `
  -k <name> -v
```

**Ship it:** `git checkout -b feat/pine-578/<name>-fixture` → commit → push → PR.

---

## Appendix — Why we need these fixtures at all

TradingView is the reference implementation of Pine Script. Our
`pyne_compiler` is a clean-room reimplementation. To claim conformance,
we need to prove — with real, TV-generated ground truth — that our
runtime produces the SAME equity curve, SAME trade list, and SAME
summary statistics as TV's Strategy Tester on the SAME input bars.

Every fixture triple you commit becomes a permanent regression test.
When someone changes our compiler or runtime six months from now, these
tests catch semantic drift immediately. Without them, we ship on hope.

This is exactly the failure mode CLAUDE.md's testing rules (§R7.1
realistic-shape fixtures) were written to prevent. The fixtures ARE the
realistic-shape data — TV is our ground truth source.

---

**Guide version:** 1.0 (2026-07-20)
**Authored by:** Claude, for Prashant, during the 2026-07-19/20 Pine
Phase 2 session.
**Feedback:** if a step is unclear or a TV UI change makes an
instruction stale, add a comment to GH #578 and Claude will revise this
guide in the next session.
