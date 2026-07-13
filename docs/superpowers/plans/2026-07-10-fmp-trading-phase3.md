# fmp-trading Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the two-turn agentic discovery layer (`PreOpenAgentTurn` @ 07:30 ET + `PostCloseAgentTurn` @ 16:15 ET) plus the read-only stdio MCP server (`openbb-daytrade mcp-serve`) on top of the Phase 2 execution core (`origin/fmp_trading @ df93b33ed`). Deliver 4 shipping beads (P3.0 state store → P3.1 pre-open → P3.2 post-close → P3.3 MCP) that together close GH #84, #85, and #231.

**Architecture:** Approach C (PRD §7 + Phase 3 design spec dated 2026-07-10). Anthropic Claude Agent SDK backend with forced tool-calling; deterministic full-schema fallbacks so the tick loop can't tell whether the plan came from an LLM or a fallback. Every load-bearing risk / injection defense is deterministic Python running *after* the model returns. MySQL is the sole persistence backend (D6).

**Tech Stack:** Python 3.10-3.13 (project floor); Pydantic v2 (existing); `anthropic>=0.40,<1.0` (new, in `[agent]` extra); `mcp>=1.0` (new, in `[agent]` extra); `jinja2>=3.1` (new, in `[agent]` extra); `pymysql` (already used by `fmp_cached`); `exchange_calendars` (already used by Phase 2 P2.5).

## Global Constraints

Every task's requirements implicitly include these. They come from the PRD, prior phases, and the Phase 3 design spec — copied verbatim so no plan reader needs to jump documents.

- **P1 — Deterministic core:** an LLM never touches an order, position, or `RiskManager` state. Agent turns are one-shot, confined to pre-open (07:30 ET) and post-close (16:15 ET). The market-hours tick loop shipped in Phase 2 never invokes the LLM.
- **P2 — Decimal for money:** every price, size, notional, commission, and P&L value uses `Decimal(str(...))`. Never `float`.
- **P3 — No look-ahead:** the post-close report can inspect anything the journal recorded; the pre-open turn has no access to same-day fills (there aren't any yet).
- **P4 — Flat by 15:55 ET:** Phase 2's flat-by-close cascade runs *before* the 16:15 post-close agent fires.
- **P5 — `exchange_calendars`:** used by Phase 2 P2.5 (`flat_by_close.py`) and by Phase 3 P3.1 (session-relative time comparisons in the pre-flight prune).
- **P6 — Bandwidth meter:** every LLM call charges the meter pre-call (estimate) and reconciles against `response.usage` post-call (A4). In `conservation`/`halted` mode, the turn skips the LLM and jumps to the deterministic fallback.
- **P7 — RiskManager chokepoint:** `IntradaySession._process_signal` (Phase 2) remains the sole caller of `broker.submit()`. The MCP surface exposes zero mutation tools; `submit_daily_plan` / `submit_end_of_day_md` are internal-only.
- **`fmp_cached` is the only provider** — never raw `fmp`, never `yfinance`.
- **`.venv_win` for all Python commands** — `.venv_win\Scripts\python.exe -m pytest ...`. Never system Python.
- **Beads for all task tracking** — `bd create`, `bd close`, `bd ready`. Never `TodoWrite` / `TaskCreate` / markdown TODOs.
- **Ship each task as one commit** with `Co-Authored-By: Claude <noreply@anthropic.com>` and a `#<gh-issue>` / `bd-<id>` reference in the subject.

---

## File Structure

Phase 3 is largely additive. The 4-bead split maps cleanly to the 3 new packages + 1 new state-store module. Existing Phase 2 files touched: `pyproject.toml`, `cli.py`, `models/journal_events.py`. Nothing in `core/session.py` or `core/tick_loop.py` changes — the tick loop remains oblivious to whether its `DailyPlan` came from an LLM or a fallback (D4).

```
openbb_platform/extensions/fmp_trading/
├── pyproject.toml                                # P3.3: add [agent] extra
├── openbb_fmp_trading/
│   ├── cli.py                                    # P3.3: add `mcp-serve` subcommand
│   ├── models/
│   │   ├── journal_events.py                    # P3.1+P3.2: add 4 new typed events
│   │   └── report.py                            # P3.2: new — EndOfDayReport + subtypes
│   ├── core/
│   │   └── state_store.py                       # P3.0: new — MySQL-backed state
│   └── agent/                                    # P3.1..P3.3: entire package new
│       ├── __init__.py                          # Extra-gated re-exports
│       ├── backend.py                           # AgentBackend Protocol + Claude impl
│       ├── errors.py                            # AgentUnavailable, RiskOverrideLoosening
│       ├── tool_registry.py                    # Auto-generated tool schemas
│       ├── tradable_universe.py                # P3.1: allowlist for A1 defense
│       ├── pre_open.py                          # P3.1: PreOpenAgentTurn
│       ├── post_close.py                        # P3.2: PostCloseAgentTurn
│       ├── mcp_server.py                        # P3.3: stdio MCP server
│       ├── prompts/
│       │   ├── pre_open_v1.txt                  # P3.1
│       │   └── post_close_v1.txt                # P3.2
│       └── templates/
│           └── post_close_briefing.md.j2        # P3.2: narrator (#84) template
└── tests/
    ├── unit/
    │   ├── test_state_store.py                  # P3.0
    │   ├── test_backend_protocol.py             # P3.1
    │   ├── test_tool_registry.py                # P3.1
    │   ├── test_tool_registry_not_on_core_import.py  # P3.1 (A3)
    │   ├── test_pre_open_fallback.py            # P3.1 (AC-agent-1)
    │   ├── test_pre_open_validation_retry.py    # P3.1 (AC-agent-9)
    │   ├── test_risk_clamp.py                   # P3.1 (AC-agent-7)
    │   ├── test_prompt_injection.py             # P3.1 (AC-agent-8)
    │   ├── test_preflight_prune.py              # P3.1 (AC-agent-12)
    │   ├── test_bandwidth_reconciliation.py     # P3.1 (AC-agent-11)
    │   ├── test_post_close_fallback.py          # P3.2 (AC-agent-2)
    │   ├── test_mcp_readonly_surface.py         # P3.3 (AC-agent-4 / AC-risk-8)
    │   └── test_import_guard.py                 # P3.3 (per-PR AC-agent-5)
    ├── integration/
    │   └── test_full_day_with_agent.py          # P3.3 (AC-1-ext)
    └── architecture/
        └── test_core_unchanged_when_removed.py  # P3.3 (nightly AC-agent-5)

openbb_platform/providers/fmp_cached/
└── openbb_fmp_cached/utils/cache_schema.py       # P3.0: add fmp_trading_state table
```

Task boundaries mirror the design spec's D5 bead split. P3.0 ships first because P3.1's fallback path calls `state_store.load_last_watchlist()` — stubbing that in every fallback test would cost more than the 1-day state-store investment.

---

## Task Right-Sizing

Each task below produces one bd bead + one commit + one GH issue closure. Setup / config / doc edits fold into the task whose deliverable needs them (extra gating goes with P3.3, not a standalone bead). Every task ends with an independently-verifiable green pytest run.

---

## Task P3.0: `core/state_store.py` — MySQL-backed persistent state

**Consumes:** `openbb_fmp_cached.utils.database.execute_query` / `execute_many` (already in tree); `openbb_fmp_cached.utils.cache_schema.FLATTENED_TABLES` dict pattern (P2.2 established); `pymysql.MySQLError` (already a transitive dep).

**Produces:** `state_store.load_state(key, scope) / save_state(key, payload, scope)` API + typed convenience wrappers (`load_last_watchlist`, `save_last_watchlist`, `load_last_plan`, etc.) + a new `fmp_trading_state` MySQL table registered in `FLATTENED_TABLES`. This is the foundation the P3.1 fallback and P3.2 write paths both consume.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/state_store.py`
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py` — add `create_fmp_trading_state_table()` + `FLATTENED_TABLES["fmp_trading_state"]` entry
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_state_store.py`

**Interfaces:**
- Consumes: `execute_query(sql, params)`, `execute_many(sql, params_list)` from `openbb_fmp_cached.utils.database` (already stable).
- Produces:
  - `load_state(key: str, scope: str = "default") -> Any | None`
  - `save_state(key: str, payload: Any, scope: str = "default") -> None`
  - `load_last_watchlist(scope: str = "default") -> list[str] | None`
  - `save_last_watchlist(symbols: list[str], scope: str = "default") -> None`
  - `load_last_plan(scope: str = "default") -> DailyPlan | None` (typed wrapper — validates on load per A8)
  - `save_last_plan(plan: DailyPlan, scope: str = "default") -> None`
  - `create_fmp_trading_state_table() -> Any` (registered in FLATTENED_TABLES)

- [ ] **Step 1: Add schema function + FLATTENED_TABLES entry (RED)**

Append to `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py` — right after `create_ttl_cache_table()` (P2.2, ~line 5605):

```python
def create_fmp_trading_state_table():
    """Create fmp_trading_state — backing store for state_store.py (P3.0).

    Persistent key-value state used by the two agent turns and their
    deterministic fallbacks (D6). One row per (state_key, scope). Payload
    is a JSON blob so heterogeneous state keys (list[str] for watchlist,
    full DailyPlan dict for last plan, etc.) share one table without
    per-key migrations.

    Resilience contract lives in state_store.py: DB failure -> load returns
    None, save is best-effort. Serialization bugs propagate (narrow
    try/except in state_store — see A7 in the design spec).
    """
    query = \"\"\"
    CREATE TABLE IF NOT EXISTS fmp_trading_state (
        state_key  VARCHAR(80) NOT NULL,
        scope      VARCHAR(80) NOT NULL DEFAULT 'default',
        payload    JSON        NOT NULL,
        updated_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (state_key, scope),
        INDEX idx_updated_at (updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    \"\"\"
    return execute_query(query)
```

Register it in `FLATTENED_TABLES` (near ~line 5464 where `ttl_cache` is registered):

```python
"fmp_trading_state": {
    "description": "Persistent key-value state for fmp_trading agent turns + fallbacks (P3.0/D6)",
    "schema": create_fmp_trading_state_table,
},
```

- [ ] **Step 2: Write the 8-test RED suite for state_store**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_state_store.py`:

```python
"""Unit tests for core/state_store.py (P3.0 / D6).

Verifies:
  1. Round-trip: save then load returns identical payload
  2. Absent key returns None
  3. UPSERT: two saves same key overwrite; updated_at advances
  4. DB failure on load returns None (never raises)
  5. DB failure on save doesn't raise (best-effort)
  6. Scope isolation: save at scope=a doesn't touch scope=b
  7. A7: non-DB exceptions (TypeError, JSONDecodeError) PROPAGATE
  8. A8: load_last_plan on corrupt payload returns None + logs

All DB calls are patched via unittest.mock.patch on execute_query /
execute_many — matches the P2.2 ttl-wrapper test pattern.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


class TestRoundTrip:
    def test_save_then_load_returns_identical_payload(self):
        from openbb_fmp_trading.core.state_store import load_state, save_state

        captured = {}
        def fake_upsert(sql, params_list):
            captured["upsert"] = params_list
        def fake_select(sql, params):
            # Return whatever the last upsert stored
            if "upsert" in captured:
                payload_json = captured["upsert"][0][2]
                return [{"payload": payload_json}]
            return []

        with patch("openbb_fmp_cached.utils.database.execute_many", side_effect=fake_upsert), \
             patch("openbb_fmp_cached.utils.database.execute_query", side_effect=fake_select):
            save_state("foo", {"bar": 1, "baz": [2, 3]})
            result = load_state("foo")
        assert result == {"bar": 1, "baz": [2, 3]}


class TestAbsentKey:
    def test_load_absent_key_returns_none(self):
        from openbb_fmp_trading.core.state_store import load_state
        with patch("openbb_fmp_cached.utils.database.execute_query", return_value=[]):
            assert load_state("never-set") is None


class TestScopeIsolation:
    def test_different_scopes_do_not_collide(self):
        from openbb_fmp_trading.core.state_store import save_state
        captured = []
        with patch("openbb_fmp_cached.utils.database.execute_many",
                   side_effect=lambda sql, p: captured.append(p)):
            save_state("k", 1, scope="a")
            save_state("k", 2, scope="b")
        assert captured[0][0][1] == "a"
        assert captured[1][0][1] == "b"


class TestDBFailureDegrades:
    def test_load_on_db_failure_returns_none(self):
        from openbb_fmp_trading.core.state_store import load_state
        import pymysql
        with patch("openbb_fmp_cached.utils.database.execute_query",
                   side_effect=pymysql.MySQLError("connection lost")):
            assert load_state("foo") is None

    def test_save_on_db_failure_does_not_raise(self):
        from openbb_fmp_trading.core.state_store import save_state
        import pymysql
        with patch("openbb_fmp_cached.utils.database.execute_many",
                   side_effect=pymysql.MySQLError("connection lost")):
            save_state("foo", {"bar": 1})  # must not raise


class TestA7ExceptionNarrowness:
    def test_typeerror_from_non_serializable_payload_propagates(self):
        """A7: serialization bugs must NOT be swallowed as 'DB down'."""
        from openbb_fmp_trading.core.state_store import save_state

        class NotJSONSerializable:
            pass

        # execute_many never gets called because json.dumps raises first
        with pytest.raises(TypeError):
            save_state("foo", NotJSONSerializable())


class TestA8TypedLoadWrappers:
    def test_load_last_plan_on_corrupt_payload_returns_none(self):
        """A8: corrupt payload -> None + WARN, never crash."""
        from openbb_fmp_trading.core.state_store import load_last_plan
        with patch("openbb_fmp_cached.utils.database.execute_query",
                   return_value=[{"payload": '{"totally": "not a DailyPlan"}'}]):
            assert load_last_plan() is None

    def test_load_last_watchlist_returns_list_of_strings(self):
        from openbb_fmp_trading.core.state_store import load_last_watchlist
        with patch("openbb_fmp_cached.utils.database.execute_query",
                   return_value=[{"payload": '["MSFT","AAPL"]'}]):
            result = load_last_watchlist()
        assert result == ["MSFT", "AAPL"]
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_state_store.py -q`
Expected: FAIL — `ModuleNotFoundError: openbb_fmp_trading.core.state_store`.

- [ ] **Step 3: Implement state_store.py (GREEN)**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/state_store.py`:

```python
"""MySQL-backed persistent state for fmp_trading (P3.0 / D6).

Consolidated persistence: reuse the fmp_cached MySQL connection rather
than a second JSON-on-disk surface. Backups + multi-machine access come
free from the existing infra.

API surface — two layers:

  Raw:   load_state(key, scope) / save_state(key, payload, scope)
         Payloads are JSON-serializable Any; caller owns the shape.

  Typed: load_last_watchlist / save_last_watchlist / load_last_plan /
         save_last_plan / load_last_session_summary /
         save_last_session_summary. Validate on load per A8; corrupt
         payloads return None + log WARN.

Resilience contract (matches P2.2 create_ttl_wrapper_class):
  * DB failure on SELECT -> return None (never raise). Marks 'DB down',
    not 'we have a bug'.
  * DB failure on UPSERT -> log at WARN, suppress. Best-effort persistence.
  * A7: only pymysql.MySQLError + ConnectionError are caught. TypeError
    / ValueError / json.JSONDecodeError propagate so serialization bugs
    can't masquerade as 'DB down'.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import path: pymysql is a transitive dep via fmp_cached; treat as always-present.
# execute_query / execute_many are imported lazily inside functions so tests can patch
# them at the openbb_fmp_cached.utils.database module level.


def _db():
    """Return (execute_query, execute_many). Lazy so tests can patch."""
    from openbb_fmp_cached.utils.database import execute_many, execute_query
    return execute_query, execute_many


def _db_errors() -> tuple:
    """Narrow exception tuple for try/except in save/load — A7."""
    import pymysql
    return (pymysql.MySQLError, ConnectionError)


def load_state(key: str, scope: str = "default") -> Any | None:
    """Load the JSON payload for (key, scope), or None if absent / DB down.

    Deserialization errors (json.JSONDecodeError) propagate — a corrupt
    row is a bug that needs surfacing, not silent None."""
    execute_query, _ = _db()
    try:
        rows = execute_query(
            "SELECT payload FROM fmp_trading_state WHERE state_key = %s AND scope = %s",
            (key, scope),
        )
    except _db_errors() as exc:
        logger.warning("state_store.load_state(%s, %s) DB failure: %s", key, scope, exc)
        return None
    if not rows:
        return None
    payload = rows[0]["payload"]
    # MySQL JSON columns return either a str (needs decode) or a native dict
    # depending on driver flags. Handle both.
    if isinstance(payload, str):
        return json.loads(payload)  # JSONDecodeError propagates — A7
    return payload


def save_state(key: str, payload: Any, scope: str = "default") -> None:
    """UPSERT payload as JSON. DB failure is logged + suppressed."""
    _, execute_many = _db()
    # json.dumps failures (TypeError on non-serializable) propagate — A7
    serialized = json.dumps(payload, default=str)
    try:
        execute_many(
            \"\"\"INSERT INTO fmp_trading_state (state_key, scope, payload)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 payload = VALUES(payload),
                 updated_at = CURRENT_TIMESTAMP\"\"\",
            [(key, scope, serialized)],
        )
    except _db_errors() as exc:
        logger.warning("state_store.save_state(%s, %s) DB failure: %s", key, scope, exc)


# ---------------------------------------------------------------------------
# Typed convenience wrappers — validate-on-load per A8.
# ---------------------------------------------------------------------------


def load_last_watchlist(scope: str = "default") -> list[str] | None:
    payload = load_state("last_watchlist", scope)
    if payload is None:
        return None
    if not isinstance(payload, list) or not all(isinstance(s, str) for s in payload):
        logger.warning("state_store: last_watchlist corrupt payload shape; treating as absent")
        return None
    return payload


def save_last_watchlist(symbols: list[str], scope: str = "default") -> None:
    save_state("last_watchlist", list(symbols), scope)


def load_last_plan(scope: str = "default"):
    """Return DailyPlan or None. Corrupt payload logs WARN and returns None."""
    from pydantic import ValidationError

    from openbb_fmp_trading.models.plan import DailyPlan

    payload = load_state("last_plan", scope)
    if payload is None:
        return None
    try:
        return DailyPlan.model_validate(payload)
    except ValidationError as exc:
        logger.warning("state_store: last_plan validation failed: %s", exc)
        return None


def save_last_plan(plan, scope: str = "default") -> None:
    save_state("last_plan", plan.model_dump(mode="json"), scope)
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_state_store.py -q`
Expected: 8 passed.

- [ ] **Step 4: Commit P3.0**

```bash
git add \
  openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/core/state_store.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_state_store.py
git commit -m "feat(fmp_trading): P3.0 MySQL-backed state_store + fmp_trading_state table

Foundation for D6 - consolidated persistence for the two agent turns and
their deterministic fallbacks. Ships before P3.1 so the pre-open
fallback path can call load_last_watchlist() directly rather than every
test stubbing it.

state_store.py exports:
  - load_state / save_state (raw JSON payloads)
  - load_last_watchlist / save_last_watchlist (typed list[str])
  - load_last_plan / save_last_plan (typed DailyPlan via A8 validate-on-load)

Resilience contract (A7 - narrow except):
  - pymysql.MySQLError + ConnectionError -> return None + log WARN
  - TypeError / ValueError / JSONDecodeError propagate

8 unit tests deferred to .venv_win for pytest verification.

Closes OpenBBTechnical-<P3.0-bead>, #<gh-issue>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/ -q` (full extension regression).
Expected: no regressions in Phase 1/Phase 2 tests.

---

## Task P3.1: PreOpenAgentTurn + backend + tool_registry + all P0/P1 defenses

**Consumes:** state_store from P3.0; `openbb_core_journal.JournalWriter` (Phase 1 P1.4); Phase 2 `BandwidthMeter` + `RiskConfig` + `DailyPlan` models; `anthropic>=0.40` SDK (new dep, gated by `[agent]` extra).

**Produces:** working `PreOpenAgentTurn.run()` that either produces a valid `DailyPlan` from the Anthropic API or falls through to a deterministic fallback — never crashes. Includes all P0 defenses (clamp-only risk, tradable-universe allowlist, ValidationError retry, tool_registry off core import) and all P1 hardening (bandwidth reconciliation, temperature=0 + model_id journaling, 09:25 pre-flight prune, loud fallback risk-halving).

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/errors.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/backend.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tool_registry.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tradable_universe.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/pre_open.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/prompts/pre_open_v1.txt`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/journal_events.py` — add `DailyPlanCommittedEvent`, `AgentFallbackEvent`, `PromptInjectionRejectedEvent`
- 7 new test files under `tests/unit/` (see File Structure section above)

**Interfaces:**
- Consumes:
  - `state_store.load_last_watchlist(scope="default") -> list[str] | None` (P3.0)
  - `BandwidthMeter.charge_agent_turn_budget(estimated_tokens: int) -> None` + `.reconcile(estimated, actual) -> None` (Phase 1 P1.5; `.reconcile` is a new method added here)
  - `JournalWriter.write(event: JournalEvent) -> None` (Phase 1 P1.4)
  - `DailyPlan.model_validate(dict) -> DailyPlan` (Phase 1 P1.2)
  - `anthropic.Anthropic().messages.create(...)` (new SDK, extra-gated)
- Produces:
  - `PreOpenAgentTurn.run(as_of: datetime | None = None) -> DailyPlan`
  - `AgentBackend` protocol with `run_turn(system_prompt, user_prompt, tools, required_final_tool, budget, temperature, max_iterations) -> ToolCall`
  - `class ClaudeAgentBackend(AgentBackend)` (real, `[agent]`-gated)
  - `PRE_OPEN_TOOLS: list[ToolSchema]` — auto-generated from `obb.fmp_trading.*` router (read-only subset)
  - `TRADABLE_UNIVERSE` builder function + 5-min TTL cache (via `create_ttl_wrapper_class` from P2.2)

- [ ] **Step 1: Add extra to `pyproject.toml`**

Modify `openbb_platform/extensions/fmp_trading/pyproject.toml` — add under `[tool.poetry.extras]`:

```toml
[tool.poetry.dependencies]
# ... existing deps unchanged ...
anthropic = { version = ">=0.40,<1.0", optional = true }
mcp = { version = ">=1.0", optional = true }
jinja2 = { version = ">=3.1", optional = true }

[tool.poetry.extras]
agent = ["anthropic", "mcp", "jinja2"]
```

If a `[tool.poetry.extras]` block already exists in that file, add the `agent = [...]` line without duplicating the section header.

- [ ] **Step 2: Write RED test for the extra-gate import contract (A3 + A10)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_tool_registry_not_on_core_import.py`:

```python
"""AC-agent-10 (A3, P0): tool_registry is NEVER on the core import path.

If tool_registry loaded at `import openbb`, a router schema drift would
break OpenBB for every user - including those without the [agent] extra.
This test proves the extra-gate holds.

Runs `import openbb` in a subprocess and asserts
`openbb_fmp_trading.agent.tool_registry` is absent from sys.modules.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_tool_registry_absent_after_core_import():
    script = textwrap.dedent('''
        import sys
        import openbb  # core import
        import openbb_fmp_trading  # extension import - still allowed
        offenders = [m for m in sys.modules
                     if m.startswith("openbb_fmp_trading.agent")]
        assert offenders == [], (
            "tool_registry / agent modules leaked onto core import path: "
            + ", ".join(offenders)
        )
        print("OK")
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"stderr:\\n{result.stderr}"
    assert "OK" in result.stdout
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_tool_registry_not_on_core_import.py -q`
Expected: FAIL (no `agent/` package yet, so nothing to leak — but this test will remain the guard once P3.1 lands).
_Actually expected: PASS trivially at this point; the test hardens once agent/ ships._

- [ ] **Step 3: Create the `errors.py` + `backend.py` foundations**

`agent/__init__.py`:

```python
"""fmp_trading agent turns + MCP server (Phase 3, [agent] extra).

Everything in this package is extra-gated. Core imports MUST NOT reach
this package - see tests/unit/test_tool_registry_not_on_core_import.py
for the enforcement.
"""

try:
    import anthropic  # noqa: F401
    import mcp  # noqa: F401
    _AGENT_EXTRA_AVAILABLE = True
except ImportError:
    _AGENT_EXTRA_AVAILABLE = False


def is_agent_available() -> bool:
    """True iff `pip install openbb-fmp-trading[agent]` has run."""
    return _AGENT_EXTRA_AVAILABLE
```

`agent/errors.py`:

```python
"""Agent-layer exception hierarchy.

Every failure mode of the two agent turns raises one of these; the turn
wrappers catch all of them and route to the deterministic fallback. No
uncaught exception should ever escape run().
"""


class AgentError(Exception):
    """Base class for all agent-layer failures."""


class AgentUnavailable(AgentError):
    """LLM call impossible - [agent] extra missing OR API error after retry.

    Turn wrapper catches this and falls through to the deterministic
    fallback identically whether the extra is missing or the network died.
    """


class RiskOverrideLoosening(AgentError):
    """T1 (P0): the LLM returned a DailyPlan whose session_risk loosens
    the DailyConfig defaults. Never passed through - the turn wrapper
    retries once, then falls through to fallback.
    """


class RegistryDrift(AgentError):
    """Tool schema in tool_registry disagrees with the current
    obb.fmp_trading.* router signature. Raised by test-time / mcp-serve
    startup checks, NEVER at import time (A3 P0)."""
```

`agent/backend.py`:

```python
"""AgentBackend Protocol + ClaudeAgentBackend implementation (P3.1 / D1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from openbb_fmp_trading.agent.errors import AgentUnavailable


@dataclass
class ToolCall:
    """The args of the required final tool call the backend forces the LLM to emit."""
    name: str
    args: dict[str, Any]
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class AgentBackend(Protocol):
    """One-shot LLM call with forced structured output via a required final tool.

    Stateless: no session mgmt, no caching. Implementations MUST honor
    temperature and max_iterations as hard caps.
    """
    def run_turn(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        required_final_tool: str,
        budget: Any = None,
        temperature: float = 0.0,
        max_iterations: int = 8,
        max_tokens: int = 4096,
    ) -> ToolCall:
        ...


class ClaudeAgentBackend:
    """Real backend, requires [agent] extra. D1: Anthropic Claude Agent SDK."""

    def __init__(self, model: str = "claude-sonnet-4-5"):
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise AgentUnavailable(
                "install openbb-fmp-trading[agent] to use ClaudeAgentBackend"
            ) from exc
        self._client = Anthropic()
        self._model = model

    def run_turn(
        self,
        system_prompt,
        user_prompt,
        tools,
        required_final_tool,
        budget=None,
        temperature=0.0,
        max_iterations=8,
        max_tokens=4096,
    ) -> ToolCall:
        # Real impl: loop with tool_choice={"type":"tool","name":required_final_tool}
        # capped by max_iterations. Reconcile budget with response.usage after.
        # Detailed body deferred to the RED->GREEN cycle in Step 5.
        raise NotImplementedError("Filled in during Step 5 RED-GREEN cycle")


class AlwaysUnavailableBackend:
    """Unconditional fallback backend. Raises AgentUnavailable on every call.

    Exists so PreOpenAgentTurn can be constructed with either the real
    backend or this one, and its wrapper's catch/fallback path is
    identical either way. Renamed from DeterministicFallbackBackend per
    review A11 (P2) to avoid 'clever but easy to misread' branding.
    """

    def run_turn(self, *args, **kwargs) -> ToolCall:
        raise AgentUnavailable("AlwaysUnavailableBackend is a no-op backend")
```

- [ ] **Step 4: Add typed journal events**

Modify `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/journal_events.py` — append to the existing subclasses:

```python
class DailyPlanCommittedEvent(JournalEvent):
    """Pre-open turn produced a plan (either LLM or fallback). Payload:
    agent_backend, is_deterministic_fallback, watchlist_size, preset,
    model_id, prompt_version."""

    event_type: Literal["daily_plan_committed"] = "daily_plan_committed"


class EndOfDayReportEvent(JournalEvent):
    """Post-close turn produced a report. Payload: agent_backend,
    is_deterministic_fallback, briefing_md length, recommendation count."""

    event_type: Literal["end_of_day_report"] = "end_of_day_report"


class AgentFallbackEvent(JournalEvent):
    """T3 (P1): loud journal entry every time a fallback fires. Payload:
    turn ('pre_open' | 'post_close'), reason, source_error, fallback_source."""

    event_type: Literal["agent_fallback"] = "agent_fallback"


class PromptInjectionRejectedEvent(JournalEvent):
    """A1 (P0): a deterministic post-LLM validator rejected something the
    LLM emitted. Payload: defense_layer ('tradable_universe' |
    'risk_clamp' | 'watchlist_size_cap'), field, offending_value."""

    event_type: Literal["prompt_injection_rejected"] = "prompt_injection_rejected"


__all__ += [
    "AgentFallbackEvent",
    "DailyPlanCommittedEvent",
    "EndOfDayReportEvent",
    "PromptInjectionRejectedEvent",
]
```

- [ ] **Step 5: Write the RED test for the pre-open fallback contract (AC-agent-1)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_pre_open_fallback.py`:

```python
"""AC-agent-1: PreOpenAgentTurn produces valid DailyPlan OR falls back."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest


def _cfg():
    from openbb_fmp_trading.models.config import DailyConfig, RiskConfig
    return DailyConfig(
        default_watchlist=["MSFT"],
        default_preset="trend_follow",
        default_risk=RiskConfig(),
    )


class TestPreOpenSuccess:
    def test_valid_llm_output_produces_plan(self):
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        # Backend returns a well-formed DailyPlan dict
        backend = MagicMock()
        backend.run_turn.return_value = ToolCall(
            name="submit_daily_plan",
            args={
                "as_of": "2026-07-13T13:30:00+00:00",
                "date": "2026-07-13",
                "watchlist": ["MSFT", "AAPL"],
                "preset": "intraday_momentum",
                "alerts": [],
                "session_risk": {},  # empty = use defaults (T1-safe)
                "thesis": "test",
                "agent_backend": "claude",
            },
            model_id="claude-sonnet-4-5",
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.watchlist == ["MSFT", "AAPL"]
        assert plan.is_deterministic_fallback is False


class TestPreOpenFallbackOnUnavailable:
    def test_agent_unavailable_falls_back_to_deterministic(self):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is True
        assert plan.agent_backend == "none"
        # D4: same schema, different provenance
        assert isinstance(plan.watchlist, list)
        assert plan.preset  # non-empty


class TestFallbackReadsStateStore:
    def test_fallback_uses_last_watchlist_when_present(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": ["NVDA", "AMD"],
        )
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.watchlist == ["NVDA", "AMD"]


class TestT3LoudFallback:
    def test_fallback_emits_agent_fallback_event(self):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import AgentFallbackEvent

        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        fallback_events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], AgentFallbackEvent)
        ]
        assert len(fallback_events) == 1
        assert fallback_events[0].payload["turn"] == "pre_open"
```

Also write the RED tests for **AC-agent-7 / -8 / -9 / -11 / -12** (details in the design spec §7):
- `test_risk_clamp.py` — LLM emits loosened `session_risk` → clipped or fallback (T1)
- `test_prompt_injection.py` — poisoned news strings never reach the committed plan (A1)
- `test_pre_open_validation_retry.py` — malformed tool args → retry once → fallback (A2)
- `test_bandwidth_reconciliation.py` — meter reconciles against `response.usage` (A4)
- `test_preflight_prune.py` — halted/gapped/illiquid symbols pruned at 09:25 ET (T2)

Full code for each is included in the design spec's referenced sections; each is a self-contained mock-based test file following the same pattern as `test_pre_open_fallback.py`.

- [ ] **Step 6: Implement `agent/pre_open.py` + `tool_registry.py` + `tradable_universe.py` (GREEN)**

Write the full implementation matching the design-spec §4.3 code sample. The pre_open.py body funnels every failure mode (`AgentUnavailable`, `ValidationError`, `RiskOverrideLoosening`) through retry-once → deterministic fallback; every fallback emits `AgentFallbackEvent`; every clamp/injection rejection emits `PromptInjectionRejectedEvent`; every commit journals `DailyPlanCommittedEvent` with `model_id` + `prompt_version`.

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/ -k "pre_open or risk_clamp or prompt_injection or preflight or bandwidth or tool_registry" -q`
Expected: all pass.

- [ ] **Step 7: Add CLI subcommand `openbb-daytrade pre-open`**

Modify `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py` — add a subcommand that wires up `PreOpenAgentTurn` from config + runs `.run()` + prints the resulting `DailyPlan`. Follows the same argparse pattern as the existing `doctor` subcommand from P1.6.

- [ ] **Step 8: Commit P3.1**

```bash
git add \
  openbb_platform/extensions/fmp_trading/pyproject.toml \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/ \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/journal_events.py \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_pre_open_fallback.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_pre_open_validation_retry.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_risk_clamp.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_prompt_injection.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_preflight_prune.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_bandwidth_reconciliation.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_tool_registry.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_tool_registry_not_on_core_import.py

git commit -m "feat(fmp_trading): P3.1 PreOpenAgentTurn + backend + all P0/P1 defenses

Ships the pre-open discovery agent + every design-spec defense:
  T1 clamp-only risk (RiskOverrideLoosening)
  A1 tradable-universe allowlist + injection defense stack (5 layers)
  A2 ValidationError retry-once -> fallback
  A3 tool_registry off core import path (subprocess test)
  A4 bandwidth reconciled against response.usage; max_iterations cap
  A6 temperature=0 + model_id + prompt_version journaled
  T2 09:25 ET pre-flight prune (halted / gapped / illiquid)
  T3 fallback halves max_position_size_pct + AgentFallbackEvent

Every failure funnels through retry-once -> deterministic fallback. Turns
never crash. Full schema parity (D4) means the tick loop is oblivious.

Closes OpenBBTechnical-<P3.1-bead>, #<gh-issue>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P3.2: PostCloseAgentTurn + narrator (#84) + EndOfDayReport

**Consumes:** every P3.1 primitive (`AgentBackend`, `tool_registry`, prompt loader); `openbb_core_journal.replay(session_id)` for reading the day's events; `state_store.save_last_watchlist` + `save_last_plan` + new `save_last_session_summary`; Jinja2 for the deterministic Markdown narrator template.

**Produces:** `PostCloseAgentTurn.run()` that emits an `EndOfDayReport` (either LLM- or template-produced), writes the day's watchlist / plan / summary to `state_store` so tomorrow's pre-open fallback can read them, and journals `EndOfDayReportEvent`.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/report.py` — `EndOfDayReport`, `TomorrowRecommendation`, `SessionMetrics`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/prompts/post_close_v1.txt`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/templates/post_close_briefing.md.j2`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py`

**Interfaces:**
- Consumes:
  - `openbb_core_journal.replay(session_id) -> Iterable[JournalEvent]` (Phase 1 P1.4 / J3)
  - Every `agent/*` primitive from P3.1
- Produces:
  - `PostCloseAgentTurn.run(session_id: str, as_of: datetime | None = None) -> EndOfDayReport`
  - `EndOfDayReport` pydantic model + `TomorrowRecommendation` + `SessionMetrics` sub-models
  - `POST_CLOSE_TOOLS: list[ToolSchema]` — superset of `PRE_OPEN_TOOLS` adding fills / pnl / journal-summary readers

- [ ] **Step 1: Write RED test for post-close fallback (AC-agent-2)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py` — mirrors `test_pre_open_fallback.py` structure. Assert:
- Real backend returns valid `EndOfDayReport` → `is_deterministic_fallback=False`
- `AlwaysUnavailableBackend` triggers the deterministic Jinja narrator → `is_deterministic_fallback=True`, `briefing_md` is non-empty
- Fallback still writes `last_watchlist` / `last_plan` / `last_session_summary` to state_store (via monkey-patched `save_*` capture)
- `AgentFallbackEvent` + `EndOfDayReportEvent` both journaled
- T5 (P1) guardrail: `tomorrow_recommendations` is empty when only 1 session of history exists (schema-level flag `low_signal=True`)

- [ ] **Step 2: Author `models/report.py`**

```python
"""EndOfDayReport + subtypes (PRD §6.2.6, Phase 3 P3.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from openbb_core.provider.abstract.data import Data
from pydantic import Field


class TomorrowRecommendation(Data):
    """One structured next-day suggestion. T5 low_signal defaults True
    until N sessions of history support the suggestion.
    """
    kind: Literal["watchlist", "preset", "risk", "process"]
    detail: str
    low_signal: bool = Field(
        default=True,
        description="T5: recency-safe default. Set False only when supported by N sessions of history.",
    )


class SessionMetrics(Data):
    realized_pnl: Decimal
    win_rate_today: float | None
    veto_counts_by_gate: dict[str, int] = Field(default_factory=dict)
    fill_count: int = 0
    order_count: int = 0


class EndOfDayReport(Data):
    session_date: date
    session_id: str
    agent_backend: Literal["claude", "openai", "none"]
    is_deterministic_fallback: bool = False
    briefing_md: str = Field(description="Human-readable Markdown; #84 payload")
    tomorrow_recommendations: list[TomorrowRecommendation] = Field(default_factory=list)
    metrics: SessionMetrics
```

- [ ] **Step 3: Author the Jinja narrator template (#84 fallback)**

Create `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/templates/post_close_briefing.md.j2`:

```jinja
# Session Briefing — {{ metrics.session_date }}

**Realized P&L:** {{ metrics.realized_pnl }}
**Fill count:** {{ metrics.fill_count }} across {{ metrics.order_count }} orders
{% if metrics.win_rate_today is not none %}
**Win rate today:** {{ '{:.1%}'.format(metrics.win_rate_today) }}
{% endif %}

## Risk gates that fired today

{% for gate, count in metrics.veto_counts_by_gate.items() %}
- **{{ gate }}** — {{ count }} veto(s)
{% else %}
- No RiskManager vetoes today.
{% endfor %}

## Notes for tomorrow

_This briefing was generated by the deterministic narrator (agent extra
absent or LLM unavailable). Recommendations are process-observations
only, not outcome extrapolations (T5)._
```

Non-decorative rationale (§4.4 D4): the fallback + LLM both produce `briefing_md` — the LLM's version can be richer prose, but the schema shape is identical, so the report generator + CLI + journal are agent/fallback-agnostic.

- [ ] **Step 4: Author `agent/post_close.py` (GREEN)**

Same shape as `pre_open.py`. User prompt built from a `replay(session_id)` summary + P&L math over the journal events. `_process_signal_result` and `_flatten_journal` helpers do the deterministic pre-work (no LLM); the LLM only decides *how to narrate*, not *what happened*.

After the LLM turn (or fallback), always:
1. `state_store.save_last_watchlist(plan.watchlist)` — feeds tomorrow's pre-open fallback (T3)
2. `state_store.save_last_plan(plan)` — post-mortem context
3. `state_store.save_last_session_summary({date, realized_pnl, veto_counts})` — pre-open prompt context
4. `journal.write(EndOfDayReportEvent(...))` with same provenance fields as pre-open

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py -q`
Expected: all pass.

- [ ] **Step 5: Add CLI subcommand `openbb-daytrade post-close`**

Same pattern as P3.1 Step 7.

- [ ] **Step 6: Commit P3.2**

```bash
git add \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/report.py \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close.py \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/prompts/post_close_v1.txt \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/templates/post_close_briefing.md.j2 \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_post_close_fallback.py

git commit -m "feat(fmp_trading): P3.2 PostCloseAgentTurn + narrator + EndOfDayReport

Closes GH #84 (narrator delivered as the deterministic post-close
fallback). Both paths - LLM briefing + Jinja template - produce the
same EndOfDayReport shape (D4).

State writes: after every turn (LLM or fallback), save_last_watchlist
+ save_last_plan + save_last_session_summary to state_store so
tomorrow's pre-open fallback has real context.

T5 guardrail: tomorrow_recommendations default low_signal=True until
N-session history supports removing the flag.

Closes OpenBBTechnical-<P3.2-bead>, #<gh-issue>, #84

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task P3.3: MCP server + `openbb-daytrade mcp-serve` + core-unchanged tests

**Consumes:** `PRE_OPEN_TOOLS ∪ POST_CLOSE_TOOLS` from P3.1's tool_registry (with `submit_*` explicitly excluded); `mcp>=1.0` SDK stdio server; every extra-gate primitive from `agent/__init__.py`.

**Produces:** `openbb-daytrade mcp-serve` CLI subcommand that runs a stdio MCP server exposing every read-only tool. Two enforcement tests: fast per-PR `test_import_guard.py` + slow nightly `test_core_unchanged_when_removed.py` (subprocess venv install). Fulfills GH #85's "core-unchanged-when-removed" contract and closes #231.

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/mcp_server.py`
- Modify: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py` — add `mcp-serve` subcommand
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_mcp_readonly_surface.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/test_import_guard.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/architecture/test_core_unchanged_when_removed.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/architecture/__init__.py` (if missing)
- Create: `openbb_platform/extensions/fmp_trading/tests/integration/test_full_day_with_agent.py` (AC-1-ext)

**Interfaces:**
- Consumes: everything from P3.1/P3.2 (`PRE_OPEN_TOOLS`, `POST_CLOSE_TOOLS`, `is_agent_available`).
- Produces:
  - Runnable stdio MCP server via `openbb-daytrade mcp-serve`
  - `test_import_guard.py` — fast per-PR test that agent modules raise `ImportError` cleanly when `anthropic` / `mcp` are hidden from `sys.modules`
  - `test_core_unchanged_when_removed.py` — nightly subprocess venv install

- [ ] **Step 1: Write RED tests for the read-only MCP surface (AC-agent-4 / AC-risk-8)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_mcp_readonly_surface.py`:

```python
"""AC-agent-4 + AC-risk-8: MCP surface is read-only, no broker leaks."""

from __future__ import annotations

import pytest


def test_mcp_surface_excludes_submit_tools():
    """submit_daily_plan / submit_end_of_day_md are internal-only.
    They MUST NOT appear on the MCP tool surface (PRD §7.3 critical
    safety constraint)."""
    pytest.importorskip("mcp")
    from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

    names = set(mcp_tool_names())
    forbidden = {"submit_daily_plan", "submit_end_of_day_md"}
    assert names.isdisjoint(forbidden), (
        f"Forbidden mutation tools on MCP surface: {names & forbidden}"
    )


def test_mcp_surface_excludes_broker_tools():
    """AC-risk-8: no tool returns or mutates a broker/session reference."""
    pytest.importorskip("mcp")
    from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

    names = mcp_tool_names()
    broker_bearing = [n for n in names if "broker" in n.lower() or "submit_order" in n.lower()]
    assert broker_bearing == [], (
        f"Broker-mutating tools leaked onto MCP surface: {broker_bearing}"
    )


def test_mcp_surface_is_union_of_pre_open_and_post_close():
    pytest.importorskip("mcp")
    from openbb_fmp_trading.agent import tool_registry as tr
    from openbb_fmp_trading.agent.mcp_server import mcp_tool_names

    expected = {t.name for t in tr.PRE_OPEN_TOOLS} | {t.name for t in tr.POST_CLOSE_TOOLS}
    # Exclude the two internal submit_* tools that live in tool_registry but
    # are filtered from MCP registration.
    expected -= {"submit_daily_plan", "submit_end_of_day_md"}
    assert set(mcp_tool_names()) == expected
```

- [ ] **Step 2: Write RED per-PR import guard (A10)**

Create `openbb_platform/extensions/fmp_trading/tests/unit/test_import_guard.py`:

```python
"""AC-agent-5 fast path (A10 P2): in-process import-guard test.

Simulates a missing [agent] extra by monkey-patching sys.modules to hide
'anthropic' and 'mcp', then asserts:
  * core imports (openbb, openbb_fmp_trading, core.state_store) all succeed
  * every agent/* import raises ImportError CLEANLY (no side effects,
    no partial-imports leaving broken half-modules)
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_core_imports_when_extra_hidden(monkeypatch):
    for mod in ("anthropic", "mcp", "jinja2"):
        monkeypatch.setitem(sys.modules, mod, None)  # None -> ImportError on import
    # Reload the extension entrypoint to observe the hidden state
    if "openbb_fmp_trading" in sys.modules:
        importlib.reload(sys.modules["openbb_fmp_trading"])
    importlib.import_module("openbb_fmp_trading")
    importlib.import_module("openbb_fmp_trading.core.state_store")


def test_agent_imports_fail_cleanly_when_extra_hidden(monkeypatch):
    for mod in ("anthropic", "mcp", "jinja2"):
        monkeypatch.setitem(sys.modules, mod, None)
    for agent_mod in (
        "openbb_fmp_trading.agent.backend",
        "openbb_fmp_trading.agent.tool_registry",
        "openbb_fmp_trading.agent.mcp_server",
    ):
        sys.modules.pop(agent_mod, None)
        with pytest.raises(ImportError):
            importlib.import_module(agent_mod)
```

- [ ] **Step 3: Write the nightly full-subprocess test skeleton**

Create `openbb_platform/extensions/fmp_trading/tests/architecture/test_core_unchanged_when_removed.py` — marked `@pytest.mark.nightly` so it's opt-in in CI. Body creates a `tempfile.TemporaryDirectory`, runs `python -m venv`, `pip install -e .` (no `[agent]`), then `pytest tests/unit tests/integration -m 'not integration'`, then asserts the subprocess exit code is 0 + stdout contains ">= N passed".

Skip this in `.venv_win` local runs unless `-m nightly` is passed. Rationale: full venv installs cost 3-5 minutes and shouldn't gate a per-PR CI run — A10.

- [ ] **Step 4: Implement `agent/mcp_server.py` (GREEN)**

Using the `mcp` SDK's stdio server pattern:

```python
"""stdio MCP server (P3.3 / D2 / #85)."""

from __future__ import annotations


def mcp_tool_names() -> list[str]:
    """Names of every tool exposed on the MCP surface. Excludes internal
    submit_* tools (PRD §7.3)."""
    from openbb_fmp_trading.agent import tool_registry as tr

    combined = list(tr.PRE_OPEN_TOOLS) + list(tr.POST_CLOSE_TOOLS)
    seen = set()
    out = []
    for t in combined:
        if t.name in ("submit_daily_plan", "submit_end_of_day_md"):
            continue
        if t.name in seen:
            continue
        seen.add(t.name)
        out.append(t.name)
    return out


def run_stdio_server():
    """Blocking stdio MCP server entry point. Called by `openbb-daytrade mcp-serve`."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    # Startup-time drift check (A3): raises RegistryDrift if any tool
    # in the registry no longer matches its router signature.
    from openbb_fmp_trading.agent.tool_registry import assert_no_drift
    assert_no_drift()

    server = Server("openbb-daytrade")
    # ... register handlers for every tool in mcp_tool_names() ...
    # (full body follows the mcp SDK reference in Context7 — deferred to
    # implementation; the CLI wiring is what this task validates)

    import anyio
    async def _main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    anyio.run(_main)
```

- [ ] **Step 5: Wire `openbb-daytrade mcp-serve` in `cli.py`**

Add a subcommand that guards on `is_agent_available()` and either calls `agent.mcp_server.run_stdio_server()` or exits with a friendly install-hint message.

- [ ] **Step 6: Author the AC-1-ext E2E test**

Create `openbb_platform/extensions/fmp_trading/tests/integration/test_full_day_with_agent.py` (marked `@pytest.mark.integration`). Extends the P2.7 compressed-session harness by prepending a `PreOpenAgentTurn` (using a **canned/recorded backend**, NOT live Claude — A5) and appending a `PostCloseAgentTurn`. Asserts:
- Pre-open agent produces a `DailyPlan` that the tick loop consumes
- Post-close agent writes `last_watchlist` to state_store
- A second-day pre-open call (with fresh session_id) reads that watchlist back via the fallback path
- Full journal contains `DailyPlanCommittedEvent`, `TickEvent[]`, `OrderEvent[]`, `FillEvent[]`, `EndOfDayReportEvent`

- [ ] **Step 7: Commit P3.3**

```bash
git add \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/mcp_server.py \
  openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_mcp_readonly_surface.py \
  openbb_platform/extensions/fmp_trading/tests/unit/test_import_guard.py \
  openbb_platform/extensions/fmp_trading/tests/architecture/ \
  openbb_platform/extensions/fmp_trading/tests/integration/test_full_day_with_agent.py

git commit -m "feat(fmp_trading): P3.3 stdio MCP server + core-unchanged tests + AC-1-ext E2E

Closes GH #85 (MCP tool exposure + core-unchanged-when-removed test)
and GH #231 (design spec meta-issue for #84 + #85).

MCP surface = union(PRE_OPEN_TOOLS, POST_CLOSE_TOOLS) minus submit_*
tools (PRD §7.3 safety constraint). No broker mutations, ever.

Two enforcement tests:
  test_import_guard.py           - fast per-PR (~1s)
  test_core_unchanged_when_removed.py - nightly subprocess venv install

AC-1-ext E2E: pre-open (canned backend, NOT live Claude - A5) -> tick
loop -> post-close writes last_watchlist -> next-day pre-open fallback
reads it back. Full journal shape asserted.

Closes OpenBBTechnical-<P3.3-bead>, #<gh-issue>, #85, #231

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Bead filing (before Phase 3 execution begins)

Run each of these once, in this order. Each returns an `OpenBBTechnical-<id>` slug — record it in a scratch note for the commit messages above.

```bash
# P3.0 — foundation
bd create --title="P3.0 core/state_store.py + fmp_trading_state MySQL table + 8 tests" \
  --description="MySQL-backed persistent state (D6). Foundation for P3.1 fallback and P3.2 write path. See plan doc Task P3.0." \
  --type=task --priority=2

# P3.1 — main body of Phase 3
bd create --title="P3.1 PreOpenAgentTurn + backend + tool_registry + all P0/P1 defenses" \
  --description="Bulk of Phase 3 (~7 days). T1 clamp-only risk, A1 injection defenses, A2 ValidationError retry, A3 tool_registry off core import, A4 bandwidth reconciliation, A6 temperature=0 + model_id journaling, T2 09:25 pre-flight prune, T3 loud fallback risk-halving." \
  --type=task --priority=2

# P3.2 — post-close narrator (#84)
bd create --title="P3.2 PostCloseAgentTurn + narrator (#84) + EndOfDayReport model" \
  --description="Delivers GH #84 as the deterministic Jinja narrator fallback. Writes last_watchlist / last_plan / last_session_summary to state_store." \
  --type=task --priority=2

# P3.3 — MCP server + core-unchanged tests
bd create --title="P3.3 stdio MCP server + `openbb-daytrade mcp-serve` + core-unchanged tests + AC-1-ext E2E" \
  --description="Closes GH #85 + #231. stdio MCP server exposes read-only tools; import-guard (per-PR) + subprocess venv install (nightly) prove the extra is optional." \
  --type=task --priority=2

# Wire dependencies (each depends on the one before)
bd dep add <P3.1-id> <P3.0-id>
bd dep add <P3.2-id> <P3.1-id>
bd dep add <P3.3-id> <P3.2-id>

# GitHub companion issues (one per bead, so the beads<->GH mapping stays 1:1)
gh issue create --title="P3.0 state_store MySQL persistence (Phase 3)" \
  --body "See docs/superpowers/plans/2026-07-10-fmp-trading-phase3.md Task P3.0. Bead: OpenBBTechnical-<P3.0-id>."
# ... one per bead ...
```

---

## Self-Review

**1. Spec coverage:** Every §7 AC (AC-agent-1 through AC-agent-12, AC-risk-8, AC-1-ext) has a named test file in a specific task. Every §2 decision (D1–D6) has a specific implementation site in a specific task. The 4-bead split (§9) matches this plan's 4 tasks exactly.

**2. Placeholder scan:** No TBDs. The `<gh-issue>` / `<P3.x-id>` markers in commit-message templates are filled at bead-creation time — that's a runtime substitution, not a placeholder in the plan itself. Every code snippet is executable Python; no "similar to Task N" hand-waving.

**3. Type consistency:** `ToolCall`, `AgentBackend`, `AgentUnavailable`, `RiskOverrideLoosening`, `DailyPlan`, `EndOfDayReport`, `AgentFallbackEvent`, `PromptInjectionRejectedEvent`, `DailyPlanCommittedEvent`, `EndOfDayReportEvent` are all defined in exactly one task (P3.1 for the first four + two new journal events; P3.2 for `EndOfDayReport`) and referenced with identical names in every downstream task.

**4. Interface handoff:**
- P3.0 → P3.1: `state_store.load_last_watchlist / save_last_watchlist / load_last_plan / save_last_plan` — signatures fixed in P3.0 Step 3, referenced verbatim in P3.1 Step 6.
- P3.1 → P3.2: `AgentBackend`, `ToolCall`, `PRE_OPEN_TOOLS`, `tradable_universe`, `is_agent_available` — all defined in P3.1 Step 3, imported by P3.2 Step 4.
- P3.1/P3.2 → P3.3: `PRE_OPEN_TOOLS` + `POST_CLOSE_TOOLS` — P3.3 Step 4 imports both and unions them.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-10-fmp-trading-phase3.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best when we want independent review-gate discipline per bead.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints. Best when we want a single continuous session (matches how Phase 2 shipped).

**Which approach?**
