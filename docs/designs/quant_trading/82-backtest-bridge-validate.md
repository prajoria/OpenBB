# 82 — backtest_bridge + validate + Attach ValidationReport

**GitHub:** [#82](https://github.com/prajoria/OpenBB/issues/82) · **Phase:** P6 · **Sprint:** 6 · **Size:** M
**Depends on:** [#78](https://github.com/prajoria/OpenBB/issues/78) (PaperBroker fills → a TradePlan to validate) · [#64](https://github.com/prajoria/OpenBB/issues/64) (Q1 repo consolidation, **RESOLVED**)
**Source PRD:** [`docs/Specs/TechnicalTrading-Engine-PRD.md`](../../Specs/TechnicalTrading-Engine-PRD.md) §15 (Robustness Validation), §20 Q1 (repo consolidation)
**Scope:** Add `validation/backtest_bridge.py` (translate a `TradePlan` into an
`openbb-backtest` `validate` call) + the `validate` command, attach the returned
`ValidationReport` to `TradePlan.validation`, and degrade gracefully when
`openbb-backtest` is absent.

> **Repo note (Q1 RESOLVED):** code and docs live in the same `OpenBBTechnical` checkout.
> techtrade implementation:
> [`../../../openbb_platform/extensions/techtrade/`](../../../openbb_platform/extensions/techtrade/).
> `openbb-backtest` is **merged in-tree** at
> [`../../../openbb_platform/extensions/backtest/`](../../../openbb_platform/extensions/backtest/)
> (its 431-test suite is green here); techtrade imports `openbb_backtest` as an **installed,
> in-tree editable package** — *never* via a filesystem checkout path. This design doc lives under
> `docs/designs/quant_trading/` (one doc per issue).

---

## What this is

**Robustness validation** asks a blunt, essential question about any trading rule: *is this edge
real, or did it just get lucky / overfit to the past?* A rule can look great on a single backtest
and still be worthless out-of-sample. This step wires techtrade into a dedicated validation engine
(`openbb-backtest`) that stress-tests a strategy across many resampled train/test splits and returns
a one-word **verdict** — `robust`, `fragile`, or `overfit` — backed by statistics like the
**Probability of Backtest Overfitting (PBO)** and the **Deflated Sharpe Ratio (DSR)**.

The clean architectural principle (PRD §15) is a **division of labor**: *techtrade generates,
backtest validates.* techtrade knows how to turn indicators into signals, levels, and orders;
`openbb-backtest` already owns the walk-forward (WFO) and combinatorial purged cross-validation
(CPCV) machinery, the overfit math, and the verdict gate. Neither should re-implement the other.
This issue therefore builds a thin **bridge**: it translates a techtrade `TradePlan` into the
`BacktestConfig` that backtest's `validate` expects, calls it, takes back the `ValidationReport`,
and **attaches that report to `TradePlan.validation`** so every downstream consumer (the
[#80 Recommendation builder](./80-recommendation-builder.md) caveats, the
[#81 Excel Summary](./81-excel-export.md) coverage cell) can read the verdict.

The defining constraint — and the deliberate contrast with [#73](./73-indicator-adapter-selector-parity-bulk.md),
which made its indicator library a *hard* dependency — is that `openbb-backtest` must be an
**optional/soft** dependency. The issue requires *graceful degradation*: if backtest is not
installed, `obb.techtrade.validate` raises one clear, actionable error (with a `pip install` hint),
while **every other** part of `obb.techtrade.*` keeps importing and running untouched. That is why
`TradePlan.validation` is typed `Data | None` and why all `openbb_backtest` imports are lazy and
in-body. The genuinely hard part, surfaced as the central open question below, is the **translation
itself**: backtest's `validate` does not take a returns series or the plan's orders/fills — it
re-runs a *registered strategy* over history, so the confluence rule must be expressed as a
re-runnable, registered strategy rather than injected as a closure.

---

## 0. Key decisions (locked) + Open questions

### Locked (do not re-open)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| L1 | Q1 cross-repo (RESOLVED, #64) | `openbb-backtest` is **in-tree**; `import openbb_backtest` as an installed package | No `quant_repos/` / sibling-checkout path is referenced at runtime |
| L2 | `TradePlan.validation` typing | `Data \| None` (already in `models.py`) — carries an `openbb_backtest.models.ValidationReport` when populated | techtrade stays **installable & importable without** `openbb-backtest` |
| L3 | Verdict vocabulary | `Verdict = Literal["robust", "fragile", "overfit"]` (backtest `models.py`) | Bridge returns the verdict verbatim; no remap |
| L4 | Division of labor (§15) | techtrade **generates**, backtest **validates** — neither re-implements the other | No WFO/CPCV/PBO/DSR math in techtrade; the bridge is pure translation + a call |
| L5 | Verdict gate owner | The gate lives **inside** `openbb_backtest.validation.build_validation_report` (precedence **overfit > robust > fragile**) | techtrade does not recompute the verdict; it reads `report.verdict` |

> The backtest verdict gate's effective thresholds (`openbb_backtest/validation/report.py`):
> `pbo_robust 0.2` · `pbo_overfit 0.5` · `dsr_robust 0.95` · `dsr_overfit 0.5`. Recorded on every
> `ValidationReport.thresholds` so the verdict is auditable.

### Open questions (for review / brainstorm)

**Q-A — Dependency posture: SOFT/optional, not hard (the headline decision).**
#73 made `openbb-technical` a **hard** dependency. **#82 must do the opposite.** The issue
explicitly requires *"graceful degradation if backtest package absent (clear error, core still
works)"* and *"no hard runtime dependency"* — which is incompatible with a hard dep. So the
posture is: **optional dependency, lazy `import openbb_backtest` inside the bridge, clear
actionable error when absent.** Sub-questions to settle:
- Declare an **`[validation]` extra** in techtrade's `pyproject.toml` (`pip install
  openbb-techtrade[validation]` pulls `openbb-backtest`), or leave it **entirely undeclared**
  (pure runtime probe, documented in README #86)? *Recommendation:* declare the extra — it's
  discoverable and still optional.
- **Which error type** on absence? techtrade **cannot** import
  `openbb_backtest.errors.OptionalDependencyError` (that import itself fails when backtest is
  absent). So techtrade needs its **own** error — a small `TechtradeDependencyError(OpenBBError)`
  (subclassing `openbb_core`'s `OpenBBError`, which techtrade already depends on) carrying a
  ready-to-run `pip install` hint. Confirm we add this leaf error.

- **Recommendation:** keep `openbb-backtest` **soft/optional** — declare a discoverable
  `[validation]` extra, lazily `import openbb_backtest` inside bridge function bodies, and raise a
  leaf `TechtradeDependencyError(OpenBBError)` (with a `pip install 'openbb-techtrade[validation]'`
  hint) when it is absent.
- **Answer:** _(pending approval)_

**Q-B — The translation: `TradePlan` → what `validate` actually accepts (the core unknown).**
The **real** entrypoint (grounded below in §3) is
`openbb_backtest.routers.validate_router.validate(config: BacktestConfig, method, …)`. It does
**not** take a returns series, an equity curve, or the plan's orders/fills. It takes a
**`BacktestConfig` naming a *registered* strategy** + universe + a date window, then **re-runs
that strategy over WFO/CPCV folds**. A techtrade `TradePlan` is a single-symbol *forward*
snapshot (signal + rule + orders + fills for one `as_of`). Bridging the two is the central
design problem. Options:

| Option | How the rule becomes a re-runnable strategy | Tradeoff |
|---|---|---|
| **B1 — Proxy an existing registered strategy** | Map plan direction/thresholds onto e.g. `mean_reversion` params | Cheap, zero new code; but a z-score fade is **not** the confluence rule — low fidelity |
| **B2 — Register a `techtrade_confluence` SignalStrategy** that recomputes the confluence signal historically and emits `{-1,0,1}` | Faithful; advertised via the `openbb_backtest_strategies` entry-point group so backtest auto-discovers it **only when both are installed** | Re-runs the signal engine over history → a **look-ahead caveat** (cf. `analysis_bridge`); "who owns the class" question |
| **B3 — Extend `validate` to accept a pre-built strategy/factory** | Pass the techtrade strategy object straight through | Cleanest fidelity, but **changes `openbb-backtest`** (out of #82 scope) |

> **Sharp constraint:** `validate` reconstructs the strategy **from `(name, params)` via the
> registry each fold** (`discovery.resolve`), so the rule must be expressible as a **registered
> name + JSON-serializable params** — an *injected closure* (the `analysis_bridge` →
> `factor_tilt` pattern) does **not** flow through `validate(strategy_params=…)`. This is what
> rules out a pure-injection bridge and pushes toward **B2**. Needs a decision.

Also unresolved under Q-B:
- **Date window:** the plan has one `as_of`; `validate` needs `start`/`end` spanning enough
  sessions to form folds. Derive `start = as_of − N years` (default horizon, e.g. 5y) or take an
  explicit `start`/`end` on the `validate` command?
- **Universe:** `[plan.symbol]` (single-symbol) is fine for a `SignalStrategy`; cross-sectional
  strategies would need a multi-symbol universe (another reason B2 leans `SignalStrategy`).
- **Call path:** import the router function directly
  (`from openbb_backtest.routers.validate_router import validate`) — testable, no `openbb.build()`
  — vs `obb.backtest.validate(...)`. *Recommendation:* direct function import (mirrors #73's
  `technical_adapter` calling router functions directly).

- **Recommendation (Q-B):** choose **B2** — register a faithful `techtrade_confluence`
  `SignalStrategy` (advertised via the `openbb_backtest_strategies` entry-point group so it is
  discovered only when both packages are installed), parameterized by the plan's rule; derive the
  fold window as `start = as_of − 5y`, `end = as_of`; use `universe = [plan.symbol]`; and call
  backtest's `validate` by **direct function import**. Document the historical-recompute look-ahead
  caveat (cf. `analysis_bridge`).
- **Answer:** _(pending approval)_

**Q-C — Method + thresholds flow.**
`validate(plan, method="wfo"|"cpcv")` maps **1:1** onto backtest's `method` (identical
`Literal["wfo","cpcv"]`); default `wfo`. **Thresholds:** pass techtrade's own cut-offs through
`validate(..., thresholds=…)`, or rely on backtest's defaults? *Recommendation:* default to
backtest's defaults (single source of truth, L5), expose an **optional** `thresholds` pass-through
for callers who want to tighten the robust band.

- **Recommendation:** forward `method` unchanged (1:1 `Literal`, default `wfo`); rely on
  **backtest's default thresholds** as the single source of truth (L5), exposing an optional
  `thresholds` pass-through for callers who want a tighter robust band.
- **Answer:** _(pending approval)_

**Q-D — Attaching the verdict + return type.**
Set `plan.validation = report` where `report` **is** a `ValidationReport` (a `Data` subclass,
assignable to the `Data | None` field). **Mutate vs return-new:** prefer
`plan.model_copy(update={"validation": report})` (immutable discipline, mirrors backtest's
`sanitize_result` / `tearsheet` `model_copy`). **Return type:** acceptance says "returns a
`ValidationReport` verdict" **and** "verdict attaches to the plan" — so return
`OBBject[ValidationReport]` and surface the plan-with-verdict either by in-place attach or by
also returning it. Confirm: `OBBject[ValidationReport]` as the return, plan updated via
`model_copy` (caller reads `plan.validation`).

- **Recommendation:** return `OBBject[ValidationReport]` (the verdict) and attach via the immutable
  `plan.model_copy(update={"validation": report})`; since `ValidationReport` is a `Data` subclass it
  satisfies the `Data | None` field without techtrade importing the backtest type at module load.
- **Answer:** _(pending approval)_

**Q-E — The tuning gate is NOT in #82 scope.**
§15's rule — *a `tune` result becomes a default only if the verdict is `robust`* — lives in
**[#83](https://github.com/prajoria/OpenBB/issues/83) (tuneta adapter + tune, gated by
validation)**, which *consumes* the verdict. #82 delivers only the **plumbing** (produce a
verdict, attach it). State this explicitly so reviewers don't expect the gate here.

- **Recommendation:** keep the tuning gate (a `tune` result becoming a default only when the
  verdict is `robust`) **out of #82 scope**; #82 delivers only the plumbing (produce the verdict
  and attach it to `TradePlan.validation`), and [#83](https://github.com/prajoria/OpenBB/issues/83)
  (tuneta adapter + tune, gated by validation) consumes that verdict.
- **Answer:** _(pending approval)_

**Q-F — Import isolation (discipline, enforced by test).**
All `openbb_backtest` imports are **lazy, inside bridge function bodies** — never at module top
level — mirroring the `models.py` `Data | None` rule (L2). This keeps `import openbb_techtrade`
clean without backtest installed, and is enforced by the
[#85](https://github.com/prajoria/OpenBB/issues/85) (core-unchanged-when-removed) discipline:
techtrade's non-validation surface must import and run identically whether or not
`openbb-backtest` is present.

- **Recommendation:** keep **all** `openbb_backtest` imports lazy and in-body (never at module top
  level), enforced by the [#85](https://github.com/prajoria/OpenBB/issues/85)
  (core-unchanged-when-removed) test, so the non-validation surface imports and runs identically
  with or without backtest installed.
- **Answer:** _(pending approval)_

---

## 1. Module layout (new)

```
openbb_platform/extensions/techtrade/openbb_techtrade/validation/
├── __init__.py            # EXISTS (one-line docstring; bridge to openbb-backtest, PRD §15)
├── backtest_bridge.py     # NEW — pure translation: TradePlan -> BacktestConfig (+ method/
│                          #   thresholds) -> lazy call into openbb_backtest.validate ->
│                          #   ValidationReport. ALL openbb_backtest imports are lazy/in-body.
│                          #   Raises TechtradeDependencyError (clear pip-install hint) if absent.
└── validate_router.py     # NEW — the `validate` command (obb.techtrade.validate). Already
                           #   referenced by techtrade_router._include_subrouters (line 42):
                           #   "openbb_techtrade.validation.validate_router".

openbb_platform/extensions/techtrade/tests/
├── unit/
│   └── test_backtest_bridge.py   # NEW (offline) — translation correctness + degradation,
│                                 #   with openbb_backtest faked / forced-absent.
└── integration/
    └── test_validate.py          # NEW — returns a real verdict on a sample plan via the
                                  #   in-tree openbb_backtest; skips cleanly if absent/unreachable.
```

**Module-boundary rules**
- `backtest_bridge.py` is the **only** module that imports `openbb_backtest`, and it does so
  **lazily inside functions** — there is no top-level `import openbb_backtest` anywhere in
  techtrade (L2/Q-F).
- The bridge references the package **`openbb_backtest`** (installed, in-tree) — **never** a
  sibling-checkout path (L1).
- `validate_router.py` depends only on `models`, `backtest_bridge`, and `openbb_core`. No cycles.
- techtrade does **not** add `openbb-backtest` to its base `[tool.poetry.dependencies]`
  (contrast #73's hard dep); it lives in an optional `[validation]` extra at most (Q-A).

---

## 2. Dependency posture & graceful degradation (Q-A)

The contrast with #73 is the whole point of this issue:

| | #73 (`openbb-technical`) | #82 (`openbb-backtest`) |
|---|---|---|
| Dependency kind | **Hard** — base `[tool.poetry.dependencies]` | **Soft/optional** — `[validation]` extra (or undeclared) |
| Import site | top-level OK once installed | **lazy, in-body only** |
| Absent at runtime | install error (acceptable) | **clear actionable error**; *core still works* |
| Enforced by | covered-set parity oracle | #85 core-unchanged-when-removed test |

**Degradation path (lazy import + clear error):**

```python
# backtest_bridge.py  (illustrative — all openbb_backtest imports are in-body)
from __future__ import annotations
from openbb_core.app.model.abstract.error import OpenBBError


class TechtradeDependencyError(OpenBBError):
    """An optional techtrade dependency (openbb-backtest) is not installed."""


def _require_backtest():
    """Lazily import the in-tree openbb-backtest, or raise an actionable error.

    techtrade stays importable/installable without openbb-backtest (TradePlan.validation
    is typed Data|None for exactly this reason); only obb.techtrade.validate needs it.
    """
    try:
        from openbb_backtest.routers.validate_router import validate as _bt_validate
        from openbb_backtest.models import BacktestConfig
    except ImportError as exc:  # backtest extension absent -> degrade, don't crash import
        raise TechtradeDependencyError(
            "obb.techtrade.validate requires the 'openbb-backtest' extension, which is "
            "not installed. Install it with: pip install 'openbb-techtrade[validation]'"
        ) from exc
    return _bt_validate, BacktestConfig
```

> **Why techtrade defines its own error** (not reuse `openbb_backtest.errors.OptionalDependencyError`):
> importing that class is exactly what fails when backtest is absent. The error must come from a
> module techtrade can always import — hence a leaf `TechtradeDependencyError(OpenBBError)`.
> `OpenBBError` is already on techtrade's path (`openbb-core`), so existing
> `except OpenBBError` handlers catch it.

---

## 3. The bridge translation (Q-B — the core integration)

### 3.1 The REAL `validate` signature (grounded in `openbb_backtest/routers/validate_router.py`)

```python
async def validate(
    config: BacktestConfig,                        # strategy NAME + universe + start/end
    method: str = "wfo",                           # "wfo" | "cpcv"
    thresholds: dict[str, float] | None = None,    # pbo_robust / pbo_overfit / dsr_robust / dsr_overfit
    strategy_params: dict[str, Any] | None = None, # kwargs the registry passes to the strategy ctor
    provider: str | None = None,                   # defaults to fmp_cached
) -> OBBject[ValidationReport]
```

Internally it `resolve`s `config.strategy` from the registry, splits `config.start..config.end`
into **walk-forward** or **CPCV** folds, **re-runs the strategy** on each OOS window through the
engine + analytics, computes **PBO / Deflated-Sharpe / MinBTL**, and calls
`build_validation_report` (which derives the verdict). **Crucially: the plan's `orders` /
`simulated_fills` are never read** — validate re-derives everything from history.

`BacktestConfig` requires: `strategy` (registered name), non-empty `universe`, `start`, `end`
(`end > start`); the rest (`engine`, `initial_cash`, `frequency`, `calendar`, costs, `benchmark`,
`seed`) have defaults.

### 3.2 The impedance mismatch the bridge must close

| `TradePlan` carries | `validate` / `BacktestConfig` wants | Bridge must supply |
|---|---|---|
| `symbol` (single) | `universe: list[str]` (non-empty) | `[plan.symbol]` |
| `as_of` (one session) | `start`, `end` (multi-year, ≥ several folds) | a **horizon**: `start = as_of − N years`, `end = as_of` (Q-B) |
| `signal` (`MoverSignal`: direction/score) + `rule` (`EntryExitRule` thresholds) | `strategy`: a **registered name** + serializable `strategy_params`, re-run each fold | a strategy that **reproduces the rule** (B1/B2/B3 — open) |
| `orders`, `simulated_fills` (#78) | *(unused by validate)* | — (a complete plan is needed only as the **attach target** + provenance) |
| — | `provider` | `fmp_cached` (fork default) |
| `method` arg | `method` | pass through (§3.3) |

> **What #78 actually buys us:** a *complete* `TradePlan` object (with fills) to **attach the
> verdict to** and to read `symbol` / `as_of` from — **not** an input to the validation math.
> validate reconstructs returns from history; it does not consume techtrade's paper fills.

### 3.3 Translation sketch (pending the Q-B decision)

```python
def plan_to_config(plan, *, horizon_years: int = 5, BacktestConfig=...):
    """TradePlan -> BacktestConfig (single-symbol, as_of-anchored window).

    The strategy name + params come from the Q-B decision (B2: a registered
    'techtrade_confluence' SignalStrategy parameterized by the plan's rule).
    """
    start = plan.as_of.replace(year=plan.as_of.year - horizon_years)
    return BacktestConfig(
        strategy="techtrade_confluence",          # B2 (open); B1 would proxy mean_reversion/momentum
        universe=[plan.symbol],
        start=start,
        end=plan.as_of,
        # engine/cash/frequency/calendar default; calendar XNYS matches techtrade sessions
    )
```

**Method mapping** is trivial — `"wfo"|"cpcv"` is the *same* `Literal` on both sides; the bridge
forwards it unchanged and lets backtest's router reject anything else (`_check_method`).

---

## 4. The `validate` command (Q-C, Q-D)

```python
# validation/validate_router.py
@router.command(methods=["POST"])
async def validate(
    plan: TradePlan,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    horizon_years: int = 5,
    provider: str | None = None,
) -> OBBject[ValidationReport]:
    """Delegate robustness validation of a TradePlan to openbb-backtest (PRD §15).

    Translates the plan into a BacktestConfig, calls openbb-backtest's validate over
    WFO/CPCV folds, attaches the returned ValidationReport to plan.validation, and
    returns the verdict. Raises TechtradeDependencyError (clear pip-install hint) if
    openbb-backtest is not installed — the rest of obb.techtrade.* is unaffected.
    """
    from openbb_techtrade.validation.backtest_bridge import validate_plan
    report = await validate_plan(
        plan, method=method, thresholds=thresholds,
        horizon_years=horizon_years, provider=provider,
    )
    return OBBject(results=report)
```

Design points:
- **`async def`** — matches backtest's `validate` (long-running per `09-api-surface.md` §2) and
  lets the bridge `await` the backtest coroutine directly (no `asyncio.run` shim in production;
  unit tests drive it with `asyncio.run`, mirroring `test_validate_router.py`).
- **Attach (Q-D):** the bridge does `plan.model_copy(update={"validation": report})`
  (immutable); `report` is a `ValidationReport` (a `Data` subclass) so it satisfies the
  `validation: Data | None` field (L2) **without** techtrade importing the backtest type at
  module load.
- **Return:** `OBBject[ValidationReport]` (the verdict). The updated plan is available via the
  bridge return / `plan.validation`.
- **Auto-wiring:** already handled — `techtrade_router._include_subrouters` includes
  `openbb_techtrade.validation.validate_router` and **skips it cleanly** if the module's imports
  fail, so a missing backtest never breaks `obb.techtrade.*` registration.

---

## 5. Determinism & testing (Q-F, #85)

| Test | Kind | Asserts |
|---|---|---|
| `test_backtest_bridge.py::translation` | unit (offline) | `plan_to_config` builds a valid `BacktestConfig`: `universe == [symbol]`, `end == as_of`, `start == as_of − horizon`, `method` forwarded |
| `test_backtest_bridge.py::degradation` | unit (offline) | with `openbb_backtest` forced un-importable, the bridge raises `TechtradeDependencyError` whose message contains `pip install` — **and** importing every *other* techtrade module still succeeds (core works) |
| `test_backtest_bridge.py::attach` | unit (offline) | given a faked `ValidationReport`, the bridge returns a plan whose `.validation` is that report (verdict ∈ {robust, fragile, overfit}) |
| `test_validate.py` | **integration** | `obb`-level (or direct) `validate` on a **sample plan** returns an `OBBject[ValidationReport]` with a real `verdict`; **skips cleanly** when `openbb-backtest` absent or `fmp_cached` unreachable |

**Degradation test discipline (#85 core-unchanged-when-removed):** the unit suite simulates
"backtest absent" (e.g. monkeypatch the import to raise) and asserts (a) a clear error from
`validate`, and (b) `import openbb_techtrade`, `obb.techtrade.movers/signals/plan/scan/export`
are **untouched**. This is the same removal discipline #85 applies to the agent layer, applied
here to the validation extra.

**Integration skip pattern** mirrors `backtest/tests/integration/test_factor_tilt_bridge.py`:
`pytestmark = [pytest.mark.integration, skipif(not _backtest_available()), skipif(not
_fmp_cached_available())]`, so the default unit run stays hermetic/offline.

> **Determinism:** the bridge itself is pure translation (no RNG); reproducibility of the
> *verdict* is `openbb-backtest`'s responsibility (its `BacktestConfig.seed` + fixed fold split).
> The bridge pins `calendar="XNYS"` (shared with backtest) and a fixed `horizon_years` so the
> derived window is stable for a given `as_of`.

---

## Acceptance mapping (#82)

| Acceptance criterion (issue) | Satisfied by |
|---|---|
| `validation/backtest_bridge.py` hands rules/plan to `openbb-backtest.validate()` | §3 (`plan_to_config` + lazy call into the real `validate`) |
| `validate(plan, method="wfo"\|"cpcv")` → `ValidationReport` | §4 command + §3.3 method pass-through (1:1 `Literal`) |
| Attach verdict to `TradePlan.validation` | §4 / Q-D (`model_copy(update={"validation": report})`; field is `Data \| None`, L2) |
| Graceful degradation if backtest absent (clear error, core still works) | §2 (lazy import + `TechtradeDependencyError` w/ `pip install` hint); §5 degradation test |
| Integration test returns a verdict on a sample plan | §5 `test_validate.py` (integration, skips cleanly) |
| `obb.techtrade.validate(plan)` returns a `ValidationReport` verdict | §4 (`async` command, `OBBject[ValidationReport]`) |
| No hard runtime dependency on sibling-checkout paths | §0 L1 + §1 boundary rules (import the in-tree `openbb_backtest` package; no `quant_repos/` path) |
| Reflects Q1 cross-repo decision (#64) | §0 L1 / repo note (in-tree editable package, not cross-repo) |
| (§15) techtrade generates, backtest validates — neither duplicates | §0 L4 (no WFO/CPCV/PBO/DSR in techtrade; bridge is translation only) |
| (§15) tuning gate (`tune` default only if robust) | **Out of scope** — #83 consumes the verdict (Q-E); #82 is plumbing only |
