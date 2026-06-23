# 75 — `signals` Command + 3 Confluence Presets + Golden-Score Test

**GitHub:** [#75](https://github.com/prajoria/OpenBB/issues/75) · **Phase:** P3 · **Sprint:** 3 · **Size:** M
**Depends on:** [#74](https://github.com/prajoria/OpenBB/issues/74) · design: [`./74-confluence-voting-score.md`](./74-confluence-voting-score.md) (confluence voting engine — score + votes)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §12.3, §9.2, §20 Q4
**Scope:** Wrap the #74 (confluence voting engine) in the `obb.techtrade.signals` command, ship three
named confluence **presets** (`trend_follow` / `mean_revert` / `breakout`) under `strategies/`, populate
`rank_in_segment`, support a custom `weights=` override, and lock a **golden-score** test through the
command.

> **Repo note:** code and docs live in the same `OpenBBTechnical` checkout. Implementation: `../../../openbb_platform/extensions/techtrade/`. This design doc lives under `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

This issue adds the `signals` command and three confluence **presets** to the techtrade extension. `obb.techtrade.signals(...)` runs the confluence voting engine over a set of symbols or a whole market segment and returns ranked `MoverSignal`s — each carrying a symbol, a composite score, a direction (`long`/`short`/`flat`), and per-indicator vote attribution that explains *why* the engine voted the way it did. A **preset** is a named, curated weighting profile — `trend_follow`, `mean_revert`, or `breakout` — that re-tilts the same four indicator families toward a trading style, so the one engine produces different behavior depending on the preset you pick. A caller can also pass custom `weights=` to override a preset's tilt.

Why it lives in this pipeline: the confluence engine from [#74](https://github.com/prajoria/OpenBB/issues/74) ([`./74-confluence-voting-score.md`](./74-confluence-voting-score.md)) is internal math with no user-facing entry point. This step exposes it as a usable `obb.techtrade.*` command — point it at a segment, pick a preset, and get back a ranked, explainable shortlist that feeds the downstream rules, sizing, and order-generation stages. `rank_in_segment` is just that ranking: it sorts the candidate signals by conviction *within* a segment (most-long first), producing a contiguous `1..N` ordering so the strongest ideas float to the top. Read this doc without the PRD: everything needed to understand the command is here.

---

## 0. Key decisions (locked) + Open questions

### 0.1 Locked (do not re-open)

| # | Decision | Choice | Source |
|---|---|---|---|
| L1 | Three named presets exist | `trend_follow` (**default**), `mean_revert`, `breakout` — each reweights the **same** four families | PRD §12.3 |
| L2 | Command output contract | `results` is a **`list[MoverSignal]`** (the `OBBject[list[MoverSignal]]` contract); annotation rendered **bare `OBBject`** per the package-builder constraint (see §2) | PRD §9.2; `techtrade_router` |
| L3 | Base weights | **Q4 RESOLVED:** trend `0.40` / momentum `0.25` / volatility `0.20` / volume `0.15` (volume = **confirmation multiplier**, not an additive vote). Presets *tilt* from this base. | PRD §20 Q4, §12.2 |
| L4 | Router attach point | `signals` ships in `engine/signals_router.py`; it auto-wires via the **existing** lazy entry in `techtrade_router._include_subrouters` (`openbb_techtrade.engine.signals_router`) | [`techtrade_router.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/techtrade_router.py) |
| L5 | `trend_follow` weighting | The default preset **is** the L3 base (trend-heavy by construction) | PRD §12.3 row 1 |

> Q4 (default weights) is **RESOLVED** and out of scope here. This issue decides only *how presets
> tilt away from* the base and *how the command resolves a universe, ranks, and overrides weights*.

### 0.2 Open questions (brainstorm before build)

| # | Question | Options | Working lean |
|---|---|---|---|
| Q-A | Preset **file format** | (a) Python modules exposing a `ConfluenceConfig`/weights object · (b) YAML/JSON data files loaded at import | **(a) Python** — type-safe, importable without a loader, mirrors #74's config object. **ASK.** |
| Q-B | Exact per-preset **reweighting** | §12.3 gives only a qualitative tilt; the numeric weights + extra knobs (ADX gate, vol regime) are undefined | Candidate table in §3 — **PROPOSED, brainstorm.** |
| Q-C | `symbols=` vs `segment=` **universe resolution** + `rank_in_segment` | (a) `segment` ⇒ internally call movers/screener (#70) · (b) accept an explicit `MoverList`; rank by **signed score** vs **`|score|`** | **(a)** resolve via movers; rank signed-score desc. **ASK on `|score|`.** |
| Q-D | Custom `weights=` **override shape** | dict `{family: weight}`; **merge** over preset vs **replace**; validation (renormalize? sum-to-1? volume excluded as multiplier) | dict, **merge**, additive-trio validated, volume validated separately. **ASK.** |
| Q-E | Provider / **fetch seam** | reuse #72 injectable `ohlcv_fetcher` + #73 `build_panels_bulk` for the panel stage | **Yes** — forward an `ohlcv_fetcher` seam into the #73 bulk path. **Confirm.** |

#### Q-A — Preset file format

Should presets ship as Python modules exposing a config object, or as YAML/JSON data files loaded at import?

- **Recommendation:** Ship each preset as a Python module exposing a `ConfluenceConfig`/weights object — type-safe, importable without a loader, and mirroring #74's config object (no YAML/JSON data-file path).
- **Answer:** Follow recommendation. Python modules are clearly the right choice here for several reasons:

  1. **Type safety at import time.** A preset module exports a `ConfluenceConfig` object — any typo
     in a field name or wrong type is caught by the IDE and type-checker before the code runs. A
     YAML/JSON file would need a runtime loader, a schema validator, and error handling for malformed
     files — all unnecessary complexity for 3 static presets.

  2. **Consistency with #74.** `ConfluenceConfig` is already a frozen dataclass. Presets being Python
     objects that instantiate that same class means the registry (`PRESETS` dict) is just
     `{"trend_follow": trend_follow.CONFIG, ...}` — no deserialization step, no schema drift.

  3. **No loader dependency.** YAML requires `pyyaml`; JSON requires parsing + validation. Python
     modules are free — they're just imports. For 3 presets that change rarely, a data-file approach
     adds a dependency and a failure mode with zero benefit.

  4. **Testability.** Golden tests can import the preset directly and assert on its fields. No
     fixture-file management, no path resolution.

  YAML/JSON would only make sense if presets were user-authored, numerous, or loaded dynamically at
  runtime (e.g., a plugin system). None of those apply here.

#### Q-B — Exact per-preset reweighting

§12.3 specifies only a qualitative tilt; the numeric per-family weights and extra knobs (ADX gate, vol regime) are undefined.

- **Recommendation:** Adopt the §3.1 candidate weight tilts as the starting point (`trend_follow` pinned to the L3 base; `mean_revert` and `breakout` tilting from it), pending brainstorm on the normalization / regime-flip / strict-ADX sub-points.
- **Answer:** Follow recommendation with notes on the three sub-points:

  1. **Normalization (preserve 0.85 sum):** Presets should preserve the `0.85` additive ceiling from
     the base weights. This was a deliberate Q-B decision in #74 — volume confirmation is needed for
     High conviction. If `mean_revert` renormalized to `1.0`, its scores would be systematically
     higher than `trend_follow` scores, breaking cross-preset comparability. Keep the sum at `0.85`
     across all presets so `score` means the same thing regardless of which preset produced it.

  2. **Regime flip (`mean_revert` volatility vote):** The `mean_revert` preset needs more than just
     a weight bump on volatility — it needs the %B vote to flip sign (price at upper band = bearish
     mean-revert signal, not bullish breakout). This is correctly identified as a **behavioural knob
     on #74's config** (`regime_threshold` / regime mode), not a weight. The preset module should set
     this knob explicitly, e.g. a `vol_regime="range"` or equivalent `ConfluenceConfig` field. Without
     this, `mean_revert` would just be `trend_follow` with different weights — same directional
     interpretation, which defeats the purpose.

  3. **Strict ADX (`breakout` gate at 30):** Sound. Raising the ADX gate from 20→30 means the
     `breakout` preset only trusts MACD when there's a strong directional trend, filtering out
     choppy/sideways breakout fakes. This is a threshold change on `ConfluenceConfig.adx_gate`,
     cleanly separate from weight tilts. The proposed §3.1 candidate table is a reasonable starting
     point — ship it un-tuned and let a future `openbb-backtest` study validate.

#### Q-C — Universe resolution + `rank_in_segment`

How does the command turn `symbols=` vs `segment=` into a ranked universe, and does ranking use signed `score` or `|score|`?

- **Recommendation:** Resolve a `segment` internally via movers/screener (#70) and rank by signed `score` descending (most-long first); surface the `|score|` conviction-ranking alternative for brainstorm before locking.
- **Answer:** Follow recommendation — use **signed score descending** as the default ranking.

  1. **Signed score is the right default.** The primary use case is "show me the strongest buy
     setups in this sector." A signed-score ranking puts the most-bullish signals at rank 1, which
     is what a long-biased trader expects. It's also what the downstream stages consume — entry/exit
     rules (#76) and order generation (#77) act on directional signals, not on conviction magnitude.

  2. **`|score|` ranking mixes longs and shorts unhelpfully.** If rank 1 is a strong short (-0.9)
     and rank 2 is a strong long (+0.85), the ranking says "these are both high conviction" but
     gives no directional coherence. A user scanning the top-5 would see an interleaved mix of
     buy/sell signals — confusing for the common case.

  3. **`|score|` is trivially derivable.** Any consumer that wants conviction-ranked output can
     `sorted(signals, key=lambda s: abs(s.score), reverse=True)` in one line. There's no need to
     bake it into the command when the signed ranking is more useful by default.

  4. **Segment resolution via movers (#70):** Correct. Reusing the existing movers/screener
     pipeline means the `segment=` path doesn't reinvent universe construction. The symbols list
     flows naturally into `build_panels_bulk` → `score_panel` → rank.

#### Q-D — Custom `weights=` override shape

What shape does the override take, and how is it validated — merge over the preset or replace it, renormalize or require an exact sum?

- **Recommendation:** Accept a dict `{family: weight}` that **merges** over the selected preset (partial override); validate the additive trio together and validate `volume` separately as a multiplier; leave renormalize-vs-require-exact-sum as the open part.
- **Answer:** Follow recommendation with a resolution on the open renormalization sub-point:

  1. **Merge over preset (not replace):** Correct. A partial override like `weights={"trend": 0.5}`
     should change only trend and leave momentum/volatility/volume at the preset's values. Full
     replacement would force the user to specify all four families every time — tedious and
     error-prone. Merge is the expected UX for an override.

  2. **Validate additive trio and volume separately:** Correct. Volume is a multiplier strength
     `k ∈ [0, 1]`, not an additive weight — it has different semantics and bounds. Lumping it into
     an additive-sum check would be a type error. Validate: each additive weight `≥ 0`, volume
     `∈ [0, 1]`, unknown keys → `ValueError`.

  3. **Renormalize vs require exact sum — resolve: require exact sum (0.85).** Renormalization is
     dangerous because it silently changes the user's intent. If someone passes
     `{"trend": 0.6, "momentum": 0.4}` (sum = 1.0 with volatility 0.20 from preset), renormalizing
     would scale all three weights down — the user typed `0.6` but gets `0.50`. That's surprising.
     Instead: after merging, check that `w_trend + w_momentum + w_volatility == 0.85` (within
     floating-point tolerance). If not, raise a `ValueError` with the actual sum and a hint. This
     is explicit, predictable, and prevents accidental score-scale changes. Advanced users who want
     a different ceiling can pass all three additive weights intentionally.

#### Q-E — Provider / fetch seam

Should the panel stage reuse the #72 injectable `ohlcv_fetcher` plus #73 `build_panels_bulk`?

- **Recommendation:** Yes — reuse the #72 injectable `ohlcv_fetcher` and forward it as a seam into the #73 `build_panels_bulk` panel stage, keeping `compute_signals` fully offline-testable.
- **Answer:** Follow recommendation. This is the obvious right answer:

  1. **Reuse, don't reinvent.** #72 already solved the "how do I get OHLCV data" problem with an
     injectable fetcher interface. #73 already solved "how do I build indicator panels in bulk."
     The signals command's job is orchestration — it should compose these existing pieces, not
     build its own fetch/panel pipeline.

  2. **Offline testability is the key property.** By forwarding the `ohlcv_fetcher` seam,
     `compute_signals` can be tested with a fake fetcher returning seeded fixture data. The
     golden-score test (§5.1) depends on this — without the seam, every test would hit the
     network and scores would vary with live data. The seam is what makes deterministic golden
     locks possible.

  3. **Consistent with the module-boundary discipline.** The doc's own §1 boundary rules state
     `signals.py` imports `engine.bulk` (#73). This answer just confirms that the existing
     `ohlcv_fetcher` parameter is threaded through rather than dropped. No new interface needed.

---

## 1. Module layout (new + changed)

```
openbb_platform/extensions/techtrade/openbb_techtrade/
├── engine/
│   ├── signals.py            # NEW — pure orchestrator (no router import):
│   │                         #   compute_signals(symbols|segment, preset, weights, as_of, top_n,
│   │                         #   *, ohlcv_fetcher=None) -> list[MoverSignal]. Chains
│   │                         #   movers(#70) -> build_panels_bulk(#73) -> confluence(#74) -> rank.
│   └── signals_router.py     # NEW — thin GET command `signals`; bare OBBject; lazy imports.
│                             #   Auto-wired by _include_subrouters (already references this path).
├── strategies/
│   ├── __init__.py           # CHANGED — preset registry: PRESETS, get_preset(name),
│   │                         #   resolve_config(preset, weights). Single source of preset->weights.
│   ├── trend_follow.py       # NEW — default preset == L3 base weights (trend-heavy).
│   ├── mean_revert.py        # NEW — momentum + band-touch; trend damped       (PROPOSED, §3).
│   └── breakout.py           # NEW — volatility + volume; strict ADX gate      (PROPOSED, §3).

openbb_platform/extensions/techtrade/tests/
├── unit/
│   └── test_signals.py       # NEW — offline: preset selection, weights merge/override, rank
│                             #   contiguity, distinct-preset behaviour, output type.
└── golden/
    ├── test_signals_golden.py            # NEW — golden-score lock THROUGH the signals() command
    │                                     #   (offline fetcher seam); carries the `golden` marker.
    └── fixtures/
        ├── signals_trend_follow.json     # NEW — locked MoverSignal payload per preset.
        ├── signals_mean_revert.json
        └── signals_breakout.json
```

**Module-boundary rules**
- `signals_router.py` is **thin** — it only maps command args → `engine.signals.compute_signals` and
  wraps the result in `OBBject`, exactly mirroring `screener_router` → `movers`/`screener`. It never
  computes scores or weights, so the static package builder stays happy and the engine stays
  unit-testable without `openbb.build()`.
- `engine/signals.py` is the **only** orchestrator. It imports `models`, `engine.movers` (#70),
  `engine.bulk` (#73 `build_panels_bulk`), `engine.confluence` (#74), and `strategies`. No router
  import → fully offline-testable through the injected `ohlcv_fetcher` seam (Q-E).
- `strategies/*` are **data-only** preset definitions (no compute). They parameterize #74's config
  object. The preset→weights mapping lives **only** here (the #73 "single source of truth" discipline,
  applied to weights instead of indicator sources).
- The `weights=` override is resolved in **one** function (`strategies.resolve_config`) — not scattered
  across the router and the engine.

---

## 2. Command surface (`signals`)

PRD §9.2: `obb.techtrade.signals(symbols|segment, preset=..., weights=...)` → `list[MoverSignal]`.

```python
# engine/signals_router.py  (thin; mirrors engine/screener_router.py)
@router.command(methods=["GET"])
def signals(
    symbols: list[str] | None = None,
    segment: str | None = None,
    preset: str = "trend_follow",          # L1/L5 default
    weights: dict[str, float] | None = None,  # Q-D custom override
    as_of: str | None = None,
    top_n: int = 10,
    calendar: str = "XNYS",
) -> OBBject:
    """Compute ranked confluence signals for a symbol set or a GICS segment.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[MoverSignal], ranked within the segment.
    """
    from openbb_techtrade.engine.signals import compute_signals

    return OBBject(
        results=compute_signals(
            symbols=symbols, segment=segment, preset=preset,
            weights=weights, as_of=as_of, top_n=top_n, calendar=calendar,
        )
    )
```

> **Return-annotation note (L2).** `about`/`segments`/`movers` all return a **bare** `OBBject` so the
> static package builder renders an importable annotation (`techtrade_router` docstring +
> `package_builder.build_func_returns`). `signals` follows the same convention: the **contract** is
> `OBBject[list[MoverSignal]]` (its `results` *is* a `list[MoverSignal]`, satisfying acceptance), while
> the rendered annotation stays bare `OBBject`. The conceptual `list[MoverSignal]` payload is documented
> in the docstring, mirroring how `movers` documents `list[MoverList]`.

**Chain** (`engine/signals.py`, pure):

```
compute_signals(symbols|segment, preset, weights, as_of, top_n, *, ohlcv_fetcher=None):
    cfg      = strategies.resolve_config(preset, weights)             # §3  (preset tilt + override)
    movers   = _resolve_universe(symbols|segment, as_of, top_n)       # §0 Q-C  -> ranked symbols
    panels   = build_panels_bulk(symbols=movers.symbols, as_of=...,   # #73 bulk panel stage (Q-E)
                                 ohlcv_fetcher=ohlcv_fetcher)         #     -> dict[str, IndicatorPanel]
    scored   = [confluence.score_panel(panels[s], cfg) for s in ...]  # #74 -> (score, direction, votes)
    return _rank_in_segment(scored, segment_label, as_of)             # §4  -> list[MoverSignal]
```

> `confluence.score_panel` is the #74 (confluence voting engine) entry point that turns one
> `IndicatorPanel` + a config into `score` / `direction` / `votes`; its exact name is owned by #74 and
> referenced here as a seam.

---

## 3. Presets (`strategies/`)

PRD §12.3 — three named presets reweight the **same** four families:

| Preset | Tilt (§12.3) | Typical use |
|---|---|---|
| `trend_follow` (default) | trend-heavy; breakout volatility | momentum movers |
| `mean_revert` | momentum + band-touch; trend damped | overextended movers |
| `breakout` | volatility + volume; ADX gate strict | gap / high-rel-volume movers |

### 3.1 PROPOSED weight tilts — **brainstorm (Q-B)**

§12.3 only states the tilt qualitatively; the numbers below are a **candidate** starting point, not
decided. `trend_follow` is pinned to the L3 base; the other two tilt from it.

| Family | `trend_follow` (= L3 base) | `mean_revert` (PROPOSED) | `breakout` (PROPOSED) |
|---|---|---|---|
| trend (additive) | **0.40** | 0.20 | 0.25 |
| momentum (additive) | **0.25** | 0.40 | 0.15 |
| volatility (additive) | **0.20** | 0.25 | 0.40 |
| volume (**multiplier**) | **0.15** | 0.15 | 0.20 |
| extra knob | `adx_gate=20` (std §12.1) | `vol_regime=range` → band-touch = mean-revert vote | `adx_gate=30` (strict); below gate ⇒ trend vote damped → 0 |

> **Open sub-points inside Q-B:**
> - **Normalization:** the additive trio (trend/momentum/volatility) sums to `0.85` in the base. Do
>   presets **preserve that sum** (comparable raw magnitudes) or **renormalize to 1.0**? Ties to Q-D.
> - **Regime flip:** `mean_revert` likely needs the §12.1 *regime-aware* volatility vote flipped to
>   range-mode (price at band ⇒ mean-revert), not just a weight bump — a behavioural knob owned by #74.
> - **Strict ADX:** `breakout`'s "ADX gate strict" is a **threshold** change (20→30), distinct from a
>   weight; it lives on #74's config, set by the preset.

### 3.2 Selection + override mechanics (Q-A, Q-D)

```python
# strategies/__init__.py  (registry — single source of preset -> config)
PRESETS: dict[str, ConfluenceConfig] = {        # ConfluenceConfig owned by #74
    "trend_follow": trend_follow.CONFIG,
    "mean_revert":  mean_revert.CONFIG,
    "breakout":     breakout.CONFIG,
}

def get_preset(name: str) -> ConfluenceConfig:
    """Look up a preset by name; raise ValueError listing valid names if unknown."""

def resolve_config(preset: str, weights: dict[str, float] | None) -> ConfluenceConfig:
    """Start from the named preset, then MERGE a partial {family: weight} override."""
```

- **By name:** `preset="mean_revert"` selects `PRESETS["mean_revert"]`; unknown name → `ValueError`
  listing the three valid keys (mirrors `movers`' unknown-segment guard).
- **Override (Q-D — PROPOSED):** `weights={"trend": 0.1, "momentum": 0.5}` **merges** over the selected
  preset (partial override; unset families keep the preset value). **Validation (open):** additive
  families ≥ 0; `volume` validated **separately** as a multiplier strength in `[0, 1]` (it is *not*
  additive, so it is excluded from any additive-sum rule); renormalize-vs-require-exact-sum is the open
  part of Q-D. Unknown family keys → `ValueError`.

---

## 4. Ranking & attribution

`MoverSignal` fields populated per symbol ([`models.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/models.py)): `symbol`, `segment`, `as_of`, `score`,
`direction` (`long`/`short`/`flat`), `votes: list[IndicatorVote]`, `rank_in_segment`.

- **`rank_in_segment` (Q-C):** one-based dense rank, sorting the segment's signals by **signed `score`
  descending** (most-long first), deterministic tie-break by `symbol` ascending. The result is a
  contiguous `1..N` over the segment.
  > **Open (Q-C):** signed `score` (directional ranking) vs `|score|` (conviction ranking, mixing
  > longs/shorts). Lean signed-score; surface for brainstorm.
- **`votes` carried through:** the per-indicator `IndicatorVote` list from #74 is attached **unchanged**
  so the engine answers *"why long?"* (PRD §12.2 transparency). Each vote carries `family`, `name`,
  `vote ∈ [-1,+1]`, and the preset-resolved `weight` — so the **weight tilt itself is visible** in the
  attribution.
- **Distinct preset behaviour (acceptance):** because each preset feeds different family `weight`s into
  the same panel, the same symbol yields a **different `score`** (and possibly `direction` /
  `rank_in_segment`) per preset — directly observable in `votes[*].weight` and asserted in §5.

---

## 5. Determinism & testing

### 5.1 Golden-score test through the command (the #75 deliverable)

`tests/golden/test_signals_golden.py` exercises the **full** `signals()` chain end-to-end yet stays
**offline + deterministic** by injecting the #72/#73 `ohlcv_fetcher` seam over seeded fixture OHLCV at a
fixed `as_of`. It uses the [`testing.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/testing.py) harness (`assert_matches_golden`, `to_jsonable`) and carries the
`golden` marker registered in `conftest.py`.

> **"Integration through the command", offline.** The issue calls this a *golden-score integration test
> through the command*: "integration" = the whole movers→panels→confluence→rank stack wired together
> (not a live-API test). Keeping it offline via the seam makes the score reproducible, so it lives in
> `tests/golden/` beside #72/#73's golden locks. An optional live-API smoke (`integration` marker,
> `fmp_cached`) under `tests/integration/` can follow but is **not** the determinism anchor.

```python
pytestmark = pytest.mark.golden
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_AS_OF = date(2024, 1, 12)            # fixed session; no look-ahead

def _run(preset: str):
    obb_result = signals(symbols=_FIXTURE_SYMBOLS, preset=preset,
                         as_of=_AS_OF.isoformat(), ohlcv_fetcher=_FAKE_FETCHER)
    return obb_result.results          # list[MoverSignal]
```

### 5.2 Assertions

| Assertion | Guards (acceptance) |
|---|---|
| `isinstance(result, OBBject)` and every `results` item is a `MoverSignal` | output is `OBBject[list[MoverSignal]]` |
| `assert_matches_golden("signals_<preset>", _run(preset), fixture_dir=_FIXTURE_DIR)` for all 3 presets | golden-score reproducibility (PRD §18 P3: "`signals` reproduces a golden score") |
| `{s.score for trend_follow} ≠ {mean_revert} ≠ {breakout}` (pairwise-distinct on a shared symbol) | "all 3 presets selectable and produce **distinct** behaviour" |
| `[s.rank_in_segment] == list(range(1, n+1))` sorted by signed score desc | `rank_in_segment` populated + contiguous |
| `weights={...}` merges over preset and changes `votes[*].weight` + `score` | custom weight override supported |

### 5.3 Determinism legs

- Fixed `as_of` (snapped offline via `resolve_session`), seeded fixture OHLCV, injected `ohlcv_fetcher`
  (no network), commit-pinned `pandas-ta-classic` submodule, and the deterministic #74 scorer.
- Presets are **pure data** (Q-A lean (a)): no I/O, no clock, no RNG — so a preset's golden is stable
  across machines.
- Regenerate goldens only intentionally after a *reviewed* change: `TECHTRADE_REGEN_GOLDEN=1`.

Run:
```powershell
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -m "not integration" -v
```

---

## Acceptance mapping (#75)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| `signals(symbols\|segment, preset=..., weights=...)` → `list[MoverSignal]` | §2 (`signals_router` + `engine.signals.compute_signals` chain) |
| 3 presets under `strategies/`: trend / mean-reversion / breakout | §1 (`strategies/{trend_follow,mean_revert,breakout}.py`), §3 (registry + tilts) |
| `rank_in_segment` populated | §4 (signed-score desc, contiguous `1..N`) |
| Custom weight override supported | §3.2 (`resolve_config`, merge semantics — Q-D) |
| `obb.techtrade.signals(segment=...)` returns ranked MoverSignals with attribution | §2 chain (movers→panels→confluence→rank) + §4 (`votes` carried through) |
| All 3 presets selectable and produce **distinct** behaviour | §3 (per-preset weights) + §5.2 (pairwise-distinct-score assertion) |
| Output is `OBBject[list[MoverSignal]]` | §2 (L2 contract) + §5.2 (type assertion) |
| Golden-score integration test through the command | §5.1 (`test_signals_golden.py`, offline seam, `golden` marker, [`testing.py`](../../../openbb_platform/extensions/techtrade/openbb_techtrade/testing.py) harness) |
| (Depends on #74) wraps confluence score + votes | §2 (`confluence.score_panel` seam), §4 (`votes` passthrough) |
| (PRD §20 Q4) base weights honoured, not re-opened | §0 L3 (presets tilt from the Q4 base; `trend_follow` == base) |
