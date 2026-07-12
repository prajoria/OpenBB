# Design — A Validated Trading System for the Expanded Confluence Panel

**Tracking:** to be filed as a bd bead + GitHub issue once approved
**Date:** 2026-07-10
**Phase:** 1 (Design) — DRAFT, pending approval
**Related specs:** `2026-07-08-confluence-panel-expansion-design.md` (parent
panel-widening spec), `2026-07-09-bd-luy-trend-family-expansion.md`
(first family PR)
**Author:** Prashant Rajoria (with Claude Code, quant-analyst review)

---

## 1. Frame

The parent spec widens the confluence panel from 14 to ~27 indicators.
The bd-luy plan (and its siblings bd-40v/z43/alj) add votes family-by-
family. But **nothing so far describes the trading system these votes
produce**: what edge it captures, how it earns money, what its risk
profile is, when it should be turned off, and how much capital it can
absorb.

This document defines that system, and then defines the acceptance
criteria in trading terms — Sharpe, drawdown, hit rate, capacity,
regime behavior — rather than in code-mechanics terms. Individual
indicators aren't validated in isolation; the **strategy that consumes
them** is.

---

## 2. The strategy in one paragraph

**Long-only, weekly-rebalanced, cross-sectional trend + confluence.**
Every Friday close, rank the eligible universe by `composite_score`.
Hold the top quartile equal-weighted, flat everything else. Position
size scales inversely with 20-day realized volatility so each position
contributes similar risk. Exit any name that drops out of the top
quartile at the next rebalance or that trips a per-position 8% stop.
Skip weeks where the market regime (SPY 200-DMA + VIX percentile) says
"risk-off." That is the entire system.

Everything else in this spec is either **defining what "composite_score"
means with the extended panel** or **proving that this system, with
extended composite_score, earns a real risk-adjusted return net of
costs**.

---

## 3. Edge — where the money comes from

### 3.1 The market inefficiency

Trend and confluence signals capture **behavioral persistence**:
- Individual investors and slow institutions accumulate winners and
  liquidate losers on a lag (disposition effect, prospect theory —
  Shefrin & Statman 1985, Barberis & Xiong 2009).
- Momentum in equities is one of the most-replicated cross-sectional
  anomalies in academic finance (Jegadeesh & Titman 1993, Asness et al.
  2013 "Value and Momentum Everywhere"). It has decayed but not
  disappeared and it survives net of realistic costs at weekly rebalance
  frequencies at the sizes we're targeting.
- Confluence — requiring **multiple orthogonal signals to agree** —
  captures the observation that the highest-conviction moves show up
  simultaneously in price trend, oscillator momentum, volatility
  compression, and volume flow. Single-family signals have well-known
  false-positive regimes (MACD in chop, RSI in trend). Ensembles
  average those failures out (Breiman 1996; also the basis of why
  boosted tree ensembles dominate factor-model horse races).

### 3.2 Why the extended panel should widen the edge

The classic 14-key panel has three known weaknesses:

1. **Trend family is thin on cross-timeframe agreement.** EMA/MACD/ADX
   are all short-to-medium-window signals. Ichimoku Cloud is a
   multi-timeframe consensus construct (26/52-period displaced averages
   — Hosoda 1969) that catches the "everything agrees" trades trend
   traders live off. Adding it should reduce the false-positive rate
   in chop and raise the hit rate at regime transitions.
2. **Momentum family has no raw rate-of-change reference.** RSI and
   Stoch are both bounded oscillators (their extreme readings persist
   in strong trends and mislead). Adding raw N-day ROC and CCI
   (unbounded, standardized) gives the ensemble a way to say "this is
   materially moving" independent of the oscillator saturation.
3. **Volume family has 50% concentration on any single reading.** OBV
   slope or CMF alone can swing the whole volume multiplier. Adding
   MFI (volume-weighted RSI) and A/D line slope diversifies the
   multiplier, making it a smoother scaling factor and reducing
   single-indicator-blow-up risk.

The extended panel is a **hypothesis**: widening families 1-3 above
will raise the Sharpe of the weekly-rebalanced long-only strategy net
of costs, without materially deepening drawdowns. Section 5 defines
how we test that hypothesis.

### 3.3 Where the edge does **not** come from

- Not from new indicators finding "hidden signals" the market has
  missed. We're using textbook indicators from 1969-1995.
- Not from parameter tuning — every indicator uses its canonical period
  (Aroon-25, Ichimoku 9/26/52, ROC-10/20, MFI-14).
- Not from ML or regime-adaptive weights (those are Phase C, separate).
- Not from beating a benchmark by more than ~1-3% annualized net —
  this is a diversification and risk-adjustment story, not an alpha-
  discovery story.

---

## 4. The trading system, fully specified

Everything below has one purpose: **be executable, so backtest results
translate to live P&L within known slippage bounds**.

### 4.1 Universe

- **Primary:** S&P 500 constituents as of each rebalance date, minus
  the bottom decile by 20-day average dollar volume (removes
  illiquidity artifacts).
- **Development basket for iteration:** PG, XOM, KO, SPY (a
  deliberately momentum-*neutral* set — no headline trend name of the
  era). NVDA is **excluded** from the dev basket to remove the soft
  selection bias flagged in reviewer N4 (indicator/confirmation
  choices made while iterating on NVDA would bake in a hindsight
  optimum the walk-forward cannot undo). All design choices freeze
  before touching the acceptance universe.

### 4.2 Signal

- `composite_score` from `confluence.py`, computed with either
  `PANEL_CLASSIC` or `PANEL_EXTENDED`, weekly at Friday close.
- Preset: `trend_follow` (weights 0.40/0.25/0.20 for trend/mom/vol
  with 0.15 volume multiplier).

### 4.3 Portfolio construction

- **Entry:** at Friday close (executed at next Monday open for
  realism), take the top 25% of the universe by `composite_score`.
- **Sizing:** equal risk-weighted. For each holding, dollar allocation
  ∝ 1 / (20-day realized volatility). Rescale so the portfolio is
  fully invested. Cap any single name at 5% of NAV.
- **Rebalance:** weekly at Friday close. Names dropping out of the
  top quartile are sold; names newly entering are bought.
- **Stops:** per-position hard stop at −8% from cost. **Ablation
  required at acceptance time** (reviewer M8): report metrics with and
  without the stop; ship the version that wins on the paired-IR
  primary. Rationale: with vol-targeted sizing, weekly re-ranking, and
  a regime kill-switch already in place, an 8% hard stop mostly fires
  cross-sectionally on high-beta names during broad selloffs — where
  realized stop slippage dwarfs the §4.5 cost model. If the ablation
  shows the stop hurts net paired IR, drop it. Also: stop monitoring
  is on daily close (not intraday), keeping the whole system on a
  daily-decision cadence.

### 4.4 Regime filter (kill switch)

Do not initiate or hold longs when the market regime is risk-off:
- SPY < 200-day moving average, **AND**
- VIX in top decile of trailing 252-day distribution.

Both conditions required (an "AND" gate — VIX spikes alone don't
close the book if the trend is still up). When risk-off, portfolio
goes to cash / treasuries until both conditions clear.

Rationale (reviewer M3 fix): **beta-drawdown control for a long-only
book, not momentum-crash protection.** The Daniel-Moskowitz 2016
"momentum crash" is a long-SHORT phenomenon (short-loser leg rocketing
on the down→up snap-back). A long-only top-quartile portfolio does not
have that mechanism; its acute risk is plain beta drawdown. The
SPY-200DMA + VIX-decile AND-gate is calibrated to sit out weeks when
both the trend has broken AND fear is extreme — i.e. deep, persistent
drawdown regimes — while staying invested through routine vol spikes.

### 4.5 Cost model

- Commission: 0 (retail zero-commission regime — accurate for 2020+).
- Half-spread: 5 bps per side.
- Slippage: 5 bps per side for names in the top-500 by dollar volume,
  10 bps for the bottom half of the universe.
- Total round-trip cost: **~20-30 bps per rebalance turn**. Applied
  to every buy and every sell in the backtest.

### 4.6 Capacity (educated estimate, not a check)

Reviewer N1: without a market-impact model, capacity cannot be derived
from the cost model in §4.5 alone. Rough estimate using
sqrt-impact `impact ≈ σ·√(order/ADV)` on the top-500 dollar-volume
tier: at ~$500M-$2B AUM, per-name orders (5% cap = $25-100M) are
~0.5-3% of ADV, giving 5-15 bps expected impact — comparable to the
§4.5 slippage assumption. **This is an educated guess, not a
capacity check.** Well beyond realistic individual or small-firm
deployment either way.

---

## 5. Acceptance — how we know it works

Two runs of the **same strategy on the same dates and same universe**;
only the composite-score panel differs:

```text
Baseline:  PANEL_CLASSIC  → composite_score → weekly rank → weekly return r_base,t
Extended:  PANEL_EXTENDED → composite_score → weekly rank → weekly return r_ext,t
Spread:    d_t = r_ext,t − r_base,t   ← THIS is what we test
```

Because both runs share universe, rules, dates, and ~most trades, their
weekly return series are 0.9+ correlated. Comparing marginal DSRs and
taking a delta discards that pairing and has weak power. **The
acceptance test is a paired test on the spread series `d_t`**
(equivalently: the self-financing long-extended / short-baseline
overlay). This is B1 in §12.3.

Both runs walked forward: 15 folds, 12-month train / **3-month slide /
3-month OOS test (non-overlapping)** — see §5.5. Pooled out-of-sample
`d_t` is the object of comparison.

### 5.1 Ship gate (mandatory + secondary)

**Mandatory — ALL must pass to ship at all:**

| # | Metric | Threshold | Why |
|---|---|---|---|
| **P** | **Paired spread information ratio** on `d_t`, tested by paired stationary block bootstrap (block=20, ≥ 2000 draws) | **IR ≥ 0.5 AND paired-bootstrap p < 0.05** | The primary edge test (B1). Directly measures whether extended earns *incremental* risk-adjusted return over baseline. |
| **N** | **Null-model PBO** (§5.4) | Observed IR of `d_t` exceeds the 95th pct of the shuffled-vote null | Guards against random-walk luck (Bailey / López de Prado 2014). |
| **B** | **External benchmark** (§5.3) | Extended net Sharpe ≥ **MTUM / naïve top-quartile 12-1 momentum** net Sharpe, at 1.0× and 1.5× costs | Guards against B2 — beating classic but losing to a $15-bps ETF. |
| **U** | **Point-in-time universe test passes** (§5.6) | Regression test on known 2021 deletion is absent from 2022 panel | B3 — no acceptance run is trustworthy on a survivorship-inflated universe. |
| **D** | **Deflated Sharpe** with pre-registered trial count `N=20` (§5.5) | Extended DSR > 0 AND Extended DSR ≥ Baseline DSR | The "did the paired lift survive the honest multiple-testing penalty" check. |

**Secondary — supporting diagnostics; report all, require majority to pass:**

| # | Metric | Threshold | Why |
|---|---|---|---|
| S1 | Max drawdown delta | MaxDD_ext ≤ MaxDD_base × 1.10 | Positive Sharpe with a materially deeper trough is not a win. |
| S2 | Hit rate **on the spread `d_t`**, not the book | Extended positive-week rate on `d_t` ≥ 52% | Reviewer M6: book hit rate is dominated by market beta, useless as discriminator. Spread hit rate isn't. |
| S3 | Absolute turnover **and cost robustness** | Paired IR remains positive at 1.5× and 2× the §4.5 cost model | Reviewer N2 — a relative-turnover band alone doesn't say the edge survives realistic frictions. |
| S4 | Regime split (bull / bear / high-vol / low-vol) | **Report** per-regime paired IR + SE; **soft-tell only:** no single regime > 60% of pooled paired IR | Reviewer M4 — 15 fold-quarters put ~1-2 bear-vol episodes in sample; a hard per-regime gate is under-powered. Kept as a "single-regime dominance" diagnostic instead. |

**Ship rule:**
- **Flag-on default:** ALL 5 mandatory pass AND ≥ 3 of 4 secondary pass.
- **Flag-off (opt-in):** ALL 5 mandatory pass AND ≤ 2 of 4 secondary pass.
- **Do not ship:** any mandatory fails.

This directly answers reviewer M1 — paired-DSR-lift (metric P) is
NECESSARY; the previously-elevated other metrics are secondary.

### 5.2 What the paired test looks like in code

Pseudo-code (harness lives in a new module; not in `techtrade`'s public
API to preserve the AGPL boundary per N7):

```python
# per fold, on OOS test window:
r_base = simulate(strategy, panel=PANEL_CLASSIC,  universe=pit_universe(dates), costs=CM)
r_ext  = simulate(strategy, panel=PANEL_EXTENDED, universe=pit_universe(dates), costs=CM)
d      = r_ext - r_base  # aligned on dates

# after pooling d across folds (non-overlapping, §5.5):
ir_hat     = mean(d) / std(d) * sqrt(52)         # weekly → annualized
ir_boot    = stationary_bootstrap(d, block=20, draws=2000)
p_paired   = (ir_boot <= 0).mean()               # H0: paired IR ≤ 0
```

### 5.3 External benchmarks (mandatory panel)

The Extended run must beat, on the same pooled-OOS window, net of costs:

- **SPY** (buy-and-hold, no rebalancing costs) — the "did any of this
  beat sitting on the index" floor.
- **MTUM** (iShares USA Momentum ETF, ~15 bps expense) — the cheap
  factor replication that Extended must justify complexity against.
- **Naïve equal-weight top-quartile 12-1 momentum** on the same
  point-in-time universe — the "no-confluence" baseline. Composite
  ranking must beat plain past-return ranking, or the ensemble adds
  no value beyond raw momentum.

Report Sharpe, DSR, max-DD, and turnover for all four (Baseline
composite + Extended composite + MTUM + naïve momentum) in one table.
Mandatory metric B in §5.1 says: **Extended ≥ MTUM AND Extended ≥
naïve momentum, at 1.0× and 1.5× costs.**

### 5.4 The null model

Paired PBO null (Bailey / López de Prado 2014, adapted for the paired
test in §5.1):

1. Take the extended-only vote stream (the votes present in Extended
   but absent from Classic).
2. Circular-shift its time index by a stationary block bootstrap
   (block = 20 bars, matching autocorrelation length). Preserves
   cross-vote correlation *structure* within a block; destroys signal
   timing. Reviewer N5 flag: this is a "timing null," not a "family is
   noise" null — labeled as such.
3. Rebuild composite with shuffled extended votes; re-simulate; recompute
   `d_t` and paired IR.
4. Repeat **≥ 2000 draws** (reviewer N5). Report bootstrap SE of the
   95th-percentile threshold.
5. Ship threshold: observed paired IR > 95th percentile of null IRs.

### 5.5 Fold geometry and pre-registered `N`

Reviewer M7 fix: **non-overlapping OOS test blocks.** 15 folds, 12-month
train / **3-month slide / 3-month OOS test**. Consecutive OOS windows
are adjacent but do not overlap; pooled `n` is honest.

What is being "fit" in the 12-month train window? **Nothing.** The
strategy has no free parameters (canonical indicator periods, fixed
`ConfluenceWeights`, textbook regime thresholds). The train window
exists solely to (a) burn in the indicator lookbacks (Ichimoku needs
52 + 26 = 78 bars minimum) and (b) demonstrate the strategy would have
been *runnable* one year before the OOS window. Stated explicitly so
future readers don't infer in-sample parameter estimation that isn't
happening.

**Pre-registered trial count for DSR deflation:** `N = 20`, covering
`{bd-luy, bd-40v, bd-z43, bd-alj}` × `{classic, extended}` × room for
a few confirmation-bar variants (Ichimoku 2/3/5-bar). Fixed **before**
running any acceptance run and used in every family's DSR going forward.
Reviewer M2 fix.

### 5.6 Point-in-time universe (Layer 0, blocks acceptance)

`fmp_cached.index_constituents` returns *current* S&P 500 membership
plus a `historical=True` add/remove change-log, **not** a point-in-time
membership panel (verified in `models/index_constituents.py`).
Reconstructing membership as-of date T is non-trivial and known to be
incomplete deep in history (reviewer B3). **Until a tested
point-in-time universe builder exists, the acceptance run cannot be
trusted.**

Layer-0 deliverable (blocks all acceptance runs):

1. `pit_universe(as_of: date) → list[str]` — reconstructs S&P 500
   membership as of the given date from the change-log.
2. Unit test: a known 2021 deletion (e.g. a company delisted mid-2021)
   is **present** in the 2020-12 panel and **absent** from the 2022-01
   panel. R7.11 mutation-verified: flipping the `>=` to `>` on the
   change-log filter must make the test fail.
3. Sanity test: len(pit_universe) ∈ [450, 550] for every quarter-end
   from 2015-01 through today (S&P 500 rarely deviates from 500 by
   more than 10).
4. Coverage limitation stated: acceptance runs are limited to
   `start_date ≥ 2015-01-01` unless a manual audit confirms deeper
   coverage. Metric M5 (single-macro-epoch limitation) accepted as a
   known constraint of this data, not a hidden risk.

### 5.7 Per-signal IC — kept as diagnostic, not a gate

Individual-vote IC (Grinold cross-sectional, IC-IR, BH-corrected p,
block-bootstrap CI, regime breakdown) is still computed and written
alongside the strategy stats. Diagnostic uses:
- Which of the new votes contributes most / least individually?
- Are any votes so highly correlated (|ρ| > 0.85) with existing votes
  that removing them wouldn't hurt strategy stats?
- Are there votes with **negative individual IC that still add lift**?
  (Hedging signals — anti-correlated errors. These are gold when found;
  a per-signal gate would have discarded them.)

Reviewers use per-signal IC to understand the system, not to gate it.

---

## 6. Risk profile at the strategy level

What a trader / portfolio manager needs to know before running this:

- **Volatility:** target 15-18% annualized (S&P 500-adjacent, no leverage).
- **Beta to SPY:** ~0.9 (long-only equity, cross-sectional not market-
  neutral, will move with the tape).
- **Expected drawdowns:** peak-to-trough 15-25% in a typical regime
  transition (momentum crashes are the acute risk). §4.4 regime filter
  is expected to cut the worst of this — that's the specific
  hypothesis it embodies.
- **Turnover:** ~200-400% per year (weekly rebalance, ~20% names
  changing per week is typical for cross-sectional momentum at this
  cadence).
- **Correlation to standard factors (Fama-French 5):** expect ~0.5-0.7
  loading on Momentum (WML), some negative loading on Value (HML). We
  don't hedge these — the strategy IS a momentum tilt.
- **Failure modes:**
  1. **Deep beta drawdown** during a sustained bear tape. The regime
     filter (§4.4) is designed to cut this — reviewer M3-corrected
     rationale (this is beta control, not the long-short momentum-crash
     mechanism from Daniel-Moskowitz 2016).
  2. **Extended chop** where trend signals whipsaw. Confluence
     requirement helps but doesn't eliminate.
  3. **Sector concentration** — momentum ends up owning whatever's
     been running (Tech in 2020, Energy in 2022). The 5% single-name
     cap does not prevent sector concentration. Accept or add a
     sector-cap follow-up (§8).
  4. **Single-epoch backtest optimism.** 2015-2025 is ZIRP→hiking + a
     historic tech/momentum run + one COVID shock. Walk-forward makes
     the test statistically OOS but not *economically* OOS across
     regimes (reviewer M5). Extending pre-2015 blocked by the §5.6
     point-in-time universe coverage constraint; stated as a known
     limitation on the DSR claim.

---

## 7. Impact on bd-luy Step 5 (the immediate use case)

The bd-luy plan currently specifies Step 5 as per-signal IC harnesses
for Aroon and Ichimoku individually. Under this proposal:

- **Steps 1-4 execute as planned.** Aroon (Step 1) is shipped. Ichimoku
  Cloud with 3-bar confirmation (Step 2) is next. Pass-through subset
  semantics (Step 3, fixes the 14 currently-failing bd-7ct tests) and
  correlation report (Step 4) are all Layer-1 mechanics — they stay.
- **New Step 0 (BLOCKS all acceptance runs):** build + test the
  point-in-time universe (§5.6). Ships as its own PR before Step 5
  can run. Reviewer B3.
- **Step 5 is replaced with the §5 acceptance runs above** — paired
  test on `d_t`, external benchmark panel (SPY / MTUM / naïve
  momentum), null-model PBO (≥ 2000 draws), pre-registered `N=20` DSR,
  non-overlapping OOS fold geometry, stop ablation. Ship according to
  the mandatory-plus-secondary rule in §5.1.
- **Individual IC still computed for Aroon and Ichimoku** in the JSON
  artifact for diagnostic visibility (§5.7).
- **Ship gate is trading-system-level, not per-signal.** If Aroon
  individually looks weak but the ensemble improves, the family ships.
  If Aroon individually looks strong but the ensemble doesn't improve
  the paired spread, the family does not ship flag-on by default
  (ships flag-off for further research, provided all 5 mandatory
  metrics pass; otherwise does not ship at all).

---

## 8. Follow-ups (file as beads after family PRs land)

Independent of this gate change, five trader-level improvements
surfaced in the quant review — none are prerequisites for shipping,
but all raise the system's practical value:

1. **`Recommendation.net_expected_r` field.** Expose net-of-cost
   expected return alongside gross. One-day change to `MoverSignal`
   / `Recommendation` shape; documented in notebook 04.
2. **Rolling-IC-weighted family aggregation.** Weight votes within a
   family by trailing 90-day IC. Turns the ensemble into an adaptive
   learner without moving to ML.
3. **Sector-conditional weights.** Utilities is range-heavy; Tech is
   trend-heavy. A sector tag on the `preset` selection routes each
   sector to the composite that historically worked for it.
4. **Signal-disagreement alert.** When family votes strongly disagree
   (trend says +1, momentum says −1), surface it in the notebook as
   a "conflict" marker. The composite score currently averages the
   disagreement and hides it.
5. **SHAP-style per-vote attribution in notebook 04.** For any ranked
   `MoverSignal`, show the marginal contribution of each vote to the
   composite score. Turns the notebook from "rank + vote counts" into
   "rank + why each vote moved it."

A sixth candidate — **sector cap** at the portfolio-construction
layer — is worth considering after we see the first full-universe
backtest and know how bad the concentration actually is.

---

## 9. Open questions

1. **Rebalance frequency.** Weekly is proposed. Daily may over-cost;
   monthly may miss regime turns. Should be a single documented choice,
   not per-PR.
2. **Regime filter parameters (SPY 200-DMA, VIX top-decile).** These
   are hand-picked from Daniel/Moskowitz. Should we search for optimal
   thresholds, or accept the textbook values to avoid overfitting?
   Propose: accept textbook to avoid a free parameter.
3. **How often does the acceptance run get repeated after ship?** Once
   at family-PR merge is the floor. Quarterly regression re-run against
   fresh data is a candidate for a monitoring bead
   (`ensemble-lift-drift-monitor`).
4. **What if a family fails §5.1 4-of-5 but individual IC is strongly
   positive?** Ship flag-off with a public research note, or don't ship?
   Propose: ship flag-off — the infrastructure (feature-flagged extended
   panel, dispatcher, tests) is valuable even when a specific family
   doesn't lift yet.
5. **Execution-timing sensitivity (added per §12 N6).** §4.3 fills at
   Monday open, but Monday open concentrates fills at a systematically
   higher-vol / lower-liquidity window than the Friday-close decision
   point. As part of the first full acceptance run, also simulate
   Monday-VWAP fills (equal-weight across the Monday session) and
   report the paired-IR delta. Diagnostic only — does not gate the
   ship decision. If the delta is material (> 0.2 IR), file a
   follow-up bead to make the fill model configurable and re-run.

---

## 10. Backing references

- Asness, Moskowitz & Pedersen (2013). *Value and Momentum Everywhere*.
  Journal of Finance 68(3).
- Bailey & López de Prado (2014). *The Deflated Sharpe Ratio*. Journal
  of Portfolio Management 40(5).
- Barberis & Xiong (2009). *What Drives the Disposition Effect?*
  Journal of Finance 64(2).
- Breiman (1996). *Bagging Predictors*. Machine Learning 24(2).
- Daniel & Moskowitz (2016). *Momentum Crashes*. Journal of Financial
  Economics 122(2).
- Grinold & Kahn (2000). *Active Portfolio Management* (2nd ed.), Ch. 6.
- Jegadeesh & Titman (1993). *Returns to Buying Winners and Selling
  Losers*. Journal of Finance 48(1).
- López de Prado (2018). *Advances in Financial Machine Learning*,
  Ch. 11-12.
- Shefrin & Statman (1985). *The Disposition to Sell Winners Too Early
  and Ride Losers Too Long*. Journal of Finance 40(3).

---

## 11. Approval checklist

- [ ] Reviewer accepts the trading system in §4 as fully specified
      (universe, entry/exit, sizing, stops-with-ablation, regime
      filter with corrected M3 rationale, cost model, capacity as
      estimate not check).
- [ ] Reviewer accepts the **paired-spread** acceptance test in §5
      with 5 mandatory + 4 secondary metrics, ship-rule as stated.
- [ ] Reviewer accepts the external-benchmark panel in §5.3 (SPY /
      MTUM / naïve momentum) as mandatory.
- [ ] Reviewer accepts the point-in-time universe deliverable (§5.6)
      as blocking bd-luy Step 5 and all future acceptance runs.
- [ ] Reviewer accepts pre-registered `N=20` for DSR deflation (§5.5)
      and non-overlapping 3-month OOS fold geometry.
- [ ] Reviewer accepts per-signal IC demoted to diagnostic (§5.7).
- [ ] Reviewer accepts the same system + acceptance applies to
      bd-40v / bd-z43 / bd-alj family PRs, one run per family, all
      counting toward the pre-registered `N`.
- [ ] Open questions in §9 resolved (concrete choices: weekly
      cadence pending validation, textbook regime params, quarterly
      drift monitor filed as bead, flag-off on 5-mandatory-but-weak
      secondary).
- [ ] 5 follow-up beads in §8 filed after family PRs land.
- [ ] Reviewer §12 blockers B1/B2/B3 all resolved in §5.1-5.6; §13
      resolution matrix reviewed.

---

## 12. Expert review — quant analyst / trader (trading-principles lens)

> Reviewer lens: systematic equity PM + backtest-validation quant. Claims
> checked against the provider layer (`fmp_cached/models/index_constituents.py`),
> the engine (`engine/confluence.py::composite_score`), and the extension's
> backtest wiring (`techtrade/pyproject.toml` → optional `openbb-backtest`
> plugin). **Headline: this is a large, correct step up from per-signal IC
> gating — the framing "validate the strategy, not the indicator" is right,
> and the DSR + PBO + walk-forward + block-bootstrap toolkit is the correct
> one. But as specified, three things will let an overfit or economically
> empty result ship: (B1) the pairing between Baseline and Extended is thrown
> away, (B2) there is no external benchmark so you can win the A/B and still
> lose to a cheap momentum ETF, and (B3) the point-in-time universe you depend
> on does not exist cleanly in the cache and must be reconstructed. Fix those
> before running.**

### 12.1 Verdict

Approve the *architecture* (strategy-level acceptance, DSR/PBO null,
diagnostic-not-gate IC). Do **not** approve the acceptance math as written:
the comparison is mis-specified as unpaired (B1), unbenchmarked (B2), and
rests on a survivorship-free universe the data layer doesn't actually
provide (B3). Two of the five §5.1 metrics are also too noisy at this
sample size to be decisive (M4, M6). Blocking items first.

### 12.2 What this gets right (keep)

- **Reframing to strategy-level validation** — the single most important
  correction over bd-luy. An indicator that ICs well but doesn't move a
  net-of-cost P&L is noise with a p-value.
- **DSR + PBO null + walk-forward + block bootstrap** is the right stack
  and directly answers the bd-luy critique. §5.2's block-bootstrap PBO is
  exactly the guard the parent design's R1 asked for.
- **§5.3 keeping negative-individual-IC-but-adds-lift "hedging" votes** is
  genuinely sophisticated and correct — a per-signal gate would throw away
  anti-correlated-error diversifiers, which are the most valuable ensemble
  members. Do not lose this.
- **Honest §3.3 "where the edge does NOT come from"** and canonical-period
  discipline (no tuning) are real degrees-of-freedom control.
- **Explicit cost model, capacity note, failure modes, factor loadings** —
  this reads like a trading system, not a code feature.

### 12.3 Blocking issues

**B1 — Baseline and Extended are the SAME strategy on the SAME dates; test the *paired difference*, not two marginal Sharpes.**
The two runs share universe, rules, dates, and ~all of their trades —
their weekly return series will be 0.9+ correlated. Comparing marginal
DSRs (metric 1) and taking a delta discards that pairing and is far less
powerful; worse, "DSR delta ≥ 0.15" has no derivation for the SE of a
*difference of two highly-correlated DSRs*. The correct object is the
**spread return series** `d_t = r_ext,t − r_base,t` (equivalently, the
self-financing long-extended / short-baseline overlay). Test whether
`mean(d_t) > 0` with a paired stationary/block bootstrap on `d_t`, and
report the information ratio of the spread. This both raises power and
gives an economically interpretable answer ("the extended overlay earns
X bps/yr net at Y IR"). As written, the delta-of-DSRs is likely to be
*inside* the noise of either DSR alone.

**B2 — No external benchmark. You can pass the internal A/B and still be
strictly worse than MTUM / a naïve 12-1 momentum / SPY.**
§6 admits a 0.5-0.7 WML loading — most of the return is the momentum
factor, buyable at ~15 bps in an ETF. The acceptance test only compares
extended-vs-classic *composite*; it never asks "does the whole apparatus
beat the cheap replication of its own dominant factor, net of costs and
turnover?" Add a mandatory external-benchmark panel: SPY, MTUM (or the
academic 12-1 UMD long-only top-quintile), and an equal-weight top-quartile
"no-confluence" momentum. If the confluence machine doesn't beat naïve
momentum net, the extra complexity isn't justified regardless of the
internal lift.

**B3 — The survivorship-free universe in §4.1 does not exist cleanly in
the cache; it must be *reconstructed*, and that's a build task with real
error bars.**
`fmp_cached`'s `index_constituents` returns *current* S&P 500 membership
plus a `historical=True` flag that yields an **add/remove change-log**, not
a point-in-time membership panel (verified in
`models/index_constituents.py`). Reconstructing "constituents as of date T"
from that change-log is (a) non-trivial, (b) known to be incomplete in
FMP's history the further back you go, and (c) the single biggest
integrity risk to the entire backtest — get it wrong and every DSR in this
doc is survivorship-inflated fiction. This must be an explicit,
tested Layer-0 deliverable ("point-in-time universe builder + a test that
a known 2021 deletion is absent from the 2022 panel"), not an assumption.
Until it exists, the acceptance run cannot be trusted.

### 12.4 Medium issues

**M1 — "4 of 5 pass to ship" lets the strategy ship with the DSR gate
FAILING.** Metric 1 is described as "the one number that captures" the
whole thesis — yet the 4-of-5 rule makes it optional. A run can ship on
hit-rate + turnover + drawdown + regime while risk-adjusted return did not
improve. Make **DSR-lift (properly paired, per B1) a NECESSARY condition**;
let the other four be supporting/secondary. "4 of the 4 secondary metrics"
is fine; the primary must be mandatory.

**M2 — DSR trial count `N` is never specified, so the deflation is
unquantified.** DSR's whole job is to penalize the number of configurations
tried. Across bd-luy/40v/z43/alj (4 families), ×(classic/extended)
×(any variant confirmation-bar choices) ×(preset), the effective `N` is
easily 8-20+. Pre-register `N` for the whole research program *before*
running, and use that `N` in every family's DSR. An unstated `N`
(implicitly 1-2) under-deflates massively and is the classic silent
overfit.

**M3 — "Momentum crash / Daniel-Moskowitz" rationale is mis-applied to a
long-only book.** The regime filter (§4.4) and failure-mode 1 (§6) cite
Daniel-Moskowitz 2016, but that crash mechanism is a **long-SHORT**
phenomenon — the short-loser leg rockets on the down→up snap-back. A
long-only top-quartile portfolio does **not** have that mechanism; its
acute risk is plain beta drawdown, not a WML crash. The AND-gate filter
may still help (cuts beta in deep drawdowns) but the stated economic
justification is wrong, and the filter is calibrated to catch a risk this
strategy structurally doesn't run. Re-justify the filter as beta/drawdown
control, or reconsider its parameters for that actual purpose.

**M4 — Regime-robustness gate (metric 5) is under-powered on 2020-2025.**
There are ~1-2 bear-vol episodes in the sample (COVID Mar-2020, 2022).
"DSR in the bear-vol regime" is then estimated on ~10-30 weeks → enormous
SE. Requiring "≥3 of 4 regimes" and *tying flag-on to 5/5* makes the
noisiest metric decisive for the highest-stakes decision. Either widen the
sample pre-2020 (if history allows), or downgrade metric 5 to a reported
diagnostic with a soft "no single regime contributes >X% of pooled DSR"
tell rather than a hard per-regime DSR gate.

**M5 — The whole test lives inside one macro epoch.** 2020-2025 is ZIRP→
hiking + a historic momentum/tech run + one COVID shock. Walk-forward makes
it statistically OOS but not *economically* OOS — every momentum system
looks good in this window. State this limitation explicitly and temper the
DSR claim; ideally extend the sample back to 2010 or earlier to include a
momentum-hostile stretch (2016 value rotation, 2009 low-quality rip).

**M6 — Weekly-portfolio hit rate (metric 3) is dominated by market
direction, not signal edge.** A beta-0.9 long-only book is "up" whenever
the market is up (~56-58% of weeks) almost regardless of which composite
ranks names. So classic and extended will show near-identical weekly hit
rates by construction, making metric 3 a weak discriminator. Measure hit
rate on the **spread** `d_t` (B1) or on the top-minus-bottom-quartile
long-short, where signal quality actually shows up.

**M7 — Fold geometry is internally inconsistent / overlapping.** "15 folds,
12m train / 1m slide / 3m OOS test" with "test windows never overlap
within a fold" — a 1-month slide with a 3-month test window means
consecutive folds' test windows overlap by 2 months, so the pooled OOS
equity curve double-counts ~2/3 of its observations, inflating `n` and
understating variance in every downstream statistic. Either use
non-overlapping 3-month test blocks (slide = 3m) or explicitly de-weight
overlapped observations in the pooled statistics. Also: what is being
*fitted* on the 12-month train window? The strategy has no free
parameters (canonical periods, fixed weights, textbook regime thresholds).
If nothing is estimated in-sample, the train/test split is ceremonial and
the real DOF being controlled is the cross-program `N` (M2), which the
walk-forward does not address. Say which it is.

**M8 — The −8% hard stop is redundant with, and worse than, the tools
already present.** You already (a) vol-target position size ∝ 1/σ and
(b) re-rank weekly and (c) run a regime kill-switch. An 8%-from-cost stop
on top of that mostly fires on high-beta names during broad selloffs —
i.e. cross-sectionally, all at once, in exactly the fast-down tape where
realized stop slippage dwarfs the 10 bps cost model (§4.5 has no fast-market
stop-slippage term). It also injects intraweek path-dependence into an
otherwise weekly-close system, forcing daily-low stop monitoring the
backtest must model honestly (close-breach vs intraday-breach differ
materially). Recommend: drop the hard stop, or justify it with a
stop-on/stop-off ablation and a fast-market slippage term.

### 12.5 Minor / nits

- **N1 — Capacity ($500M-2B) is asserted with no market-impact model.** §4.5
  has no size-dependent impact term, so §4.6 can't be derived from it. Either
  add a sqrt-impact term (impact ∝ σ·√(order/ADV)) or label capacity an
  educated guess, not a check.
- **N2 — Absolute turnover/cost breakeven is missing.** Metric 4 gates
  *relative* turnover (ext within 0.7-1.3× base) but never checks that
  absolute turnover × cost leaves the 1-3% edge intact. Cross-sectional
  momentum at weekly cadence often churns 400-800%/yr, not the 200-400%
  in §6. Add a cost-stress: does the lift survive 1.5× and 2× assumed
  costs? If it dies at 1.5×, it isn't robust.
- **N3 — Panel count drift.** "14 → ~27 indicators" here vs "14→31 keys /
  7→20 votes" in the parent spec. Reconcile keys-vs-votes-vs-indicators so
  the DSR `N` and the decorrelation accounting refer to the same objects.
- **N4 — Development basket includes NVDA**, the single best trend name of
  the era. Indicator/confirmation choices made while iterating on that
  basket are a soft selection bias the walk-forward cannot undo (choices
  precede the split). Prefer a neutral or randomly-drawn dev basket, and
  freeze all design choices before touching the acceptance universe.
- **N5 — Null model shuffles one family's votes**, which also destroys that
  family's *cross-vote* correlation structure inside the ensemble, not just
  its timing — so §5.2 tests a slightly different null than "this family is
  noise." Acceptable, but state it; and 1000 shuffles for a 95th-pct tail is
  thin — use ≥2000 and report the bootstrap SE of the percentile.
- **N6 — Monday-open execution concentrates fills** at a systematically
  higher-vol / lower-liquidity window than the Friday-close decision;
  a small execution-timing sensitivity (Mon open vs Mon VWAP) would bound it.
- **N7 — `openbb-backtest` is an optional AGPL extra** (verified in
  `pyproject.toml`); the confluence `SignalStrategy` plugin exists but the
  walk-forward / DSR / PBO harness in §5 is net-new code. Scope it as such
  and keep the AGPL boundary clean (techtrade must still import without it).

### 12.6 Answers to §9 open questions

1. **Rebalance frequency:** weekly is defensible, but the choice interacts
   with turnover/cost (N2) and should be *validated*, not assumed — run the
   acceptance at weekly and monthly once and pick on net-of-cost paired IR
   (B1). Don't leave it as a free knob per family.
2. **Regime parameters:** accept textbook (your proposal) — correct, adding a
   free parameter here would be self-inflicted overfit. But re-derive *why*
   those params for a long-only book (M3), since the Daniel-Moskowitz
   justification doesn't transfer.
3. **Re-run cadence after ship:** once at merge is the floor; the quarterly
   `ensemble-lift-drift-monitor` bead is the right call — file it, and have
   it emit the paired spread IR (B1), not just re-print the DSR.
4. **Fail 4-of-5 but strong individual IC:** ship flag-off (your proposal) —
   agreed, *provided* per-signal IC is explicitly labeled diagnostic (§5.3)
   and the research note states it did not lift the net-of-cost paired spread.

### 12.7 Recommendations (prioritized)

1. **Make the acceptance a PAIRED test on the spread series** `r_ext − r_base`
   (B1): paired block bootstrap on `d_t`, report spread IR and net bps/yr.
   This is the biggest power + interpretability upgrade available.
2. **Add mandatory external benchmarks** (B2): SPY, MTUM/UMD, naïve
   equal-weight top-quartile momentum. Ship only if the system beats naïve
   momentum net.
3. **Build + test a point-in-time universe** from the constituent change-log
   before any acceptance run (B3); add a regression test on a known
   add/remove event.
4. **Make paired DSR-lift a NECESSARY ship condition** (M1); demote the other
   four to supporting.
5. **Pre-register the cross-program trial count `N`** and use it in every
   family's DSR (M2).
6. **Fix fold geometry to non-overlapping OOS blocks** and state what (if
   anything) is fit in-sample (M7).
7. **Re-justify or re-parameterize the regime filter for long-only beta
   control** (M3); **ablate the −8% stop** (M8).
8. **Add a cost-stress (1.5×/2×) and absolute-turnover breakeven** (N2), and
   an impact-based capacity number (N1).
9. **Extend the sample pre-2020 if data allows**, and label the single-epoch
   limitation loudly (M5); measure hit rate on the spread, not the book (M6).

**One-line summary for the approver:** *the philosophy and toolkit are right
and a real advance over per-signal IC — but as written you're running an
unpaired, unbenchmarked A/B on a universe the data layer can't yet build
survivorship-free; make the test paired, benchmark it against a cheap
momentum ETF, and build the point-in-time universe first, then this becomes
a genuinely trustworthy ship gate.*

Nothing here is investment advice; it evaluates a research/engineering
design.

---

## 13. Resolution matrix — §12 review items

Each row: reviewer item → resolution in this spec → status.

| # | Item | Resolution | Status |
|---|---|---|---|
| **B1** | Paired A/B, not marginal Sharpes | §5 rewrites the acceptance around `d_t = r_ext − r_base` with paired block-bootstrap on IR; mandatory metric P | **Resolved** |
| **B2** | External benchmark (SPY / MTUM / naïve momentum) | §5.3 mandatory panel; ship gate metric B requires beating MTUM AND naïve momentum at 1.0× and 1.5× costs | **Resolved** |
| **B3** | Point-in-time universe doesn't exist in the cache | §5.6 Layer-0 deliverable with R7.11 mutation-verified test; new Step 0 in bd-luy (§7) blocks acceptance until it ships | **Resolved** |
| **M1** | DSR must be necessary, not one-of-five | §5.1 mandatory P/N/B/U/D — all required; secondary S1-S4 are supporting only | **Resolved** |
| **M2** | Pre-register DSR trial count `N` | §5.5 `N=20` fixed before any acceptance run; documented allocation across families/variants | **Resolved** |
| **M3** | Regime-filter rationale mis-applied to long-only | §4.4 rewritten as beta-drawdown control, not Daniel-Moskowitz momentum-crash; §6 failure mode 1 updated | **Resolved** |
| **M4** | Regime robustness under-powered | §5.1 S4 downgraded to a diagnostic ("no single regime > 60% of pooled paired IR"); no hard per-regime gate | **Resolved** |
| **M5** | Single macro-epoch limitation | §6 failure mode 4 states it loudly; §5.6 sets 2015-01 floor from data-coverage side | **Resolved (acknowledged)** |
| **M6** | Hit rate on the book is beta-dominated | §5.1 S2 measures hit rate on the spread `d_t`, not the book | **Resolved** |
| **M7** | Fold geometry overlapping / unclear in-sample fit | §5.5 non-overlapping 3-month OOS blocks; explicit "nothing is fitted in the 12-month train, it exists for indicator burn-in only" | **Resolved** |
| **M8** | −8% stop redundant with vol-target + regime filter | §4.3 stop is now ablation-required at acceptance; ship the version that wins on paired IR | **Resolved** |
| **N1** | Capacity has no impact model | §4.6 rewritten as sqrt-impact educated estimate, explicitly labeled not-a-check | **Resolved** |
| **N2** | Absolute turnover / cost stress missing | §5.1 S3 requires paired IR to survive 1.5× and 2× cost model | **Resolved** |
| **N3** | Panel count drift (27 vs 31 indicators / 20 votes) | To reconcile in a follow-up edit to the parent spec; not blocking here (this doc uses "extended panel" as an object, not a count) | **Deferred to parent-spec edit** |
| **N4** | Dev basket includes NVDA (soft selection bias) | §4.1 dev basket changed to PG/XOM/KO/SPY; NVDA excluded | **Resolved** |
| **N5** | 1000 null draws too thin; label the null | §5.4 raises to ≥ 2000 draws with bootstrap SE reported; explicitly labeled "timing null within a block" | **Resolved** |
| **N6** | Monday-open concentration | §9 open question 5 (new): run a Mon-open vs Mon-VWAP execution sensitivity as part of first acceptance run; report only, don't gate | **Accepted as diagnostic** |
| **N7** | `openbb-backtest` AGPL boundary | §5.2 explicitly notes the walk-forward / DSR / PBO harness lives in a new module outside `techtrade`'s import surface | **Resolved** |
| §9 Q1 | Rebalance frequency | Weekly + monthly run once at first acceptance; pick on paired IR net of costs | **Accepted** |
| §9 Q2 | Regime params source | Textbook (no free knob); rationale re-derived per M3 | **Accepted** |
| §9 Q3 | Post-ship re-run cadence | Quarterly `ensemble-lift-drift-monitor` bead, emits paired spread IR | **Accepted (to file)** |
| §9 Q4 | 5-mandatory-pass + weak secondary | Ship flag-off; per-signal IC labeled diagnostic; research note published | **Accepted** |

**Bottom line:** every blocker (B1/B2/B3) is resolved inline in §5;
all 8 mediums resolved or explicitly acknowledged (M5); 6 of 7 minors
resolved, N3 deferred to a parent-spec reconciliation edit. The
one-line summary from §12 — "make the test paired, benchmark it
against a cheap momentum ETF, and build the point-in-time universe
first" — is now literally what §5.1 requires.
