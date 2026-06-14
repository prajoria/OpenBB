# 79 — scan Command: All Sectors → Ranked TradePlans

**GitHub:** [#79](https://github.com/prajoria/OpenBB/issues/79) · **Phase:** P4 · **Sprint:** 5 · **Size:** M
**Depends on:** [#78](https://github.com/prajoria/OpenBB/issues/78) (paper fill sim — `simulate` / `PaperBroker`)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §9.2 (command surface), §10 (segment & top-mover screening); reuse rule §19; resolved questions §20 Q2/Q3
**Scope:** Add `obb.techtrade.scan(metric=…, top_n=…, preset=…)` — the **one-call orchestrator** that screens all 11 GICS sectors, runs each segment's movers through the existing signals→rules→orders→fills chain, and returns a **cross-segment ranked** `list[TradePlan]`. `scan` is pure **composition over existing engines** (no new signal/rule/order/fill logic), plus an integration test over a small multi-sector universe asserting deterministic ordering for a fixed as-of.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

> **⚠ Stale issue refs in the #79 body — corrected here.** The issue's acceptance line "reuses
> **#6/#11/#13/#14**" predates the current techtrade numbering; those IDs do **not** exist in this
> project. They map 1:1 onto the real techtrade chain `scan` composes:
>
> | Stale ref (issue body) | Real techtrade issue | Surface `scan` reuses |
> |---|---|---|
> | `#6` | [#73](https://github.com/prajoria/OpenBB/issues/73) ([design](./73-indicator-adapter-selector-parity-bulk.md)) | bulk indicator panels (`engine/bulk.build_panels_bulk`) |
> | `#11` | [#75](https://github.com/prajoria/OpenBB/issues/75) ([design](./75-signals-command-presets.md)) | confluence signals (`signals` → `MoverSignal`) |
> | `#13` | [#77](https://github.com/prajoria/OpenBB/issues/77) ([design](./77-order-generation-tradeplan.md)) | orders + `TradePlan` (`plan` / `engine/orders.build_plan`) |
> | `#14` | [#78](https://github.com/prajoria/OpenBB/issues/78) ([design](./78-paperbroker-fill-sim.md)) | paper fills (`simulate` / `PaperBroker`) |
>
> The screener/mover front of the chain ([#69](https://github.com/prajoria/OpenBB/issues/69) universe
> resolver, [#70](https://github.com/prajoria/OpenBB/issues/70) movers) and the rules/sizing stage
> ([#76](https://github.com/prajoria/OpenBB/issues/76)) are implicit upstream of `#13`→#77 and are
> reused identically.

---

## What this is

**`scan`** is the **one-call orchestrator**: a single command that sweeps **all 11 market sectors**
at once and returns a cross-sector **ranked list of `TradePlan`s**. For each sector it chains the
whole techtrade pipeline end to end — screen for the top movers → compute confluence signals
([#75 design](./75-signals-command-presets.md)) → apply entry/exit rules + position sizing
([#76 design](./76-entryexit-rule-sizing.md)) → generate orders into a `TradePlan`
([#77 design](./77-order-generation-tradeplan.md)) → paper-fill them
([#78 design](./78-paperbroker-fill-sim.md)) — then ranks the resulting plans **against each other**
so the strongest setups across the entire market float to the top.

It exists because the per-symbol and per-segment commands only answer *"what about THIS name / THIS
sector?"*; `scan` answers the trader's real morning question — *"across the whole market today, what
are the best setups?"*. It is pure **composition**: it reuses the existing
screener / signals / rules / orders / fills engines **without re-implementing any of their logic**
(the deliberate anti-duplication principle of §19), adding **only** the cross-segment ranking and
deterministic ordering on top. In short, `scan` owns just the **fan-out** across sectors (left edge)
and the final **rank** (right edge) — every box in between is an already-built engine call.

---

## 0. Key decisions (locked) + open questions

### 0.1 Locked (from PRD §10, §20 Q2/Q3, and the existing screener/mover engine)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | Segment taxonomy | **11 GICS sectors, fixed** (PRD §20 **Q2**) — `screener.GICS_SECTOR_ETFS`, canonical insertion order XLK/XLF/XLE/XLV/XLY/XLP/XLI/XLB/XLRE/XLU/XLC | `scan` iterates exactly that ordered map; no industry-group / cap-tier axes in v1 |
| L2 | Universe source | **`etf_holdings` default** (PRD §20 **Q3**) — `SegmentConfig.universe_source="etf_holdings"`, `constituent_list` / `screener` remain configurable | Reuses `engine.universe.resolve_universe` as-is; `scan` passes the source through, never re-resolves membership |
| L3 | Mover pool | **Reuse `equity.discovery`** (gainers/losers/active) via `engine.movers.list_movers` (PRD §10) | No second screener; `scan` calls the existing per-segment mover ranker, no candidate logic of its own |
| L4 | Composition only | `scan` **reuses** the chain `movers (#70) → panels (#73) → signals (#75) → rules (#76) → orders (#77) → fills (#78)`; it adds **only** the cross-segment fan-out + final ranking | §19 anti-duplication: `scan` contains **zero** indicator / vote / sizing / order / fill math (§2) |
| L5 | Determinism | **Fixed as-of** (calendar-snapped `XNYS` once, parent-side) + **fixed sector→ETF map** + **stable total-order tie-break** | Identical `scan(...)` output for a fixed as-of, byte-stable under `to_jsonable` (§5) |
| L6 | Fills included | `scan` runs through **`simulate` (#78)** so each returned `TradePlan` carries `simulated_fills` (issue: "…→ orders → **fills**") | `scan` needs *t+1* bar data for the planned symbols (§2.3, **Q-C**) |
| L7 | Return / wiring | `OBBject[list[TradePlan]]`; `scan` attaches as a command on **[`engine/plan_router.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py)** (the #77 router already in `techtrade_router._include_subrouters`); bare-`OBBject` return per the static-package-builder rule | One more command beside `plan` / `orders` / `simulate`; no new sub-router include needed |

### 0.2 Open questions (please review / brainstorm)

> **Q-A — cross-segment ranking key + `top_n` semantics. ← most important.**
> The issue says "**ranked** `TradePlan`s across all 11 sectors" but does not name the rank key.
> `TradePlan` exposes several candidate keys; each implies a different "best plan":
>
> | Candidate key | Source field | Behaviour | Note |
> |---|---|---|---|
> | **`|score|`** (RECOMMEND) | `plan.signal.score` (∈ [-1,+1]) | strongest **conviction**, long **or** short | direction-neutral; surfaces the most decisive setups |
> | raw `score` | `plan.signal.score` | longs float to top, shorts sink | biased; only sensible if `scan` is long-only |
> | `risk_reward` | `plan.recommendation.risk_reward` | reward:risk ordering | near-constant pre-fill (= `target_r_multiple`, default 2.0) → poor discriminator; also needs #80 |
> | composite | `|score|` × mover signal | blends conviction + mover strength | most "tunable", least transparent; weights are arbitrary (§19 distrust risk) |
>
> **Recommend `|score|` descending** (conviction magnitude) as the cross-segment key, with the §3
> total-order tie-break. **Confirm** — and confirm `flat`/sub-threshold plans (`|score| <
> entry_threshold`, empty `orders`) are **ranked last / filtered**, not interleaved.
>
> **`top_n` is overloaded — disambiguate.** Two distinct caps are in play:
> 1. **per-segment mover `top_n`** (already exists: `movers.list_movers(top_n=…)`, `SegmentConfig.top_n`) — how many movers per sector enter the chain;
> 2. a hypothetical **global N** — how many *plans* the cross-segment sort returns.
>
> | Option | `top_n` means | Output size |
> |---|---|---|
> | **(i) RECOMMEND** | per-segment cap (reuse existing semantics) | ≤ `11 × top_n` plans, **all** returned fully sorted |
> | (ii) | global cap after merge | exactly `top_n` plans (or fewer) |
> | (iii) | both — add a separate `limit=` for the global cap | per-segment `top_n` + global `limit` |
>
> Recommend **(i)** (keeps `top_n` consistent with `movers`/`plan`; "ranked across all sectors" =
> the full sorted set), with **(iii)**'s optional `limit=` as a thin top-of-list slice if a bounded
> result is wanted. **Also disambiguate `metric=`:** it is the **mover** `rank_metric`
> (`pct_change`/`volume`/`gap`/`rel_volume`) selecting *which* movers per sector — it is **not** the
> cross-segment plan-rank key (Q-A's `|score|`). These are two different knobs; the command doc must
> say so.

> **Q-B — orchestration shape: loop `plan(segment=…)` ×11, or fan out once over the union? (the §19 lever)**
> #77's `plan(segment=…)` already runs `movers → #73 bulk panels → signals → rules → orders` for one
> sector. Two shapes for `scan`:
>
> | Shape | How | Pro | Con |
> |---|---|---|---|
> | **B1 — loop the command** | call `plan(segment=s)` for each of the 11 sectors, concat, sort | maximal reuse, trivially correct, zero new internals | **11 separate `build_panels_bulk` spawn pools** → 11× spawn-import cost (#73 NFR §17); per-sector `as_of` re-snapped 11× |
> | **B2 — fan out once (RECOMMEND)** | gather the union of movers across all 11 sectors first, then **one** `build_panels_bulk(union)`, then map each symbol through the **same** `signals→rules→orders` engine functions `plan` uses, then one `simulate` | single spawn pool (amortized), one `as_of` snap, best throughput | must call the **shared engine builder**, not re-walk `plan`'s body — see the duplication note ↓ |
>
> **Recommend B2**, but it forces a **factoring decision**: to avoid re-implementing `plan`'s
> per-symbol body (which would *be* the §19 violation), #77's plan internals should expose a reusable
> engine seam — e.g. `engine.plan.build_plans_for_symbols(symbols, as_of, preset, risk) ->
> list[TradePlan]` — that **both** `plan(symbols|segment)` (#77) **and** `scan` (#79) call.
> `scan` then = `resolve movers (11 sectors) → build_panels_bulk(union) → build_plans_for_symbols(…)
> → simulate → rank`. **Open:** is that shared builder already factored by #77, or does #79 land the
> refactor (and is that in scope for a Size-M issue)? If #77 only exposes the `plan` *command*,
> fall back to **B1** for v1 and file a follow-up to factor the seam. Where `#73 build_panels_bulk`
> plugs in is the throughput crux: **once, over the union** (B2) vs **per sector** (B1).

> **Q-C — does `scan` run `simulate` (#78) inline (fills), or stop at orders?**
> The issue scope says "…→ orders → **fills**" and the acceptance says "ranked `TradePlan`s", so
> **L6 includes fills**: `scan` calls `simulate` so each `TradePlan.simulated_fills` is populated.
> That pulls #78's **bar-data requirement** into `scan`: `simulate` needs the *t+1…* OHLCV window per
> planned symbol (#78 Q-B). For 11 sectors × `top_n` symbols this is a **non-trivial fetch**.
> Sub-questions:
> - **C1 — bar seam:** does `scan` accept an explicit `bars=`/`ohlcv_fetcher=` seam (like `simulate`)
>   so the integration test runs offline, with `fmp_cached` as the live default? (Recommend: **yes**,
>   forward the same seam #78 exposes.)
> - **C2 — fills optional?** add `simulate: bool = True` so `scan` can stop at the order skeleton
>   when bar data is unavailable / for a cheap dry-run? (Recommend: **yes**, default `True` per L6.)
> - **C3 — ranking before or after fills?** `|score|` (Q-A) is known **pre-fill**, so ranking does
>   **not** depend on `simulate`. Recommend rank on `signal.score` so the order is identical whether
>   or not fills ran (keeps the rank deterministic and `simulate`-independent).

> **Q-D — determinism mechanics (what exactly makes `scan` reproducible).**
> - **as_of:** snap **once** in the parent via `movers.resolve_session(as_of, "XNYS")`, pass the
>   resolved `date` down to every segment + to `simulate`'s *t+1* (no per-segment re-snap, no
>   look-ahead drift). Confirm `XNYS` is the only calendar for v1.
> - **sector order:** iterate `GICS_SECTOR_ETFS` insertion order (L1) — fixed.
> - **tie-break:** equal `|score|` is common (e.g. two symbols at 0.40). Mirror the existing
>   `rank_movers` discipline (`key=(-metric, symbol)`) and **extend to a total order** with
>   `segment` as the final key: `key = (-round(|score|, 9), symbol, segment)` (§3). A symbol can
>   surface in two sector ETFs, so `symbol` alone is not unique across segments — `segment` closes
>   the order. Confirm the rounding ε and the key tuple.
> - **integration fixture:** seed a small **offline** multi-sector universe (≥3 sectors, a handful of
>   symbols each) via the injectable `candidate_fetcher` / `ohlcv_fetcher` / `bars=` seams so the
>   "deterministic ordering for a fixed as-of" test needs **no API key** (§5).

> **Q-E — failure isolation + performance across 11 sectors.**
> - **isolation:** if one sector's mover fetch, one symbol's panel, or one `simulate` window fails,
>   does `scan` **skip-and-continue** (drop that symbol/sector, keep the rest) or **fail whole**?
>   Recommend **skip-and-continue** — it mirrors `movers._default_candidate_fetcher` (already wraps
>   each discovery source / symbol in `try/except: continue`) and `_resolve_filter_universe`
>   (degrades to no-filter on resolution failure). A `scan` that aborts because one of ~110 symbols
>   404s is hostile. **Open:** surface skipped symbols as a warning / in `OBBject.warnings`?
> - **performance:** 11 sectors × `top_n` symbols → reuse the **#73 spawn pool** exactly once over
>   the union (Q-B B2). NFR §17: throughput ≈ `single_symbol_cost × N / cores`. The integration test
>   stays small (offline fixture) so CI cost is bounded.

Each open question carries an approvable placeholder (mirroring the PRD §20 convention): a concrete
**Recommendation** restating the leaning above, plus an **Answer** line for the user to sign off.

#### Q-A — cross-segment ranking key + `top_n` semantics

Which key orders the merged plans, and what do `top_n` / `metric` each mean? The issue says "ranked
`TradePlan`s across all 11 sectors" but names neither the rank key nor whether `top_n` is per-segment
or global. This is the most important open question — it defines what "best setup" means.

- **Recommendation:** Rank by **`|score|` descending** (conviction magnitude, direction-neutral) with
  the §3 total-order tie-break; `flat` / sub-threshold plans (`|score| < entry_threshold`, empty
  `orders`) rank **last / filtered**, not interleaved. `top_n` keeps its existing **per-segment** mover
  meaning (opt-i, ≤ `11×top_n` plans, all returned sorted) with an optional global `limit=` top-slice
  (opt-iii); `metric=` is the **mover** `rank_metric` selecting *which* movers per sector, **not** the
  cross-segment plan-rank key — see §3.
- **Answer:** _(pending approval)_

#### Q-B — orchestration shape: loop `plan(segment=…)` ×11, or fan out once over the union?

Does `scan` loop the existing `plan` command per sector (B1), or gather the union of movers across all
11 sectors and run **one** `build_panels_bulk` + shared plan builder (B2)? This is the §19 lever —
B2's throughput requires reusing #77's per-symbol body rather than re-walking it.

- **Recommendation:** Prefer **B2** (one spawn pool, one `as_of` snap), which forces #77 to expose a
  reusable `engine.plan.build_plans_for_symbols(symbols, as_of, preset, risk) -> list[TradePlan]` seam
  called by **both** `plan` and `scan`. **Open:** if #77 only exposes the `plan` *command* (no shared
  builder), fall back to **B1** for v1 and file a follow-up to factor the seam — see §2.
- **Answer:** _(pending approval)_

#### Q-C — does `scan` run `simulate` (#78) inline (fills), or stop at orders?

The scope says "…→ orders → **fills**", so should each returned `TradePlan` carry `simulated_fills`,
and how does that pull #78's *t+1* bar-data requirement into `scan`? Settles the bar seam, an opt-out,
and whether ranking depends on fills.

- **Recommendation:** Include fills inline per **L6** (`simulate` runs so `simulated_fills` is
  populated). **C1:** forward the same injectable `bars=` / `ohlcv_fetcher=` seam #78 exposes (live
  default `fmp_cached`, offline in tests) — yes. **C2:** add `simulate: bool = True` so the order
  skeleton can be returned without bar data — yes, default `True`. **C3:** rank on `signal.score`
  (**pre-fill**) so the order is identical with or without `simulate` — see §3 / §5.
- **Answer:** _(pending approval)_

#### Q-D — determinism mechanics (what exactly makes `scan` reproducible)

Which inputs are pinned so `scan(...)` is byte-identical for a fixed as-of — the calendar snap, sector
order, tie-break key tuple, rounding ε, and the offline fixture seams? Confirms the precise total-order
key and that no per-segment re-snap leaks look-ahead.

- **Recommendation:** Snap `as_of` **once** parent-side via `movers.resolve_session(as_of, "XNYS")`
  and thread the resolved `date` everywhere (confirm `XNYS` is the only v1 calendar); iterate
  `GICS_SECTOR_ETFS` insertion order (L1); total-order tie-break `key = (-round(|score|, 9), symbol,
  segment)` (`segment` closes the order since a symbol can appear in two sector ETFs); seed the
  integration fixture offline via the `candidate_fetcher` / `ohlcv_fetcher` / `bars=` seams — see §5.
- **Answer:** _(pending approval)_

#### Q-E — failure isolation + performance across 11 sectors

If one sector's mover fetch, one symbol's panel, or one `simulate` window fails, does `scan`
skip-and-continue or fail whole — and should skipped symbols surface as warnings? Also: how is the
11-sector × `top_n` fetch kept cheap?

- **Recommendation:** **Skip-and-continue** (drop the failing symbol/sector, keep the rest) — mirrors
  `movers._default_candidate_fetcher` and `_resolve_filter_universe`, which already degrade rather than
  abort; aborting because one of ~110 symbols 404s is hostile. **Open:** surface skipped symbols in
  `OBBject.warnings`. For performance, reuse the **#73 spawn pool** exactly once over the union (Q-B
  B2); keep the integration test on a small offline fixture so CI cost is bounded — see §2 / §5.
- **Answer:** _(pending approval)_

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/engine/
├── screener.py          # EXISTING (#68) — GICS_SECTOR_ETFS, list_segments(). REUSED read-only:
│                        #   the canonical 11-sector ordered map scan iterates (L1).
├── movers.py            # EXISTING (#70) — list_movers(segment=None,…) already ranks ALL 11
│                        #   sectors -> list[MoverList]; resolve_session() (XNYS snap). REUSED.
├── bulk.py              # EXISTING (#73) — build_panels_bulk(symbols,…) spawn pool. REUSED ONCE
│                        #   over the union of movers (Q-B B2), not per sector.
├── plan.py / orders.py  # EXISTING (#77) — build_plan / (proposed) build_plans_for_symbols seam.
│                        #   REUSED: scan maps each symbol through the SAME builder (Q-B, §19).
├── simulate.py          # EXISTING (#78) — simulate_orders(orders, fill_model, bars/fetcher,…).
│                        #   REUSED to populate TradePlan.simulated_fills (L6, Q-C).
├── scan.py              # NEW (#79) — the orchestrator. scan_segments(metric, top_n, preset,
│                        #   risk, as_of, simulate=True, …) -> list[TradePlan]:
│                        #   fan-out (11 sectors) -> union -> reuse chain -> cross-segment rank.
│                        #   Contains NO signal/rule/order/fill math (§19) — only fan-out + sort.
└── plan_router.py       # CHANGED (#77 owns it) — add the `scan` command beside plan/orders/
                         #   simulate. Already lazily included by techtrade_router (L7).

openbb_platform/extensions/techtrade/tests/
├── integration/
│   └── test_scan.py     # NEW — small multi-sector universe (offline fixture via seams);
│                        #   asserts ranked list + deterministic ordering for a fixed as-of (§5).
└── unit/
    └── test_scan.py     # NEW (recommended) — fan-out + cross-segment sort + tie-break on
                         #   hand-built TradePlans; fully offline, no chain calls (§5).
```

**Module-boundary rules**
- `scan.py` **composes engines, it does not re-implement them.** It imports `screener` (sector map),
  `movers` (mover ranking + `resolve_session`), `bulk` (panels), the #77 plan builder, and
  `simulate` — and adds *only* the fan-out loop + the final `sorted(...)`. Any indicator / vote /
  ATR / sizing / order-mapping / fill formula appearing in `scan.py` is a §19 regression by
  definition (a unit test can assert `scan.py` imports the chain rather than `indicators`/`rules`).
- `scan` resolves `as_of` **once** (parent-side `movers.resolve_session`) and threads the resolved
  `date` everywhere — the single determinism seam (L5, Q-D).
- `plan_router.scan` is **thin**: validate args → `scan.scan_segments(...)` → `OBBject(results=…)`.
- No cycles: `scan → {screener, movers, bulk, plan, simulate, models}`; router → `scan`.

---

## 2. Orchestration chain (reuse map — real refs)

`scan` is the **orchestrator** that stitches the already-built stages. Nothing below is new logic;
`scan` owns only the **fan-out** (left edge) and the **rank** (right edge).

```
            ┌────────────────────────  scan(metric, top_n, preset, risk, as_of)  ────────────────────────┐
            │                                                                                             │
 11 GICS    │  movers.list_movers(           panels             signals          rules+sizing    orders   │   simulate        cross-segment
 sectors  ──┼─▶ segment=None,        ─▶ bulk.build_panels  ─▶ signals(#75)  ─▶  rules(#76)   ─▶  build_  ─┼─▶ simulate    ─▶  sort by |score|
 (L1)       │   metric=, top_n=)         _bulk(UNION,#73)      MoverSignal       levels+size     plan(#77)│   (#78)→fills      → list[TradePlan]
            │   reuse #70 + equity.discovery (PRD §10)        score∈[-1,+1]     EntryExitRule    TradePlan│   simulated_fills  (Q-A / §3)
            └─────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Stage | Real issue | Engine surface `scan` calls | `scan` adds |
|---|---|---|---|
| Segment map | [#68] | `screener.GICS_SECTOR_ETFS` (11, ordered) | iterate (L1) |
| Movers / segment | [#70] | `movers.list_movers(segment=None, metric=, top_n=, as_of=)` → `list[MoverList]` | gather the **union** of symbols |
| Bulk panels | **[#73]** (stale `#6`) | `bulk.build_panels_bulk(union, as_of=…)` | call **once** over the union (Q-B) |
| Signals | **[#75]** (stale `#11`) | confluence → `MoverSignal` (`score`, `direction`, `rank_in_segment`) | — |
| Rules + sizing | [#76] | `EntryExitRule` eval → levels + `position_size` | — |
| Orders + plan | **[#77]** (stale `#13`) | `plan` / `orders.build_plan` → `TradePlan` skeleton | — |
| Fills | **[#78]** (stale `#14`) | `simulate(orders, bars/fetcher)` → `list[Fill]` → `simulated_fills` | inline per L6 (Q-C) |
| **Cross-segment rank** | **#79 (this)** | — | `sorted(plans, key=…)` (§3) |

> **The §19 contract, restated:** every box except the leftmost (fan-out) and rightmost (rank) is an
> **existing** techtrade engine call. `scan` introduces no parallel implementation of any of them.
> The recommended B2 shape (Q-B) reuses #77's per-symbol plan builder via a shared engine seam so
> the chain body is written **once** and called by both `plan` and `scan`.

---

## 3. Cross-segment ranking (§9.2 "ranked `TradePlan`s")

Per-segment ranking already exists (`MoverSignal.rank_in_segment`, `Mover.rank`). #79 adds the
**cross-segment** ranking that merges all sectors into one ordered list.

**Rank key (Q-A — recommended):** conviction magnitude, direction-neutral.

```python
# scan.py — the ONLY new ordering logic in #79 (pure, deterministic, offline)
def _rank_key(plan: TradePlan) -> tuple:
    score = plan.signal.score
    # primary: strongest |score| first; ties broken to a TOTAL order so the
    # output is byte-identical for a fixed as-of (L5, Q-D).
    return (-round(abs(score), 9), plan.symbol, plan.segment)

ranked = sorted(plans, key=_rank_key)
```

| Property | Rule | Why |
|---|---|---|
| Primary key | `-|score|` (conviction, long **or** short) | surfaces the most decisive setups regardless of side (Q-A) |
| Tie-break 1 | `symbol` ascending | mirrors `movers.rank_movers` `(-metric, symbol)` discipline |
| Tie-break 2 | `segment` ascending | a symbol can appear in two sector ETFs → `symbol` alone isn't unique; `segment` closes the **total** order (Q-D) |
| Sub-threshold / `flat` | ranked **last** or filtered (Q-A) | `|score| < entry_threshold` ⇒ empty `orders`; not an actionable plan |
| `top_n` | per-segment mover cap (Q-A opt-i); optional global `limit=` slice | "ranked across all sectors" = full sorted set, ≤ `11×top_n` |
| Rank independence | key uses `signal.score` only (**pre-fill**) | order is identical with or without `simulate` (Q-C C3) |

> **Rounding ε (`round(…, 9)`):** two genuinely-equal scores must compare equal so the symbol
> tie-break decides — float noise at the 1e-12 level must not reorder the list. Matches the
> `testing.DEFAULT_TOL = 1e-9` golden tolerance already used across techtrade.

---

## 4. Command surface (§9.2)

```python
# engine/plan_router.py — new command beside plan / orders / simulate (bare OBBject return)

@router.command(methods=["GET"])
def scan(
    metric: str = "pct_change",      # MOVER rank_metric (pct_change/volume/gap/rel_volume) — Q-A
    top_n: int = 10,                 # per-segment mover cap (reuses movers/SegmentConfig) — Q-A(i)
    preset: str = "trend_follow",    # confluence/rule preset forwarded to #75/#76
    risk: float | None = None,       # risk_per_trade fraction -> #76 sizing (mirrors plan, #77 Q-D)
    as_of: str | None = None,        # snapped ONCE to last XNYS session (look-ahead-free) — Q-D
    simulate: bool = True,           # run #78 fills inline (L6); False = order skeleton only — Q-C2
    limit: int | None = None,        # optional global top-of-list slice after the sort — Q-A(iii)
) -> OBBject:
    """One-call scan: screen all 11 GICS sectors -> cross-segment ranked TradePlans.

    results -> list[TradePlan], ranked by |signal.score| desc (symbol, segment tie-break).
    """
    from openbb_techtrade.engine.scan import scan_segments
    return OBBject(results=scan_segments(
        metric=metric, top_n=top_n, preset=preset, risk=risk,
        as_of=as_of, simulate=simulate, limit=limit,
    ))
```

| Command | Input | `results` payload | Notes |
|---|---|---|---|
| `obb.techtrade.scan(...)` | `metric`, `top_n`, `preset`, `risk`, `as_of`, `simulate`, `limit` | `list[TradePlan]` | all 11 sectors, cross-segment ranked (§3); fills inline per L6 |

- **Return-annotation rule:** bare `OBBject` (no parametrized model) so `package_builder.
  build_func_returns` renders an importable annotation — the established `techtrade_router` /
  `screener_router` / `plan_router` pattern; `list[TradePlan]` is documented in the docstring and
  round-trips through Python / REST / CLI / MCP (§9).
- **`metric` vs rank key:** `metric` chooses *which movers per sector* enter the chain; the
  cross-segment **plan** order is `|score|` (§3). The docstring states both explicitly (Q-A).
- **Offline seams (Q-C):** `scan_segments` forwards the injectable `candidate_fetcher` /
  `ohlcv_fetcher` / `bars=` seams the chain already exposes, so the integration test runs hermetic.

---

## 5. Determinism & testing

**Determinism (L5, Q-D)** — `scan` is deterministic for a fixed as-of because every input is pinned:

| Source of variance | Pinned by |
|---|---|
| "today" / weekend / half-day | `movers.resolve_session(as_of, "XNYS")` snapped **once**, threaded down |
| sector iteration order | `GICS_SECTOR_ETFS` insertion order (L1) |
| per-segment mover order | existing `rank_movers` `(-metric, symbol)` tie-break |
| cross-segment plan order | §3 total-order key `(-|score|, symbol, segment)` |
| signal/level/order/fill math | upstream engines (already golden-locked by #74–#78) |
| float noise on equal scores | `round(|score|, 9)` (= `testing.DEFAULT_TOL`) |

**Integration test — `tests/integration/test_scan.py`** (the acceptance test):

```python
# small OFFLINE multi-sector universe via injected seams (no API key, no network):
#   ≥3 GICS sectors, a few symbols each, seeded OHLCV -> deterministic scores.
@pytest.mark.integration
def test_scan_ranks_across_sectors_deterministically(scan_fixture):
    plans = scan_segments(metric="pct_change", top_n=5, as_of="2026-06-12",
                          candidate_fetcher=scan_fixture.movers,
                          bars=scan_fixture.bars)
    # (a) cross-segment: plans span >1 sector
    assert len({p.segment for p in plans}) > 1
    # (b) ranked: |score| is non-increasing down the list
    keys = [(-abs(p.signal.score), p.symbol, p.segment) for p in plans]
    assert keys == sorted(keys)
    # (c) deterministic: a second identical call is byte-identical
    again = scan_segments(metric="pct_change", top_n=5, as_of="2026-06-12",
                          candidate_fetcher=scan_fixture.movers, bars=scan_fixture.bars)
    assert to_jsonable(plans) == to_jsonable(again)
    # (d) fills present (L6) and look-ahead-free (each fill timestamp > as_of)
    assert all(f.timestamp.date() > date(2026, 6, 12)
               for p in plans for f in p.simulated_fills)
```

- Carries the `integration` marker but is **offline by construction** (seeded fixture through the
  `candidate_fetcher` / `bars=` seams), so it runs in CI without `fmp_cached` — the determinism
  assertion (c) is the heart of the acceptance.
- A live smoke variant (real `fmp_cached`, `@pytest.mark.integration`, network) may assert
  *shape* only (returns `list[TradePlan]`, spans ≤11 sectors, non-increasing `|score|`) — never
  exact values (live movers drift).

**Unit test — `tests/unit/test_scan.py`** (fan-out + sort, no chain):

| Assertion | Locks |
|---|---|
| `_rank_key` orders hand-built `TradePlan`s by `-|score|` then `symbol` then `segment` | §3 total order |
| equal `|score|` (long vs short, e.g. +0.4 / −0.4) → `symbol`/`segment` tie-break decides | Q-A direction-neutral + Q-D |
| sub-threshold / `flat` plans rank last (or filtered) | Q-A |
| `limit=k` slices the first `k` after sort; `top_n` is the per-segment cap (≤ `11×top_n` total) | Q-A(i)/(iii) |
| one sector/symbol fetch raising → that entry skipped, rest returned | Q-E skip-and-continue |
| `scan.py` does not import `indicators` / `rules` / `orders`-math modules (composition only) | §19 / L4 |

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/integration/test_scan.py -m "integration" -v
```

---

## Acceptance mapping (#79)

| Acceptance criterion (issue) | Satisfied by | Open dependency |
|---|---|---|
| `scan(metric=, top_n=, preset=)` chains screener → signals → rules → orders → fills | §2 orchestration chain; §4 command; L4/L6 | Q-B (fan-out shape), Q-C (fills inline) |
| Cross-segment ranking of resulting plans | §3 `_rank_key` `(-|score|, symbol, segment)` | **Q-A** (rank key + `top_n` semantics) |
| Deterministic ordering for a fixed as-of date | §5 determinism table; L5; `resolve_session` snap; total-order tie-break | Q-D (key tuple, ε, calendar) |
| Integration test over a small multi-sector universe | §5 `test_scan.py` (offline seeded fixture, ≥3 sectors) | Q-C C1 (bar seam) |
| `obb.techtrade.scan(...)` returns ranked `TradePlan`s across all 11 sectors | §1 `scan.py` + §4 `plan_router.scan` → `OBBject[list[TradePlan]]`; L1/L7 | — |
| Reuses ~~#6/#11/#13/#14~~ → **#73/#75/#77/#78** (no logic duplication) | header stale-ref correction; §2 reuse map; L4 §19 contract; unit "no chain-math import" test | Q-B (shared builder seam to avoid re-walking #77) |
| Deterministic output | §5 (a)–(c); `to_jsonable` byte-stability | Q-D |

> **Net new dependency surfaced:** B2 throughput (Q-B) wants #77 to expose a reusable
> `build_plans_for_symbols` engine seam so `scan` reuses the per-symbol chain body instead of
> re-walking it (the only way to honour §19 *and* a single spawn pool). Confirm whether that seam
> exists from #77 or is in-scope for this Size-M issue; if not, ship **B1** (loop `plan(segment=…)`)
> for v1 and file the factoring follow-up.
