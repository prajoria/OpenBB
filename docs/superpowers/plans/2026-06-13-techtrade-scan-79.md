# #79 — scan Command: All Sectors → Cross-Segment Ranked TradePlans (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `obb.techtrade.scan(...)` — the one-call orchestrator that screens all 11 GICS sectors, runs each sector's top movers through the existing signals→rules→orders→fills chain, and returns a **cross-segment ranked** `list[TradePlan]`.

**Architecture:** `scan` is pure **composition over existing engines** (design §19 / L4): it owns ONLY the fan-out across sectors (left edge) and the final cross-segment rank (right edge). Every stage in between is an already-built engine call. Because `engine/plan.py` exposes **no** `build_plans_for_symbols` seam (confirmed by reading the module), the approved **B1 fallback** (design §0.2 Q-B answer) applies: `scan_segments` loops `build_plans(symbols=…, segment=…)` per `MoverList` (the literal "loop `plan(segment=s)` ×11" shape), concatenates, simulates fills per symbol when forward bars are supplied, filters non-actionable plans, then sorts by a total-order key `(-round(abs(score), 9), symbol, segment)`.

**Tech Stack:** Python 3.10+, pydantic `Data` models, pytest (unit + integration + `golden`-style determinism), ruff (line-length 122). Test interpreter: `I:\masterswork\git\OpenBBTechnical\.venv_win\Scripts\python.exe`. Run techtrade tests from repo root `I:\masterswork\git\OpenBBTechnical`.

---

## Grounding facts (verified this session — do not re-derive)

- **HEAD:** `de29f94fe` (#78). Only 3 dirty files in the tree, all **noise — leave UNSTAGED**:
  `openbb_platform/core/openbb/assets/reference.json`,
  `openbb_platform/core/openbb/package/__init__.py`,
  `openbb_platform/extensions/agents/tests/test_config.py`.
- **Naming (locked):** pure fn `scan_segments` (design §4 disambiguates it from the command); command `scan`; pure module `engine/scan.py`; tests `tests/unit/test_scan.py` + `tests/integration/test_scan_integration.py` (contract manifest line 246 wins over design's `test_scan.py`).
- **Router auto-wiring:** `techtrade_router._include_subrouters` already lists `("openbb_techtrade.engine.plan_router", "router")`. Appending `scan` to `plan_router.py` needs **zero** `techtrade_router` edits.
- **`plan_router.py` has NO `from __future__ import annotations`** (it has `orders(plan: TradePlan)`). Do **not** add it. The new `scan` command uses only builtin/None-able annotations, so this is fine.
- **Engine signatures (verified):**
  - `movers.resolve_session(as_of: date | str | None = None, calendar: str = "XNYS") -> date` (idempotent).
  - `movers.list_movers(segment=None, *, metric="pct_change", top_n=10, as_of=None, calendar="XNYS", universe_source="etf_holdings", candidate_fetcher=None, holdings_fetcher=None, screener_fetcher=None, constituents_map=None, resolve_universe_filter=True) -> list[MoverList]`. `segment=None` ranks all 11 in canonical `GICS_SECTOR_ETFS` order. When `candidate_fetcher` is injected, universe filtering is skipped (hermetic). The candidate fetcher is invoked **segment-blind** as `fetcher(as_of=session, calendar=calendar, needs_ohlcv=…)`.
  - `plan.build_plans(symbols=None, segment=None, *, preset="trend_follow", risk=0.01, as_of=None, signal_fetcher=None, level_fetcher=None) -> list[TradePlan]`. Passing **both** `symbols` and `segment` scores the explicit symbols and stamps the segment label (verified via `signals._resolve_universe`). Flat/sub-threshold signals yield a plan with `orders == []`, `position_size == Decimal(0)`, `recommendation.action == "HOLD/FLAT"`.
  - `execution.broker.simulate(orders: list[Order], bars: list, *, broker: BrokerInterface | None = None) -> list[Fill]`. `broker=None` builds a default `PaperBroker`. Empty orders/bars → `[]`. `bars[0]` is session *t+1*.
- **Models:** `TradePlan(symbol, segment, as_of, signal: MoverSignal, rule, position_size, orders=[], simulated_fills=[], recommendation, validation=None)`. `MoverSignal.score: float ∈ [-1,+1]`. Populate fills with `plan.model_copy(update={"simulated_fills": fills})`.
- **Determinism ε:** `round(abs(score), 9)` matches `testing.DEFAULT_TOL = 1e-9`.
- **§19 composition guard:** `scan.py` may import `movers`, `plan`, `execution.broker`, `models` only. It must **NOT** import `indicators`, `indicators_technical`, `confluence`, `rules`, or `orders` (those are the chain-math modules `scan` composes, never re-implements).
- **`bars` seam decision (v1):** `scan_segments` accepts `bars: dict[str, list] | None = None` — a per-symbol map of the forward (*t+1…*) OHLCV window. When `simulate=True` and `bars` carries a window for a plan's symbol, run `simulate(plan.orders, window, broker=broker)` and attach. #78 exposes **no** live forward-bar fetcher, so on the live path (no `bars` injected) `simulated_fills` stays `[]` — the order skeleton is still returned and ranked correctly (ranking is pre-fill per design Q-C C3). This is a documented v1 boundary; a live forward-bar fetcher is a follow-up.
- **Isolation granularity (B1):** segment-level skip-and-continue around each `build_plans` call (one of 11 sectors failing drops that sector, keeps the rest) + per-symbol skip-and-continue around each `simulate`. Finer per-symbol *build* isolation is a B2 follow-up (the shared-builder seam). Both emit `warnings.warn(...)` so `command_runner` surfaces them in `OBBject.warnings` (design Q-E).
- **Command surface (design §4 — a strict superset of the contract sketch):** `scan(metric="pct_change", top_n=10, preset="trend_follow", risk: float | None = None, as_of=None, simulate=True, limit=None)`. The contract's 4-param sketch (`metric, top_n, preset, as_of`) is satisfied as a subset; `risk`/`simulate`/`limit` are the reviewed Q-A/Q-C additions, all optional with defaults.

---

## File Structure

| File | Responsibility |
|---|---|
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py` | **NEW.** `scan_segments(...)` orchestrator + `_rank_key` (the only new ordering logic) + `_with_fills` helper. Composition only. |
| `openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py` | **MODIFY.** Append the thin `scan` command beside `plan` / `orders` / `simulate`. |
| `openbb_platform/extensions/techtrade/tests/unit/test_scan.py` | **NEW.** Offline unit tests: `_rank_key` total order, equal-`|score|` tie-break, flat filtered, fan-out across sectors, `limit` slice / `top_n` cap, skip-and-continue, simulate-attaches-fills, pre-fill rank independence, §19 composition guard. |
| `openbb_platform/extensions/techtrade/tests/integration/test_scan_integration.py` | **NEW.** Offline-seeded deterministic acceptance test (all seams injected) + an optional live smoke that skips cleanly. |

---

### Task 1: `_rank_key` + sort/filter core (the only new ordering logic)

**Files:**
- Create: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scan.py`

- [ ] **Step 1: Write the failing test** — `tests/unit/test_scan.py` (header + `_rank_key` tests).

```python
"""Unit tests for the #79 scan orchestrator (PRD §9.2, design §3/§5, contract §#79).

Fully offline and deterministic. ``scan_segments`` is pure COMPOSITION over the existing
movers (#70) -> signals/levels/orders (#75-#77) -> fills (#78) chain: it owns only the
fan-out across the 11 GICS sectors and the final cross-segment rank. Every seam is faked
here so the whole fan-out runs with no network, no API key, and no pandas-ta call. The
rank key ``(-round(abs(score), 9), symbol, segment)`` is exercised directly on built
plans so any drift in the sign (direction-neutral |score|), the rounding epsilon, the
symbol/segment total-order tie-break, the flat-plan filter, the limit slice, the
skip-and-continue isolation, or the pre-fill rank independence is caught.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.plan import build_plans
from openbb_techtrade.engine.scan import _rank_key, scan_segments
from openbb_techtrade.models import MoverSignal, TradePlan

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90


def _signal(symbol: str, segment: str, score: float) -> MoverSignal:
    """Build a ranked MoverSignal with an explicit score (direction from the sign)."""
    direction = "long" if score >= 0.4 else "short" if score <= -0.4 else "flat"
    return MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF, score=score,
        direction=direction, votes=[], rank_in_segment=1,
    )


def _signal_fetcher_for(signals: dict[tuple[str, str], MoverSignal]):
    """Offline signal_fetcher keyed by (symbol, segment): serves the matching signals."""

    def _fetch(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        return [signals[(s, segment)] for s in (symbols or []) if (s, segment) in signals]

    return _fetch


def _level_fetcher(entry: Decimal = _ENTRY, atr: float = _ATR):
    def _fetch(symbol: str, *, as_of: date):
        return entry, atr

    return _fetch


def _plan(symbol: str, segment: str, score: float) -> TradePlan:
    """Build ONE real TradePlan (signal/rule/size/orders/recommendation) for a score."""
    sig = _signal(symbol, segment, score)
    plans = build_plans(
        symbols=[symbol], segment=segment, as_of=_AS_OF,
        signal_fetcher=_signal_fetcher_for({(symbol, segment): sig}),
        level_fetcher=_level_fetcher(),
    )
    return plans[0]


def test_rank_key_orders_by_abs_score_desc_then_symbol_then_segment():
    """Assert the total-order key sorts by -|score|, then symbol, then segment (design §3)."""
    a = _plan("AAA", "Information Technology", 0.90)
    b = _plan("BBB", "Energy", 0.50)
    c = _plan("CCC", "Financials", -0.95)  # |score| 0.95 is the strongest
    ordered = sorted([a, b, c], key=_rank_key)
    assert [p.symbol for p in ordered] == ["CCC", "AAA", "BBB"]


def test_rank_key_is_direction_neutral_on_equal_abs_score():
    """Assert +0.40 and -0.40 tie on |score| and break by symbol then segment (Q-A/Q-D)."""
    long_xlk = _plan("ZZZ", "Information Technology", 0.40)
    short_aaa = _plan("AAA", "Energy", -0.40)
    ordered = sorted([long_xlk, short_aaa], key=_rank_key)
    # equal |0.40|; "AAA" < "ZZZ" so the short sorts first (symbol tie-break)
    assert [p.symbol for p in ordered] == ["AAA", "ZZZ"]


def test_rank_key_segment_breaks_same_symbol_across_two_etfs():
    """Assert a symbol surfacing in two sectors is total-ordered by segment (design §3)."""
    in_xlk = _plan("DUP", "Information Technology", 0.60)
    in_xlc = _plan("DUP", "Communication Services", 0.60)
    ordered = sorted([in_xlk, in_xlc], key=_rank_key)
    # equal symbol + |score|; "Communication Services" < "Information Technology"
    assert [p.segment for p in ordered] == ["Communication Services", "Information Technology"]


def test_rank_key_rounds_score_to_nine_dp_so_float_noise_does_not_reorder():
    """Assert scores equal within 1e-9 tie on |score| and defer to the symbol key."""
    p1 = _plan("AAA", "Energy", 0.4000000001)
    p2 = _plan("BBB", "Energy", 0.4000000002)  # differ at 1e-10 -> equal after round(...,9)
    ordered = sorted([p2, p1], key=_rank_key)
    assert [p.symbol for p in ordered] == ["AAA", "BBB"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_techtrade.engine.scan'` (the import on line `from openbb_techtrade.engine.scan import _rank_key, scan_segments`).

- [ ] **Step 3: Write the minimal implementation** — create `engine/scan.py` with the module docstring, imports, and `_rank_key` only (orchestrator stubbed minimally so the import resolves).

```python
"""scan orchestrator: all 11 GICS sectors -> cross-segment ranked TradePlans (issue #79, PRD §9.2).

The one-call orchestrator behind ``obb.techtrade.scan``. It is pure **composition** over the
already-built techtrade chain (the design §19 / L4 anti-duplication contract): it owns ONLY the
fan-out across sectors (left edge) and the final cross-segment rank (right edge). Every stage in
between is an existing engine call --

* ``movers.list_movers(segment=None, ...)`` (#70) -- ranks the top movers of all 11 GICS sectors in
  canonical ``GICS_SECTOR_ETFS`` order;
* ``plan.build_plans(symbols=..., segment=...)`` (#75 signals -> #76 rules/sizing -> #77 orders +
  inline ``Recommendation``) -- assembles one ``TradePlan`` per mover;
* ``execution.broker.simulate(orders, bars)`` (#78) -- paper-fills each plan's orders when a forward
  ``t+1...`` window is supplied.

Because #77's ``plan`` exposes no reusable ``build_plans_for_symbols`` seam, this v1 uses the
design-approved **B1** shape (§0.2 Q-B answer): loop ``build_plans`` once per ``MoverList`` (the
literal "loop ``plan(segment=s)`` x11"), with **segment-level** skip-and-continue around each build
and **per-symbol** skip-and-continue around each ``simulate``. Failures emit ``warnings.warn`` so the
command runner surfaces them in ``OBBject.warnings`` (design Q-E). The single new ordering logic is
:func:`_rank_key`: a total-order key ``(-round(abs(score), 9), symbol, segment)`` -- conviction
magnitude first (direction-neutral), then symbol, then segment (a symbol can appear in two sector
ETFs, so segment closes the order). Ranking reads only the **pre-fill** ``signal.score`` so the order
is identical with or without ``simulate`` (design Q-C C3). Determinism rests on a single parent-side
``resolve_session(as_of, "XNYS")`` snap threaded everywhere, the fixed sector order, and the 9-dp
rounding (= ``testing.DEFAULT_TOL``).

This module imports the chain engines (``movers`` / ``plan`` / ``execution.broker``) and ``models``
ONLY -- never ``indicators`` / ``confluence`` / ``rules`` / ``orders`` (the chain-math it composes,
never re-implements; a unit test guards this §19 boundary).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from openbb_techtrade.engine.movers import list_movers, resolve_session
from openbb_techtrade.engine.plan import build_plans
from openbb_techtrade.execution.broker import simulate as simulate_orders
from openbb_techtrade.models import MoverSignal, TradePlan

#: Default risk fraction (mirrors plan.build_plans' 0.01) used when ``risk`` is left ``None``.
_DEFAULT_RISK = 0.01
#: Rounding epsilon for the rank key; matches ``testing.DEFAULT_TOL`` so float noise never reorders.
_RANK_EPSILON = 9


def _rank_key(plan: TradePlan) -> tuple[float, str, str]:
    """Cross-segment total-order sort key: ``(-round(|score|, 9), symbol, segment)`` (design §3).

    Primary key is conviction magnitude (``|signal.score|``) descending, so the most decisive setups
    float to the top regardless of side (a strong short ranks like a strong long). Ties break to a
    **total** order by ``symbol`` then ``segment`` -- the latter is required because a symbol can
    surface in two sector ETFs, so ``symbol`` alone is not unique across segments. The key reads only
    the pre-fill ``signal.score`` so the order is identical whether or not ``simulate`` ran.

    Parameters
    ----------
    plan : TradePlan
        The plan to derive a sort key for.

    Returns
    -------
    tuple[float, str, str]
        ``(-round(abs(score), 9), symbol, segment)``.
    """
    score = plan.signal.score
    return (-round(abs(score), _RANK_EPSILON), plan.symbol, plan.segment)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v`
Expected: the 4 `_rank_key` tests PASS. (`scan_segments` is imported but not yet exercised; the import resolves because it will be defined in Task 2 — so add a minimal placeholder now to keep the import green, see Step 5.)

- [ ] **Step 5: Add a minimal `scan_segments` placeholder so the module import resolves**

Append to `engine/scan.py` (full body lands in Task 2):

```python
def scan_segments(
    metric: str = "pct_change",
    top_n: int = 10,
    *,
    preset: str = "trend_follow",
    risk: float | None = None,
    as_of: date | str | None = None,
    simulate: bool = True,
    limit: int | None = None,
    candidate_fetcher: Callable[..., list[dict]] | None = None,
    signal_fetcher: Callable[..., list[MoverSignal]] | None = None,
    level_fetcher: Callable[..., tuple[Decimal, float]] | None = None,
    bars: dict[str, list] | None = None,
    broker: object | None = None,
) -> list[TradePlan]:
    """Placeholder -- full orchestrator body lands in Task 2."""
    raise NotImplementedError
```

- [ ] **Step 6: Re-run; confirm import green + 4 rank tests pass**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v`
Expected: 4 PASS, 0 fail.

- [ ] **Step 7: Commit**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py openbb_platform/extensions/techtrade/tests/unit/test_scan.py
git commit -m "$(cat <<'EOF'
test(techtrade): #79 scan _rank_key total-order key (red->green)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `scan_segments` orchestration (B1 fan-out + filter + simulate + limit)

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py`
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scan.py`

- [ ] **Step 1: Write the failing tests** — append orchestration tests to `tests/unit/test_scan.py`.

```python
def _candidate_fetcher(*rows: dict):
    """Offline candidate_fetcher (segment-blind): returns the same movers for every sector."""

    def _fetch(as_of=None, calendar="XNYS", needs_ohlcv=False, **kwargs):
        return [dict(r) for r in rows]

    return _fetch


def _bar(open_, high, low, close):
    return {
        "open": Decimal(open_), "high": Decimal(high), "low": Decimal(low),
        "close": Decimal(close), "volume": Decimal("1000000"),
        "timestamp": "2024-01-16T21:00:00+00:00",
    }


# Two movers fetched for EVERY sector (the fetcher is segment-blind), with per-(symbol,segment)
# scores so the same symbol gets a deterministic score in each sector it surfaces in.
def _all_signals(score_aaa: float, score_bbb: float) -> dict:
    from openbb_techtrade.engine.movers import list_movers as _lm  # local import: avoid top cycle
    segments = [ml.segment for ml in _lm(
        segment=None, candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ), as_of=_AS_OF,
    )]
    out: dict[tuple[str, str], MoverSignal] = {}
    for seg in segments:
        out[("AAA", seg)] = _signal("AAA", seg, score_aaa)
        out[("BBB", seg)] = _signal("BBB", seg, score_bbb)
    return out


def test_scan_segments_fans_out_across_all_sectors_and_sorts_by_abs_score():
    """Assert scan fans out over 11 sectors and returns plans sorted by |score| (AAA before BBB)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    # 11 sectors x 2 movers = 22 actionable plans (all |score| >= 0.4 -> all have orders)
    assert len(plans) == 22
    assert len({p.segment for p in plans}) == 11
    keys = [_rank_key(p) for p in plans]
    assert keys == sorted(keys)
    # AAA (|0.90|) entirely precedes BBB (|0.50|)
    assert {p.symbol for p in plans[:11]} == {"AAA"}
    assert {p.symbol for p in plans[11:]} == {"BBB"}


def test_scan_segments_filters_flat_subthreshold_plans():
    """Assert flat / sub-threshold plans (empty orders) are filtered from the ranked list (Q-A)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.05)  # BBB flat (|0.05| < 0.4)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    assert {p.symbol for p in plans} == {"AAA"}  # all 11 BBB flats filtered out
    assert all(p.orders for p in plans)


def test_scan_segments_limit_slices_top_of_list_after_sort():
    """Assert ``limit=k`` returns the first k after the cross-segment sort (Q-A opt-iii)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    plans = scan_segments(
        as_of=_AS_OF, simulate=False, limit=5,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
            {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
    )
    assert len(plans) == 5
    assert {p.symbol for p in plans} == {"AAA"}  # top 5 are all the |0.90| AAA plans


def test_scan_segments_skip_and_continue_on_segment_build_failure():
    """Assert a build raising for one sector drops that sector and keeps the rest (Q-E)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)

    def _boom_for_energy(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
        if segment == "Energy":
            raise RuntimeError("synthetic mover/panel failure")
        return [signals[(s, segment)] for s in (symbols or []) if (s, segment) in signals]

    import pytest
    with pytest.warns(UserWarning, match="Energy"):
        plans = scan_segments(
            as_of=_AS_OF, simulate=False,
            candidate_fetcher=_candidate_fetcher(
                {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
                {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
            ),
            signal_fetcher=_boom_for_energy,
            level_fetcher=_level_fetcher(),
        )
    assert "Energy" not in {p.segment for p in plans}
    assert len({p.segment for p in plans}) == 10  # the other 10 sectors survive


def test_scan_segments_simulate_attaches_fills_when_bars_supplied():
    """Assert simulate=True with a forward window populates simulated_fills (L6, Q-C)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    window = [_bar("121.40", "122", "120.0", "121"), _bar("119", "120", "117.00", "118")]
    plans = scan_segments(
        as_of=_AS_OF, simulate=True, limit=1,
        candidate_fetcher=_candidate_fetcher(
            {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        ),
        signal_fetcher=_signal_fetcher_for(signals),
        level_fetcher=_level_fetcher(),
        bars={"AAA": window},
    )
    assert plans[0].simulated_fills, "expected fills attached for AAA"
    assert plans[0].simulated_fills[0].order_ref == "AAA:entry"


def test_scan_segments_rank_is_identical_with_and_without_simulate():
    """Assert ranking (pre-fill |score|) is independent of the simulate flag (Q-C C3)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    cand = _candidate_fetcher(
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    )
    no_fills = scan_segments(
        as_of=_AS_OF, simulate=False, candidate_fetcher=cand,
        signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher(),
    )
    with_fills = scan_segments(
        as_of=_AS_OF, simulate=True, candidate_fetcher=cand,
        signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher(),
        bars={"AAA": [_bar("121.40", "122", "120.0", "121")]},
    )
    assert [(p.symbol, p.segment) for p in no_fills] == [(p.symbol, p.segment) for p in with_fills]


def test_scan_segments_empty_universe_returns_empty_list():
    """Assert no movers (empty candidate pool) yields an empty plan list (no error)."""
    plans = scan_segments(
        as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher(),  # no rows
        signal_fetcher=_signal_fetcher_for({}),
        level_fetcher=_level_fetcher(),
    )
    assert plans == []


def test_scan_segments_is_deterministic():
    """Assert two identical scans produce equal plan snapshots (pure, no hidden state)."""
    signals = _all_signals(score_aaa=0.90, score_bbb=0.50)
    cand = _candidate_fetcher(
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    )
    kw = dict(as_of=_AS_OF, simulate=False, candidate_fetcher=cand,
              signal_fetcher=_signal_fetcher_for(signals), level_fetcher=_level_fetcher())
    a = scan_segments(**kw)
    b = scan_segments(**kw)
    assert [p.model_dump() for p in a] == [p.model_dump() for p in b]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v`
Expected: the 8 new orchestration tests FAIL with `NotImplementedError` (the placeholder). The 4 Task-1 rank tests still PASS.

- [ ] **Step 3: Write the implementation** — replace the `scan_segments` placeholder body and add `_with_fills`.

```python
def scan_segments(
    metric: str = "pct_change",
    top_n: int = 10,
    *,
    preset: str = "trend_follow",
    risk: float | None = None,
    as_of: date | str | None = None,
    simulate: bool = True,
    limit: int | None = None,
    candidate_fetcher: Callable[..., list[dict]] | None = None,
    signal_fetcher: Callable[..., list[MoverSignal]] | None = None,
    level_fetcher: Callable[..., tuple[Decimal, float]] | None = None,
    bars: dict[str, list] | None = None,
    broker: object | None = None,
) -> list[TradePlan]:
    """Screen all 11 GICS sectors and return cross-segment ranked ``TradePlan``s (PRD §9.2, #79).

    The one-call orchestrator. Snaps ``as_of`` once to the last ``XNYS`` session, ranks each sector's
    top ``top_n`` movers by ``metric`` (``movers.list_movers(segment=None, ...)``), then -- per sector
    (the design-approved **B1** shape) -- assembles a ``TradePlan`` for that sector's movers via
    ``plan.build_plans(symbols=..., segment=...)`` (the #75->#76->#77 chain). When ``simulate`` and a
    forward bar window is supplied for a plan's symbol, the plan's orders are paper-filled (#78) and
    the fills attached. Non-actionable plans (flat / sub-threshold -> empty ``orders``) are filtered,
    and the survivors are sorted by :func:`_rank_key` (conviction magnitude, total-order tie-break).
    A build or fill failure for one sector / symbol is skipped with a ``warnings.warn`` (surfaced in
    ``OBBject.warnings``) rather than aborting the whole scan (design Q-E).

    Parameters
    ----------
    metric : str, optional
        The **mover** rank metric (``pct_change`` / ``volume`` / ``gap`` / ``rel_volume``) selecting
        *which* movers per sector enter the chain. **Not** the cross-segment plan-rank key (that is
        always ``|signal.score|``, §3). Defaults to ``"pct_change"``.
    top_n : int, optional
        Per-segment mover cap (reuses ``movers``/``SegmentConfig`` semantics). The returned list holds
        up to ``11 x top_n`` actionable plans, fully sorted. Defaults to ``10``.
    preset : str, optional
        Confluence/rule preset forwarded to the signal chain. Defaults to ``"trend_follow"``.
    risk : float | None, optional
        Risk-per-trade fraction fed to the #76 sizing; ``None`` uses the chain default ``0.01``.
    as_of : date | str | None, optional
        Requested date, snapped **once** parent-side to the last ``XNYS`` session and threaded down
        (no per-sector re-snap -> no look-ahead drift). Defaults to today when ``None``.
    simulate : bool, optional
        Run #78 fills inline when ``True`` (and a forward window is available); ``False`` returns the
        order skeletons only. Ranking is pre-fill, so the order is identical either way. Defaults to
        ``True``.
    limit : int | None, optional
        Optional global top-of-list slice applied after the cross-segment sort. Defaults to ``None``
        (return the full sorted set).
    candidate_fetcher : Callable[..., list[dict]] | None, optional
        Mover-candidate seam forwarded to ``list_movers``; injected by tests for an offline universe.
    signal_fetcher : Callable[..., list[MoverSignal]] | None, optional
        Ranked-signal seam forwarded to ``build_plans``; injected by tests.
    level_fetcher : Callable[..., tuple[Decimal, float]] | None, optional
        ``(entry, atr)`` seam forwarded to ``build_plans``; injected by tests.
    bars : dict[str, list] | None, optional
        Per-symbol forward (``t+1...``) OHLCV windows for the fill simulation. When ``None`` no fills
        are produced (the live forward-bar fetcher is a follow-up; the skeleton is still ranked).
    broker : object | None, optional
        Broker forwarded to ``simulate``; ``None`` uses the default ``PaperBroker``.

    Returns
    -------
    list[TradePlan]
        Actionable plans across all 11 sectors, cross-segment ranked by ``|signal.score|`` desc
        (symbol, segment tie-break); ``[]`` when no actionable plan is found.
    """
    session = resolve_session(as_of, "XNYS")
    risk_fraction = risk if risk is not None else _DEFAULT_RISK

    mover_lists = list_movers(
        segment=None, metric=metric, top_n=top_n, as_of=session,
        candidate_fetcher=candidate_fetcher,
    )

    plans: list[TradePlan] = []
    for mover_list in mover_lists:
        symbols = [mover.symbol for mover in mover_list.movers]
        if not symbols:
            continue
        try:
            segment_plans = build_plans(
                symbols=symbols, segment=mover_list.segment, preset=preset,
                risk=risk_fraction, as_of=session,
                signal_fetcher=signal_fetcher, level_fetcher=level_fetcher,
            )
        except Exception as exc:  # noqa: BLE001 - skip-and-continue isolation (design Q-E)
            warnings.warn(
                f"scan: skipped segment {mover_list.segment!r}: {exc}", stacklevel=2,
            )
            continue
        plans.extend(segment_plans)

    if simulate and bars is not None:
        plans = [_with_fills(plan, bars, broker) for plan in plans]

    actionable = [plan for plan in plans if plan.orders]
    ranked = sorted(actionable, key=_rank_key)
    return ranked[:limit] if limit is not None else ranked


def _with_fills(plan: TradePlan, bars: dict[str, list], broker: object | None) -> TradePlan:
    """Return ``plan`` with paper fills attached for its symbol's forward window (skip on failure).

    Looks up the plan's symbol in ``bars``; when a non-empty forward window and order list are both
    present, runs ``execution.broker.simulate`` and attaches the resulting fills via ``model_copy``.
    A missing window, empty orders, or a simulation error leaves the plan unchanged (per-symbol
    skip-and-continue with a ``warnings.warn`` on error, design Q-E). Ranking never depends on fills,
    so a skipped fill does not affect the plan's position in the output.

    Parameters
    ----------
    plan : TradePlan
        The plan whose orders to fill.
    bars : dict[str, list]
        Per-symbol forward (``t+1...``) OHLCV windows.
    broker : object | None
        Broker forwarded to ``simulate`` (``None`` -> default ``PaperBroker``).

    Returns
    -------
    TradePlan
        The plan with ``simulated_fills`` populated, or the original plan unchanged.
    """
    window = bars.get(plan.symbol)
    if not window or not plan.orders:
        return plan
    try:
        fills = simulate_orders(plan.orders, window, broker=broker)
    except Exception as exc:  # noqa: BLE001 - per-symbol fill isolation (design Q-E)
        warnings.warn(f"scan: skipped fills for {plan.symbol!r}: {exc}", stacklevel=2)
        return plan
    return plan.model_copy(update={"simulated_fills": fills})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py -m "not integration" -v`
Expected: all 12 tests PASS (4 rank + 8 orchestration).

- [ ] **Step 5: Commit**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py openbb_platform/extensions/techtrade/tests/unit/test_scan.py
git commit -m "$(cat <<'EOF'
feat(techtrade): #79 scan_segments B1 fan-out + filter + simulate + rank

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: §19 composition-only import guard

**Files:**
- Test: `openbb_platform/extensions/techtrade/tests/unit/test_scan.py`

- [ ] **Step 1: Write the failing test** — append to `tests/unit/test_scan.py`.

```python
def test_scan_module_is_composition_only_no_chain_math_imports():
    """Assert scan.py composes the chain engines and re-implements none of their math (§19/L4).

    scan owns only the fan-out + the final rank; every chain-math module (indicators / confluence /
    rules / orders) must be reached THROUGH movers/plan/broker, never imported directly into scan.
    """
    import openbb_techtrade.engine.scan as scan_mod

    source = __import__("inspect").getsource(scan_mod)
    forbidden = ("indicators", "indicators_technical", "confluence", "rules", "import orders")
    for needle in forbidden:
        assert needle not in source, f"scan.py must not reference chain-math module {needle!r} (§19)"
```

- [ ] **Step 2: Run the test to verify it passes** (the implementation already honors this — this test *locks* the boundary against future regressions).

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit/test_scan.py::test_scan_module_is_composition_only_no_chain_math_imports -v`
Expected: PASS. If it FAILS, the implementation imported a chain-math module — remove that import and route through `movers`/`plan`/`broker` instead.

> **Note (TDD nuance):** this is a guard/regression test that passes immediately because Task 2 was written composition-only. That is intentional — it pins an architectural invariant (design §5 row 6), not new behavior. Verify it would fail if violated by temporarily adding `from openbb_techtrade.engine import rules  # noqa` to `scan.py`, re-running (expect FAIL), then removing it (expect PASS).

- [ ] **Step 3: Commit**

```bash
git add openbb_platform/extensions/techtrade/tests/unit/test_scan.py
git commit -m "$(cat <<'EOF'
test(techtrade): #79 lock scan.py composition-only §19 import boundary

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `scan` command on `plan_router.py`

**Files:**
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py`

- [ ] **Step 1: Append the `scan` command** after the existing `simulate` command (end of file). Do **not** add `from __future__ import annotations`.

```python
@router.command(methods=["GET"])
def scan(
    metric: str = "pct_change",
    top_n: int = 10,
    preset: str = "trend_follow",
    risk: float | None = None,
    as_of: str | None = None,
    simulate: bool = True,
    limit: int | None = None,
) -> OBBject:
    """Screen all 11 GICS sectors into a cross-segment ranked plan list (PRD §9.2, issue #79).

    The one-call orchestrator: ranks each sector's top ``top_n`` movers by ``metric``, runs them
    through the #75 signals -> #76 rules/sizing -> #77 orders chain, optionally paper-fills via #78,
    then returns the actionable plans **cross-segment ranked** by ``|signal.score|`` descending
    (symbol, then segment, tie-break). ``metric`` selects *which movers* per sector enter the chain;
    it is **not** the cross-segment plan-rank key. ``as_of`` is snapped once to the last ``XNYS``
    session (look-ahead-free) and threaded to every sector. ``simulate=False`` returns the order
    skeletons only; ``limit`` slices the top of the ranked list. Skipped sectors / symbols (transient
    fetch failures) surface in ``OBBject.warnings`` rather than aborting the scan.

    Parameters
    ----------
    metric : str, optional
        Mover rank metric (``pct_change`` / ``volume`` / ``gap`` / ``rel_volume``). Defaults to
        ``"pct_change"``.
    top_n : int, optional
        Per-segment mover cap. Defaults to ``10`` (up to ``11 x top_n`` plans returned, sorted).
    preset : str, optional
        Confluence/rule preset. Defaults to ``"trend_follow"``.
    risk : float | None, optional
        Risk-per-trade fraction for #76 sizing; ``None`` uses the chain default ``0.01``.
    as_of : str | None, optional
        ISO date to scan as of; snapped to the most recent session. Defaults to today when ``None``.
    simulate : bool, optional
        Run #78 fills inline when forward bars are available. Defaults to ``True``.
    limit : int | None, optional
        Optional global top-of-list slice after the cross-segment sort. Defaults to ``None``.

    Returns
    -------
    OBBject
        OBBject whose ``results`` is a list[TradePlan], cross-segment ranked (empty when no
        actionable setup is found).
    """
    from openbb_techtrade.engine.scan import scan_segments

    return OBBject(results=scan_segments(
        metric=metric, top_n=top_n, preset=preset, risk=risk,
        as_of=as_of, simulate=simulate, limit=limit,
    ))
```

- [ ] **Step 2: Verify the command imports and the router exposes it** (a quick smoke, no rebuild needed for import-level check).

Run:
```bash
.venv_win\Scripts\python.exe -c "from openbb_techtrade.engine.plan_router import scan, router; print('scan' in [getattr(r, 'name', None) or r for r in []] or callable(scan)); print(type(router).__name__)"
```
Expected: prints `True` then `Router`. (If `ImportError`, check the `scan_segments` import path.)

- [ ] **Step 3: Run the full techtrade unit suite to confirm nothing regressed**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/unit -m "not integration" -q`
Expected: all unit tests PASS (the #72–#79 suites).

- [ ] **Step 4: Ruff check the two production files**

Run: `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py`
Expected: `All checks passed!` (line-length 122). Fix any finding before committing.

- [ ] **Step 5: Commit**

```bash
git add openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py
git commit -m "$(cat <<'EOF'
feat(techtrade): #79 wire scan command onto plan_router (bare OBBject)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Offline-deterministic integration test (acceptance gate) + live smoke

**Files:**
- Create: `openbb_platform/extensions/techtrade/tests/integration/test_scan_integration.py`

- [ ] **Step 1: Write the integration test** — fully offline (all seams injected) so the determinism gate runs in CI without `fmp_cached` (design §5), plus a live smoke that skips cleanly.

```python
"""Integration / acceptance test for the #79 scan orchestrator (PRD §9.2, design §5).

THE acceptance gate of #79. A small OFFLINE multi-sector universe is seeded through the injectable
``candidate_fetcher`` / ``signal_fetcher`` / ``level_fetcher`` / ``bars=`` seams, so the
cross-segment determinism assertion runs in CI with no API key and no network. A second, live smoke
exercises the real chain over ``fmp_cached`` and skips cleanly when credentials / data are absent
(mirrors the movers / signals integration resilience).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from openbb_techtrade.engine.scan import scan_segments
from openbb_techtrade.models import MoverSignal, TradePlan
from openbb_techtrade.testing import to_jsonable

pytestmark = pytest.mark.integration

_AS_OF = date(2024, 1, 12)
_ENTRY = Decimal("121.40")
_ATR = 1.90


def _signal(symbol: str, segment: str, score: float) -> MoverSignal:
    direction = "long" if score >= 0.4 else "short" if score <= -0.4 else "flat"
    return MoverSignal(
        symbol=symbol, segment=segment, as_of=_AS_OF, score=score,
        direction=direction, votes=[], rank_in_segment=1,
    )


def _candidate_fetcher(as_of=None, calendar="XNYS", needs_ohlcv=False, **kwargs):
    # segment-blind: the same two movers surface in every sector
    return [
        {"symbol": "AAA", "pct_change": 0.05, "volume": 100},
        {"symbol": "BBB", "pct_change": 0.03, "volume": 200},
    ]


def _signal_fetcher(symbols=None, segment=None, *, preset="trend_follow", as_of=None):
    # AAA strong long, BBB strong short -> distinct |score| per symbol, same in each sector
    scores = {"AAA": 0.90, "BBB": -0.55}
    return [_signal(s, segment, scores[s]) for s in (symbols or []) if s in scores]


def _level_fetcher(symbol: str, *, as_of: date):
    return _ENTRY, _ATR


def _bars() -> dict[str, list]:
    win = [
        {"open": Decimal("121.40"), "high": Decimal("122"), "low": Decimal("120.0"),
         "close": Decimal("121"), "volume": Decimal("1000000"),
         "timestamp": "2024-01-16T21:00:00+00:00"},
        {"open": Decimal("119"), "high": Decimal("120"), "low": Decimal("117.00"),
         "close": Decimal("118"), "volume": Decimal("1000000"),
         "timestamp": "2024-01-17T21:00:00+00:00"},
    ]
    return {"AAA": win, "BBB": win}


def _scan():
    return scan_segments(
        metric="pct_change", top_n=5, as_of=_AS_OF, simulate=True,
        candidate_fetcher=_candidate_fetcher, signal_fetcher=_signal_fetcher,
        level_fetcher=_level_fetcher, bars=_bars(),
    )


def test_scan_ranks_across_sectors_deterministically():
    """Assert scan spans >1 sector, is |score|-ranked, byte-deterministic, and fills are present."""
    plans = _scan()
    assert plans, "offline scan returned no plans"
    assert all(isinstance(p, TradePlan) for p in plans)
    # (a) cross-segment: plans span more than one sector
    assert len({p.segment for p in plans}) > 1
    # (b) ranked: the total-order key is non-decreasing down the list
    keys = [(-round(abs(p.signal.score), 9), p.symbol, p.segment) for p in plans]
    assert keys == sorted(keys)
    # (c) deterministic: a second identical scan is byte-identical
    assert to_jsonable(plans) == to_jsonable(_scan())
    # (d) fills present (L6) and look-ahead-free (every fill stamped strictly after as_of)
    assert all(p.simulated_fills for p in plans)
    assert all(f.timestamp.date() > _AS_OF for p in plans for f in p.simulated_fills)


def test_scan_simulate_false_matches_offline_ranking_order():
    """Assert simulate=False yields the same ranking order (pre-fill rank independence, C3)."""
    with_fills = _scan()
    no_fills = scan_segments(
        metric="pct_change", top_n=5, as_of=_AS_OF, simulate=False,
        candidate_fetcher=_candidate_fetcher, signal_fetcher=_signal_fetcher,
        level_fetcher=_level_fetcher,
    )
    assert [(p.symbol, p.segment) for p in with_fills] == [(p.symbol, p.segment) for p in no_fills]


def test_scan_live_smoke_shape_only():
    """Assert the live chain returns shape-valid ranked plans, or skip on missing creds/data."""
    try:
        plans = scan_segments(metric="pct_change", top_n=2, simulate=False)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully on creds / network
        pytest.skip(f"Live scan unavailable: {exc}")
    assert isinstance(plans, list)
    assert all(isinstance(p, TradePlan) for p in plans)
    assert len({p.segment for p in plans}) <= 11
    keys = [(-round(abs(p.signal.score), 9), p.symbol, p.segment) for p in plans]
    assert keys == sorted(keys)
```

- [ ] **Step 2: Run the offline acceptance tests**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests/integration/test_scan_integration.py -m "integration" -v`
Expected: `test_scan_ranks_across_sectors_deterministically` and `test_scan_simulate_false_matches_offline_ranking_order` PASS; `test_scan_live_smoke_shape_only` PASSES or SKIPS (no creds) — never fails.

- [ ] **Step 3: Commit**

```bash
git add openbb_platform/extensions/techtrade/tests/integration/test_scan_integration.py
git commit -m "$(cat <<'EOF'
test(techtrade): #79 offline-deterministic scan acceptance + live smoke

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Quality (simplify), full-suite verification, review, finalize

**Files:** (review-only; fixes applied inline as found)

- [ ] **Step 1: Run the whole techtrade suite (unit + integration, offline)**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/techtrade/tests -q`
Expected: all PASS or cleanly SKIP (live-only tests). Zero failures, zero errors.

- [ ] **Step 2: Ruff check all touched production files**

Run: `.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/techtrade/openbb_techtrade/engine/scan.py openbb_platform/extensions/techtrade/openbb_techtrade/engine/plan_router.py`
Expected: `All checks passed!`

- [ ] **Step 3: Invoke the `simplify` skill** on the #79 diff — launch the 3 review agents (reuse, quality, efficiency) in parallel, aggregate, fix directly. Focus: confirm no chain-math duplication crept into `scan.py`; confirm `_with_fills` / filter / sort are the minimal surface; confirm seam names match the rest of the package.

- [ ] **Step 4: Invoke `superpowers:requesting-code-review`** — dispatch a code-reviewer subagent over `BASE_SHA=de29f94fe HEAD_SHA=$(git rev-parse HEAD)` with the design doc + contract #79 section as requirements. Fix Critical/Important findings before finalizing.

- [ ] **Step 5: Confirm only #79 manifest files + the 3 known noise files are dirty**

Run: `git status --short`
Expected: the 3 noise files (`reference.json`, `package/__init__.py`, `agents/tests/test_config.py`) plus nothing else uncommitted (Tasks 1–5 already committed the four #79 files). The 3 noise files stay **UNSTAGED**.

- [ ] **Step 6: Push and comment on GitHub issue #79**

```bash
git push
gh issue comment 79 --body "$(cat <<'EOF'
Implemented #79 (scan command -> cross-segment ranked TradePlans): `engine/scan.py` (`scan_segments` + `_rank_key`), the `scan` command on `engine/plan_router.py`, `tests/unit/test_scan.py`, and `tests/integration/test_scan_integration.py`. B1 fan-out (loop `build_plans(segment=...)` x11) with segment/symbol skip-and-continue surfaced in `OBBject.warnings`; cross-segment rank `(-round(abs(score),9), symbol, segment)` (pre-fill, simulate-independent); offline-deterministic acceptance gate. Follow-up filed: live forward-bar fetcher for fills + B2 shared `build_plans_for_symbols` seam.
EOF
)"
```

- [ ] **Step 7: Mark native task #24 (#79) completed; file the B2 / live-bars follow-up.**

---

## Self-Review

**1. Spec coverage (design acceptance map §509–§517):**
- `scan(metric, top_n, preset)` chains screener→signals→rules→orders→fills → Task 2 (`scan_segments` B1) + Task 4 (command).
- Cross-segment ranking → Task 1 (`_rank_key`).
- Deterministic ordering for a fixed as-of → Task 2 (single `resolve_session` snap) + Task 5 (determinism assertion).
- Integration test over a small multi-sector universe → Task 5.
- Returns ranked `TradePlan`s across all 11 sectors → Task 2 fan-out + Task 4 `OBBject(results=...)`.
- Reuses #73/#75/#77/#78, no logic duplication → Task 3 (§19 guard) + composition-only imports.
- Deterministic output (`to_jsonable` byte-stability) → Task 5 (c).
- Net-new dependency (B2 shared builder) → documented as B1 fallback + Task 6 follow-up.

**2. Placeholder scan:** none — every step carries full code or an exact command + expected output. Task 1 Step 5 is a deliberate, labeled interim placeholder replaced in Task 2 Step 3.

**3. Type consistency:** `scan_segments` signature is identical in Task 1 (placeholder), Task 2 (body), and is called with the same kwargs by the Task 4 command. `_rank_key(plan) -> tuple[float, str, str]`. `_with_fills(plan, bars, broker) -> TradePlan`. `bars: dict[str, list]`. Seam names (`candidate_fetcher`, `signal_fetcher`, `level_fetcher`, `bars`, `broker`) match the engines they forward to. Command params (`metric, top_n, preset, risk, as_of, simulate, limit`) ⊇ contract's 4-param sketch and = design §4.
