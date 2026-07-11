# How to export `rsi_reversal` reference CSVs from TradingView

This fixture ships the Pine v6 strategy source (`rsi_reversal.pine`)
but AWAITS the expected `equity.csv`, `trades.csv`, and `stats.csv`
files sourced from TradingView's Strategy Tester UI. Until those land,
the bd-cht conformance harness auto-skips this triple (per
`_discover_strategy_triples()`'s incomplete-triple filter).

## Steps

1. Open [TradingView Pine Editor](https://www.tradingview.com/pine-script-editor/).
2. Paste the entire contents of `rsi_reversal.pine` into the editor.
3. Click **Add to Chart** — the strategy runs on whatever the current
   symbol/timeframe is.
4. **Set the chart to a deterministic 500-bar window**:
   - Symbol: any liquid instrument (e.g. AAPL, SPY, BTCUSDT)
   - Timeframe: 1D
   - Zoom to the most recent 500 bars
5. Open the **Strategy Tester** panel (bottom of the screen).
6. Verify the strategy compiled cleanly and shows a result summary.
7. Export three CSVs from the Strategy Tester panel:
   - **List of Trades → Export CSV** → save as `rsi_reversal.trades.csv`
   - **Performance Summary → Export CSV** (or the KPI table) → save as
     `rsi_reversal.stats.csv`
   - **Equity curve** (may require right-click → Export or a plugin) →
     save as `rsi_reversal.equity.csv` with columns
     `bar_index,equity,drawdown` (500 rows)
8. Commit the three CSVs into this directory. The bd-cht harness will
   auto-pick them up on next test run.

## Deterministic bars vs live TV bars — a caveat

bd-cht's harness uses a fixed-seed synthetic 500-bar random walk
(`_deterministic_500_bars()` in `conftest.py`, seed 20260711). TV
Strategy Tester runs on real market bars. This means the CSVs you
export from TV will NOT match a pyne_compiler run on the deterministic
bars — the expected values are for TV's bars, not the harness's.

**Two options to reconcile:**
- (a) Change the harness to load the fixture's `bars.csv` (a fourth
  CSV file capturing the bars the strategy ran on) instead of the
  deterministic generator. This makes fixtures self-contained.
- (b) Author fixtures to specify their bar window (symbol + timeframe
  + date range) and have a harness helper reproduce those exact bars
  from a data source. More coupling, less reproducibility.

Preferred: **(a)** — export a `rsi_reversal.bars.csv` alongside the
three CSVs. bd-ph0 phase 2 will land the harness change.

## Clean-room note

The Pine source in `rsi_reversal.pine` was authored from scratch
per PRD §2.5 (no viewing of TV or PyneComp source code). The reference
CSVs you export are the *output* of that script run on TV — this is
observing behavior, not copying source, and is inside the clean-room
constraint.
