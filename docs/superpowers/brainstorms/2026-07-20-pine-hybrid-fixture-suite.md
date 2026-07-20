# Brainstorm: Hybrid Pine fixture design — TV trades + fmp_cached bars

| Field | Value |
|---|---|
| **Status** | Brainstorm / proposal — awaiting decisions on 6 open questions |
| **Program** | Pine Script Support (GH Project #5) |
| **Related issues** | #578 (5 pilot fixtures), #584 (request.security corpus), #586 (v5 roundtrip) |
| **Related PRs / docs** | [PR #946](https://github.com/prajoria/OpenBB/pull/946) (fixture prep guide), [`docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md`](../../pine/HOW_TO_PREPARE_TV_FIXTURES.md) |
| **Author** | Claude (2026-07-20 session, drafted from Prashant's question mid-workflow on rsi_reversal fixture) |
| **Reviewer** | @prashant (approval required before promoting to a `docs/superpowers/specs/` design doc) |

---

## Context

Prashant asked, mid-workflow on fixture #578: *"can you use fmp_cached
backed data for most of other datasets? as they can't be different in
TV correct? keeping your fixtures in mind trade file comes from TV but
probably others can be created from fmp_cache data? create a proposal/
brainstorm .md file"*

The clarifying question landed on the **hybrid design**: TV's Strategy
Tester List-of-Trades stays as the fixture (it's the load-bearing
artifact humans can verify), but bars come from `fmp_cached` and the
equity/stats parity assertions get **derived at test time by re-running
the strategy through our runtime on those bars**. If our trades match
TV's, everything downstream (equity trajectory, KPIs) follows from
identical arithmetic. If they don't, we've caught a real bug.

This flips fixture prep from a 4-CSV chore (`bars` + `trades` + `equity`
+ `stats`) to a 1-CSV chore (`trades`). Cheaper per fixture, more
fixtures possible for the same human time budget.

**This is a brainstorm / proposal**, not an approved implementation
plan. It documents the design and the open questions so a next-session
decision can be made cleanly.

---

## The design in one paragraph

For each fixture:

1. **`.pine` source** — same as today, checked into the repo.
2. **`.trades.csv`** — from TV Strategy Tester, reshaped to our
   1-row-per-round-trip schema (already done for `rsi_reversal` via
   [`Tools/pine/reshape_tv_trades.py`](../../../Tools/pine/reshape_tv_trades.py)).
3. **`.provenance.json`** (NEW) — declares the exact `(provider,
   symbol, start_date, end_date, adjustment)` the trades were sourced
   against, plus a content hash of the resolved bars at capture time so
   we can detect fmp_cached drift.
4. **NO `bars.csv`, NO `equity.csv`, NO `stats.csv` in the fixture dir.**
   Bars are fetched at test time from fmp_cached with the exact
   `(symbol, start, end, adjustment)` from provenance.json, hashed, and
   compared to the recorded content hash. Equity and stats are what
   our runtime PRODUCES on those bars — the parity assertion is against
   the TV trades file, not against pre-recorded equity/stats.

---

## Why this works

**Trades are the load-bearing artifact.** If our runtime produces the
same closed-round-trip list TV does (same entry/exit dates, prices, qty,
direction) on the same bars, then:

- Our equity curve = deterministic function of trades + initial capital
  → matches TV's within float precision.
- Our KPIs (win_rate, profit_factor, max_drawdown, etc.) = deterministic
  function of trades + equity curve → match TV's within float precision.

So we only need to assert **trades match** to catch every downstream
divergence.

**Bars stability is enforceable via content hash.** The provenance file
records the SHA-256 of the sorted bars fmp_cached returned at capture
time. At test time, we fetch the same `(symbol, start, end, adjustment)`
and hash the result. If the hash matches, we know the fmp_cached cache
hasn't drifted for that window and the test is reproducible. If the
hash differs, the test fails with a clear "fmp_cached drift" error
naming what changed — human intervention required (a mini "license
manifest" pattern from PR #906).

---

## What we compare, what we discard

| Artifact | Source | Fixture file? | Compared? |
|---|---|---|---|
| `.pine` | Repo | ✅ yes | — (input) |
| Bars | fmp_cached at test time | ❌ no (regenerated) | Hash-verified vs provenance |
| Trades (recorded) | TV Strategy Tester | ✅ `.trades.csv` | Compared to runtime output |
| Trades (runtime output) | Our runtime | ❌ no (generated) | ← This is the parity assertion |
| Equity curve | Our runtime | ❌ no | — (never recorded, never compared) |
| Stats / KPIs | Our runtime | ❌ no | — (never recorded, never compared) |

The old `conformance_strategy/` suite compared **all three** (equity,
trades, stats). The hybrid compares **only trades**, on the theory that
trades are the load-bearing signal and everything else is a downstream
computation.

---

## Trade-offs vs the current 4-CSV design

### Wins

- **1 export per fixture instead of 4.** Human time drops ~75%.
  Realistic to have 20+ fixtures instead of 5.
- **No TV Essential requirement (probably).** Free-tier TV can export
  List of Trades (needs verification — see open question #1 below). If
  yes, contributors don't need a $15/mo TV account.
- **No manual equity export.** That was the flakiest step in the guide
  (TV UI varies by version; add-a-plot workaround needed).
- **No manual stats pivot.** The `metric,value → 1-row` reshape
  disappears.
- **CI runs the strategy end-to-end,** not just parity assertions. Any
  runtime crash surfaces immediately.
- **Bars provenance is machine-checkable** — no "did I use the right
  500-bar window?" ambiguity; the provenance file names the exact dates.

### Losses

- **Weaker parity signal.** If TV's equity computation differs from
  ours (different treatment of margin interest, borrow fees, weekend
  gaps, etc.), the hybrid design MISSES that class of bug because
  equity is never compared. Trades match ≠ equity matches, if the
  runtime has an equity-computation bug separate from trade-generation.
  Mitigation: keep at least ONE fixture (`rsi_reversal`) in the old
  4-CSV form as a "full-parity canary" that catches equity-arithmetic
  drift the hybrid tests would miss.
- **fmp_cached becomes a hard test dependency.** CI needs MySQL + FMP
  API key. Current conformance suite runs without them (bars are either
  deterministic-generated or provided as CSV). Mitigation:
  `pytest.importorskip` pattern — hybrid tests skip when fmp_cached
  isn't installed / configured (same pattern used by #585's
  `test_backtest_bridge_integration.py`).
- **Adjustment methodology drift.** TV's splits/dividend adjustment for
  AAPL historical bars may differ from FMP's at the pennies-precision
  level, especially pre-2020 splits. If our runtime processes fmp_cached
  bars and produces trades that differ from TV's trades by ONE cent on
  the entry price, the trade-list parity assertion fails. Mitigation:
  wider tolerance on the price columns (e.g. `abs(a-b) < 0.01`) with a
  loud warning when the delta exceeds a threshold.
- **fmp_cached snapshot drift.** Even with the content-hash gate, when
  the hash changes (fmp corrects a historical bar) the human has to
  decide: is this an fmp fix (accept + bump the recorded hash + verify
  trades still match) or an fmp regression (revert)?
- **New failure modes** — MySQL connection issues, FMP API rate limits,
  cache-population race conditions on cold CI runners. Each needs a
  documented recovery path.

### Neutral

- **Trades reshape still needed.** `reshape_tv_trades.py` runs
  regardless of which design. Already shipped in PR #946.
- **Existing 5 fixtures.** They already have `.pine` sources. Adding
  provenance.json + trades.csv migrates each in minutes.

---

## Open questions the plan needs answered before implementation

1. **Does TV Free-tier support List of Trades export?** If NO, the "no
   Essential required" win vanishes. Prashant would know from his own
   account.

2. **How wide a tolerance is acceptable on trade price parity?**
   TradingView uses its own split-adjustment; FMP uses its own. On
   AAPL 1981-2026 the raw prices are pennies (post-adjustment for the
   1987/2000/2005/2014/2020 splits) — an `abs(TV_price - FMP_price)`
   delta of $0.01 is 10% of a $0.10 pre-split price but 0.003% of a
   $300 post-2020 price. Absolute vs relative tolerance choice.

3. **Should the hybrid suite REPLACE `conformance_strategy/` or run
   PARALLEL?** Proposal: parallel — keep one full-parity canary
   fixture in the old suite (`rsi_reversal`, since it's the one being
   built now), migrate the other 4 pilots to the hybrid design when
   they land. New fixtures default to hybrid unless there's a specific
   reason to lock in full parity.

4. **Where does the hybrid suite live?**
   - Option A: `tests/conformance_strategy_hybrid/` (parallel to
     existing `tests/conformance_strategy/`)
   - Option B: `tests/conformance_strategy/` with a marker on each
     fixture indicating "hybrid mode" vs "full-parity mode"
   - Option A keeps the two suites' failure modes cleanly separated;
     Option B avoids code duplication. Recommendation: **B** — one
     suite, one discovery walker, mode flag on the provenance file.

5. **Does the hybrid suite gate CI merge?** Or is it a
   nightly/scheduled-only test since it needs MySQL+FMP? Current
   `conformance_strategy/` gates CI merge. Recommendation: **hybrid
   suite runs on every PR but SKIPS when fmp_cached isn't configured**;
   the current 4-CSV canary always runs (no deps).

6. **What happens when TV renames columns in a future update?**
   `reshape_tv_trades.py` is currently coded against today's TV column
   names. When TV changes them (they do, periodically), the reshape
   breaks and human intervention updates the column map. This is
   already true of the current design — not new.

---

## Provenance.json shape (draft)

```json
{
  "schema_version": 1,
  "fixture_name": "rsi_reversal",
  "captured_at": "2026-07-20",
  "captured_by": "prashant@masterswork",
  "trades_source": {
    "tool": "TradingView Strategy Tester",
    "symbol": "NASDAQ:AAPL",
    "timeframe": "1D",
    "start_date": "1981-01-01",
    "end_date": "2026-07-20"
  },
  "bars_source": {
    "provider": "fmp_cached",
    "symbol": "AAPL",
    "start_date": "1981-01-01",
    "end_date": "2026-07-20",
    "adjustment": "splits_only",
    "bars_sha256": "3f2a...b7e1",
    "bars_row_count": 11482
  },
  "parity_assertions": {
    "trades": "exact match on (date_entry, date_exit, type)",
    "trades_price_tolerance": {"absolute": 0.01, "relative": 0.001},
    "equity": "not compared (derived at test time)",
    "stats": "not compared (derived at test time)"
  },
  "canary_mode": false
}
```

`canary_mode: true` on the ONE fixture that also ships the old
`.equity.csv` + `.stats.csv` for full-parity assertion — that fixture
runs both hybrid AND full-parity assertions.

---

## Files that would be touched (future session, NOT this brainstorm)

- **NEW** `docs/superpowers/specs/YYYY-MM-DD-pine-hybrid-fixture-suite-design.md`
  — full design spec derived from this brainstorm, with answers to the
  6 open questions filled in
- **MODIFIED** `openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/conftest.py`
  — extend `_discover_strategy_triples` to detect hybrid-mode fixtures
  (provenance.json present) and construct bars from fmp_cached instead
  of reading bars.csv
- **NEW** `Tools/pine/capture_bars_provenance.py` — utility to
  regenerate provenance.json for a fixture after an intentional
  fmp_cached cache refresh
- **MODIFIED** `docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md` — add a new
  Part describing the hybrid workflow as the DEFAULT for new fixtures;
  demote the 4-CSV full-parity workflow to "canary" status
- **MODIFIED** each of the 4 not-yet-exported fixture dirs (
  `sma_crossover`, `bb_squeeze`, `breakout_atr_trail`,
  `macd_histogram_signal`) — add provenance.json, drop expectation of
  equity.csv/stats.csv/bars.csv

---

## What this brainstorm explicitly does NOT ship

- **No code changes.** This file is a brainstorm/proposal.
- **No `provenance.json` on the in-flight `rsi_reversal` fixture** —
  that one stays as the full-parity canary per open question #3.
- **No breaking change to the current suite** — hybrid mode is additive.
- **No decision on the 6 open questions** — those need a next-session
  discussion with @prashant.

---

## Recommended next steps

1. **This session (docs-only):** ship this brainstorm to the repo so
   future sessions can find it and reference it. Done via the PR
   containing this file.
2. **Next session (short):** answer the 6 open questions inline in this
   file (or in a review comment thread), then promote to a formal
   design spec under `docs/superpowers/specs/`.
3. **Session after that (implementation):** land the `conftest.py`
   hybrid-mode plumbing + provenance.json for one non-canary fixture
   (e.g. `sma_crossover`) as the pilot. Verify it catches bugs the
   canary catches, then migrate the other 3.
4. **Ongoing:** new fixtures default to hybrid; canary count stays at
   1 (`rsi_reversal`) unless a specific runtime-arithmetic concern
   arises.

---

## Verification (for the deliverables when they eventually ship)

- **This brainstorm file:** @prashant reads it and can articulate the
  hybrid design + trade-offs in their own words. That's the entire
  success criterion for a brainstorm.
- **Full design spec** (future): peer review that all 6 open questions
  have concrete answers; the spec is ready to implement.
- **Implementation** (future): a hybrid fixture triple lands, its
  parity test fires on a real Pine runtime regression that we
  deliberately introduce and revert (R7.7 reverse-verification, same
  pattern used throughout the 2026-07-19/20 Pine session).

---

## See also

- [`docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md`](../../pine/HOW_TO_PREPARE_TV_FIXTURES.md)
  — the current 4-CSV fixture prep guide. Would be updated (not
  replaced) if this brainstorm is approved.
- [`openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/README.md`](../../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/README.md)
  — the parity-test intent doc that motivates the fixture suite in the
  first place.
- [`Tools/pine/reshape_tv_trades.py`](../../../Tools/pine/reshape_tv_trades.py)
  — the TV trades CSV reshape tool, already shipped in PR #946. This
  brainstorm assumes it stays.
- [PR #906](https://github.com/prajoria/OpenBB/pull/906) — where the
  "license manifest" pattern this brainstorm references (SHA + drift
  detection + manual refresh command) was introduced.
