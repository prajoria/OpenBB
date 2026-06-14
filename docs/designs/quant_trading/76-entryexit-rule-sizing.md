# 76 — EntryExitRule + Risk-Based Sizing (ATR Stop / R-Target / Time-Stop)

**GitHub:** [#76](https://github.com/prajoria/OpenBB/issues/76) · **Phase:** P4 · **Sprint:** 4 · **Size:** M
**Depends on:** [#75](https://github.com/prajoria/OpenBB/issues/75) (signals command + 3 presets + golden-score test → `MoverSignal`)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §13 (Entry/Exit & Order Generation), §20 Q6 (sizing inputs), privacy §4.7 (Guiding Principle 7)
**Scope:** Add the pure rules engine that turns one `MoverSignal` + an `ATR(14)` value + a
reference price into deterministic **entry / stop / target levels** and a **risk-based share
size**, plus Decimal unit tests for the sizing and level math. No orders, no fills, no network.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

An **EntryExitRule** is the small bundle of risk parameters that converts a *directional opinion*
into an *executable plan*: where to get in, where to bail if wrong (the **stop**), where to take
profit (the **target**), and how long to wait before giving up (the **time stop**). Upstream,
[#74 confluence voting](./74-confluence-voting-score.md) produced a `MoverSignal` — a score in
`[-1,+1]` plus a `long`/`short`/`flat` direction. That tells you *which way*, but not *how much* or
*at what prices*. This step answers those two questions deterministically.

**Risk-based sizing** is the discipline of deciding share count from how much you are willing to
*lose*, not how much you want to *spend*. You pick a small **risk budget** per trade (e.g. 1% of an
abstract account notional) and a **stop distance** (here `atr_stop_mult · ATR`, so the stop is a
volatility-scaled cushion away from entry). The share count then falls out of one formula —
`qty = floor(risk_budget / (atr_stop_mult · ATR))` — so a more volatile stock (bigger ATR) is sized
*smaller* and a calmer one *larger*, holding the dollar-risk-if-stopped roughly constant across very
different symbols. The **stop** sits `atr_stop_mult` ATRs away from entry; the **target** at
`target_r_multiple` times that same stop distance (a "2R" target risks 1 to make 2); the **time
stop** caps how many bars a position may be held. Every money/quantity value uses `Decimal` so cents
and share counts never drift on float rounding.

This module is deliberately **pure and offline**: it takes `(signal, atr, ref_price, rule, sizing)`
and returns levels + size, importing only `models` + stdlib `decimal`/`math` — no network, no
pandas-ta. It computes the **static** plan; the **temporal** exits (opposite-signal cross, time stop)
are *parameters that travel with the plan* and are fired later, bar-by-bar, by the paper-fill
simulator ([#78 design](./78-paperbroker-fill-sim.md)). Order objects themselves are materialized by
[#77 order generation](./77-order-generation-tradeplan.md). #76 owns the numbers; it does not run the
clock or emit orders.

---

## 0. Key decisions (locked) + Open questions

### 0.1 Locked (from models.py + PRD §13 / §20 Q6)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | `EntryExitRule` parameter defaults | **Consumed as-is from `models.py`** — `entry_threshold=0.4`, `exit_on_opposite=True`, `atr_stop_mult=2.0`, `target_r_multiple=2.0`, `max_holding_bars=20` | #76 does **not** modify `EntryExitRule`; it is the input params bundle, not a new model |
| L2 | Sizing inputs (Q6 **RESOLVED**) | **Abstract notional by default** — explicit `account_size` (Decimal notional) + `risk_per_trade` (float fraction); no implicit holdings read; optional local `portfolio_app` may supply the notional but is **never required, never default** | Privacy-safe (§4.7): outward artifacts carry shares + percent-of-notional, never personal dollars |
| L3 | Sizing formula (§13) | `qty = floor(risk_budget / (atr_stop_mult · ATR))`, with `risk_budget = risk_per_trade · account_size` | Denominator `atr_stop_mult · ATR` **is** the per-share risk (= stop distance) — sizing and levels share one quantity |
| L4 | Numeric types | **Decimal** for money/qty (`account_size`, `risk_budget`, `entry/stop/target`, `quantity`, per-share risk); **float** for ratios (`score`, `risk_per_trade`, `atr` off the panel, `*_pct`, `risk_reward`) | Matches `models.py` field typing; ATR/`risk_per_trade` are quantized **into** Decimal at the boundary (Q-B) |
| L5 | Level formulas (§13) | `stop = entry ∓ atr_stop_mult · ATR`; `target = entry ± target_r_multiple · (entry − stop)` | Sign folds on `direction` (long/short); `(entry − stop)` magnitude = per-share risk = `atr_stop_mult · ATR` (L3) |
| L6 | ATR source | `IndicatorPanel.volatility["atr"]` — **ATR(14)** from `engine/indicators.py` `IndicatorConfig.atr_length = 14` (built by #72 panel / #73 selector) | #76 **never recomputes** ATR; it receives the as_of scalar from the caller — pure, no pandas-ta |
| L7 | Module posture | **Pure / offline / deterministic** — `rules.py` depends on `models` (+ stdlib `decimal`, `math`) only | Unit-testable without `openbb.build()`; same `(signal, atr, ref_price, config)` → identical `(levels, size)` |
| L8 | Pre-fill boundary | #76 produces the **static plan** (entry gate + levels + size) from a **reference price**; the **realized** entry price is fixed downstream at the paper fill | Stop/target are computed as **distances off a reference**; #78 (PaperBroker fill sim) supplies the realized entry (§13 bar-*t* → *t+1*) |

> **Locked, but do not re-open Q6.** The *value* of the Q6 decision (abstract `account_size` +
> `risk_per_trade`) is settled. What is **not** yet settled is *where those two fields live as a
> model* — that is Q-A below, a genuine model-addition to brainstorm.

### 0.2 Open questions (please review / brainstorm)

| # | Question | Why it matters | Straw default to react to |
|---|---|---|---|
| **Q-A** | **Where do `account_size` + `risk_per_trade` live?** A new `SizingConfig` (or `RiskConfig`) `Data` model, vs. extra fields tacked onto an existing config object. **Neither field exists in `models.py` today — this is a model addition.** Defaults? | These two inputs gate all sizing (L2/L3). They are not on `EntryExitRule` (which is pure level/threshold params) and not anywhere else yet. | New leaf `SizingConfig(Data)` with `account_size: Decimal = Decimal("100000")`, `risk_per_trade: float = 0.01`; optional `portfolio_app` hook stays out of the model |
| **Q-B** | **Decimal discipline at the float→Decimal boundary.** ATR arrives as **float** off the panel (L6); `risk_per_trade` is a float fraction. How/where are they quantized to Decimal for level + size math? Which **rounding mode** (`ROUND_HALF_EVEN`?) and **price tick** (quantize levels to cents `0.01`?)? And what is the **`entry` reference price** — the as_of `close`, a next-bar-open placeholder, or left **symbolic** until the #78 (paper fill) realizes it? | Float artifacts (`0.1+0.2`) must not leak into money. Tick + rounding choices change golden values. #76 is **pre-fill** (L8), so the "entry" it uses is a *reference*, with the realized fill price finalized in #78. | `Decimal(str(atr))` / `Decimal(str(risk_per_trade))` at the boundary; levels quantized to `Decimal("0.01")` with `ROUND_HALF_EVEN`; qty floored with `ROUND_FLOOR`; `entry = ref_price` (as_of close) carried as a **reference**, re-stamped at the #78 fill |
| **Q-C** | **Long / short / flat handling.** Stop **below** entry for long / **above** for short; target the opposite side. How is `direction == "flat"` handled? And is the **entry gate** `\|score\| ≥ rule.entry_threshold` (recompute) or simply `signal.direction != "flat"` (trust #74's resolution)? | Sign errors invert the whole plan. `entry_threshold` (0.4) lives on `EntryExitRule`, but #74/#75 already resolved `direction` — two thresholds risk disagreeing. | Sign-fold on `direction` (`sign=+1` long, `−1` short); `flat` → **no levels, size 0, no trade**; entry gate = `\|score\| ≥ rule.entry_threshold` **and** `direction != "flat"` (assert consistency with upstream in a test) |
| **Q-D** | **Sizing edge-cases.** `risk_budget = risk_per_trade · account_size`. What if `ATR ≤ 0` / `NaN` (division guard)? Floor to **whole shares** (Decimal→int)? Are **fractional shares** ever allowed? What if `risk_budget < risk_per_share` (size rounds to 0)? | A zero/NaN ATR is a div-by-zero; floor vs. round changes the share count; size-0 must be a clean "no trade", not a crash. | `ATR ≤ 0` or non-finite → **size 0, no trade**; `floor` to whole shares (`ROUND_FLOOR`); no fractional shares in v1; `qty == 0` is a valid "skip" outcome |
| **Q-E** | **The #76 ↔ #77 ↔ #78 seam.** Does #76 emit `Order` objects, or only the **rule + levels + size** struct that #77 turns into orders? And is the static plan the *whole* job, given `exit_on_opposite` / `max_holding_bars` are **temporal** triggers evaluated over a bar sequence? | Keeps #76 a pure function and avoids duplicating #77's Order materialization. The dynamic exits fire during simulation, not at single-bar `apply`. | #76 = `apply(signal, atr, ref_price, rule, sizing) -> RuleResult` (levels + size + per-share risk); **#77 (order generation + TradePlan)** materializes the `Order` list; **#78 (paper fill sim)** evaluates opposite-cross / time-stop bar-by-bar. Result-struct shape (new `Data` model vs. plain dataclass) is part of this question |

Each open question carries an approvable placeholder (mirroring the PRD §20 convention): a concrete
**Recommendation** restating the straw default, plus an **Answer** line for the user to sign off.

#### Q-A — Where do `account_size` + `risk_per_trade` live?

A new `SizingConfig` (or `RiskConfig`) `Data` model, versus extra fields tacked onto an existing
config object. Neither field exists in [`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py)
today, so this is a genuine model addition. These two inputs gate all sizing (L2/L3).

- **Recommendation:** add a new leaf `SizingConfig(Data)` with
  `account_size: Decimal = Decimal("100000")` and `risk_per_trade: float = 0.01`; keep the optional
  `portfolio_app` hook out of the model (opt-in, supplied at the call site only).
- **Answer:** _(pending approval)_

#### Q-B — Decimal discipline at the float→Decimal boundary

ATR arrives as **float** off the panel (L6) and `risk_per_trade` is a float fraction. How/where are
they quantized to Decimal for level + size math, which rounding mode and price tick, and what is the
`entry` reference price — the as_of `close`, a next-bar-open placeholder, or symbolic until the #78
paper fill realizes it?

- **Recommendation:** quantize at the boundary with `Decimal(str(atr))` / `Decimal(str(risk_per_trade))`;
  round levels to cents `Decimal("0.01")` with `ROUND_HALF_EVEN`; floor qty with `ROUND_FLOOR`; carry
  `entry = ref_price` (as_of close) as a **reference**, re-stamped at the
  [#78 fill](./78-paperbroker-fill-sim.md).
- **Answer:** _(pending approval)_

#### Q-C — Long / short / flat handling + the entry gate

Stop below entry for long, above for short, target on the opposite side. How is
`direction == "flat"` handled, and is the entry gate `|score| ≥ rule.entry_threshold` (recompute) or
simply `signal.direction != "flat"` (trust #74's resolution)? Sign errors invert the whole plan, and
two thresholds risk disagreeing.

- **Recommendation:** sign-fold on `direction` (`sign=+1` long, `−1` short); `flat` → **no levels,
  size 0, no trade**; entry gate = `|score| ≥ rule.entry_threshold` **and** `direction != "flat"`,
  asserting consistency with the upstream [#74](./74-confluence-voting-score.md) resolution in a test.
- **Answer:** _(pending approval)_

#### Q-D — Sizing edge-cases (ATR guard, floor, fractional shares)

With `risk_budget = risk_per_trade · account_size`: what happens if `ATR ≤ 0` / `NaN` (division
guard)? Floor to whole shares? Are fractional shares ever allowed? What if
`risk_budget < risk_per_share` so the size rounds to 0?

- **Recommendation:** `ATR ≤ 0` or non-finite → **size 0, no trade** (no division); `floor` to whole
  shares (`ROUND_FLOOR`); no fractional shares in v1; treat `qty == 0` as a valid "skip" outcome, not
  an error.
- **Answer:** _(pending approval)_

#### Q-E — The #76 ↔ #77 ↔ #78 seam

Does #76 emit `Order` objects, or only the rule + levels + size struct that #77 turns into orders?
And is the static plan the whole job, given `exit_on_opposite` / `max_holding_bars` are temporal
triggers evaluated over a bar sequence?

- **Recommendation:** #76 returns `apply(signal, atr, ref_price, rule, sizing) -> RuleResult`
  (levels + size + per-share risk only); [#77](./77-order-generation-tradeplan.md) materializes the
  `Order` list; [#78](./78-paperbroker-fill-sim.md) evaluates opposite-cross / time-stop bar-by-bar.
  Make `RuleResult` a new `Data` model (not a plain dataclass) for OBBject-friendly serialization.
- **Answer:** _(pending approval)_

---

## 1. Module layout (new)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
└── rules.py            # NEW — the pure rules engine:
                        #   • apply(signal, atr, ref_price, *, rule, sizing) -> RuleResult
                        #   • level math (entry/stop/target) with long/short sign-fold (§2)
                        #   • risk-based sizing  qty = floor(risk_budget / (atr_stop_mult·ATR))  (§3)
                        #   • Decimal-only money/qty; float ratios; ATR/fraction quantized at the boundary
                        #   Depends on models (+ stdlib decimal, math) ONLY. No network, no pandas-ta.

openbb_platform/extensions/techtrade/openbb_techtrade/models.py
                        # CHANGED (Q-A) — add SizingConfig(Data): account_size: Decimal,
                        #   risk_per_trade: float.  Possibly add a RuleResult(Data) carrier (Q-E).

openbb_platform/extensions/techtrade/tests/unit/
└── test_rules.py       # NEW — golden Decimal examples for level math + sizing;
                        #   long / short / flat; ATR≤0 & NaN guards; floor behaviour; determinism.
```

**Module-boundary rules**
- `rules.py` is **pure**: it takes `(MoverSignal, atr: float, ref_price: Decimal, rule: EntryExitRule,
  sizing: SizingConfig)` and returns levels + size. It performs **no** I/O and imports nothing from
  the engine except `models` — so it is unit-testable without `openbb.build()`.
- ATR is **passed in** (L6). `rules.py` never imports pandas-ta / `indicators.py` / `selector.py`;
  the caller (eventually #77 order generation) reads `IndicatorPanel.volatility["atr"]` and hands it
  over. This keeps the rules engine independent of the indicator stack.
- The float→Decimal quantization (Q-B) happens **once**, at the top of `apply`, so the body is
  all-Decimal. No float money ever escapes.

---

## 2. `EntryExitRule` semantics (PRD §13)

The five §13 behaviours and where each is *defined* (#76) vs. *fired* (downstream):

| §13 behaviour | Rule field (`EntryExitRule`) | Definition (#76) | Fired by |
|---|---|---|---|
| **Entry** — `\|score\|` crosses `entry_threshold` in a direction | `entry_threshold=0.4` | Gate: open a plan only when `\|score\| ≥ entry_threshold` and `direction ≠ flat` (Q-C) | #77 (order generation) emits the entry `Order` |
| **Stop** — `entry ∓ atr_stop_mult·ATR` | `atr_stop_mult=2.0` | Static stop **level** off the reference entry (§2.1) | #78 evaluates touch intrabar |
| **Target** — `entry ± target_r_multiple·(entry−stop)` | `target_r_multiple=2.0` | Static target **level** (§2.1) | #78 evaluates touch intrabar |
| **Signal exit** — opposite-direction cross | `exit_on_opposite=True` | Carried through as a rule flag | #78 / sim evaluates over the bar sequence (temporal) |
| **Time exit** — `max_holding_bars` reached | `max_holding_bars=20` | Carried through as a rule field | #78 / sim counts bars held (temporal) |

> **Static vs. temporal split.** #76 computes the **static** plan — the entry gate plus the
> stop/target **levels** and the **size** — deterministically from a single `(signal, atr,
> ref_price)`. The **temporal** exits (`exit_on_opposite`, `max_holding_bars`) are *rule parameters*
> that travel with the plan and are evaluated bar-by-bar during the paper simulation in
> **#78 (PaperBroker fill sim)**. #76 owns the numbers; it does not run the clock.

### 2.1 Level formulas (long / short sign-fold)

Let `R = atr_stop_mult · ATR` be the **per-share risk** (a positive Decimal magnitude = the stop
distance), and `sign = +1` for `direction == "long"`, `−1` for `"short"`. Then the §13 `∓ / ±`
formulas collapse to:

```
R       = atr_stop_mult · ATR                  # per-share risk = stop distance (Decimal)
entry   = ref_price                            # reference (realized at the #78 fill, L8/Q-B)
stop    = entry − sign · R
target  = entry + sign · target_r_multiple · R
```

| `direction` | `entry` | `stop` | `target` | Note |
|---|---|---|---|---|
| `long`  (`sign=+1`) | `ref` | `ref − R` (below) | `ref + target_r_multiple·R` (above) | `(entry − stop) = +R` |
| `short` (`sign=−1`) | `ref` | `ref + R` (above) | `ref − target_r_multiple·R` (below) | `(entry − stop) = −R`; §13 `±` yields a below-entry target |
| `flat`  | — | — | — | no levels, size 0, no trade (Q-C) |

> **One quantity, two uses.** `(entry − stop)` magnitude equals `R = atr_stop_mult · ATR`, which is
> exactly the **sizing denominator** in §3. So "risk per share" is computed once and feeds both the
> target's R-multiple and the share count — they cannot disagree. (This is the `risk_per_share`
> Decimal that the #80 Recommendation builder later surfaces.)

---

## 3. Risk-based sizing (PRD §13 + §20 Q6)

```
risk_budget    = risk_per_trade · account_size            # Decimal money (e.g. 0.01 · 100000 = 1000)
risk_per_share = atr_stop_mult · ATR                      # Decimal, = R from §2.1 (stop distance)
qty            = floor(risk_budget / risk_per_share)      # Decimal → whole shares
```

- **Inputs (Q-A, Q6-locked):** `account_size` (Decimal notional) and `risk_per_trade` (float
  fraction) come from a **`SizingConfig`** — abstract by default (`Decimal("100000")`, `0.01`), never
  read from personal holdings. An optional local `portfolio_app` *may* supply `account_size` when run
  locally, but is never required and never the default.
- **Guards (Q-D):** if `ATR ≤ 0` or non-finite → `risk_per_share` is 0/invalid → **size 0, no trade**
  (no division). If `risk_budget < risk_per_share` → `floor` yields **0 shares** → a clean "skip",
  not an error.
- **Floor (Q-D):** `qty` floors to **whole shares** (`Decimal.quantize(Decimal("1"), ROUND_FLOOR)`,
  then `int`). No fractional shares in v1.

### 3.1 Decimal quantization boundary (Q-B)

| Quantity | Arrives as | Converted to Decimal by | Quantize / rounding |
|---|---|---|---|
| `atr` | **float** (panel `volatility["atr"]`) | `Decimal(str(atr))` | — (raw magnitude) |
| `risk_per_trade` | **float** fraction | `Decimal(str(risk_per_trade))` | — |
| `account_size` | **Decimal** (already) | — | — |
| `risk_budget`, `risk_per_share` | computed | Decimal arithmetic | intermediate full precision |
| `entry / stop / target` | computed | Decimal arithmetic | **`Decimal("0.01")` cents, `ROUND_HALF_EVEN`** (Q-B straw) |
| `quantity` | computed | Decimal division | **`Decimal("1")`, `ROUND_FLOOR`** → `int` |

> **Privacy normalization (§4.7 / Principle 7).** The sizing **output is shares + per-share risk +
> percent-of-notional**, never a personal dollar P&L. Because `account_size` defaults to an
> **abstract** notional, nothing #76 emits reveals an account balance — the outward artifact is
> normalized by construction. Personal dollar amounts only ever appear if a user runs locally against
> `portfolio_app`, which is opt-in and out of scope here.

---

## 4. Determinism & testing (`tests/unit/test_rules.py`)

Pure function of `(signal, atr, ref_price, rule, sizing)` → identical `(levels, size)`. All money/qty
assertions use **Decimal equality** (no float tolerance) against hand-computed golden values.

| Test | Inputs | Expected (Decimal) | Asserts |
|---|---|---|---|
| `test_long_levels` | `ref=100.00, ATR=2.50, mult=2.0, R-mult=2.0, long` | `entry=100.00, stop=95.00, target=110.00, risk_per_share=5.00` | §2.1 long sign-fold + cents quantize |
| `test_short_levels` | `ref=50.00, ATR=1.00, mult=2.0, R-mult=2.0, short` | `entry=50.00, stop=52.00, target=46.00, risk_per_share=2.00` | §2.1 short sign-fold (stop above, target below) |
| `test_size_honors_budget` | `account=100000, risk=0.01, ATR=2.50, mult=2.0` | `risk_budget=1000.00, risk_per_share=5.00, qty=200` | §3 formula; `qty` honors the 1%-of-notional budget |
| `test_size_floor` | `account=100000, risk=0.01, ATR=1.50, mult=2.0` | `risk_budget=1000.00, risk_per_share=3.00, qty=333` (`1000/3 = 333.33…`) | floor to whole shares, no fractional |
| `test_flat_no_trade` | `direction=flat` | no levels, `qty=0` | Q-C flat handling — size 0, no plan |
| `test_atr_zero_guard` | `ATR=0` | `qty=0`, no trade | Q-D div guard (no `ZeroDivisionError`) |
| `test_atr_nan_guard` | `ATR=NaN` | `qty=0`, no trade | Q-D non-finite guard |
| `test_entry_gate_threshold` | `\|score\| < entry_threshold` | no plan | Q-C entry gate consistent with `direction != flat` |
| `test_decimal_typing` | any long | `type(stop) is Decimal`, `type(qty) is int`, `type(risk_per_share) is Decimal` | L4 Decimal discipline; no float money leaks |
| `test_deterministic` | same inputs ×2 | identical struct | L7 determinism |

Worked example (golden `test_size_honors_budget`, long):

```
ATR = 2.50, atr_stop_mult = 2.0  →  R = risk_per_share = Decimal("5.00")
ref = 100.00                     →  entry 100.00, stop 95.00, target 110.00
account_size = 100000, risk_per_trade = 0.01  →  risk_budget = Decimal("1000.00")
qty = floor(1000.00 / 5.00) = 200 shares
```

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_rules.py -m "not integration" -v
```

---

## Acceptance mapping (#76)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| Given a signal + ATR, rule yields **entry/stop/target + size deterministically** | §2.1 level math + §3 sizing; §4 determinism test (L7) |
| `EntryExitRule` covers entry-threshold cross, exit-on-opposite, ATR stop, R-target, time stop | §2 behaviour table (static levels here; temporal exits carried for #78) |
| **Risk-based sizing** `qty = floor(risk_budget / (atr_stop_mult·ATR))` | §3 formula + §0 L3; `risk_budget = risk_per_trade·account_size` |
| **ATR(14)** stop + **R-multiple** target levels from the rule | §2.1 (`R = atr_stop_mult·ATR`); §0 L6 ATR(14) source = `IndicatorConfig.atr_length=14` |
| **Sizing honors risk budget** | §3 + `test_size_honors_budget` / `test_size_floor` |
| **Uses Decimal** (money/qty) | §0 L4, §3.1 quantization, §4 `test_decimal_typing` |
| **Unit tests for sizing + level math (Decimal)** | §4 `test_rules.py` golden examples |
| Reflects **Q6** sizing-input decision (**abstract notional default**) | §0 L2, §3 `SizingConfig` (Q-A), §3.1 privacy normalization (§4.7) |
| (Privacy §4.7) normalized notional, no personal dollars | §3.1 — shares + percent-of-notional out; abstract `account_size` default |
| Pre-fill seam to #77 (order gen) / #78 (paper fill) | §0 L8, Q-E — #76 returns levels + size struct only |
