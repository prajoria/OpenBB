# 74 — Weighted Confluence Voting → Score + IndicatorVote Attribution

**GitHub:** [#74](https://github.com/prajoria/OpenBB/issues/74) · **Phase:** P3 · **Sprint:** 3 · **Size:** L
**Depends on:** [#73](https://github.com/prajoria/OpenBB/issues/73) (the hybrid selector / authoritative `IndicatorPanel`) and [#64](https://github.com/prajoria/OpenBB/issues/64) (Q4 default weights, **RESOLVED**)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §12 (Weighted Confluence Signal Engine), §20 Q4
**Scope:** Add `engine/confluence.py`: map each indicator family's panel readings to votes ∈ `[-1,+1]`,
fuse them through the Q4 family weights (trend/momentum/volatility additive; volume as a confirmation
multiplier) into a composite `score ∈ [-1,+1]`, bucket direction + conviction, and emit a fully
reconciling `list[IndicatorVote]` so the engine can always answer *"why long?"*.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

> **⚠ This is a PLANNING / brainstorming doc.** Q4 fixes the *family weights* and *volume-as-multiplier*
> posture (§0a). It does **not** fix the per-indicator vote math, the multiplier formula, or the
> normalization rules — those are surfaced as **OPEN QUESTIONS (§0b)** for the user to decide before
> code is written. The `ConfluenceConfig` defaults shown below are *provisional placeholders*, not
> decisions.

---

## What this is

**Weighted Confluence Voting** turns a panel of technical indicators into a single, explainable
directional call. A *confluence* signal is simply the idea that you trust a direction more when
several **independent** indicators agree on it — rather than betting on one indicator alone, each
indicator casts a directional **vote** as a number in `[-1, +1]` (`+1` = strongly bullish, `−1` =
strongly bearish, `0` = neutral), and those votes are combined into one composite **score**, also in
`[-1, +1]`. *Weighted* means the votes do **not** count equally: trend indicators carry more weight
than momentum, which carry more than volatility, and volume acts as a confirmation multiplier rather
than its own vote — all per the configured family weights (`0.40 / 0.25 / 0.20 / 0.15`). *Attribution*
means the result never throws away its reasoning: the signal keeps the full list of per-indicator
votes (each with its family, name, vote, and weight) so a human can read back **exactly why** it
said long or short. This step is the brain of techtrade: the screener finds the top-moving stocks,
the indicator panel ([#73 design](./73-indicator-adapter-selector-parity-bulk.md)) computes the raw
indicator readings, and **this** step collapses that panel of numbers into one actionable call — a
`MoverSignal` carrying `score` + `direction` (`long`/`short`/`flat`) + `votes`. Everything downstream
is driven by that score: the entry/exit rules and position sizing
([#76 design](./76-entryexit-rule-sizing.md)), order generation
([#77 design](./77-order-generation-tradeplan.md)), and the final human-readable recommendation
([#80 design](./80-recommendation-builder.md)) and Excel export
([#81 design](./81-excel-export.md)). The transparency property — being able to answer *"why
long?"* from the votes alone — is a core product principle, not an afterthought.

---

## 0. Key decisions — locked vs open

### 0a. Locked (from PRD §12 / Q4 / §14.2 — do **not** re-open)

| # | Decision | Value | Source |
|---|---|---|---|
| L1 | Additive family weights | trend `0.40`, momentum `0.25`, volatility `0.20` | §12.2, Q4 |
| L2 | Volume posture | volume `0.15` applied as a **confirmation multiplier**, *not* an additive vote | §12.1, §12.2, Q4 |
| L3 | Composite formula | `raw = Σ_family(w·Σ(vote/n)); score = clip(raw·volume_confirmation, -1, +1)` | §12.2 |
| L4 | Vote range | every indicator vote ∈ `[-1, +1]`; final `score` ∈ `[-1, +1]` (hard clip) | §12.1, §12.2 |
| L5 | Direction bucketing | `long` if `score ≥ +entry_threshold`, `short` if `score ≤ −entry_threshold`, else `flat` | §12.2 |
| L6 | `entry_threshold` default | `0.4` (lives on `EntryExitRule`, #76 rules + sizing) | [`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py), §13 |
| L7 | Conviction buckets | `\|score\| ≥ 0.7` → **High**; `0.4 ≤ \|score\| < 0.7` → **Medium**; `< 0.4` → **Low** | §14.2 |
| L8 | Candles excluded from voting | candlestick patterns are **confirmation-only flags** in v1, never a weighted family (`IndicatorVote.family` has no `"candles"` member) | Q8, [`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py) |
| L9 | ATR never votes | ATR sets stop distance (#76), it is **not** a directional vote | §12.1 |
| L10 | Attribution is mandatory | every signal carries its full `votes` list; `votes` must reconcile to `score` | §12.2, §4.3 transparency |

> **Q4 is RESOLVED — do not relitigate the weights.** `0.40/0.25/0.20/0.15` with volume-as-multiplier
> is the shipped, un-tuned, honest default; a future `openbb-backtest` study may revisit it via
> [#75 design](./75-signals-command-presets.md)
> (signals command + presets), but #74 hard-codes these as the `ConfluenceConfig` defaults.

### 0b. Open questions for brainstorming (NOT decided — pick before coding)

| ID | Question | Why it matters | Leaning (recommendation, **not** decided) |
|---|---|---|---|
| **Q-A** | Exact per-indicator vote functions: how does each reading map to `[-1,+1]`? (RSI linear ramp vs `tanh`; ADX **continuous damp** vs **hard gate**; `macd_hist` pure-sign vs magnitude-scaled; stoch K/D cross sign; **Bollinger %B regime-aware** — is a regime detector in scope for v1?) | Determines the actual signal content; the %B regime choice can **flip the sign** of the volatility vote (continue vs mean-revert) | Piecewise-linear ramps w/ deadband; ADX as a *continuous* damp; **use ADX as the regime proxy** (no new module) so %B is votable from the panel alone — see §2 |
| **Q-B** | Volume "confirmation multiplier": exact formula + bounds. How are `obv_slope` (unbounded) + `cmf` (~`[-1,1]`) combined, and how does sign-agreement amplify / divergence damp? Also: do the additive weights (sum `0.85`) renormalize to `1.0`, or is the `0.85` ceiling intended so volume is *needed* to reach high conviction? | Sets how (and whether) `score` can reach `±1`; an unbounded multiplier interacts with the final clip | `volume_confirmation = 1 + k·sign(raw)·vol_vote`, `vol_vote ∈ [-1,1]`, `k=0.5` → range `[0.5,1.5]`; **leave the 0.85 additive ceiling** (don't renormalize) — see §3 |
| **Q-C** | Normalization when indicators are absent (warm-up NaN ⇒ key omitted from panel): is `n_indicators` the **fixed family roster** (missing ⇒ 0 vote, damps family) or **renormalized to present count** (family stays full-weight)? And if a whole family is empty, drop+rescale its weight or leave it at 0? | A short-history symbol either scores weaker (fixed-n) or full-scale on one indicator (renorm-n); changes every score on warm-up | Renormalize over **present** indicators per family; if a family is entirely absent, leave it at `0` (do **not** rescale sibling family weights) — see §3 |
| **Q-D** | Per-family **voter roster** + intra-family `n_indicators`: which panel keys are *voters* vs *gates/inputs*? (Is `adx` a voter or only a gate on `macd_hist`? Do `ema_fast`/`ema_slow` vote, or only via derived `ema_cross`? Do `stoch_k`+`stoch_d` emit **one** combined vote or two? Does any volatility key besides `bb_pctb` vote, given the panel carries no `close` for `kc_upper`/`kc_lower`?) | `per_indicator_weight = w_family / n_indicators`, so the roster directly scales each vote's weight | trend voters `{macd_hist (adx-gated), ema_cross}` (n=2); momentum `{rsi, stoch}` combined (n=2); volatility `{bb_pctb}` (n=1, kc/atr are levels) — see §2 |
| **Q-E** | Where do weights + shape params live? A frozen `ConfluenceConfig` dataclass mirroring `IndicatorConfig`'s `DEFAULT_CONFIG` pattern? Does `direction_threshold` duplicate `EntryExitRule.entry_threshold`, or is it a single source of truth? How do #75 presets override it? | Config shape is the seam #75 (signals + presets) plugs into; threshold duplication risks drift | Frozen `ConfluenceConfig` + `DEFAULT_CONFLUENCE`; `direction_threshold` **defaults from** `EntryExitRule.entry_threshold` (0.4) but is overridable; presets are alternate `ConfluenceConfig` instances — see §3 |

> Each leaning above is a **starting position for the review**, not a committed choice. The golden
> fixture (§5) is intentionally **not generated** until Q-A…Q-E are settled, because every one of them
> changes the locked numbers.

Each open question below carries an approvable placeholder (mirroring the PRD §20 convention): a
concrete **Recommendation** restating the table's leaning, plus an **Answer** line for the user to
sign off. Resolving these unblocks the golden fixture (§5.1).

#### Q-A — Per-indicator vote functions (incl. the %B regime question)

How does each indicator reading map to `[-1,+1]` — RSI linear ramp vs `tanh`, ADX continuous damp vs
hard gate, `macd_hist` pure-sign vs magnitude-scaled, stoch K/D cross sign, and is a Bollinger %B
regime detector in scope for v1? This sets the actual signal content, and the %B regime choice can
flip the sign of the volatility vote (continue vs mean-revert).

- **Recommendation:** Use piecewise-linear ramps with a deadband; treat ADX as a *continuous* damp;
  reuse ADX as the regime proxy (no new module) so %B is votable from the panel alone — see §2.
- **Answer:** Follow recommendation. The recommendation is solid, industry-aligned, and specifically avoids the two common pitfalls: hard binary thresholds (fragile) and over-engineered regime models (overfit-prone).

#### Q-B — Volume confirmation-multiplier formula + the 0.85 ceiling

What is the exact formula and bounds for the volume multiplier — how are `obv_slope` (unbounded) and
`cmf` (~`[-1,1]`) combined, and how does sign-agreement amplify / divergence damp? And do the
additive weights (sum `0.85`) renormalize to `1.0`, or is the `0.85` ceiling intended so volume is
*needed* to reach High conviction? This sets whether `score` can reach `±1` and how the multiplier
interacts with the final clip.

- **Recommendation:** `volume_confirmation = 1 + k·sign(raw)·vol_vote` with `vol_vote ∈ [-1,1]` and
  `k=0.5` → range `[0.5,1.5]`; leave the `0.85` additive ceiling in place (do **not** renormalize) —
  see §3.
- **Answer:** Yes, it's well-designed. Here's why:

1. It encodes a real trading principle. "Don't trust a move without volume" is one of the oldest rules in technical analysis (Dow Theory, ~1900s). Making volume necessary for high conviction is correct. A breakout on low/divergent volume frequently fails.

2. The multiplier is bounded and safe. With k=0.5, the range is [0.5, 1.5] — it can halve or amplify by 50%, but the final clip(-1, +1) guarantees no runaway. Symmetric and predictable.

3. Neutral when absent. If volume data is missing (warm-up period, no OBV/CMF), the multiplier defaults to 1.0 — the score is unchanged. No penalty, no bonus. This is important for short-history stocks.

4. The sign-agreement trick is elegant. sign(raw) · vol_vote is a one-line way to encode "same direction = amplify, opposite = damp" without branching logic. It's the kind of thing you'd see in production quant systems.

5. The 0.85 ceiling is defensible. Not renormalizing creates a deliberate asymmetry: indicators alone can give you a signal, but you need volume to give you conviction. This matches how experienced traders actually think — "I like the setup, but I want to see volume confirm before I size up."

#### Q-C — Normalization when indicators are absent (warm-up)

When a warm-up NaN omits a key from the panel, is `n_indicators` the **fixed family roster** (missing
⇒ 0 vote, damping the family) or **renormalized to the present count** (family stays full-weight)? And
if a whole family is empty, do we drop+rescale its weight or leave it at `0`? This changes every score
on warm-up — short-history symbols either score weaker (fixed-n) or full-scale on one indicator
(renorm-n).

- **Recommendation:** Renormalize over the **present** indicators per family; if a family is entirely
  absent, leave it at `0` (do **not** rescale sibling family weights) — see §3.
- **Answer:** Yes — and it's the safer of the two designs. Here's the reasoning:

1. Renormalize within a family: Correct.

If you have two momentum indicators and one is missing, the one that is present is your best available information for that family. Penalizing the score just because you have less data is a false signal — a weak score should mean "indicators disagree" or "indicators are neutral," not "I don't have enough data yet."

With fixed-n, a 30-day-old stock with a screaming RSI buy signal would look like a lukewarm signal just because Stochastic hasn't warmed up. That's misleading.

2. Do NOT rescale across trend families: Also correct.
3. Volume neutrality is preserved.

The volume multiplier already defaults to 1.0 when the volume family is absent (Q-B scenario 4). Combined with Q-C's "leave absent family at 0," a warm-up stock with no volume data gets:

No volume amplification/damping (multiplier = 1.0)
No artificial inflation from rescaling
The system degrades gracefully.
#### Q-D — Per-family voter roster + intra-family `n_indicators`

Which panel keys are *voters* vs *gates/inputs*? Is `adx` a voter or only a gate on `macd_hist`? Do
`ema_fast`/`ema_slow` vote, or only via the derived `ema_cross`? Do `stoch_k`+`stoch_d` emit **one**
combined vote or two? Does any volatility key besides `bb_pctb` vote, given the panel carries no
`close` for `kc_upper`/`kc_lower`? Because `per_indicator_weight = w_family / n_indicators`, the
roster directly scales each vote's weight.

- **Recommendation:** trend voters `{macd_hist (adx-gated), ema_cross}` (n=2); momentum `{rsi, stoch}`
  combined (n=2); volatility `{bb_pctb}` (n=1, kc/atr are levels) — see §2.
- **Answer:** 1. ADX as gate, not voter — Correct
ADX measures trend strength, not direction. ADX = 50 just means "strong trend" — it doesn't tell you if it's up or down. Giving it a directional vote would be nonsensical.

Using it as a gate/dampener on macd_hist is the right role: "I have a MACD signal, but how much should I trust it?" ADX answers that.

If ADX were a voter (n=3), each trend vote would get 0.40/3 = 0.133 weight instead of 0.40/2 = 0.20. The MACD and EMA cross signals — which actually carry directional information — would each be weaker. Bad trade.

2. ema_fast/ema_slow only through ema_cross — Correct
ema_fast = 142.50 and ema_slow = 138.20 are raw price levels. They don't mean "bullish" or "bearish" on their own. What matters is their relationship:

If you let ema_fast and ema_slow vote separately, what would their votes even be? "EMA(20) is $142.50, therefore... bullish?" That's meaningless without context.

Making them vote through ema_cross is the only sensible approach. It also keeps n=2, preserving the weight of each trend voter at 0.20.

3. Stoch K/D as one combined vote — Correct
Stochastic %K and %D are designed as a pair. The signal comes from their cross:

%K crosses above %D → bullish
%K crosses below %D → bearish
Splitting them into two separate votes (n=3 for momentum) would:

Dilute RSI's weight from 0.25/2 = 0.125 to 0.25/3 = 0.083
Create redundancy — %K and %D are highly correlated (D is just a smoothed K), so they'd almost always vote the same direction, double-counting
One combined vote sign(stoch_k - stoch_d) is cleaner and avoids correlation bias.

4. Volatility: only bb_pctb votes (n=1) — Correct, but notable
This means one indicator carries the entire 0.20 volatility weight. That's a lot of power for one voter. But the alternatives are worse:

Alternative	Problem
Let ATR vote	ATR has no direction (L9) — it's just "how volatile is this?"
Let KC levels vote	Panel has no close price to compare against — can't compute "price above/below KC"
Add KC %position (like %B)	Requires panel redesign (#73 scope change)
Set n=0, drop volatility	Loses 0.20 weight entirely — wastes a family
So bb_pctb alone at n=1 is the least-bad option given the current panel design. It gets full 0.20 weight, which is significant but not unreasonable — Bollinger %B is a well-established, information-rich indicator.

The Weight Distribution Result
Family	Weight	n voters	Per-vote weight	Total family votes
Trend	0.40	2	0.20 each	macd_hist(gated) + ema_cross
Momentum	0.25	2	0.125 each	rsi + stoch
Volatility	0.20	1	0.20	bb_pctb alone
Volume	0.15	—	multiplier	obv_slope + cmf → formula
Notice: bb_pctb (0.20) has the same per-vote weight as macd_hist (0.20) and more than rsi (0.125). That feels right — these are the workhorses of their respective families.

One Thing Worth Flagging
Volatility is a single point of failure. If bb_pctb is NaN (warm-up), the entire volatility family goes to zero (per Q-C). With the other families, losing one voter still leaves one to carry the weight. Volatility has no backup.

This isn't a flaw in the recommendation — it's an inherent limitation of the current panel. The doc acknowledges this: KC keys can't vote without close. A future panel extension adding kc_pctb (Keltner %B) would give volatility a second voter and reduce this fragility. But for v1, bb_pctb alone is the right call.

Verdict
The recommendation is sound. It correctly separates:

Directional signals (voters) from context/gates (ADX, ATR)
Derived signals (ema_cross, stoch cross) from raw inputs (ema_fast, stoch_k)
Bounded indicators (%B) from unbounded levels (KC prices)
The voter count (2/2/1) produces sensible per-vote weights, avoids correlation double-counting, and keeps each family's power aligned with its information content.

#### Q-E — Where weights + shape params live (config seam)

Should weights and shape params live in a frozen `ConfluenceConfig` dataclass mirroring
`IndicatorConfig`'s `DEFAULT_CONFIG` pattern? Does `direction_threshold` duplicate
`EntryExitRule.entry_threshold`, or is it a single source of truth? How do
[#75 design](./75-signals-command-presets.md) presets override it? This config shape is the seam #75
plugs into, and threshold duplication risks drift.

- **Recommendation:** Frozen `ConfluenceConfig` + `DEFAULT_CONFLUENCE`; `direction_threshold`
  **defaults from** `EntryExitRule.entry_threshold` (0.4) but is overridable; presets are alternate
  `ConfluenceConfig` instances — see §3.
- **Answer:** Follow recommendation. The design is sound and well-structured:

1. **Frozen dataclass:** Standard, correct — matches the existing `IndicatorConfig` / `DEFAULT_CONFIG`
   pattern in the codebase. Immutability guarantees same config → same score (determinism §17), makes
   configs hashable for cache keys and audit trails, and defaults baked in means `score_panel(panel)`
   works with zero config out of the box.

2. **`direction_threshold` defaults to 0.4, overridable:** A pragmatic compromise between coupling
   (always reading from `EntryExitRule`, which would break confluence's pure/standalone boundary) and
   full duplication (separate values that could drift). Drift risk is mitigated because presets (#75)
   override both configs together as a bundle, and golden tests lock the behavior.

3. **Presets as full alternate `ConfluenceConfig` instances:** Simple, auditable, testable. Each preset
   is a complete, self-contained config — no inheritance chains, no partial-override merge logic. For
   v1 with 3 presets, explicit full configs are more readable than DRY partial overrides. One argument
   swap (`config=PRESET_MEAN_REVERT`) changes everything.

---

## 1. Module layout (new)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
└── confluence.py                 # NEW — IndicatorPanel -> votes -> score/direction.
                                  #   ConfluenceConfig (frozen) + DEFAULT_CONFLUENCE;
                                  #   per-family vote fns; volume multiplier; compose();
                                  #   conviction/direction bucketers. Pure, offline.

openbb_platform/extensions/techtrade/tests/
├── unit/
│   └── test_confluence.py             # NEW — reconciliation invariant, direction &
│                                      #   conviction buckets, normalization (Q-C),
│                                      #   multiplier neutrality, clip at ±1.
└── golden/
    ├── test_confluence_golden.py      # NEW — golden score + FULL vote breakdown locked
    │                                  #   via testing.assert_matches_golden (golden marker).
    └── fixtures/
        └── confluence_votes_synthetic.json   # NEW — committed golden (regen under review).
```

**Module-boundary rules**
- `confluence.py` depends **only** on `openbb_techtrade.models` (`IndicatorPanel`, `IndicatorVote`,
  `MoverSignal`). It consumes an **already-built** `IndicatorPanel` (from #73's
  `selector.build_indicator_panel_hybrid`) — it does **not** import
  [`engine/indicators.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators.py), `selector.py`,
  `pandas`, `pandas_ta_classic`, `openbb_technical`, or call `openbb.build()`. Pure, deterministic,
  fully offline-testable.
- `confluence.py` does **not** rank across symbols. It emits `(score, direction, votes)`; the
  `rank_in_segment` field of `MoverSignal` is attached by **[#75 design](./75-signals-command-presets.md) (signals command)**, which has the
  cross-symbol segment context. (Boundary note — see §3 for the exact return contract.)
- No network, no I/O, no global state; identical `(panel, config)` in ⇒ identical output (NFR §17,
  determinism §11).

---

## 2. Vote model (per family) — PRD §12.1

Each family reads its panel dict (`IndicatorPanel.trend|momentum|volatility|volume`, all
`dict[str, float]`) and emits one or more `IndicatorVote`s. The voter roster (Q-D) is **smaller than
the panel key set**: several keys are *gates* or *inputs*, not directional voters.

| Family | Panel keys present (#73 panel) | Proposed voter(s) (Q-D) | Vote derivation (§12.1) | Open Q |
|---|---|---|---|---|
| **trend** (`w=0.40`) | `macd_hist, adx, ema_fast, ema_slow, ema_cross` | `macd_hist` (ADX-gated), `ema_cross` → **n=2** | `sign(macd_hist)` **damped by ADX strength**; `ema_cross` → `+1` golden / `−1` death | Q-A, Q-D |
| **momentum** (`w=0.25`) | `rsi, stoch_k, stoch_d` | `rsi`, `stoch` (K/D combined) → **n=2** | RSI: deadband 45–55 → 0, ramp to `±1` at 30/70; stoch K/D cross **confirms sign** | Q-A, Q-D |
| **volatility** (`w=0.20`) | `bb_pctb, atr, kc_upper, kc_lower` | `bb_pctb` → **n=1** (ATR never votes — L9; kc are bare levels, no `close` in panel) | regime-aware %B: trend regime → breakout continues; range regime → mean-revert | Q-A, Q-D |
| **volume** (`w=0.15`) | `obv_slope, cmf` | folded into the **multiplier**, not additive (L2) | rising OBV / positive CMF amplifies same-sign `raw`; divergence damps it | Q-B |

### 2.1 Trend (Q-A / Q-D)

- **`macd_hist` vote.** `base = sign(macd_hist)` (PRD literal) — *or* a magnitude-scaled
  `tanh(macd_hist / scale)` if conviction should survive (pure-sign is scale-free → no extra param;
  `tanh` needs a `scale` and reintroduces a normalization concern). **[Q-A]**
- **ADX gate.** `adx > 20 ⇒ full weight, else damped` (§12.1). *"Damped"* is ambiguous:
  - **Option 1 (continuous):** `damp = min(adx / adx_gate, 1.0)`; `vote = base · damp`. Smooth, no cliff.
  - **Option 2 (hard gate):** `vote = base` if `adx > adx_gate` else `base · damp_const` (e.g. `0.5`).
  - Also open: does ADX damp **only `macd_hist`** or the **whole trend family**? **[Q-A]**
- **`ema_cross` vote.** `+1` if `ema_cross > 0` (golden), `−1` if `< 0` (death); `ema_cross` is the
  derived `ema_fast − ema_slow` already in the panel (#72). `ema_fast`/`ema_slow` do **not** vote
  individually — they are inputs to `ema_cross`. **[Q-D]**

### 2.2 Momentum (Q-A / Q-D)

- **RSI vote.** §12.1: `>55 ⇒ +`, `<45 ⇒ −`, magnitude saturates at 70/30. Proposed piecewise-linear:
  `0` in `[45,55]`; linear `0→+1` over `[55,70]`; linear `0→−1` over `[45,30]`; clip outside.
  Alternative: a smooth `tanh((rsi−50)/scale)` (no hard deadband). **[Q-A]**
- **Stoch vote.** §12.1: "stoch K/D cross **confirms sign**". Proposed single combined vote
  `sign(stoch_k − stoch_d)`, optionally scaled by distance from 50 (overbought/oversold context).
  Open: one combined `stoch` vote (n=2 family) **or** separate `stoch_k` + `stoch_d` votes (n=3). **[Q-D]**

### 2.3 Volatility — the **biggest** open question (Q-A)

§12.1 makes the %B vote **regime-aware**: *trend regime →* `%B > 1` breakout votes **+** (continue);
*range regime →* price at a band votes **mean-revert** (opposite sign). This needs a **regime signal
that the panel does not currently carry**. Options:

- **Option 1 — ADX-as-regime-proxy (recommended).** `adx ≥ regime_thr` (e.g. 25) ⇒ trend regime
  (breakout interpretation); else range regime (mean-revert interpretation). Reuses an existing panel
  key, **no new module**, keeps `confluence.py` panel-only.
- **Option 2 — simplified single-mode v1.** Drop regime entirely; map `%B` to one fixed-sign vote
  (e.g. `clip(2·(bb_pctb − 0.5), −1, +1)` trend-continue). Ship the regime split in a later issue.
- **Option 3 — dedicated regime detector.** A new sub-module/feature; largest scope, defers #74.

> **⚠ Sign-flip risk.** Under mean-revert, `%B > 1` votes **negative**; under trend-continue it votes
> **positive**. Because volatility carries `w=0.20`, the wrong regime call can move `score` by up to
> `0.40` (a full `±0.20` swing). This is why the regime decision is flagged as the headline Q-A item.

> **Keltner / ATR.** `kc_upper`/`kc_lower` are **price levels**; the `IndicatorPanel` carries no
> `close`, so they cannot form a directional vote on their own — they (and ATR, L9) stay
> **non-voting** in v1 unless the panel is extended. Surfaced under Q-D.

### 2.4 Volume (Q-B) — feeds the multiplier, not the sum

`obv_slope` (unbounded slope) and `cmf` (~`[-1,1]`) combine into a `vol_vote ∈ [-1,1]` that drives
`volume_confirmation` (§3). `obv_slope` needs squashing (`sign(obv_slope)` or `tanh(obv_slope/scale)`);
`cmf` is already bounded. The volume indicators still appear in the `votes` list (`family="volume"`)
so the multiplier is auditable (§4), but they are **not** summed into `raw`.

---

## 3. Composite score, direction & conviction — PRD §12.2

### 3.1 The formula (L3)

```
raw   = Σ_family∈{trend,momentum,volatility} ( w_family · Σ_indicator (vote_i / n_indicators) )
score = clip( raw · volume_confirmation, -1, +1 )
```

- Additive families are trend/momentum/volatility only; **volume is the multiplier** (L2).
- `per_indicator_weight = w_family / n_indicators` — so each `IndicatorVote.weight` is exactly this
  coefficient, and the within-family votes sum (after `·weight`) to at most `w_family` (§4).
- `n_indicators` is the **voter** count (Q-D), and how it responds to absent keys is **Q-C**.

> **Additive ceiling (Q-B sub-point).** trend+momentum+volatility weights sum to `0.85`, **not** `1.0`
> (volume is multiplicative). So `|raw| ≤ 0.85`; reaching `|score| ≥ 0.7` (High conviction, L7) without
> volume amplification requires near-unanimous families. **Open:** leave the `0.85` ceiling (volume
> confirmation is *needed* for High conviction — arguably the intent) **or** renormalize the three
> additive weights to sum `1.0`. Tied to Q-B.

### 3.2 Volume confirmation multiplier (Q-B)

Proposed (NOT decided): `volume_confirmation = 1 + k · sign(raw) · vol_vote`, bounded so amplify/damp
is symmetric, e.g. `k = 0.5 ⇒ multiplier ∈ [0.5, 1.5]`:
- `vol_vote` same sign as `raw` ⇒ multiplier `> 1` (amplify); opposite sign ⇒ `< 1` (damp).
- `vol_vote ≈ 0` or **volume family absent** ⇒ multiplier `= 1.0` (neutral; never raises on warm-up).
- The final `clip(·, -1, +1)` (L4) bounds `score` regardless of the multiplier's range.

### 3.3 `ConfluenceConfig` (Q-E) — provisional sketch

```python
# confluence.py  (illustrative — field set/defaults are Q-A/Q-B/Q-E, NOT decided)
from dataclasses import dataclass

@dataclass(frozen=True)
class ConfluenceConfig:
    # --- additive family weights (Q4 / L1 — LOCKED) ---
    w_trend: float = 0.40
    w_momentum: float = 0.25
    w_volatility: float = 0.20
    # --- volume multiplier budget (Q4 / L2 — LOCKED; NOT additive) ---
    w_volume: float = 0.15
    # --- direction / conviction thresholds (L5-L7) ---
    direction_threshold: float = 0.4      # Q-E: defaults from EntryExitRule.entry_threshold (#76)
    conviction_high: float = 0.7
    conviction_medium: float = 0.4
    # --- vote-shape params (ALL PROVISIONAL — Q-A / Q-B) ---
    rsi_low: float = 45.0
    rsi_high: float = 55.0
    rsi_sat_low: float = 30.0
    rsi_sat_high: float = 70.0
    adx_gate: float = 20.0
    regime_threshold: float = 25.0        # Q-A Option 1: ADX-as-regime-proxy
    vol_mult_k: float = 0.5               # Q-B: multiplier strength -> [1-k, 1+k]

DEFAULT_CONFLUENCE = ConfluenceConfig()
```

> Mirrors `indicators.IndicatorConfig` / `DEFAULT_CONFIG` (frozen, hashable, per-call overridable).
> **[#75 design](./75-signals-command-presets.md) (signals command + presets)** supplies `trend_follow` / `mean_revert` / `breakout` as alternate
> `ConfluenceConfig` instances (§12.3) — this issue ships only the default.

### 3.4 Direction & conviction bucketers (L5, L7)

```python
def bucket_direction(score: float, threshold: float) -> str:
    if score >= threshold:    return "long"      # inclusive (L5: score ≥ +entry_threshold)
    if score <= -threshold:   return "short"
    return "flat"

def bucket_conviction(score: float, cfg: ConfluenceConfig) -> str:
    a = abs(score)
    if a >= cfg.conviction_high:    return "High"      # |score| ≥ 0.7
    if a >= cfg.conviction_medium:  return "Medium"    # 0.4 ≤ |score| < 0.7
    return "Low"                                       # |score| < 0.4
```

- `direction` populates `MoverSignal.direction` (`Literal["long","short","flat"]`).
- `conviction` is a pure helper here; **[#80 design](./80-recommendation-builder.md) (Recommendation builder)** consumes it for
  `Recommendation.conviction` (`Literal["High","Medium","Low"]`, §14.2). Bucket edges are
  lower-inclusive (Medium `= [0.4, 0.7)`, High `= [0.7, 1]`).

### 3.5 Return contract (boundary with [#75 design](./75-signals-command-presets.md))

`confluence.py` exposes the analytical core, e.g.:

```python
def score_panel(panel: IndicatorPanel, *, config: ConfluenceConfig = DEFAULT_CONFLUENCE
                ) -> tuple[float, str, list[IndicatorVote]]:
    """Return (score in [-1,+1], direction, fully-reconciling votes) for one panel. Pure."""
```

`MoverSignal(symbol, segment, as_of, score, direction, votes, rank_in_segment)` is assembled by
**[#75 design](./75-signals-command-presets.md) (signals command)**, which adds `segment` + `rank_in_segment`. (Open sub-note: confluence could
instead return a partial `MoverSignal` with a placeholder rank — recommend the tuple to keep the
ranking concern out of the scorer; finalize in §0b/Q-E discussion.)

---

## 4. `IndicatorVote` attribution & the reconciliation invariant (§4.3, L10)

Every vote that touched `score` is recorded as an `IndicatorVote` ([`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py)):

| `IndicatorVote` field | Type | Meaning here |
|---|---|---|
| `family` | `Literal["trend","momentum","volatility","volume"]` | the emitting family (no `"candles"` — L8) |
| `name` | `str` | voter key, e.g. `"macd_hist"`, `"ema_cross"`, `"rsi"`, `"stoch"`, `"bb_pctb"`, `"obv_slope"`, `"cmf"` |
| `vote` | `float` | the `[-1,+1]` reading from §2 |
| `weight` | `float` | the coefficient applied: additive families `w_family / n_indicators`; volume votes carry their share of the `0.15` multiplier budget |

**Reconciliation invariant (asserted by the test suite).** Given `votes` + `config`, the score is
*exactly* reconstructable — no hidden term:

```
raw  = Σ_{v: v.family ∈ {trend,momentum,volatility}} ( v.weight · v.vote )
mult = combine_volume({v: v.family == "volume"}, raw, config)     # the Q-B formula
score == clip(raw · mult, -1, +1)        # within DEFAULT_TOL (1e-9)
```

Plus the **weight-budget** checks (the issue's "sum/weights reconcile" acceptance):
- `Σ trend-vote weights == w_trend` (0.40), `Σ momentum == 0.25`, `Σ volatility == 0.20`
  (after Q-C renormalization, present-only).
- `Σ volume-vote weights == w_volume` (0.15) — the multiplier budget.
- Every `|vote| ≤ 1`; final `|score| ≤ 1`.

> This is what operationalizes *"votes fully explain the score."* A reader (or
> [#80 design](./80-recommendation-builder.md)'s deterministic
> reasoning narrative, §14.2) can rank `votes` by `|weight·vote|` to produce the *"why long?"*
> top-factors list directly from the attribution — no recomputation, no second source of truth.

---

## 5. Determinism & testing plan (PRD §17, harness [`testing.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/testing.py))

### 5.1 Golden-score test — `tests/golden/test_confluence_golden.py`

- **Input:** a **hand-constructed, seeded synthetic `IndicatorPanel`** with known indicator values
  (covers a clear-long, a clear-short, a flat/near-threshold, and a **warm-up panel with keys omitted**
  to exercise Q-C). Building the panel literally (not via OHLCV) keeps the test purely about the voting
  math and maximally deterministic.
- **Lock:** the full result — `score`, `direction`, and the **entire `votes` breakdown** (every
  `family/name/vote/weight`) — serialized via `testing.to_jsonable` and compared with
  `testing.assert_matches_golden("confluence_votes_synthetic", payload, fixture_dir=..., tol=1e-9)`.
- **Marker / regen:** carries the `golden` pytest marker; regenerate the fixture intentionally with
  `TECHTRADE_REGEN_GOLDEN=1` (`testing.REGEN_ENV`) **only after Q-A…Q-E are settled and under review**.

```python
# test_confluence_golden.py (sketch)
import pytest
from pathlib import Path
from openbb_techtrade.testing import assert_matches_golden

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.golden
def test_confluence_golden():
    score, direction, votes = score_panel(SYNTHETIC_PANEL)   # SYNTHETIC_PANEL: seeded literal
    payload = {"score": score, "direction": direction, "votes": votes}
    assert_matches_golden("confluence_votes_synthetic", payload, fixture_dir=FIXTURES)
```

### 5.2 Unit tests — `tests/unit/test_confluence.py`

| Test | Asserts |
|---|---|
| reconciliation invariant | recompute `raw·mult` from `votes` + config ⇒ `== score` (≤1e-9); per-family weight budgets sum to `w_family`; volume weights sum to `0.15` (§4) |
| direction buckets | `score = ±entry_threshold` exactly ⇒ `long`/`short` (inclusive, L5); between ⇒ `flat` |
| conviction buckets | values at `0.4` and `0.7` land in the right bucket (lower-inclusive edges, L7) |
| normalization (Q-C) | dropping a present voter key changes `n_indicators` per the chosen Q-C rule (family stays full-weight under renorm); empty family ⇒ `0` contribution |
| volume neutrality | empty volume family ⇒ `multiplier == 1.0` ⇒ `score == clip(raw)` (Q-B) |
| clip at ±1 | a panel engineered past `±1` clamps to exactly `±1` (L4) |
| vote-range guard | every emitted `IndicatorVote.vote ∈ [-1,+1]` for arbitrary panels |

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -v
```

> **Determinism legs:** pure function of `(IndicatorPanel, ConfluenceConfig)`; no RNG at score time
> (the synthetic panel's seeding is fixed in the fixture), no network, no `pandas`/`pandas_ta`. Same
> inputs ⇒ byte-stable `votes` + `score`, satisfying the §11 reproducibility discipline that
> [#75 design](./75-signals-command-presets.md) / [#80 design](./80-recommendation-builder.md)
> downstream rely on.

---

## Acceptance mapping (#74)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| `engine/confluence.py`: each indicator emits a vote in `[-1,+1]` | §1 (module), §2 (per-family vote model), L4 |
| Families weighted trend `0.40` / momentum `0.25` / volatility `0.20`; volume `0.15` as confirmation multiplier | §0a L1–L2, §3.1–§3.2 (formula + multiplier) |
| Composite `score ∈ [-1,+1]` | §3.1 (`clip`, L4) |
| Per-indicator `IndicatorVote` attribution | §4 (`family/name/vote/weight`), §2 voter roster |
| Direction bucketing (long/short/flat) | §3.4 `bucket_direction`, L5–L6 |
| Conviction bucket from `\|score\|` | §3.4 `bucket_conviction`, L7 |
| Golden-score unit test with full vote breakdown | §5.1 (`assert_matches_golden`, `golden` marker, regen env) |
| Composite score reproduces a golden value | §5.1 golden lock |
| `votes` fully explain the score (sum/weights reconcile) | §4 reconciliation invariant + weight-budget checks; §5.2 reconciliation test |
| Weights reflect the Q4 decision | §0a L1–L2 (RESOLVED), §3.3 `ConfluenceConfig` defaults |
| (Depends) consumes #73 hybrid `IndicatorPanel`; (Depends) #64 Q4 weights | §1 boundary rules; §0a |

> **Gate before implementation:** resolve **Q-A…Q-E (§0b)** with the user. Each one changes the locked
> numbers, so the golden fixture (§5.1) is authored *after* those decisions, not before.
