# fmp-trading Phase 3 — Agent turns + MCP tool server (design spec)

**Date:** 2026-07-10
**Author:** fmp-trading working group
**Status:** Draft — for user approval before Phase 3 planning
**Scope:** Design gate for the openbb-dev-cycle skill's Phase 1 (Design & Brainstorming). Turns PRD §7 into concrete implementation decisions. **Depends on** Phase 2 (`origin/fmp_trading @ d0632b9d1`), which shipped `IntradaySession`, `RiskManager`, `BandwidthMeter`, `openbb_core_journal.JournalWriter`, and the `_process_signal` chokepoint.

**Closes on Phase 3 completion:**
- GitHub #85 (MCP tool exposure + core-unchanged-when-removed test)
- GitHub #84 (Narrator — delivered as PostCloseAgentTurn's deterministic fallback per PRD Table §2.4 line 53–54)
- GitHub #231 (Design spec meta-issue for #84+#85 — this document)

---

## 1. Goal

Give the deterministic Phase 2 execution core a **two-turn agentic discovery layer**:

1. A one-shot **PreOpenAgentTurn** at 07:30 ET that produces a committed `DailyPlan` (watchlist + preset + alerts + risk overrides + thesis) which the market-hours tick loop consumes verbatim.
2. A one-shot **PostCloseAgentTurn** at 16:15 ET that reads the day's journal + fills and produces an `EndOfDayReport` (Markdown briefing + structured recommendations for tomorrow) — also serving as the deliverable for #84 (narrator).
3. An **MCP tool server** (`openbb-daytrade mcp-serve`) that exposes the same read-only tools external LLM clients (Claude Desktop, VS Code MCP, custom) can call — closing #85.

**Non-goals** (deferred to later phases per PRD §10):
- Mid-day agent intervention. Both turns are one-shot; the tick loop never invokes the LLM.
- Live routing / real broker. Phase 3 stays on `StatefulTestBroker`-shaped simulation.
- UX. CLI + MCP only; no notebook/desktop surface.
- Options / futures / crypto. Equities only.

---

## 2. User-locked foundational decisions

Recorded from the brainstorming gate (2026-07-10):

| # | Decision | Rationale |
|---|---|---|
| **D1** | **Agent runtime:** Anthropic Claude Agent SDK (Python, `anthropic` + `anthropic[bedrock]` optional) | Native forced tool-calling, structured output via `tool_choice`, and MCP-server support in one dep. Aligns with the openbb-dev-cycle default model. PRD's `agent_backend` field defaults to `"claude"`. |
| **D2** | **MCP packaging:** stdio server as `openbb-daytrade mcp-serve` CLI subcommand | Matches Claude Desktop + VS Code MCP client expectations. No new HTTP infra. Follows the `openbb-daytrade doctor` CLI pattern from P1.6. |
| **D3** | **Tool schemas:** auto-generated from `obb.fmp_trading.*` Router signatures at import time | Single source of truth. "Core-unchanged-when-removed" test (#85 AC) becomes trivial: assert the extra adds no new Router entries. Uses OpenBB's existing type-hint → JSON-schema pipeline. |
| **D4** | **Fallback shape:** full schema parity — deterministic fallback returns a `DailyPlan` / `EndOfDayReport` identical in shape to the LLM output | Downstream code (tick loop, journal, report generator) treats agent-produced and fallback-produced objects interchangeably; only `agent_backend='none'` + `is_deterministic_fallback=True` flags reveal provenance. |
| **D5** | **Bead split:** 3 sub-tasks — P3.1 pre-open turn, P3.2 post-close turn, P3.3 MCP server | Delivers operator-visible value first (pre-open ships a working DailyPlan). Each sub-task ships with its own tests + fallback + CLI subcommand. |
| **D6** | **Persistent state backend:** MySQL (reuse the `fmp_cached` connection) — new `fmp_trading_state` table + `state_store.py` helper. No JSON-on-disk. | Consolidates persistence on one backend. Backups + multi-machine access come for free from the existing MySQL infra. Avoids "half-in-DB, half-on-disk" split that the plan doc originally implied. |

---

## 3. Architecture (Approach C, PRD-approved)

```
┌─────────────────────────── 07:30 ET ────────────────────────────┐
│  PreOpenAgentTurn.run()                                          │
│    ├─ Bandwidth: charge_agent_turn_budget()                      │
│    ├─ Backend: ClaudeAgentBackend (or DeterministicFallback)     │
│    │    ├─ Tool set: pre_open_tools (read-only subset)           │
│    │    ├─ Forced tool-calling → submit_daily_plan(...)          │
│    │    └─ Validated → DailyPlan pydantic instance               │
│    ├─ Journal: DailyPlanCommittedEvent                           │
│    └─ Returns: DailyPlan                                         │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────── 09:30 – 16:00 ET (Phase 2) ──────────┐
        │  IntradaySession.run() — tick loop              │
        │    reads DailyPlan; agent never called          │
        └─────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────── 16:15 ET ────────────────────────────┐
│  PostCloseAgentTurn.run()                                        │
│    ├─ Bandwidth: charge_agent_turn_budget()                      │
│    ├─ Journal reader: replay(session_id) → events                │
│    ├─ Backend: ClaudeAgentBackend (or DeterministicFallback)     │
│    │    ├─ Tool set: post_close_tools (read-only, adds fills/pnl)│
│    │    ├─ Forced tool-calling → submit_end_of_day_md(...)       │
│    │    └─ Validated → EndOfDayReport pydantic instance          │
│    ├─ Journal: EndOfDayReportEvent                               │
│    └─ Returns: EndOfDayReport                                    │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌───────────── Always-on (opt-in) ────────────────┐
        │  openbb-daytrade mcp-serve                       │
        │    stdio MCP server exposing read-only tools     │
        │    External clients: Claude Desktop, VS Code MCP │
        └─────────────────────────────────────────────────┘
```

### Module layout

New files (all under `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/`):

```
agent/
├── __init__.py               # Extra-gated re-exports (see §6.2)
├── backend.py                # AgentBackend Protocol + ClaudeAgentBackend impl
├── tool_registry.py          # Auto-generate tool schemas from obb.fmp_trading.*
├── pre_open.py               # PreOpenAgentTurn + deterministic fallback
├── post_close.py             # PostCloseAgentTurn + deterministic fallback (narrator #84)
├── mcp_server.py             # stdio MCP server (openbb-daytrade mcp-serve)
├── prompts/
│   ├── pre_open.txt          # Loaded at import; edited without touching code
│   └── post_close.txt
└── tests/
    ├── unit/
    │   ├── test_backend_protocol.py
    │   ├── test_tool_registry.py
    │   ├── test_state_store.py             # persistence round-trip (see §6.5)
    │   ├── test_pre_open_fallback.py       # AC-agent-1
    │   ├── test_post_close_fallback.py     # AC-agent-2
    │   └── test_mcp_readonly_surface.py    # AC-risk-8 (no broker tools)
    ├── integration/
    │   └── test_full_day_with_agent.py     # AC-1 extended: agent → tick loop → agent
    └── architecture/
        └── test_core_unchanged_when_removed.py  # #85 AC
```

**State-persistence module** (lives in `core/` next to `bandwidth.py`, not under `agent/`, because it's a general-purpose primitive the tick loop and both agent turns share):

```
core/
├── state_store.py            # MySQL-backed persistent state (see §6.5)
```

Existing files touched (minimal — most Phase 3 code is additive):

- `openbb_platform/extensions/fmp_trading/pyproject.toml` — add `[agent]` extra with `anthropic>=0.40`, `mcp>=1.0`.
- `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli.py` — add `mcp-serve` subcommand (follows `doctor` pattern).
- `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/plan.py` — no changes (`DailyPlan` shape already matches PRD §7.1).
- `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/journal_events.py` — add `DailyPlanCommittedEvent` + `EndOfDayReportEvent` typed subclasses.

---

## 4. Component designs

### 4.1 AgentBackend Protocol (`agent/backend.py`)

```python
class AgentBackend(Protocol):
    """A one-shot LLM call that forces the model to emit structured output
    via a required final tool call. Stateless: no session mgmt, no caching.
    """
    def run_turn(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[ToolSchema],
        required_final_tool: str,
        max_tokens: int = 4096,
        budget: BandwidthMeter | None = None,
    ) -> ToolCall:
        """Execute the turn; return the args of the required final tool.

        Raises AgentUnavailable if the SDK is missing or the API errors
        after retry. Callers catch this and fall through to their
        deterministic fallback.
        """
```

Two implementations ship in Phase 3:
- `ClaudeAgentBackend` (real, requires `[agent]` extra) — wraps `anthropic.Anthropic().messages.create(...)` with `tool_choice={"type": "tool", "name": required_final_tool}`.
- `DeterministicFallbackBackend` (always present) — raises `AgentUnavailable` unconditionally. Exists so the turn wrapper can catch identically whether the extra is missing or an API call failed.

**Why a Protocol not an ABC:** matches Python's structural typing convention already in use across `openbb_core.provider.abstract.fetcher`. Third-party backends (OpenAI, Bedrock, local) can be added later without inheritance.

### 4.2 Tool Registry (`agent/tool_registry.py`)

Walks `obb.fmp_trading` at import time and emits tool schemas via OpenBB's existing Router → JSON-schema pipeline (already used by the REST API and CLI). Two curated tool lists:

- **`PRE_OPEN_TOOLS`** — read-only movers/snapshot/news commands. Explicit allowlist (not "everything in the router").
- **`POST_CLOSE_TOOLS`** — read-only journal / fills / PnL commands. Superset of `PRE_OPEN_TOOLS` because post-close needs to inspect the session's outcome.

The MCP server (D2) exposes the union of both. **Neither list includes** `submit_order`, `broker.*`, `session.close`, or any mutation. This is what makes AC-risk-8 (no broker tools) testable.

**Registry validation** runs at import time and raises `RegistryDrift` if a tool's Router signature no longer matches its cached schema — catches drift the moment `obb.fmp_trading.*` changes shape.

### 4.3 PreOpenAgentTurn (`agent/pre_open.py`)

```python
@dataclass
class PreOpenAgentTurn:
    config: DailyConfig
    backend: AgentBackend
    bandwidth: BandwidthMeter
    journal: JournalWriter

    def run(self, as_of: datetime | None = None) -> DailyPlan:
        as_of = as_of or datetime.now(timezone.utc)
        try:
            tool_call = self.backend.run_turn(
                system_prompt=PRE_OPEN_SYSTEM_PROMPT,
                user_prompt=self._build_user_prompt(as_of),
                tools=PRE_OPEN_TOOLS,
                required_final_tool="submit_daily_plan",
                budget=self.bandwidth,
            )
            plan = DailyPlan.model_validate(tool_call.args)
        except AgentUnavailable:
            plan = self._deterministic_fallback(as_of)

        self.journal.write(DailyPlanCommittedEvent(
            ts=as_of, session_id=plan.date.isoformat(),
            payload={"agent_backend": plan.agent_backend,
                     "is_deterministic_fallback": plan.is_deterministic_fallback,
                     "watchlist_size": len(plan.watchlist),
                     "preset": plan.preset},
        ))
        return plan
```

**Fallback (D4)** — yesterday's watchlist (from the `fmp_trading_state` MySQL table via `state_store.load_last_watchlist()` — see §6.5) + `trend_follow` preset + empty alerts + default `RiskConfig`. Same `DailyPlan` shape; `agent_backend="none"` and `is_deterministic_fallback=True`. If no prior watchlist exists (first-ever run OR the DB row is absent), fall back further to the `DailyConfig.default_watchlist` field.

**CLI:** `openbb-daytrade pre-open [--config path] [--dry-run]` — dry-run stops after the tool call but doesn't journal.

### 4.4 PostCloseAgentTurn (`agent/post_close.py`)

Same shape as PreOpen. User prompt built by feeding the day's journal events through `openbb_core_journal.replay()` and summarizing fills + P&L + veto counts. Fallback delivers #84's deterministic narrator: a Markdown briefing generated from a Jinja template applied to the session's `EndOfDayReport` sub-fields.

**Template location:** `agent/templates/post_close_briefing.md.j2`. Ships with the deterministic fallback path; the LLM turn can also request it as one of its tools if it wants a "structured template starting point" (D4 parity).

### 4.5 MCP Server (`agent/mcp_server.py`)

Uses the official `mcp` Python SDK (`pip install mcp`). Registers tools from the union of `PRE_OPEN_TOOLS` + `POST_CLOSE_TOOLS`. **Does NOT register** `submit_daily_plan` or `submit_end_of_day_md` — those are internal to the built-in turns (PRD §7.3 critical safety constraint).

**Launch:** `openbb-daytrade mcp-serve` — stdio transport, no config file, no HTTP.

**"Core-unchanged-when-removed" test (#85 AC):** a subprocess-level test in `tests/architecture/test_core_unchanged_when_removed.py` that:
1. Creates a fresh venv,
2. Installs `openbb-fmp-trading` **without** the `[agent]` extra,
3. Runs the full unit + integration test suite,
4. Asserts every non-agent test passes and every `agent/*` import raises `ImportError` cleanly (no partial-import crashes elsewhere in the codebase).

---

## 5. Data models added

Two typed `JournalEvent` subclasses in `models/journal_events.py`:

```python
class DailyPlanCommittedEvent(JournalEvent):
    event_type: Literal["daily_plan_committed"] = "daily_plan_committed"

class EndOfDayReportEvent(JournalEvent):
    event_type: Literal["end_of_day_report"] = "end_of_day_report"
```

One new pydantic model in `models/report.py`:

```python
class EndOfDayReport(Data):
    session_date: date
    session_id: str
    agent_backend: Literal["claude", "openai", "none"]
    is_deterministic_fallback: bool
    briefing_md: str = Field(description="Human-readable Markdown; #84 payload")
    tomorrow_recommendations: list[TomorrowRecommendation]
    metrics: SessionMetrics  # realized_pnl, win_rate, veto_counts_by_gate, etc.
```

`TomorrowRecommendation` and `SessionMetrics` shapes ship in the same file. `DailyPlan` needs no schema changes.

---

## 6. Cross-cutting concerns

### 6.1 Bandwidth budget

Both turns charge the `BandwidthMeter` before making the LLM call:
- `charge_agent_turn_budget(estimated_tokens=8000)` for pre-open
- `charge_agent_turn_budget(estimated_tokens=12000)` for post-close (larger journal replay context)

If the meter is in `conservation` or `halted` mode, the turn skips the LLM call and goes straight to the deterministic fallback. Journaled as `BandwidthDegradedEvent` (new subclass).

### 6.2 Extra gating (`pyproject.toml`)

```toml
[tool.poetry.extras]
agent = ["anthropic (>=0.40)", "mcp (>=1.0)", "jinja2 (>=3.1)"]
```

`agent/__init__.py` uses a try/except import guard:

```python
try:
    from anthropic import Anthropic
    _AGENT_EXTRA_AVAILABLE = True
except ImportError:
    _AGENT_EXTRA_AVAILABLE = False

def is_agent_available() -> bool:
    return _AGENT_EXTRA_AVAILABLE
```

`ClaudeAgentBackend.__init__` raises `AgentUnavailable("install openbb-fmp-trading[agent]")` if `_AGENT_EXTRA_AVAILABLE` is False. `PreOpenAgentTurn` and `PostCloseAgentTurn` catch that and fall through — same code path as an API error.

### 6.3 Security invariants (from PRD §14)

Enforced by architecture tests:
- **AC-risk-8:** `test_no_broker_tools.py` inspects `PRE_OPEN_TOOLS + POST_CLOSE_TOOLS` and asserts none returns or mutates a broker/session reference (grep on tool schema `name` + a smoke run that intercepts `broker.submit` at the module level).
- **#85 AC:** `test_core_unchanged_when_removed.py` (see §4.5).
- **API-key handling:** `ANTHROPIC_API_KEY` read from environment only; never journaled, never in prompts.

### 6.4 Prompt engineering discipline

System prompts live in `agent/prompts/*.txt` (plain text, no Jinja). Edited without touching Python code. Every prompt starts with an explicit **"You MUST call the `submit_*` tool exactly once as your final action"** to reinforce the SDK's `tool_choice` constraint at the model level too.

Prompt versioning: filename includes a version suffix (`pre_open_v1.txt`). Tests pin the version, so a prompt change requires an explicit test update.

### 6.5 Persistent state layer (`core/state_store.py`) — D6

**Backend:** MySQL, via the same connection helpers `fmp_cached` uses (`openbb_fmp_cached.utils.database.execute_query` / `execute_many`). No new dependency; credentials come from the existing `~/.openbb_platform/user_settings.json` `mysql_*` block.

**Schema — new table `fmp_trading_state`:**

```sql
CREATE TABLE IF NOT EXISTS fmp_trading_state (
  state_key   VARCHAR(80)  NOT NULL,          -- 'last_watchlist', 'last_plan', etc.
  scope       VARCHAR(80)  NOT NULL DEFAULT 'default',   -- multi-profile support
  payload     JSON         NOT NULL,
  updated_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                             ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key, scope),
  INDEX idx_updated_at (updated_at)
);
```

Registered in `openbb_fmp_cached.utils.cache_schema.FLATTENED_TABLES` alongside `ttl_cache` (P2.2). The registration is a one-liner — `create_fmp_trading_state_table()` follows the same function-per-table pattern.

**Why one JSON-payload column vs. per-key typed columns:**
- State keys are heterogeneous (`list[str]` for watchlist, full `DailyPlan` dict for last plan, dict for cursor positions).
- Adding a new state key never requires a migration — write it, read it.
- JSON lookups are still primary-key-indexed via `state_key`, so single-row reads are O(1).

**API surface (`state_store.py`):**

```python
def load_state(key: str, scope: str = "default") -> Any | None:
    """Return the deserialized payload or None if the key is absent.
    On DB failure, returns None (never fail-fast — same resilience
    pattern as create_ttl_wrapper_class from P2.2)."""

def save_state(key: str, payload: Any, scope: str = "default") -> None:
    """UPSERT the payload as JSON. On DB failure, logs and best-effort
    suppresses — the calling turn continues with its in-memory value."""

def load_last_watchlist(scope: str = "default") -> list[str] | None:
    """Convenience wrapper: load_state('last_watchlist')."""

def save_last_watchlist(symbols: list[str], scope: str = "default") -> None:
    """Convenience wrapper: save_state('last_watchlist', symbols)."""
```

**State keys shipped in Phase 3** (not exhaustive — new keys land as needs arise):

| Key | Type of payload | Written by | Read by |
|---|---|---|---|
| `last_watchlist` | `list[str]` | PostCloseAgentTurn (records the day's plan.watchlist) | PreOpenAgentTurn deterministic fallback |
| `last_plan` | full `DailyPlan.model_dump()` | PreOpenAgentTurn on successful commit | PostCloseAgentTurn context builder; operator inspection via CLI |
| `last_session_summary` | `{date, realized_pnl, veto_counts}` | SessionEndEvent handler | PreOpenAgentTurn prompt context |
| `bandwidth_month` | `{month, used_bytes, mode}` | BandwidthMeter (migrated from disk in Phase 1 P1.5 — deferred to a follow-up bead, not Phase 3 blocking) | BandwidthMeter itself |

**Resilience contract:** every `load_state` / `save_state` call is wrapped in try/except; DB unavailability degrades gracefully to "no prior state" (fallback returns `None`, save is best-effort). This matches the P2.2 `create_ttl_wrapper_class` pattern exactly — SELECT failures fall through, UPSERT failures are logged and suppressed.

**Scope column** — supports multi-profile setups later (e.g., `scope='paper'` vs. `scope='live'`) without a schema change. Phase 3 hardcodes `scope='default'` in every call site; the arg exists for future work.

**Migration from any disk-based state** — Phase 3 is the first place these state keys are written; there is no legacy disk file to migrate. The one Phase 1 disk file (BandwidthMeter's monthly counter) stays on disk in Phase 3 and gets migrated in a follow-up bead (`bd remember` note filed for tracking).

**Test surface (`tests/unit/test_state_store.py`):**
1. Round-trip: `save_state("foo", {"bar": 1})` → `load_state("foo")` returns `{"bar": 1}`.
2. Absent-key: `load_state("never-set")` returns `None`.
3. UPSERT: two saves with the same key overwrite; `updated_at` advances.
4. DB failure (mocked): `save_state` doesn't raise; `load_state` returns `None`.
5. Scope isolation: `save_state("k", 1, scope="a")` doesn't touch `scope="b"`.
6. `load_last_watchlist` returns `list[str]` shape and survives JSON round-trip.

---

## 7. Acceptance criteria

Every AC below has a corresponding test file listed in §4.

| AC | Description | Test |
|---|---|---|
| AC-agent-1 | Pre-open turn produces a valid `DailyPlan` from the LLM, OR falls back to deterministic on `AgentUnavailable` | `test_pre_open_fallback.py` |
| AC-agent-2 | Post-close turn produces a valid `EndOfDayReport` OR falls back to deterministic Markdown briefing (#84 delivery) | `test_post_close_fallback.py` |
| AC-agent-3 | Tool registry auto-generates schemas from `obb.fmp_trading.*` router; drift is detected at import | `test_tool_registry.py` |
| AC-agent-4 | MCP server exposes only read-only tools; `submit_*` and `broker.*` are not registered | `test_mcp_readonly_surface.py` |
| AC-agent-5 | Removing the `[agent]` extra leaves the deterministic core fully functional (#85 AC) | `test_core_unchanged_when_removed.py` |
| AC-agent-6 | Persistent state round-trips through MySQL: `save_state` → `load_state` returns identical payload; DB failure degrades to `None` without raising | `test_state_store.py` |
| AC-risk-8 | Agent turns cannot access `PaperBroker`; tool-set inspection asserts none returns broker refs | (part of AC-agent-4) |
| AC-1-ext | Full day E2E: pre-open agent → tick loop → post-close agent writes `last_watchlist` → next-day pre-open fallback reads it | `test_full_day_with_agent.py` |

---

## 8. Global constraints (inherited from PRD)

- **P1** deterministic core — LLM confined to the two one-shot turns. Tick loop never calls the LLM.
- **P2** `Decimal` for money — every fill / recommendation / metric uses `Decimal(str(...))`.
- **P3** no look-ahead — post-close report can inspect anything the journal recorded; pre-open turn has no access to same-day fills (there aren't any yet).
- **P4** flat by 15:55 — Phase 2's flat-by-close cascade runs before post-close agent fires.
- **P5** `exchange_calendars` — turn scheduling honors half-day sessions (pre-open still at 07:30 ET; post-close at close+15min).
- **P6** bandwidth meter — turns respect the meter's mode (§6.1).
- **P7** RiskManager chokepoint — MCP surface omits every mutation; `submit_daily_plan` is only callable from the built-in `PreOpenAgentTurn`.

---

## 9. Roadmap → Phase 3 planning

Each of these ships as an independent bd bead + GH issue (D5 split):

- **P3.0** `core/state_store.py` + `fmp_trading_state` MySQL table + 6 unit tests (~1 day) — foundation for D6. Ships first because P3.1's fallback path depends on `load_last_watchlist`.
- **P3.1** PreOpenAgentTurn + backend Protocol + ClaudeAgentBackend + tool_registry (bulk of the work: ~5 days) — closes GH #85's tool-registry piece and lays MCP groundwork
- **P3.2** PostCloseAgentTurn + narrator template + EndOfDayReport model + writes `last_watchlist` + `last_plan` + `last_session_summary` via state_store (~3 days) — closes GH #84
- **P3.3** MCP server + `openbb-daytrade mcp-serve` CLI + core-unchanged test (~2 days) — closes GH #85 fully + GH #231 (design meta-issue)

**Sequence:** P3.0 → P3.1 → P3.2 → P3.3. P3.0 (state store) delivers the persistence primitive P3.1's fallback and P3.2's write path both consume; the small ~1-day cost prevents having to stub `last_watchlist` reads in every fallback test.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Anthropic SDK breaking changes mid-Phase-3 | Pin to `anthropic>=0.40,<1.0` in `[agent]` extra; upgrade in a separate bd bead post-P3.3 |
| Tool registry drift when `obb.fmp_trading.*` router changes | `RegistryDrift` exception at import time forces schema regen before the next test run |
| Prompt version churn breaks the `EndOfDayReport` schema | Pydantic `model_validate` on the tool-call args catches this; test asserts on the schema, not the prompt output |
| MCP client compat (stdio version mismatch) | Test matrix covers `mcp>=1.0`; document minimum Claude Desktop version in the CLI help |
| LLM cost creep from long agent turns | `budget: BandwidthMeter | None` param + explicit `max_tokens` per turn; billing dashboard deferred to Phase 6 |
| Circular imports (agent/ imports openbb.obb) | Agent modules do `from openbb import obb` inside function bodies, not at module load |
| MySQL unavailable during pre-open turn | `state_store.load_last_watchlist()` returns `None` on DB error; fallback further degrades to `DailyConfig.default_watchlist`. Never fail-fast — market open doesn't wait for the DB. |
| Concurrent writes to `fmp_trading_state` from two profiles | `scope` column keys the write; PK is `(state_key, scope)`. Same-scope races are rare (one operator per scope) but ON DUPLICATE KEY UPDATE is atomic. |

---

## 11. Open questions

**None.** All prior open questions have been resolved by the user-locked D1–D5 decisions or by explicit inheritance from the PRD.

---

## 12. Spec self-review

- ✅ **Placeholder scan** — no TBDs, no vague "handle appropriately" bullets. Every AC has a named test file.
- ✅ **Internal consistency** — the 3-way bead split (§9) matches the tool registry / turn implementations (§4), which match the acceptance criteria (§7).
- ✅ **Scope check** — Phase 3 is one design; it decomposes into 3 buildable beads. No new subsystem hiding under a bullet.
- ✅ **Ambiguity check** — "read-only" is defined explicitly as "the union of `PRE_OPEN_TOOLS` + `POST_CLOSE_TOOLS`, which excludes every `submit_*` and every `broker.*`." "Deterministic fallback" is defined explicitly as "same schema, different provenance flag."
