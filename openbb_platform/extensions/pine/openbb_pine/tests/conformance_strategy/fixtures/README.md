# conformance_strategy fixtures

This directory holds the reference fixtures the `conformance_strategy`
parity suite runs against. Each subdirectory is one **fixture triple**
(actually four required files plus one optional bars file — see below)
that pins a Pine strategy's TradingView output as ground truth and
compares our runtime's output against it.

## What's in this directory

Six subdirectories, each named after its strategy:

- `placeholder_smoke/` — never-trades smoke fixture used by bd-cht to
  keep the harness alive before any real strategies land. Runs against
  the deterministic 500-bar synthetic walk (no `bars.csv`).
- `rsi_reversal/` — pilot for the human-in-loop TV export workflow.
- `sma_crossover/`, `macd_histogram_signal/`, `bb_squeeze/`,
  `breakout_atr_trail/` — the four remaining bd-ph0 archetype fixtures.
  Their CSV triples are pending the same TV-export workflow the
  `rsi_reversal` pilot documents.

## The parity-test intent

The point of these fixtures is **not** to check that our Pine compiler
emits valid Python — that's what the unit suite does. The point is to
check that executing a real Pine v6 strategy through our
`pyne_compiler` + `run_byo` runtime produces the **same equity curve,
same trade list, and same summary statistics** as TradingView's own
Strategy Tester on the **same input bars**.

When a parity assertion fails, exactly one of these things is true:

1. **Compiler bug** — our emitted Python doesn't faithfully translate
   the Pine source.
2. **Runtime bug** — the compiled Python is correct but our
   `strategy.*` primitives (entry, close, position sizing, commissions,
   fill model) don't match TV's semantics.
3. **Data-source difference** — the bars our test fed the runtime don't
   match the bars TV ran the strategy against. This is why the
   `bars.csv` file exists (bd-0ru2): we ship the exact OHLCV series TV
   ran on, so this class of failure is eliminated by construction.
4. **A genuine TV quirk** — TradingView has undocumented behavior we
   need to match (or explicitly deviate from and document why).

The five real fixtures each cover one common Pine strategy archetype so
we surface parity gaps across the surface area a real user's script
would hit:

| Fixture | Archetype |
|---|---|
| `rsi_reversal` | Oscillator mean-reversion |
| `sma_crossover` | Trend-following crossover |
| `macd_histogram_signal` | Momentum / oscillator signal |
| `bb_squeeze` | Volatility contraction/expansion |
| `breakout_atr_trail` | Breakout with ATR trailing stop |

## Files per fixture

| File | Required? | Source | Purpose |
|---|---|---|---|
| `<name>.pine` | Yes | Hand-authored (clean-room) | Pine v6 strategy source, run by TV *and* by our runtime |
| `<name>.bars.csv` | Optional* | TV chart → *Export chart data* | Exact OHLCV series TV ran on; harness feeds these into `run_byo` |
| `<name>.equity.csv` | Yes | TV Strategy Tester → equity curve | Bar-by-bar equity + drawdown, ground truth for `test_strategy_equity_parity` |
| `<name>.trades.csv` | Yes | TV Strategy Tester → *List of Trades* | Closed-trade table, ground truth for `test_strategy_trade_list_exact_match` |
| `<name>.stats.csv` | Yes | TV Strategy Tester → *Performance Summary* | One-row summary stats dict, ground truth for `test_strategy_stats_parity` |
| `HOW_TO_EXPORT_FROM_TV.md` | Recommended | Fixture author | Short per-fixture export notes (symbol/timeframe/inputs used) |
| `GUIDE.md` | Recommended for first fixture | Fixture author | Step-by-step walkthrough — see `rsi_reversal/GUIDE.md` as the pilot |
| `regenerate.py` | `placeholder_smoke` only | — | Regenerates the smoke fixture's deterministic CSVs; real fixtures do not have this |

\* Without a `bars.csv`, the harness falls back to the deterministic
500-bar synthetic walk (`_deterministic_500_bars` in `conftest.py`,
seed `20260711`). Only `placeholder_smoke` uses that path.

## What TradingView plan is required

**TradingView Essential** or higher. The free tier does not reliably
expose the Strategy Tester CSV export buttons and caps chart data
export. Premium is nice-to-have (larger bar histories, more reliable
equity-curve export) but Essential is sufficient for the 500-bar
fixtures shipped here. If Essential turns out to be insufficient for
the equity-curve export specifically, that's a real gap — see the
"Step 10" note in `rsi_reversal/GUIDE.md`.

## The workflow at a glance

1. Pick a fixture directory whose CSV triple is missing (any of the
   four besides `placeholder_smoke` and `rsi_reversal` once that pilot
   lands).
2. Follow `rsi_reversal/GUIDE.md` as the master walkthrough. Adapt
   symbol/timeframe/strategy-specific notes as needed for your fixture.
3. Run the strategy in TradingView on the target symbol/timeframe
   window.
4. Export the four CSVs (`bars`, `equity`, `trades`, `stats`), renaming
   headers as required so the harness's `_read_*_csv` parsers accept
   them.
5. Commit the four CSVs into the fixture's directory.
6. Run
   `pytest openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy -q -k <fixture-name>`.
   Green = parity confirmed. Any failure is a real gap — file a bd and
   link it to bd-ph0.

## Clean-room posture on TV exports

We author the `.pine` sources from scratch (no viewing of TradingView
or PyneComp source). Observing the *output* of our own scripts on TV's
public UI — bar values, trade lists, summary stats — is behavior
observation, not source copying, and is inside the clean-room
constraint per PRD §2.5. Do **not** paste TV example scripts into these
fixtures, and do **not** consult TV or PyneComp source to understand
how a specific `strategy.*` primitive is implemented internally.

## Adding a sixth (or Nth) fixture

1. Author a new Pine v6 strategy source in a fresh
   `fixtures/<name>/<name>.pine`. Keep it small (single-entry / single-
   exit is easiest to reason about) and clean-room.
2. Follow the `rsi_reversal/GUIDE.md` walkthrough end-to-end to produce
   the four CSVs. Save them alongside the `.pine` file using the
   `<name>.<kind>.csv` naming convention.
3. Add a short `HOW_TO_EXPORT_FROM_TV.md` capturing the symbol,
   timeframe, bar count, and any per-input overrides you set in TV.
4. Run the parity suite — if it passes, open a PR. If it fails,
   diagnose whether the failure is a runtime bug (file a bd) or a
   fixture-recording error (redo the export).
