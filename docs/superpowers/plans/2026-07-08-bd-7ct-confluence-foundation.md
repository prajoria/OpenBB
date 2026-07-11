# bd-7ct — Confluence Expansion Foundation PR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`. Steps use checkbox (`- [ ]`) tracking. **TDD throughout** — red before green. **Read the design doc first:** [`../specs/2026-07-08-confluence-panel-expansion-design.md`](../specs/2026-07-08-confluence-panel-expansion-design.md), especially §10 expert review + §12 recommendations R1-R12. Where design and this plan disagree, design wins — fix this plan.

**Goal:** Ship the **foundation** for the confluence panel expansion (bd-tik epic). This PR adds ZERO new indicators. It ships the **plumbing + eval harness** that every downstream family PR (bd-luy/40v/z43/alj) will use as its acceptance gate, and proves backward compatibility byte-identically.

**Non-goal:** No new indicators. No preset weight changes. No changes to `composite_score` / `conviction_for` / `MoverSignal` shape. All of that is deferred to family PRs — and each family PR is blocked by empirical harness data this PR generates.

**Architecture:** A versioned `PanelConfig` selector (enum, not `bool`) is threaded through `build_indicator_panel` / `technical_panel` / `build_signal` and resolved **once** per build (no per-vote branching). The classic path is preserved byte-identically when `panel="classic"`; a new `extended` path exists as a **pass-through stub** (populates the same 14 keys today — extension happens in family PRs). A new `engine/panel_eval.py` module computes per-vote **Information Coefficient** (IC) vs N-day forward return on a recorded single-name basket + logs shadow-mode divergence when both panels are computed side-by-side. Family PRs will import `panel_eval` and demonstrate positive IC + non-negative validate-DSR delta as their AC gate.

**Tech Stack:** Python 3.12, stdlib `enum` / `dataclasses`, pandas (for IC + rolling correlations), `openbb_techtrade` (existing engine modules), pytest, `openbb_techtrade.testing.assert_matches_golden` (#71 golden harness).

---

## Design decisions locked from the spec (rationale for reviewers)

1. **Enum selector, not bool (§11 OQ1 revised).** `PanelConfig(panel=Literal["classic","extended"])` future-proofs against v3 panels and reads better at call sites (`panel="extended"` vs `extended=True`). Frozen dataclass mirroring `IndicatorConfig`.
2. **PanelConfig is separate from ConfluenceWeights.** The reviewer flagged that panel builders don't currently receive weights (`build_indicator_panel` is a layer below scoring). Threading `PanelConfig` explicitly is architecturally cleaner than shoehorning panel selection into `ConfluenceWeights`.
3. **Flag on `AnalysisFeatureFlags` is the boot-time switch.** `use_extended_confluence_panel: bool = False` maps to `PanelConfig(panel="extended" if True else "classic")` at the pipeline entry. Env-var override matches PR #404 pattern. Family PRs will add `use_extended_confluence_panel=True` to their fixture cfg.
4. **Extended path is a pass-through in this PR.** `_compute_trend_ext` returns the same dict `_compute_trend` returns. This proves the plumbing works without introducing indicator risk; family PRs replace each stub with real new indicators. Golden invariance test proves `panel="classic"` and `panel="extended"` produce identical panels TODAY (until family PRs add keys).
5. **IC harness (R1) ships in this PR.** Not in family PRs. Every future family PR imports it — it is the acceptance gate. Ships with a baseline test that computes IC on the classic panel's existing votes on the basket fixture (baseline against which future family PRs will be measured).
6. **Shadow-mode logger writes parquet, not JSON.** ~1KB per symbol per day; ~4 weeks of shadow data is a few MB. Parquet columnar reads make the divergence analysis trivial in pandas.
7. **Single-name basket fixture** (per §10 N1): NVDA (hi-beta tech), PG (lo-vol staple), XOM (cyclical), PLTR (recent IPO). SPY stays as market baseline. 2020-2025 = 5 years, covers hi-vol regime (2022).
8. **No new external deps.** IC = `scipy.stats.spearmanr` is already in the platform's dep tree. Parquet writes use `pandas.to_parquet(engine="pyarrow")` — pyarrow already a platform dep.

---

## File Structure (7 new + 4 modified)

**NEW:**

| File | Purpose |
|---|---|
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/panel_config.py` | `PanelConfig` frozen dataclass + `PANEL_CLASSIC`/`PANEL_EXTENDED` sentinels |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_ext.py` | `_compute_{trend,momentum,volatility,volume}_ext` pass-through stubs |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence_ext.py` | `{trend,momentum,volatility,_volume}_votes_ext` pass-through stubs |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/panel_eval.py` | `compute_information_coefficient(vote_series, forward_returns)` + `shadow_diff` + `write_shadow_log` |
| `openbb_platform/extensions/techtrade/tests/fixtures/basket_2020_2025.parquet` | Recorded OHLCV for NVDA/PG/XOM/PLTR/SPY, 2020-01-01 → 2025-12-31 |
| `openbb_platform/extensions/techtrade/tests/unit/test_panel_config.py` | Contract tests for `PanelConfig` |
| `openbb_platform/extensions/techtrade/tests/unit/test_panel_eval.py` | IC harness tests |
| `openbb_platform/extensions/techtrade/tests/unit/test_panel_eval_baseline.py` | Baseline IC report on classic panel |
| `openbb_platform/extensions/techtrade/tests/unit/test_extended_pass_through.py` | Golden invariance: classic == extended today |
| `openbb_platform/extensions/techtrade/tests/unit/test_shadow_mode_logger.py` | Shadow-mode plumbing tests |
| `openbb_platform/extensions/techtrade/tests/unit/test_backward_compat_flag_off.py` | AC-1: flag-off byte-identical golden |
| `openbb_platform/extensions/techtrade/tests/unit/test_panel_build_perf.py` | p95 wall-clock ≤ 100ms |

**MODIFIED:**

| File | Change |
|---|---|
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py` | Add `panel_config: PanelConfig = PANEL_CLASSIC` kwarg to `build_indicator_panel` + `build_panel_for_symbol`. Dispatch to `_compute_*_ext` when `panel_config.panel == "extended"`. |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_technical.py` | Same kwarg + dispatch on `technical_panel`. |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence.py` | Add `panel_config` param to `build_signal`. Dispatch vote emitters to `_ext` when extended. |
| `Analysis/stock_analysis.py` | Add `use_extended_confluence_panel: bool = False` to `AnalysisFeatureFlags` with docstring + env-var override matching PR #404 pattern. |

---

## Implementation steps

Each step is a bd sub-bead under `bd-7ct`. Steps 1-3 are foundation; 4-6 are wiring; 7-9 are fixture + invariance proof; 10-12 are the harness + shadow logger; 13-14 are docs + review.

### Step 1 — PanelConfig object [bd-7ct.1]

**Deliverable:** `engine/panel_config.py` with the versioned selector.

- [ ] Create the module:
  ```python
  from dataclasses import dataclass
  from typing import Literal
  Panel = Literal["classic", "extended"]

  @dataclass(frozen=True, slots=True)
  class PanelConfig:
      panel: Panel = "classic"
      def __post_init__(self):
          if self.panel not in ("classic", "extended"):
              raise ValueError(f"unknown panel {self.panel!r}")

  PANEL_CLASSIC = PanelConfig(panel="classic")
  PANEL_EXTENDED = PanelConfig(panel="extended")
  ```
- [ ] RED: `tests/unit/test_panel_config.py` — unknown `panel=` value raises `ValueError`, `PANEL_CLASSIC` is frozen (mutation raises `FrozenInstanceError`), both sentinels reachable.
- [ ] GREEN.
- [ ] R7.10 module-scope constants — no magic strings elsewhere.

### Step 2 — Pass-through stubs [bd-7ct.2]

**Deliverable:** `engine/indicators_ext.py` + `engine/confluence_ext.py` — pass-throughs that return exactly what the classic functions return.

- [ ] `indicators_ext.py`:
  ```python
  from openbb_techtrade.engine.indicators import (
      _compute_trend, _compute_momentum, _compute_volatility, _compute_volume,
  )
  def _compute_trend_ext(df, config): return _compute_trend(df, config)
  # ... same for momentum/volatility/volume
  ```
- [ ] `confluence_ext.py` — same pattern for the 4 vote emitters.
- [ ] Docstrings state: *"Pass-through in bd-7ct; family PRs (bd-luy/40v/z43/alj) will replace each function with the extended implementation."*
- [ ] RED: `tests/unit/test_extended_pass_through.py` — computes classic panel + extended panel on same fixture, asserts dict equality.

### Step 3 — AnalysisFeatureFlags wire-up [bd-7ct.3]

**Deliverable:** New `use_extended_confluence_panel` flag on `AnalysisFeatureFlags` following the exact PR #404 pattern.

- [ ] Modify `Analysis/stock_analysis.py::AnalysisFeatureFlags`:
  - Add field `use_extended_confluence_panel: bool = False`
  - Add docstring paragraph referencing this spec
  - Extend `from_env()` reading `ANALYSIS_USE_EXTENDED_CONFLUENCE_PANEL`
- [ ] RED: extend existing feature-flags test with `test_use_extended_confluence_panel_default_false` + `test_from_env_reads_new_flag`.
- [ ] GREEN + full Analysis suite still passes.

### Step 4 — Thread PanelConfig through build_indicator_panel [bd-7ct.4]

**Deliverable:** `engine/indicators.py` accepts + honors `panel_config` kwarg.

- [ ] RED:
  - `test_build_panel_with_classic_config_matches_no_kwarg` — default kwarg produces same panel as omitting (backward compat).
  - `test_build_panel_with_extended_config_calls_ext_stubs` — extended path calls `_compute_trend_ext` (verified via `unittest.mock.patch` spy).
- [ ] GREEN: add `panel_config: PanelConfig = PANEL_CLASSIC` kwarg. Dispatch resolved ONCE at top of function (per D1 in spec).
- [ ] Also thread through `build_panel_for_symbol`.
- [ ] Regression: existing 400+ techtrade tests still pass.

### Step 5 — Thread PanelConfig through technical_panel [bd-7ct.5]

**Deliverable:** Mirror step 4 for `engine/indicators_technical.py`.

- [ ] RED: analogous tests targeting `technical_panel`.
- [ ] GREEN: same kwarg + dispatch pattern.

### Step 6 — Thread PanelConfig through confluence.build_signal [bd-7ct.6]

**Deliverable:** `engine/confluence.py::build_signal` accepts `panel_config` + dispatches vote emitters.

- [ ] RED:
  - `test_build_signal_classic_matches_no_kwarg` — backward compat
  - `test_build_signal_extended_calls_ext_vote_emitters` — spy on `trend_votes_ext` etc.
  - Golden regression: `build_signal` produces byte-identical `MoverSignal.score` + `MoverSignal.votes` under classic vs no-kwarg.
- [ ] GREEN.

### Step 7 — Single-name basket fixture [bd-7ct.7]

**Deliverable:** `tests/fixtures/basket_2020_2025.parquet` — recorded OHLCV for NVDA/PG/XOM/PLTR/SPY, 5 years.

- [ ] Author `tools/record_basket_fixture.py` (not shipped in the extension):
  - Uses `obb.equity.price.historical(symbol=X, provider="fmp_cached", start_date="2020-01-01", end_date="2025-12-31")`
  - Concatenates into single DataFrame with `symbol` column
  - Writes parquet via `pyarrow`
- [ ] Run once, commit the parquet (~200KB estimated).
- [ ] Add `tests/fixtures/__init__.py::load_basket()` returning `dict[str, pd.DataFrame]`.
- [ ] Header note: *"recorded 2026-07-08; do not regenerate without approval — golden invariance depends on stable data."*

### Step 8 — Golden invariance suite (flag-off byte-identical) [bd-7ct.8]

**Deliverable:** `tests/unit/test_backward_compat_flag_off.py` — the AC-1 guarantee.

- [ ] For each of 3 recorded panels (SPY / NVDA / PG on 2025-06-15) computed with the CURRENT (pre-PR) code:
  - Snapshot the panel dict to `tests/golden/panels/`
  - Snapshot the resulting `MoverSignal` to `tests/golden/signals/`
- [ ] RED: `test_classic_panel_matches_golden` — build panel with flag=False, assert against golden.
- [ ] RED: `test_classic_signal_matches_golden` — same for signals.
- [ ] R7.11 mutation-verify: temporarily change `_compute_trend` to return `{}`, confirm both tests flip red. Revert.
- [ ] Uses `openbb_techtrade.testing.assert_matches_golden` (#71 harness) → `TECHTRADE_REGEN_GOLDEN=1` can regenerate deliberately.

### Step 9 — Wall-clock benchmark [bd-7ct.9]

**Deliverable:** benchmark test proving PR adds negligible overhead.

- [ ] `tests/unit/test_panel_build_perf.py`: build classic panel N=100 times on NVDA fixture, measure mean+p95 wall-clock.
- [ ] Assert p95 ≤ 100ms per symbol.
- [ ] Same for extended path (should be same as classic since stubs pass through).

### Step 10 — panel_eval: IC computation [bd-7ct.10]

**Deliverable:** `engine/panel_eval.py::compute_information_coefficient` — the core of the R1 acceptance gate.

- [ ] RED: `tests/unit/test_panel_eval.py`:
  - `test_ic_perfect_positive_signal_returns_near_1` — synthetic vote series ≡ forward returns → IC ≈ +1.0
  - `test_ic_random_signal_returns_near_0` — random-normal votes vs random-normal returns → IC ≈ 0
  - `test_ic_negative_signal_returns_near_negative_1` — inverted synthetic → IC ≈ -1.0
  - `test_ic_flat_signal_returns_nan` — all-zero votes → IC is NaN (documented)
  - `test_ic_handles_nan_in_votes` — leading NaN votes → excluded from correlation
- [ ] GREEN: implement using `scipy.stats.spearmanr(vote_series, forward_returns.shift(-N))`. Default N=5 (business week). Return `ICResult(coefficient, p_value, n_samples, n_dropped_nan)` dataclass.
- [ ] Docstring cites Grinold's `IR = IC·√breadth`, links Bailey/López de Prado PBO paper.

### Step 11 — panel_eval: baseline IC report on classic panel [bd-7ct.11]

**Deliverable:** integration-lite test that computes baseline IC for every existing (classic) vote on the basket fixture.

- [ ] `tests/unit/test_panel_eval_baseline.py`:
  - For each symbol × each of 7 existing votes (ema_cross, macd_hist, rsi, stoch_cross, bb_pctb, obv_slope, cmf):
    - Compute vote series over 5-year fixture
    - Compute 5-day forward return
    - Call `compute_information_coefficient`
  - Assert every IC is finite
  - Print summary table: `(mean IC across basket, p95 IC, count of significant p<0.05)` — becomes the baseline row for family PRs
- [ ] Persist as `tests/golden/panel_eval/classic_baseline_ic.json` — snapshot future family PRs diff against.

### Step 12 — Shadow-mode logger [bd-7ct.12]

**Deliverable:** `engine/panel_eval.py::shadow_diff` + write helper.

- [ ] `shadow_diff(classic_signal, extended_signal) -> dict`:
  - Returns `{score_delta, vote_count_classic, vote_count_extended, added_vote_names, removed_vote_names, per_family_score_delta}`
- [ ] `write_shadow_log(diffs, out_dir)`:
  - Writes `Analysis/exports/panel_shadow_YYYY-MM-DD.parquet`
  - One row per symbol per day
  - Wraps write in try/except + R7.3 WARNING if path missing/unwritable — never blows up the pipeline
- [ ] Integration point (BEHIND the flag): when `panel_config.panel == "extended"`, ALSO compute classic panel + `shadow_diff` + append log. Return the EXTENDED signal (not classic). *"Shadow"* = observe classic vs extended in log while acting on extended.
- [ ] RED: `tests/unit/test_shadow_mode_logger.py`:
  - `test_shadow_diff_shape`
  - `test_shadow_diff_identical_panels_has_zero_deltas` (pass-through stubs → today, classic and extended are identical → all deltas 0.0)
  - `test_write_shadow_log_appends_correctly`
  - `test_write_shadow_log_survives_missing_dir` — R7.3 loud-empty on write failure
- [ ] GREEN.
- [ ] Docstring: cites [Wikipedia: Feature toggle](https://en.wikipedia.org/wiki/Feature_toggle) shadow-canary deployment pattern.

### Step 13 — Notebook 03 flag documentation [bd-7ct.13]

**Deliverable:** brief note about the flag (deferred deep dive to family PRs).

- [ ] Small markdown cell in notebook 03: *"The current panel is 14 keys / 7 votes. An extended panel is under development behind `AnalysisFeatureFlags(use_extended_confluence_panel=True)`. See `docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md`. This notebook currently uses the classic panel; family PRs (bd-luy/40v/z43/alj) will extend what shows up in the vote table."*
- [ ] No table changes (tables stay accurate for classic path).

### Step 14 — Full-suite regression + 3-way convergence review [bd-7ct.14]

**Deliverable:** full test suite green + parallel code review dispatched.

- [ ] Full techtrade suite: `pytest openbb_platform/extensions/techtrade/tests -m "not integration"` — all pass.
- [ ] Full Analysis suite: `pytest Analysis/tests/test_stock_analysis.py -m "not integration"` — all pass.
- [ ] **3-way parallel convergence review** (Phase B pattern):
  - `feature-dev:code-reviewer` — bugs, logic, project-convention adherence
  - `pr-review-toolkit:silent-failure-hunter` — silent fails, degenerate paths, R7.3 compliance
  - `pr-review-toolkit:pr-test-analyzer` — R7.11 mutation coverage, load-bearing test quality
- [ ] Address all HIGH findings; file MEDIUM+ as follow-up beads if not fixed inline.

---

## Review checkpoints (at least one per 3 steps)

- **After step 3**: user reviews `PanelConfig` shape + `AnalysisFeatureFlags` field (cheap to change now).
- **After step 6**: user reviews the wiring diff — is threading correct? Dispatch overhead acceptable?
- **After step 11**: user reviews the baseline IC report — do the numbers look sane? This is what every family PR must beat.
- **After step 14**: full 3-way reviewer verdict presented before commit + PR open.

---

## Beads to file (14 sub-beads under bd-7ct)

```
bd-7ct (parent)
  ├── bd-7ct.1  PanelConfig object
  ├── bd-7ct.2  Pass-through stubs                     blocked-by 7ct.1
  ├── bd-7ct.3  AnalysisFeatureFlags flag              (parallel to 7ct.1-2)
  ├── bd-7ct.4  Thread through build_indicator_panel   blocked-by 7ct.1, 7ct.2
  ├── bd-7ct.5  Thread through technical_panel        blocked-by 7ct.1, 7ct.2
  ├── bd-7ct.6  Thread through build_signal            blocked-by 7ct.1, 7ct.2
  ├── bd-7ct.7  Basket fixture                        (parallel — no code deps)
  ├── bd-7ct.8  Golden invariance suite                blocked-by 7ct.4, 7ct.5, 7ct.6, 7ct.7
  ├── bd-7ct.9  Wall-clock benchmark                   blocked-by 7ct.4
  ├── bd-7ct.10 panel_eval IC computation              (parallel — pure math module)
  ├── bd-7ct.11 baseline IC report                     blocked-by 7ct.7, 7ct.10
  ├── bd-7ct.12 Shadow-mode logger                     blocked-by 7ct.6, 7ct.10
  ├── bd-7ct.13 Notebook 03 flag note                  (parallel)
  └── bd-7ct.14 Full-suite regression + review         blocked-by all above
```

---

## Acceptance criteria (rolls up to bd-7ct)

- [ ] `use_extended_confluence_panel=False` → panel + signal byte-identical to pre-PR (golden regression on 3 recorded fixtures).
- [ ] `use_extended_confluence_panel=True` → extended path is exercised, produces identical panel/signal today because stubs pass through. Shadow log fires and records zero-delta rows.
- [ ] `PanelConfig(panel="extended")` and `PANEL_EXTENDED` sentinel both work.
- [ ] `panel_eval.compute_information_coefficient` returns known values on synthetic fixtures.
- [ ] Baseline IC report generated for all 7 existing votes on 5-symbol × 5-year basket. Persisted as golden.
- [ ] Wall-clock p95 ≤ 100ms per symbol (unchanged from baseline).
- [ ] Full techtrade suite + Analysis suite pass.
- [ ] 3-way parallel review verdict: GREEN or YELLOW-with-fixes-applied.
- [ ] bd sub-beads all closed; bd-7ct closed; bd-tik epic remains open (family PRs still pending).

---

## Rollout after this PR

Once bd-7ct merges:

1. Sync + update bd-luy/40v/z43/alj descriptions: *"harness available at `panel_eval.compute_information_coefficient`; run baseline first, then measure each new vote's IC delta vs baseline; must be positive to ship."*
2. Shadow-mode logs accumulate. After 4-6 weeks, review divergence + IC deltas across family PRs to decide default flip.
3. Docs PR bd-znw follows once at least trend + volatility PRs have landed.

---

## Total budget

- Steps 1-3: 0.5 day
- Steps 4-6: 0.5 day
- Steps 7-9: 0.5 day
- Steps 10-12: 0.75 day
- Steps 13-14: 0.25 day
- Reviewer feedback iterations: 0.5 day

**Total: ~3 days** (design estimated 1 day; scope is bigger with harness landing in Phase 2 per §12 R1).
