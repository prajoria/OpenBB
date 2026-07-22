# Brainstorm: Hybrid Pine fixture design — TV trades + fmp_cached bars

| Field | Value |
|---|---|
| **Status** | Brainstorm / proposal — awaiting decisions on 6 open questions |
| **Program** | Pine Script Support (GH Project #5) |
| **Related issues** | #578 (5 pilot fixtures), #584 (request.security corpus), #586 (v5 roundtrip) |
| **Related PRs / docs** | [PR #946](https://github.com/prajoria/OpenBB/pull/946) (fixture prep guide), [`docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md`](../../pine/HOW_TO_PREPARE_TV_FIXTURES.md) |
| **Author** | Claude (2026-07-20 session, drafted from Prashant's question mid-workflow on rsi_reversal fixture) |
| **Reviewer** | @prashant (approval required before promoting to a `docs/superpowers/specs/` design doc) |
| **HARD CONSTRAINT (2026-07-20)** | @prashant's TV plan is **Essential**, which allows exporting **List of Trades only** — bars, equity curve, and Performance Summary CSVs are **not exportable** from this tier. This kills the 4-CSV canary path unless someone with TV Premium provides those CSVs, or canaries are re-designed to use synthetic/deterministic bars. See open question **Q7** below. |

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

   > **Recommendation (Claude):** Empirical — Prashant to confirm from
   > his account. But treat the answer as **non-blocking**: even if
   > free-tier exports trades, the export omits the *adjustment* and
   > *strategy settings* used, which we must capture separately in
   > `provenance.json` regardless (see A4/B4). So the design proceeds
   > either way; a NO only removes the "no paid TV" bullet from the
   > Wins list, it does not change the architecture. Don't gate
   > implementation on this.
[PR] I agree for now
2. **How wide a tolerance is acceptable on trade price parity?**
   TradingView uses its own split-adjustment; FMP uses its own. On
   AAPL 1981-2026 the raw prices are pennies (post-adjustment for the
   1987/2000/2005/2014/2020 splits) — an `abs(TV_price - FMP_price)`
   delta of $0.01 is 10% of a $0.10 pre-split price but 0.003% of a
   $300 post-2020 price. Absolute vs relative tolerance choice.

   > **Recommendation (Claude):** This is the wrong question to lead
   > with — tolerance is *downstream* of window selection. Fix the
   > window first (**start 2025-01-01**, per R1) so both series are
   > post-last-split and congruent; that largely dissolves the problem.
   > For the residual, use **relative** tolerance, never absolute:
   > structural gate = trade count/ordering/direction must match
   > **exactly** (zero tolerance); numeric gate = per-row price/PnL
   > within `abs(a-b)/max(|a|,|b|) < 1e-3` (~10 bps) with a loud
   > warning at half that. Never let the numeric tolerance paper over
   > a count mismatch — a differing trade *set* is a structural fail,
   > not a rounding issue.

   [PR] accept

3. **Should the hybrid suite REPLACE `conformance_strategy/` or run
   PARALLEL?** Proposal: parallel — keep one full-parity canary
   fixture in the old suite (`rsi_reversal`, since it's the one being
   built now), migrate the other 4 pilots to the hybrid design when
   they land. New fixtures default to hybrid unless there's a specific
   reason to lock in full parity.

   > **Recommendation (Claude):** Agree with **parallel**, but bump the
   > canary count above 1. A single canary is too thin for the exact
   > surface (max-drawdown / intrabar equity) that trades-only parity
   > cannot cover (see A1). Keep **~20–25% of fixtures as full 4-CSV
   > canaries**, chosen to span distinct KPI surfaces (one
   > drawdown-heavy, one short-selling, one pyramiding). New fixtures
   > default to hybrid; canaries are deliberately curated, not
   > incidental.

   [PR] Parallel accepted.

4. **Where does the hybrid suite live?**
   - Option A: `tests/conformance_strategy_hybrid/` (parallel to
     existing `tests/conformance_strategy/`)
   - Option B: `tests/conformance_strategy/` with a marker on each
     fixture indicating "hybrid mode" vs "full-parity mode"
   - Option A keeps the two suites' failure modes cleanly separated;
     Option B avoids code duplication. Recommendation: **B** — one
     suite, one discovery walker, mode flag on the provenance file.

   > **Recommendation (Claude):** **B is fine, but only if the
   > completeness-rewrite is done properly** (see B3). Today
   > `_discover_strategy_triples` treats any dir lacking
   > equity/trades/stats as *incomplete and skips it* — so hybrid
   > fixtures would be silently dropped. Option B must make
   > completeness *mode-dependent*: provenance.json present ⟹ hybrid
   > completeness (`pine + trades + provenance`); absent ⟹ legacy
   > completeness (the current four). Preserve the loud WARNING skip in
   > *both* modes. **If time-boxed, prefer A** — it doesn't touch the
   > harness's loudest safety property and can't silently swallow a
   > half-authored fixture.

   [PR] Option B

5. **Does the hybrid suite gate CI merge?** Or is it a
   nightly/scheduled-only test since it needs MySQL+FMP? Current
   `conformance_strategy/` gates CI merge. Recommendation: **hybrid
   suite runs on every PR but SKIPS when fmp_cached isn't configured**;
   the current 4-CSV canary always runs (no deps).

   > **Recommendation (Claude):** Agree, with one honesty caveat: on
   > PR CI (no MySQL, no FMP key) `pytest.importorskip` means the
   > hybrid tests **skip**, i.e. they provide **zero PR-gate coverage**
   > in exactly the environment where you'd want them (see B2). So the
   > deterministic **4-CSV canaries are what actually gate merge**;
   > the hybrid suite is best run as a **nightly/scheduled job** on a
   > runner that *does* have MySQL+FMP, where a skip is treated as a
   > failure (not a pass). Decide this deliberately rather than letting
   > "skips silently" become the default posture.

   [PR] agree

6. **What happens when TV renames columns in a future update?**
   `reshape_tv_trades.py` is currently coded against today's TV column
   names. When TV changes them (they do, periodically), the reshape
   breaks and human intervention updates the column map. This is
   already true of the current design — not new.

   > **Recommendation (Claude):** Correctly a pre-existing risk, not a
   > hybrid-specific one — don't let it block this design. Make the
   > failure *loud and self-explaining*: have `reshape_tv_trades.py`
   > validate the input header against its expected `_SHARED_COLUMN_MAP`
   > keys and raise a clear `ValueError` naming the missing/renamed
   > columns (fail at reshape time, not silently downstream). Record
   > the TV `export_schema_version` (or a header fingerprint) in
   > `provenance.json` so a future break is diagnosable at a glance.
   > Low priority — implement opportunistically, not as a blocker.

   [PR] agree with cluade recommendation.

7. **TV Essential tier exports trades only — how do we source canaries
   (equity.csv + stats.csv) and PR-gate bars?** @prashant's TV plan
   allows Strategy Tester → List of Trades export, but NOT the equity
   curve or Performance Summary. This invalidates two things we just
   accepted:
   - **D1.3's canary count (2-3 full-parity canaries):** canaries by
     definition ship `.equity.csv` and `.stats.csv` sourced from TV.
     Without Premium, they cannot be produced.
   - **D1.6's PR gate:** the plan was "4-CSV canaries gate PR
     deterministically, hybrid runs nightly." If canaries don't exist,
     the PR gate has no parity coverage; either hybrid must gate PR
     (re-introducing the CI-skip paradox from B2) or PR gate loses
     parity entirely and only unit tests protect the merge.

   > **Recommendation (Claude):** Three options, ordered by preference:
   >
   > **Option 7-A — Synthetic-bars canaries.** Canaries stop using
   > *TV-recorded* equity/stats. Instead, canary fixtures use the
   > existing deterministic 500-bar synthetic walk (`_deterministic_500_bars`
   > in `conftest.py`, seed 20260711), run through **our runtime**, and
   > record the runtime's OWN trades/equity/stats as the "golden"
   > snapshot. Parity is then a **round-trip stability** check (does
   > this runtime + these bars produce the same output today as when
   > the snapshot was taken?) — NOT a cross-engine parity check against
   > TV. This detects engine regressions but does NOT catch cases where
   > our engine diverges from TV. Cheap, no external deps, gates PR
   > cleanly. Best fit for the Essential-tier constraint.
   >
   > **Option 7-B — Drop canaries; accept the A1 gap.** Accept that
   > equity/max_drawdown parity vs TV is out of reach with this TV plan.
   > PR gate becomes: unit tests + hybrid suite skipped-when-unconfigured.
   > On nightly runner (with FMP+MySQL), hybrid runs and covers
   > trades-parity. Cheapest but explicitly loses the intrabar-drawdown
   > coverage A1 flagged as the missing 20%.
   >
   > **Option 7-C — Ask a Premium-tier collaborator to seed canaries once.**
   > A one-time export from someone with TV Premium produces the
   > equity.csv + stats.csv for 2-3 chosen fixtures; those become
   > checked-in reference data and never need re-export unless the
   > `.pine` source changes. Delegates the constraint rather than
   > engineering around it. Realistic only if such a collaborator exists.
   >
   > **My recommendation: 7-A.** It preserves a PR-gating deterministic
   > canary (which was the load-bearing property of D1.6), doesn't
   > require anyone to have a paid TV account, and the "round-trip
   > stability" check is a real regression guard even if it doesn't
   > catch TV-parity drift. Combine with the hybrid suite's TV-trades
   > cross-check running nightly, and the combined coverage is:
   > (engine-vs-itself) on PR + (engine-vs-TV) on nightly.

   [PR] **7-C, non-blocking.** @prashant will find a Premium-tier
   collaborator to seed the canary CSVs. Until then, canaries are a
   **deferred additive layer**, not a prerequisite. Ship the design in
   two waves:
   - **Wave 1 (unblocked, ship now):** trades-only hybrid suite,
     nightly. All 5 pilots migrate to hybrid mode with Essential-tier
     trades + fmp_cached bars. Spec promotes with Q7 open but tracked.
   - **Wave 2 (when Premium CSVs arrive):** drop `.equity.csv` +
     `.stats.csv` into 2-3 chosen fixture dirs, flip
     `canary_mode: true` in their provenance.json. D1.7's mode-dependent
     completeness rule picks them up automatically — zero rework.
   - **Risk accepted during the wait:** A1's max-drawdown / intrabar-
     equity gap ships uncovered on PR AND nightly. Document explicitly
     in the spec as an eyes-open call, not a silent hole.

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

---

## Reviewer feedback — Claude (2026-07-20), trading + software-eng lens

**Verdict:** The direction is sound and worth pursuing — cheaper fixtures
mean more coverage per human-hour, which is the right lever. But two of
the load-bearing claims are **overstated**, and one open question (#2,
adjustment divergence) is not a side-issue — it is the make-or-break risk
that should gate the whole design. Below: correctness concerns first
(they change the design), then feasibility, then concrete recommendations.

### A. Trading-correctness concerns

**A1 — "trades match ⟹ equity matches ⟹ stats match" is only ~80%
true, and the missing 20% is exactly max-drawdown.**
Closed-trade equity is a deterministic function of trades + initial
capital. But TV's **max drawdown**, **run-up**, and the whole
intra-trade equity path are computed on the *mark-to-market* equity
curve, which includes **open-position unrealized P&L bar-by-bar** — not
just realized equity at trade close. Two engines can produce identical
closed-trade lists and still report different `max_drawdown` because one
marks the open position intrabar and the other doesn't (and TV's
intrabar model — `high` first vs `low` first — is itself a convention).
The doc even lists `runup` / `drawdown` (MFE/MAE) as free columns from
TV — those are *intrabar excursion* metrics that **cannot** be
reconstructed from entry/exit dates+prices alone; they require the bars
*and* an identical intrabar traversal model. So "assert trades match and
everything downstream follows" is false precisely for the KPIs most
likely to harbor bugs. This strengthens, not weakens, the case for
keeping equity/stats canaries — see rec R2.

**A2 — Position sizing is path-dependent, so a 1-cent price tolerance
can silently cascade into a different trade *set*.**
`strategy.entry` with default/percent-of-equity sizing computes quantity
from equity *at entry time*. If an early fill differs by a cent, the
share count differs, which changes realized P&L, which changes equity,
which changes the next trade's size — and eventually whether a later
signal even fires the same way. "Wider tolerance on price columns" (the
proposed mitigation for A3) treats the symptom and can **mask** a real
compounding divergence. Per-row numeric tolerance is fine for the last
mile, but the **trade count and ordering must be an exact, zero-tolerance
structural assertion** — that's the real regression detector.

**A3 — Adjustment divergence (open Q#2) is the actual blocker, and the
proposed pilot window is the worst possible choice.**
TV builds its own continuously-adjusted series; FMP builds its own. On a
**1981→2026 AAPL** window spanning five splits, these two series will
disagree — and not just at the pennies level. RSI is computed on the
adjusted close; a different adjusted series shifts *which bar* crosses 30
or 70, which changes the *set* of trades, not merely their prices. When
the trade count differs, no price tolerance saves you — parity fails
structurally and the fixture is unusable. **A $0.01 absolute tolerance
across a series that ranges from ~$0.10 to ~$250 is not viable; it must
be relative.** But even a relative tolerance can't rescue a
crossover-timing shift. This means the pilot should be a **short, recent,
post-last-split window** (e.g. AAPL 2021–2026, or better a liquid symbol
with *no* split in-window) to de-risk the design *before* committing to
it. Piloting on 45-year AAPL would likely produce a red suite and a wrong
conclusion that "the hybrid idea doesn't work," when really only the
data window was pathological.

**A4 — Fill/commission/slippage/`process_orders_on_close` model must be
pinned or trades won't match for reasons unrelated to your engine.**
TV's defaults (commission=0, slippage=0, fills at bar close vs intrabar,
`calc_on_every_tick`, pyramiding) directly move entry/exit prices and
timing. None of these are captured in the draft `provenance.json`. If the
Pine runtime's execution model doesn't match the TV settings the fixture
was captured under, trades diverge and you'll burn hours chasing a
"bug" that's a config mismatch. **Add a `strategy_settings` block to
provenance** recording exactly the TV Strategy Tester properties used.

**A5 — Bar-timestamp / session / timezone alignment.**
TV daily bars key off the exchange session in exchange-local time; FMP
`date` fields may land a day off at boundaries or around DST. An
off-by-one bar shifts every signal. Worth an explicit normalization
step + assertion in the harness (align on trading-date, not raw string),
not left implicit.

### B. Software-engineering / feasibility concerns

**B1 — The content-hash gate over floating-point bars is fragile.**
SHA-256 over a serialized DataFrame is sensitive to float repr, column
order, NaN rendering, and timezone formatting — you'll get spurious
"fmp_cached drift" failures from cosmetic changes (pandas/pyarrow
upgrades) that didn't change a single price. Define a **canonical
serialization** explicitly: sort by date, fixed column order, round OHLCV
to a stated precision (e.g. 6 dp), render dates as UTC ISO, hash *that*.
Don't hash the raw provider frame.

**B2 — The CI-skip paradox undercuts the headline win.**
Win #4 says "CI runs the strategy end-to-end." But the mitigation for the
fmp_cached dependency is `pytest.importorskip` → on PR CI (no MySQL, no
FMP key) the hybrid tests **skip**. So the strongest end-to-end coverage
runs only locally / nightly, exactly *not* on the PR gate. That's a
legitimate design (many repos gate on the cheap deterministic suite and
run the heavy one nightly), but the doc should state it honestly rather
than list "CI runs end-to-end" as a win. The 4-CSV canary remains the
only thing actually gating merges.

**B3 — Recommendation B ("one suite, mode flag") is more than an
`extend` — it's a rewrite of the completeness rule.**
The current `_discover_strategy_triples` treats a fixture as *incomplete
and skips it* unless `pine + equity.csv + trades.csv + stats.csv` all
exist ([conftest.py](../../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/conftest.py)).
A hybrid fixture deliberately omits equity/stats, so **under today's
walker every hybrid fixture would be silently skipped as "incomplete."**
Option B therefore requires making completeness *mode-dependent*
(provenance.json present ⟹ hybrid completeness = pine + trades +
provenance; absent ⟹ legacy completeness = the current four). That's
fine, but it's a real change to the loudest safety property in the
harness — call it out, and keep the "loud skip" behavior for genuinely
half-authored dirs in *both* modes.

**B4 — provenance.json nits.**
- Record the `fmp_cached` package version and the provider's actual
  parameter *name/value* enumeration — verify `adjustment: "splits_only"`
  is a value the provider accepts (the platform typically uses
  `adjustment` ∈ {`splits_only`, `unadjusted`, …}; confirm before
  baking the string into a schema).
- `captured_by: "prashant@masterswork"` puts an email in-repo forever —
  fine if intended, but consider a handle instead of an address.
- Add `strategy_settings` (per A4) and `bars_timezone` / `session`
  (per A5).

**B5 — Diagnostic signal is muddier than the 4-CSV design, not just
"weaker."** With recorded bars, a red test means *engine* bug (bars are
frozen). With hybrid, a red test conflates *engine* bug **and**
*data/adjustment* divergence — two very different fixes. The content
hash catches *drift over time*, but it does **not** tell you whether the
FMP bars ever matched the bars TV actually computed on. So first-capture
correctness still rests on a human eyeballing that trades line up. Worth
stating that the hybrid trades speed at the cost of a noisier failure
diagnosis.

### C. Recommendations (concrete)

- **R1 — Re-pick the pilot window: start from 2025-01-01 only.**
  Don't validate the design on 1981–2026 AAPL. Constrain the capture to
  **`start_date = 2025-01-01` → present** (~18 months of daily bars).
  Rationale: AAPL's last split was 2020-08 (4:1), so a window opening
  2025-01-01 sits entirely *after* every split in AAPL's history —
  TV's and FMP's adjusted series should be congruent to the cent because
  there is no split-adjustment math to disagree on within the window,
  and dividend adjustment over ~18 months is small and often
  configurable off. This maximizes the chance that trade *counts* match
  exactly on the first capture, which is the only way to know whether
  the engine (not the data) is what the suite is testing. Expand the
  window only *after* a short recent window passes clean. This single
  change most de-risks the whole proposal. (Answers open Q#2's real
  form: the tolerance question is secondary to the *window-selection*
  question — a post-last-split window largely dissolves Q#2.)
  - Set `provenance.json.bars_source.start_date` and
    `trades_source.start_date` to `"2025-01-01"` for the pilot; record
    the exact `end_date` used at capture so the window is reproducible.
  - Caveat: an 18-month daily window on a mean-reverting RSI(14) 30/70
    strategy may produce only a handful of round-trips — enough to
    validate the *plumbing*, but pair it with at least one
    higher-frequency or wider (still post-2020-08) window before
    trusting the suite's statistical coverage.
- **R2 — Keep more than one canary.** A1 shows equity/drawdown is
  exactly the silently-rotting surface. One canary out of 20 is too
  thin. Suggest ~20–25% of fixtures retain full 4-CSV parity, chosen to
  cover distinct KPI surfaces (a drawdown-heavy strategy, a
  short-selling strategy, a pyramiding strategy).
- **R3 — Split the parity assertion into two tiers.** (1) *Structural*:
  trade count + ordering + direction — **exact, zero tolerance, hard
  fail.** (2) *Numeric*: per-row prices/PnL — **relative tolerance**,
  loud warning on breach. Never let a numeric tolerance paper over a
  structural mismatch (A2/A3).
- **R4 — Pin the execution model** in provenance (A4). Without this the
  suite is not reproducible in principle.
- **R5 — Canonicalize before hashing** (B1). Specify the exact
  serialization in the design spec.
- **R6 — State the CI-skip reality** (B2) as a *loss*, and decide
  deliberately: nightly-only for hybrid, PR-gate for the 4-CSV canaries.
  Recommend that split.
- **R7 — Reverse-verify the pilot** (already in the doc's verification
  section — good; keep it). Additionally verify the *negative*: perturb
  the adjustment (feed unadjusted bars) and confirm the structural
  assertion goes red. That proves the suite actually detects the A3
  failure mode rather than tolerating it.

### D. On the six open questions

- **Q1 (Free-tier List of Trades):** empirical, Prashant-answerable —
  agree. Note that even if free-tier exports trades, the *adjustment*
  and *settings* it used still need capturing (A4/B4).
- **Q2:** reframe from "how wide a tolerance" to "**which
  symbol/window keeps TV and FMP adjustment congruent**" — tolerance is
  downstream of that. Relative, not absolute, regardless.
- **Q3 (replace vs parallel):** agree with *parallel*, but bump the
  canary count above 1 (R2).
- **Q4 (A vs B):** B is fine *if* B3's completeness rewrite is done
  properly. If time-boxed, A is lower-risk because it doesn't touch the
  existing walker's safety property.
- **Q5 (CI gate):** agree hybrid = every-PR-but-skips; be explicit that
  "skips" means "provides zero PR-gate coverage where unconfigured"
  (B2).
- **Q6 (TV column renames):** correctly noted as pre-existing, not new.

**Bottom line:** feasible and worth a pilot, but (1) fix the pilot
window before anything else, (2) don't trust "trades ⟹ everything," keep
real equity/stats canaries, (3) make trade-count a hard structural gate,
and (4) pin the execution model + canonicalize the hash. Do those and
the design earns its keep; skip them and the first red suite will look
like the idea failing when it's really the data window and a missing
settings block.

---

## Response to reviewer feedback — plan for design revisions (2026-07-20, later same day)

The reviewer feedback (§ above) is accepted. It changes the design in
material ways — not "these are nice tweaks," but "the pilot window is
wrong, the parity model is wrong, the CI-gate story is misstated, and
the importer is missing critical context." Below is the plan to fold
each recommendation into the design. **No code shipped in this
brainstorm iteration** — this is still the proposal, revised.

### D1. Design deltas (things that CHANGE from the initial draft)

**D1.1 — Pilot window: 2025-01-01 → present, single symbol, no in-window split.**
Adopt R1 as an unconditional prerequisite of any implementation session.
The 1981–2026 AAPL window sitting on the in-flight `rsi_reversal`
fixture is the wrong choice for validating the design (five splits
in-window guarantee TV vs FMP adjusted-series divergence). Revised
pilot: **AAPL 2025-01-01 → capture date, 1D bars**. Also acceptable:
any liquid symbol with no split in the window (SPY, MSFT post-2020).
If the recent-window pilot passes clean, expand cautiously; if it
doesn't, that's a real signal about the hybrid model itself, not the
data.

**D1.2 — Parity assertion split into two tiers (R3).** Replace the
single "trades match with $0.01 tolerance" assertion (which A2/A3 shows
can silently paper over structural bugs) with:

  1. **Structural assertion (zero tolerance, hard fail):** identical
     trade count, identical `(date_entry, date_exit, type)` tuples in
     order. A mismatch here means the trade *set* diverged, which is
     always a real signal and is never resolvable by wider tolerance.
  2. **Numeric assertion (relative tolerance, per-column, loud
     warning on breach):** prices, PnL, run-up, drawdown. Tolerance
     applied ONLY once structural has passed. Breaches log a warning
     naming the column + delta before failing.

**D1.3 — Canary count bumped from 1 to ~20-25% of fixtures (R2).**
Reviewer's A1 is correct: trades match ≠ equity/max_drawdown match,
because intra-trade unrealized-P&L path and TV's intrabar traversal
model both affect drawdown/runup and neither is reconstructable from
`(entry_date, entry_price, exit_date, exit_price)`. **Retain at least 1
canary per KPI-surface class:** one drawdown-heavy (choose based on
which existing pilot exercises drawdown most — likely
`breakout_atr_trail`), one short-selling (whichever pilot has short
entries), one pyramiding if any. `rsi_reversal` becomes one of the
canaries. Target: 2-3 full-parity canaries, remaining N-3 fixtures on
hybrid path. Revisit ratio quarterly.

**D1.4 — Provenance.json schema expanded (A4, A5, B4).** Add:

  - `strategy_settings`: exact TV Strategy Tester properties in use
    when the trades were captured. Fields: `initial_capital`,
    `commission_type` (Percent / Cash / PerContract), `commission_value`,
    `slippage_ticks`, `pyramiding_max_orders`, `process_orders_on_close`
    (bool), `calc_on_every_tick` (bool), `default_qty_type`,
    `default_qty_value`. Without this, trade-price divergence for
    reasons unrelated to the runtime is indistinguishable from a
    runtime bug.
  - `bars_source.timezone`: exchange TZ used to align dates. For NYSE
    equities: `America/New_York`. Harness must normalize FMP's UTC
    dates onto exchange sessions before comparing to TV.
  - `bars_source.session`: `regular` vs `extended`. Default `regular`.
  - `fmp_cached_version`: package version at capture time. If a
    future fmp_cached patch changes the row shape (rare but possible),
    provenance flags it.
  - Drop the email address from `captured_by`; use a handle
    (`prashant`, not `prashant@masterswork`). Emails in-repo forever
    are avoidable.

**D1.5 — Canonical bars serialization for hashing (B1).** Never hash a
raw pandas frame. Canonical serialization before SHA-256:
  ```
  1. Sort by `date` ascending.
  2. Fixed column order: date, open, high, low, close, volume.
  3. `date` → UTC ISO 8601 with `T00:00:00+00:00`.
  4. OHLCV → strings, decimals rounded to 6 dp (matches Pine's
     `syminfo.pricescale` precision for equities; fixed for volume as int).
  5. Row-terminator: `\n` (never CRLF).
  6. No trailing newline on the last row.
  Hash: SHA-256 over the resulting bytes.
  ```
  The exact serialization is specified once in the design spec (future
  session) and reused by both the capture tool and the harness.

**D1.6 — CI-gate story stated honestly (B2).** Remove "CI runs the
strategy end-to-end" from the Wins list — it does not, on PR CI
without MySQL+FMP. Rewrite as:
  - **PR gate:** the 4-CSV canaries (2-3 fixtures) always run.
    Deterministic, no external deps. Guarantees a red-check on any
    engine regression a canary can detect.
  - **Nightly (and locally):** the hybrid suite runs when fmp_cached
    is configured. Broader coverage but not merge-blocking.

  This split is a legitimate design (many mature repos do exactly
  this), it just needs to be presented as the tradeoff it is, not as
  a strict win.

**D1.7 — Completeness rule becomes mode-dependent (B3).** The current
`_discover_strategy_triples` treats any dir missing one of `pine +
equity + trades + stats` as incomplete and warns-and-skips. The revised
walker:
  - **Hybrid mode** (provenance.json present): completeness = pine +
    trades + provenance. Missing → warn-and-skip (same loud behavior).
  - **Full-parity mode** (no provenance.json): completeness = the
    current four. Missing → warn-and-skip.
  A dir that has BOTH (canary) satisfies both completeness checks and
  runs both assertions.

  The loud-skip safety property (R7.3 loud empties) is preserved in
  both modes — this is not a weakening, it's a mode selector.

### D2. Data importer / validation tool — what exists, what's needed

The reviewer's ask *"hope you have a data importer tool to convert to
our validation logic for trade data"* has a partial-yes answer:

**Already exists:** [`Tools/pine/reshape_tv_trades.py`](../../../Tools/pine/reshape_tv_trades.py)
(shipped in PR #946). Converts TV Strategy Tester List-of-Trades CSV
into our 1-row-per-round-trip schema. Handles the exit-before-entry
pairing convention, direction detection, 50/50 commission split, dtype
preservation. R7-clean.

**Needed extensions before hybrid mode ships:**

- **D2.1 — Structural validation.** Reshape today accepts any TV CSV
  with the expected columns; add a validation pass that asserts (a)
  every Trade number has exactly 2 legs (entry + exit), (b) directions
  match within a pair, (c) exit_time > entry_time, (d) qty is
  non-negative. Fail loudly on structural anomaly rather than silently
  passing through.

- **D2.2 — Metadata capture.** Extend the CLI to accept optional
  `--symbol`, `--timeframe`, `--start`, `--end`, `--tv-strategy-settings-json`
  and emit them into a companion `<fixture>.trades.meta.json` alongside
  the CSV. That metadata is exactly what feeds provenance.json's
  `trades_source` block (D1.4).

- **D2.3 — Bars fetch + hash tool.** New tool
  `Tools/pine/capture_bars_provenance.py` per the original brainstorm.
  Given `(symbol, start, end, adjustment)`, fetches from fmp_cached,
  canonicalizes per D1.5, hashes, and emits the `bars_source` block of
  provenance.json. Idempotent — running twice on the same window
  produces byte-identical output.

- **D2.4 — Provenance.json validator.** Given a fixture dir, verify
  provenance.json parses, matches schema, references a real
  `.trades.csv` in the same dir, and (if fmp_cached available)
  re-fetches bars and confirms the hash. Fail loudly on any mismatch.
  Standalone tool for pre-PR local verification.

- **D2.5 — Harness-side bars loader for hybrid mode.** New helper in
  `conftest.py` that reads provenance.json, calls fmp_cached, verifies
  the hash, canonicalizes bars, feeds the resulting records to
  `run_byo` — the same seam the deterministic generator uses today.

The five extensions above are the "data importer for our validation
logic" the reviewer asked about. #D2.1 and #D2.2 extend the existing
reshape tool; #D2.3 through #D2.5 are net-new. Each is small (~50-150
LoC) but they compose into the full pipeline: TV export → reshape +
validate + capture-metadata → capture-bars-provenance → harness
consumes both.

### D3. Sequencing (revised from the initial "next steps")

The original brainstorm proposed "answer 6 open questions → promote to
spec → implement." The reviewer's feedback tightens this into a
concrete, verifiable sequence:

1. **This session (docs only, done):** the brainstorm + this response
   land in the repo so the design + feedback are one artifact.
2. **Next session (short, docs only):** promote to
   `docs/superpowers/specs/YYYY-MM-DD-pine-hybrid-fixture-suite-design.md`
   with all 6 open questions answered per the reviewer's
   recommendations (D1.1–D1.7). Include the canonical serialization
   spec (D1.5) and the extended provenance schema (D1.4) as code
   blocks.
3. **Implementation session 1 (SMALL, HIGH-RISK-RESOLVING):** implement
   D2.1 (structural validation on reshape) and D2.3 (capture bars
   tool). Then run the tools against a **2025-01-01 → present AAPL
   pilot**. Verify the reshape's structural checks catch a deliberately
   corrupted TV CSV (R7.7 reverse-verify), and verify the hash is
   stable across two consecutive `capture_bars_provenance` runs.
4. **Implementation session 2 (VALIDATION OF THE HYPOTHESIS):** implement
   D2.5 (harness bars loader), migrate one existing pilot (e.g.
   `sma_crossover`) to hybrid mode with the 2025-01-01 window, and run
   the two-tier assertion (D1.2). If structural passes and numeric
   passes within relative tolerance, the design is validated. If
   structural fails, STOP and investigate — the whole thesis (data
   parity is achievable) is under question.
5. **Implementation session 3 (SCALE):** if session 2 validated,
   migrate the remaining pilots. Retain 2-3 canaries per D1.3.
6. **Implementation session 4 (NEGATIVE TESTS):** perform R7 negative
   verification — feed unadjusted bars into a hybrid fixture, confirm
   the structural assertion goes red. This proves the suite detects
   the A3 failure mode.

Each session ships one PR under the standard Pine merge rule. Session
2 is the go/no-go gate for the whole design.

### D4. What this response explicitly does NOT do

- No code changes. Still a brainstorm iteration.
- No decision on canary count (D1.3 says "2-3"; the exact count and
  which specific fixtures become canaries needs input from @prashant
  based on which pilots exercise which KPI surfaces).
- No commitment to the 2025-01-01 pilot window before @prashant
  confirms — it may make sense to pick a longer post-2020 window if
  the strategy's signal density is too low over 18 months (D1.1
  caveat).
- No spec promotion — that's next session's work.
- No implementation of any of the 5 tool extensions (D2.1-D2.5).

### D5. Success criteria for this feedback response

A next-session author (Claude or human) can:

- Read this response and know what changed in the design.
- Read this response + the reviewer feedback and understand the
  reasoning without re-deriving it.
- Start the spec-promotion session with all six open questions answered
  by the D1 deltas — no re-litigation needed.
- Start implementation session 1 with a concrete tool contract for
  D2.1–D2.5.

---

## Meta-note on why this response is inline in the brainstorm

The reviewer feedback was authored directly into this file (§Reviewer
feedback above), and this response is authored directly after it. The
alternative — respond in a PR review thread — would fragment the
design conversation across two systems. Keeping brainstorm + review +
response in one artifact means future sessions grep the design and see
the full history, not just the initial draft.

