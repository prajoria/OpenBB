# 78 — PaperBroker Fill Simulation (BrokerInterface, Next-Bar-Open) + simulate

**GitHub:** [#78](https://github.com/prajoria/OpenBB/issues/78) · **Phase:** P4 · **Sprint:** 4 · **Size:** L
**Depends on:** [#77](https://github.com/prajoria/OpenBB/issues/77) (orders + TradePlan)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §14.1 (broker / fill model), §13 (look-ahead discipline); models §9.3; reuse rule §19
**Scope:** Add a live-ready `BrokerInterface` Protocol + a `PaperBroker` implementation, a
next-bar-open fill model (no look-ahead) with slippage + commission, the
`obb.techtrade.simulate(orders, fill_model=...)` command returning a **FillList**, and the
golden test that enforces *bar-t signal → t+1 fill*.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> The merged backtest extension referenced below lives at
> [`../../../openbb_platform/extensions/backtest/openbb_backtest/`](../../../openbb_platform/extensions/backtest/openbb_backtest/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

A **paper broker** is a simulated order-execution engine: it accepts the orders a strategy produces
and decides — using only information that would have been available at the time — at what price and
when each order would actually have filled, *without* touching a real brokerage account. It is the
bridge between "the strategy says buy" and "here is the trade that resulted," so the rest of the
pipeline can report realistic entry prices, costs, and outcomes.

The single hardest correctness rule here is **no look-ahead**. A signal is computed from the close of
some bar *t* (a trading session). You must not let the simulated fill use any price from bar *t*
itself — by the time you could act, that bar is already over. The convention this issue enforces is
**next-bar-open**: an order built from a bar-*t* signal fills no earlier than the **open of bar
*t+1***. A golden test locks this down so a future regression that "peeks" at the signal bar fails
loudly. On top of that, two realism adjustments are applied: **slippage** (you rarely fill exactly at
the quoted price — buys fill a little higher, sells a little lower; default 5 basis points) and
**commission** (per-trade or per-share cost; default zero for equities). Stops and targets are then
evaluated **intrabar** against each forward bar's high/low, with a **conservative tie-break** (if both
the stop and the target are touched in the same bar, assume the stop — the worse outcome).

The execution seam is expressed as a `BrokerInterface` **Protocol** (`submit` / `cancel` /
`positions`) so the paper broker shipped here can later be swapped for a real Alpaca/IBKR client
behind the *same* call sites. Everything uses `Decimal` for money and share counts. The command
`obb.techtrade.simulate(orders, fill_model=...)` returns a **FillList** (`list[Fill]`) that feeds back
onto [`TradePlan.simulated_fills`](./77-order-generation-tradeplan.md) and is consumed by the
[#80 Recommendation builder](./80-recommendation-builder.md) for the realized entry price. A notable
design tension — surfaced as the headline open question below — is whether to **reuse** the
already-merged `openbb-backtest` execution machinery or build a small techtrade-local broker that
mirrors its math; the leaf-`models.py` standalone guarantee pushes toward the latter.

---

## 0. Key decisions (locked) + open questions

### 0.1 Locked (carried from PRD §14.1 / §13 + the merged `openbb-backtest` convention)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | Fill convention | **Next-bar-open (t+1)** default; an order built from a bar-*t* signal can fill no earlier than the open of bar *t+1* | Matches §13 and `openbb-backtest`'s `FillModel(kind="next_bar_open")` |
| L2 | Look-ahead discipline | **bar-*t* signal → *t+1* fill**, enforced by a golden test (§5) | PRD principle #4 (G6); the single hard correctness gate of this issue |
| L3 | `BrokerInterface` | A `runtime_checkable` **Protocol** — `submit(order, bar) -> Fill \| None`, `cancel(order_ref)`, `positions()` (§14.1) | Live-ready: `PaperBroker` is the v1 impl; a real Alpaca/IBKR broker swaps in behind the same Protocol (acceptance) |
| L4 | `Fill` shape | Exactly `models.Fill`: `order_ref:str`, `timestamp:datetime` (tz-aware), `symbol:str`, `side:str`, `quantity:Decimal`, `price:Decimal` (**after slippage**), `commission:Decimal`, `slippage:Decimal` | No new fill schema; feeds `TradePlan.simulated_fills` and #80 (Recommendation builder) |
| L5 | Default models | **Zero-commission** equities + **fixed 5 bps** slippage | §14.1 default row; explicit, overridable via `fill_model` |
| L6 | Numeric discipline | **`Decimal`** for price / quantity / commission / slippage; slippage **always adverse** (buys fill higher, sells lower) | Mirrors `openbb-backtest` execution discipline; no `float` money |
| L7 | `FillList` | `OBBject[list[Fill]]` payload — **no new wrapper model**; same `list[Fill]` stored on `TradePlan.simulated_fills` | Round-trips through Python / REST / CLI / MCP unchanged (§9) |

### 0.2 Open questions (for review / brainstorm)

> **Q-A — REUSE `openbb-backtest`'s execution machinery, or build a techtrade-local `PaperBroker`? (HEADLINE)**
> `openbb-backtest` is **merged in-tree** and already ships the entire fill stack this issue needs:
> `openbb_backtest.engine.execution.{Commission, Slippage, FillModel, RealisticBroker}` +
> `openbb_backtest.models.{Bar, Trade, CommissionModel, SlippageModel, PositionSnapshot}` +
> the `openbb_backtest.interfaces.Broker` Protocol. Its `FillModel.kind="next_bar_open"` is the
> *same* convention §13 mandates, and its `Slippage`/`Commission` cover the exact option matrix in
> §14.1 (fixed_bps / volume_share / spread; per_share / flat / percent). **Three postures:**
>
> | Option | What | Pros | Cons |
> |---|---|---|---|
> | **A1 — hard reuse** | `import openbb_backtest...` directly; techtrade `simulate` wraps `RealisticBroker` | Zero duplication (§19); battle-tested math; convention parity for free | **Breaks Q7 standalone** — `models.py` is a deliberate leaf with *no* `openbb_backtest` import, and the `validation` field is typed `Data` precisely to keep techtrade installable without backtest (see #85, core-unchanged-when-removed). A1 makes backtest a hard dep. Also couples to backtest's `Broker.fill(DataFrame, bar) -> Trade` shape, which is **not** §14.1's `submit(order, bar) -> Fill` |
> | **A2 — local, mirror the math (RECOMMENDED)** | techtrade-native `BrokerInterface` (submit/cancel/positions, §14.1) + `PaperBroker` with its own small `Commission`/`Slippage`/`FillModel` that **mirror** backtest's formulas; a parity test cross-checks | Keeps techtrade **independently installable** (Q7, #85); Protocol matches §14.1 exactly; `Fill`/`Order` already techtrade-native | Re-states ~20 lines of slippage/commission formula — the §19 "duplication" risk, **neutralized** by a parity golden test (the #73 oracle pattern) |
> | **A3 — optional reuse + local fallback** | soft-import backtest's execution when present, else local | Best of both at runtime | Two code paths to keep at parity; most complex; likely over-built for v1 |
>
> **Recommendation: A2.** The explicit decoupling in `models.py`, the Q7 standalone answer, and the
> #85 removal test outweigh the duplication concern; a parity test against `openbb-backtest` (when
> installed) buys back the §19 guarantee without the hard dependency. **But this is the central
> choice — confirm before any code.**
>
> - **Answer (Review):** ✅ **Approved — A2 (techtrade-local PaperBroker).**
>
>   This is the right call given three hard constraints: (1) `models.py` is a deliberate leaf with no
>   `openbb_backtest` import, (2) Q7 requires techtrade to be independently installable, and (3) the
>   #85 core-unchanged-when-removed test enforces this. A hard import (A1) would break all three.
>   The ~20 lines of duplicated slippage/commission math is a small price for clean decoupling, and
>   the parity test (the #73 oracle pattern) neutralizes the §19 duplication concern — if the formulas
>   diverge, the test catches it. A3 (soft-import fallback) adds two code paths for zero user benefit
>   in v1. A2 also lets techtrade define its own `BrokerInterface` Protocol matching §14.1 exactly
>   (`submit(order, bar) -> Fill | None`), rather than adapting to backtest's different `Broker.fill`
>   signature.
> `Order` carries `symbol` but **no bars**. To fill at *t+1* the broker needs bar *t+1*'s
> open/high/low. Two seams (recommend supporting both):
> - **B1 — explicit `bars=`**: `simulate(orders, bars=...)` takes the OHLCV window
>   (`list[Bar]` or `dict[symbol -> list[Bar]]`). Fully offline / deterministic / test- and
>   backtest-bridge-friendly; no look-ahead **by construction** (caller controls the window).
> - **B2 — injectable fetcher**: `simulate(orders, ohlcv_fetcher=...)` pulls *t+1..* via the
>   `fmp_cached` seam already used in `engine/universe.py`, `movers.py`, `indicators.py`. Live
>   default fetches; tests inject fakes.
> - **t+1 identity:** the signal's `as_of` (a session `date`) is bar *t*; *t+1* is the **next
>   trading session strictly after `as_of`**, resolved with the same `exchange_calendars` snap
>   `movers.resolve_session` already uses (`XNYS` default). **Open:** does `simulate` take `as_of`
>   explicitly, or read it from the originating `TradePlan`/`Order` context (`Order` has no `as_of`
>   today — would need to thread it through #77)?
>
> - **Recommendation:** support **both** seams — `bars=` (B1) as the offline/deterministic default
>   that the golden + backtest bridge use, and an injectable `ohlcv_fetcher=` (B2) for the live
>   `fmp_cached` path; take `as_of` as an **explicit** `simulate` param (do not retrofit `Order`),
>   resolving *t+1* via the `movers.resolve_session` calendar snap.
> - **Answer (Review):** ✅ **Approved — both seams + explicit `as_of`.**
>
>   Supporting both `bars=` and `ohlcv_fetcher=` is the right design: `bars=` makes the golden test
>   deterministic by construction (the test *controls* the data), while `ohlcv_fetcher=` provides the
>   live path without hardcoding it. Taking `as_of` explicitly (rather than retrofitting `Order`) is
>   correct — `Order` is a pure level/intent model that shouldn't carry temporal context. Calendar
>   resolution via `movers.resolve_session` reuses existing infrastructure and keeps *t+1* computation
>   in one place.

> **Q-C — `BrokerInterface` exact shape + the `Bar` / `PositionSnapshot` types.**
> §14.1 lists `submit` / `cancel` / `positions`. v1 batch sim only *needs* `submit`.
> - **C1 — full §14.1 (RECOMMENDED)**: ship all three. `cancel` is a no-op book entry; `positions()`
>   returns the internal position book. Cheap, and it is what makes the "swap in a live broker"
>   acceptance criterion real (a live impl must answer cancel/positions).
> - **C2 — trim to `submit()`** for v1, add the rest with the first live impl. Smaller surface, but
>   the Protocol no longer *is* the live contract.
> - **`Bar` / `PositionSnapshot` types:** reuse `openbb_backtest.models.Bar`/`PositionSnapshot`
>   (re-introduces the Q-A coupling), **or** define **minimal techtrade-local** ones in `models.py`
>   (`Bar`: `symbol`, `timestamp` tz-aware, OHLCV `Decimal`; `PositionSnapshot`: `symbol`,
>   `quantity` signed `Decimal`, `market_value`, `as_of`). Local keeps the leaf clean — recommended
>   if Q-A=A2.
>
> - **Recommendation:** ship the **full §14.1 surface** (C1 — `submit`/`cancel`/`positions`) so the
>   Protocol *is* the live contract, and define **minimal techtrade-local** `Bar`/`PositionSnapshot`
>   in `models.py` (consistent with the recommended Q-A=A2, keeping the leaf free of an
>   `openbb_backtest` import).
> - **Answer (Review):** ✅ **Approved — full Protocol (C1) + local types.**
>
>   1. **Full Protocol — correct.** Shipping all three methods (`submit`/`cancel`/`positions`) means
>      the Protocol *is* the live broker contract from day one. A future Alpaca/IBKR integration can
>      implement `BrokerInterface` and slot in without Protocol changes. If only `submit` shipped (C2),
>      adding `cancel`/`positions` later would be a breaking Protocol change affecting all
>      implementations. `cancel` as a no-op and `positions` returning the internal book are cheap.
>
>   2. **Local `Bar`/`PositionSnapshot` — correct under Q-A=A2.** If techtrade defines its own
>      `PaperBroker`, it needs its own input/output types. Importing backtest's `Bar` would reintroduce
>      the coupling A2 was chosen to avoid. The local types are minimal (OHLCV Decimal + tz-aware
>      timestamp; symbol + signed qty + market value) and serve as the Protocol's typed contract.

> **Q-D — `fill_model=` param shape + the config model.**
> The issue's signature is `simulate(orders, fill_model=...)`. Proposed: a single techtrade
> `FillModel` (or `BrokerConfig`) `Data` model bundling the three knobs from §14.1 —
> `commission` (kind `per_share`/`flat`/`percent`, `value:Decimal`, `min_per_trade:Decimal`),
> `slippage` (kind `fixed_bps`/`volume_share`/`spread`, `value:Decimal`), and `fill`
> (kind `next_bar_open`/`limit`, `limit_timeout_bars:int`). **Defaults: zero-commission +
> `fixed_bps` value 5** (L5). **Open:** one nested `fill_model` Data (recommended — single handle,
> matches the issue) vs three flat params (`commission_model`, `slippage_model`, `fill_kind`)?
> Note backtest already names these `CommissionModel`/`SlippageModel`/`FillModel`; if Q-A=A2 we
> re-declare equivalents (parity-tested), if A1 we reuse them verbatim.
>
> - **Recommendation:** one **nested `fill_model` `Data`** model (single handle matching the issue
>   signature) bundling `commission` / `slippage` / `fill`, defaulting to zero-commission +
>   `fixed_bps` value 5 (L5); under the recommended Q-A=A2 these are techtrade-local re-declarations
>   cross-checked by the §5.3 parity test.
> - **Answer (Review):** ✅ **Approved — single nested `FillModel` Data.**
>
>   A single `fill_model` handle is better UX than three flat params. The user passes one object
>   that says "here's how fills work" rather than separately configuring commission kind, slippage
>   kind, and fill kind. It also matches the issue signature (`simulate(orders, fill_model=...)`).
>   Defaults of zero-commission + 5 bps fixed slippage are standard for equity paper trading —
>   conservative enough to be realistic, simple enough to be the v1 default. The parity test against
>   backtest's equivalents (§5.3) catches any formula drift.

> **Q-E — intrabar stop/target evaluation, conservative tie-break, and the forward walk.**
> A `TradePlan` (#77) emits an **entry** order plus contingent **stop** / **target** / **time**
> exits (`intent` tags). `simulate` must:
> 1. Fill the entry at *t+1* **open ± slippage** (L1).
> 2. From *t+1* forward, on each bar test **stop** (`low ≤ stop` long / `high ≥ stop` short) and
>    **target** (`high ≥ target` long / `low ≤ target` short) **intrabar** against bar high/low.
> 3. **Conservative tie-break:** when **both** stop and target are touched in the *same* bar,
>    **the stop fills** (worst case for the trade) — §14.1 "conservative tie-breaking". Assume stop.
> 4. **Time stop:** at `max_holding_bars` (`EntryExitRule`, default 20) → `exit_time` fill.
> - **Open E1 — exit fill price:** a triggered stop fills at the **stop level ± slippage** (level-touch
>   model) vs the bar **open** vs **close**? Recommend stop→`stop_price ± slip`, target→`limit_price
>   ∓ slip` (favourable side capped at the level), conservative on gaps. Confirm.
> - **Open E2 — walk scope:** `simulate` walks bar-by-bar until the first exit triggers **or**
>   `max_holding_bars` — which means it needs a **bar window** `t+1 .. t+1+max_holding_bars`, not a
>   single bar (reinforces Q-B). Single-fill mode (entry only, no exit walk) as a lighter default?
>
> - **Recommendation:** evaluate stops/targets **intrabar** against high/low with the **conservative
>   stop-wins tie-break**; on a triggered exit fill stop→`stop_price ± slip`, target→`limit_price ∓
>   slip` (E1); walk the full `t+1 .. t+1+max_holding_bars` window and stop at the **first** exit
>   (E2), with entry-only single-fill available as an explicit lighter mode.
> - **Answer (Review):** ✅ **Approved — conservative tie-break + full walk + single-fill option.**
>
>   1. **Intrabar stop/target against high/low — correct.** Using only open/close would miss most
>      intraday stop/target triggers on daily bars. High/low is the standard approach for daily-bar
>      backtesting (Zipline, Backtrader, QuantConnect all do this).
>
>   2. **Conservative tie-break (stop wins) — correct and industry standard.** When both stop and
>      target are touched in the same bar, you don't know which happened first. Assuming the stop
>      (the worse outcome) is the conservative/honest choice. This prevents overstating strategy
>      performance. Every serious backtesting framework uses this convention.
>
>   3. **Exit fill at level ± slippage (E1) — correct.** Stop fills at `stop_price + adverse_slip`
>      (longs fill lower, shorts fill higher), target fills at `limit_price - adverse_slip`. This
>      is more realistic than filling at the bar open or close. Slippage on the exit mirrors the
>      entry treatment.
>
>   4. **Full walk with single-fill option (E2) — correct.** The full walk is needed for realistic
>      simulation. The entry-only lighter mode (`simulate=False` equivalent) is useful for dry runs
>      and the `scan` command's `simulate=False` mode (Q-C in #79).

> **Q-F — `Decimal` discipline + tz-aware timestamp source.**
> `price`/`commission`/`slippage`/`quantity` are `Decimal` (L6). `Fill.timestamp` is a **tz-aware
> `datetime`**, but techtrade `as_of` is a `date` (session). **Open:** derive the fill timestamp from
> the *t+1* `Bar.timestamp` when bars are supplied (already tz-aware UTC, like
> `openbb_backtest.models.Bar`); for date-only daily bars, localize to **session close in the
> exchange calendar's tz** (e.g. 16:00 `America/New_York`) → UTC. Confirm the localization rule so
> the no-look-ahead test can assert an exact, deterministic `t+1` timestamp.
>
> - **Recommendation:** keep `price`/`commission`/`slippage`/`quantity` as `Decimal` end-to-end; take
>   the fill timestamp from the supplied *t+1* `Bar.timestamp` when present, else localize a date-only
>   daily bar to **16:00 `America/New_York` → UTC**, so the golden test can assert an exact
>   deterministic tz-aware `t+1` timestamp.
> - **Answer (Review):** ✅ **Approved — Decimal end-to-end + 16:00 ET → UTC localization.**
>
>   1. **Decimal for all money/qty — non-negotiable.** This matches L6 and the discipline established
>      in #76. No float money can escape into `Fill` fields.
>
>   2. **Timestamp from `Bar.timestamp` when present — correct.** If the caller supplies bars with
>      tz-aware timestamps, use them directly. No ambiguity.
>
>   3. **16:00 America/New_York → UTC for date-only bars — sensible default.** US equity markets
>      close at 16:00 ET. Localizing to session close produces a deterministic, meaningful timestamp
>      that the golden test can pin. This is the same convention `exchange_calendars` uses for XNYS
>      session close. The UTC conversion ensures all timestamps are in a single timezone regardless
>      of the caller's locale.

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/
├── models.py                  # CHANGED (only if Q-A=A2 + Q-C=local types) — add leaf-level
│                              #   Bar + PositionSnapshot (Decimal OHLCV, tz-aware ts). NO
│                              #   openbb_backtest import (keeps techtrade standalone, Q7/#85).
│                              #   FillModel/BrokerConfig config Data also lands here (Q-D).
├── engine/
│   ├── broker.py              # NEW — BrokerInterface(Protocol, runtime_checkable) +
│   │                          #   PaperBroker(submit/cancel/positions) + local
│   │                          #   Commission/Slippage/FillModel helpers (mirror backtest math,
│   │                          #   parity-tested). The ONLY place fill price is decided.
│   ├── simulate.py            # NEW — simulate(orders, fill_model=..., bars=.../fetcher=...):
│   │                          #   resolves t+1 via calendar snap, walks the bar window, drives
│   │                          #   PaperBroker.submit per order, assembles list[Fill] (FillList).
│   └── plan_router.py         # CHANGED — add the `simulate` command beside `orders` (#77 owns
│                              #   this router). OR new engine/simulate_router.py (see §4 open).
tests/
├── unit/
│   └── test_paperbroker.py    # NEW — slippage/commission Decimal math; next-bar-open reference
│                              #   price; intrabar stop/target; conservative tie-break;
│                              #   Protocol conformance (isinstance vs runtime_checkable).
└── golden/
    └── test_no_lookahead.py   # NEW — THE enforcement: bar-t signal fills at t+1 ONLY;
                               #   broker never reads bar-t OHLC for the entry price.
```

**Module-boundary rules**
- `broker.py` depends only on `models` (+ `openbb_backtest.engine.execution` **iff** Q-A=A1). It
  never imports `confluence` / `rules` / `screener` — it consumes `Order` and a `Bar`, emits a
  `Fill`. This is the single seam a live broker later replaces.
- `simulate.py` is the **only** module that identifies *t+1* (calendar snap, mirroring
  `movers.resolve_session`) and that walks the bar window; it orchestrates, never re-computes fill
  price (that lives in `broker.py`).
- No cycles: `models ← broker ← simulate ← plan_router`. `models` stays a leaf (no
  `openbb_backtest` import under Q-A=A2 → `obb.techtrade.*` imports cleanly with backtest absent).

> **§9.1 naming note:** the PRD layout names a single `engine/execution.py` hosting
> "BrokerInterface + paper fill simulation + Recommendation builder". This issue splits the broker /
> fill half into `engine/broker.py` and leaves the **Recommendation builder** for #80 (which may keep
> the `engine/execution.py` name). Folding both into one `execution.py` is acceptable — flagged so
> #80 and #78 agree on the filename before code.

---

## 2. `BrokerInterface` — the live-ready Protocol (§14.1)

```python
# engine/broker.py  (shape under Q-A=A2 / Q-C=C1)
from __future__ import annotations
from typing import Protocol, runtime_checkable
from openbb_techtrade.models import Order, Fill, Bar, PositionSnapshot

@runtime_checkable
class BrokerInterface(Protocol):
    """Execution seam — paper now, live later, identical call sites (PRD §14.1)."""

    def submit(self, order: Order, bar: Bar) -> Fill | None:
        """Attempt to fill `order` against `bar`; None when it does not fill."""
        ...

    def cancel(self, order_ref: str) -> None:
        """Cancel a resting order by reference (no-op once filled)."""
        ...

    def positions(self) -> list[PositionSnapshot]:
        """Current open positions held by the broker book."""
        ...
```

- **Why a Protocol (not a base class):** `runtime_checkable` lets a unit test assert
  `isinstance(PaperBroker(...), BrokerInterface)` *and* lets any future Alpaca/IBKR client satisfy
  the contract structurally — the **swap-in-live** acceptance criterion, with **no inheritance
  coupling**. Mirrors the `openbb_backtest.interfaces.Broker` Protocol pattern (reuse-of-pattern, not
  of-code, under Q-A=A2).
- **v1 = `PaperBroker` only** (NG1). `cancel` records a book cancellation; `positions()` returns the
  internal book. Live routing is an explicitly out-of-scope later phase.

---

## 3. `PaperBroker` — fill logic (§14.1)

```python
class PaperBroker:                       # implements BrokerInterface structurally
    def __init__(self, fill_model: FillModel | None = None) -> None:
        self._fm = fill_model or FillModel()          # zero-commission + 5 bps (L5)
        self._book: dict[str, Decimal] = {}           # symbol -> signed qty
```

**3.1 Entry — next-bar-open ± slippage (L1)**
- `intent="entry"`, `order_type="market"`: reference price = **bar *t+1* `open`**
  (`FillModel.reference_price`, mirroring backtest). Slippage is a **signed, adverse** per-share
  adjustment (buy → `+`, sell/short → `−`); `fill_price = open + slip`. Commission computed on the
  *filled* price. `slippage` field stores `abs(slip) * quantity` (cost component), `price` stores the
  post-slippage fill — exactly the `Fill` contract (L4).
- `order_type="limit"` (configurable-offset entry, §13): marketable test against the *t+1* range
  (`limit_marketable`); unfilled → `submit` returns `None` (optionally retried for
  `limit_timeout_bars`).

**3.2 Exit — intrabar stop/target vs bar high/low (Q-E)**
- For each forward bar, evaluate contingent exits against **high/low** (not open/close):
  - long: **stop** if `low ≤ stop_price`; **target** if `high ≥ limit_price`.
  - short: **stop** if `high ≥ stop_price`; **target** if `low ≤ limit_price`.
- **Conservative tie-break:** both touched in one bar ⇒ **stop fills** (assume the adverse path) —
  §14.1. Exit fill price per Q-E/E1 (recommend stop→`stop_price ± slip`, target→`limit_price ∓ slip`).

**3.3 Commission + slippage models (mirror §14.1 matrix)**

| Model | Kinds | Default | Formula (per `openbb-backtest` parity) |
|---|---|---|---|
| Commission | `per_share` / `flat` / `percent` | **flat 0** (zero-commission) | `per_share: qty·value` · `flat: value` · `percent: qty·price·value`; `max(cost, min_per_trade)` |
| Slippage | `fixed_bps` / `volume_share` / `spread` | **fixed_bps 5** | `fixed_bps: price·value/1e4` · `volume_share: price·value·(qty/bar.volume)` · `spread: price·(spread_bps/1e4)/2`; signed by side |

**3.4 Forward walk (Q-E/E2)**
`simulate` (not the broker) advances *t+1, t+2, …* up to `max_holding_bars`, calling `submit` for the
entry on *t+1* then testing the contingent exits each bar; the **first** exit (stop/target/time/
opposite-signal) closes the position and ends the walk. The broker stays stateless-per-call; the walk
state lives in `simulate`.

> **No-look-ahead is structural here:** the entry references bar *t+1*'s `open`, and exits scan only
> bars *≥ t+1* (high/low). Bar *t* — the signal bar — is **never** read by the broker. A stop/target
> *may* trigger on *t+1* itself (the position is open at the *t+1* open); that is **not** look-ahead
> because *t+1 > t*. The forbidden case (entry or exit referencing bar *t*) is what §5 locks down.

---

## 4. `simulate` command (`obb.techtrade.simulate`)

```python
# engine/plan_router.py (or engine/simulate_router.py — open below)
@router.command(methods=["POST"])
def simulate(
    orders: list[Order],
    fill_model: FillModel | None = None,     # Q-D: zero-commission + 5 bps default
    bars: ... | None = None,                 # Q-B: explicit OHLCV window (offline/test)
    as_of: str | None = None,                # Q-B: bar-t session; t+1 via calendar snap
    # ohlcv_fetcher seam injected internally; fmp_cached live default
) -> OBBject:
    """Paper-fill `orders` and return a FillList (list[Fill]). PRD §14.1."""
    from openbb_techtrade.engine.simulate import simulate_orders
    return OBBject(results=simulate_orders(orders, fill_model=fill_model, bars=bars, as_of=as_of))
```

- **Output:** `OBBject` whose `results` is `list[Fill]` — the **FillList** (L7). Each `Fill` carries
  `price` (after slippage), `commission`, `slippage`, and a tz-aware *t+1* `timestamp`. The same
  list lands on `TradePlan.simulated_fills` (#77) and is consumed by #80 (Recommendation builder) for
  the realized entry price.
- **Return-annotation rule:** the command returns a **bare `OBBject`** (no parametrized model) so the
  static package builder renders an importable annotation — the established `techtrade_router` /
  `screener_router` pattern; the `list[Fill]` payload is documented in the docstring.
- **`positions`:** §14.1 lists "FillList **plus** updated positions". v1 returns the FillList as the
  primary payload; positions are reachable via `PaperBroker.positions()` for live-readiness. **Open:**
  also attach a positions list to the OBBject, or keep `simulate` fill-only?

> **Router placement (open):** add `simulate` to the existing `plan_router` (keeps
> `plan → orders → simulate` together, the natural #77 grouping) **vs** a dedicated
> `engine/simulate_router.py` (cleaner single-responsibility, one more lazy include in
> `techtrade_router._include_subrouters`). Recommend `plan_router` for cohesion.

---

## 5. No-look-ahead discipline & testing

### 5.1 `tests/golden/test_no_lookahead.py` — the enforcement (acceptance)

The one test this issue exists to guarantee: **a bar-*t* signal fills at *t+1* only.**

```python
# deterministic OHLCV: bar t (as_of) has a DISTINCT open from bar t+1 so a same-bar
# fill is detectable by price alone.
def test_signal_at_t_fills_at_t_plus_one_only():
    fills = simulate_orders([entry_order], bars=window, as_of=T)   # T == bar-t session
    f = fills[0]
    # (a) timestamp identity: fill is stamped t+1, never t
    assert f.timestamp.date() == next_session(T)        # == t+1
    assert f.timestamp.date() != T
    # (b) price provenance: fill price derives from bar t+1 open (± slippage), NOT bar t open
    assert _base_of(f) == window[T1].open               # never window[T].open
    # (c) tz-aware (Q-F)
    assert f.timestamp.tzinfo is not None
```

- **How it's enforced:** the fixture sets `bar_t.open ≠ bar_{t+1}.open`; a regression that peeked at
  bar *t* would yield `bar_t.open`-derived price and fail assertion (b). The timestamp assertion (a)
  catches a same-bar timestamp. Carries the `golden` marker; seeded, offline, deterministic.
- **Exit-side variant:** a stop placed so it would have triggered on bar *t* must **not** fill until a
  bar *≥ t+1* touches it — asserts the forward walk never reaches back to *t*.

### 5.2 `tests/unit/test_paperbroker.py` — fill math (offline)

| Assertion | Locks |
|---|---|
| `fixed_bps` 5 on a known price → exact `Decimal` slippage; buy fills **higher**, sell **lower** | §14.1 default, L6 adverse-sign |
| `flat` / `per_share` / `percent` commission → exact `Decimal`, `min_per_trade` floor respected | §14.1 commission matrix |
| entry reference price == bar *t+1* `open`; `price == open + signed_slip` | L1 / §3.1 |
| intrabar: long stop on `low ≤ stop`; target on `high ≥ limit`; short mirrored | §3.2 |
| **conservative tie-break** — both touched ⇒ **stop** fill | §14.1 |
| `isinstance(PaperBroker(...), BrokerInterface)` | L3 swap-in-live contract |
| money/qty are `Decimal` end-to-end; no `float` leaks into `Fill` | L6 |

### 5.3 Parity check (only if Q-A=A2 — reuse-of-pattern, not code)

When `openbb-backtest` is importable, a parity test (the #73 oracle pattern) cross-checks techtrade's
local `Commission`/`Slippage`/next-bar-open `reference_price` against
`openbb_backtest.engine.execution` on a shared fixture, within `Decimal` exactness. This is what
**buys back the §19 anti-duplication guarantee without the hard dependency** — `importorskip`-style,
skipped cleanly when backtest is absent (preserving Q7 standalone / #85).

---

## Acceptance mapping (#78)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| `BrokerInterface` Protocol (live-ready) + `PaperBroker` impl | §2 (Protocol), §3 (PaperBroker); L3 |
| Next-bar-open fill (no look-ahead) with slippage + commission | §3.1 (open ± slippage), §3.3 (models); L1/L5/L6 |
| `simulate(orders, fill_model=...)` → `FillList` | §4 (`obb.techtrade.simulate` → `OBBject[list[Fill]]`); L7 |
| Fills have **price-after-slippage + commission** | §3.1/§3.3 → `Fill.price`/`commission`/`slippage` (L4) |
| **No same-bar peeking** — test enforced | §5.1 `test_no_lookahead.py` (timestamp + price-provenance asserts) |
| Bar-*t* signals fill at *t+1* only (golden) | §5.1; §3 structural argument; PRD §13 |
| `PaperBroker` swappable for a future live impl via the Protocol | §2 `runtime_checkable` Protocol; §5.2 `isinstance` test |
| (§19) indicator/exec duplication risk mitigated | Q-A=A2 + §5.3 parity check (or Q-A=A1 direct reuse) |
| (Q7 / #85) techtrade stays independently installable | §1 leaf `models`, no `openbb_backtest` import under A2 |
| Feeds #77 (`TradePlan.simulated_fills`) and #80 (Recommendation realized entry) | §4 FillList → `simulated_fills`; L4/L7 |
