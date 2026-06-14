# 77 — Order Generation + plan/orders → TradePlan

**GitHub:** [#77](https://github.com/prajoria/OpenBB/issues/77) · **Phase:** P4 · **Sprint:** 4 · **Size:** M
**Depends on:** [#76](https://github.com/prajoria/OpenBB/issues/76) (EntryExitRule + sizing → levels + size)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §13 (order generation), §9.2 (command surface), §9.3 (models)
**Scope:** Turn a `MoverSignal` + `EntryExitRule` + the sized levels from [#76](https://github.com/prajoria/OpenBB/issues/76) into a deterministic `Order` list (entry + intent-tagged exits), assemble the per-symbol `TradePlan`, and expose `plan(symbols|segment, preset=…, risk=…)` and `orders(plan)` on `obb.techtrade.*`.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

Order generation and the `TradePlan`. Given a signal plus its entry/exit rule and sizing (the previous
step), this turns the abstract plan into a concrete, ordered list of broker-style `Order`s — an entry
order, plus contingent exit orders each tagged with an *intent* (`exit_stop`, `exit_target`, `exit_time`,
`exit_signal`) so every order's purpose is explicit. It then assembles the per-symbol `TradePlan`, the
single object that bundles the signal, the rule, the size, and the orders together. It also exposes two
commands: `plan(...)` builds the full plan per symbol, and `orders(plan)` materializes just the order list.

It exists in this pipeline because the rules step produces price *levels and a size*; this step expresses
them as the actual orders a broker (or the paper-fill simulator next) would act on, and packages everything
into the `TradePlan` that flows through fills, the recommendation, and the Excel export. The `intent` tags
are what let downstream consumers (and a future live broker) understand each order's role. Look-ahead
discipline applies throughout: orders planned on today's bar are meant to fill on the *next* bar.

---

## 0. Key decisions (locked) + open questions

### 0.1 Locked in brainstorming

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | Models | `Order` + `TradePlan` **already exist** in [`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py) (scaffolded by [#71](https://github.com/prajoria/OpenBB/issues/71)). #77 **populates**, does not define them | No new Pydantic models; one possible *Optional* tweak to `TradePlan.recommendation` — see **Q-A** |
| L2 | `intent` enum | Fixed `{entry, exit_stop, exit_target, exit_time, exit_signal}`; every emitted order carries exactly one | Acceptance "every exit order has a correct `intent`" is a direct enum-mapping check (§2) |
| L3 | Order ordering | **Entry first**, then contingent `exit_stop`, `exit_target`, `exit_time`, `exit_signal` (canonical, enum-order) per §13 | Deterministic list → golden-stable (§5) |
| L4 | Entry default | `market` next-bar-open; `limit`-with-offset is the configurable alternative (§13) | Entry order has no price by default; limit offset is opt-in (**Q-C**) |
| L5 | Look-ahead | Signal on bar *t* → orders **fill at t+1** (paper). #77 emits **planned** levels off the `as_of` reference bar; realized prices land at [#78](https://github.com/prajoria/OpenBB/issues/78) (paper fill sim) | #77 prices are *planned*, not *filled* (**Q-F**) |
| L6 | Module boundary | #77 **consumes** [#76](https://github.com/prajoria/OpenBB/issues/76)'s levels (`entry_ref`, `stop`, `target`) + `position_size`; it does **not** recompute ATR/stop/target/sizing math | [`orders.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/engine/orders.py) is a pure mapper: levels → `Order` rows. No indicator compute, no network |
| L7 | Types | `Decimal` for every `quantity`/`limit_price`/`stop_price`; signal/levels chain reuses [#73](https://github.com/prajoria/OpenBB/issues/73) bulk panels + [#75](https://github.com/prajoria/OpenBB/issues/75) signals | No float drift in emitted prices; one provider path (`fmp_cached`) |

### 0.2 Open questions (please review / brainstorm)

> **Q-A — `TradePlan` completeness at #77 (the cross-issue ordering problem). ← most important.**
> `models.py` types the downstream-filled fields **asymmetrically**:
> ```python
> orders:          list[Order]      = Field(default_factory=list)   # #77 fills
> simulated_fills: list[Fill]       = Field(default_factory=list)   # #78 fills — has default []
> recommendation:  Recommendation   = Field(...)                    # #80 fills — REQUIRED, no default
> validation:      Data | None      = Field(default=None)           # #82 fills — Optional
> ```
> `simulated_fills` and `validation` are downstream-filled **and** default, so a `TradePlan` constructs
> fine without them. **`recommendation` is downstream-filled by [#80](https://github.com/prajoria/OpenBB/issues/80) (Recommendation builder) but has *no default*** — so `TradePlan(signal=…, rule=…, orders=…)`
> raises a pydantic `ValidationError` today. And per PRD §14.2 a `Recommendation` is derived from the
> **realized paper fill** ([#78](https://github.com/prajoria/OpenBB/issues/78)), so it genuinely *cannot* be built at #77. #77 cannot emit any `TradePlan` until this is resolved. Options:
>
> | Opt | Approach | Cost |
> |---|---|---|
> | **(i) — RECOMMEND** | Make `recommendation: Recommendation \| None = None` in `models.py` | 1-line model edit on the [#71](https://github.com/prajoria/OpenBB/issues/71) scaffold; mirrors the `simulated_fills`/`validation` downstream-fill pattern; #77 ships the **plan skeleton** (signal+rule+size+orders), [#80](https://github.com/prajoria/OpenBB/issues/80) populates `recommendation`. Touches the shared contract that #78/#80/#81 read → needs sign-off |
> | (ii) | #77 builds a **placeholder** `Recommendation` from data it already has (entry/stop/target/size/atr are known via #76) with neutral narrative (`reasoning=""`, action from direction) | Emits half-true narrative fields #80 must overwrite; placeholder strings leak if #80 slips; golden churn |
> | (iii) | Gate `plan` on [#80](https://github.com/prajoria/OpenBB/issues/80); #77 ships only the `orders` builder + tests | **Breaks the issue DAG** (#77 depends on #76 only) and leaves #77's "`plan` returns a complete TradePlan" acceptance unmet |
>
> **Recommendation: (i).** It is the honest separation — the issue acceptance lists "complete `TradePlan`
> **(signal+rule+size+orders)**", which is exactly the skeleton, *omitting* `recommendation`/`simulated_fills`.
> Confirm we may make the one-line `models.py` change (out of #77's "no new models" remit, so flagged).
>
> - **Recommendation:** option (i) — make `recommendation: Recommendation | None = None` in `models.py`, so #77 ships the plan skeleton and [#80](https://github.com/prajoria/OpenBB/issues/80) populates `recommendation`.
> - **Answer:** _(pending approval)_

> **Q-B — side mapping (confirm the 4-side table).** Direction drives both legs:
>
> | `signal.direction` | entry `side` | every exit `side` |
> |---|---|---|
> | `long` | `buy` | `sell` |
> | `short` | `sell_short` | `buy_to_cover` |
> | `flat` | — (no orders; empty plan, `position_size = 0`) | — |
>
> Confirm `flat` ⇒ an empty `orders` list (vs. omitting the plan entirely). Recommend: still emit the
> `TradePlan` (carrying the `flat` signal) with `orders = []` so `scan`/export rows stay symbol-complete.
>
> - **Recommendation:** still emit the `TradePlan` (carrying the `flat` signal) with `orders = []` so `scan`/export rows stay symbol-complete.
> - **Answer:** _(pending approval)_

> **Q-C — `order_type` & resting vs. event-driven per intent.** `exit_stop` (a price) → `order_type="stop"`
> + `stop_price`; `exit_target` (a price) → `order_type="limit"` + `limit_price`. But **`exit_time`
> (`max_holding_bars`) and `exit_signal` (opposite cross) are not prices — they are *triggers*** with no
> field in the `Order` model to hold the trigger. Two readings:
> - **(a) — RECOMMEND:** materialize **all four** exits as `Order` rows now. `exit_time`/`exit_signal` are
>   `order_type="market"`, `limit_price=stop_price=None`; their *trigger* is carried by the `EntryExitRule`
>   (`max_holding_bars`, `exit_on_opposite`) and **realized at [#78](https://github.com/prajoria/OpenBB/issues/78)**. This is the only reading that ever
>   *uses* the `exit_time`/`exit_signal` enum members, satisfying "every exit order has a correct `intent`".
> - (b) emit only `exit_stop` + `exit_target` as orders; treat time/signal purely as rule conditions
>   evaluated during simulate (no `Order` rows). Then two `intent` values are never produced at #77.
>
> Also (Q-C'): entry `limit`-with-offset — is the offset a `plan`/preset param (e.g. `entry_limit_bps`)?
> Recommend it stays a preset/rule knob, **default `market`** (L4), offset deferred unless a preset sets it.
>
> - **Recommendation:** option (a) — materialize **all four** exits as `Order` rows now (`exit_time`/`exit_signal` as `market` rows, triggers carried by the `EntryExitRule` and realized at [#78](https://github.com/prajoria/OpenBB/issues/78)); for Q-C', keep the entry-limit offset a preset/rule knob, **default `market`**, offset deferred unless a preset sets it.
> - **Answer:** _(pending approval)_

> **Q-D — `risk=…` param shape.** Maps to [#76](https://github.com/prajoria/OpenBB/issues/76)'s sizing config (`account_size` + `risk_per_trade`),
> which fixes `position_size`. What does `plan(risk=…)` accept?
> - (i) a **float** `risk_per_trade` fraction (e.g. `0.01` = risk 1% per trade), `account_size` from a
>   normalized-notional default (PRD §4.7 forbids emitting personal dollar amounts) — simplest, CLI/REST-friendly;
> - (ii) a **`SizingConfig`-shaped dict** (`{account_size, risk_per_trade, …}`) passed straight to #76;
> - (iii) a named **risk preset** string.
>
> Recommend: accept **(i) a float shorthand OR (ii) the #76 `SizingConfig`** (float → `risk_per_trade`),
> defaulting `account_size` to normalized notional. Confirm the param name (`risk`) and default.
>
> - **Recommendation:** accept **(i) a float shorthand OR (ii) the #76 `SizingConfig`** (float → `risk_per_trade`), defaulting `account_size` to normalized notional.
> - **Answer:** _(pending approval)_

> **Q-E — `plan(segment=…)` fan-out & return shape.** `segment` reuses [#70](https://github.com/prajoria/OpenBB/issues/70) movers → [#73](https://github.com/prajoria/OpenBB/issues/73) bulk
> panels → [#75](https://github.com/prajoria/OpenBB/issues/75) signals → one `TradePlan` per symbol. `symbols=[…]` plans an explicit list.
> Return shape: `OBBject[list[TradePlan]]` (single symbol ⇒ a length-1 list, mirroring `movers`/`signals`).
> Confirm: list-always (no scalar special-case), and `symbols` **xor** `segment` is required (one of the two).
>
> - **Recommendation:** return `OBBject[list[TradePlan]]` list-always (single symbol ⇒ length-1 list, no scalar special-case), with `symbols` **xor** `segment` required (one of the two).
> - **Answer:** _(pending approval)_

> **Q-F — where pre-fill prices come from.** Entry is `market` (no price). `exit_stop`/`exit_target` need
> prices, derived from an **entry reference**; pre-fill we don't know the realized next-bar-open, so the
> reference = the `as_of` bar (last known close) used by [#76](https://github.com/prajoria/OpenBB/issues/76) to compute `entry_ref`/`stop`/`target`. So
> #77's `stop_price`/`limit_price` are **planned** `Decimal` levels off `entry_ref`. [#78](https://github.com/prajoria/OpenBB/issues/78) fills entry at
> realized next-bar-open; [#80](https://github.com/prajoria/OpenBB/issues/80) reports the realized `entry_price`. **Open:** does #78 **re-anchor**
> stop/target off the realized fill, or freeze #77's planned levels? Recommend: #77 freezes planned levels;
> #78/#80 reconcile and report any drift (keeps #77 deterministic and offline-testable).
>
> - **Recommendation:** #77 freezes planned levels off the `as_of` reference bar; [#78](https://github.com/prajoria/OpenBB/issues/78)/[#80](https://github.com/prajoria/OpenBB/issues/80) reconcile and report any drift (keeps #77 deterministic and offline-testable).
> - **Answer:** _(pending approval)_

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
├── rules.py            # EXISTING (#76) — EntryExitRule eval + sizing:
│                       #   (signal, rule, panel/atr, sizing) -> levels(entry_ref, stop, target)
│                       #   + position_size. #77 CONSUMES this; never recomputes the math (L6).
├── orders.py           # NEW (#77) — pure mapper, models-only dependency:
│                       #   build_orders(signal, rule, levels, size) -> list[Order]   (§2)
│                       #   build_plan(signal, rule, levels, size)   -> TradePlan      (§3, skeleton)
└── plan_router.py      # NEW (#77) — sub-router attached by techtrade_router._include_subrouters:
                        #   plan(symbols|segment, preset=, risk=, as_of=) and orders(plan)   (§4)

openbb_platform/extensions/techtrade/tests/
└── unit/
    ├── test_orders.py  # NEW — intents + prices + sides match the rule; ordering; conditional exits (§5)
    └── test_plan.py    # NEW — plan skeleton assembly; segment fan-out; orders(plan) round-trip (§5)
```

**Module-boundary rules**
- `orders.py` is **pure**: it imports only `models` and maps #76 levels + #75 signal onto `Order`/`TradePlan`.
  No indicator compute, no `obb.*`, no network — fully unit-testable without `openbb.build()`.
- `orders.py` does **not** encode stop/target/sizing math — that is #76's [`rules.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/engine/rules.py) (L6). It only assigns
  `side`/`order_type`/`intent`/prices/`quantity` per the §2 table.
- [`plan_router.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py) is thin: it calls `signals` ([#75](https://github.com/prajoria/OpenBB/issues/75)) → `rules` ([#76](https://github.com/prajoria/OpenBB/issues/76)) → `orders.build_plan`, wraps in
  `OBBject`. The sub-router wires up automatically — [`techtrade_router`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py)`._include_subrouters` already lists
  `openbb_techtrade.engine.plan_router` (skipped until this file exists).
- No cycles: `orders` → `models`; `plan_router` → `orders`, `rules`, `signals`, `models`.

---

## 2. Order generation (§13)

`build_orders(signal, rule, levels, size)` emits one entry order then the contingent exits, **in canonical
enum order** (L3). `levels` and `size` come from #76; this function only maps.

### 2.1 Side mapping (Q-B)

| `signal.direction` | entry `side` | exit `side` (all four exits) |
|---|---|---|
| `long`  | `buy`         | `sell` |
| `short` | `sell_short`  | `buy_to_cover` |
| `flat`  | — no orders — | — no orders — |

### 2.2 `order_type` / price / tif per `intent` (Q-C, Q-F)

`E = levels.entry_ref`, `S = levels.stop`, `T = levels.target` (Decimal, from #76). `qty = size` for **every**
leg (exits close the full position).

| `intent` | `order_type` | `limit_price` | `stop_price` | `tif` | emitted when |
|---|---|---|---|---|---|
| `entry` | `market` (default) / `limit` | `None` / `E ∓ offset` | `None` | `day` | `direction ≠ flat` (always) |
| `exit_stop` | `stop` | `None` | `S` | `gtc` | always |
| `exit_target` | `limit` | `T` | `None` | `gtc` | always |
| `exit_time` | `market` | `None` | `None` | `gtc` | `rule.max_holding_bars is not None` |
| `exit_signal` | `market` | `None` | `None` | `gtc` | `rule.exit_on_opposite is True` |

> **Why time/signal are `market` rows with `None` prices (Q-C(a)):** they are **event-driven**, not price
> levels. The `Order` model has no trigger field, so the trigger lives in the `EntryExitRule`
> (`max_holding_bars`, `exit_on_opposite`) and the row is realized by [#78](https://github.com/prajoria/OpenBB/issues/78) (paper fill sim). Materializing
> them now is what gives the `exit_time` / `exit_signal` enum members an emitter and satisfies the acceptance
> "every exit order has a correct `intent`".

> **`tif`:** entry `day` (next-bar-open fills same session); resting exits `gtc` (live until triggered). This
> is the proposed default mapping, not a hard lock — adjust if simulate ([#78](https://github.com/prajoria/OpenBB/issues/78)) wants day-scoped exits.

> **OCO note:** `exit_stop` and `exit_target` both carry the full `qty`; in a live broker they would be an
> OCO pair (one fill cancels the other). At #77 they are independent rows; the **first-touch-wins / single-exit**
> invariant is enforced by the [#78](https://github.com/prajoria/OpenBB/issues/78) PaperBroker, not here. Flag if #77 should instead tag an `oco_group`.

### 2.3 Level provenance (Q-F)

`E`/`S`/`T` are **planned** levels off the `as_of` reference bar (last close), exactly as #76 computes them —
`S = E ∓ atr_stop_mult·ATR(14)`, `T = E ± target_r_multiple·(E−S)`, signs by direction. They are the prices a
reader/broker sees *before* the fill; the **realized** entry is finalized at [#78](https://github.com/prajoria/OpenBB/issues/78) and reported by [#80](https://github.com/prajoria/OpenBB/issues/80).

---

## 3. `TradePlan` assembly (§9.3)

`build_plan(signal, rule, levels, size)` composes the skeleton:

```python
TradePlan(
    symbol=signal.symbol,
    segment=signal.segment,
    as_of=signal.as_of,
    signal=signal,                       # from #75
    rule=rule,                           # from #76 (preset/risk applied)
    position_size=size,                  # from #76 sizing
    orders=build_orders(signal, rule, levels, size),   # §2
    # simulated_fills -> default []      (#78 fills)
    # recommendation  -> see Q-A         (#80 fills)
    # validation      -> default None    (#82 fills)
)
```

The plan composes four already-built parts: the **signal** (#75 confluence), the **rule** (#76, with `preset`/
`risk` applied), the **size** (#76 sizing), and the **orders** (§2). `simulated_fills` and `validation` take
their model defaults; **`recommendation` is the lone blocker (Q-A)** — under the recommended option (i) it is
`None` here and populated by [#80](https://github.com/prajoria/OpenBB/issues/80).

> **Downstream-fill contract (make explicit in the PR):** #77 emits a *plan skeleton* —
> `{signal, rule, position_size, orders}` populated; `{simulated_fills, recommendation, validation}` filled by
> [#78](https://github.com/prajoria/OpenBB/issues/78) / [#80](https://github.com/prajoria/OpenBB/issues/80) / [#82](https://github.com/prajoria/OpenBB/issues/82) respectively. The skeleton round-trips through Python/REST/CLI as a valid `Data` object.

---

## 4. Command surface (§9.2)

```python
# plan_router.py  (sub-router; bare OBBject returns per the static-package-builder constraint)

@router.command(methods=["GET"])
def plan(
    symbols: list[str] | None = None,   # explicit symbols  (xor segment)
    segment: str | None = None,         # GICS sector -> fan-out  (xor symbols)
    preset: str = "trend_follow",       # confluence/rule preset (#75/#76)
    risk: float | None = None,          # risk_per_trade fraction -> #76 sizing (Q-D)
    as_of: str | None = None,           # snapped to last session, look-ahead-free
) -> OBBject:
    """results -> list[TradePlan], one per symbol (single symbol => length-1 list)."""

@router.command(methods=["POST"])
def orders(plan) -> OBBject:            # plan: TradePlan | dict
    """results -> list[Order]: re-validate the plan and materialize plan.orders."""
```

| Command | Input | `results` payload | Notes |
|---|---|---|---|
| `obb.techtrade.plan(...)` | `symbols` **xor** `segment`, `preset`, `risk`, `as_of` | `list[TradePlan]` | fan-out via [#73](https://github.com/prajoria/OpenBB/issues/73) bulk panels + [#75](https://github.com/prajoria/OpenBB/issues/75) signals (Q-E) |
| `obb.techtrade.orders(plan)` | a `TradePlan` (or its dict) | `list[Order]` | re-validates a (possibly deserialized) plan and returns `plan.orders` |

**Chaining (the P3→P4 pipeline):**
```
movers (#70) ─▶ panels (#73 bulk) ─▶ signals (#75) ─▶ rule+sizing (#76) ─▶ plan (#77) ─▶ orders (#77)
                                       MoverSignal       levels + size       TradePlan      list[Order]
```
`plan` runs the whole chain per symbol; `orders(plan)` is the cheap materializer that extracts/re-validates the
order list from an existing plan (e.g. one reloaded from JSON). `orders` is **idempotent** — it returns the
plan's existing `orders`, regenerating from `signal`+`rule` only if the list is empty.

> Like the existing `screener_router`/`signals_router`, both commands return a **bare `OBBject`** (no
> parametrized model) so `package_builder.build_func_returns` renders an importable annotation; the
> `list[TradePlan]` / `list[Order]` payload types are documented in the docstrings (PRD §9.2 round-trips).

---

## 5. Determinism & testing

**Determinism**
- **Fixed list order** (L3): `[entry, exit_stop, exit_target, exit_time, exit_signal]`, conditional members
  dropped — never reordered → golden-stable.
- **Decimal prices/qty** (L7): levels arrive as `Decimal` from #76; `orders.py` does no float arithmetic, so
  no drift. `as_of`-anchored, look-ahead-free (L5); pure function ⇒ identical output for identical input.
- No network / no RNG in `orders.py` or `build_plan` — unit tests run fully offline with a hand-built
  `MoverSignal` + `EntryExitRule` + synthetic levels.

**Unit tests** (`test_orders.py`, `test_plan.py`)

| Test | Asserts |
|---|---|
| intents present & correct | every emitted order's `intent` ∈ enum; exits carry `exit_*`; entry carries `entry` |
| **prices match the rule** | `exit_stop.stop_price == E ∓ atr_stop_mult·ATR`; `exit_target.limit_price == E ± target_r_multiple·(E−S)`; entry `market` ⇒ `limit_price is None` |
| side mapping (Q-B) | `long` ⇒ entry `buy`/exits `sell`; `short` ⇒ entry `sell_short`/exits `buy_to_cover` |
| `flat` ⇒ empty | `direction == "flat"` ⇒ `orders == []`, `position_size == 0` |
| quantity | every leg `quantity == position_size` (Decimal-equal) |
| conditional exits (Q-C) | no `exit_time` when `max_holding_bars is None`; no `exit_signal` when `exit_on_opposite is False` |
| ordering (L3) | order list is the canonical entry-first sequence |
| `order_type`/`tif` map | stop⇒`stop`+`gtc`; target⇒`limit`+`gtc`; entry⇒`market`+`day` |
| plan skeleton (§3) | `signal`/`rule`/`position_size`/`orders` populated; `simulated_fills == []`; `recommendation` per Q-A; round-trips via `to_jsonable` |
| `orders(plan)` round-trip | `orders(build_plan(...)).results == plan.orders`; idempotent on a reloaded dict |
| segment fan-out (Q-E) | `plan(segment=…)` ⇒ `list[TradePlan]` len == #symbols; `plan(symbols=[X])` ⇒ length-1 |

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_orders.py openbb_platform/extensions/techtrade/tests/unit/test_plan.py -m "not integration" -v
```

> A golden `TradePlan` fixture (via `testing.assert_matches_golden`, [#71](https://github.com/prajoria/OpenBB/issues/71)) can lock the full skeleton once
> Q-A is settled — deferred here to avoid churning the golden when `recommendation` flips to Optional.

---

## Acceptance mapping (#77)

| Acceptance criterion (issue) | Satisfied by | Open dependency |
|---|---|---|
| `Order` generation from rules (entry + exit_stop/target/time/signal intents) | §2 `build_orders` + side/`order_type`/price/intent table | Q-C(a) (time/signal as market rows) |
| `plan(symbols\|segment, preset=…, risk=…)` → `TradePlan` per symbol | §3 `build_plan` + §4 `plan` command (fan-out Q-E, `risk` Q-D) | **Q-A** (`recommendation` Optional) |
| `orders(plan)` materializes the order list | §4 `orders` command → `list[Order]` | — |
| Unit tests: order intents + prices match the rule | §5 `test_orders.py` (intents, prices, sides, ordering) | — |
| `obb.techtrade.plan(...)` returns a complete `TradePlan` (signal+rule+size+orders) | §3 skeleton — the four parts the acceptance names | **Q-A** (skeleton vs. required `recommendation`) |
| `obb.techtrade.orders(plan)` returns the materialized order list | §4 `orders` | — |
| Every exit order has a correct `intent` | §2 enum mapping + §5 intent test | Q-C (all four intents emitted) |

> **Net new risk surfaced:** #77 cannot construct *any* `TradePlan` until **Q-A** is resolved, because
> `TradePlan.recommendation` is a required field owned by a *later* issue ([#80](https://github.com/prajoria/OpenBB/issues/80)). Recommended fix is the
> one-line `recommendation: Recommendation | None = None` edit — please confirm before implementation starts.
