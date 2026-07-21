# Design spec: Hybrid Pine fixture suite (TV trades + fmp_cached bars)

| Field | Value |
|---|---|
| **Status** | Approved design — ready to implement |
| **Program** | Pine Script Support (GH Project #5) |
| **Tracking issue** | [#957](https://github.com/prajoria/OpenBB/issues/957) |
| **Supersedes** | The "brainstorm / proposal" status of [`docs/superpowers/brainstorms/2026-07-20-pine-hybrid-fixture-suite.md`](../brainstorms/2026-07-20-pine-hybrid-fixture-suite.md). The brainstorm remains checked-in as historical context; this spec is the go-forward source of truth. |
| **Related issues** | #578 (5 pilot fixtures), #584 (request.security corpus), #586 (v5 roundtrip), #951 (D2.1+D2.2 reshape validation) |
| **Related PRs** | #946 (fixture prep guide, docs), #952 (D2.1+D2.2 shipped), this PR stacks on #952 |
| **Author** | Claude (2026-07-20 session, from @prashant Q1–Q7 answers) |
| **HARD CONSTRAINT** | @prashant's TradingView plan is **Essential** — trades exportable, bars/equity/stats not. Wave 1 designs entirely around this. Wave 2 lifts the constraint via a Premium-tier collaborator (Q7, non-blocking). |

---

## 1. Goals and non-goals

### Goals

- **G1** — Reduce per-fixture human capture cost from 4 CSVs to 1 (trades
  only), enabling 20+ fixtures for the same time budget that produced 5.
- **G2** — Preserve reproducibility: every fixture's data is byte-stable
  across machines and across time, enforced by a content-hash gate on
  bars.
- **G3** — Catch Pine runtime regressions on the load-bearing signal
  (the closed-trade list) even in the absence of TV-parity coverage of
  equity/stats.
- **G4** — Ship in two waves so Wave 1 is unblocked by the TV Essential
  constraint; Wave 2 slots additive canary coverage in with zero
  harness rework.
- **G5** — Make failure modes diagnosable: a red test names *what*
  diverged (trade set, price row, bars drift, provenance mismatch),
  never just "test failed."

### Non-goals

- **NG1** — Tick-level intrabar simulation. TV's intrabar traversal
  model (high-first / low-first) is a convention, not a specification;
  matching it precisely is out of scope.
- **NG2** — Cross-broker slippage/commission modelling. `provenance.json`
  pins the settings that were captured; we do not attempt to model
  arbitrary broker execution.
- **NG3** — Replacing the deterministic 500-bar smoke suite. It still
  runs on PR CI as the cheapest safety net. Hybrid coverage is
  additive, not replacing.
- **NG4** — Auto-refreshing fixtures when `fmp_cached` updates. Drift
  detection is machine-enforced; drift *resolution* is a human decision
  per fixture (accept new hash + verify trades still match, or revert).

---

## 2. Architecture

### 2.1 Per-fixture directory layout

```
openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/
└── <fixture_name>/
    ├── <fixture_name>.pine                 # Pine v5 source (unchanged from today)
    ├── <fixture_name>.trades.csv           # TV-sourced, reshaped via reshape_tv_trades.py
    ├── <fixture_name>.trades.meta.json     # Emitted by reshape (D2.2, already shipped)
    ├── provenance.json                     # NEW — pins bars source, hash, settings
    ├── HOW_TO_EXPORT_FROM_TV.md            # Existing per-fixture stub
    │
    ├── <fixture_name>.equity.csv           # Wave 2 only (canary mode)
    └── <fixture_name>.stats.csv            # Wave 2 only (canary mode)
```

`provenance.json` is the mode selector. Its presence signals **hybrid
mode**; its absence signals **legacy full-parity mode**. Both may
coexist in a canary fixture (both files present).

### 2.2 What is compared, what is discarded

| Artifact | Source | Fixture file? | Compared to? |
|---|---|---|---|
| `.pine` | Repo | ✅ yes | — (input) |
| Bars | fmp_cached at test time | ❌ no (regenerated) | Hash-verified vs `provenance.bars_source.bars_sha256` |
| Trades (recorded) | TV Strategy Tester | ✅ `.trades.csv` | Compared to runtime output |
| Trades (runtime output) | Our runtime | ❌ no (generated) | ← **the parity assertion** |
| Equity (Wave 2 canary only) | TV | ✅ `.equity.csv` (canary) | Compared to runtime equity |
| Stats (Wave 2 canary only) | TV | ✅ `.stats.csv` (canary) | Compared to runtime stats |

Wave 1 asserts only trades-parity. Wave 2 canaries additionally assert
equity/stats parity, covering the intrabar-drawdown surface (A1) that
trades-only parity cannot reach.

### 2.3 Mode-dependent completeness rule (D1.7)

`conftest.py::_discover_strategy_triples` today treats any fixture dir
lacking `pine + equity + trades + stats` as incomplete and
warn-and-skips. The revised walker classifies each dir by mode:

- **Hybrid mode** — `provenance.json` present. Completeness =
  `pine + trades + provenance`. Any missing → warn-and-skip (loud).
- **Full-parity mode** — no `provenance.json`. Completeness = the
  current four (`pine + equity + trades + stats`). Any missing →
  warn-and-skip (loud).
- **Canary mode** — `provenance.json` present AND `equity.csv +
  stats.csv` present. Satisfies both completeness checks and runs both
  assertions.

The loud-skip property (CLAUDE.md R7.3 loud empties) is preserved in
all three modes. This is a mode selector, not a safety weakening.

---

## 3. Rollout in two waves

### 3.1 Wave 1 — ship now (unblocked by TV Essential)

**What ships:**

- All 5 existing pilots migrate to hybrid mode:
  `rsi_reversal`, `sma_crossover`, `bb_squeeze`, `breakout_atr_trail`,
  `macd_histogram_signal`.
- Each fixture dir gets `provenance.json` + a fresh `.trades.csv`
  captured against the **2025-01-01 → capture-date** window on a
  post-last-split symbol (default: `NASDAQ:AAPL`; `SPY` and `MSFT`
  post-2020 are acceptable alternates).
- Legacy `.equity.csv` / `.stats.csv` / `.bars.csv` files (if present)
  are removed from the pilot dirs — the hybrid suite regenerates bars
  from fmp_cached and never records equity/stats.

**Coverage delivered:**

- Trade-parity assertion vs TV, on every fixture, on **nightly** runs
  (where `fmp_cached` is configured).
- Deterministic 500-bar smoke suite continues to run on **every PR**
  as it does today.
- Unit tests for the runtime run on every PR (unchanged).

**Coverage NOT delivered (accepted gap):**

- Intrabar-drawdown / max-drawdown / MFE / MAE parity vs TV. This is
  the "missing 20%" A1 flagged. Documented explicitly as an eyes-open
  risk. Mitigated in Wave 2.

### 3.2 Wave 2 — canaries (blocked on Premium collaborator)

**What ships:**

- 2–3 fixtures selected by @prashant based on which KPI surfaces they
  exercise (one drawdown-heavy, one short-selling, ideally one
  pyramiding).
- A Premium-tier collaborator exports `.equity.csv` + `.stats.csv` from
  TV Strategy Tester for each selected fixture, using the exact
  `strategy_settings` recorded in that fixture's `provenance.json`.
- Files drop into the fixture dirs. The canary-mode branch of the
  discovery walker (§2.3) picks them up automatically. `canary_mode:
  true` is flipped in each selected fixture's `provenance.json`.

**Coverage delivered on top of Wave 1:**

- Equity-curve parity vs TV (adds intrabar-drawdown coverage).
- Stats/KPI parity vs TV (adds max_drawdown, run_up, profit_factor
  precision checks).

**Rework cost:** zero harness code changes. The mode-dependent
completeness rule already handles the transition. Only per-fixture
`canary_mode` flag flips.

### 3.3 Wave-independent PR-gate story

Until Wave 2 ships, the PR gate consists of:

- **Deterministic 500-bar smoke suite** — always runs.
- **Runtime unit tests** — always run.
- **Hybrid trades-parity suite** — runs via `pytest.importorskip` and
  **skips** on PR CI (no MySQL, no FMP key). Not a merge gate.

This is honest about the coverage gap: PR CI cannot verify
TV-parity; only nightly can. Once Wave 2 canaries land, PR CI additionally
runs the (deterministic, no-external-deps) canary equity/stats parity
against the checked-in reference CSVs — that closes the loop.

---

## 4. `provenance.json` schema (D1.4)

```json
{
  "$schema_version": 1,
  "fixture_name": "rsi_reversal",
  "canary_mode": false,
  "captured_at": "2026-07-20",
  "captured_by": "prashant",

  "trades_source": {
    "tool": "TradingView Strategy Tester",
    "tv_plan_at_capture": "Essential",
    "symbol": "NASDAQ:AAPL",
    "timeframe": "1D",
    "start_date": "2025-01-01",
    "end_date": "2026-07-20",
    "reshape_tool_version": "1.1.0",
    "row_count": 37
  },

  "bars_source": {
    "provider": "fmp_cached",
    "fmp_cached_version": "0.3.4",
    "symbol": "AAPL",
    "start_date": "2025-01-01",
    "end_date": "2026-07-20",
    "adjustment": "splits_only",
    "timezone": "America/New_York",
    "session": "regular",
    "bars_sha256": "3f2a...b7e1",
    "bars_row_count": 396
  },

  "strategy_settings": {
    "initial_capital": 1000000,
    "commission_type": "Percent",
    "commission_value": 0.0,
    "slippage_ticks": 0,
    "pyramiding_max_orders": 1,
    "process_orders_on_close": false,
    "calc_on_every_tick": false,
    "default_qty_type": "fixed",
    "default_qty_value": 1
  },

  "parity_assertions": {
    "structural": {
      "gate": "hard_fail",
      "tolerance": "zero",
      "keys": ["trade_num", "date_entry", "date_exit", "type"]
    },
    "numeric": {
      "gate": "warn_and_fail",
      "tolerance_relative": 1.0e-3,
      "warn_threshold_relative": 5.0e-4,
      "columns": [
        "price_entry", "price_exit",
        "profit", "profit_percent",
        "runup", "drawdown", "commission"
      ]
    },
    "equity": "not compared (Wave 1)",
    "stats": "not compared (Wave 1)"
  }
}
```

### 4.1 Field notes

- **`$schema_version`** — bumped on breaking changes. Consumers
  reject unknown-schema files loudly rather than silently skipping.
- **`captured_by`** — a **handle**, not an email address. Emails in
  repo history are avoidable; a handle serves the same audit purpose.
- **`tv_plan_at_capture`** — records the TV subscription tier used.
  Diagnostic value when reproducibility questions arise.
- **`strategy_settings`** — mirrors TV Strategy Tester → Properties.
  Without these, price/timing divergence for reasons unrelated to the
  runtime is indistinguishable from a runtime bug (A4).
- **`bars_source.timezone`** — the exchange session's TZ used to align
  dates. Harness must normalize fmp_cached's UTC dates onto this TZ
  before comparing to TV. NYSE equities: `America/New_York`.
- **`bars_source.fmp_cached_version`** — pins the provider package
  version. A future patch changing row shape is caught at hash-check
  time rather than silently mis-comparing.
- **`parity_assertions.structural`** — enforces R3 (D1.2): zero-
  tolerance structural gate. Trade set must be identical.
- **`parity_assertions.numeric`** — relative tolerance only. Absolute
  tolerance is meaningless when prices span $0.10 → $250.

---

## 5. Canonical bars serialization for hashing (D1.5)

Never hash a raw pandas DataFrame. The `bars_sha256` in
`provenance.json.bars_source` is computed over the following canonical
form:

```
1. Sort rows by `date` ascending.
2. Fixed column order: [date, open, high, low, close, volume].
3. `date` → UTC ISO 8601 with `T00:00:00+00:00`.
4. OHLC → strings, decimals rounded to 6 dp (matches Pine's
   `syminfo.pricescale` precision for equities).
5. `volume` → string, formatted as int (no decimals, no thousands sep).
6. Row terminator: `\n` (Unix line ending, never CRLF).
7. No trailing newline on the last row.
8. Hash: SHA-256 over the resulting UTF-8 bytes.
```

Rationale: SHA-256 over a raw provider frame is sensitive to float
repr, column order, NaN rendering, and TZ formatting. That produces
spurious drift failures from cosmetic changes (pandas/pyarrow
upgrades) that didn't touch a single price. Canonical serialization
eliminates every such source. The exact byte-sequence is testable:
running the tool twice on the same window MUST produce byte-identical
hashes.

`Tools/pine/capture_bars_provenance.py` (D2.3) and the harness bars
loader (D2.5) MUST share the exact same serialization code — extracted
into `openbb_pine.testing.canonical_bars` so drift between capture-time
and test-time is impossible.

---

## 6. Two-tier parity assertion (D1.2)

Every hybrid-mode fixture runs both tiers, in order:

### 6.1 Tier 1 — structural (zero tolerance, hard fail)

- Trade count must match exactly.
- Trades sorted by `trade_num`, then compared element-wise on
  `(date_entry, date_exit, type)`. Any mismatch fails the test with a
  diff summary naming the first divergent trade.
- **No numeric tolerance applies at this tier.** A different trade set
  is always a real signal (A2/A3): sizing is path-dependent, so a
  1-cent price drift can silently cascade into a whole different trade
  chain. Never let numeric tolerance paper over a structural mismatch.

### 6.2 Tier 2 — numeric (relative tolerance, warn + fail)

Only runs if tier 1 passed. Per-column, per-row assertion:

```
delta = abs(runtime_value - fixture_value)
scale = max(abs(runtime_value), abs(fixture_value), 1.0)  # avoid /0
if delta / scale > tolerance_relative:
    fail with column + trade_num + delta
elif delta / scale > warn_threshold_relative:
    log.warning with column + trade_num + delta (test still passes)
```

Columns covered per §4 `parity_assertions.numeric.columns`.

### 6.3 Wave 2 (canary) additional assertions

- Equity curve: per-row structural (date alignment) + numeric (relative
  tolerance on equity value).
- Stats: per-metric numeric (relative tolerance on each KPI).

Same two-tier discipline: structural alignment zero-tolerance,
values relative.

---

## 7. Tool contracts (D2.1–D2.5)

| ID | Tool | Status | Location |
|---|---|---|---|
| **D2.1** | Reshape structural validation | ✅ shipped in PR #952 | `Tools/pine/reshape_tv_trades.py` |
| **D2.2** | Reshape metadata capture | ✅ shipped in PR #952 | `Tools/pine/reshape_tv_trades.py` |
| **D2.3** | `capture_bars_provenance.py` | 🟡 next implementation session | `Tools/pine/capture_bars_provenance.py` |
| **D2.4** | Provenance validator | 🟡 packaged with D2.5 | `Tools/pine/validate_provenance.py` |
| **D2.5** | Harness hybrid-mode bars loader | 🟡 next implementation session | `openbb_platform/extensions/pine/openbb_pine/testing/canonical_bars.py` + `.../conformance_strategy/conftest.py` |

### 7.1 D2.3 contract — `capture_bars_provenance.py`

```
Usage:
    capture_bars_provenance.py <fixture_dir>
        --symbol NASDAQ:AAPL
        --start 2025-01-01
        --end 2026-07-20
        --timeframe 1D
        --adjustment splits_only
        --timezone America/New_York
        --session regular
        [--tv-strategy-settings-json path/to/settings.json]

Behavior:
    1. Fetch bars from fmp_cached with the given (symbol, start, end,
       adjustment).
    2. Canonicalize per §5.
    3. Compute SHA-256.
    4. Emit / update <fixture_dir>/provenance.json — merge (not
       replace) with any existing file; refuse to overwrite unless
       --force.
    5. Print the hash + row count to stdout.
    6. Exit code 0 on success, 1 on fetch failure, 2 on schema
       validation failure.

Idempotency:
    Running twice on the same window MUST produce byte-identical
    provenance.json.
```

### 7.2 D2.5 contract — harness hybrid-mode bars loader

```
Location: openbb_pine.testing.canonical_bars
Public API:
    canonicalize_bars(records: list[dict]) -> bytes
    sha256_bars(records: list[dict]) -> str

Location: openbb_pine.tests.conformance_strategy.conftest
Extension:
    _discover_strategy_triples() classifies each fixture per §2.3.
    For hybrid-mode dirs:
        1. pytest.importorskip("openbb_fmp_cached")
        2. Read provenance.json.
        3. Fetch bars via openbb_fmp_cached matching every provenance
           parameter exactly.
        4. Canonicalize + hash + assert hash == provenance.bars_sha256.
           On mismatch: FAIL with clear "fmp_cached drift" message
           naming symbol / window / expected-vs-actual hash.
        5. Feed canonicalized bars to run_byo(strategy=<pine>,
           bars=<canonical>, settings=<provenance.strategy_settings>).
        6. Compare runtime trades to <fixture>.trades.csv per §6.
```

### 7.3 D2.4 contract — provenance validator

Standalone CLI + importable function. Used both as a pre-PR local check
and inside D2.5's harness. Validates:

- `provenance.json` parses and matches schema (Pydantic model).
- Referenced `<fixture>.trades.csv` exists.
- If `fmp_cached` is available: re-fetches bars, re-hashes, asserts
  match.
- Fails loudly on any mismatch with a diff summary.

---

## 8. Sequencing (D3)

Each session ships one PR under the standard Pine merge rule.

### 8.1 Sessions

1. **This session (docs-only, this spec):** the design lands in the
   repo. Docs-only PR stacked on #952. Zero code, zero risk. ✅
2. **Implementation session 1 (small, high-risk-resolving):** implement
   **D2.3** + the shared `canonical_bars` module. Verify:
   - Two consecutive `capture_bars_provenance` runs on the same window
     produce byte-identical output (idempotency).
   - The 2025-01-01 → present AAPL pilot fetches cleanly from
     fmp_cached.
   - Reverse-verification (R7.7): deliberately perturb the canonical
     serialization, confirm hash changes; restore, confirm hash
     restored.
3. **Implementation session 2 (VALIDATION OF THE HYPOTHESIS):** implement
   **D2.4 + D2.5**, migrate **one** existing pilot (recommend
   `sma_crossover` — simplest signal, easiest to reason about) to
   hybrid mode with the 2025-01-01 window. Run the two-tier assertion.
   - **Go-signal:** structural passes + numeric within relative
     tolerance. The design is validated.
   - **No-go:** structural fails on first migration. STOP and
     investigate; the whole thesis (data parity is achievable with
     this window + this pipeline) is under question. Do not scale.
4. **Implementation session 3 (SCALE):** if session 2 validated,
   migrate remaining 4 pilots. Update the fixture prep guide to
   present hybrid workflow as the default; demote legacy 4-CSV workflow
   to a canary-only appendix.
5. **Implementation session 4 (NEGATIVE TESTS + NIGHTLY WIRING):**
   perform R7 negative verification — feed unadjusted bars into a
   hybrid fixture, confirm the structural assertion goes red. Wire the
   hybrid suite into a nightly GH Actions job (separate workflow file,
   fmp_cached configured via secrets).
6. **Wave 2 (blocked on Premium collaborator):** onboard 2–3 canaries
   when the Premium CSVs arrive. Flip `canary_mode: true` per fixture.

### 8.2 Success gate

Sessions 1–3 must pass before Wave 2 is considered viable. If session 2
red-suite reveals the hybrid model cannot achieve trades-parity on a
recent-window pilot, the whole spec is re-opened rather than papered
over.

---

## 9. Success criteria (D5)

A next-session author (Claude or human) can:

- Read §2–§4 and understand the fixture layout + mode selector.
- Read §5 and reproduce the canonical serialization byte-for-byte in
  any language.
- Read §6 and implement the two-tier assertion without further
  design questions.
- Read §7 and start Implementation Session 1 without ambiguity about
  the D2.3 CLI shape or the D2.5 harness integration point.
- Read §8 and know the exact go/no-go gate for scaling.

If any of these fails, the spec is incomplete and needs a follow-up
before implementation starts.

---

## 10. Open items (post-approval)

- **Q7 Wave 2 collaborator hunt:** @prashant to identify a Premium-tier
  contributor willing to run TV Strategy Tester exports for 2–3
  chosen fixtures. Non-blocking for Wave 1.
- **Fixture selection for canaries:** decide which 2–3 pilots become
  canaries once Premium CSVs are on the table. Criteria: distinct
  KPI surfaces (drawdown-heavy, short-selling, pyramiding). Deferred
  until Wave 2 is unblocked.
- **Nightly GH Actions workflow:** the exact YAML for the nightly
  hybrid job lands in Implementation Session 4, not here.

---

## 11. Anti-goals (things this spec explicitly rejects)

- **Absolute price tolerance.** Every tolerance is relative. See §6.2.
- **Silent skips.** Every mode's completeness check warn-and-skips
  loudly. R7.3 discipline preserved everywhere.
- **Numeric tolerance masking structural mismatch.** Tier 1 is
  zero-tolerance. Tier 2 only runs if tier 1 passed. See §6.
- **Hash over raw pandas frames.** Canonical serialization only. See §5.
- **Emails in repo history.** `captured_by` is a handle.
- **"Trades match ⟹ everything matches" claims.** Explicitly false for
  max-drawdown / MFE / MAE. Wave 2 canaries exist precisely to cover
  that gap.

---

## 12. See also

- Brainstorm (historical context, reviewer feedback, Q1–Q7 debate):
  [`docs/superpowers/brainstorms/2026-07-20-pine-hybrid-fixture-suite.md`](../brainstorms/2026-07-20-pine-hybrid-fixture-suite.md)
- Current fixture prep guide (4-CSV workflow, to be updated in Session
  3): [`docs/pine/HOW_TO_PREPARE_TV_FIXTURES.md`](../../pine/HOW_TO_PREPARE_TV_FIXTURES.md)
- Reshape tool (D2.1 + D2.2 shipped):
  [`Tools/pine/reshape_tv_trades.py`](../../../Tools/pine/reshape_tv_trades.py)
- PR that introduced the "license manifest" drift-detection pattern
  this spec's bars-hash gate draws from:
  [PR #906](https://github.com/prajoria/OpenBB/pull/906)
- Conformance harness discovery walker to be extended (D2.5):
  [`.../conformance_strategy/conftest.py`](../../../openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/conftest.py)
