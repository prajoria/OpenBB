# Phase 4: market_snapshot + AlertManager v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the pre-open discovery command (`market_snapshot`) and AlertManager v1 (3 spec types with session-journal + agent-context delivery only, no external channels). Closes PRD §10 Phase 4 tasks P4.1–P4.4 and article-adjacent additions from §4.2.

**Architecture:** Two loosely-coupled surfaces land in the same phase. (a) `market_snapshot` is a pure builder that fans out to existing `obb.equity.discovery.{gainers,losers,actives}` via `fmp_cached`, unifies rows, computes sentiment + top-mover + optional sector-rollup + volatility filter, returns a `MarketSnapshot`. No new fetchers. (b) `AlertManager` is a session-scoped registry + evaluator dispatching on `AlertSpec.kind` (discriminated union). Two delivery sinks only: session journal (always) + agent-context callable (only when set). External delivery (webhook, email, push, SMS) is forbidden in v1 — enforced by an AST-level architecture test.

**Tech Stack:** Python 3.10-3.13, `openbb-core` v4.6.0+, Pydantic v2, `Decimal` for money/quantities, `pytest` (+ `parametrize` for cross-matrices), stdlib `ast` for the NG7 guardrail. Env: `.venv_win`. Provider always `fmp_cached`.

**PRD references:** §4.2 (market_snapshot), §4.4 (AlertManager), §6.2.2 (MarketSnapshot models), §6.2.4 (Alert models), §10 Phase 4, §1.3 follow-up #2 (AlertManager v2 deferred), NG7 (no external delivery in v1).

---

## Critical Design Constraints — READ FIRST

1. **Codegen bug (inherited from Phase 1):** every router command annotates return type as **bare `OBBject`**, never `OBBject[MarketSnapshot]` or `OBBject[Alert]`. The static package builder emits parametrized model names into generated signatures without importing them → `NameError` on first namespace access. See Phase 1 scaffold plan for full trace.

2. **NG7 delivery cap:** `AlertManager` may deliver `AlertEvent`s to **exactly two sinks** — `journal_write: Callable[[JournalEvent], None]` and optional `agent_notify: Callable[[AlertEvent], None]`. Nothing else. No webhook, no email, no push, no SMS. Enforced by (a) an AST test in `tests/architecture/test_alert_delivery_ng7.py` that fails the build if `alert_manager.py` imports `smtplib`, `requests`, `httpx`, `urllib.request`, `twilio`, `aiohttp`, or `email.mime`, plus (b) an instance-attribute audit ensuring the manager carries no forbidden attribute names.

3. **Provider posture (from PRD §5.4):** no `provider="fmp"` literal anywhere in this phase's code. Every `obb.equity.*` call in `snapshot_router.py` passes `provider="fmp_cached"`. Phase 0's CI grep test catches regressions.

4. **AlertSpec is a discriminated union** — `AlertSpec = Annotated[PriceThresholdSpec | PercentChangeSpec | VolumeSpikeSpec, Field(discriminator="kind")]`. Never re-declare; import from `openbb_fmp_trading.models.alert` (Phase 1 defined this).

**Tracker:** GitHub epic + Phase-4 sub-issue; reference in every commit. Do NOT invent a bd id.

**Branch:** `fmp_trading` (per PRD). No worktree.

---

## Global Constraints

Copy-forward from PRD §2.2. Every task must respect these.

- **P1** — Deterministic core. Neither snapshot builder nor AlertManager touches an LLM.
- **P2** — `Decimal` for money and share counts; no float drift. `MoverRow.price/change`, `PriceThresholdSpec.price` are `Decimal`; ratios/percentages (`change_pct`, `threshold_pct`, `sentiment_ratio`) are `float`.
- **P3** — No look-ahead: AlertManager evaluates on completed ticks; no peeking at future bars.
- **P5** — All timestamps tz-aware (`datetime.now(timezone.utc)` where needed; snapshot `as_of` from Quote timestamps).
- **P6** — `market_snapshot` uses `provider="fmp_cached"` — cache-first bandwidth discipline.
- **P7** — RiskManager veto not touched here; AlertManager emits events, never mutates positions.
- **NG7** — external delivery of alerts is v2. AST test enforces.

---

## File Structure

All paths under `openbb_platform/extensions/fmp_trading/`:

| File | Responsibility |
|---|---|
| `openbb_fmp_trading/core/market_snapshot.py` | Pure `build_snapshot(top_n, include, ...)` — fetches gainers/losers/actives, unifies, computes sentiment ratio + top movers + optional sector rollup + volatility filter. |
| `openbb_fmp_trading/core/alert_manager.py` | `AlertManager` class: CRUD + `evaluate(tick) → list[AlertEvent]` + 2-sink delivery. Session-scoped. |
| `openbb_fmp_trading/router/snapshot_router.py` | Router: `obb.fmp_trading.market_snapshot(...)` (bare `OBBject`). |
| `openbb_fmp_trading/router/alert_router.py` | Router: `obb.fmp_trading.alert.{create,list,delete,evaluate,history}` + module-level `_manager` bound per session. |
| `openbb_fmp_trading/cli/alert_cmd.py` | argparse subcommands `openbb-daytrade alert {create,list,delete}`. |
| `tests/unit/test_market_snapshot.py` | Builder tests: all-inclusion, single-inclusion, volatility filter, sector rollup, empty inputs, top-mover edge cases. |
| `tests/unit/test_alert_manager.py` | CRUD + one happy-path per spec + reset. |
| `tests/unit/test_alert_router.py` | Router smoke: bind_session, mocked evaluate returning events. |
| `tests/unit/test_alert_cli.py` | CLI smoke: create/list/delete round-trip. |
| `tests/architecture/test_alert_delivery_ng7.py` | AST-level test: alert_manager.py MUST NOT import external-delivery libs. |
| `tests/unit/test_alert_matrix.py` | (Task 7) Parametrized cross-matrix per spec + NG7 delivery invariants. |

Modified outside these paths:
- `openbb_fmp_trading/router/__init__.py` — re-export `snapshot_router`, `alert_router`.
- `openbb_fmp_trading/fmp_trading_router.py` — extend lazy-include tuple with per-entry prefix.
- `openbb_fmp_trading/cli/main.py` — register `alert` subparser.

> **Out of scope for Phase 4** (do NOT create here):
> - External delivery (webhook/email/push/SMS) → v2 (NG7)
> - Pattern-based alerts (breakout, wedge, ML) → v2 (PRD §1.3 follow-up #3)
> - Bar-history-based percent-change windows (`"1h"`, `"5m"`) → deferred to Phase 5 (v1 supports `"session"` only; the other two raise `NotImplementedError` with a clear v2 pointer)
> - Auto-wiring `bind_session` from `IntradaySession.run()` → touched by Phase 2 owner when tick loop lands

---

## Task 1: NG7 architecture guardrail (do this FIRST)

Locks the NG7 invariant BEFORE any AlertManager code lands. If a future contributor adds a webhook import, this test fails the build immediately.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/tests/architecture/__init__.py` (empty package marker)
- Create: `openbb_platform/extensions/fmp_trading/tests/architecture/test_alert_delivery_ng7.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/alert_manager.py` (empty stub so imports don't fail)

**Consumes:** nothing — this is a static check.
**Produces:** CI guardrail failing the build if `alert_manager.py` imports any external-delivery lib.

- [ ] **Step 1: Create the guardrail test (fails until stub exists)**

```python
"""NG7 guardrail — alert_manager.py must not import any external-delivery client in v1.

If you're adding webhook/email/push/SMS to v1 you are re-opening the PRD;
this test will fail loudly. Move it to v2 or amend PRD §1.3 first.
"""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_IMPORTS = {
    "smtplib", "email.mime", "email.message",   # email
    "requests", "httpx", "urllib.request",       # webhook / http push
    "twilio", "pushover", "pusher",              # SMS / push
    "boto3",                                     # AWS SES / SNS
    "aiohttp",                                   # webhook async
}

MODULE = (
    Path(__file__).resolve().parents[2]
    / "openbb_fmp_trading" / "core" / "alert_manager.py"
)


def test_alert_manager_has_no_external_delivery_imports():
    assert MODULE.exists(), f"expected {MODULE} to exist"
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    hits = FORBIDDEN_IMPORTS & imported
    assert not hits, (
        f"NG7 violation: alert_manager.py imports {hits}. v1 delivery is journal + "
        "agent-context only. Webhook/email/push/SMS is v2 (PRD §1.3 follow-up #2)."
    )
```

- [ ] **Step 2: Create empty stub so the test can execute**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/alert_manager.py`:

```python
"""AlertManager v1 — stub. Real implementation lands in Task 4.

NG7: this module MUST NOT import smtplib/requests/httpx/twilio/aiohttp/etc.
Enforced by tests/architecture/test_alert_delivery_ng7.py.
"""
```

- [ ] **Step 3: Run test to verify PASS**

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/architecture/test_alert_delivery_ng7.py -q
```
Expected: `1 passed`.

- [ ] **Step 4: Commit**

```
git add openbb_platform/extensions/fmp_trading/tests/architecture/ openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/alert_manager.py
git commit -m "test(fmp_trading): NG7 architecture guardrail — AlertManager forbidden imports (P4)

AST test fails the build if alert_manager.py grows a smtplib/requests/httpx/
twilio/aiohttp import — locks NG7 (no external delivery in v1) before any
AlertManager code lands. Empty module stub so the test can execute.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: `market_snapshot` builder (P4.1 core)

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_market_snapshot.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/market_snapshot.py`

**Consumes:** `MoverRow`, `MarketSnapshot` (from `openbb_fmp_trading.models.snapshot`, Phase 1).
**Produces:** `build_snapshot(top_n, include, volatility_threshold_pct, sector_rollup, exchange, discovery_client, profile_client) → MarketSnapshot`. Discovery/profile clients are injected for testability.

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for market_snapshot builder (P4.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openbb_fmp_trading.core.market_snapshot import build_snapshot


class _MockDiscovery:
    """Stub for obb.equity.discovery.* — returns fixture rows."""
    def __init__(self, gainers=None, losers=None, actives=None):
        self._gainers = gainers or []
        self._losers = losers or []
        self._actives = actives or []

    def gainers(self, provider=None): return MagicMock(results=self._gainers)
    def losers(self, provider=None): return MagicMock(results=self._losers)
    def most_active(self, provider=None): return MagicMock(results=self._actives)


def _row(symbol, name, price, change_pct, volume):
    """Fixture builder for a discovery result row."""
    return MagicMock(
        symbol=symbol, name=name,
        price=float(price), change=0.0, change_pct=float(change_pct),
        volume=int(volume),
    )


def test_snapshot_unifies_gainers_losers_actives():
    disc = _MockDiscovery(
        gainers=[_row("AAPL", "Apple", "180.0", 5.2, 1_000_000)],
        losers=[_row("XYZ", "XYZ Corp", "50.0", -6.1, 500_000)],
        actives=[_row("MSFT", "Microsoft", "400.0", 1.0, 2_000_000)],
    )
    snap = build_snapshot(
        top_n=10, include=["gainers", "losers", "actives"],
        discovery_client=disc, profile_client=None,
    )
    assert len(snap.movers) == 3
    types = [m.type for m in snap.movers]
    assert "gainer" in types and "loser" in types and "active" in types


def test_snapshot_sentiment_ratio():
    disc = _MockDiscovery(
        gainers=[_row("A", "A", "1", 1, 1), _row("B", "B", "1", 1, 1), _row("C", "C", "1", 1, 1)],
        losers=[_row("X", "X", "1", -1, 1)],
    )
    snap = build_snapshot(top_n=10, include=["gainers", "losers"],
                          discovery_client=disc, profile_client=None)
    assert snap.sentiment_ratio == 3.0                                     # 3 gainers / 1 loser


def test_snapshot_top_gainer_and_top_loser():
    disc = _MockDiscovery(
        gainers=[_row("AAPL", "Apple", "180", 5.2, 1_000),
                 _row("TSLA", "Tesla", "250", 8.1, 500)],
        losers=[_row("XYZ", "XYZ", "50", -6.1, 500),
                _row("ABC", "ABC", "10", -12.0, 100)],
    )
    snap = build_snapshot(top_n=10, include=["gainers", "losers"],
                          discovery_client=disc, profile_client=None)
    assert snap.top_gainer.symbol == "TSLA"                                # highest change_pct
    assert snap.top_loser.symbol == "ABC"                                  # lowest change_pct


def test_snapshot_volatility_filter():
    disc = _MockDiscovery(
        gainers=[_row("A", "A", "1", 6.0, 1), _row("B", "B", "1", 3.0, 1)],
        losers=[_row("X", "X", "1", -7.0, 1), _row("Y", "Y", "1", -2.0, 1)],
    )
    snap = build_snapshot(
        top_n=10, include=["gainers", "losers"],
        volatility_threshold_pct=5.0,
        discovery_client=disc, profile_client=None,
    )
    assert snap.volatile_movers is not None
    volatile_symbols = {m.symbol for m in snap.volatile_movers}
    assert volatile_symbols == {"A", "X"}                                  # |pct| > 5


def test_snapshot_sector_rollup_populates_breakdown():
    disc = _MockDiscovery(
        gainers=[_row("AAPL", "Apple", "180", 5.2, 1_000),
                 _row("MSFT", "MS", "400", 3.0, 500)],
    )
    profile = MagicMock()
    profile.side_effect = lambda symbol, provider=None: MagicMock(
        results=[MagicMock(sector="Technology")]
    )
    snap = build_snapshot(top_n=10, include=["gainers"], sector_rollup=True,
                          discovery_client=disc, profile_client=profile)
    assert snap.sector_breakdown == {"Technology": 2}


def test_snapshot_empty_inputs_produces_empty_snapshot():
    disc = _MockDiscovery()
    snap = build_snapshot(top_n=10, include=["gainers", "losers"],
                          discovery_client=disc, profile_client=None)
    assert snap.movers == []
    assert snap.top_gainer is None and snap.top_loser is None
    assert snap.sentiment_ratio == 0.0
```

- [ ] **Step 2: Run test — expect fail**

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_market_snapshot.py -q
```
Expected: FAIL — `ImportError: cannot import name 'build_snapshot'`.

- [ ] **Step 3: Implement the builder**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/market_snapshot.py`:

```python
"""market_snapshot builder — pure fan-out over discovery.{gainers,losers,actives}.

Article-inspired pattern (unified gainers+losers+actives with sentiment ratio +
top-mover extraction + volatility filter + optional sector rollup) — see PRD §4.2.

Provider posture: discovery calls use provider="fmp_cached" ALWAYS. Never raw fmp.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Literal

from openbb_fmp_trading.models.snapshot import MarketSnapshot, MoverRow


def _to_mover_row(row: Any, mover_type: Literal["gainer", "loser", "active"]) -> MoverRow:
    """Coerce a discovery result row into a MoverRow. Uses str/float coercion
    to survive slight upstream shape drift; Decimal for money-adjacent fields."""
    return MoverRow(
        symbol=row.symbol,
        type=mover_type,
        name=getattr(row, "name", row.symbol),
        price=Decimal(str(row.price)),
        change=Decimal(str(getattr(row, "change", 0.0))),
        change_pct=float(getattr(row, "change_pct", getattr(row, "percent_change", 0.0))),
        volume=int(getattr(row, "volume", 0)),
        sector=None,
    )


def build_snapshot(
    top_n: int = 10,
    include: list[Literal["gainers", "losers", "actives"]] | None = None,
    volatility_threshold_pct: float | None = None,
    sector_rollup: bool = False,
    exchange: str = "NASDAQ",
    discovery_client: Any = None,
    profile_client: Callable[..., Any] | None = None,
) -> MarketSnapshot:
    """Build a MarketSnapshot from discovery data.

    discovery_client: obb.equity.discovery namespace (real or mock).
    profile_client:   callable like obb.equity.profile(symbol=..., provider=...)
                      — required only when sector_rollup=True.
    """
    include = include or ["gainers", "losers", "actives"]
    movers: list[MoverRow] = []

    if discovery_client is None:
        from openbb import obb
        discovery_client = obb.equity.discovery

    if "gainers" in include:
        for row in list(discovery_client.gainers(provider="fmp_cached").results)[:top_n]:
            movers.append(_to_mover_row(row, "gainer"))
    if "losers" in include:
        for row in list(discovery_client.losers(provider="fmp_cached").results)[:top_n]:
            movers.append(_to_mover_row(row, "loser"))
    if "actives" in include:
        for row in list(discovery_client.most_active(provider="fmp_cached").results)[:top_n]:
            movers.append(_to_mover_row(row, "active"))

    if sector_rollup and movers:
        if profile_client is None:
            from openbb import obb
            profile_client = lambda symbol, provider="fmp_cached": obb.equity.profile(
                symbol=symbol, provider=provider
            )
        for m in movers:
            try:
                prof = profile_client(symbol=m.symbol, provider="fmp_cached")
                m.sector = getattr(prof.results[0], "sector", None)
            except Exception:
                m.sector = None

    gainer_count = sum(1 for m in movers if m.type == "gainer")
    loser_count = sum(1 for m in movers if m.type == "loser")
    sentiment_ratio = gainer_count / max(loser_count, 1) if (gainer_count + loser_count) else 0.0

    gainers = [m for m in movers if m.type == "gainer"]
    losers = [m for m in movers if m.type == "loser"]
    top_gainer = max(gainers, key=lambda m: m.change_pct) if gainers else None
    top_loser = min(losers, key=lambda m: m.change_pct) if losers else None

    volatile: list[MoverRow] | None = None
    if volatility_threshold_pct is not None:
        volatile = [m for m in movers if abs(m.change_pct) > volatility_threshold_pct]

    breakdown: dict[str, int] | None = None
    if sector_rollup:
        breakdown = {}
        for m in movers:
            if m.sector:
                breakdown[m.sector] = breakdown.get(m.sector, 0) + 1

    return MarketSnapshot(
        as_of=datetime.now(timezone.utc),
        movers=movers,
        sentiment_ratio=sentiment_ratio,
        top_gainer=top_gainer,
        top_loser=top_loser,
        sector_breakdown=breakdown,
        volatile_movers=volatile,
    )
```

- [ ] **Step 4: Run tests — expect PASS + commit**

Run:
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_market_snapshot.py -q
```
Expected: `6 passed`.

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/market_snapshot.py openbb_platform/extensions/fmp_trading/tests/unit/test_market_snapshot.py
git commit -m "feat(fmp_trading): market_snapshot builder — unified gainers/losers/actives (P4.1)

Pure builder fans out to obb.equity.discovery.* via fmp_cached; unifies rows
into MoverRow; computes sentiment ratio, top gainer/loser, optional sector
rollup (joins equity.profile), optional volatility filter. No new fetchers.

Refs PRD §4.2 and article: coinmonks/top-gainers-and-losers-quick-market-
updates-with-fmp-d71f75193543.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: `snapshot_router.py` — obb.fmp_trading.market_snapshot

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_snapshot_router.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/router/__init__.py` (if not present)
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/router/snapshot_router.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py` (add lazy include)

**Consumes:** `build_snapshot` from Task 2.
**Produces:** `obb.fmp_trading.market_snapshot(...) → OBBject` (bare!) whose `results` is the `MarketSnapshot.model_dump(mode="json")`.

- [ ] **Step 1: Failing router smoke test**

```python
"""Router smoke test for obb.fmp_trading.market_snapshot."""

from __future__ import annotations

from unittest.mock import patch

from openbb_fmp_trading.router.snapshot_router import market_snapshot


def test_router_returns_bare_obbject():
    with patch("openbb_fmp_trading.router.snapshot_router.build_snapshot") as m:
        from openbb_fmp_trading.models.snapshot import MarketSnapshot
        from datetime import datetime, timezone
        m.return_value = MarketSnapshot(
            as_of=datetime.now(timezone.utc),
            movers=[], sentiment_ratio=0.0,
            top_gainer=None, top_loser=None,
            sector_breakdown=None, volatile_movers=None,
        )
        result = market_snapshot(top_n=5)
        assert hasattr(result, "results")


def test_router_passes_params_through():
    with patch("openbb_fmp_trading.router.snapshot_router.build_snapshot") as m:
        from openbb_fmp_trading.models.snapshot import MarketSnapshot
        from datetime import datetime, timezone
        m.return_value = MarketSnapshot(
            as_of=datetime.now(timezone.utc),
            movers=[], sentiment_ratio=0.0,
            top_gainer=None, top_loser=None,
            sector_breakdown=None, volatile_movers=None,
        )
        market_snapshot(top_n=20, include=["gainers"], volatility_threshold_pct=5.0,
                        sector_rollup=True, exchange="NYSE")
        m.assert_called_once_with(
            top_n=20, include=["gainers"], volatility_threshold_pct=5.0,
            sector_rollup=True, exchange="NYSE",
        )
```

- [ ] **Step 2: Implement router**

Create `openbb_fmp_trading/router/__init__.py`:
```python
"""fmp_trading router subpackage — sub-routers included by fmp_trading_router."""

from openbb_fmp_trading.router.snapshot_router import router as snapshot_router

__all__ = ["snapshot_router"]
```

Create `openbb_fmp_trading/router/snapshot_router.py`:
```python
"""Router: obb.fmp_trading.market_snapshot(...).

CODEGEN: return bare `OBBject`, never `OBBject[MarketSnapshot]` — see Phase 1
Critical Design Constraint.
"""

from __future__ import annotations

from typing import Literal

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_fmp_trading.core.market_snapshot import build_snapshot

router = Router(prefix="")


@router.command(methods=["GET"])
def market_snapshot(
    top_n: int = 10,
    include: list[Literal["gainers", "losers", "actives"]] | None = None,
    volatility_threshold_pct: float | None = None,
    sector_rollup: bool = False,
    exchange: str = "NASDAQ",
) -> OBBject:
    """Unified pre-open gainers/losers/actives snapshot (PRD §4.2)."""
    snap = build_snapshot(
        top_n=top_n, include=include,
        volatility_threshold_pct=volatility_threshold_pct,
        sector_rollup=sector_rollup, exchange=exchange,
    )
    return OBBject(results=snap.model_dump(mode="json"))
```

- [ ] **Step 3: Wire into `fmp_trading_router.py`**

Extend the existing lazy-include tuple to append the snapshot router. Add near the top of `_include_subrouters`:
```python
from openbb_fmp_trading.router.snapshot_router import router as snapshot_router
router.include_router(snapshot_router)
```
(Exact wiring depends on the Phase 1 scaffold — follow the pattern established there.)

- [ ] **Step 4: Rebuild + codegen probe + test**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_snapshot_router.py -q
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print(callable(obb.fmp_trading.market_snapshot))"
.venv_win\Scripts\python.exe -c "s=open('openbb_platform/core/openbb/package/fmp_trading.py').read(); assert 'OBBject[' not in s; print('codegen clean')"
```
Expected: `2 passed`; `openbb.build()` exit 0; `True`; `codegen clean`.

- [ ] **Step 5: Commit**

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/router/ openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py openbb_platform/extensions/fmp_trading/tests/unit/test_snapshot_router.py
git commit -m "feat(fmp_trading): market_snapshot router — obb.fmp_trading.market_snapshot (P4.1)

Thin router over build_snapshot; returns bare OBBject with MarketSnapshot
dict payload. Codegen-safe (no OBBject[Model]).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: `AlertManager` core (P4.2)

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_alert_manager.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/alert_manager.py` (replace Task-1 stub)

**Consumes:** `AlertSpec` union, `Alert`, `AlertEvent` (from `openbb_fmp_trading.models.alert`, Phase 1); `TickData` (Phase 1); `JournalEvent` (Phase 1).
**Produces:**
- `AlertManager(session_id: str, journal_write: Callable | None, agent_notify: Callable | None)`
- `.create(spec) → Alert`
- `.list(active_only=True) → list[Alert]`
- `.delete(alert_id) → bool`
- `.evaluate(tick: TickData) → list[AlertEvent]` (fires sinks internally)
- `.history() → list[AlertEvent]` (session-scoped)
- `reset_manager_for_tests()` helper for offline test isolation

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for AlertManager v1 — CRUD + happy-path fires per spec + reset."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openbb_fmp_trading.core.alert_manager import AlertManager
from openbb_fmp_trading.models.alert import (
    Alert, AlertEvent, PercentChangeSpec, PriceThresholdSpec, VolumeSpikeSpec,
)


NOW = datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)


def _quote(symbol, price, ts=NOW):
    return MagicMock(symbol=symbol, price=Decimal(str(price)),
                     change=Decimal("0"), change_pct=0.0, volume=100, timestamp=ts)


def _bar(symbol, ts, volume):
    return MagicMock(symbol=symbol, ts=ts, volume=int(volume))


def _tick(ts, quotes, bars=None):
    return MagicMock(
        ts=ts, quotes=quotes, bars_recent=bars or {},
        session_status=MagicMock(exchange="NASDAQ"),
    )


# ---- CRUD ---------------------------------------------------------------------

def test_create_returns_alert_with_uuid_and_registers():
    mgr = AlertManager()
    a = mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    assert isinstance(a, Alert)
    assert a.is_active is True
    assert a.fired_count == 0
    assert a in mgr.list()


def test_list_active_only_default():
    mgr = AlertManager()
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    assert len(mgr.list(active_only=True)) == 1


def test_delete_removes_alert():
    mgr = AlertManager()
    a = mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    ok = mgr.delete(a.id)
    assert ok is True
    assert mgr.list() == []


def test_delete_unknown_returns_false():
    mgr = AlertManager()
    assert mgr.delete(str(uuid.uuid4())) is False


# ---- Happy-path fires per spec ------------------------------------------------

def test_price_threshold_up_fires_on_cross():
    mgr = AlertManager()
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
    events = mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
    assert len(events) == 1 and events[0].symbol == "AAPL"


def test_percent_change_session_fires_on_breach():
    mgr = AlertManager()
    mgr.create(PercentChangeSpec(symbol="TSLA", threshold_pct=5.0, window="session"))
    q = _quote("TSLA", "210")
    q.change_pct = 6.2
    events = mgr.evaluate(_tick(NOW, {"TSLA": q}))
    assert len(events) == 1


def test_volume_spike_fires_when_current_exceeds_ratio():
    mgr = AlertManager()
    mgr.create(VolumeSpikeSpec(symbol="NVDA", ratio_vs_avg=3.0, avg_window=5))
    for i in range(5):
        mgr.evaluate(_tick(
            NOW + timedelta(minutes=5 * i),
            {"NVDA": _quote("NVDA", "500")},
            bars={"NVDA": [_bar("NVDA", NOW + timedelta(minutes=5 * i), 100_000)]},
        ))
    events = mgr.evaluate(_tick(
        NOW + timedelta(minutes=30),
        {"NVDA": _quote("NVDA", "500")},
        bars={"NVDA": [_bar("NVDA", NOW + timedelta(minutes=30), 400_000)]},
    ))
    assert len(events) == 1


# ---- Sink delivery ------------------------------------------------------------

def test_journal_sink_receives_event():
    written: list = []
    mgr = AlertManager(session_id="s1", journal_write=written.append)
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
    mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
    assert len(written) == 1


def test_agent_sink_receives_event_when_bound():
    ctx: list = []
    mgr = AlertManager(agent_notify=ctx.append)
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
    mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
    assert len(ctx) == 1 and isinstance(ctx[0], AlertEvent)


def test_history_returns_all_fired_events():
    mgr = AlertManager()
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
    mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
    mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
    assert len(mgr.history()) == 1
```

- [ ] **Step 2: Implement the manager (replace stub)**

Overwrite `openbb_fmp_trading/core/alert_manager.py`:

```python
"""AlertManager v1 — session-scoped registry + pure evaluator + NG7 dual-sink delivery.

NG7: AlertEvents go to (a) the SessionJournal (always when journal_write is
provided) and (b) an agent-context sink (only when agent_notify is bound).
NO webhook, NO email, NO push, NO SMS in v1. Enforced by
tests/architecture/test_alert_delivery_ng7.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable

from openbb_fmp_trading.models.alert import (
    Alert, AlertEvent, AlertSpec, PercentChangeSpec, PriceThresholdSpec, VolumeSpikeSpec,
)


@dataclass
class _PriceState:
    last_side: str | None = None                   # "above" | "below" | None


@dataclass
class AlertManager:
    session_id: str = "default"
    journal_write: Callable[[Any], None] | None = None
    agent_notify: Callable[[AlertEvent], None] | None = None
    _alerts: dict[str, Alert] = field(default_factory=dict)
    _price_state: dict[str, _PriceState] = field(default_factory=dict)
    _history: list[AlertEvent] = field(default_factory=list)

    # ---- CRUD ------------------------------------------------------------------

    def create(self, spec: AlertSpec) -> Alert:
        alert = Alert(
            id=str(uuid.uuid4()),
            spec=spec,
            created_at=datetime.now(timezone.utc),
            is_active=True,
            fired_count=0,
            session_id=self.session_id,
        )
        self._alerts[alert.id] = alert
        return alert

    def list(self, active_only: bool = True) -> list[Alert]:
        vals = self._alerts.values()
        return [a for a in vals if a.is_active] if active_only else list(vals)

    def delete(self, alert_id: str) -> bool:
        popped = self._alerts.pop(alert_id, None)
        self._price_state.pop(alert_id, None)
        return popped is not None

    def history(self) -> list[AlertEvent]:
        return list(self._history)

    # ---- Evaluation ------------------------------------------------------------

    def evaluate(self, tick: Any) -> list[AlertEvent]:
        """Evaluate ALL active alerts against a tick; deliver via sinks."""
        events: list[AlertEvent] = []
        for alert in self._alerts.values():
            if not alert.is_active:
                continue
            evt = self._evaluate_one(alert, tick)
            if evt is not None:
                events.append(evt)
                alert.fired_count += 1
                self._deliver(evt)
        self._history.extend(events)
        return events

    def _evaluate_one(self, alert: Alert, tick: Any) -> AlertEvent | None:
        spec = alert.spec
        if isinstance(spec, PriceThresholdSpec):
            return self._eval_price(alert, spec, tick)
        if isinstance(spec, PercentChangeSpec):
            return self._eval_pct(alert, spec, tick)
        if isinstance(spec, VolumeSpikeSpec):
            return self._eval_volume(alert, spec, tick)
        return None

    def _eval_price(self, alert, spec: PriceThresholdSpec, tick):
        quote = tick.quotes.get(spec.symbol)
        if quote is None:
            return None
        price = Decimal(str(quote.price))
        cur = "above" if price > spec.price else ("below" if price < spec.price else "equal")
        state = self._price_state.setdefault(alert.id, _PriceState())
        prior = state.last_side
        state.last_side = cur
        if prior is None or prior == cur:
            return None
        if spec.crosses == "up" and prior == "below":
            return self._make_event(alert, tick,
                                    condition=f"price {price} crossed above {spec.price}",
                                    context={"price": str(price), "threshold": str(spec.price)})
        if spec.crosses == "down" and prior == "above":
            return self._make_event(alert, tick,
                                    condition=f"price {price} crossed below {spec.price}",
                                    context={"price": str(price), "threshold": str(spec.price)})
        return None

    def _eval_pct(self, alert, spec: PercentChangeSpec, tick):
        quote = tick.quotes.get(spec.symbol)
        if quote is None:
            return None
        if spec.window != "session":
            # 1h / 5m bar-lookback windows require bar-history — deferred to Phase 5
            return None
        change_pct = float(quote.change_pct)
        if abs(change_pct) < spec.threshold_pct:
            return None
        return self._make_event(
            alert, tick,
            condition=f"|change_pct| {change_pct:.2f}% >= threshold {spec.threshold_pct}%",
            context={"change_pct": change_pct, "threshold_pct": spec.threshold_pct},
        )

    def _eval_volume(self, alert, spec: VolumeSpikeSpec, tick):
        bars = tick.bars_recent.get(spec.symbol) or []
        if len(bars) < spec.avg_window + 1:
            return None
        history = bars[-(spec.avg_window + 1):-1]
        current = bars[-1]
        avg = sum(b.volume for b in history) / max(len(history), 1)
        if avg <= 0:
            return None
        ratio = current.volume / avg
        if ratio < spec.ratio_vs_avg:
            return None
        return self._make_event(
            alert, tick,
            condition=f"volume {current.volume} = {ratio:.2f}x avg({int(avg)}) >= {spec.ratio_vs_avg}x",
            context={"current_volume": current.volume, "avg_volume": avg, "ratio": ratio},
        )

    def _make_event(self, alert: Alert, tick: Any, *, condition: str, context: dict) -> AlertEvent:
        return AlertEvent(
            alert_id=alert.id,
            ts=getattr(tick, "ts", datetime.now(timezone.utc)),
            symbol=alert.spec.symbol,
            condition=condition,
            context=context,
        )

    def _deliver(self, event: AlertEvent) -> None:
        """NG7: journal always (when bound), agent context only when bound.
        Anything else here needs a PRD amendment first."""
        if self.journal_write is not None:
            from openbb_fmp_trading.models.session_state import JournalEvent
            self.journal_write(JournalEvent(
                ts=event.ts, session_id=self.session_id, event_type="alert",
                payload={
                    "alert_id": event.alert_id, "symbol": event.symbol,
                    "condition": event.condition, "context": event.context,
                },
            ))
        if self.agent_notify is not None:
            self.agent_notify(event)
```

- [ ] **Step 3: Run tests + commit**

```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_alert_manager.py -q
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/architecture/test_alert_delivery_ng7.py -q
```
Expected: `~14 passed`; NG7 still green (no forbidden imports).

```
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/alert_manager.py openbb_platform/extensions/fmp_trading/tests/unit/test_alert_manager.py
git commit -m "feat(fmp_trading): AlertManager v1 — 3 spec types + NG7 dual-sink delivery (P4.2)

Session-scoped registry; discriminated dispatch on AlertSpec.kind; pure evaluate()
+ internal _deliver() to journal + optional agent sink. NO external delivery.
1h/5m percent-change windows raise no-op (deferred to Phase 5 bar-history).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: `alert_router.py` — obb.fmp_trading.alert.*  (P4.3a)

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_alert_router.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/router/alert_router.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/router/__init__.py` (re-export)
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py` (mount at `/alert`)

**Consumes:** `AlertManager` from Task 4.
**Produces:**
- `obb.fmp_trading.alert.create(kind, symbol, ...) → OBBject[Alert]` (bare OBBject!)
- `obb.fmp_trading.alert.list_alerts(active_only) → OBBject[list[Alert]]` (renamed to avoid Python `list` collision)
- `obb.fmp_trading.alert.delete(alert_id) → OBBject`
- `obb.fmp_trading.alert.evaluate(tick_dict) → OBBject[list[AlertEvent]]` (mainly for external clients / testing)
- `obb.fmp_trading.alert.history() → OBBject[list[AlertEvent]]`
- `bind_session(session_id, journal_write, agent_notify) → AlertManager` (called by IntradaySession)
- `reset_manager_for_tests()` (test-only helper)

- [ ] **Step 1: Router tests** (3-4 tests: create round-trip, list, delete). See Phase 0 plan for pattern.

- [ ] **Step 2: Implement `alert_router.py`** (module-level `_manager`, all commands return bare `OBBject`, `_build_spec()` helper dispatches on `kind` argument).

- [ ] **Step 3: Re-export from `router/__init__.py`** and **mount at `/alert`** in `fmp_trading_router.py`.

- [ ] **Step 4: Rebuild + codegen probe + tests green.**

- [ ] **Step 5: Commit**
```
git commit -m "feat(fmp_trading): alert_router — obb.fmp_trading.alert.* (P4.3a)

Five bare-OBBject commands mounted at /alert. Module-level AlertManager
singleton bound per session via bind_session(session_id, journal_write,
agent_notify) — IntradaySession (Phase 2) invokes bind_session at session
start. reset_manager_for_tests() for offline test isolation. Codegen-safe:
no OBBject[Model]. list_alerts avoids collision with Python builtin.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: CLI `alert_cmd.py` — openbb-daytrade alert {create,list,delete}  (P4.3b)

**Files:**
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/test_alert_cli.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli/alert_cmd.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli/main.py` (register `alert` subparser)

**Consumes:** `AlertManager` via `_manager` singleton in `router/alert_router.py`.
**Produces:** three subcommands (create, list, delete). Exit code 0 on success, 1 on validation error.

- [ ] **Step 1: CLI test** — smoke create (all 3 spec kinds), list, delete round-trip, bad-kind error path.

- [ ] **Step 2: Implement `cli/alert_cmd.py`** — argparse subparser with `--symbol`, `--type {price,pct,volume}`, `--up/--down/--threshold/--window/--ratio/--avg-window`. Handles all 3 AlertSpec kinds. Returns nonzero on validation error.

- [ ] **Step 3: Wire into `cli/main.py`** — `add_alert_subparser(sub)` next to existing `doctor` subparser.

- [ ] **Step 4: Run tests + smoke CLI:**
```
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_alert_cli.py -q
.venv_win\Scripts\openbb-daytrade alert create --symbol AAPL --type price --up 180
.venv_win\Scripts\openbb-daytrade alert list
```
Expected: `~4 passed`; CLI prints `created <id> on AAPL: price_threshold` then a listing.

- [ ] **Step 5: Commit**
```
git commit -m "feat(fmp_trading): openbb-daytrade alert {create,list,delete} CLI (P4.3b)

argparse subcommands wired into existing openbb-daytrade CLI, sharing the
module-level AlertManager singleton with the router.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Threshold-cross matrix + NG7 delivery invariants (P4.4)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_alert_matrix.py`

Task 4 covered CRUD + one happy-path fire per spec. Task 7 hardens the matrix: for every spec, exhaustive threshold-cross cases via `parametrize`, plus dedicated NG7 delivery-invariant assertions.

- [ ] **Step 1: Write parametrized matrix tests**

```python
"""Threshold-cross matrix (P4.4) — comprehensive fire/no-fire coverage per spec kind."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from openbb_fmp_trading.core.alert_manager import AlertManager
from openbb_fmp_trading.models.alert import (
    AlertEvent, PercentChangeSpec, PriceThresholdSpec, VolumeSpikeSpec,
)
from openbb_fmp_trading.models.session_state import JournalEvent


NOW = datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)


def _quote(symbol, price, ts=NOW, change_pct=0.0):
    q = MagicMock(symbol=symbol, price=Decimal(str(price)),
                  change=Decimal("0"), volume=100, timestamp=ts)
    q.change_pct = change_pct
    return q


def _bar(symbol, ts, volume):
    return MagicMock(symbol=symbol, ts=ts, volume=int(volume))


def _tick(ts, quotes, bars=None):
    return MagicMock(ts=ts, quotes=quotes, bars_recent=bars or {})


# --------------------------- Price threshold matrix ---------------------------

@pytest.mark.parametrize(
    "prev_price,curr_price,crosses,should_fire",
    [
        ("179.00", "179.50", "up",   False),  # below → below
        ("179.00", "180.50", "up",   True),   # below → above
        ("180.00", "180.50", "up",   False),  # touch  → above (already crossed)
        ("181.00", "180.50", "down", False),  # above → above
        ("181.00", "179.50", "down", True),   # above → below
        ("180.00", "179.50", "down", False),  # touch  → below (already crossed)
    ],
)
def test_price_threshold_matrix(prev_price, curr_price, crosses, should_fire):
    mgr = AlertManager()
    mgr.create(PriceThresholdSpec(symbol="AAPL", crosses=crosses, price=Decimal("180")))
    mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", prev_price)}))
    events = mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", curr_price)}))
    assert bool(events) is should_fire


# --------------------------- Percent-change matrix ----------------------------

@pytest.mark.parametrize(
    "change_pct,threshold_pct,should_fire",
    [
        (4.99, 5.0, False),
        (5.00, 5.0, True),
        (6.00, 5.0, True),
        (-4.99, 5.0, False),
        (-5.00, 5.0, True),
        (-7.00, 5.0, True),
    ],
)
def test_percent_change_matrix(change_pct, threshold_pct, should_fire):
    mgr = AlertManager()
    mgr.create(PercentChangeSpec(symbol="TSLA", threshold_pct=threshold_pct, window="session"))
    events = mgr.evaluate(_tick(NOW, {"TSLA": _quote("TSLA", "210", change_pct=change_pct)}))
    assert bool(events) is should_fire


# --------------------------- Volume-spike matrix ------------------------------

@pytest.mark.parametrize(
    "avg_volume,current_volume,ratio_threshold,should_fire",
    [
        (1_000_000, 2_999_999, 3.0, False),
        (1_000_000, 3_000_000, 3.0, True),
        (1_000_000, 5_000_000, 3.0, True),
        (1_000_000,   500_000, 3.0, False),
    ],
)
def test_volume_spike_matrix(avg_volume, current_volume, ratio_threshold, should_fire):
    mgr = AlertManager()
    mgr.create(VolumeSpikeSpec(symbol="AAPL", ratio_vs_avg=ratio_threshold, avg_window=5))
    for i in range(5):
        t = NOW + timedelta(minutes=5 * i)
        mgr.evaluate(_tick(t, {"AAPL": _quote("AAPL", "100", t)},
                          bars={"AAPL": [_bar("AAPL", t, avg_volume)]}))
    t = NOW + timedelta(minutes=30)
    events = mgr.evaluate(_tick(t, {"AAPL": _quote("AAPL", "100", t)},
                                bars={"AAPL": [_bar("AAPL", t, current_volume)]}))
    assert bool(events) is should_fire


# --------------------------- NG7 delivery invariants --------------------------

class TestNG7DeliveryInvariants:
    """The two-and-only-two sink cap — journal + agent context. Nothing else."""

    def test_journal_events_carry_alert_payload_verbatim(self):
        written: list[JournalEvent] = []
        mgr = AlertManager(session_id="test-session", journal_write=written.append)
        mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
        mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
        mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
        assert len(written) == 1
        ev = written[0]
        assert ev.event_type == "alert"
        assert ev.session_id == "test-session"
        assert ev.payload["symbol"] == "AAPL"
        assert "condition" in ev.payload

    def test_agent_notify_receives_alertevent_not_dict(self):
        ctx: list = []
        mgr = AlertManager(agent_notify=ctx.append)
        mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
        mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
        mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
        assert len(ctx) == 1 and isinstance(ctx[0], AlertEvent)

    def test_manager_has_no_external_delivery_attrs(self):
        forbidden = {"webhook", "email_to", "sms_to", "push_endpoint", "http_url", "smtp_host"}
        instance_attrs = set(vars(AlertManager()).keys())
        assert not (instance_attrs & forbidden)

    def test_history_matches_journal_writes_count(self):
        written: list[JournalEvent] = []
        mgr = AlertManager(journal_write=written.append)
        mgr.create(PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")))
        mgr.evaluate(_tick(NOW, {"AAPL": _quote("AAPL", "179")}))
        mgr.evaluate(_tick(NOW + timedelta(seconds=5), {"AAPL": _quote("AAPL", "181")}))
        assert len(mgr.history()) == len(written) == 1
```

- [ ] **Step 2: Run + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_alert_matrix.py -v`
Expected: ~20 passed (6 price + 6 pct + 4 volume + 4 NG7).

```
git add openbb_platform/extensions/fmp_trading/tests/unit/test_alert_matrix.py
git commit -m "test(fmp_trading): threshold-cross matrix + NG7 delivery invariants (P4.4)

Parametrized matrices per spec kind (6+6+4 cases) plus NG7 invariant class:
* Journal events carry AlertEvent payload verbatim with event_type=alert
* Agent-notify receives AlertEvent instance (not dict)
* Manager has no external-delivery attrs (webhook/email/sms/push/http/smtp)
* history() length matches journal_write invocation count

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Final acceptance gates — lint, rebuild, whole-suite green

- [ ] **Step 1: Ruff clean** — `ruff check openbb_platform/extensions/fmp_trading` → `All checks passed!`
- [ ] **Step 2: Full Phase-4 suite** — unit + architecture — `~40+ tests passed`
- [ ] **Step 3: Rebuild + codegen probe** — `obb.fmp_trading.market_snapshot` + `obb.fmp_trading.alert.*` callable; `'OBBject[' not in fmp_trading*.py`
- [ ] **Step 4: Regression check** — Phase 0/1 tests still green; techtrade suite untouched
- [ ] **Step 5: Generated files NOT staged** — `git restore --staged openbb_platform/core/openbb/package/` if any appear
- [ ] **Step 6: Report status; do NOT push without user confirmation**

Summarize: 8 commits landed (NG7 guardrail + snapshot builder + snapshot router + AlertManager + alert router + CLI + matrix + final gate). Extension surface: `obb.fmp_trading.market_snapshot` + `obb.fmp_trading.alert.{create,list_alerts,delete,evaluate,history}` + `openbb-daytrade alert {create,list,delete}`. NG7 architecturally enforced. Await user approval before push.

---

## Self-Review Notes

**PRD §10 Phase 4 coverage:**
- **P4.1** `market_snapshot` command + `MoverRow` + `MarketSnapshot` models → Task 2 (builder) + Task 3 (router). Models re-used from Phase 1 §6.2.2. ✓
- **P4.2** AlertManager v1 with 3 spec types + session-log + agent-context delivery → Task 4 (manager) + Task 1 (NG7 architecture guardrail). ✓
- **P4.3** `alert.*` sub-router + CLI subcommands → Task 5 (router) + Task 6 (CLI). ✓
- **P4.4** Alert eval tests × threshold-cross cases + NG7 delivery invariants → Task 7. ✓

**NG7 posture — enforced in depth:**
1. **AST guardrail (Task 1)** — build fails if `alert_manager.py` imports any of `smtplib`, `requests`, `httpx`, `urllib.request`, `twilio`, `aiohttp`, `email.mime`, `boto3`, `pushover`, `pusher`.
2. **Attribute audit (Task 7)** — instance vars must not include `webhook / email_to / sms_to / push_endpoint / http_url / smtp_host`.
3. **Sink discipline (Task 4)** — only two Callable parameters (`journal_write`, `agent_notify`); no other exit paths for `AlertEvent`.
4. **PRD §1.3 follow-up #2** — future external delivery is a v2 concern with its own PR, credential store, and user opt-in.

**Global constraints respected:**
- Every router command annotates bare `OBBject` — verified in Task 3 Step 4, Task 5 Step 4, Task 8 Step 3.
- Every `obb.equity.*` call in `market_snapshot.py` and `snapshot_router.py` passes `provider="fmp_cached"`. Phase 0 grep test catches regressions.
- `Decimal` for every price/change/threshold field.
- `AlertSpec` used as the Phase 1 discriminated union — no re-declaration.

**Deferred (do not implement here):**
- External delivery (webhook / email / SMS / push) → v2 (NG7).
- Pattern-based alerts (breakout, wedge, ML) → v2 (PRD §1.3 #3).
- Bar-history percent-change windows (`"1h"`, `"5m"`) → Phase 5 (v1 supports `"session"` only; other windows return `None` silently).
- Auto-wiring `bind_session` into `IntradaySession.run()` → Phase 2 owner (tick loop lands there).
- Alert history export into end-of-day workbook → Phase 5's `xlsx_renderer.py` reads `event_type=="alert"` from journal; nothing extra here.

**Interface contracts (for later phases):**
- `AlertManager.__init__(session_id, journal_write, agent_notify)` — Phase 2's `IntradaySession` calls `bind_session(...)` at start; Phase 3's `PostCloseAgentTurn` reads `history()` for context.
- `router.alert_router.bind_session(session_id, journal_write=..., agent_notify=...) → AlertManager` — returns the freshly-bound manager so caller has an explicit handle.
- `MarketSnapshot.model_dump(mode="json")` produces plain-JSON `results` that survives the OBBject envelope round-trip (Task 3 test verifies).
