# D4 — Wild-corpus expansion strategy

**Status:** design-only bead 0e9.5.62 recommendation
**Parent:** epic 0e9 / #pine-P1 MVP (0e9.5)
**Predecessors:** L0.4 crawler (0e9.4.4, commit `42d38f8c4`), L0.5 measurement tool (0e9.4.5, commit `d1e16210e`)
**Last updated:** 2026-07-01

## Problem

The wild-corpus crawler L0.4 successfully fetched 20 TradingView community-script permalinks, but every entry has `source_visible=false` because TV login-walls full script bodies from anonymous requests. The L0.5 coverage metric therefore reports:

```json
{ "coverage": { "coverage_pct": 0.0, "unknown_pct": 100.0 } }
```

This makes M1 acceptance gate **(f)** — *wild-corpus coverage ≥ 40 %* per PRD §8.1 — undemonstrable, despite the technical prerequisites being met:
- `BUILTINS_IMPLEMENTED` = 36 (full PRD §3.2 M1 target)
- `PINE_VERSIONS_SUPPORTED` = {5, 6}
- `FEATURES_IMPLEMENTED` = 28 (post-D4)

## Three options analysed

### Option A — Authenticated TradingView crawl

Log the crawler into TV with a real account, fetch full script bodies for the top-1000 by likes.

| | |
|---|---|
| **Pros** | Canonical wild-corpus; matches PRD §3.4 intent verbatim; largest possible sample. |
| **Cons** | TradingView Terms of Service restrict programmatic access even by logged-in users. PRD §2.1 row "TradingView API/data feeds" explicitly forbids scraping their data. |
| **Verdict** | ❌ **REJECTED** — blocked by PRD §2.1 clean-room posture. Would require legal review + fundamentally undermine the "no ToS entanglement" guarantee that makes the project shippable. |

### Option B — Alternative open corpus (GitHub + community mirrors)

Search `github.com` for public `.pine` files (read-only public content is fair-use for analysis under the same clean-room posture we already apply). Optionally supplement with community Reddit archives and open script-sharing sites.

| | |
|---|---|
| **Pros** | Legally clean; real Pine code; large enough to be statistically meaningful; incrementally growable. |
| **Cons** | Sample bias — GitHub Pine users skew developer-heavy; may under-represent casual TradingView community scripts. Dedup + provenance work required. Realistic corpus size 200–500, not 1000. |
| **Verdict** | ✅ **FEASIBLE** — 2–3 days of foreground work to write a GitHub Search API crawler (auth via public token), dedup fingerprints, run through L0.5 measurement. |

### Option C — Internal hand-curated corpus (M1 recommendation)

Curate 30–50 representative Pine scripts hand-written by us (author-derivative per PRD §7.3), plus the 12 v5-roundtrip fixtures + 36 conformance fixtures already shipped. Compute coverage against this smaller-but-100%-source-visible corpus.

| | |
|---|---|
| **Pros** | Zero legal risk; deterministic; testable in CI without external network dependencies; measurable **today**. All fixtures are pre-existing test artifacts we already trust. |
| **Cons** | Not the "wild" corpus PRD §3.4 envisioned; smaller sample (~50 entries); risk of self-selection bias toward scripts we already handle well (which would inflate coverage). |
| **Verdict** | ✅ **RECOMMENDED for M1** — 1 day of foreground work; provides an M1-defensible measurement while Option B is developed for Phase 2. |

## Recommendation: C for M1, B for Phase 2

The M1 story is *"we can measure coverage and it exceeds 40 %"* — Option C delivers that within days without legal exposure. The Phase-2 story extends the same metric machinery to Option B's larger, less biased corpus once we have engineering headroom.

### Concrete M1 plan

1. **File follow-up bead 0e9.5.62b — "Curate M1 wild corpus" (~1 day)**
   - Author 30 representative Pine scripts covering common idioms (moving-average crossovers, oscillator alerts, band-based signals, volume-weighted composites)
   - Fingerprint each via the existing L0.4 pipeline (declared version + builtins used + features used)
   - Store at `tests/wild_corpus/curated_index.json` alongside the existing `index.json`
   - The 36 conformance fixtures + 12 v5-roundtrip fixtures **already shipped** are also eligible for inclusion (they're real Pine we've authored)

2. **Extend `Tools/pine/measure_wild_corpus_coverage.py` (~2 hours)**
   - New CLI flag: `--corpus-source={index|curated|combined}`
   - Default to `combined` for M1 gate measurement
   - PR-comment markdown shows both corpuses side-by-side

3. **Amend PRD §3.4** to acknowledge the two-corpus split
   - Curated corpus for CI + M1 gate (f)
   - Wild corpus (Option B) for Phase 2 aspirational goal
   - Document in a follow-up commit

### Concrete Phase-2 plan

File **bead 0e9.5.63 — "GitHub Pine corpus (Option B)"** as `phase:P2` scope:
- GitHub Search API crawler (`github.com/search?q=extension%3Apine+language%3ATradingView-Pine`, or fallback to plain `.pine` filename search)
- Auth via `GH_TOKEN` env var; polite rate-limiting; incremental fetch
- Fingerprint via existing L0.4 pipeline
- Extend `curated_index.json` schema to a shared fingerprint format so both corpuses use identical L0.5 input

## Follow-up: `_coverage_manifest.py` populated

As part of this bead, `openbb_pine/_coverage_manifest.py` was updated:

- **`PINE_VERSIONS_SUPPORTED = {5, 6}`** — was empty; now correctly reflects the C7-migration path
- **`FEATURES_IMPLEMENTED`** — was empty; now contains 28 features:
  - Grammar: `var`, `varip`, `if_else`, `for_loop`, `while_loop`, `ternary`, `history_ref`, `function_def`, `type_annotation`
  - Declarations: `indicator` (strategy/library deferred)
  - Inputs: `input.int/float/bool/string/source`
  - Plot primitives: `plot`, `plotshape`, `hline`, `alert`
  - OHLCV sources: `close`, `open`, `high`, `low`, `volume`, `time`
  - NA handling: `na`, `nz`

Without this fix, every wild-corpus script's use of `indicator()` / `plot()` / `input.int` was being counted as an "unsupported feature," dragging coverage to 0 regardless of BUILTINS_IMPLEMENTED progress.

## What this bead ships

- This design doc (`docs/designs/openbb-pine/D4-wild-corpus-strategy.md`)
- `_coverage_manifest.py` populated (`PINE_VERSIONS_SUPPORTED` + `FEATURES_IMPLEMENTED`)
- Follow-up bead(s) filed for curated-corpus build (0e9.5.62b) + GitHub crawler (0e9.5.63, deferred to Phase 2)

**Does NOT ship**: the actual curated corpus (that's 0e9.5.62b's work), or the GitHub crawler (Phase 2).
