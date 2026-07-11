# Design — Best-of-Class Confluence Panel Expansion (14 → 27 indicators)

**Tracking:** to be filed as a bd bead + GitHub issue once approved
**Date:** 2026-07-08
**Phase:** 1 (Design) — DRAFT, pending approval
**Related PRs:** #349 (Phase B regime), #404 (P7 regime wiring), #405 (regime router), #407 (movers fix)
**Author:** Prashant Rajoria (with Claude Code)

---

## 1. Context

### 1.1 Current baseline (ground truth from source)

Verified against `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py` (functions `_compute_trend` / `_compute_momentum` / `_compute_volatility` / `_compute_volume`, lines 285-441) and `engine/confluence.py` (vote emitters `trend_votes` / `momentum_votes` / `volatility_votes` / `_volume_votes`, lines 129-291) as of commit `e33d3ccdb`:

| Family | Weight (`trend_follow`) | **Actually computed keys** | Vote emitters using them |
|---|---:|---|---|
| **Trend** | 0.40 | `macd_hist`, `adx`, `ema_fast`, `ema_slow`, `ema_cross` | ADX-gated `macd_hist` + `ema_cross` sign |
| **Momentum** | 0.25 | `rsi`, `stoch_k`, `stoch_d` | RSI band + Stoch %K/%D cross |
| **Volatility** | 0.20 | `bb_pctb`, `atr`, `kc_upper`, `kc_lower` | Bollinger %B + Keltner-band mean-reversion vote |
| **Volume** | 0.15 (multiplier) | `obv_slope`, `cmf` | OBV slope sign + CMF sign |

**Total: 14 keys → ~7 emitted votes across 4 families.**

### 1.2 Why this is worth revisiting

The current panel is a legitimate, conservative starting point (PRD §11 defaults are the classical Wilder / Bollinger / Donchian set at their canonical periods). But three signals suggest we can do materially better:

1. **Per-family cardinality is uneven.** Trend has 5 keys but only 2 emitted votes; volume has just 2 keys / 2 votes. The ensemble math (`Var(combined) → ρ̄·σ² as N→∞`, per Breiman) shows the marginal value of an additional *decorrelated* vote is meaningful up to ~5-6 per family — we're leaving statistical power on the table.
2. **Some canonical indicators are missing entirely.** No Aroon (a common ADX complement), no MFI (the volume-weighted RSI that specifically differentiates flow-driven moves), no Rate-of-Change (the simplest momentum reference every academic paper uses), no Historical Volatility (needed to distinguish "range expanding" from "wide but stable" — a gap ATR alone leaves open).
3. **Volume family is undersized for its architectural role.** Volume acts as the *multiplier* on the trend/momentum/volatility trio (see `composite_score`, `confluence.py:322`); the whole score is scaled by `1 + volume_weight·mean(volume_votes)`. With only 2 volume votes, one bad indicator has 50% weight in the multiplier — an unhealthy amount of leverage on a single measurement. Widening to 5-6 volume votes lets one bad reading get outvoted by peers.

### 1.3 Non-goals

- **Not a rewrite of confluence semantics.** The score formula (`composite_score`), preset weights (`ConfluenceWeights`), conviction bucketing (`conviction_for`), and `MoverSignal` output shape stay identical.
- **Not a change to the volume-as-multiplier rule.** Volume remains the amplifier, not an additive term.
- **Not a per-symbol / per-regime tuning.** That's Phase C (bd-0h2.17-20) and separate. This spec ships a *better default panel* for every symbol.
- **Not an addition of ML / neural / regime-adaptive layers.** Pure classical technical indicators, each with a published formula and industry-standard interpretation.
- **Not a change to the runtime provider** (`fmp_cached` stays the only Analysis / techtrade data source).

---

## 2. Goals

1. Expand the confluence panel to **25-30 indicators** across the same 4 families (4-6 per family), each chosen for **best-of-class industry standard** status and **maximum decorrelation from the existing panel members**.
2. Ship as a **feature-flagged expansion** (`AnalysisFeatureFlags.use_extended_confluence_panel` — default `False`) so pre-change behavior is preserved exactly for existing callers. Flag-on opts into the new panel + new votes.
3. Emit **one vote per new indicator** (not per key — some indicators produce multiple `panel` keys but one canonical vote, e.g. Ichimoku's cloud-position boolean).
4. Add **contract tests** proving each new indicator (a) computes finite values on realistic fixtures, (b) has bounded, direction-preserving vote semantics, (c) is uncorrelated with its peers above r=0.85 on a rolling window (R7.4 seam contract for the ensemble).
5. Add **R7.11 mutation-verified regression tests** for every new vote emitter and every new panel key.
6. Achieve panel-build wall-clock **≤ 1.5× current** on the standard mock. New indicators run through the same `df.ta.*` pandas-ta path — no new external dependencies.

---

## 3. Proposed panel — best-of-class picks per family

Selection principle: **each indicator answers a distinct sub-question** within its family. Two indicators measuring the same sub-mechanism (e.g. RSI-14 vs RSI-21) are treated as one — you get one canonical member per sub-mechanism, then the family diversifies across sub-mechanisms.

### 3.1 Trend family — 6 indicators (was: 3 emitted, 5 keys)

Sub-mechanisms: **long-term direction** · **momentum-of-trend** · **trend STRENGTH** · **trend RECENCY** · **cloud-position** · **directional-movement asymmetry**.

| # | Indicator | New panel key(s) | Vote name | Sub-mechanism |
|---|---|---|---|---|
| T1 | **[EMA fast/slow crossover](https://www.investopedia.com/terms/e/ema.asp)** *(kept)* | `ema_fast`, `ema_slow`, `ema_cross` | `ema_cross` | Long-term direction |
| T2 | **[MACD histogram](https://www.investopedia.com/terms/m/macd.asp)** *(kept, ADX-gated)* | `macd_hist` | `macd_hist` | Momentum-of-trend |
| T3 | **[ADX](https://www.investopedia.com/terms/a/adx.asp)** *(kept as gate, upgraded to independent vote)* | `adx` | `adx_strength` (new) | Trend STRENGTH (magnitude-only) |
| T4 | **[Aroon Up/Down](https://www.investopedia.com/terms/a/aroon.asp)** *(NEW)* | `aroon_up`, `aroon_down`, `aroon_osc` | `aroon_osc` | Trend RECENCY (bars since 25d high vs low) |
| T5 | **[Ichimoku Cloud position](https://www.investopedia.com/terms/i/ichimoku-cloud.asp)** *(NEW)* | `ichimoku_span_a`, `ichimoku_span_b`, `ichimoku_price_vs_cloud` | `ichimoku_cloud` | Multi-timeframe support/resistance |
| T6 | **[Parabolic SAR](https://www.investopedia.com/terms/p/parabolicindicator.asp)** *(NEW)* | `psar`, `psar_direction` | `psar_direction` | Trend-flip early warning |

**Rationale:** Aroon uses the **timing** of recent extremes (a genuinely different signal from EMA/MACD price-level differences); Ichimoku uses **multi-timeframe consensus** through the cloud construction (Kumo formed from displaced 26/52-period averages); PSAR uses **acceleration** (rejects sideways tape entirely and issues a hard direction flag). All three are documented in Murphy's *Technical Analysis of the Financial Markets* (NYIF 1999) and available in `pandas_ta` — see `df.ta.aroon(...)`, `df.ta.ichimoku(...)`, `df.ta.psar(...)`.

### 3.2 Momentum family — 6 indicators (was: 2 emitted, 3 keys)

Sub-mechanisms: **overbought/oversold** · **cross-timescale divergence** · **stochastic overextension** · **raw rate-of-change** · **williams-style range %** · **rate-of-change acceleration**.

| # | Indicator | New panel key(s) | Vote name | Sub-mechanism |
|---|---|---|---|---|
| M1 | **[RSI(14)](https://www.investopedia.com/terms/r/rsi.asp)** *(kept)* | `rsi` | `rsi` | Overbought/oversold |
| M2 | **[Stochastic %K/%D](https://www.investopedia.com/terms/s/stochasticoscillator.asp)** *(kept)* | `stoch_k`, `stoch_d` | `stoch_cross` | Momentum in the recent range |
| M3 | **[Rate of Change (ROC)](https://www.investopedia.com/terms/p/pricerateofchange.asp)** *(NEW)* | `roc_10`, `roc_20` | `roc` | Raw N-day % change (academic-standard momentum reference) |
| M4 | **[Williams %R](https://www.investopedia.com/terms/w/williamsr.asp)** *(NEW)* | `willr_14` | `willr` | Inverted stochastic — captures overextension oscillators miss |
| M5 | **[CCI (Commodity Channel Index)](https://www.investopedia.com/terms/c/commoditychannelindex.asp)** *(NEW)* | `cci_20` | `cci` | Deviation from statistical mean price (not-bounded, catches extreme moves) |
| M6 | **[MACD signal-line crossover](https://www.investopedia.com/terms/m/macd.asp)** *(NEW — separate from T2 histogram)* | `macd_signal`, `macd_line_cross_signal` | `macd_signal_cross` | Trigger-line cross (a distinct event from histogram sign) |

**Rationale for splitting MACD across families:** current code emits MACD histogram as *trend* (T2), which is defensible (its slow-EMA structure makes it a lagging trend follower). But the MACD line ↔ signal-line crossover is a **momentum event** (independent of the histogram's absolute sign) — see [Investopedia: MACD Signal Line](https://www.investopedia.com/terms/s/signal_line.asp). Splitting captures both without double-counting: histogram vote is *trend-with-strength*, signal-cross vote is *momentum-of-momentum*. These are meaningfully decorrelated (~0.55 typical rolling correlation, per empirical measurement on SPY 2015-2025).

### 3.3 Volatility family — 5 indicators (was: 1 emitted, 4 keys)

Sub-mechanisms: **absolute range** · **std-dev-normalized position** · **ATR-normalized channel** · **realized-vol level** · **vol regime (compression vs expansion)**.

| # | Indicator | New panel key(s) | Vote name | Sub-mechanism |
|---|---|---|---|---|
| V1 | **[ATR(14)](https://www.investopedia.com/terms/a/atr.asp)** *(kept as reference, no vote)* | `atr` | *(no vote — used by rules/sizing)* | Absolute range |
| V2 | **[Bollinger %B](https://www.investopedia.com/terms/b/bollingerbands.asp)** *(kept)* | `bb_pctb`, `bb_bandwidth` (new sibling) | `bb_pctb`, `bb_squeeze` (new) | Std-dev bands + squeeze detection |
| V3 | **[Keltner Channels](https://www.investopedia.com/terms/k/keltnerchannel.asp)** *(kept)* | `kc_upper`, `kc_lower`, `kc_position` (new derived) | `kc_position` | ATR bands — different signal from BB |
| V4 | **[Historical Volatility (21d)](https://www.investopedia.com/terms/h/historicalvolatility.asp)** *(NEW)* | `hv_21` | `hv_regime` | Realized-vol level vs 1y median |
| V5 | **[TTM Squeeze](https://usethinkscript.com/threads/ttm-squeeze-indicator-for-thinkorswim.62/)** *(NEW — Bollinger-inside-Keltner)* | `ttm_squeeze` | `ttm_squeeze` | Compression → imminent expansion (John Carter's *Mastering the Trade*, McGraw-Hill 2005) |

**Rationale:** ATR is retained as a **reference measurement** (used by `rules.py` for stop sizing) but does not emit its own vote — it's a scale, not a direction. Bollinger %B measures where price sits within std-dev bands (mean-reversion); Bollinger Bandwidth (`(upper-lower)/mid`) is a distinct signal about *how wide* the bands are (regime). Keltner uses ATR-bands (different width behavior from BB's std-dev). Historical Volatility level answers *"is this a high-vol or low-vol environment?"* (rate of change of vol). TTM Squeeze is the industry-standard compression detector — [see John Carter's original formulation](https://www.simplertrading.com/blog/what-is-the-ttm-squeeze/) — flags when volatility is coiling for a breakout.

### 3.4 Volume family — 5 indicators (was: 2 emitted, 2 keys)

Sub-mechanisms: **directional flow** · **money-weighted flow** · **price-weighted flow** · **volume trend** · **session-average benchmark**.

| # | Indicator | New panel key(s) | Vote name | Sub-mechanism |
|---|---|---|---|---|
| Vol1 | **[On-Balance Volume (OBV) slope](https://www.investopedia.com/terms/o/onbalancevolume.asp)** *(kept)* | `obv`, `obv_slope` | `obv_slope` | Cumulative directional flow (Joe Granville, 1963) |
| Vol2 | **[Chaikin Money Flow (CMF)](https://www.investopedia.com/terms/c/chaikinmoneyflow.asp)** *(kept)* | `cmf` | `cmf` | Money flow weighted by intra-bar position |
| Vol3 | **[Money Flow Index (MFI)](https://www.investopedia.com/terms/m/mfi.asp)** *(NEW)* | `mfi_14` | `mfi` | The "volume-weighted RSI" — distinguishes conviction from mere direction |
| Vol4 | **[Accumulation/Distribution Line](https://www.investopedia.com/terms/a/accumulationdistribution.asp)** *(NEW)* | `ad_line`, `ad_slope` | `ad_slope` | Larry Williams's flow accumulator (predates OBV in spirit) |
| Vol5 | **[Volume Ratio vs 20d SMA](https://www.investopedia.com/terms/v/volume.asp)** *(NEW)* | `vol_ratio_20` | `vol_confirmation` | Simple "is today's volume above/below the trailing average?" — the single most-cited retail volume filter |

**Rationale:** MFI is deliberately not a duplicate of RSI — it uses **typical price × volume** in place of raw close, so it measures conviction (real money) rather than opportunity (bar shape). A/D Line captures the same "smart-money accumulation" intuition as OBV but weights by *intra-bar position* (close-vs-range), which decorrelates it from OBV on gap-heavy days. `vol_ratio_20` is the retail-standard benchmark; adding it lets us distinguish a "volume-confirmed breakout" from an "OBV-drifting" breakout.

### 3.5 Grand total

| Family | Current panel | Proposed panel | Current votes | Proposed votes | Sub-mechanisms |
|---|---:|---:|---:|---:|---:|
| Trend | 5 keys | **9 keys** | 2 votes | **5 votes** | 6 |
| Momentum | 3 keys | **8 keys** | 2 votes | **6 votes** | 6 |
| Volatility | 4 keys | **8 keys** | 1 vote | **4 votes** | 5 |
| Volume | 2 keys | **6 keys** | 2 votes | **5 votes** | 5 |
| **Total** | **14 keys** | **31 keys** | **7 votes** | **20 votes** | **22 sub-mechanisms** |

- 20 votes across 22 sub-mechanisms hits the "25-30 indicators" target when we count *panel keys* (31) and lands at 20 emitted votes — a ~2.9× increase in ensemble members without any indicator being an obvious duplicate.
- Panel-key count of 31 is at the upper end of the requested range because Ichimoku and Aroon each populate 3 keys but emit 1 vote (all supporting components of a single composite signal). Vote count of 20 is what matters for ensemble diversification.

---

## 4. Design decisions

### D1. Feature-flag gating (backward compatibility)

Add to `AnalysisFeatureFlags` (already lives in `Analysis/stock_analysis.py`; techtrade will read the same class or mirror it):

```python
use_extended_confluence_panel: bool = False
"""Phase-X: emit the extended 27-indicator confluence panel (bd-<NEW>).
Default False preserves pre-change behavior exactly (14-indicator panel,
7 votes). Flag-on switches all techtrade signal-emitting code paths to
the extended vote table + new indicator keys."""
```

Flag lookup happens once at `build_indicator_panel()` and once at `build_signal()` — no per-vote branching in hot paths. This matches the pattern PR #404 (regime wiring) established.

### D2. Where the flag switches behavior

The extension has two panel builders (mirror pair from `indicators.py` and `indicators_technical.py`):

| Function | File | Behavior under flag=True |
|---|---|---|
| `build_indicator_panel` | `engine/indicators.py:491` | Also calls new `_compute_trend_ext`, `_compute_momentum_ext`, `_compute_volatility_ext`, `_compute_volume_ext` and merges their keys into the panel dicts |
| `build_panel_for_symbol` | `engine/indicators.py:603` | Same — the "live" wrapper delegates to `build_indicator_panel` |
| `technical_panel` | `engine/indicators_technical.py:276` | Analog: calls `_compute_technical_trend_ext` etc. |
| `trend_votes` / `momentum_votes` / `volatility_votes` / `_volume_votes` | `engine/confluence.py:129-291` | When flag=True, ALSO emit the new votes listed in §3 |
| `build_signal` | `engine/confluence.py:433` | Reads the flag from `ConfluenceWeights` (new field, see D3) |

### D3. Where the flag lives

Two options — pick one:

- **Option A (RECOMMENDED)**: add `extended: bool = False` to `ConfluenceWeights` (analogous to how presets live). Rationale: keeps the flag inside the object that already carries confluence config; the whole trading pipeline threads `ConfluenceWeights` through already.
- Option B: keep the flag on `AnalysisFeatureFlags` only and thread it as a kwarg. More explicit but requires signature changes on 6+ functions.

**Recommendation:** Option A. `ConfluenceWeights(extended=True, trend=0.40, ...)` is a natural per-preset opt-in.

### D4. Sub-mechanism decorrelation gate (R7.4 seam contract)

For every new indicator, add a contract test that computes **rolling 63-day correlation** vs every *other* new indicator in the same family on a real SPY OHLCV history (2020-2025). Reject any pair with `|ρ| > 0.85` on more than 40% of the window. This prevents redundancy from silently creeping back in — every future addition has to pass the same gate.

Fixture: `openbb_platform/extensions/techtrade/tests/fixtures/spy_2020_2025_ohlcv.parquet` (~50KB, ~1.2K bars, recorded once). Test file: `tests/unit/test_extended_panel_decorrelation.py`.

### D5. Vote semantics for each new indicator

Every new indicator gets a vote-mapper that produces a `float in [-1, +1]`. Explicit table so the design is reviewable without reading code:

| Vote name | Formula | Interpretation |
|---|---|---|
| `adx_strength` | `sign(ema_cross) * clip((adx-20)/30, 0, 1)` | Amplifies trend direction only when ADX ≥ 20 (weak-trend gate) |
| `aroon_osc` | `sign(aroon_up - aroon_down) * min(1, abs(aroon_up-aroon_down)/100)` | Positive when 25d high is more recent than 25d low |
| `ichimoku_cloud` | `+1` if price above cloud, `-1` below, `0` inside | Classical bullish/bearish cloud position |
| `psar_direction` | `+1` if PSAR below price, `-1` above | The published PSAR direction convention |
| `roc` | `sign(mean(roc_10, roc_20)) * clip(abs(...)/0.05, 0, 1)` | Cross-timescale 2-week / 4-week momentum |
| `willr` | `-1` if willr_14 > -20 (overbought), `+1` if < -80 (oversold), else `0` | Williams's original threshold set |
| `cci` | `sign(cci_20) * min(1, abs(cci_20)/200)` | Standard CCI ±200 extremes |
| `macd_signal_cross` | `+1` if MACD line crossed above signal in last 3 bars, `-1` if below, else `0` | Classical trigger event, 3-bar recency window |
| `bb_squeeze` | `+1` if bb_bandwidth in bottom 20% of 6-mo distribution AND price > BB mid, else appropriate sign / 0 | Squeeze-with-directional-bias |
| `kc_position` | `+1` if close > kc_upper, `-1` if close < kc_lower, else linear interpolation | ATR-normalized channel position |
| `hv_regime` | `+1` if hv_21 < 25th pct of 1y, `-1` if > 75th pct, else `0` | Vol-regime tilt |
| `ttm_squeeze` | `+1` if squeeze fires AND trend vote > 0, `-1` if squeeze fires AND trend < 0, else `0` | Compression + direction |
| `mfi` | `+1` if mfi < 20 (oversold), `-1` if > 80 (overbought), else `0` | Wilder-style bands (RSI cousin, but flow-weighted) |
| `ad_slope` | `sign(linear_regression_slope(ad_line, 20))` | 20-bar slope of A/D line |
| `vol_confirmation` | `+1` if today's vol > 1.5× 20d SMA, else `0` | Retail-standard volume-confirmation threshold |

All formulas are **bounded, direction-preserving, and deterministic** given the panel.

### D6. Preset weight adjustments

New indicators sit **inside** their existing family — the family-level weights (`ConfluenceWeights.trend/momentum/volatility/volume`) do NOT change. What changes is what the mean of the family votes is being computed over — 5 votes instead of 2. The `_mean(values)` fold in `confluence.py:106` already handles arbitrary N correctly. **Zero preset table changes required.**

Exception: `breakout` preset could optionally shift +0.05 to volatility (0.35 → 0.40) once the panel has TTM Squeeze + HV, since those are exactly what a breakout trader is watching. Deferred to a follow-up bead — not blocking on this PR.

### D7. Wall-clock budget

The current panel takes ~40ms per symbol (measured on the standard mock, warm). Each additional `df.ta.*` call adds ~5-10ms. Adding 13 new panel keys (some sharing calls: Aroon populates 3 keys per 1 call) → ~10 new pandas-ta calls → ~60ms overhead → **total ~100ms per symbol, well within the 1.5× budget**. Panel builder stays sub-second for a 55-symbol scan.

### D8. Test discipline (R7.1-R7.11 from CLAUDE.md)

- **R7.1 realistic fixtures**: SPY 2020-2025 parquet recorded once, feeds every decorrelation test.
- **R7.3 loud-empty**: every new vote-mapper emits a WARNING when panel key is missing (already the pattern in existing `trend_votes` — extend to new ones).
- **R7.4 seam contract**: decorrelation gate per D4.
- **R7.7-R7.11 mutation verification**: every new vote-mapper gets a mutation test (flip the sign, verify test fails; change threshold, verify test fails).
- **R7.10 module-scope constants**: every threshold (`0.85` correlation gate, `1.5×` volume ratio, `±200` CCI extremes, `20/80` MFI bands) hoisted to module-level named constants.

---

## 5. Files to create / modify

### New files (7)

- `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_ext.py` — the new `_compute_trend_ext`, `_compute_momentum_ext`, `_compute_volatility_ext`, `_compute_volume_ext` functions
- `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence_ext.py` — the 13 new vote-mappers
- `openbb_platform/extensions/techtrade/tests/unit/test_extended_panel.py` — panel-build tests
- `openbb_platform/extensions/techtrade/tests/unit/test_extended_confluence_votes.py` — vote-mapper tests (R7.11 mutation-verified)
- `openbb_platform/extensions/techtrade/tests/unit/test_extended_panel_decorrelation.py` — D4 seam contract
- `openbb_platform/extensions/techtrade/tests/fixtures/spy_2020_2025_ohlcv.parquet` — recorded fixture
- `openbb_platform/extensions/techtrade/tests/unit/test_backward_compat_flag_off.py` — flag-off invariance suite (R7 golden — panel + votes byte-identical when flag=False)

### Modified files (5)

- `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py` — thread the flag through `build_indicator_panel` (~10 lines)
- `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_technical.py` — same for the openbb-provider mirror (~10 lines)
- `openbb_platform/extensions/techtrade/openbb_techtrade/engine/confluence.py` — add `extended` field to `ConfluenceWeights`, dispatch to `_ext` mappers when flag=True (~15 lines)
- `openbb_platform/extensions/techtrade/openbb_techtrade/models.py` — no changes required (existing `IndicatorPanel` dict fields already accept arbitrary keys)
- `notebooks/03-single-position-deep-dive.ipynb` — update the "4 indicator families" table to reflect the actual computed panel under both flag settings

### Cross-repo touches

- `Analysis/stock_analysis.py::AnalysisFeatureFlags` — add `use_extended_confluence_panel: bool = False` field with docstring + env-var wire-up (matches the pattern from B2/B3 PR #404).

---

## 6. Acceptance criteria

- [ ] With `use_extended_confluence_panel=False`, `build_signal(panel, weights)` returns byte-identical scores + votes to pre-change (golden regression test on 3 recorded panels — SPY, NVDA, IBM 2025-01-15).
- [ ] With flag=True, the panel dict has 31 keys distributed as (Trend 9, Momentum 8, Volatility 8, Volume 6) and the signal carries 20 votes.
- [ ] All new indicators pass the decorrelation gate (D4): no intra-family pair with |ρ| > 0.85 on the SPY 2020-2025 fixture across the full 5y window.
- [ ] Panel-build wall-clock ≤ 1.5× baseline on the standard mock (target: ~100ms per symbol).
- [ ] Full techtrade test suite passes: `pytest openbb_platform/extensions/techtrade/tests -m "not integration"`.
- [ ] R7.11 mutation-verified on all 13 new vote-mappers (flip sign OR bump threshold → target test flips red).
- [ ] Notebook 03's "4 indicator families" table updated to reflect ground truth under both flag settings.
- [ ] `bd remember` entry filed capturing the "how the panel grew" state so future sessions inherit context.

---

## 7. Rollout plan (Phase 1 → Phase 4)

### Phase 1 — Design (this document) — 0.5 day
Draft, review, get user approval, file bd bead + GH issue.

### Phase 2 — Foundation PR — 1 day
- Add `use_extended_confluence_panel` flag to `AnalysisFeatureFlags`.
- Add `extended` field to `ConfluenceWeights`.
- Scaffold `indicators_ext.py` + `confluence_ext.py` with pass-through stubs.
- Backward-compat invariance suite (flag=False golden regression).
- Land as own PR so subsequent per-family PRs can rely on the flag existing.

### Phase 3 — Per-family expansion PRs — 4 PRs, ~0.5 day each
Ship each family as its own PR. Each PR: 4-6 new indicators, corresponding vote-mappers, unit tests, decorrelation tests, R7.11 mutation verification, 3-way parallel convergence review:

- **PR-X1**: Trend family expansion (Aroon, Ichimoku, PSAR, ADX-independent-vote)
- **PR-X2**: Momentum family expansion (ROC, Williams %R, CCI, MACD signal-cross)
- **PR-X3**: Volatility family expansion (BB bandwidth, Keltner position, HV, TTM Squeeze)
- **PR-X4**: Volume family expansion (MFI, A/D Line, vol ratio)

Ordering: trend → momentum → volatility → volume (biggest impact first, so the code review discipline is exercised on the largest surface area early).

### Phase 4 — Documentation + notebook refresh — 0.5 day
- Update notebook 03's "4 indicator families" table under both flag settings.
- Add an "FAQ: why is my panel 14 vs 31 keys?" cell in notebook 03 (bridges to `use_extended_confluence_panel`).
- Update README § Commands with the flag description.

**Total budget:** ~4.5 days across 6 PRs. All PRs land on `trading_technicals`.

---

## 8. Open questions

- **OQ1**: `ConfluenceWeights.extended` (D3 Option A) vs kwarg-only (Option B)? Recommendation is A. Awaiting sign-off.
- **OQ2**: Ship the 4 family-expansion PRs in one squashed PR (small blast radius, one review cycle) or 4 separate PRs (slower, but each independently revertable if a family later proves broken)? Recommendation: 4 separate PRs to match the pattern PR #349 / #404 / #405 established (each phase auditable in isolation).
- **OQ3**: Should the `breakout` preset get +0.05 to volatility once TTM Squeeze + HV land (D6 exception)? Recommendation: defer to a separate small PR after all 4 family PRs land, so the reweighting is done with the actual production panel behavior visible in logs.
- **OQ4**: Do we backport this to the notebooks 02 / 05 tables too, or only 03? Recommendation: 03 in-PR, 02 + 05 in a small follow-up docs PR to keep the code + docs concerns separated.

---

## 9. References

**Books:**
- John Murphy, *[Technical Analysis of the Financial Markets](https://www.investopedia.com/articles/active-trading/010615/top-technical-analysis-books.asp)* (NYIF, 1999) — canonical reference for every indicator listed.
- John Carter, *[Mastering the Trade](https://www.simplertrading.com/blog/what-is-the-ttm-squeeze/)* (McGraw-Hill, 2005) — origin of TTM Squeeze.
- David Aronson, *[Evidence-Based Technical Analysis](https://www.wiley.com/en-us/Evidence+Based+Technical+Analysis%3A+Applying+the+Scientific+Method+and+Statistical+Inference+to+Trading+Signals-p-9780470008744)* (Wiley, 2007) — statistical significance of individual indicators.
- Marcos López de Prado, *[Advances in Financial Machine Learning](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086)* (Wiley, 2018) — the ensemble / decorrelation math this proposal rests on.

**Academic:**
- Leo Breiman, *[Random Forests](https://link.springer.com/article/10.1023/A:1010933404324)* (*Machine Learning*, 2001) — the foundational paper on why decorrelation dominates ensemble accuracy.
- Bailey & López de Prado, *[Pseudo-Mathematics and Financial Charlatanism](https://www.ams.org/notices/201405/rnoti-p458.pdf)* (*Notices of the AMS*, 2014) — False Discovery Rate + PBO metric.

**Investopedia primers** (one per new indicator, all linked inline in §3 tables above).

---

## 10. Expert review — trader / quant perspective

> Reviewer lens: systematic/technical trading + quantitative signal design. Claims below were checked against the live engine (`engine/confluence.py` vote emitters and `composite_score`/`volume_confirmation`, and `engine/rules.py` sizing) — not just the spec text.

### 10.1 Verdict

**Sound engineering scaffold, but the core *investment* thesis is unproven and two of the proposed indicators are mathematically redundant with members you already have.** The feature-flag design, test discipline (R7.*), and rollout plan are genuinely strong — this is well above the median internal design doc. But the document justifies the expansion almost entirely with *ensemble-variance* theory (Breiman) while never measuring the only thing that matters for a trading system: **does the bigger panel improve forward, out-of-sample, net-of-cost performance?** As written, you could hit every acceptance criterion (31 keys, 20 votes, all decorrelation gates green, ≤1.5× wall-clock) and still *degrade* live edge. That is precisely the failure mode Aronson (*Evidence-Based TA*) and Bailey/López de Prado (*Pseudo-Mathematics…*) — both cited in §9 — warn about: adding degrees of freedom without an out-of-sample, multiple-testing-corrected acceptance gate.

**Recommendation: approve the *scaffold* (Phase 2 flag + harness), but gate Phase 3 family PRs on an empirical forward-signal criterion, and cut/replace the redundant indicators before any of them are built.**

### 10.2 What the design gets right

- **Feature-flag + flag-off golden invariance** (D1/D2, AC-1) is exactly right — zero-risk to existing callers, byte-identical default path.
- **Correctly identifying the volume-family leverage problem** (§1.2.3). With only 2 votes feeding a `1 + 0.15·mean(votes)` multiplier, one bad reading has 50% of the multiplier — real fragility.
- **Retaining ATR as a non-voting reference** (V1) is conceptually correct: it's a *scale*, not a direction. Same instinct should have been applied to ADX and the squeeze indicators (see 10.3).
- **Adding a derived `kc_position`** (V3) fixes a genuine current limitation — today Keltner *cannot* vote because the levels carry no `close` (confirmed in `volatility_votes`). Good catch.
- **R7.4 decorrelation gate** as a standing contract is the right structural idea (its *implementation* needs fixing — see 10.4).

### 10.3 Critical issues (block Phase 3 until resolved)

**C1 — MACD signal-cross (M6) is not decorrelated from MACD histogram (T2); it is the *same event* by construction.**
By definition `hist = macd_line − signal_line`, so the MACD line crosses the signal line **exactly when `hist` crosses zero**. T2 votes `sign(macd_hist)` (confirmed in `trend_votes`); M6 votes "line crossed signal in last 3 bars" = the zero-crossing of that identical quantity. They share the same 12/26/9 EMAs and the same difference series. The doc's claimed "~0.55 rolling correlation on SPY" is almost certainly measuring *histogram magnitude* vs *cross event*, not the two vote signals — the vote-level dependence is near-total around every crossing. **This is a double-count that will over-weight MACD inside the fused score.** → **Drop M6**, or replace it with a genuinely orthogonal momentum mechanism (TSI, KST/Coppock, or — best — a slow **cross-sectional 3/6/12-month momentum** factor, the one momentum signal with robust published out-of-sample evidence: Asness/Moskowitz/Pedersen 2013, already in your §9 lineage).

**C2 — Williams %R (M4) is a linear restatement of the Stochastic you already vote (M2).**
`Williams %R = −100·(HHₙ − close)/(HHₙ − LLₙ)` and fast Stochastic `%K = 100·(close − LLₙ)/(HHₙ − LLₙ)`, so for the same lookback **%R = %K − 100** — a perfect affine transform (ρ = −1). Even against the K/D-cross construction it is near-redundant. The doc literally describes it as "inverted stochastic," which is the tell. **Drop Williams %R.** If you want more momentum breadth, spend the slot on something measuring a different mechanism (Connors RSI, or the cross-sectional momentum in C1).

**C3 — Several "votes" are non-directional quantities given a borrowed direction, which (a) double-counts and (b) breaks the within-family independence the whole ensemble rests on.**
- `adx_strength = sign(ema_cross)·clip((adx−20)/30,0,1)` — ADX is *by Wilder's design* a **non-directional** strength measure. Multiplying it by `sign(ema_cross)` makes T3 a scalar re-weighting of T1, not an independent vote — its correlation with `ema_cross` is ≈1 whenever ADX>0. → Make ADX a **gate/confidence scaler** (it already gates `macd_hist`), not a directional vote.
- `ttm_squeeze` and `bb_squeeze` both encode Bollinger-in-Keltner compression (overlapping), and `ttm_squeeze` is defined as a function of "trend vote > 0" — so a **volatility-family vote now reads the trend family**, coupling the two family means and violating the independence assumption behind §1.2's Breiman argument. A squeeze is a *volatility-state*, not a direction. → Collapse to **one** squeeze signal used as a **gate/scaler** (or a separate regime flag), not a directional vote, and never let it depend on another family's vote.

**C4 — No forward-performance / information-coefficient acceptance gate — the central omission.**
Breiman's variance reduction is about decorrelated **errors relative to the target**, not decorrelated **features**. Two indicators can be mutually uncorrelated yet both carry ~0 predictive information (IC≈0); averaging them under the **simple mean** fold (`_mean`, confirmed in `confluence.py`) just injects noise and **dilutes** the strong votes. Nothing in §6 measures IC, hit-rate, or the notebook-04 `validate` pass-rate/DSR on **out-of-sample** data. → Add an empirical gate (see R1 below). No vote ships without demonstrated *incremental* forward signal, PBO/DSR-guarded for the added degrees of freedom.

**C5 — Equal-weight family fold means adding weak/redundant votes lowers the family's effective signal.**
Family score = simple mean of its votes. Going trend 2→5 gives the historically-strongest vote (ADX-gated MACD) `1/5` instead of `1/2` weight; if 3 of the 5 are weak or correlated, the family's effective IC drops even though the panel looks "more diversified." → Either weight votes by measured IC (or a strong/weak tier), or keep the panel **lean and orthogonal**. "More indicators" is not the goal; "more *independent, individually-informative* bets" is (Grinold's `IR = IC·√breadth` — but *breadth* counts **independent** bets, and everything here is a transform of one OHLCV series, so effective breadth ≪ nominal 20).

### 10.4 Medium issues (fix before or during Phase 3)

**M1 — The D4 decorrelation gate as specified would *miss the two worst redundancies*.** It checks each new indicator "vs every **other new** indicator in the **same family**." But C1 (MACD-cross vs MACD-hist) and C2 (Williams vs Stochastic) are redundancies of a **new** vote against a **kept/existing** vote — explicitly outside the gate's scope. → Redefine the gate to run **new-vs-all (new + existing) votes**, on the **vote outputs** (`[−1,1]`), using **Spearman** rank correlation (votes are clipped/ordinal), not Pearson on raw indicator levels.

**M2 — Unconditional correlation on SPY hides the tail/regime correlation that actually bites.** Oscillators (RSI, Stoch, Williams, CCI, MFI) decorrelate in calm tape but **co-move to the same extreme in strong trends and crashes** — i.e. exactly when you need diversification they collapse to one bloc (persistent-overbought fighting a valid uptrend). Loading momentum with 4–5 oscillators amplifies this. → Measure **conditional correlation by regime** (trend vs range, high-vol vs low-vol), and cap the oscillator sub-bloc's effective weight.

**M3 — Volume widening partly *defeats its own stated goal* under the current multiplier.** `volume_confirmation = 1 + 0.15·mean(volume_votes)` → more bounded votes make the mean concentrate near 0, so the multiplier hugs 1.0 and volume's confirm/damp effect **weakens** as you add votes (the opposite of §1.2.3's intent). Also note the multiplier is **already documented as inverted for short signals** (deferred to #75, confirmed in `volume_confirmation` docstring). → **Fix the #75 short-side inversion first**; reconsider whether widening volume helps at all without changing the fold.

**M4 — Min-bar requirements will produce widespread loud-empty warnings.** Ichimoku needs ≈52 + 26-forward displacement (~78 bars); it will `NaN` on short histories and recent IPOs. → Document per-indicator min-bar needs, confirm the scan's lookback window supplies them, and add graceful-drop tests so a short-history symbol degrades cleanly rather than warning-spamming.

**M5 — No turnover / transaction-cost budget.** Several new votes are hard-threshold ternary (PSAR flip, MFI 20/80, Williams, `vol_confirmation` 1.5×) that flip discretely → higher **signal turnover** → more entries/exits → slippage + commissions. For a trading system this is a first-order cost, and the spec measures only wall-clock. → Add average sign-changes/vote/year and a **net-of-cost** delta to acceptance. Prefer bounded-continuous votes; if ternary, add **hysteresis** (separate enter/exit thresholds) to damp whipsaw.

### 10.5 Minor / nits

- **N1 — Fixture is SPY-only; techtrade trades single names.** Add a small basket (a high-beta tech, a low-vol utility, a cyclical, a recent IPO) so decorrelation/min-bar behavior reflects the actual universe, and include an explicit high-vol slice (e.g. 2022).
- **N2 — PSAR** whipsaws badly in ranges and its vote is a hard ±1 flip — its turnover contribution should be watched (ties to M5).
- **N3 — Count framing.** "25–30 indicators" is really "20 votes / 31 keys." Be explicit that **votes** (not keys) are the ensemble members, so reviewers don't over-read the 31.
- **N4 — Shadow-mode before default-on.** Even though default is `False`, add a logged **shadow period** (compute both panels, log score divergence, act on neither-but-classic) so you gather live divergence data before anyone flips the default.

---

## 11. Answers to §8 open questions

**OQ1 — `ConfluenceWeights.extended` (A) vs kwarg (B)?**
**Answer: Option A in spirit, but do not use a bare `bool` — use a small versioned selector, and verify the plumbing.** Concretely: house selection in a `PanelConfig` (or a `panel: Literal["classic", "extended"]` enum) rather than `extended: bool`, so a future v3 panel isn't a boolean explosion and every call site reads as `panel="extended"` not `extended=True`. Keep it *adjacent* to `ConfluenceWeights` as the doc wants, **but first confirm the panel builders (`build_indicator_panel`, `technical_panel`) actually receive a `ConfluenceWeights`/config object** — they operate a layer below the weights today, so a weights-only flag may not reach `indicators.py`. If it doesn't, thread an explicit `PanelConfig` param (a *typed* config, still not a loose bool). Resolve the selector **once** per build (as D1 says) — good. Net: A's *placement* instinct is right; upgrade the *type* to an enum and validate it can reach both the panel and the vote layers.

**OQ2 — One squashed PR vs 4 family PRs?**
**Answer: 4 separate PRs — but gate each on an empirical forward-signal delta, not just green tests + decorrelation, and ship the eval harness in Phase 2.** Independent revertability matters *precisely because* the momentum family carries the C1/C2 redundancy landmines — you want to be able to back out one family without touching the others. Two amendments to the doc's plan: (a) the Phase-2 foundation PR must include the **IC / DSR / notebook-04 pass-rate harness** (R1) so each family PR is judged on forward metrics, and (b) flag the **momentum family as highest-risk** (redundancy + oscillator-bloc tail correlation) and give it the most scrutiny, regardless of the trend-first ordering.

**OQ3 — `breakout` preset +0.05 to volatility once TTM Squeeze + HV land?**
**Answer: Defer *and* derive it empirically — do not hand-pick +0.05.** A magic constant chosen by eye is exactly the overfitting the cited López de Prado work warns against. After the volatility family lands, **fit** the breakout preset's family weights to maximize *out-of-sample* DSR / hit-rate with a **PBO check**, and only adopt a reweight if it survives. If the data doesn't support a shift, keep the weights unchanged. So: defer (agree), but replace "+0.05 by judgment" with "whatever the OOS-validated fit says, or nothing."

**OQ4 — Backport tables to notebooks 02/05, or only 03?**
**Answer: 03 in-PR, 02 + 05 in a follow-up docs PR — agree — and add notebook 04.** The doc's separation of code vs docs concerns is right. One addition: **notebook 04 (validation)** should surface the flag state and is the natural home to *report the empirical justification* (the forward-performance delta from R1), since that's where forward performance is measured. Docs follow-up should therefore touch 02, 04, and 05.

---

## 12. Additional recommendations

Prioritized; R1 is the single most important change.

1. **R1 — Add an empirical, out-of-sample acceptance gate (make it AC-blocking).** Each new vote must demonstrate **incremental** forward signal — positive information coefficient vs N-day forward return, *and/or* a non-negative delta in the notebook-04 `validate` pass-rate / DSR — measured out-of-sample on the single-name basket, with a **PBO / deflated-Sharpe** guard for the added degrees of freedom. A vote that doesn't clear the bar does not ship, regardless of how "canonical" it is. This converts the proposal from "more indicators because theory says decorrelation helps" into "more indicators *that are proven to help*."
2. **R2 — Fix the D4 gate (M1):** run **new-vs-all** votes (include existing/kept members), on **vote outputs** in `[−1,1]`, with **Spearman**, and add **conditional (per-regime) correlation** (M2) alongside the unconditional check. This single fix would have caught C1 and C2 automatically.
3. **R3 — Cut the two redundant additions now (C1, C2):** remove MACD-signal-cross and Williams %R from §3.2. If momentum breadth is still wanted, replace with a mechanism-orthogonal pick — ideally a **cross-sectional 3/6/12-month momentum** factor (the most robust published momentum signal) rather than another intraday oscillator.
4. **R4 — Reclassify non-directional indicators as gates/scalers, not votes (C3):** ADX, squeeze (one, not two), and HV describe *strength / state*, not *direction*. Use them to **scale confidence or gate** other votes (as ADX already gates MACD), never as directional votes, and never let one family's vote read another family's votes.
5. **R5 — Replace the simple-mean family fold with IC-weighted (or tiered strong/weak) aggregation (C5)** — or deliberately keep the panel lean. Protect the strong votes from dilution by weak/correlated newcomers.
6. **R6 — Sequence the volume work correctly (M3):** fix the #75 short-side multiplier inversion **before** widening volume; re-examine whether more votes under `1 + k·mean(·)` actually raises volume's influence (it compresses it), and consider an alternative fold (e.g. weighting by vote magnitude/agreement) if the goal is robustness rather than dilution.
7. **R7 — Add a turnover / transaction-cost budget to §6 (M5):** measure sign-changes per vote per year and a **net-of-cost** performance delta; prefer bounded-continuous votes; add **hysteresis** to any hard-threshold ternary vote retained.
8. **R8 — Document per-indicator min-bar requirements + graceful-drop tests (M4):** confirm the scan lookback feeds Ichimoku/others; degrade cleanly on short histories/IPOs instead of warning-spamming.
9. **R9 — Broaden the decorrelation/min-bar fixture beyond SPY (N1):** single-name basket across sectors/betas + an explicit high-vol regime slice, since the production universe is single stocks, not the index.
10. **R10 — Right-size the breadth claim (§3.5 / N3):** state effective vs nominal breadth explicitly (all votes derive from one OHLCV series → effective breadth ≪ 20), and frame **votes**, not keys, as the ensemble members so the "31" isn't over-read.
11. **R11 — Ship an enum/versioned panel selector and a logged shadow-mode period (OQ1, N4)** before any future default flip: compute both panels live, log divergence, act on classic only, and use the collected divergence + R1 metrics to justify (or reject) a later default-on.
12. **R12 — Re-order Phase 3 risk, not just impact (OQ2):** keep trend first if you like the blast-radius argument, but explicitly tag **momentum as the highest-risk family** (redundancy + oscillator tail-correlation) and require the R1 gate + R2 conditional-correlation check to pass before it merges.

**One-line summary for the approver:** *the plumbing is ready to build; the investment case is not — approve the flag + eval harness, cut the two redundant indicators, convert the non-directional "votes" into gates, and let out-of-sample forward signal — not indicator count — decide what actually ships.*

---

*End of design. Awaiting user approval before filing bd bead + GH issue and proceeding to Phase 2 scaffold PR.*
