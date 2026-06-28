# 80 — Recommendation Builder (Levels / Stop-Gaps / R:R / Conviction / Reasoning)

**GitHub:** [#80](https://github.com/prajoria/OpenBB/issues/80) · **Phase:** P5 · **Sprint:** 5 · **Size:** M
**Depends on:** [#78](https://github.com/prajoria/OpenBB/issues/78) (PaperBroker fill sim → realized `entry_price`)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §14.2 (Recommendation builder), §9.3 (`Recommendation` model), §13 (levels / sizing)
**Scope:** Add the pure builder in `engine/execution.py` that turns a **paper-filled `TradePlan`**
(realized entry from [#78](https://github.com/prajoria/OpenBB/issues/78), levels + size from [#76](https://github.com/prajoria/OpenBB/issues/76), votes from [#74](https://github.com/prajoria/OpenBB/issues/74)) into a fully-populated
`Recommendation` — action/conviction, entry/stop/target + stop-gaps + R:R + ATR, sizing/risk fields,
and a **deterministic, non-LLM** `reasoning` / `top_factors` / `caveats` narrative that traces back to
the signal's `votes`. No orders, no fills, no network, no LLM.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

> **⚠ This is a PLANNING / brainstorming doc.** The `Recommendation` field set, conviction buckets,
> and the §14.2 distance/R:R formulas are **locked** (§0.1). The **reasoning-template grammar** (Q-A),
> `top_factors`/`caveats` derivation (Q-B/Q-C), the **FLAT / no-fill `entry_price`** edge case (Q-D),
> and the `risk_pct_of_notional` formula (Q-E) are **open** — surfaced for review before any code.

---

## What this is

A **Recommendation** is the final, human-readable verdict the techtrade pipeline produces for one
symbol: a plain-English *"this is a BUY / SELL_SHORT / HOLD, here's how confident, here's where to
enter, stop, and target, here's how big, and here's **why**."* It is the last step that turns a
machine's numbers into something a person can read, act on, and audit. Every earlier stage fed this
one: [#74 confluence voting](./74-confluence-voting-score.md) produced the directional `score` and the
per-indicator `votes`; [#76 entry/exit + sizing](./76-entryexit-rule-sizing.md) produced the levels
and share size; [#77 order generation](./77-order-generation-tradeplan.md) packaged them into a
`TradePlan`; [#78 the paper broker](./78-paperbroker-fill-sim.md) realized the actual entry price.
This builder collects all of it and **populates every field** of the `Recommendation` model.

Three of those fields are prose: **`reasoning`** (a 2–4 sentence narrative), **`top_factors`** (the
handful of indicators that mattered most), and **`caveats`** (the "but watch out for…" warnings). The
defining design choice here is that this narrative is **deterministic and non-LLM** — it is generated
from a fixed *template* driven entirely by the signal's `votes`, not by a language model. That matters
for two reasons: it is **auditable** (every phrase traces back to a specific indicator vote, so you
can always answer *"why does it say that?"*), and it is **golden-lockable** (the exact string is
stable across runs, so a regression test can pin it). The builder also computes the derived risk
geometry — stop-distance %, target-distance %, and the **risk:reward ratio** — from the *actual*
levels, so any drift between the planned and realized entry is reflected honestly rather than hidden.

The module is **pure, offline, and deterministic**: it imports only `models` (+ stdlib `decimal` /
`math`), recomputes nothing (it carries every number through from upstream and only *derives* gaps and
*renders* prose), and feeds two consumers — the [#81 Excel export](./81-excel-export.md) (one row per
recommendation) and, optionally, an agent layer that may rewrite the prose but never replaces the
shipped template. An optional later agent rewrite is out of scope; the template is what ships.

---

## 0. Key decisions — locked vs open

### 0.1 Locked (from `models.py` + PRD §14.2 / §9.3 / §13)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | `Recommendation` schema | **Consumed as-is from `models.py`** (scaffolded by [#71](https://github.com/prajoria/OpenBB/issues/71)). #80 **populates every field**, defines no new model | All 20 fields fixed: `symbol/segment/as_of`, `action`, `conviction`, `score`, `entry_price/stop_price/target_price` (Decimal), `stop_distance_pct/target_distance_pct/risk_reward/atr` (float), `position_size/risk_per_share` (Decimal), `risk_pct_of_notional` (float), `time_stop_bars` (int\|None), `reasoning` (str), `top_factors` (list[str]), `caveats` (str) |
| L2 | Action from direction | `long → BUY`, `short → SELL_SHORT`, `flat → HOLD/FLAT` | `action: Literal["BUY","SELL_SHORT","HOLD/FLAT"]`; pure map off `signal.direction` |
| L3 | Conviction buckets | `\|score\| ≥ 0.7` → **High**; `0.4 ≤ \|score\| < 0.7` → **Medium**; `< 0.4` → **Low** (lower-inclusive edges) | Reuse [#74](https://github.com/prajoria/OpenBB/issues/74)'s `confluence.bucket_conviction` (single source of truth) — see §3 / Q-note |
| L4 | Distance / R:R formulas (§14.2, §9.3) | `stop_distance_pct = \|entry − stop\| / entry`; `target_distance_pct = \|target − entry\| / entry`; `risk_reward = \|target − entry\| / \|entry − stop\|` | Computed from the **actual** levels (not echoed from `target_r_multiple`), so quantization/realized-fill drift is reflected honestly |
| L5 | Numeric discipline | **Decimal** for prices/sizing (`entry_price/stop_price/target_price/position_size/risk_per_share`); **float** for ratios/pcts (`score/stop_distance_pct/target_distance_pct/risk_reward/atr/risk_pct_of_notional`) | Matches `models.py` typing; distances computed in **Decimal** then cast to `float` at the boundary — no float money math (§2) |
| L6 | `reasoning` is the **source of truth** | A **deterministic, templated, non-LLM** 2–4 sentence narrative from `MoverSignal.votes`. The optional agent layer (§16) *may* rewrite prose, but the template is what ships when the agent is absent | Auditable + golden-lockable; no network, no model call (§4) |
| L7 | Builder posture | **Pure / offline / deterministic** — `execution.py` depends on `models` (+ stdlib `decimal`, `math`) only; consumes a **paper-filled `TradePlan`**; **never** recomputes votes ([#74](https://github.com/prajoria/OpenBB/issues/74)), levels/sizing ([#76](https://github.com/prajoria/OpenBB/issues/76)), or fills ([#78](https://github.com/prajoria/OpenBB/issues/78)) | Same `TradePlan` in ⇒ identical `Recommendation` (string-stable) out; unit-testable without `openbb.build()` |
| L8 | Auditability | `reasoning`, `top_factors`, `caveats` are derived **only** from `signal.votes` (`IndicatorVote.family/name/vote/weight`) + the levels/rule on the plan — no second source of truth | Acceptance "traces to the signal's votes" is a direct invariant (§4, §5) |

### 0.2 Open questions (please review / brainstorm)

> **Q-A — the reasoning-template grammar (THE central item).** §14.2 gives **one** example sentence;
> the exact templated phrasing per family × direction × strength must be *designed*. §4 proposes a
> skeleton — confirm the slot count, the phrase bank, and (the headline tension) **where raw readings
> come from**: the §14.2 example embeds raw indicator values (*"ADX 28, EMA20>EMA50, RSI 62"*), but
> `IndicatorVote` carries **only** `vote ∈ [-1,+1]` and `weight` — **not** the raw reading. Reconcile:
>
> | Opt | Source of the parenthetical detail | Pros | Cons |
> |---|---|---|---|
> | **A1 — votes-only (RECOMMEND)** | polarity tokens from votes (`"MACD+"`, `"EMA cross+"`, `"RSI+"`) — no raw numbers | Pure trace to `votes` (L8); no panel coupling; golden-stable | Loses the literal *"RSI 62"* flavour of the §14.2 example |
> | **A2 — builder also takes `IndicatorPanel`** | raw readings (`rsi=62`, `adx=28`) pulled from the panel that produced the votes | Matches the §14.2 example verbatim | Couples #80 to the panel; weakens "traces to **votes**" (two sources); panel must be threaded onto the `TradePlan` (it is **not** there today) |
> | **A3 — extend `IndicatorVote` with a `reading: float`** | each vote carries its own raw value | One source, richest narrative | **Model change touching [#74](https://github.com/prajoria/OpenBB/issues/74)** + every golden it locked; out of #80's "no new models" remit |
>
> Recommend **A1** (votes-only) for v1, with the parenthetical as polarity tokens; revisit A3 if the
> prose must show raw numbers. **This choice gates `top_factors` formatting (Q-B) too.**
>
> - **Recommendation:** A1 — votes-only polarity tokens (`"MACD+"`, `"RSI+"`), keeping the narrative a
>   pure trace to `signal.votes` (L8) with no panel coupling; revisit A3 only if raw readings become a
>   hard requirement.
> - **Answer (Review):** ✅ **Approved — A1 (votes-only polarity tokens).**
>
>   1. **A1 preserves the auditability invariant (L8).** Every phrase traces to an `IndicatorVote`,
>      which traces to a panel indicator. The chain is clean: one source of truth, one mapping.
>      A2 would introduce a second source (`IndicatorPanel`) that must be threaded through the entire
>      pipeline — a coupling cost with no user-visible benefit in v1.
>
>   2. **No panel on `TradePlan` today.** A2 requires the `IndicatorPanel` to reach the builder,
>      but the `TradePlan` doesn't carry it. Adding it would be a model change touching #74, #77,
>      and every golden downstream. Not worth it for parenthetical detail.
>
>   3. **Polarity tokens are readable.** `"MACD+"`, `"RSI+"`, `"EMA cross−"` are concise and
>      self-explanatory. A user reading `"momentum confirming (RSI+, MACD+)"` understands the
>      signal; the exact `RSI=62` value is secondary context the user can always look up.
>
>   4. **A3 is the right future path.** If raw readings become a hard requirement (e.g., for a
>      richer agent-layer narrative), extending `IndicatorVote` with an optional `reading: float`
>      is clean and backward-compatible. But that's a future issue, not #80.

> **Q-B — `top_factors` selection + format.** Rank `signal.votes` by **`\|weight · vote\|`** (the [#74](https://github.com/prajoria/OpenBB/issues/74)
> §4 attribution key, descending) and take the top-**K**. **K = 3** (matches the §9.3 example length).
> Per-factor string: `"{NAME}{±} ({family})"` e.g. `"MACD+ (trend)"`, `"RSI+ (momentum)"`,
> `"OBV+ (volume)"` (raw-number form `"RSI 62"` only if Q-A=A2/A3). **Tie-break:** `\|weight·vote\|`
> desc → family canonical order `(trend, momentum, volatility, volume)` → `name` alpha. Drop
> near-zero contributors (`\|weight·vote\| ≤ ε`). **Open:** K=3 fixed or configurable? include volume
> votes (they carry a share of the `0.15` multiplier budget, so `weight·vote` is defined)? format
> exact string?
>
> - **Recommendation:** rank by `|weight·vote|` desc, **K = 3** (configurable via the builder config,
>   default 3), **include** volume votes, format each as `"{NAME}{±} ({family})"`, tie-break
>   `|weight·vote|` → family canonical order → name alpha, dropping near-zero contributors.
> - **Answer (Review):** ✅ **Approved — follow recommendation.**
>
>   1. **`|weight·vote|` as the ranking key — correct.** This is the same attribution key #74 §4
>      uses to reconcile votes to the composite score. Reusing it for `top_factors` means the
>      factors that appear are the ones that *actually moved the score* — faithful by construction.
>
>   2. **K=3 configurable — correct.** K=3 matches the §9.3 example length and is a sensible
>      default for a 2–4 sentence narrative. Making it configurable (via the builder config)
>      costs nothing and lets power users adjust.
>
>   3. **Include volume votes — correct.** Volume carries a `0.15` multiplier budget. If OBV
>      or CMF fires strongly, its `|weight·vote|` contribution is real. Excluding volume would
>      hide a meaningful factor from `top_factors`.
>
>   4. **Format `"{NAME}{±} ({family})"` — clean and readable.** The family in parens adds
>      context without clutter. The tie-break chain (magnitude → family order → alpha) is
>      total and deterministic.

> **Q-C — `caveats` triggers + deterministic ordering.** Which conditions raise a caveat, and in what
> fixed precedence? Proposed trigger set (each a short clause, joined in this order):
>
> | # | Trigger (deterministic predicate over the plan) | Example clause |
> |---|---|---|
> | 1 | **Validation** ([#82](https://github.com/prajoria/OpenBB/issues/82)): `plan.validation` present and failing / high overfit-prob | *"validation flags overfitting"* |
> | 2 | **No paper fill:** `action ≠ HOLD/FLAT` but `simulated_fills` has no entry fill | *"no paper fill — levels are planned, not realized"* |
> | 3 | **Volume divergence:** a `volume` vote opposes `sign(score)` | *"volume diverging from price"* |
> | 4 | **Intra-family disagreement:** two voters in one family with opposite signs (e.g. `macd_hist+` vs `ema_cross−`) | *"trend votes split"* |
> | 5 | **Borderline conviction:** `entry_threshold ≤ \|score\| < entry_threshold + δ` (e.g. `[0.40, 0.50)`) | *"borderline conviction"* |
> | 6 | **Missing family:** a family absent from the panel (warm-up / short history) ⇒ omitted from voting | *"momentum unavailable (short history)"* |
>
> **Open:** the full trigger set + the δ band (5); whether `plan.validation` (typed `Data \| None`,
> [#82](https://github.com/prajoria/OpenBB/issues/82)) is even available at #80's call site; and the **empty representation** — `caveats` is a
> required `str` (not Optional), so when nothing triggers, ship `""` or a benign `"None."`?
>
> - **Recommendation:** adopt the full six-trigger set in the listed precedence with δ = 0.10 (the
>   `[0.40, 0.50)` borderline band); treat `plan.validation` as optionally present (trigger #1 fires
>   only when it is); and ship the empty case as `"None."` (a benign, non-blank, golden-stable string).
> - **Answer (Review):** ✅ **Approved — full six-trigger set with `"None."` empty case.**
>
>   1. **Six triggers in fixed precedence — correct and complete.** The ordering (validation →
>      no-fill → volume divergence → intra-family split → borderline → missing family) reflects
>      severity: structural warnings first (validation, fill failure), then signal-quality
>      warnings. A deterministic ordering makes caveats golden-stable.
>
>   2. **δ = 0.10 for borderline band `[0.40, 0.50)` — reasonable.** This flags scores that
>      *barely* crossed the entry threshold, which is genuinely useful information. 10 basis
>      points of score above the threshold means the recommendation could easily flip on a
>      slightly different day.
>
>   3. **`plan.validation` optionally present — correct.** #82 is a soft dependency; the
>      trigger fires only when the field is populated. This is exactly why `validation` is
>      typed `Data | None`.
>
>   4. **`"None."` for empty caveats — correct.** A blank string is ambiguous (is it missing
>      or intentionally empty?). `"None."` is unambiguous, golden-stable, and reads naturally
>      in both the Excel export and the narrative context.

> **Q-D — `entry_price` provenance + the FLAT / no-fill edge case (a real model tension).**
> The three price fields are **required `Decimal`** (no default), yet a `HOLD/FLAT` symbol has **no
> trade and no fill** ([#76](https://github.com/prajoria/OpenBB/issues/76) emits no levels; [#77](https://github.com/prajoria/OpenBB/issues/77) emits empty orders; [#78](https://github.com/prajoria/OpenBB/issues/78) produces no fills). What goes
> in `entry_price/stop_price/target_price`?
>
> | Case | `entry_price` source | `stop`/`target` | Gaps / R:R / size |
> |---|---|---|---|
> | **BUY/SELL_SHORT, filled** | **realized** entry from the `entry`-intent `Fill.price` ([#78](https://github.com/prajoria/OpenBB/issues/78), after slippage) | from [#76](https://github.com/prajoria/OpenBB/issues/76) levels — **frozen** (as planned) **or re-anchored** off the realized entry (sub-Q below) | computed (§2) |
> | **BUY/SELL_SHORT, NOT filled** (limit never marketable / no t+1 bar) | fall back to **planned** `entry_ref` ([#77](https://github.com/prajoria/OpenBB/issues/77), off `as_of` close) + caveat #2 | planned levels | computed off planned |
> | **HOLD/FLAT** | **?** — model forces a Decimal. Straw: the **`as_of` close** (a meaningful reference price) | **?** Straw: `stop = target = entry` ⇒ zero-distance | `stop_distance_pct = target_distance_pct = 0.0`, `risk_reward = 0.0`, `position_size = 0`, `risk_per_share = 0`, `time_stop_bars = None` |
>
> The Excel sketch (§14.3) renders the FLAT row's Entry/Stop/Target/Stop%/R:R as **"—"**, so whatever
> sentinel we pick, [#81](https://github.com/prajoria/OpenBB/issues/81) maps the zero-distance/flat case to "—". **Open:** (a) FLAT entry =
> `as_of` close vs `Decimal("0")`; (b) for filled trades, **freeze** [#77](https://github.com/prajoria/OpenBB/issues/77)'s planned stop/target (R:R drifts
> from `target_r_multiple` because the realized entry ≠ planned `entry_ref`) **or re-anchor** stop/target
> off the realized entry (keeps R:R ≈ `target_r_multiple` exact). [#77](https://github.com/prajoria/OpenBB/issues/77) Q-F recommended *freeze +
> report drift* — confirm #80 reports the drifted R:R rather than re-anchoring.
>
> - **Recommendation:** FLAT entry = the **`as_of` close** (a meaningful reference, not `Decimal("0")`)
>   with `stop = target = entry` ⇒ zero-distance gaps; for filled trades **freeze** [#77](https://github.com/prajoria/OpenBB/issues/77)'s planned
>   stop/target and **report the drifted R:R** honestly (no re-anchoring), consistent with [#77](https://github.com/prajoria/OpenBB/issues/77) Q-F.
> - **Answer (Review):** ✅ **Approved — FLAT = `as_of` close; freeze levels; report drift.**
>
>   1. **FLAT entry = `as_of` close — correct.** `Decimal("0")` is a meaningless sentinel that
>      would confuse any downstream consumer. The `as_of` close is a real, meaningful reference
>      price that answers "where was the stock when we decided not to trade?" The zero-distance
>      (`stop = target = entry`) and zero-size fields are the clean FLAT representation, and
>      #81 maps them to `"—"` in Excel.
>
>   2. **Freeze planned levels for filled trades — consistent with #77 Q-F.** Re-anchoring
>      stop/target off the realized entry would hide the slippage. If the planned entry was
>      $100 and the fill was $100.15, the frozen stop ($97) and target ($104) now produce a
>      *slightly different* R:R than the planned 2.0×. That drift is real information —
>      reporting it honestly is the right thing. The user sees: "your fill was 15 cents worse
>      than planned, so your actual R:R is 1.97× instead of 2.0×."
>
>   3. **Division guards (zero-distance) — essential.** The `entry == stop` case must not
>      throw `ZeroDivisionError`. Returning `0.0` for all distance/R:R fields is the natural
>      sentinel.

> **Q-E — `risk_pct_of_notional` formula (§4.7 normalized, no personal dollars).** The field is
> `float`, documented *"Position risk as a percent of notional / sizing risk fraction used."* Three
> defensible readings:
>
> | Opt | Formula | "Notional" means | Self-contained? |
> |---|---|---|---|
> | **E1** | `risk_per_share / entry_price` (`= stop_distance_pct`) | position value (`qty·entry`) — per-share risk normalized by price | **Yes** — only needs levels already on the rec |
> | **E2** | `sizing.risk_per_trade` (e.g. `0.01`) | the **input** risk budget fraction | needs `risk_per_trade` threaded to #80 |
> | **E3 — RECOMMEND** | `(position_size · risk_per_share) / account_size` | **account** notional; the *realized* fraction of (abstract) account at risk, `≤ risk_per_trade` after share-flooring | needs `account_size` threaded to #80 |
>
> All three are privacy-safe (`account_size` defaults to an **abstract** notional, [#76](https://github.com/prajoria/OpenBB/issues/76) L2 — no
> personal dollars leak; the output is a pure fraction). **But E2/E3 require `account_size`/`risk_per_trade`
> to reach #80** — the `TradePlan` carries `position_size` but **not** the `SizingConfig` today, so a
> plumbing decision rides on this (E1 needs nothing extra). **Open:** pick the formula **and** confirm
> whether `SizingConfig` is threaded onto the `TradePlan` for E2/E3.
>
> - **Recommendation:** E3 — `(position_size · risk_per_share) / account_size` (the realized fraction
>   of abstract account notional at risk), which requires threading `SizingConfig` (or at least
>   `account_size`) onto the `TradePlan`; if that plumbing is rejected, fall back to **E1**
>   (`risk_per_share / entry_price`), which needs nothing extra.
> - **Answer (Review):** ✅ **Approved — E3 with `SizingConfig` threading; E1 as fallback.**
>
>   1. **E3 is the most informative formula.** `(position_size × risk_per_share) / account_size`
>      answers the real question: "what fraction of my capital is at risk in this trade?" E1
>      (`risk_per_share / entry_price`) is just `stop_distance_pct` by another name —
>      redundant with an existing field. E2 (`risk_per_trade`) is the *input* budget, not the
>      *realized* fraction after share-flooring.
>
>   2. **Threading `SizingConfig` (or `account_size`) is acceptable.** The `TradePlan` already
>      carries `position_size` (from #76's sizing). Adding `account_size` is one more Decimal
>      field — either directly on `TradePlan` or by making `SizingConfig` accessible through
>      the plan's `rule`. The plumbing cost is low.
>
>   3. **E1 as fallback is pragmatic.** If the plumbing is deferred, E1 (`risk_per_share /
>      entry_price`) still produces a meaningful per-share risk fraction. The field contract
>      (`float`, documented as "risk fraction") holds for both formulas — E3 is just richer.

> **Q-F — builder location, signature, and the `engine/execution.py` filename pact.** PRD §9.1 names a
> single `engine/execution.py` hosting *"BrokerInterface + paper fill simulation + Recommendation
> builder"*; [#78](https://github.com/prajoria/OpenBB/issues/78) split the broker/fill half into `engine/broker.py` + `engine/simulate.py` and
> **left `execution.py` for #80** (its §1 note). Proposed: `execution.py::build_recommendation(plan:
> TradePlan, *, config=...) -> Recommendation`. **Open:** does the builder **return** the
> `Recommendation` (caller attaches via `plan.model_copy(update={"recommendation": rec})`), or
> **mutate** `plan.recommendation` in place? Recommend **return-only** (pure; the `plan_router`/`scan`
> caller attaches), since `TradePlan.recommendation` is `Recommendation | None` per [#77](https://github.com/prajoria/OpenBB/issues/77) Q-A.
>
> - **Recommendation:** `execution.py::build_recommendation(plan, *, config=...) -> Recommendation`,
>   **return-only** (pure); the `plan_router` / [#79](https://github.com/prajoria/OpenBB/issues/79) `scan` caller attaches it via
>   `plan.model_copy(update={"recommendation": rec})`. Keep the `engine/execution.py` filename for #80
>   per the [#78](./78-paperbroker-fill-sim.md) §1 pact (broker/fill live in `broker.py`/`simulate.py`).
> - **Answer (Review):** ✅ **Approved — return-only builder in `execution.py`.**
>
>   1. **Return-only (pure) — correct.** `build_recommendation` should be a pure function:
>      plan in, `Recommendation` out. No mutation. The caller (`plan_router` / `scan`) attaches
>      the result via `model_copy`. This is the same immutable discipline used by backtest's
>      `sanitize_result` and the #78 `model_copy` attach pattern.
>
>   2. **`execution.py` filename — honors the #78 §1 pact.** #78 split the broker/fill code
>      into `broker.py` + `simulate.py` and explicitly left `execution.py` for #80. Keeping
>      this agreement avoids a confusing rename.
>
>   3. **Reuse `confluence.bucket_conviction` (L3) — confirmed.** Import the two-line bucketer
>      from `confluence.py` rather than inline it. One source of truth for the `0.7 / 0.4`
>      edges prevents silent drift between the confluence score and the recommendation's
>      conviction label.

---

## 1. Module layout (new)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
└── execution.py        # NEW (#80) — the pure Recommendation builder (Q-F):
                        #   build_recommendation(plan: TradePlan, *, config=DEFAULT_REC) -> Recommendation
                        #     • action/conviction from signal.direction + |score|        (§3)
                        #     • entry/stop/target + stop_distance_pct/target_distance_pct/risk_reward/atr (§2)
                        #     • position_size/risk_per_share/risk_pct_of_notional/time_stop_bars (§2, Q-E)
                        #     • deterministic reasoning / top_factors / caveats from votes (§4)
                        #   Depends on models (+ stdlib decimal, math) ONLY. No network, no LLM,
                        #   no pandas, no openbb.build(). (#78 owns broker.py/simulate.py.)

openbb_platform/extensions/techtrade/tests/
├── unit/
│   └── test_recommendation.py     # NEW — every field populated + right type; Decimal R:R/distance
│                                  #   correctness; reasoning references the ACTUAL top votes;
│                                  #   action/conviction buckets; FLAT/no-fill edge (Q-D).
└── golden/
    ├── test_recommendation_golden.py        # NEW — lock reasoning/top_factors/caveats STRINGS via
    │                                        #   testing.assert_matches_golden (golden marker, regen env).
    └── fixtures/recommendation_synthetic.json   # NEW — committed golden (regen under review).
```

**Module-boundary rules**
- `execution.py` is **pure**: it takes a paper-filled `TradePlan` (whose `signal.votes`, `orders`,
  `simulated_fills`, `position_size`, `rule` are already populated by [#74](https://github.com/prajoria/OpenBB/issues/74)/[#77](https://github.com/prajoria/OpenBB/issues/77)/[#78](https://github.com/prajoria/OpenBB/issues/78)) and returns a
  `Recommendation`. It performs **no** I/O and imports nothing from the engine except `models` (and,
  optionally, `confluence.bucket_conviction` for L3 — see §3) — unit-testable without `openbb.build()`.
- It **never recomputes** the signal, the levels, the sizing, or the fill price. Every number is
  **carried through** from upstream; #80 only *derives* the gaps/ratios (§2) and *renders* the
  narrative (§4). One source of truth per quantity (kills any §19 duplication).
- The float↔Decimal boundary (§2.1) is crossed **once**: distances are computed in `Decimal`, then
  cast to `float` for the `*_pct`/`risk_reward` fields. No `float` money ever escapes.
- No cycles: `models ← execution`; the `plan_router`/`scan` caller ([#77](https://github.com/prajoria/OpenBB/issues/77)/[#79](https://github.com/prajoria/OpenBB/issues/79)) attaches the result onto
  `TradePlan.recommendation`.

---

## 2. Levels & risk math (§14.2 / §9.3 / §13)

Inputs (all already on the paper-filled `TradePlan`):

| Quantity | Type | Source |
|---|---|---|
| `entry_price` | Decimal | realized `entry`-intent `Fill.price` ([#78](https://github.com/prajoria/OpenBB/issues/78), after slippage); planned `entry_ref` fallback (Q-D) |
| `stop_price`, `target_price` | Decimal | [#76](https://github.com/prajoria/OpenBB/issues/76) levels carried via [#77](https://github.com/prajoria/OpenBB/issues/77) orders (`exit_stop.stop_price`, `exit_target.limit_price`); frozen or re-anchored (Q-D) |
| `atr` | float | the ATR(14) that set the stop — `IndicatorPanel.volatility["atr"]` via [#76](https://github.com/prajoria/OpenBB/issues/76); **carried through**, never recomputed |
| `position_size`, `risk_per_share` | Decimal | [#76](https://github.com/prajoria/OpenBB/issues/76) sizing (`risk_per_share = \|entry − stop\| = atr_stop_mult·ATR`); `plan.position_size` |
| `time_stop_bars` | int\|None | `plan.rule.max_holding_bars` |
| `score` | float | `plan.signal.score` |

### 2.1 Derived stop-gaps & R:R (Decimal, then cast)

```
# all-Decimal arithmetic; entry/stop/target are Decimal (cents-quantized upstream)
stop_distance   = abs(entry_price - stop_price)        # Decimal
target_distance = abs(target_price - entry_price)      # Decimal

stop_distance_pct   = float(stop_distance   / entry_price)   # §14.2: |entry-stop|/entry
target_distance_pct = float(target_distance / entry_price)   # §14.2: |target-entry|/entry
risk_reward         = float(target_distance / stop_distance) # reward / risk  (≡ target_distance_pct / stop_distance_pct)

risk_per_share = stop_distance                          # Decimal, = |entry - stop| (carried from #76)
```

- **`risk_reward`** is computed from the **actual** levels, so it reflects any realized-fill drift
  (Q-D) rather than blindly echoing `rule.target_r_multiple` (default `2.0`).
- **Division guards (FLAT / zero-distance):** when `entry_price == 0` or `stop_distance == 0` (the
  FLAT sentinel, Q-D) ⇒ `stop_distance_pct = target_distance_pct = risk_reward = 0.0` (no
  `ZeroDivisionError`); `position_size = 0`, `risk_per_share = 0`, `time_stop_bars = None`.
- **`atr`** is surfaced verbatim (the value that sized the stop) — #80 does **not** touch pandas-ta.
- **`risk_pct_of_notional`** per Q-E (straw **E3**: `float(position_size · risk_per_share / account_size)`).

> **One quantity, two uses (carried from [#76](https://github.com/prajoria/OpenBB/issues/76) §2.1).** `risk_per_share = \|entry − stop\|` is the
> same magnitude that sized the position and set the R-multiple target — so `risk_reward`,
> `stop_distance_pct`, and `position_size` cannot disagree by construction. #80 surfaces it; it does
> not re-derive it.

---

## 3. Action & conviction buckets (§14.2)

```python
ACTION = {"long": "BUY", "short": "SELL_SHORT", "flat": "HOLD/FLAT"}     # L2

def action_of(signal) -> str:
    return ACTION[signal.direction]

# L3 — reuse #74's bucketer (single source of truth for the edges)
def conviction_of(score: float) -> str:
    a = abs(score)
    if a >= 0.7:   return "High"      # |score| ≥ 0.7
    if a >= 0.4:   return "Medium"    # 0.4 ≤ |score| < 0.7  (lower-inclusive)
    return "Low"                      # |score| < 0.4
```

- `action` is a pure map off `signal.direction` (resolved by [#74](https://github.com/prajoria/OpenBB/issues/74)/[#75](https://github.com/prajoria/OpenBB/issues/75)); `conviction` off `|score|`.
- A `flat` signal is **typically** `|score| < entry_threshold (0.4)` ⇒ `Low`, so `HOLD/FLAT` + `Low`
  is the consistent FLAT row — but the two fields are computed **independently** (a `flat` symbol
  could in principle carry a higher `|score|` if direction were resolved differently upstream; #80
  does not second-guess [#74](https://github.com/prajoria/OpenBB/issues/74)).
- **L3 reuse note (minor open):** import `bucket_conviction` from `confluence.py` to avoid two copies
  of the `0.7 / 0.4` edges drifting, **vs** inline the two-line helper to keep `execution.py` free of
  an engine import. Recommend **reuse** (one source of truth); confirm.

---

## 4. Deterministic reasoning (the non-LLM narrative) — §14.2

The acceptance hinge: `reasoning`, `top_factors`, and `caveats` must **trace to the actual votes**
(`signal.votes`), with **no recomputation and no second source of truth**. [#74](https://github.com/prajoria/OpenBB/issues/74) §4 already
guarantees the `votes` *fully reconcile* to `score`, so a narrative built from `votes` is faithful by
construction.

### 4.1 `reasoning` — template grammar (Q-A, the central open item)

The §14.2 example, decomposed into deterministic **slots**:

```
"Long NVDA: trend strongly positive (MACD histogram +, ADX 28, EMA20>EMA50),
 momentum confirming (RSI 62), and rising OBV confirms participation.
 Stop 2×ATR below entry (−3.1%); target at 2R (+6.2%)."
  └─ lead ──┘└──────────── per-family clauses (votes) ───────────────────┘
                                                          └──── levels sentence (§2) ────┘
```

| Slot | Filled from | Form (proposed) |
|---|---|---|
| **Lead** | `action` + `symbol` | `"Long {sym}: "` / `"Short {sym}: "` / `"Hold {sym}: "` |
| **Family clause** ×(present families, canonical order) | per-family signed contribution `Σ(weight·vote)` + its voters | `"{family} {strength}{polarity} ({detail tokens})"` |
| **Levels sentence** | `rule.atr_stop_mult`, `risk_reward`, signed `stop_distance_pct`, `target_distance_pct` | `"Stop {mult}×ATR {below/above} entry ({stop%:+.1%}); target at {RR:.1f}R ({tgt%:+.1%})."` |

Proposed **phrase bank** (deterministic; keyed by family × sign × strength bucket — *all provisional,
Q-A*):

| Family | strength = strong / mid / weak | polarity by `sign(contribution)` |
|---|---|---|
| **trend** | `"strongly "` / `""` / `"weakly "` | `+ → "positive"`, `− → "negative"`, mixed → `"mixed"` |
| **momentum** | (same strength ladder) | `+ → "confirming"`, `− → "diverging"`, ~0 → `"neutral"` |
| **volatility** | — | `+ → "breakout/expanding"`, `− → "mean-reverting/range-bound"` |
| **volume** | — | `+ → "{rising OBV / positive CMF} confirms participation"`, `− → "volume diverging"` |

- **Strength bucket** from `|family contribution| / w_family`: `≥ 0.66 → strong`, `≥ 0.33 → mid`,
  else `weak` (deterministic thresholds; provisional).
- **Detail tokens** in parens (Q-A headline): **votes-only (A1, recommended)** ⇒ polarity tokens
  `"MACD+"`, `"EMA cross+"`, `"RSI+"`; **panel-coupled (A2)** ⇒ raw readings `"ADX 28"`, `"RSI 62"`.
- **Number formatting is a determinism input:** pcts to `1` decimal with sign (`−3.1%`), R to `1`
  decimal (`2.0R`). The exact format is golden-locked (§5) so the string is byte-stable.
- **Sentence count** stays in the §14.2 **2–4** band: 1 lead+clauses sentence + 1 levels sentence;
  a 3rd appears only when a caveat is inlined (or `caveats` is kept strictly separate — confirm in Q-A).
- **FLAT:** lead `"Hold {sym}: "` + a "mixed / below threshold" clause + **no** levels sentence
  (zero-distance) — e.g. *"Hold JPM: mixed — trend flat, momentum neutral; below the entry threshold."*

### 4.2 `top_factors` (Q-B)

```
rank votes by  |weight · vote|  desc           # the #74 §4 attribution key
take top K (=3); format each:  f"{NAME}{'+' if vote>0 else '−'} ({family})"
tie-break:  |weight·vote| → family canonical order → name alpha
drop |weight·vote| ≤ ε
```

⇒ e.g. `["MACD+ (trend)", "RSI+ (momentum)", "OBV+ (volume)"]` (A1) — exactly the §9.3 example shape
(raw-number form `"RSI 62"` only under Q-A=A2/A3). **Every entry names a real `IndicatorVote`** — the
auditability check in §5 asserts each `top_factors` name appears in `signal.votes`.

### 4.3 `caveats` (Q-C)

Evaluate the §0.2 Q-C trigger predicates in **fixed precedence**, join the firing clauses into one
string (ordering is deterministic ⇒ golden-stable). Empty ⇒ `""` or `"None."` (Q-C open). Each clause
is **derived from the plan** (a `volume` vote opposing `sign(score)`, a family missing from the panel,
`plan.validation` failing, etc.) — never free text.

> **Auditability invariant (the issue's core acceptance).** Every phrase in `reasoning`, every entry
> in `top_factors`, and every clause in `caveats` is a pure function of `(signal.votes, levels, rule,
> validation)` already on the `TradePlan`. There is **no** recomputation and **no** second source of
> truth — a reader can map any narrative fragment back to a specific `IndicatorVote` or level. §5 locks
> this with both an assertion test (names ⊂ votes) and a golden string lock.

---

## 5. Determinism & testing

**Determinism.** `build_recommendation` is a pure function of one paper-filled `TradePlan` — no
network, no RNG, no LLM, no clock. Same plan in ⇒ identical `Recommendation` (including the **exact**
`reasoning` string) out. Money/qty assertions use **Decimal equality** (no float tolerance) against
hand-computed goldens; pct/ratio fields compare within `testing.DEFAULT_TOL` (1e-9).

### 5.1 `tests/unit/test_recommendation.py` (offline)

| Test | Asserts |
|---|---|
| `test_all_fields_populated` | every `Recommendation` field is non-`None` and the right type (`type(entry_price) is Decimal`, `type(stop_distance_pct) is float`, …) — the issue's "every field populated" |
| `test_distance_and_rr_decimal` | golden Decimal levels ⇒ exact `stop_distance_pct`, `target_distance_pct`, `risk_reward`; computed in Decimal then cast (L4/L5) |
| `test_action_map` | `long→BUY`, `short→SELL_SHORT`, `flat→HOLD/FLAT` (L2) |
| `test_conviction_buckets` | `\|score\|` at `0.7` → High, `0.4` → Medium, `0.39` → Low (lower-inclusive, L3) |
| `test_reasoning_references_top_votes` | each `top_factors` name ∈ `{v.name for v in signal.votes}`; `top_factors` ordered by `\|weight·vote\|`; each name appears in the `reasoning` string (the auditability acceptance) |
| `test_top_factors_rank_and_tiebreak` | top-K = 3; tie-break order (Q-B); near-zero votes dropped |
| `test_caveats_deterministic_order` | engineered triggers fire in the fixed precedence (Q-C); empty ⇒ the chosen empty form |
| `test_flat_no_fill_edge` | `direction="flat"` ⇒ `HOLD/FLAT`, zero-distance gaps, `position_size==0`, `risk_per_share==0`, `time_stop_bars is None`, no `ZeroDivisionError` (Q-D) |
| `test_no_fill_fallback` | `action≠FLAT` + empty `simulated_fills` ⇒ planned-`entry_ref` fallback + caveat #2 (Q-D) |
| `test_risk_pct_of_notional` | the chosen Q-E formula on golden inputs; privacy-safe (pure fraction, no dollar value) |
| `test_deterministic` | same plan ×2 ⇒ identical `Recommendation` (incl. `reasoning` string) |

### 5.2 `tests/golden/test_recommendation_golden.py` — narrative lock

Because `reasoning`/`top_factors`/`caveats` are **deterministic strings**, lock them against a
committed fixture via the `testing.py` harness (the [#74](https://github.com/prajoria/OpenBB/issues/74)/[#71](https://github.com/prajoria/OpenBB/issues/71) golden pattern):

```python
import pytest
from pathlib import Path
from openbb_techtrade.testing import assert_matches_golden

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.golden
def test_recommendation_golden():
    rec = build_recommendation(SYNTHETIC_FILLED_PLAN)   # hand-built, seeded TradePlan
    assert_matches_golden("recommendation_synthetic", rec, fixture_dir=FIXTURES)
```

- `to_jsonable` renders `Decimal → str` (lossless money discipline) and the full narrative strings, so
  the fixture locks **both** the numeric levels and the exact `reasoning` prose.
- Carries the `golden` marker; regenerate intentionally with `TECHTRADE_REGEN_GOLDEN=1`
  (`testing.REGEN_ENV`) **only after Q-A…Q-E are settled and under review** — the template grammar and
  the FLAT/no-fill sentinel both change the locked string/values.
- Fixture covers a **clear BUY** (full narrative + top_factors + a divergence caveat), a **SELL_SHORT**
  (sign-folded levels sentence), and a **HOLD/FLAT** (zero-distance, no levels sentence) so the
  golden exercises every branch of §4.

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_recommendation.py openbb_platform/extensions/techtrade/tests/golden/test_recommendation_golden.py -m "not integration" -v
```

---

## Acceptance mapping (#80)

| Acceptance criterion (issue) | Satisfied by | Open dependency |
|---|---|---|
| `engine/execution.py` builder: entry/stop/target, **stop-gaps**, R:R, ATR | §2 (Decimal gaps + `risk_reward`); §1 (`execution.py`, Q-F filename pact with [#78](https://github.com/prajoria/OpenBB/issues/78)) | Q-D (entry provenance), Q-F (signature) |
| Sizing fields: `position_size`, `risk_per_share`, `risk_pct_of_notional`, `time_stop_bars` | §2 (carried from [#76](https://github.com/prajoria/OpenBB/issues/76); Q-E formula) | **Q-E** (formula + plumbing) |
| **Deterministic reasoning template** (non-LLM): `reasoning`/`top_factors`/`caveats` traced to votes | §4 (grammar + `top_factors` rank + `caveats` precedence); L6/L8 | **Q-A/Q-B/Q-C** |
| `action` + `conviction` buckets from score | §3 (L2 action map, L3 buckets) | — |
| Unit test: **every field populated**; reasoning references actual top votes | §5.1 (`test_all_fields_populated`, `test_reasoning_references_top_votes`) | — |
| `Recommendation` fully populated per §9.3 / §14.2 | §0.1 L1 (all 20 fields), §2–§4 | Q-D (required Decimals for FLAT) |
| `reasoning`/`top_factors` trace to the signal's votes (**auditable**) | §4.3 invariant; §5.1 names ⊂ votes; §5.2 golden lock | Q-A (votes-only vs panel) |
| R:R, stop/target distance % computed correctly (**Decimal**) | §2.1 (Decimal arithmetic, cast at boundary); §5.1 `test_distance_and_rr_decimal` | — |
| (Depends) consumes [#78](https://github.com/prajoria/OpenBB/issues/78) realized entry; feeds [#81](https://github.com/prajoria/OpenBB/issues/81) (one Excel row), [#82](https://github.com/prajoria/OpenBB/issues/82) caveat | §1 boundary; §2 (Fill entry); §4.3 (validation caveat) | Q-C (validation availability) |

> **Gate before implementation:** resolve **Q-A…Q-F (§0.2)** with the user. Q-A (template grammar) and
> Q-D (FLAT/no-fill `entry_price`) change the golden string/values, so the §5.2 fixture is authored
> *after* those decisions, not before.
