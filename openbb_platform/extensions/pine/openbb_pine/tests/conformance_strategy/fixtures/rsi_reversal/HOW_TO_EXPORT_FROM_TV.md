# How to export `rsi_reversal` reference CSVs from TradingView

> **See also:**
> - [`GUIDE.md`](./GUIDE.md) (same directory) — deep-dive visual walkthrough
>   of the TradingView UI for this fixture (~325 lines with screenshot
>   placeholders and pre-flight checklist).
> - [`docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md`](../../../../../../../../docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md)
>   — the meta-guide covering the fixture concept, CSV schema, PowerShell
>   massaging snippets, commit + PR flow, and cross-fixture troubleshooting.
>
> This stub below is the quick reference. Read the meta-guide first if
> you're new to the workflow; read `GUIDE.md` if you're new to TradingView.

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

## Deterministic bars vs live TV bars — reconciled via `bars.csv`

bd-cht's original harness used a fixed-seed synthetic 500-bar random
walk (`_deterministic_500_bars()` in `conftest.py`, seed 20260711).
TV Strategy Tester runs on real market bars, so a naive export would
not match a pyne_compiler run on the synthetic bars.

**Landed in bd-0ru2**: export a `rsi_reversal.bars.csv` alongside the three
CSVs — the harness auto-detects it and uses those bars for the parity
comparison, so the fixture is self-contained and byte-reproducible on
any machine. If `bars.csv` is absent, the harness falls back to the
deterministic 500-bar synthetic walk (used only by the internal
`placeholder_smoke` fixture).

### How to export `bars.csv` from TradingView

TradingView exposes the underlying OHLCV on the chart itself, not the
Strategy Tester panel:

1. With the strategy still on the chart and the 500-bar window set
   exactly as it was for the three tester CSVs, click the chart title
   (top-left of the chart pane) → **Export chart data…** (also
   available via the chart's `⋮` menu → *Export chart data…*).
2. In the dialog:
   - **Time format**: ISO (UTC preferred — matches
     `_deterministic_500_bars()`'s `2024-01-01T00:00:00+00:00` shape)
   - **Include hidden studies**: unchecked
3. Save as `rsi_reversal.bars.csv` in this directory.
4. Verify the file has columns exactly:
   `date, open, high, low, close, volume` (rename any TV variants like
   `time` → `date` if needed — the harness's `_load_bars_csv()` requires
   these exact names).
5. The row count should match the strategy's bar range (typically 500).

The harness's `_load_bars_csv()` keeps `date` as a raw string and
parses OHLCV to `float` — the same record shape `run_byo` expects and
that `_deterministic_500_bars()` produces.

## Clean-room note

The Pine source in `rsi_reversal.pine` was authored from scratch
per PRD §2.5 (no viewing of TV or PyneComp source code). The reference
CSVs you export are the *output* of that script run on TV — this is
observing behavior, not copying source, and is inside the clean-room
constraint.
