# `rsi_reversal` — visual walkthrough (pilot)

This is the pilot walkthrough for the bd-ph0 phase-2 human-in-loop CSV
export workflow. Once this fixture's four CSVs are green, clone this
document into each of the other four fixture directories with strategy-
specific tweaks.

## 1. What you're doing

You are going to run our `rsi_reversal.pine` strategy inside
TradingView's Strategy Tester, then export four CSV files (`bars`,
`equity`, `trades`, `stats`) so our conformance harness can compare
our runtime's output against TradingView's on identical inputs.

## 2. Before you start

- [ ] A TradingView **Essential** account or higher (free tier does not
      reliably expose the export buttons).
- [ ] A modern browser (Chrome, Edge, Firefox). Safari works but menu
      positions occasionally differ.
- [ ] ~30–40 minutes of uninterrupted time.
- [ ] This repo checked out locally, and the fixture directory in an
      editor / file explorer:
      `openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/`
- [ ] The file `rsi_reversal.pine` in that directory open in a text
      editor so you can copy its full contents.

## 3. Step 1 — Open TradingView and sign in

1. Go to <https://www.tradingview.com/>.
2. Sign in (top-right → *Sign in*).
3. Confirm your plan is Essential+ (top-right avatar → *Account and
   billing*).

`[Screenshot: TradingView top nav bar with a signed-in avatar]`

## 4. Step 2 — Open a chart

We want a deterministic, liquid, ~500-bar window.

**Recommended:** SPY, timeframe `1D`, most recent 500 bars.
**Alternatives:** AAPL, MSFT, QQQ. All are highly liquid US equities
with clean daily bars and no listing gaps.
**Avoid:** crypto pairs (24×7 sessions confuse the bar count),
low-liquidity tickers (gaps blow up parity), and any symbol with
recent stock splits (adjustment differences vs FMP will surface as
"real" parity failures that are actually data-source noise).

1. Top-left of the toolbar → click the **symbol search** box (or press
   `/`). Type `SPY` and pick *SPDR S&P 500 ETF Trust*.
2. To the right of the symbol → click the **timeframe** button. Pick
   `1D` (Day).
3. Use `Ctrl+←` (back one bar range) / mouse-wheel until roughly 500
   daily bars are visible in the viewport.

`[Screenshot: TV chart of SPY, 1D timeframe, showing ~500 daily bars]`

## 5. Step 3 — Open the Pine Editor

1. Look at the **bottom panel** of the TV UI. It has multiple tabs
   (*Stock Screener*, *Strategy Tester*, *Pine Editor*, *Text Notes*,
   *Trading Panel*).
2. Click the **Pine Editor** tab. If it isn't visible, click the small
   `+` at the far right of the tab row and add it.

`[Screenshot: Bottom panel with the Pine Editor tab active]`

## 6. Step 4 — Paste the strategy source

1. In your local editor, open
   `openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/rsi_reversal.pine`.
2. Select the entire contents (`Ctrl+A`, `Ctrl+C`).
3. Back in the TV Pine Editor: click into the editor, `Ctrl+A` to
   select whatever is currently there, `Delete`, then `Ctrl+V` to paste
   the contents of `rsi_reversal.pine`.

`[Screenshot: Pine Editor pane with the rsi_reversal source pasted in]`

## 7. Step 5 — Save + Add to Chart

1. In the Pine Editor toolbar (top of that pane), click **Save**. Name
   the script `rsi_reversal_conformance`. It will save to your personal
   scripts.
2. Click **Add to chart**. The strategy compiles and, if successful,
   the RSI subchart appears below the price pane and the Strategy
   Tester tab populates.

`[Screenshot: "Add to chart" toolbar button with RSI subchart rendering below]`

If TV shows a **syntax error** here, **stop** and file a bd against
`openbb_pine` — the shipped `.pine` source must compile cleanly in TV
by definition (it's the ground truth). Do not silently mutate the
source to make it compile.

## 8. Step 6 — Open Strategy Tester

1. In the same bottom panel, click the **Strategy Tester** tab.
2. Depending on your TV version you should see 3–5 sub-tabs. The ones
   we care about are:
   - **Overview** — high-level summary numbers
   - **Performance Summary** — the full stats table
   - **List of Trades** — every closed (and open) trade
   - **Properties** — the strategy inputs TV used

`[Screenshot: Strategy Tester panel with Overview / Performance / Trades / Properties tabs visible]`

## 9. Step 7 — Verify the strategy actually ran

Look at **Overview → Total Trades**. It should be `> 0`.

- If it is `0`: either the RSI thresholds never triggered on this bar
  range, or the bar range is too short. First try widening to more
  bars (700–800). If still zero, file a bd — the fixture threshold
  choice or symbol needs to change.
- If it is a healthy number (say `5`–`40`), continue.

`[Screenshot: Strategy Tester Overview panel showing non-zero Total Trades]`

## 10. Step 8 — Export `stats.csv` (Performance Summary)

1. Click the **Performance Summary** sub-tab.
2. Click **Export CSV** (usually a small download icon at the top-right
   of the panel). If your TV version calls this "Download" or has it
   hidden in a `⋮` menu, use whichever affordance is present.
3. Save as `rsi_reversal.stats.csv` and move it into the fixture
   directory.

**Column-name alignment** — the harness's `_read_stats_csv` requires
the following exact column names (as used in `placeholder_smoke`):

```
net_profit, net_profit_percent, gross_profit, gross_profit_percent,
gross_loss, gross_loss_percent, max_drawdown, max_drawdown_percent,
max_runup, max_runup_percent, buy_and_hold_return,
buy_and_hold_return_percent, sharpe_ratio, sortino_ratio,
profit_factor, closed_trades, winning_trades, losing_trades,
percent_profitable, avg_trade, avg_winning_trade, avg_losing_trade,
largest_winning_trade, largest_losing_trade, avg_bars_in_trades,
commission_paid, max_contracts_held, open_trades,
max_cons_winning_trades, max_cons_losing_trades, ratio_avg_win_loss
```

TV's Performance Summary export uses **human-readable labels** (e.g.
`Net Profit`, `Percent Profitable`, `Sharpe Ratio`) — you will need
to rename headers to the snake_case names above. Additionally, TV
exports one row per metric with a "value / long-only / short-only"
shape; the harness expects **one wide row** with one column per
metric. In practice this means: open the CSV, transpose or rebuild it
to the exact shape shown in
`placeholder_smoke/placeholder_smoke.stats.csv` (header row + single
data row of numbers), and strip any `%` / `$` / thousands separators
so cells are plain numeric strings.

## 11. Step 9 — Export `trades.csv` (List of Trades)

1. Click the **List of Trades** sub-tab.
2. **Export CSV** → save as `rsi_reversal.trades.csv` in the fixture
   directory.

**Column-name alignment** — the harness's `_read_trades_csv` reads
whatever headers you give it (it's a `DictReader`), but the current
parity assertion checks **trade count only**. For consistency with the
placeholder, use these headers:

```
id, direction, qty, pnl, pnl_pct, bars_held, comment
```

TV exports a much wider trade table (entry time, entry price, exit
time, exit price, run-up, drawdown, cumulative profit, …). Extra
columns are harmless — the current assertion only counts rows — but
you should still rename headers so a future tightening of
`test_strategy_trade_list_exact_match` (planned for the first real
trading fixture) matches without a rewrite.

## 12. Step 10 — Export `equity.csv` (Equity Curve)

This one is the trickiest — TV does not always expose an equity-curve
CSV export in the same click-path as the trades / stats tables.

**Option A (preferred, if available):** In the Strategy Tester panel,
right-click the equity curve chart → *Export Chart Data* → *CSV*.

**Option B:** If your TV plan/version has a dedicated **Equity Curve**
sub-tab in Strategy Tester, use the export button there.

**Option C (fallback):** If neither is available, **stop** and file a
bd:

> `[ph0-p2 gap] TV Essential does not expose an equity-curve CSV
> export path for the Strategy Tester`

Two recovery paths from there:

1. **Upgrade to TradingView Premium** for the session that produces
   the fixtures.
2. **Reconstruct the curve** from `trades.csv` + `initial_capital`: walk
   the trade list bar-by-bar, applying realized PnL at each closing
   bar, to derive `equity[bar_index]`. Note this reintroduces class-3
   (data-source) uncertainty vs the true TV curve.

**Column-name alignment** — the harness's `_read_equity_csv` requires
exactly:

```
bar_index, equity, drawdown
```

TV likely exports `time` (or `date`) instead of `bar_index` — you must
transform to `bar_index` where `bar_index = 0` is the first bar of
your 500-bar window and `bar_index = 499` is the last. TV also
sometimes reports `drawdown` as a positive number and sometimes as a
signed value — inspect a few rows against
`placeholder_smoke/placeholder_smoke.equity.csv` (which uses positive
`drawdown`) and normalize accordingly.

## 13. Step 11 — Export `bars.csv`

1. **Right-click the main price chart** (the top pane with the SPY
   candles) → *Export Chart Data…*. On some TV builds this lives under
   the chart's `⋮` menu (top-right of the price pane).
2. In the dialog:
   - **Time format:** ISO (UTC preferred — matches the ISO strings the
     harness expects).
   - **Include hidden studies:** unchecked.
   - **Data:** OHLCV (the default).
3. Save as `rsi_reversal.bars.csv` in the fixture directory.

**Column-name alignment** — the harness's `_load_bars_csv` requires
exactly:

```
date, open, high, low, close, volume
```

TV likely exports the timestamp column as `time` instead of `date`,
and may include extras like `Volume MA 20`. Rename `time` → `date` and
drop any extra columns before committing.

`[Screenshot: Chart context menu with "Export Chart Data..." highlighted]`

Verify: `wc -l rsi_reversal.bars.csv` should show approximately `501`
(500 data rows + 1 header row).

## 14. Step 12 — Commit and test

1. Sanity-check the four files are present:
   ```bash
   ls openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/
   ```
   You should see `rsi_reversal.pine`, `rsi_reversal.bars.csv`,
   `rsi_reversal.equity.csv`, `rsi_reversal.trades.csv`,
   `rsi_reversal.stats.csv`, plus the two doc files.
2. Run the parity subset:
   ```bash
   .venv_win\Scripts\python.exe -m pytest \
     openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy \
     -q -k rsi_reversal 2>&1 | tail -10
   ```
   Expected: **3 tests run** (`test_strategy_equity_parity`,
   `test_strategy_trade_list_exact_match`, `test_strategy_stats_parity`).
   Green on all three = parity confirmed and the fixture is ready to
   ship.
3. If any test **fails**, that is a real parity gap. File a bd
   describing which assertion failed and paste the pytest diff.
4. If everything passes, commit and open a PR:
   ```bash
   git switch -c fixtures/rsi-reversal-tv-csvs openbb_pine_support
   git add openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/*.csv
   git commit -m "test(pine): rsi_reversal TV-exported reference CSVs (bd-ph0)"
   git push -u origin fixtures/rsi-reversal-tv-csvs
   gh pr create --base openbb_pine_support --head fixtures/rsi-reversal-tv-csvs \
     --title "test(pine): rsi_reversal TV reference CSVs (bd-ph0)"
   ```

## 15. Common gotchas

- **TV column names ≠ harness column names.** The harness parsers use
  snake_case, single-word names (`net_profit`, `bar_index`, `date`).
  TV exports human labels. Rename before committing.
- **Timestamp column name.** TV uses `time` for bar exports; harness
  wants `date`. Rename.
- **`bar_index` vs timestamps.** The equity harness wants an integer
  `bar_index` starting at 0. TV exports timestamps. Transform.
- **Decimal separator.** If your TV account or OS locale is set to a
  European locale, TV may export decimals as `1,234` — the harness
  expects `1234`. Change locale to `en-US` before export, or run a
  find-replace on the CSV.
- **Quote characters and thousands separators.** Strip `"1,234.56"` →
  `1234.56` in numeric cells; `_read_stats_csv` does not tolerate
  thousands separators.
- **The 500-bar count.** "Visible on screen" is not the same as "in
  the exported dataset" — verify the row count of `bars.csv` matches
  the row count of `equity.csv` (should both be ~500).
- **Session hours.** For equities the daily bar is one row per RTH
  session. For crypto it's 24×7. If you accidentally used a crypto
  symbol you will get too many bars per calendar month.
- **Split / dividend adjustments.** TV and FMP occasionally disagree
  on adjustment factors. This is why we ship `bars.csv` — the harness
  uses TV's bars, sidestepping the disagreement entirely. Do not
  substitute FMP bars for TV bars.
- **Currency parameter.** If TV's strategy `Properties` shows a
  different `currency` than the Pine source's default, note it — it
  can shift `net_profit` values by an FX factor.

## 16. What "success" looks like

- Four CSVs in the fixture directory: `rsi_reversal.bars.csv`,
  `.equity.csv`, `.trades.csv`, `.stats.csv`.
- `pytest -k rsi_reversal` shows **3 passed** with no `SKIPPED`.
- No unresolved TV interaction blockers (equity export path worked, or
  the Option-C bd is filed).
- A short note in this fixture's `HOW_TO_EXPORT_FROM_TV.md` recording
  any deviations (symbol used, TV version, bar-count actual, header
  renames applied).

## 17. Next steps

Once `rsi_reversal` is green, clone this `GUIDE.md` into each of the
remaining four fixture directories (`sma_crossover`,
`macd_histogram_signal`, `bb_squeeze`, `breakout_atr_trail`) with
per-strategy tweaks (different symbol/timeframe if appropriate,
different expected trade-count sanity number in Step 7). The 30–40
minute budget per fixture × 4 remaining fixtures ≈ ~2.5 hours to
complete bd-ph0 phase 2 end-to-end.
