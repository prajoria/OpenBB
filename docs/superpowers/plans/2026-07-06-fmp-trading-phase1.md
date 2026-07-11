# Phase 1: fmp_trading Foundations — Scaffold, Models, RiskManager, Journal, Bandwidth, Doctor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task ends with a green pytest + a self-contained commit; do not batch commits across tasks.

**Goal:** Land the pre-tick-loop foundations of `openbb-fmp-trading` — a green-building extension skeleton, the full v1 Pydantic model surface (§6), the eight-gate `RiskManager` (§8), an NDJSON `SessionJournal`, a month-persistent `BandwidthMeter`, and the `doctor()` diagnostic — so Phase 2's `IntradaySession` tick loop can be wired in without touching correctness plumbing.

**Architecture:** A pure-compute OpenBB extension (no data provider) mirroring the on-disk shape of `openbb-techtrade`: a top-level `fmp_trading_router.py` that lazily includes sub-routers, `models/` split by responsibility per PRD §6.4, and a `core/` package holding `RiskManager`, `SessionJournal`, `BandwidthMeter`. No tick loop, no PaperBroker wiring, no agent turns — those land in P2/P3. Every command in this phase returns bare `OBBject` for codegen safety.

**Tech Stack:** Python 3.10-3.13, Poetry-style `pyproject.toml`, `openbb-core` extension entry points, Pydantic v2, `Decimal` for money/quantities, `exchange_calendars` for clock decisions, `pytest`. Env: `.venv_win`.

---

## Global Constraints

Copy-forward from PRD §2.2. Every task in this phase must respect these.

- **P1 — Deterministic signal core, agent is optional shell.** Models, RiskManager, Journal, and BandwidthMeter are pure — no LLM code lives in `core/` or `models/`.
- **P2 — `Decimal` for money and share counts; no float drift.** Every price, quantity, notional, drawdown-dollar field is `Decimal`. Only ratios/percentages (`day_dd_pct`, `change_pct`) may be `float`.
- **P3 — No look-ahead.** Not exercised until P2's tick loop, but the model shapes (`IntradayBar.ts` = bar-start, `Fill` carries a distinct fill-time) must not conflate signal-time with fill-time.
- **P5 — Every clock decision uses `exchange_calendars`.** `RiskManager.G1 flat_by_close` and `doctor()` MUST route today/now through the exchange calendar — no naive `datetime.now()`.
- **P7 — RiskManager veto is the source of truth on trade admission.** In Phase 1 we ship the class + its 8 gates + tests; the chokepoint enforcement CI test (§8.6) is a P2 deliverable but every gate here must be independently testable with fixture data.

### Critical Design Constraint (codegen safety) — READ FIRST

The static package builder in `openbb_core/app/static/package_builder.py` has a codegen bug identical to the one hit by the merged `backtest` extension: a router command whose return type is annotated `OBBject[SomeModel]` renders the model's bare `__name__` into the generated `openbb/package/fmp_trading.py` **without emitting a matching import**. Result: `import openbb` succeeds, but the first access to `obb.fmp_trading.*` raises `NameError: name 'SomeModel' is not defined`.

Root cause verified in `build_func_returns` (line ~1650): a bare `OBBject` subclass renders as the string `"OBBject"` — always valid, always importable. Every working core extension (equity, etf, crypto, techtrade) uses bare `OBBject` in its generated module.

**RULE for every command in this scaffold — Phase 1 through Phase 6:** annotate the return type as bare `OBBject:`, never `OBBject[SomeModel]`. Typed return models are still declared under `models/` and are still used inside the command body (`return OBBject(results=SomeModel(...))`) — only the *annotation* on the router function is bare. This is the same rule techtrade adopted; see `docs/superpowers/plans/2026-06-13-techtrade-scaffold.md` (Critical Design Constraint).

**Branch:** Work directly on `fmp_trading`. No worktree.

---

## File Structure (Phase 1)

All paths under `openbb_platform/extensions/fmp_trading/`:

| File | Responsibility |
|---|---|
| `openbb_fmp_trading/__init__.py` | Package marker + `__version__ = "0.1.0"`. |
| `openbb_fmp_trading/py.typed` | PEP 561 typing marker (empty). |
| `openbb_fmp_trading/fmp_trading_router.py` | Top-level `Router`; lazy sub-router includes; defines `doctor` command (bare `OBBject`). |
| `openbb_fmp_trading/models/__init__.py` | Re-exports all public models per §6.4. |
| `openbb_fmp_trading/models/config.py` | `DailyConfig`, `RiskConfig`. |
| `openbb_fmp_trading/models/plan.py` | `DailyPlan`. |
| `openbb_fmp_trading/models/snapshot.py` | `MoverRow`, `MarketSnapshot`. |
| `openbb_fmp_trading/models/market_data.py` | `IntradayBar`, `Quote`, `AftermarketQuote`, `AftermarketTrade`, `SessionStatus`, `IndicatorValue`. |
| `openbb_fmp_trading/models/alert.py` | `AlertSpec` discriminated union + concrete specs + `Alert`, `AlertEvent`. |
| `openbb_fmp_trading/models/session_state.py` | `TickData`, `PnLSnapshot`, `BandwidthState`, `RiskState`, `JournalEvent`, `TradeDecision`. |
| `openbb_fmp_trading/models/results.py` | `SessionResult`, `HealthReport`, `ReportManifest`. |
| `openbb_fmp_trading/core/__init__.py` | Empty package marker. |
| `openbb_fmp_trading/core/risk_manager.py` | `RiskManager` + `TradeDecision` factory helpers; 8 gates. |
| `openbb_fmp_trading/core/journal.py` | `SessionJournal` NDJSON writer + reader (`replay_events`). |
| `openbb_fmp_trading/core/bandwidth.py` | `BandwidthMeter` + month-persistent state (`~/.openbb_platform/fmp_trading/bandwidth.json`). |
| `openbb_fmp_trading/core/doctor.py` | `run_doctor() -> HealthReport` — used by both the router command and the CLI. |
| `openbb_fmp_trading/cli/__init__.py` | CLI package marker. |
| `openbb_fmp_trading/cli/main.py` | `openbb-daytrade` Typer/argparse entry — Phase 1 supports `doctor` only. |
| `pyproject.toml` | Package metadata + `openbb_core_extension` entry point + `openbb-daytrade` script entry. |
| `README.md` | One-paragraph extension description. |
| `tests/__init__.py`, `tests/unit/__init__.py` | Test package markers. |
| `tests/unit/test_scaffolding.py` | Package + router import; `doctor` command present. |
| `tests/unit/test_models_roundtrip.py` | Every model round-trips via `model_dump_json` → `model_validate_json`. |
| `tests/unit/test_risk_manager.py` | 8 tests — one per gate. |
| `tests/unit/test_journal.py` | Writer append + reader replay + partial-line-recovery test. |
| `tests/unit/test_bandwidth.py` | Charge accounting, month rollover, conservation-mode threshold. |
| `tests/unit/test_doctor.py` | `HealthReport` fields populated; missing extras degrade gracefully. |

Modified outside the extension:
- `openbb_platform/dev_install.py` — add the editable path entry.

> **Out of scope for Phase 1** (belong to later phases; do NOT implement here):
> tick loop (`IntradaySession`), `PaperBroker` wiring (P2), agent turns / MCP (P3),
> `market_snapshot` command / `AlertManager` runtime evaluator (P4), reporter (P5),
> the 6 new `openbb_fmp` fetchers (P0 — must be green before P2, but not required for P1
> since Phase 1 makes no live FMP calls).

---

## Task 1 (P1.1): Extension scaffold + green build + doctor stub route

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/py.typed`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py`
- Create: `openbb_platform/extensions/fmp_trading/pyproject.toml`
- Create: `openbb_platform/extensions/fmp_trading/README.md`
- Create: `openbb_platform/extensions/fmp_trading/tests/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_scaffolding.py`
- Modify: `openbb_platform/dev_install.py`

### Interfaces
- **Consumes:** `openbb_core.app.router.Router`, `openbb_core.app.model.obbject.OBBject`.
- **Produces:** `openbb_fmp_trading.fmp_trading_router.router` (entry point target); `obb.fmp_trading.doctor()` reachable (returns a stub `OBBject` — real payload lands in Task 6).

- [ ] **Step 1: Write the failing scaffolding test**

Create `tests/unit/test_scaffolding.py`:

```python
"""Unit tests for fmp_trading scaffolding: package + router imports, command surface."""

from __future__ import annotations


def test_package_imports():
    import openbb_fmp_trading

    assert openbb_fmp_trading.__version__ == "0.1.0"


def test_router_exposes_doctor():
    from openbb_fmp_trading.fmp_trading_router import router

    paths = {getattr(route, "path", None) for route in router.api_router.routes}
    assert "/doctor" in paths
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_scaffolding.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_fmp_trading'`.

- [ ] **Step 2: Create the package + typing markers**

`openbb_fmp_trading/__init__.py`:

```python
"""OpenBB fmp-trading extension — intraday day-trading automation on fmp_cached."""

__version__ = "0.1.0"
```

Create empty `openbb_fmp_trading/py.typed` (0 bytes).
Create `tests/__init__.py` and `tests/unit/__init__.py` each with a single-line docstring:

```python
"""fmp_trading extension test suite."""
```

- [ ] **Step 3: Create the top-level router with a stub `doctor` command**

`openbb_fmp_trading/fmp_trading_router.py`:

```python
"""Top-level fmp_trading router.

Assembles the public ``obb.fmp_trading.*`` surface. Sub-routers (session, snapshot,
data, alert, session_state, report) are attached lazily inside
:func:`_include_subrouters` as each is implemented per PRD §10 (P2 tick loop, P3
agent turns, P4 alerts, P5 report). Missing sub-routers are skipped so the extension
imports cleanly during incremental development.

The ``doctor`` command returns a bare ``OBBject`` (no parametrized model) so the
static package builder renders a valid, importable return annotation — see the
Critical Design Constraint in the Phase 1 plan and ``package_builder.build_func_returns``.
"""

from __future__ import annotations

from importlib import import_module

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(
    prefix="",
    description="Intraday day-trading automation on fmp_cached (deterministic core).",
)


def _include_subrouters() -> None:
    for module_path, attr in (
        ("openbb_fmp_trading.routers.session_router", "router"),
        ("openbb_fmp_trading.routers.snapshot_router", "router"),
        ("openbb_fmp_trading.routers.data_router", "router"),
        ("openbb_fmp_trading.routers.alert_router", "router"),
        ("openbb_fmp_trading.routers.session_state_router", "router"),
        ("openbb_fmp_trading.routers.report_router", "router"),
    ):
        try:
            module = import_module(module_path)
        except ImportError:
            continue
        router.include_router(getattr(module, attr))


_include_subrouters()


@router.command(methods=["GET"])
def doctor() -> OBBject:
    """Return an fmp_trading health report (stub — populated in Task 6)."""
    return OBBject(results={"status": "stub", "phase": "P1.1"})
```

- [ ] **Step 4: Create `pyproject.toml` + `README.md`**

`pyproject.toml`:

```toml
[tool.poetry]
name = "openbb-fmp-trading"
version = "0.1.0"
description = "Intraday day-trading automation extension for OpenBB (fmp_cached)."
authors = ["Trading Automation working group"]
license = "AGPL-3.0-only"
readme = "README.md"
packages = [{ include = "openbb_fmp_trading" }]

[tool.poetry.dependencies]
python = ">=3.10,<3.14"
openbb-core = "^1.6.10"
openbb-techtrade = "^0.1.0"
pandas = "*"
numpy = "*"
exchange-calendars = "*"
pydantic = "^2.0"

[tool.poetry.extras]
# agent      -> optional LLM backends for pre/post-close turns (P3)
# xlsxwriter -> richer Excel engine, shared with techtrade[xlsxwriter] (P5)
# validation -> backtest bridge (P6)

[tool.poetry.scripts]
openbb-daytrade = "openbb_fmp_trading.cli.main:main"

[tool.poetry.plugins."openbb_core_extension"]
fmp_trading = "openbb_fmp_trading.fmp_trading_router:router"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

`README.md`:

```markdown
# openbb-fmp-trading

Intraday day-trading automation extension for the OpenBB Platform.

Ships a deterministic execution core with optional agent-driven pre-open discovery
and post-close review. Composes on `openbb-techtrade` unchanged; talks only to
`fmp_cached` (never raw `fmp` in application code).

Status: **Phase 1 — Foundations** (scaffold, models, RiskManager, Journal,
BandwidthMeter, doctor). See `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
for the full PRD.
```

- [ ] **Step 5: Add to `dev_install.py`**

In `openbb_platform/dev_install.py`, locate the `LOCAL_DEPS` block that already lists `openbb-techtrade`. Add the new line immediately after the techtrade line, matching indentation:

```
openbb-fmp-trading = { path = "./extensions/fmp_trading", develop = true }
```

- [ ] **Step 6: Editable-install + rebuild + prove namespace resolves**

```bash
.venv_win\Scripts\python.exe -m pip install -e openbb_platform/extensions/fmp_trading
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print('has fmp_trading:', hasattr(obb, 'fmp_trading')); print(obb.fmp_trading.doctor().results)"
```

Expected: `Successfully installed openbb-fmp-trading-0.1.0`; `openbb.build()` exit 0 with `fmp_trading@0.1.0` listed; final line prints `has fmp_trading: True` and `{'status': 'stub', 'phase': 'P1.1'}`. This proves we avoided the `OBBject[Model]` NameError trap.

- [ ] **Step 7: Run scaffolding tests + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_scaffolding.py -q
git status --porcelain openbb_platform/core/openbb/package/   # confirm generated file NOT staged
git restore --staged openbb_platform/core/openbb/package/ 2>/dev/null || true
git add openbb_platform/extensions/fmp_trading openbb_platform/dev_install.py
git commit -m "feat(fmp_trading): P1.1 scaffold extension + green build + doctor stub

Scaffold openbb-fmp-trading per PRD §3.1: package, top-level router with lazy
sub-router includes, a stub doctor command returning bare OBBject (codegen-safe
per the backtest OBBject[Model] NameError trap), pyproject entry point,
dev_install wiring.

Acceptance (P1.1): openbb.build() green; obb.fmp_trading resolves; doctor() runs;
2 scaffolding tests pass.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: `2 passed`.

---

## Task 2 (P1.2): Core data models + Pydantic round-trip tests

**Files:**
- Create: `openbb_fmp_trading/models/__init__.py`
- Create: `openbb_fmp_trading/models/config.py`
- Create: `openbb_fmp_trading/models/plan.py`
- Create: `openbb_fmp_trading/models/snapshot.py`
- Create: `openbb_fmp_trading/models/market_data.py`
- Create: `openbb_fmp_trading/models/alert.py`
- Create: `openbb_fmp_trading/models/session_state.py`
- Create: `openbb_fmp_trading/models/results.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_models_roundtrip.py`

### Interfaces
- **Consumes:** `openbb_core.provider.abstract.data.Data` (base class); `pydantic.Field`, `Annotated`, `Decimal`.
- **Produces:** every model listed in PRD §6.2, importable from `openbb_fmp_trading.models`.

- [ ] **Step 1: Write the failing round-trip test**

Create `tests/unit/test_models_roundtrip.py`. The test uses a parameterised fixture set covering every model with realistic values; JSON serialize → deserialize → equality holds.

```python
"""Round-trip: every model.model_dump_json() → model_validate_json() must equal the original."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from openbb_fmp_trading.models import (
    Alert,
    AlertEvent,
    AftermarketQuote,
    AftermarketTrade,
    BandwidthState,
    DailyConfig,
    DailyPlan,
    HealthReport,
    IndicatorValue,
    IntradayBar,
    JournalEvent,
    MarketSnapshot,
    MoverRow,
    PercentChangeSpec,
    PnLSnapshot,
    PriceThresholdSpec,
    Quote,
    ReportManifest,
    RiskConfig,
    RiskState,
    SessionResult,
    SessionStatus,
    TickData,
    TradeDecision,
    VolumeSpikeSpec,
)

_NOW = datetime(2026, 7, 6, 14, 30, tzinfo=timezone.utc)


def _samples():
    """Yield (name, instance) for every model under test."""
    risk = RiskConfig()
    yield "RiskConfig", risk
    yield "DailyConfig", DailyConfig(
        starting_equity=Decimal("100000"), default_risk=risk
    )
    yield "DailyPlan", DailyPlan(
        as_of=_NOW, date=date(2026, 7, 6), watchlist=["AAPL", "MSFT"],
        preset="intraday_momentum", alerts=[], session_risk=risk,
        thesis="test", agent_backend="none",
    )
    yield "MoverRow", MoverRow(
        symbol="AAPL", type="gainer", name="Apple Inc.", price=Decimal("180.00"),
        change=Decimal("2.50"), change_pct=1.4, volume=50_000_000,
    )
    yield "MarketSnapshot", MarketSnapshot(
        as_of=_NOW, movers=[], sentiment_ratio=1.2, top_gainer=None, top_loser=None,
    )
    yield "IntradayBar", IntradayBar(
        symbol="AAPL", interval="5min", ts=_NOW,
        open=Decimal("180"), high=Decimal("181"), low=Decimal("179.5"),
        close=Decimal("180.75"), volume=1_000_000,
    )
    yield "Quote", Quote(
        symbol="AAPL", price=Decimal("180.75"), change=Decimal("0.75"),
        change_pct=0.42, volume=50_000_000, timestamp=_NOW,
    )
    yield "AftermarketQuote", AftermarketQuote(
        symbol="AAPL", price=Decimal("181"), bid=Decimal("180.95"),
        ask=Decimal("181.05"), bid_size=100, ask_size=200, volume=10_000, timestamp=_NOW,
    )
    yield "AftermarketTrade", AftermarketTrade(
        symbol="AAPL", price=Decimal("181"), size=100, timestamp=_NOW,
    )
    yield "SessionStatus", SessionStatus(
        exchange="NASDAQ", is_market_open=True, is_pre_market=False,
        is_after_market=False, is_early_close_day=False, next_open=_NOW, next_close=_NOW,
    )
    yield "IndicatorValue", IndicatorValue(
        symbol="AAPL", indicator="RSI", ts=_NOW, value=55.2,
        period_length=14, timeframe="5min",
    )
    for spec in (
        PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")),
        PercentChangeSpec(symbol="AAPL", threshold_pct=5.0, window="session"),
        VolumeSpikeSpec(symbol="AAPL", ratio_vs_avg=3.0),
    ):
        yield f"AlertSpec::{spec.kind}", spec
    yield "Alert", Alert(
        id="a1", spec=PriceThresholdSpec(symbol="AAPL", crosses="up", price=Decimal("180")),
        created_at=_NOW,
    )
    yield "AlertEvent", AlertEvent(
        alert_id="a1", ts=_NOW, symbol="AAPL", condition="price > 180", context={"p": "180.5"},
    )
    yield "TickData", TickData(ts=_NOW, quotes={}, bars_recent={},
        session_status=SessionStatus(
            exchange="NASDAQ", is_market_open=True, is_pre_market=False,
            is_after_market=False, is_early_close_day=False, next_open=_NOW, next_close=_NOW,
        ))
    yield "PnLSnapshot", PnLSnapshot(
        ts=_NOW, realized_pnl=Decimal("100"), unrealized_pnl=Decimal("50"),
        day_pnl=Decimal("150"), day_dd_pct=0.0, positions_open=0, positions_closed=0,
    )
    yield "BandwidthState", BandwidthState(
        month_used_bytes=1_000_000, month_budget_bytes=50 * 1024**3,
        month_used_pct=0.002, mode="normal", session_used_bytes=100_000,
    )
    yield "RiskState", RiskState(
        ts=_NOW, gates_active=[], gates_tripped_today=[], cooldowns={},
        flat_by_close_window_open=False, day_dd_pct=0.0,
        open_position_count=0, max_open_positions=5,
    )
    yield "JournalEvent", JournalEvent(
        ts=_NOW, session_id="s1", event_type="tick", payload={"n": 1},
    )
    yield "TradeDecision::approved", TradeDecision(verdict="APPROVED", plan={})
    yield "TradeDecision::rejected", TradeDecision(
        verdict="REJECTED", reason="in cooldown", reason_code="G4",
        gate="per_symbol_cooldown", plan={},
    )
    yield "SessionResult", SessionResult(
        session_id="s1", date=date(2026, 7, 6), exchange="NASDAQ",
        started_at=_NOW, ended_at=_NOW, exit_code=0,
        daily_plan=DailyPlan(
            as_of=_NOW, date=date(2026, 7, 6), watchlist=["AAPL"],
            preset="intraday_momentum", alerts=[], session_risk=risk,
            thesis="t", agent_backend="none",
        ),
        final_pnl=PnLSnapshot(
            ts=_NOW, realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
            day_pnl=Decimal("0"), day_dd_pct=0.0,
            positions_open=0, positions_closed=0,
        ),
        final_bandwidth=BandwidthState(
            month_used_bytes=0, month_budget_bytes=1, month_used_pct=0.0,
            mode="normal", session_used_bytes=0,
        ),
        total_ticks=0, total_signals=0, total_orders=0, total_fills=0,
        total_vetoes=0, total_alerts_fired=0, flat_at_close=True,
        journal_path="/tmp/j.ndjson",
    )
    yield "HealthReport", HealthReport(
        ts=_NOW, fmp_credentials_ok=True, mysql_cache_ok=True,
        exchange_calendars_ok=True, techtrade_version="0.1.0", techtrade_ok=True,
        agent_extra_installed=False, xlsxwriter_extra_installed=False,
        validation_extra_installed=False, bandwidth_remaining_pct=95.0,
        warnings=[], errors=[],
    )
    yield "ReportManifest", ReportManifest(
        session_id="s1", md_path=None, xlsx_path=None, json_path=None,
        included_agent_narrative=False,
    )


@pytest.mark.parametrize("name,instance", list(_samples()), ids=lambda x: x if isinstance(x, str) else "")
def test_roundtrip(name, instance):
    payload = instance.model_dump_json()
    revived = type(instance).model_validate_json(payload)
    assert revived == instance
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_models_roundtrip.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'openbb_fmp_trading.models'`.

- [ ] **Step 2: Create `models/config.py`, `models/plan.py`, `models/snapshot.py`**

Each file inherits from `openbb_core.provider.abstract.data.Data` (which re-exports the base `Data` class extending `pydantic.BaseModel`). Full field lists come from PRD §6.2 — copy verbatim, including defaults. Money and quantities use `Decimal`; timestamps use tz-aware `datetime`; enums use `Literal[...]`; optional fields use `T | None = None`.

Sample skeleton for `config.py`:

```python
"""DailyConfig + RiskConfig — top-level session configuration (PRD §6.2.1)."""

from __future__ import annotations

from decimal import Decimal
from datetime import date
from typing import Literal

from openbb_core.provider.abstract.data import Data


class RiskConfig(Data):
    max_open_positions: int = 5
    day_dd_pct: float = -2.0
    cooldown_after_stopout_min: int = 30
    max_positions_per_sector: int = 2
    max_position_size_pct_equity: float = 10.0
    max_notional_pct_equity: float = 30.0
    flat_by_close_time_et: str = "15:50"


class DailyConfig(Data):
    date: date | None = None
    exchange: Literal["NASDAQ", "NYSE", "AMEX"] = "NASDAQ"
    starting_equity: Decimal
    default_preset: str = "intraday_momentum"
    bandwidth_tier: Literal["premium", "ultimate"] = "premium"
    bandwidth_monthly_bytes: int = 50 * 1024**3
    default_risk: RiskConfig
    agent_backend: Literal["claude", "openai", "none"] = "claude"
    agent_max_watchlist_size: int = 20
    agent_universe_hint: list[str] | None = None
```

`plan.py` implements `DailyPlan` (§6.2.1). `snapshot.py` implements `MoverRow` and `MarketSnapshot` (§6.2.2). Follow the same shape — one Pydantic class per PRD entry.

- [ ] **Step 3: Create `models/market_data.py` + `models/alert.py`**

`market_data.py` bundles the six data classes from §6.2.3 (`IntradayBar`, `Quote`, `AftermarketQuote`, `AftermarketTrade`, `SessionStatus`, `IndicatorValue`). `alert.py` implements the discriminated `AlertSpec` union (§6.2.4):

```python
from typing import Annotated, Literal
from pydantic import Field

AlertSpec = Annotated[
    PriceThresholdSpec | PercentChangeSpec | VolumeSpikeSpec,
    Field(discriminator="kind"),
]
```

Each concrete spec sets `kind: Literal["price_threshold"] = "price_threshold"` etc. `Alert` and `AlertEvent` follow §6.2.4.

- [ ] **Step 4: Create `models/session_state.py` + `models/results.py`**

`session_state.py` implements `TickData`, `PnLSnapshot`, `BandwidthState`, `RiskState`, `JournalEvent`, plus `TradeDecision` (§8.1 — it lives here rather than in a separate module because the RiskManager returns it and journal events reference it). `results.py` implements `SessionResult`, `HealthReport`, `ReportManifest` from §6.2.6.

- [ ] **Step 5: Create `models/__init__.py` — the public re-export surface**

```python
"""Public model surface for openbb-fmp-trading (PRD §6.4)."""

from openbb_fmp_trading.models.alert import (
    Alert, AlertEvent, AlertSpec,
    PercentChangeSpec, PriceThresholdSpec, VolumeSpikeSpec,
)
from openbb_fmp_trading.models.config import DailyConfig, RiskConfig
from openbb_fmp_trading.models.market_data import (
    AftermarketQuote, AftermarketTrade, IndicatorValue, IntradayBar,
    Quote, SessionStatus,
)
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.results import HealthReport, ReportManifest, SessionResult
from openbb_fmp_trading.models.session_state import (
    BandwidthState, JournalEvent, PnLSnapshot, RiskState, TickData, TradeDecision,
)
from openbb_fmp_trading.models.snapshot import MarketSnapshot, MoverRow

__all__ = [
    "Alert", "AlertEvent", "AlertSpec",
    "AftermarketQuote", "AftermarketTrade",
    "BandwidthState", "DailyConfig", "DailyPlan",
    "HealthReport", "IndicatorValue", "IntradayBar", "JournalEvent",
    "MarketSnapshot", "MoverRow", "PercentChangeSpec", "PnLSnapshot",
    "PriceThresholdSpec", "Quote", "ReportManifest", "RiskConfig",
    "RiskState", "SessionResult", "SessionStatus", "TickData",
    "TradeDecision", "VolumeSpikeSpec",
]
```

- [ ] **Step 6: Green the tests + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_models_roundtrip.py -q
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models openbb_platform/extensions/fmp_trading/tests/unit/test_models_roundtrip.py
git commit -m "feat(fmp_trading): P1.2 core data models + round-trip tests

All PRD §6.2 models (config, plan, snapshot, market_data, alert,
session_state, results) with Decimal for money/quantities, tz-aware
datetimes, Literal enums, and a discriminated AlertSpec union.

Round-trip test parametrizes every model and asserts
model_validate_json(model_dump_json(m)) == m.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: `~25 passed`.

---

## Task 3 (P1.3): RiskManager with 8 gates + one test per gate

**Files:**
- Create: `openbb_fmp_trading/core/__init__.py`
- Create: `openbb_fmp_trading/core/risk_manager.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_risk_manager.py`

### Interfaces
- **Consumes:** `RiskConfig`, `RiskState`, `TickData`, `TradeDecision` from `models`; `exchange_calendars` for G1 clock; a `TradePlan` shape stubbed as a `Mapping[str, Any]` (Phase 2 replaces with `openbb_techtrade.models.TradePlan`).
- **Produces:** `RiskManager.propose_trade(plan, tick) -> TradeDecision`; `RiskManager.on_fill(...)`, `RiskManager.on_stopout(...)` hooks for Phase 2.

- [ ] **Step 1: Create `core/__init__.py`**

```python
"""fmp_trading core: RiskManager, SessionJournal, BandwidthMeter, doctor."""
```

- [ ] **Step 2: Implement `core/risk_manager.py`**

Order-sensitive gates; first REJECT wins; every rejection carries `reason_code` ∈ {G1..G8}. Time comparisons route through `exchange_calendars` (P5).

```python
"""RiskManager — 8-gate trade admission (PRD §8).

Every proposed trade funnels through :meth:`RiskManager.propose_trade`.
No path bypasses it — the chokepoint CI test (§8.6) lands in Phase 2
alongside IntradaySession. This phase ships the gate logic + tests only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal
from typing import Any, Mapping

import exchange_calendars as xcals

from openbb_fmp_trading.models import RiskConfig, RiskState, TickData, TradeDecision

TradePlan = Mapping[str, Any]  # Phase 2 replaces with openbb_techtrade.models.TradePlan


@dataclass
class RiskManager:
    config: RiskConfig
    starting_equity: Decimal
    exchange: str = "NASDAQ"
    state: RiskState = field(default_factory=lambda: RiskState(
        ts=datetime.now(timezone.utc),
        gates_active=["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"],
        gates_tripped_today=[], cooldowns={}, flat_by_close_window_open=False,
        day_dd_pct=0.0, open_position_count=0, max_open_positions=5,
    ))
    # Session-scoped ledgers (mutated by IntradaySession callbacks in P2):
    open_positions_by_symbol: dict[str, Decimal] = field(default_factory=dict)  # symbol -> qty
    open_positions_by_sector: dict[str, int] = field(default_factory=dict)
    total_notional: Decimal = Decimal("0")
    day_pnl: Decimal = Decimal("0")

    def propose_trade(self, plan: TradePlan, tick: TickData) -> TradeDecision:
        for gate in (self._g1, self._g2, self._g3, self._g4, self._g5,
                     self._g6, self._g7, self._g8):
            decision = gate(plan, tick)
            if decision is not None:
                self.state.gates_tripped_today = list(
                    {*self.state.gates_tripped_today, decision.reason_code}
                )
                return decision
        return TradeDecision(verdict="APPROVED", plan=dict(plan))

    # ---- G1: flat_by_close ----
    def _g1(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        cutoff_h, cutoff_m = map(int, self.config.flat_by_close_time_et.split(":"))
        cal = xcals.get_calendar(self.exchange)
        now_local = tick.ts.astimezone(cal.tz)
        if now_local.time() >= time(cutoff_h, cutoff_m):
            self.state.flat_by_close_window_open = True
            return TradeDecision(
                verdict="REJECTED",
                reason=f"in flat-by-close window; no new opens after {self.config.flat_by_close_time_et} ET",
                reason_code="G1", gate="flat_by_close", plan=dict(plan),
            )
        return None

    # ---- G2: max_open_positions ----
    def _g2(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        if self.state.open_position_count >= self.config.max_open_positions:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"already at max_open_positions={self.config.max_open_positions}",
                reason_code="G2", gate="max_open_positions", plan=dict(plan),
            )
        return None

    # ---- G3: day_dd_pct_breach ----
    def _g3(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        if self.state.day_dd_pct <= self.config.day_dd_pct:
            return TradeDecision(
                verdict="REJECTED",
                reason=(f"day drawdown {self.state.day_dd_pct:.2f}% "
                        f"exceeds day_dd_pct={self.config.day_dd_pct}%"),
                reason_code="G3", gate="day_dd_pct_breach", plan=dict(plan),
            )
        return None

    # ---- G4: per_symbol_cooldown ----
    def _g4(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        symbol = plan["symbol"]
        until = self.state.cooldowns.get(symbol)
        if until is not None and tick.ts < until:
            mins = int((until - tick.ts).total_seconds() // 60) + 1
            return TradeDecision(
                verdict="REJECTED",
                reason=f"symbol {symbol} in {mins}min cooldown after stopout",
                reason_code="G4", gate="per_symbol_cooldown", plan=dict(plan),
            )
        return None

    # ---- G5: sector_cap ----
    def _g5(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        sector = plan.get("sector")
        if sector is None:
            return None
        current = self.open_positions_by_sector.get(sector, 0)
        cap = self.config.max_positions_per_sector
        if current >= cap:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"sector {sector} at cap {current}/{cap} positions",
                reason_code="G5", gate="sector_cap", plan=dict(plan),
            )
        return None

    # ---- G6: max_position_size ----
    def _g6(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        notional = Decimal(str(plan["notional"]))
        limit = self.starting_equity * Decimal(str(self.config.max_position_size_pct_equity)) / Decimal("100")
        if notional > limit:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"position size {notional} exceeds max_position_size={limit}",
                reason_code="G6", gate="max_position_size", plan=dict(plan),
            )
        return None

    # ---- G7: total_notional_cap ----
    def _g7(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        notional = Decimal(str(plan["notional"]))
        cap = self.starting_equity * Decimal(str(self.config.max_notional_pct_equity)) / Decimal("100")
        if (self.total_notional + notional) > cap:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"total notional {self.total_notional + notional} exceeds max_notional={cap}",
                reason_code="G7", gate="total_notional_cap", plan=dict(plan),
            )
        return None

    # ---- G8: duplicate_position ----
    def _g8(self, plan: TradePlan, tick: TickData) -> TradeDecision | None:
        symbol = plan["symbol"]
        if symbol in self.open_positions_by_symbol:
            return TradeDecision(
                verdict="REJECTED",
                reason=f"already long {symbol}; blocking additional long",
                reason_code="G8", gate="duplicate_position", plan=dict(plan),
            )
        return None
```

- [ ] **Step 3: Write the 8 gate tests**

Create `tests/unit/test_risk_manager.py` with one test per gate. Each test constructs the minimal `RiskManager` state that trips exactly that gate and asserts the returned `TradeDecision`. Example G1 + G4; the remainder follow the same shape.

```python
"""RiskManager — one test per gate (PRD §8.2, AC-risk-1)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import exchange_calendars as xcals
import pytest

from openbb_fmp_trading.core.risk_manager import RiskManager
from openbb_fmp_trading.models import RiskConfig, SessionStatus, TickData


def _tick(ts):
    return TickData(
        ts=ts, quotes={}, bars_recent={},
        session_status=SessionStatus(
            exchange="NASDAQ", is_market_open=True, is_pre_market=False,
            is_after_market=False, is_early_close_day=False, next_open=ts, next_close=ts,
        ),
    )


def _rm(**overrides):
    cfg = RiskConfig(**{k: v for k, v in overrides.items() if k in RiskConfig.model_fields})
    return RiskManager(config=cfg, starting_equity=Decimal("100000"))


def test_g1_flat_by_close_rejects_after_1550_et():
    rm = _rm()
    cal = xcals.get_calendar("NASDAQ")
    et = cal.tz
    tick = _tick(datetime(2026, 7, 6, 15, 51, tzinfo=et).astimezone(timezone.utc))
    plan = {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"}
    d = rm.propose_trade(plan, tick)
    assert d.verdict == "REJECTED" and d.reason_code == "G1"


def test_g2_max_open_positions():
    rm = _rm()
    rm.state.open_position_count = rm.config.max_open_positions
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G2"


def test_g3_day_dd_pct_breach():
    rm = _rm()
    rm.state.day_dd_pct = -3.0  # config default is -2.0
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G3"


def test_g4_per_symbol_cooldown():
    rm = _rm()
    now = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
    rm.state.cooldowns["AAPL"] = now + timedelta(minutes=15)
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"}, _tick(now),
    )
    assert d.reason_code == "G4"


def test_g5_sector_cap():
    rm = _rm()
    rm.open_positions_by_sector["Tech"] = rm.config.max_positions_per_sector
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G5"


def test_g6_max_position_size():
    rm = _rm()
    # 10% of 100k = 10k limit; propose 15k
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("15000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G6"


def test_g7_total_notional_cap():
    rm = _rm()
    # 30% of 100k = 30k cap; already holding 25k, propose 10k
    rm.total_notional = Decimal("25000")
    d = rm.propose_trade(
        {"symbol": "MSFT", "notional": Decimal("10000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G7"


def test_g8_duplicate_position():
    rm = _rm()
    rm.open_positions_by_symbol["AAPL"] = Decimal("100")
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("1000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.reason_code == "G8"


def test_all_gates_pass_approves():
    rm = _rm()
    d = rm.propose_trade(
        {"symbol": "AAPL", "notional": Decimal("5000"), "sector": "Tech"},
        _tick(datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)),
    )
    assert d.verdict == "APPROVED"
```

- [ ] **Step 4: Green tests + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_risk_manager.py -q
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core openbb_platform/extensions/fmp_trading/tests/unit/test_risk_manager.py
git commit -m "feat(fmp_trading): P1.3 RiskManager with 8 gates + tests

RiskManager.propose_trade() runs 8 gates in order (G1..G8); first REJECT
wins; every REJECTED decision carries reason_code and gate name.
exchange_calendars powers G1's flat-by-close clock (P5).

Tests: one per gate + one all-pass smoke test.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: `9 passed`.

---

## Task 4 (P1.4): SessionJournal NDJSON writer + reader/replay

**Files:**
- Create: `openbb_fmp_trading/core/journal.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_journal.py`

### Interfaces
- **Consumes:** `JournalEvent` from `models`; standard `pathlib.Path`.
- **Produces:** `SessionJournal(path).write(event)` — atomic-append NDJSON; `read_events(path) -> Iterator[JournalEvent]` for replay; a `partial-line-recovery` behaviour where a truncated final line is skipped rather than crashing (P2's replay must never fail on a session that was killed mid-write).

- [ ] **Step 1: Write the failing test**

`tests/unit/test_journal.py`:

```python
"""SessionJournal — append writer + replay reader + partial-line recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openbb_fmp_trading.core.journal import SessionJournal, read_events
from openbb_fmp_trading.models import JournalEvent


def _ev(i: int) -> JournalEvent:
    return JournalEvent(
        ts=datetime(2026, 7, 6, 10, i % 60, tzinfo=timezone.utc),
        session_id="s1", event_type="tick", payload={"n": i},
    )


def test_write_then_replay_roundtrip(tmp_path: Path):
    j = SessionJournal(tmp_path / "s.ndjson")
    for i in range(5):
        j.write(_ev(i))
    events = list(read_events(tmp_path / "s.ndjson"))
    assert len(events) == 5
    assert [e.payload["n"] for e in events] == [0, 1, 2, 3, 4]


def test_partial_line_is_skipped(tmp_path: Path):
    path = tmp_path / "s.ndjson"
    j = SessionJournal(path)
    j.write(_ev(0))
    j.write(_ev(1))
    # Simulate crash mid-write: append a truncated JSON fragment.
    with path.open("a", encoding="utf-8") as f:
        f.write('{"ts": "2026-07-06T10:02:00+00:00", "session_id": "s1", "event_')
    events = list(read_events(path))
    assert len(events) == 2  # partial line dropped, first two survive


def test_append_across_reopen(tmp_path: Path):
    path = tmp_path / "s.ndjson"
    SessionJournal(path).write(_ev(0))
    SessionJournal(path).write(_ev(1))  # new instance, same file
    assert len(list(read_events(path))) == 2
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_journal.py -q`
Expected: FAIL — module not found.

- [ ] **Step 2: Implement `core/journal.py`**

```python
"""SessionJournal — append-only NDJSON writer + resilient reader.

One row per event; every row is a self-contained JSON document terminated by
a newline. Atomic-per-line append: on any crash, the tail may be truncated
but every complete prior line is intact and replay-safe.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator

from openbb_fmp_trading.models import JournalEvent


class SessionJournal:
    """Append-only NDJSON writer for JournalEvents.

    The file is opened in append mode on every ``write()`` call — cheap on
    modern filesystems, and it means multiple SessionJournal instances against
    the same path don't step on each other (single-writer-per-tick is the
    intended pattern; this shape simply refuses to lose data if that invariant
    breaks temporarily).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: JournalEvent) -> None:
        line = event.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)

    def write_many(self, events: Iterable[JournalEvent]) -> None:
        for e in events:
            self.write(e)


def read_events(path: str | Path) -> Iterator[JournalEvent]:
    """Yield every complete JournalEvent from an NDJSON file.

    Truncated final lines (crashed mid-write) are silently skipped — replay
    must survive an aborted session. Malformed non-final lines raise, since
    that indicates real corruption rather than a clean truncation.
    """
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    for idx, raw in enumerate(lines):
        line = raw.rstrip("\n")
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            # Only tolerate a broken *final* line (crash mid-write).
            if idx == len(lines) - 1:
                continue
            raise
        yield JournalEvent.model_validate(data)
```

- [ ] **Step 3: Green tests + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_journal.py -q
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/journal.py openbb_platform/extensions/fmp_trading/tests/unit/test_journal.py
git commit -m "feat(fmp_trading): P1.4 SessionJournal NDJSON writer + resilient reader

Append-only NDJSON per event; per-line atomic writes; reader tolerates a
truncated final line (crash mid-write) but raises on interior corruption.
Enables obb.fmp_trading.replay() in P5 to reconstruct any prior session.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: `3 passed`.

---

## Task 5 (P1.5): BandwidthMeter + monthly persistence + conservation-mode test

**Files:**
- Create: `openbb_fmp_trading/core/bandwidth.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_bandwidth.py`

### Interfaces
- **Consumes:** `BandwidthState` from `models`; `pathlib.Path` for `~/.openbb_platform/fmp_trading/bandwidth.json`.
- **Produces:** `BandwidthMeter.charge(bytes) -> BandwidthState`; `.mode` transitions `normal → conservation` at 80%, `conservation → halted` at 95%; month rollover clears counters; atomic persistence via temp-file rename.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_bandwidth.py`:

```python
"""BandwidthMeter — accounting, thresholds, monthly rollover, atomic persistence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openbb_fmp_trading.core.bandwidth import BandwidthMeter


def test_charge_accumulates(tmp_path: Path):
    m = BandwidthMeter(state_path=tmp_path / "bw.json", budget_bytes=1_000_000,
                       today=date(2026, 7, 6))
    s = m.charge(100)
    assert s.month_used_bytes == 100
    m.charge(400)
    assert m.state.month_used_bytes == 500


def test_conservation_at_80_pct(tmp_path: Path):
    m = BandwidthMeter(state_path=tmp_path / "bw.json", budget_bytes=1_000,
                       today=date(2026, 7, 6))
    m.charge(750)  # 75%
    assert m.state.mode == "normal"
    m.charge(100)  # 85%
    assert m.state.mode == "conservation"


def test_halted_at_95_pct(tmp_path: Path):
    m = BandwidthMeter(state_path=tmp_path / "bw.json", budget_bytes=1_000,
                       today=date(2026, 7, 6))
    m.charge(960)
    assert m.state.mode == "halted"


def test_month_rollover_resets(tmp_path: Path):
    m = BandwidthMeter(state_path=tmp_path / "bw.json", budget_bytes=1_000,
                       today=date(2026, 7, 6))
    m.charge(500)
    m.rollover_if_needed(today=date(2026, 8, 1))
    assert m.state.month_used_bytes == 0
    assert m.state.mode == "normal"


def test_persists_across_instances(tmp_path: Path):
    path = tmp_path / "bw.json"
    m1 = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    m1.charge(300)
    m2 = BandwidthMeter(state_path=path, budget_bytes=1_000, today=date(2026, 7, 6))
    assert m2.state.month_used_bytes == 300
```

Run: expected FAIL — module not found.

- [ ] **Step 2: Implement `core/bandwidth.py`**

```python
"""BandwidthMeter — monthly persistent FMP bandwidth accounting (PRD §8.7 / P6).

State file layout (JSON): {"month": "YYYY-MM", "used_bytes": int}.
Atomic writes via write-to-temp + os.replace so a crash never yields a
corrupt state file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from openbb_fmp_trading.models import BandwidthState

Mode = Literal["normal", "conservation", "halted"]

CONSERVATION_THRESHOLD = 0.80
HALTED_THRESHOLD = 0.95


@dataclass
class BandwidthMeter:
    state_path: Path
    budget_bytes: int
    today: date
    state: BandwidthState = None  # type: ignore[assignment]
    _session_used: int = 0

    def __post_init__(self) -> None:
        self.state_path = Path(self.state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_init()

    def _load_or_init(self) -> None:
        month_key = self.today.strftime("%Y-%m")
        used = 0
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                if data.get("month") == month_key:
                    used = int(data.get("used_bytes", 0))
            except (json.JSONDecodeError, ValueError):
                used = 0  # corrupt file: start fresh, log in P2
        self.state = self._build_state(used)

    def _build_state(self, used: int) -> BandwidthState:
        pct = used / self.budget_bytes if self.budget_bytes else 0.0
        mode: Mode = "normal"
        if pct >= HALTED_THRESHOLD:
            mode = "halted"
        elif pct >= CONSERVATION_THRESHOLD:
            mode = "conservation"
        return BandwidthState(
            month_used_bytes=used, month_budget_bytes=self.budget_bytes,
            month_used_pct=pct, mode=mode, session_used_bytes=self._session_used,
        )

    def charge(self, num_bytes: int) -> BandwidthState:
        self._session_used += num_bytes
        new_used = self.state.month_used_bytes + num_bytes
        self.state = self._build_state(new_used)
        self._persist()
        return self.state

    def rollover_if_needed(self, today: date) -> None:
        current_month = self.today.strftime("%Y-%m")
        new_month = today.strftime("%Y-%m")
        if new_month != current_month:
            self.today = today
            self._session_used = 0
            self.state = self._build_state(0)
            self._persist()

    def _persist(self) -> None:
        payload = json.dumps({
            "month": self.today.strftime("%Y-%m"),
            "used_bytes": self.state.month_used_bytes,
        })
        # Atomic write: tmp + os.replace
        fd, tmp = tempfile.mkstemp(
            prefix="bw-", suffix=".json", dir=str(self.state_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self.state_path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
```

- [ ] **Step 3: Green tests + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_bandwidth.py -q
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/bandwidth.py openbb_platform/extensions/fmp_trading/tests/unit/test_bandwidth.py
git commit -m "feat(fmp_trading): P1.5 BandwidthMeter + monthly persistence + conservation mode

Persists {month, used_bytes} to ~/.openbb_platform/fmp_trading/bandwidth.json
via atomic tmp+os.replace. Mode transitions: normal -> conservation at 80%,
conservation -> halted at 95% (PRD P6, NFR-14). rollover_if_needed() clears
counters when the month ticks over.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: `5 passed`.

---

## Task 6 (P1.6): `obb.fmp_trading.doctor()` + `openbb-daytrade doctor` CLI

**Files:**
- Create: `openbb_fmp_trading/core/doctor.py`
- Modify: `openbb_fmp_trading/fmp_trading_router.py` (replace stub `doctor` with real command)
- Create: `openbb_fmp_trading/cli/__init__.py`
- Create: `openbb_fmp_trading/cli/main.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_doctor.py`

### Interfaces
- **Consumes:** `HealthReport` from `models`; `BandwidthMeter` from `core`; `openbb_core.app.service.user_service` (credentials); `importlib.metadata` for optional-extra probing.
- **Produces:** `run_doctor(...) -> HealthReport`; `obb.fmp_trading.doctor()` returns `OBBject(results=<HealthReport-dumped-dict>)`; `openbb-daytrade doctor` prints a human-readable summary + exits non-zero if any `errors` are populated.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_doctor.py`:

```python
"""doctor() — fields populated, missing extras degrade gracefully, exit-code discipline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openbb_fmp_trading.core.doctor import run_doctor
from openbb_fmp_trading.models import HealthReport


def test_doctor_returns_populated_healthreport(tmp_path: Path):
    report = run_doctor(bandwidth_state_path=tmp_path / "bw.json",
                       bandwidth_budget_bytes=1_000, today=date(2026, 7, 6))
    assert isinstance(report, HealthReport)
    # These booleans must be answered one way or the other; None is a bug.
    for field in ("fmp_credentials_ok", "mysql_cache_ok", "exchange_calendars_ok",
                  "techtrade_ok", "agent_extra_installed", "xlsxwriter_extra_installed",
                  "validation_extra_installed"):
        assert getattr(report, field) in (True, False), field
    assert 0.0 <= report.bandwidth_remaining_pct <= 100.0


def test_doctor_router_command_returns_obbject_results():
    from openbb import obb
    result = obb.fmp_trading.doctor()
    assert result.results is not None
    assert "fmp_credentials_ok" in result.results or hasattr(result.results, "fmp_credentials_ok")
```

Run: expected FAIL — `core.doctor` module missing and the router still returns the stub payload.

- [ ] **Step 2: Implement `core/doctor.py`**

```python
"""doctor() — HealthReport builder used by both the router command and the CLI."""

from __future__ import annotations

from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import exchange_calendars as xcals

from openbb_fmp_trading.core.bandwidth import BandwidthMeter
from openbb_fmp_trading.models import HealthReport


def _extra_installed(pkg: str) -> bool:
    try:
        version(pkg)
        return True
    except PackageNotFoundError:
        return False


def _check_fmp_credentials() -> bool:
    try:
        from openbb_core.app.service.user_service import UserService
        creds = UserService().default_user_settings.credentials
        return bool(getattr(creds, "fmp_cached_api_key", None) or getattr(creds, "fmp_api_key", None))
    except Exception:
        return False


def _check_mysql_cache() -> bool:
    # Best-effort probe; failure to import openbb_fmp_cached simply degrades to False.
    try:
        from openbb_fmp_cached.utils.helpers import ping_cache  # type: ignore
        return ping_cache()
    except Exception:
        return False


def _check_exchange_calendars() -> bool:
    try:
        xcals.get_calendar("NASDAQ").is_session(date.today())
        return True
    except Exception:
        return False


def run_doctor(
    *, bandwidth_state_path: Path | str, bandwidth_budget_bytes: int,
    today: date | None = None,
) -> HealthReport:
    today = today or date.today()
    warnings: list[str] = []
    errors: list[str] = []

    try:
        tt_version = version("openbb-techtrade")
        tt_ok = True
    except PackageNotFoundError:
        tt_version = "0.0.0"
        tt_ok = False
        errors.append("openbb-techtrade not installed")

    fmp_ok = _check_fmp_credentials()
    if not fmp_ok:
        errors.append("FMP credentials missing (set fmp_cached_api_key in user_settings.json)")

    mysql_ok = _check_mysql_cache()
    if not mysql_ok:
        warnings.append("fmp_cached MySQL cache unreachable — will fall back to raw fmp per tier-1 pattern")

    xcals_ok = _check_exchange_calendars()
    if not xcals_ok:
        errors.append("exchange_calendars not available for NASDAQ")

    bw = BandwidthMeter(state_path=bandwidth_state_path,
                        budget_bytes=bandwidth_budget_bytes, today=today)
    remaining_pct = max(0.0, 100.0 * (1.0 - bw.state.month_used_pct))
    if bw.state.mode == "conservation":
        warnings.append(f"BandwidthMeter in conservation mode ({bw.state.month_used_pct:.1%} used)")
    if bw.state.mode == "halted":
        errors.append(f"BandwidthMeter halted ({bw.state.month_used_pct:.1%} used)")

    return HealthReport(
        ts=datetime.now(timezone.utc),
        fmp_credentials_ok=fmp_ok,
        mysql_cache_ok=mysql_ok,
        exchange_calendars_ok=xcals_ok,
        techtrade_version=tt_version,
        techtrade_ok=tt_ok,
        agent_extra_installed=_extra_installed("anthropic"),
        xlsxwriter_extra_installed=_extra_installed("xlsxwriter"),
        validation_extra_installed=_extra_installed("openbb-backtest"),
        bandwidth_remaining_pct=remaining_pct,
        warnings=warnings,
        errors=errors,
    )
```

- [ ] **Step 3: Replace the router stub with the real command**

Edit `openbb_fmp_trading/fmp_trading_router.py`, replacing the stub `doctor` function with:

```python
from pathlib import Path

from openbb_fmp_trading.core.doctor import run_doctor


@router.command(methods=["GET"])
def doctor() -> OBBject:
    """Return an fmp_trading environment health report.

    Checks: FMP credentials, MySQL cache reachability, exchange_calendars data,
    techtrade installation + version, [agent] / [xlsxwriter] / [validation]
    extras, and remaining monthly bandwidth budget.

    Return annotation is bare ``OBBject`` per the Critical Design Constraint
    (see the Phase 1 plan header). The ``HealthReport`` model is instantiated
    inside the function body and its ``.model_dump()`` becomes ``results``.
    """
    state_path = Path.home() / ".openbb_platform" / "fmp_trading" / "bandwidth.json"
    report = run_doctor(
        bandwidth_state_path=state_path,
        bandwidth_budget_bytes=50 * 1024**3,
    )
    return OBBject(results=report.model_dump(mode="json"))
```

- [ ] **Step 4: Implement the CLI entry**

`openbb_fmp_trading/cli/__init__.py`:

```python
"""openbb-daytrade CLI."""
```

`openbb_fmp_trading/cli/main.py`:

```python
"""openbb-daytrade — CLI entry point (Phase 1: doctor only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openbb_fmp_trading.core.doctor import run_doctor


def _cmd_doctor(_args: argparse.Namespace) -> int:
    state_path = Path.home() / ".openbb_platform" / "fmp_trading" / "bandwidth.json"
    report = run_doctor(
        bandwidth_state_path=state_path, bandwidth_budget_bytes=50 * 1024**3,
    )
    print("openbb-daytrade doctor")
    print("=" * 40)
    print(f"  FMP credentials       : {'OK' if report.fmp_credentials_ok else 'MISSING'}")
    print(f"  fmp_cached MySQL      : {'OK' if report.mysql_cache_ok else 'unreachable'}")
    print(f"  exchange_calendars    : {'OK' if report.exchange_calendars_ok else 'MISSING'}")
    print(f"  openbb-techtrade      : {report.techtrade_version} ({'OK' if report.techtrade_ok else 'MISSING'})")
    print(f"  [agent] extra         : {'installed' if report.agent_extra_installed else 'absent'}")
    print(f"  [xlsxwriter] extra    : {'installed' if report.xlsxwriter_extra_installed else 'absent'}")
    print(f"  [validation] extra    : {'installed' if report.validation_extra_installed else 'absent'}")
    print(f"  Bandwidth remaining   : {report.bandwidth_remaining_pct:.1f}%")
    for w in report.warnings:
        print(f"  WARN: {w}")
    for e in report.errors:
        print(f"  ERROR: {e}")
    return 1 if report.errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openbb-daytrade")
    sub = parser.add_subparsers(dest="cmd", required=True)
    doctor_p = sub.add_parser("doctor", help="Health check the environment")
    doctor_p.set_defaults(func=_cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Rebuild the static package + green tests + smoke the CLI**

```bash
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_doctor.py -q
.venv_win\Scripts\openbb-daytrade doctor
```

Expected: `openbb.build()` exit 0; pytest `2 passed`; CLI prints the health block and exits 0 or 1 depending on whether FMP credentials are configured on this machine (both outcomes are correct — the test only asserts the boolean fields are set).

- [ ] **Step 6: Full-suite regression + commit**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit -q
.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/fmp_trading
git status --porcelain openbb_platform/core/openbb/package/
git restore --staged openbb_platform/core/openbb/package/ 2>/dev/null || true
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/doctor.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/fmp_trading_router.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli \
        openbb_platform/extensions/fmp_trading/tests/unit/test_doctor.py
git commit -m "feat(fmp_trading): P1.6 doctor() command + openbb-daytrade doctor CLI

run_doctor() probes FMP credentials, MySQL cache reachability,
exchange_calendars, techtrade version, [agent]/[xlsxwriter]/[validation]
extras, and remaining monthly bandwidth budget. Router command returns
bare OBBject with results=report.model_dump() (codegen-safe). CLI prints
the same report and exits non-zero on any error.

Acceptance: obb.fmp_trading.doctor() runs; openbb-daytrade doctor runs;
unit suite green across all Phase 1 tasks.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: full Phase 1 unit suite green (~30+ tests across scaffolding, models, risk, journal, bandwidth, doctor).

---

## Self-Review Notes

**Spec coverage (Phase 1 acceptance from PRD §10):**
- P1.1 scaffold mirroring techtrade layout → Task 1 ✓
- P1.2 §6 models + round-trip tests → Task 2 (parametrized over ~25 models) ✓
- P1.3 RiskManager 8 gates + one test per gate → Task 3 (G1..G8 + all-pass smoke) ✓
- P1.4 SessionJournal NDJSON writer + reader/replay → Task 4 (write, read, partial-line recovery, cross-instance append) ✓
- P1.5 BandwidthMeter + monthly persistence + conservation-mode test → Task 5 (charge, 80%/95% thresholds, rollover, cross-instance persistence) ✓
- P1.6 `obb.fmp_trading.doctor()` + CLI → Task 6 ✓

**Codegen safety:** Every router command in this phase (`doctor` only) uses `-> OBBject:` bare. Task 6 Step 5 rebuilds the static package and asserts `obb.fmp_trading.doctor()` returns real results — proving we did not regress the NameError trap.

**Deferred to later phases (explicitly not implemented here):**
- Six new FMP fetchers (P0)
- `IntradaySession` tick loop + broker chokepoint CI test (P2)
- `PreOpenAgentTurn` / `PostCloseAgentTurn` / MCP tool server (P3)
- `market_snapshot` + `AlertManager` runtime evaluator + `alert.*` sub-router (P4)
- `report()` / `replay()` CLI subcommand (P5)
- Live-broker `AlpacaBroker(BrokerInterface)` (permanently out of v1 scope per NG1)

**Type/interface consistency:** `TradeDecision` lives in `models.session_state` (imported by both `risk_manager` and downstream journal writers); `HealthReport.model_dump(mode="json")` produces plain-JSON `results` that survives OBBject envelope serialization; `BandwidthMeter.state` is always a `BandwidthState` instance (populated in `__post_init__`).

**Session close:** Report Phase 1 status (six commits landed; unit suite green; `obb.fmp_trading.doctor()` runs; branch `fmp_trading` ahead by 6). Do NOT run `git push` — wait for user approval per CLAUDE.md conservative-profile policy.
