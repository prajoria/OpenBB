# bd-luy — Trend Family Expansion Implementation Plan (Aroon + Ichimoku)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`. TDD throughout — red before green. **Read first:** [`../specs/2026-07-08-confluence-panel-expansion-design.md`](../specs/2026-07-08-confluence-panel-expansion-design.md) §3.1 (trend family picks), §10.3 C3 (ADX gate reclassification), §10.4 M4 (min-bar caveat), §10.4 M5 (turnover budget + hysteresis), §12 R1 (empirical IC gate) — and the foundation plan [`2026-07-08-bd-7ct-confluence-foundation.md`](2026-07-08-bd-7ct-confluence-foundation.md). Where design and this plan disagree, design wins.

**Goal:** Replace the trend-family pass-through stubs (shipped in bd-7ct) with real Aroon + Ichimoku implementations, gated on a defensible net-of-cost Information Coefficient. Reclassify ADX from a directional vote to a gate/confidence scaler per §10 C3.

**Scope decision (§ Expert review 2, PSAR cut):** PSAR was in the original design (§3.1 T6) but is **cut from bd-luy scope** on best-practice grounds — Han/Yang/Zhou (2011, *RFS*) and Neely et al. (2014, *Management Science*) both show PSAR has negative alpha on US equities after costs, and modern institutional quant surveys show near-zero usage. A follow-up bead `bd-<PSAR-later>` is filed for revisiting PSAR (or better: Donchian breakout / 200-day SMA slope / cross-sectional momentum) after Aroon + Ichimoku land and we have real shadow-mode data.

**Architecture:** `_compute_trend_ext` populates the classic keys PLUS 5 new keys (`aroon_up`, `aroon_down`, `aroon_osc`, `ichimoku_price_vs_cloud`, `ichimoku_confirmed_position`). `trend_votes_ext` returns the classic votes PLUS 2 new votes (`aroon_osc`, `ichimoku_cloud` — the latter with 3-bar confirmation buffer). ADX becomes a gate/scaler applied inside `macd_hist` vote (existing behavior preserved). Ichimoku degrades gracefully when < 78 bars are available.

**Tech Stack:** `pandas_ta_classic` (already vendored) — `df.ta.aroon(length=25)`, `df.ta.ichimoku(tenkan=9, kijun=26, senkou=52)`. No new external deps. (9/26/52 is Hosoda's 1969 original — every professional Ichimoku practitioner uses these; alternative retail parameters like 20/60/120 have no published empirical support.)

---

## Design decisions locked from the spec (rationale for reviewers)

**Revised after expert review (§ R.3 blockers B1 + B2, plus additional best-practice controls from a second-pass trader/quant review). See §R.7 recommendations 1-7 + § Expert review 2. Two rounds of review reshaped this plan; the numbering below reflects the final state.**

1. **R1 IC gate: net-of-cost + null-model + walk-forward + BH-corrected + real point-in-time universe (B1 fix + best-practice additions).** Original threshold ("mean IC > +0.005 AND ≥3/5 basket positive") was near-vacuous — P(≥3/5 positive | true IC=0) = 0.5, and +0.005 is well inside overlap-corrected standard error. **Revised gate**:

   - **Metric**: **net-of-cost** IC information ratio `mean_fold(IC_net) / std_fold(IC_net)` across walk-forward folds. Gross-of-cost IC also reported for context.
   - **Universe**: cross-sectional over the **real scan universe** (XLK sector-ETF holdings ≈ 70 symbols, plus SPY as market baseline) — not 5 hand-picked survivors. Basket of 4 (NVDA/PG/XOM/SPY) stays as fast-suite smoke fixture only.
   - **IC formulation**: **Spearman cross-sectional-per-day, then time-averaged** (Grinold formulation from *Active Portfolio Management* Ch. 10). Explicit to avoid the common "per-symbol time-series IC then average across symbols" mistake that inflates significance via within-symbol autocorrelation.
   - **Fold structure**: **rolling window, 15 folds** (12-month train / 1-month slide / 3-month test). 5 folds gives only 4 dof for the std estimate — inadequate. 15 folds gives a meaningful IC-IR distribution.
   - **Horizon**: 20-bar forward return (matches `max_holding_bars`), with 5/10/20 grid reported for context.
   - **Standard error**: block bootstrap with blocksize = horizon (20 bars) to correct for overlapping-return autocorrelation.
   - **Cost model**: crude but honest — **−6 bps per round-trip** (Interactive Brokers-tier liquid-name conservative estimate). `IC_net_per_fold = IC_gross_per_fold − 6bps × trades_per_fold / return_per_fold`. Realistic annualized cost drag on a 12-flips/year signal at 20-bar holding: **~7 bps/month** in absolute terms.
   - **Null-model baseline**: 1000-permutation shuffle of the vote series → compute IC-IR under each permutation → require `actual IC-IR > 95th percentile of null IC-IR`. This is more defensible than any parametric significance test (Bailey/López de Prado PBO paper 2014, cited in design §12 R1).
   - **Regime-segmented breakdown**: JSON also reports IC-IR by market regime (using `openbb-regime` from PR #349). A signal that has aggregate IC-IR = 0.7 but IC = +2.0 in BULL / -1.5 in CRISIS is a regime-conditional signal, not a stable one — this surfaces the distinction for the reviewer.
   - **Multiple-testing correction**: **Benjamini-Hochberg** across the candidate votes at α=0.05.
   - **Ship criterion (per vote, all 4 required)**:
     1. Net-of-cost **IC-IR > 0.7** (not 0.5 — Grinold reports BGI production signals at 0.35-0.55, so 0.5 gross ≈ 0.3 net which is too weak to justify complexity)
     2. Null-model empirical p < 0.05 (actual IC-IR beats 95th percentile of 1000 permutations)
     3. BH-corrected parametric one-sided p < 0.05
     4. Regime breakdown shows positive net IC in **at least 2 of the 4 regimes** (`TRENDING_BULL` / `RANGING` / `TRENDING_BEAR` / `CRISIS`) — otherwise it's a regime-conditional signal and should be routed via `use_regime_input`, not shipped as a universal vote
   - **Discipline unchanged**: any vote that fails is cut from the PR + follow-up bead filed. Do not lower the thresholds. If all fail, the PR ships as a no-op (empty extension) — that's a real outcome, not a bug.

2. **ADX stays as a gate/scaler, not a vote (§10 C3).** Unchanged — expert reviewer confirmed correct.

3. **Ichimoku min-bar degradation (§10 M4) — unchanged from original.** Reviewer confirmed correct.

4. **Ichimoku cloud vote gets 3-bar confirmation buffer (§R.4 M3 fix).** Original design applied hysteresis only to PSAR (which is now cut); Ichimoku still gets symmetric treatment because Kumo-cross whipsaws in ranges are exactly what §10 M5 warned about. Cloud-cross must persist for 3 consecutive bars before flipping. Implemented as a pure fixed-window function.

5. **Golden invariance is the AC ceiling, not a floor.** Unchanged — reviewer called this "the strongest part of the plan."

6. **Decorrelation gate tightened to |ρ| ≤ 0.70 (§R.4 M4 fix).** Original 0.85 admits 72% shared variance. 0.70 admits 49% — more honest for intra-family diversification. Near-miss pairs (0.6 ≤ |ρ| ≤ 0.7) are reported with numbers but don't fail. Aroon-vs-(raw ADX level) reported as FYI even though ADX isn't a vote (§R.4 M4 tail).

7. **PSAR cut from scope (best-practice recommendation).** Empirical support is weak (Han/Yang/Zhou 2011 negative alpha; Neely et al. 2014 dominated by 200-day SMA), and modern institutional quant surveys show near-zero usage. Rather than build hysteresis machinery around a signal with low prior probability of clearing an honest gate, cut it and file a follow-up bead for revisiting — or better, replacing it with **Donchian breakout** (Richard Dennis's actual Turtle Trader signal), **200-day SMA slope** (Faber 2007), or a **cross-sectional 3/6/12-month momentum factor** (Asness/Moskowitz/Pedersen 2013, the design's own §R.7 R3 recommendation).

---

## File Structure (3 new + 3 modified + 1 new tool)

**NEW:**

| File | Purpose |
|---|---|
| `openbb_platform/extensions/techtrade/tests/unit/test_extended_trend_family.py` | Unit tests for the 5 new panel keys + 2 new vote mappers + Ichimoku min-bar degradation + Ichimoku 3-bar confirmation + Aroon direction + determinism tests |
| `openbb_platform/extensions/techtrade/tests/unit/test_decorrelation_trend_family.py` | R7.4 seam contract: pairwise Spearman ρ on trend-family votes, |ρ| ≤ 0.70 (tightened per §R.4 M4) |
| `openbb_platform/extensions/techtrade/tests/unit/test_trend_family_ic.py` | Mechanics-only pytest: finite IC, adequate n_samples, backend="scipy". Does NOT gate on threshold (§R.4 M5 — statistical acceptance lives in the reviewed JSON, not a rotting CI assert) |
| `tools/measure_trend_ic.py` | Offline script producing `tests/golden/panel_eval/extended_trend_ic.json` — the reviewed R1 acceptance artifact (walk-forward 15-fold + XLK point-in-time universe + net-of-cost + null-model permutation + regime-segmented + BH-corrected + block-bootstrap-CI per §R.3 B1 and best-practice controls) |
| `openbb_platform/extensions/techtrade/tests/golden/panel_eval/extended_trend_ic.json` | Reviewed R1 acceptance JSON (checked in as the merge-time evidence) |

**MODIFIED:**

| File | Change |
|---|---|
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_ext.py` | Replace `_compute_trend_ext` pass-through with real impl: classic keys + Aroon (3 keys: `aroon_up`, `aroon_down`, `aroon_osc`) + Ichimoku (2 keys: raw `ichimoku_price_vs_cloud` + confirmed `ichimoku_confirmed_position`). Module constant `_ICHIMOKU_CONFIRMATION_BARS=3` (R7.10). Preserve pass-through pattern for other 3 families. |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence_ext.py` | Replace `trend_votes_ext` pass-through with real impl: classic votes + `aroon_osc_vote` + `ichimoku_cloud_vote` (reads `ichimoku_confirmed_position`). Both new votes are pure functions of the panel — no cross-call state. Preserve pass-through pattern for other 3 families. |
| `openbb_platform/extensions/techtrade/tests/unit/test_extended_pass_through.py` | Update trend-family byte-identity tests → subset assertion (classic keys ⊂ extended keys, classic votes ⊂ extended votes by name). Momentum/volatility/volume stay strict byte-identity. |
| `openbb_platform/extensions/techtrade/tests/golden/panel_eval/classic_baseline_ic.json` | **UNCHANGED** — extended IC lives in the separate `extended_trend_ic.json` artifact. |
| `notebooks/03-single-position-deep-dive.ipynb` | Update the flag callout with a "extended trend family shipped (Aroon + Ichimoku)" note. |

---

## Implementation steps

Each step is a bd sub-bead under bd-luy. Steps 1-2 build the primitives; 3-5 wire the tests; 6-7 verify. **Step 3 (PSAR) has been cut from scope per Design decision 7 — a follow-up bead is filed for revisiting PSAR (or better alternatives: Donchian breakout, 200-day SMA slope, cross-sectional 3/6/12-month momentum) after Aroon + Ichimoku land and shadow-mode data accumulates.**

### Step 1 — Aroon panel + vote [bd-luy.1]

**Deliverable:** `_compute_trend_ext` populates `aroon_up`, `aroon_down`, `aroon_osc`; `trend_votes_ext` emits `aroon_osc_vote`.

- [ ] RED: `test_extended_trend_family.py::test_aroon_keys_populated` — build panel on 100-bar synthetic uptrend, assert all 3 aroon keys present with finite values.
- [ ] RED: `test_extended_trend_family.py::test_aroon_osc_vote_positive_on_uptrend` — synthetic uptrend produces `aroon_osc > 0` (up recency > down recency) → vote > 0.
- [ ] RED: `test_extended_trend_family.py::test_aroon_osc_vote_negative_on_downtrend` — mirror.
- [ ] RED: `test_extended_trend_family.py::test_aroon_determinism_run_twice` — same OHLCV → same vote across two independent calls (proves purity).
- [ ] GREEN: replace `_compute_trend_ext` pass-through with classic + `df.ta.aroon(length=25)` addition. Vote formula: `sign(aroon_up - aroon_down) * min(1, abs(aroon_up-aroon_down)/100)` per spec §D5.
- [ ] R7.11 mutation-verify: swap `aroon_up - aroon_down` to reversed → downtrend test flips red.

### Step 2 — Ichimoku panel + vote [bd-luy.2]

**Deliverable:** `_compute_trend_ext` populates `ichimoku_price_vs_cloud` (raw single-bar ±1/0); `trend_votes_ext` emits `ichimoku_cloud_vote` with **3-bar confirmation buffer** (§R.4 M3 fix).

- [ ] RED: `test_ichimoku_key_populated_when_history_sufficient` — 200-bar fixture → key present.
- [ ] RED: `test_ichimoku_key_absent_when_history_too_short` — 40-bar fixture → key NOT in panel (graceful degrade per §10 M4).
- [ ] RED: `test_ichimoku_vote_absent_when_key_absent` — short-history fixture → vote-list doesn't contain `ichimoku_cloud`.
- [ ] RED: `test_ichimoku_vote_requires_3_bar_confirmation` — price crosses cloud edge for 1 bar then reverses → vote stays 0 (no flip). Only after 3 consecutive same-side bars does the vote emit ±1. Symmetric with PSAR treatment per §R.4 M3 (even though PSAR is now cut, the hysteresis discipline is still correct here).
- [ ] RED: `test_ichimoku_vote_above_cloud_positive` — synthetic trending series with price above senkou-span-max for ≥3 consecutive bars → +1 vote.
- [ ] RED: `test_ichimoku_determinism_run_twice` — same OHLCV → same vote across two independent calls (proves purity).
- [ ] GREEN: extend `_compute_trend_ext` with `df.ta.ichimoku(tenkan=9, kijun=26, senkou=52)`. Populate BOTH `ichimoku_price_vs_cloud` (raw single-bar, preserved for audit) AND `ichimoku_confirmed_position` (3-bar-confirmed windowed vote input). Vote reads the confirmed key; missing key ⇒ no vote emitted.
- [ ] R7.11 mutation-verify: change confirmation window from 3→1 → `test_ichimoku_vote_requires_3_bar_confirmation` flips red.

### Step 3 — Update pass-through test to subset semantics [bd-luy.3]

**Deliverable:** `test_extended_pass_through.py`'s trend-family tests change from strict-equality to subset-of-keys.

- [ ] Locate: `TestIndicatorsExtPassThroughEquality::test_trend_ext_matches_classic` and `TestBuildIndicatorPanelExtendedDispatch::test_extended_produces_identical_panel_today` and `TestBuildSignalExtendedDispatch::test_extended_produces_identical_signal_today`
- [ ] Change trend-related assertions to `assert set(classic_keys).issubset(set(extended_keys))` + `assert len(extended) > len(classic)` (there must actually be new keys or the whole PR was a no-op).
- [ ] LEAVE momentum/volatility/volume tests STRICT — bd-40v/z43/alj will update those when they land.
- [ ] Existing tests for `_compute_momentum_ext` / `_compute_volatility_ext` / `_compute_volume_ext` still assert byte-identity.

### Step 4 — Decorrelation gate [bd-luy.4]

**Deliverable:** `test_decorrelation_trend_family.py` computes pairwise |ρ| ≤ 0.70 across all trend votes on the basket (§R.4 M4: tightened from 0.85).

- [ ] Load basket fixture, build every daily panel for each symbol, extract all trend votes → DataFrame per symbol × vote.
- [ ] For each pair (i, j) with i < j, compute Spearman ρ.
- [ ] Assert `abs(rho) <= 0.70` for every pair.
- [ ] Report near-miss pairs (0.60 ≤ |ρ| ≤ 0.70) with their exact numbers but don't fail — surfaces mechanistic overlap for reviewer inspection.
- [ ] Additionally report Aroon-vs-(raw ADX level) correlation as FYI (ADX isn't a vote but shares the directional-movement mechanism per §R.4 M4 tail).
- [ ] Print full matrix so a reviewer can see the numbers (not just the pass/fail).
- [ ] Marked `integration` since it iterates the 5-year basket × 4 symbols × ~7 votes (~30s).

### Step 5 — R1 IC acceptance gate: net-of-cost + null-model + regime-segmented + walk-forward JSON artifact [bd-luy.5]

**Deliverable (revised after §R.3 B1 + §R.4 M1/M2/M5/M6 + best-practice second-pass review):** Two-part gate:
- **(a) `tools/measure_trend_ic.py`** — offline script that produces the reviewed JSON artifact `tests/golden/panel_eval/extended_trend_ic.json`. This is the **acceptance evidence** at merge time.
- **(b) `test_trend_family_ic.py`** — pytest that asserts only **mechanical correctness** (finite IC, adequate n_samples, `backend == "scipy"`) on the small 4-symbol basket. Does NOT assert edge thresholds → won't rot as data updates (§R.4 M5).

**Part (a) — the reviewed JSON artifact:**

Metric methodology (§R.3 B1 fix + best-practice controls):

- **Universe**: real point-in-time XLK holdings on each fold's train-end date (typically ~70 symbols), NOT the 4-symbol basket. Basket is smoke-test only.
- **IC formulation**: **Spearman cross-sectional-per-day, then time-averaged** (Grinold formulation from *Active Portfolio Management* Ch. 10). Explicit to avoid the common "per-symbol time-series IC then average across symbols" mistake that inflates significance via within-symbol autocorrelation.
- **Fold structure**: **rolling window, 15 folds** (12-month train / 1-month slide / 3-month test). 5 folds → only 4 dof for std estimate — inadequate. 15 folds gives a meaningful IC-IR distribution.
- **Horizons reported**: {5, 10, 20} bars forward. Gate on **20** (matches `max_holding_bars`); 5/10 reported for context (§R.4 M1 fix).
- **Standard error**: block bootstrap with blocksize = horizon (20 bars) to correct for overlapping-return autocorrelation (§R.4 M6 fix).
- **Cost model**: crude but honest — **−6 bps per round-trip** (Interactive Brokers-tier liquid-name conservative estimate). `IC_net_per_fold = IC_gross_per_fold − 6bps × trades_per_fold / return_per_fold`. Realistic annualized cost drag on a 12-flips/year signal at 20-bar holding: ~7 bps/month in absolute terms.
- **Null-model baseline**: 1000-permutation shuffle of the vote series → compute IC-IR under each permutation → require `actual IC-IR > 95th percentile of null IC-IR`. Bailey/López de Prado 2014 (cited in design §12 R1) — more defensible than any parametric significance test because it makes zero assumptions about return distribution.
- **Regime segmentation**: JSON reports IC-IR by market regime using `openbb-regime` from PR #349 (`TRENDING_BULL` / `RANGING` / `TRENDING_BEAR` / `CRISIS`). Signals with strong aggregate IC-IR but only 1 regime showing positive net IC are regime-conditional — should be routed via `use_regime_input`, not shipped as universal votes.
- **Multiple-testing correction**: **Benjamini-Hochberg** across the 2 candidate votes at α=0.05 (§R.3 B1). With only 2 votes the BH threshold is close to raw α — but the correction discipline is preserved.
- **Ship criterion (per vote, ALL 4 required)**:
  1. Net-of-cost **IC-IR > 0.7** (not 0.5 — Grinold reports BGI production signals at 0.35-0.55, so 0.5 gross ≈ 0.3 net which is too weak to justify complexity)
  2. Null-model empirical p < 0.05 (actual IC-IR beats 95th percentile of 1000 permutations)
  3. BH-corrected parametric one-sided p < 0.05
  4. Regime breakdown shows positive net IC in **≥ 2 of the 4 regimes** (otherwise it's a regime-conditional signal and should be routed via `use_regime_input`, not shipped as a universal vote)

Emitted JSON structure:
```json
{
  "generated_at": "2026-07-10T...",
  "universe": "XLK holdings, point-in-time per fold",
  "fold_config": {"n_folds": 15, "train_months": 12, "slide_months": 1, "test_months": 3},
  "cost_bps_per_round_trip": 6,
  "null_model_permutations": 1000,
  "horizons_bars": [5, 10, 20],
  "gate_horizon": 20,
  "bh_alpha": 0.05,
  "ship_criteria": {
    "min_ic_ir_net": 0.7,
    "null_model_percentile": 95,
    "min_positive_regimes": 2
  },
  "votes": {
    "aroon_osc": {
      "per_fold_ic_gross": [...],
      "per_fold_ic_net": [...],
      "ic_ir_gross": 0.85,
      "ic_ir_net": 0.72,
      "block_bootstrap_ic_ci": [0.02, 0.08],
      "null_model_ic_ir_p95": 0.31,
      "null_model_p_empirical": 0.012,
      "bh_corrected_p": 0.024,
      "regime_ic": {
        "TRENDING_BULL": {"n": 380, "ic_net": 0.045},
        "RANGING": {"n": 210, "ic_net": 0.008},
        "TRENDING_BEAR": {"n": 95, "ic_net": -0.012},
        "CRISIS": {"n": 45, "ic_net": 0.031}
      },
      "positive_regimes": 3,
      "ship": true
    },
    "ichimoku_cloud": {...}
  },
  "shipped_votes": ["aroon_osc", "ichimoku_cloud"],
  "cut_votes": []
}
```

Reviewer signs off on the JSON at the **step-5 review checkpoint** — the JSON is the acceptance artifact, not a pytest assertion. If a vote is cut, file follow-up bead + strip its implementation from the PR.

**Part (b) — mechanics-only pytest:**

- [ ] For each of `{aroon_osc, ichimoku_cloud}` × each of `{NVDA, PG, XOM, SPY}` (4 symbols; PLTR excluded per §R.4 M2 — 2020 IPO doesn't have full 5-year history):
  - Compute IC via `compute_information_coefficient(votes, returns, forward_bars=20)`
  - Assert `math.isfinite(ic.coefficient)` (or `n_samples == 0` in short-history graceful-drop case)
  - Assert `ic.backend == "scipy"`
  - Assert `ic.n_samples > 100` (enough data to be non-degenerate)
- [ ] Does NOT assert IC > any threshold — that lives in the reviewed JSON.
- [ ] Marked `integration` (~1 min).

**Discipline unchanged**: if the JSON gate cuts a vote, cut its implementation from the PR + file follow-up. Do not lower the thresholds.

### Step 6 — Notebook 03 update [bd-luy.6]

**Deliverable:** Refresh the `bd-7ct foundation` callout cell in notebook 03 to mention the extended trend family (Aroon + Ichimoku) is now live.

### Step 7 — Full-suite regression + 3-way review [bd-luy.7]

**Deliverable:** All tests green; parallel review dispatched.

- [ ] `pytest openbb_platform/extensions/techtrade/tests -m "not integration"` — all pass, no classic-path regressions (bd-7ct.8 + bd-o4q goldens still byte-identical).
- [ ] `pytest -m integration` — new integration tests pass; existing integration flakiness not new.
- [ ] 3-way parallel review: `feature-dev:code-reviewer` + `pr-review-toolkit:silent-failure-hunter` + `pr-review-toolkit:pr-test-analyzer`.

---

## Review checkpoints

- **After step 2**: user reviews the Ichimoku 3-bar-confirmation implementation before wiring downstream tests. Now the biggest architectural moving piece with PSAR cut from scope.
- **After step 5**: user reviews the `extended_trend_ic.json` acceptance artifact. **This IS the R1 gate sign-off** — any vote whose JSON entry doesn't clear ALL 4 criteria (IC-IR net > 0.7, null-model p < 0.05, BH-corrected p < 0.05, ≥2 regimes positive) gets cut from the PR + follow-up bead filed.
- **After step 7**: full 3-way reviewer verdicts presented before commit + PR open.

---

## Acceptance criteria

- [ ] With `PANEL_CLASSIC` (or default kwarg), byte-identical to pre-bd-luy (bd-7ct.8 + bd-o4q goldens still pass).
- [ ] With `PANEL_EXTENDED`, trend panel has ≥5 new keys and ships whatever subset of {`aroon_osc`, `ichimoku_cloud`} passes the R1 gate below (may be 0-2 votes; the panel keys are always populated for audit even if the vote is cut).
- [ ] **R1 IC gate (reviewed JSON artifact)**: `extended_trend_ic.json` shows, for each shipped vote, ALL 4 criteria met:
  - Net-of-cost IC-IR > 0.7 at the 20-bar horizon (Grinold-formulation, walk-forward 15-fold on XLK point-in-time universe)
  - Null-model empirical p < 0.05 (1000 permutations)
  - BH-corrected parametric one-sided p < 0.05
  - ≥ 2 of 4 regimes show positive net IC
- [ ] Every pair of trend votes has |Spearman ρ| ≤ 0.70 on the basket (§R.4 M4).
- [ ] Ichimoku degrades gracefully on <78-bar histories (no exception, no key, no vote).
- [ ] Ichimoku passes deterministic-purity tests (same OHLCV → same vote; run-twice invariance).
- [ ] Mechanics-only pytest (`test_trend_family_ic.py`) asserts finite IC + adequate n_samples on 4-symbol subset (PLTR excluded per §R.4 M2). Does NOT assert threshold — that's the JSON's job.
- [ ] 3-way review verdict: GREEN or YELLOW-with-fixes-applied.

---

## Total budget

- Steps 1-2: 0.5 day (Aroon + Ichimoku, both well-defined; PSAR cut saves 0.25d)
- Step 3: 0.1 day (test updates)
- Step 4: 0.2 day (decorrelation)
- Step 5: 0.9 day (walk-forward IC harness + XLK point-in-time universe fetch + null-model permutation + cost model + regime segmentation + BH correction + block-bootstrap CI + reviewed JSON — up from 0.3d due to §R.3 B1 rigor + best-practice controls; this step is where the honesty lives)
- Step 6: 0.05 day (notebook)
- Step 7 + review iteration: 0.5 day

**Total: ~2.2 days** (same as previous estimate: PSAR cut savings offset by IC harness sophistication).

---

## Expert review — trader / quant analyst

> Reviewer lens: systematic technical trading + quantitative signal validation. Claims below were checked against the shipped harness (`engine/panel_eval.py::compute_information_coefficient`) and the live vote emitters (`engine/confluence.py`), not just the plan text. **Headline: the *engineering* plan is solid and well-sequenced; the *statistical acceptance gate* (Step 6 / R1) is, as specified, too weak to protect against exactly the overfitting the parent design invoked it to prevent — and the PSAR hysteresis quietly breaks the determinism contract the audit trail depends on. Fix those two before building.**

### R.1 Verdict

Approve the scaffold and the trend *indicators* (Aroon/Ichimoku/PSAR are all defensible best-of-class picks), but **do not accept Step 6's gate as written**. Two changes are blocking (B1, B2); the rest are strong-recommend.

### R.2 What the plan gets right

- **Golden-invariance handling (Step 4)** is exactly correct: classic path stays byte-identical, extended path moves equality→subset with a `len(extended) > len(classic)` guard so a no-op PR can't sneak through. This is the strongest part of the plan.
- **ADX-stays-a-gate (decision 2)** correctly implements design §10 C3 — no borrowed-direction double-count. Good.
- **Ichimoku graceful degrade (decision 4)** matches the existing pandas-ta absent-key pattern; the RED tests for the <78-bar case are the right shape.
- **"If a vote fails, cut it — do not lower the threshold" (Step 6)** is the right *discipline*, even though the threshold itself is mis-set (see B1).

### R.3 Blocking issues

**B1 — The R1 IC gate is statistically near-vacuous as specified, and is *weaker* than the harness you already have.**
The gate is "mean IC > +0.005 AND ≥3/5 symbols positive." Problems, in order of severity:
- **"≥3 of 5 symbols positive" is a coin flip.** Under the null (true IC = 0), P(≥3 of 5 positive) = 0.5 exactly (binomial, p=0.5). So this clause admits pure noise half the time. It provides essentially zero selective power.
- **+0.005 is inside the noise band.** `compute_information_coefficient` is a Spearman IC; its standard error is ≈ `1/√n_eff`. Critically, the harness computes **overlapping** 5-day forward returns (`returns.shift(-5)` on daily bars, confirmed in source), so consecutive observations share 4/5 of their window → effective sample size is ~n/5 and the naïve SE is understated by ~√5. An IC of 0.005 will not be distinguishable from 0 at any honest confidence level. You will "pass" votes that are indistinguishable from a random series.
- **You're ignoring the `p_value` the harness already returns.** `ICResult` carries a per-symbol `p_value`; the gate throws it away in favour of a raw threshold. Use it. Better: aggregate properly (below).
- **No multiple-testing / DSR / PBO correction — which design §12 R1 explicitly required.** You test 3 votes × 5 symbols = 15 IC estimates and keep the winners. The parent spec's R1 said "PBO / deflated-Sharpe guard for the added degrees of freedom." As written this plan under-delivers against the very requirement it cites, and the plan's own preamble says "where design and this plan disagree, design wins" — so design wins here.
- **In-sample selection / no OOS split.** IC is measured on the same 2020–2025 basket the vote will then trade forward. Selecting on the full sample and shipping is the textbook data-snooping the design warned about. There is no train/validate/walk-forward partition.

→ **Replace the gate with a defensible one** (see R.5 rec 1): measure the **IC information ratio** `mean(IC)/std(IC)` across a **walk-forward** split on a **much larger, point-in-time universe** (the actual scan universe — the sector-ETF holdings, hundreds of names — not 5 hand-picked survivors), require a **one-sided significance** after a Newey-West / non-overlapping-window or block-bootstrap SE correction, and apply a **Bonferroni/BH** correction across the votes tested. Keep "don't lower the threshold" — just set the threshold somewhere meaningful.

**B2 — PSAR hysteresis makes the vote path-dependent, silently breaking the "identical panel in → identical vote out" determinism contract that the reasoning/audit trail is sold on.**
The whole selling point of this engine (design doc §3, "deterministic, votes-only narrative; no LLM; same panel + weights → same reasoning") is that a vote is a pure function of the current panel. "Emit the last non-zero vote (persistence)" makes `psar_direction_vote` a function of **history**, not of the current bar's panel. Consequences:
- Two identical panels can now produce different votes depending on preceding bars → the audit trail's reproducibility guarantee no longer holds for this vote.
- **Option A is under-specified for the stated semantics.** Packing `psar_streak_len` (count of consecutive same-direction bars) is *insufficient* to implement "persist the last non-zero vote," because when the current streak is < 3 you must know the last *confirmed* direction — which can be arbitrarily far back, beyond any fixed 3-bar pack. As written, Option A cannot express the rule.
- Determinism *can* be preserved if the vote is redefined as a pure function of a **fixed trailing window** of the OHLCV ending at bar T (i.e. recompute PSAR direction + confirmation over, say, the last K bars every time, K fixed). Then the same history→same vote. But that must be stated explicitly, the lookback K fixed and documented, and partial-history vs full-history behavior pinned by a test.

→ **Redefine PSAR hysteresis as a pure function of a fixed-length trailing window** (deterministic, reproducible), OR drop persistence and use simple **3-bar confirmation with decay-to-zero** in the neutral zone (also pure if computed from a fixed window). Do **not** ship a mutable cross-call state. Add a determinism test: same OHLCV slice → same vote, run twice.

### R.4 Medium issues

**M1 — Horizon mismatch: IC at 5 bars, trades held up to 20 bars.** The system's time-stop is `max_holding_bars = 20`. A 5-day-forward IC can be positive while the 20-day IC (the horizon you actually trade) is flat or negative — trend vs mean-reversion crossover is exactly this. Measure IC at the **holding horizon** (and ideally a small grid: 5/10/20) and gate on the horizon the vote is traded at.

**M2 — 5-symbol basket is too small *and* internally inconsistent *and* survivorship-biased.**
- Step 5 says "4 symbols," Step 6 says 5 (`NVDA, PG, XOM, PLTR, SPY`). Pick one; the AC references both.
- **PLTR IPO'd Sep 2020** — it does not have "the full 5-year history" the plan assumes, and its early window will trip the same Ichimoku <78-bar path you're testing. The fixture claim is internally impossible.
- Five hand-picked names that all still trade in 2025 is **survivorship-biased** — the design doc itself flagged survivorship bias (notebook 02). A per-symbol time-series IC on 5 survivors is an optimistic estimate. Cross-sectional IC on the real point-in-time universe is the right measurement (ties to B1).

**M3 — Ichimoku cloud vote is ternary ±1/0 with no hysteresis, but PSAR gets it — inconsistent turnover discipline.** Price hugging the cloud edge in a range will flip `ichimoku_cloud` ±1 bar-to-bar, which is precisely the whipsaw M5 was meant to damp. If PSAR needs hysteresis, so does the cloud-cross (arguably more, since price coils around the Kumo in exactly the ranges where trend votes should stand down). Either apply a small confirmation buffer to the cloud vote too, or justify the asymmetry.

**M4 — The 0.85 decorrelation bar is lenient enough to admit ~70%-shared-variance "diversifiers."** ρ = 0.85 ⇒ ρ² ≈ 0.72 shared variance. Two votes that co-move 72% of the time add little independent information (design §C5 dilution). For *intra-family* additions where the goal is genuine breadth, a **0.7** bar is more honest. Also note: Aroon(25) and the ADX gate both derive from directional-movement / rolling high-low extremes; since ADX is now a gate (not a vote), Aroon-vs-ADX won't appear in the vote matrix — but the shared trend-strength mechanism is real. Report Aroon-vs-(ADX level) as an FYI even though ADX isn't a vote.

**M5 — Putting the IC acceptance as a live-data `pytest` assertion (`test_trend_family_ic.py`, integration) will rot.** IC drifts as the cache/history updates; a test that passes at IC=0.006 today can fail at 0.004 next quarter with zero code change → red CI, no bug. **Statistical acceptance belongs in a reviewed artifact at merge, not a standing CI assert.** Emit `extended_trend_ic.json` + surface it at the Step 6 review checkpoint (you already have that checkpoint — lean on it), and make the *pytest* only assert non-degenerate mechanics (finite IC, n_samples adequate, backend=='scipy'), not the edge threshold.

**M6 — Overlapping-window autocorrelation isn't handled anywhere.** Even outside the gate, any IC number you *report* on overlapping 5-day returns overstates precision ~√5×. Report non-overlapping or block-bootstrap CIs in the JSON artifact so a reviewer isn't misled by a tight-looking p-value.

### R.5 Minor / nits

- **N1 — Ichimoku 9/26/52** are the classic daily settings; fine as a default, but note it's a *convention*, not tuned (design's non-goal excludes tuning — good, just say so). Some US-equity practitioners use 20/60/120.
- **N2 — Turnover budget "≤12 flips/year"** for one vote is reasonable, but state whether that's per-vote or the composite's contribution, and confirm it's measured *after* hysteresis on non-overlapping observations.
- **N3 — `psar_direction` raw key vs hysteresis vote**: keep the raw ±1 direction in the panel for auditability, and make the *vote* the derived, windowed quantity — don't overwrite the raw reading.
- **N4 — Persistence keeps PSAR "always ±1" after first signal** — it never returns to neutral in chop, which keeps a stale directional bias precisely when a trend vote should go quiet. Prefer decay-to-zero over last-value-persistence on trend-family votes.

### R.6 Answers to the plan's open decisions

- **PSAR Option A vs B (review checkpoint after Step 3):** neither as written. **Option A is under-specified (B2)** and Option B's "return a series" is a bigger refactor than needed. **Correct move:** define the hysteresis vote as a **pure function of a fixed-K trailing window** computed inside `_compute_trend_ext` (deterministic, no cross-call state, no series-refactor). Pack the *derived* vote input (e.g. `psar_confirmed_direction` over K bars), not a bare `streak_len`. Add a run-twice determinism test.
- **IC gate strength (review checkpoint after Step 6):** as R.3 B1 — swap the raw threshold for an **IC-IR + walk-forward + multiple-testing-corrected significance on the real universe**. This is the checkpoint where the design's R1 actually gets honored.

### R.7 Additional recommendations (prioritized)

1. **Rebuild the acceptance gate (B1).** Metric = IC information ratio `mean(IC)/std(IC)` across walk-forward folds; universe = point-in-time scan universe (hundreds of names), not 5 survivors; horizon = the traded holding horizon (~20 bars, plus a 5/10/20 grid for context); SE = Newey-West or block-bootstrap to kill overlap bias; significance = one-sided with **Benjamini-Hochberg** across the 3 votes; ship-criterion = corrected significant *positive* IC-IR. Keep "cut, don't loosen."
2. **Make PSAR (and Ichimoku) hysteresis a pure fixed-window function (B2, M3).** Preserve determinism; add same-input-twice tests; prefer decay-to-zero over value-persistence.
3. **Fix the basket (M2):** resolve 4-vs-5, drop/replace PLTR for full-history coverage or explicitly test its short-history window, and move the *acceptance* measurement to the real point-in-time universe; keep the small basket only for fast unit smoke tests.
4. **Demote the IC pytest to mechanics-only; gate on the reviewed JSON artifact (M5).** Stops CI rot; keeps the human R1 sign-off.
5. **Tighten the intra-family decorrelation bar to 0.7 (M4)** and report the near-miss pairs with their numbers, not just pass/fail.
6. **Measure IC at the holding horizon (M1)** and record all horizons in the artifact.
7. **Report overlap-corrected CIs (M6)** in `extended_trend_ic.json` so reviewers aren't fooled by tight naïve p-values.

**One-line summary for the approver:** *the build plan is ready; the science isn't — fix the two blockers (a real, walk-forward, multiple-testing-corrected IC gate on the actual universe, and a deterministic fixed-window PSAR vote), and the trend family is good to ship.*

Nothing in this review is trading advice; it evaluates a research/engineering plan.
