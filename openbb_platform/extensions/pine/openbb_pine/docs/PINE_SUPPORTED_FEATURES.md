# OpenBB Pine — Supported Features (alpha)

This is the human-readable inventory of what the Pine v6 → Python
compiler supports as of the alpha release. The **authoritative source**
is
[`openbb_pine/_coverage_manifest.py`](../_coverage_manifest.py) —
if this doc and the manifest disagree, the manifest wins.

## Coverage snapshot

As of alpha, **48/49 (97.96%)** of a curated 49-script wild corpus
compiles and runs unedited. PRD target M2 ≥70% — the alpha lands with a
28-point margin above the gate.

Pine language versions supported: **v5, v6**.

## Fully supported

### Directives

| Directive | Notes |
|-----------|-------|
| `indicator(...)` | Compiles to `@script.indicator` |
| `strategy(...)` | Compiles to `@script.strategy` (bd-aeh) |

### Strategy order-management builtins (bd-aeh + bd-h14)

- `strategy.entry`
- `strategy.exit`
- `strategy.close`
- `strategy.close_all`
- `strategy.cancel`
- `strategy.cancel_all`

### Strategy constants (bd-h14)

- `strategy.long`, `strategy.short`
- `strategy.fixed`, `strategy.cash`, `strategy.percent_of_equity`

### Strategy position introspection

- `strategy.position_size` (bd-9cae)

### Persistent state

- `var name = expr` — untyped persistent binding
- `var TYPE name = init` — typed persistent binding, including
  `var TYPE x = na` (bd-27v7, Persistent[T] annotation)
- `varip` — persistent-across-intrabar state

### Cross-timeframe

- `request.security(sym, tf, expr)` (bd-god)

### Language features (from `FEATURES_IMPLEMENTED`, 27 total)

`alert`, `close`, `for_loop`, `function_def`, `high`, `history_ref`,
`hline`, `if_else`, `indicator`, `input.bool`, `input.float`,
`input.int`, `input.source`, `input.string`, `low`, `na`, `nz`,
`open`, `plot`, `plotshape`, `ternary`, `time`, `type_annotation`,
`var`, `varip`, `volume`, `while_loop`.

### Builtins (from `BUILTINS_IMPLEMENTED`, 56 total)

**Colors:** `color.black`, `color.blue`, `color.gray`, `color.green`,
`color.new`, `color.orange`, `color.purple`, `color.red`, `color.white`,
`color.yellow`.

**Inputs:** `input.bool`, `input.float`, `input.int`, `input.source`,
`input.string`.

**Math:** `math.abs`, `math.exp`, `math.log`, `math.max`, `math.min`,
`math.pow`, `math.round`, `math.sign`, `math.sqrt`, `math.sum`.

**Strings:** `str.tonumber`, `str.tostring`.

**Technical analysis:** `ta.adx`, `ta.atr`, `ta.barssince`, `ta.bb`,
`ta.cci`, `ta.change`, `ta.crossover`, `ta.crossunder`, `ta.cum`,
`ta.ema`, `ta.highest`, `ta.linreg`, `ta.lowest`, `ta.macd`,
`ta.median`, `ta.mfi`, `ta.mom`, `ta.obv`,
`ta.percentile_linear_interpolation`, `ta.rma`, `ta.roc`, `ta.rsi`,
`ta.sar`, `ta.sma`, `ta.stdev`, `ta.stoch`, `ta.tr`, `ta.vwap`,
`ta.wma`.

## Known limitations (alpha)

### Deferred to M3

- **`library(...)` directive** — raises `PF011` at compile time
  (M3-deferred; alpha cannot compile user-authored libraries).

### Filed as gap beads (post-alpha)

- **`strategy.opentrades` / `closedtrades` / `wintrades` / `losstrades`**
  — position-history counters not supported. Workaround: check
  `strategy.position_size != 0` for in-position detection.
- **`plot.style_histogram` codegen** — plot-style constant not emitted
  correctly in some contexts (bd-jxhh).
- **Certain color constants in specific plot contexts** (e.g.
  `color.gray` in some `plot(...)` argument positions) — bd-jxhh.

### Conformance fixtures pending TV parity validation

Five conformance strategy fixtures ship with `.pine` sources plus
TV-export instructions in each fixture directory:

- `rsi_reversal`
- `sma_crossover`
- `breakout_atr_trail`
- `bb_squeeze`
- `macd_histogram_signal`

Expected CSVs (equity / trades / stats) await human TradingView Strategy
Tester exports (bd-ph0 phase 2). The Python side runs; only the parity
reference data is outstanding.

## Reporting missing features

Same channels as
[`PINE_ALPHA_QUICKSTART.md`](./PINE_ALPHA_QUICKSTART.md) — file a bd
issue or a GitHub issue with the `pine-alpha` label. Please include the
minimal Pine snippet that surfaces the gap and the actual error.

## For deep reference

The authoritative machine-readable manifest is
[`openbb_pine/_coverage_manifest.py`](../_coverage_manifest.py), which
exposes `FEATURES_IMPLEMENTED`, `BUILTINS_IMPLEMENTED`, and
`PINE_VERSIONS_SUPPORTED` as importable sets.
