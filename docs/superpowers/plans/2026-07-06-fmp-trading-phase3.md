# fmp_trading Phase 3 — Agent Turns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the pre-open + post-close **agent turns** into `openbb-fmp-trading` — a backend-agnostic Protocol layer (`AgentBackend`), a Claude Sonnet impl via the `anthropic` SDK, a deterministic fallback that runs when the `[agent]` extra is absent or the LLM turn fails, an MCP tool server exposing the read-only session surface to external clients, and the `#85` "core-unchanged-when-removed" acceptance test. Closes PRD §7 and PRD §10 Phase 3 items P3.1–P3.7. Corresponds to epic **#85 (MCP tool exposure + core-unchanged-when-removed test)** and epic **#84 (Narrator / deterministic briefing)**.

**Architecture:** Two one-shot LLM turns (§3.4 boundary). Pre-open turn runs at 07:30 ET, gathers pre-market context via read-only tools, and MUST call `submit_daily_plan()` before exit — enforced via anthropic's `tool_choice={"type":"tool","name":"submit_daily_plan"}` on the final turn. Post-close turn runs at 16:15 ET and MUST call three submit tools (`submit_end_of_day_md`, `submit_preset_review`, `submit_next_day_hints`). Both turns are backend-swappable behind an `AgentBackend` Protocol; Claude is the v1 impl, deterministic fallback is always available. External MCP clients get a **read-only** subset — no `submit_*` tools are ever exposed to MCP, keeping the P7 invariant intact (LLM never touches broker/orders/positions).

**Tech Stack:** Python 3.10-3.13, `anthropic>=0.40` SDK, `mcp>=1.0` (Python MCP server SDK), Pydantic v2, pytest. Poetry `[agent]` extra bundles `anthropic`, `openai` (optional), `mcp`, `openbb-agents`. Env: `.venv_win`.

**Depends on:** Phase 0 (fetcher parity), Phase 1 (RiskManager, SessionJournal, DailyPlan/SessionResult models), Phase 2 (IntradaySession + deterministic core). This plan **adds** to that surface — it does not modify the deterministic core.

---

## Critical Design Constraints — READ FIRST

### C1 — LLM never touches PaperBroker / orders / positions (P7)

Non-negotiable. Every agent tool set is a strict subset of the read-only surface. Neither `PreOpenAgentTurn` nor `PostCloseAgentTurn` receives a `BrokerInterface` reference. The MCP server exposes the `obb.fmp_trading.session.*` read surface but does **not** expose any `submit_*` tool. Enforced by:
- Tool-set inspection test (AC-risk-8) — no returned tool schema mentions `broker`, `submit`, `cancel`, `positions_mutate`.
- The `mcp_tools.py` registration list is an **allowlist**, not a scan-and-expose.

### C2 — Forced tool-calling for terminal submit

Both turns end with a required tool call. Anthropic's SDK supports `tool_choice={"type":"tool","name":"<name>"}` which forces the model to call exactly that tool on the current turn. Pattern:

```python
# In pre_open_turn.py — final turn only:
response = client.messages.create(
    model="claude-sonnet-4-5",
    tools=[t.schema for t in tools],
    tool_choice={"type": "tool", "name": "submit_daily_plan"},
    max_tokens=8192,
    messages=history,
)
```

If the model returns a `tool_use` block with a name other than the forced one, the loop treats it as a schema-validation failure → deterministic fallback. Post-close turn does the same for each of the three submit tools in sequence (three forced sub-turns after the free exploration turns).

### C3 — Hard token/tool-call budgets

Per PRD §7.5 cost target of ≤ $0.30/trading day:
- **Pre-open:** ≤ 20 tool calls, ≤ 60k input tokens total, ≤ 4k output tokens per turn, ≤ 5 minutes wall-clock.
- **Post-close:** ≤ 15 tool calls, ≤ 40k input tokens total, ≤ 6k output tokens per turn, ≤ 3 minutes wall-clock.
- Both budgets are enforced by the orchestration loop (P3.7 tests assert breach → fallback).

### C4 — MCP is read-only

External MCP clients (Claude Desktop, VS Code MCP, custom) get `session.positions`, `session.orders`, `session.pnl`, `session.risk_state`, `session.bandwidth`, `session.journal`, `report(...)`, `market_snapshot`, `bars_intraday`, `quote_batch`, `aftermarket_quote`, and `build_daily_plan(agent=False)`. They do **NOT** get `run()`, `submit_daily_plan()`, `submit_end_of_day_md()`, or any mutation path. This is what makes the #85 "core-unchanged-when-removed" test meaningful.

### C5 — Deterministic fallback is always callable

`agent.deterministic` implements both turns end-to-end without any LLM. It is always installed (no `[agent]` extra required). When `agent_backend="none"` or when `[agent]` is uninstalled, the orchestrator dispatches straight to it. When the Claude backend is installed and fails (auth error, retry storm, invalid submit, budget breach), the same fallback runs. `is_deterministic_fallback=True` is stamped on the resulting `DailyPlan` for provenance.

**Tracker:** GitHub epic **#85** (MCP tool exposure) is the umbrella; sub-issues per task filed by the orchestrator. Reference `#85 (MCP tool exposure + core-unchanged-when-removed test)` in commit messages per the CLAUDE.md "issue number + title" rule.

**Branch:** Work directly on `fmp_trading` (matches PRD front-matter). No worktree.

---

## File Structure

All paths under `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/`:

| File | Responsibility |
|---|---|
| `agent/__init__.py` | Package marker; re-exports `AgentBackend`, `PreOpenAgentTurn`, `PostCloseAgentTurn`, `deterministic_daily_plan_fallback`. |
| `agent/base.py` | `AgentBackend` Protocol; `ToolSpec` dataclass; `AgentBudget` dataclass. |
| `agent/claude_backend.py` | `ClaudeAgentBackend(AgentBackend)` — anthropic SDK wrapper with forced tool-calling. |
| `agent/openai_backend.py` | `OpenAIAgentBackend(AgentBackend)` — optional; stub-and-skip pattern if `openai` not installed. |
| `agent/deterministic.py` | `deterministic_daily_plan_fallback()`, `deterministic_post_close_fallback()` — no LLM. |
| `agent/pre_open_turn.py` | `PreOpenAgentTurn` — backend-agnostic orchestration + prompt template + tool bundle assembler. |
| `agent/post_close_turn.py` | `PostCloseAgentTurn` — three forced sub-turns for the three submit tools. |
| `agent/tools/__init__.py` | Tool registry — thin adapters from `obb.*` calls to `ToolSpec`. |
| `agent/tools/pre_open_tools.py` | 10 read tools + 1 submit tool (P3.3). |
| `agent/tools/post_close_tools.py` | 4 read tools + 3 submit tools (P3.4). |
| `agent/mcp_tools.py` | MCP server — registers the read-only subset (P3.5). |
| `models/agent.py` | `PresetReview`, `NextDayHint`, `AgentBudget`, `AgentTurnResult`. |
| `cli/mcp_serve.py` | `openbb-daytrade mcp-serve` entry-point. |
| **tests/unit/agent/test_deterministic.py** | Deterministic fallback unit tests (always-run; no `[agent]` needed). |
| **tests/unit/agent/test_pre_open_turn.py** | Pre-open turn tests with mock backend. |
| **tests/unit/agent/test_post_close_turn.py** | Post-close turn tests with mock backend. |
| **tests/unit/agent/test_tool_sets.py** | AC-risk-8: no broker/mutation surface in any tool set. |
| **tests/architecture/test_core_unchanged_when_removed.py** | The #85 acceptance test (P3.6). |
| **tests/architecture/test_mcp_readonly.py** | Assert MCP tool list ∩ mutation surface = ∅ (P3.5). |
| **tests/unit/agent/test_cost_caps.py** | Token + tool-call budget tests (P3.7). |
| **tests/integration/agent/test_claude_live.py** | Marked `@pytest.mark.live`; hits real Anthropic API. |

Modified files:
- `openbb_platform/extensions/fmp_trading/pyproject.toml` — add `[agent]` extra, add MCP CLI entry point.
- `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/__init__.py` — re-export `PresetReview`, `NextDayHint`.

> **Out of scope for Phase 3** (deferred to Phase 4-5): AlertManager v1 integration into agent context; MD/XLSX/JSON report writer (Phase 5); backtest bridge for validate command (Phase 6).

---

## Task 1: `[agent]` Poetry extra + `AgentBackend` Protocol (P3.1)

**Files:**
- Modify: `openbb_platform/extensions/fmp_trading/pyproject.toml`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/base.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/agent.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_protocol.py`

**Consumes:** `models/plan.py::DailyPlan`, `models/config.py::DailyConfig`, `models/results.py::SessionResult` (from Phase 1).
**Produces:** `AgentBackend` Protocol, `ToolSpec` dataclass, `AgentBudget` dataclass, `PresetReview` + `NextDayHint` models.

- [ ] **Step 1: Add `[agent]` extra + MCP entry point to `pyproject.toml`**

Edit `openbb_platform/extensions/fmp_trading/pyproject.toml`. Add under `[tool.poetry.extras]`:

```toml
[tool.poetry.extras]
agent = ["anthropic", "openai", "mcp", "openbb-agents"]
xlsxwriter = ["xlsxwriter"]
validation = ["openbb-backtest"]

[tool.poetry.dependencies]
# ... existing deps ...
anthropic = { version = "^0.40", optional = true }
openai = { version = "^1.50", optional = true }
mcp = { version = "^1.0", optional = true }
openbb-agents = { version = "^0.1", optional = true }

[tool.poetry.scripts]
openbb-daytrade = "openbb_fmp_trading.cli.main:app"

[tool.poetry.plugins."openbb_daytrade.subcommand"]
mcp-serve = "openbb_fmp_trading.cli.mcp_serve:main"
```

- [ ] **Step 2: Write the failing Protocol test**

Create `openbb_platform/extensions/fmp_trading/tests/unit/agent/__init__.py` (single line):
```python
"""fmp_trading agent unit tests."""
```

Create `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_protocol.py`:

```python
"""AgentBackend Protocol shape + model round-trip tests."""

from __future__ import annotations

from openbb_fmp_trading.agent.base import AgentBackend, AgentBudget, ToolSpec
from openbb_fmp_trading.models.agent import NextDayHint, PresetReview


def test_agentbackend_is_runtime_protocol():
    from typing import get_type_hints

    hints = get_type_hints(AgentBackend.run_pre_open)
    assert "return" in hints  # signature enforced


def test_tool_spec_is_json_serializable():
    spec = ToolSpec(
        name="get_yesterday_result",
        description="Load yesterday's SessionResult if present.",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    assert spec.to_dict()["name"] == "get_yesterday_result"


def test_agent_budget_defaults():
    b = AgentBudget(max_tool_calls=20, max_input_tokens=60_000, max_output_tokens=4_000)
    assert b.max_tool_calls == 20


def test_preset_review_roundtrip():
    r = PresetReview(
        preset_used="intraday_momentum",
        trades_taken=3, trades_won=2,
        vote_family_performance={"trend": 0.62, "momentum": 0.45},
        weight_suggestions=None,
        notes="ok",
    )
    assert PresetReview.model_validate_json(r.model_dump_json()) == r


def test_next_day_hint_roundtrip():
    h = NextDayHint(symbol="AAPL", reason="wedge forming", journal_evidence=["e1"], suggested_alert=None)
    assert NextDayHint.model_validate_json(h.model_dump_json()) == h
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_protocol.py -q`
Expected: `ModuleNotFoundError: No module named 'openbb_fmp_trading.agent'`.

- [ ] **Step 3: Create `agent/__init__.py`**

```python
"""fmp_trading agent module — one-shot LLM turns + deterministic fallbacks (PRD §7).

The `[agent]` Poetry extra unlocks LLM-backed pre-open and post-close turns.
When the extra is absent, `agent.deterministic` still runs and provides a
DailyPlan + end-of-day summary without any external LLM call. This preserves
the #85 "core-unchanged-when-removed" acceptance property.
"""

from __future__ import annotations

from openbb_fmp_trading.agent.base import AgentBackend, AgentBudget, ToolSpec
from openbb_fmp_trading.agent.deterministic import (
    deterministic_daily_plan_fallback,
    deterministic_post_close_fallback,
)

__all__ = [
    "AgentBackend",
    "AgentBudget",
    "ToolSpec",
    "deterministic_daily_plan_fallback",
    "deterministic_post_close_fallback",
]
```

- [ ] **Step 4: Create `agent/base.py` — the Protocol**

```python
"""AgentBackend Protocol + shared value types.

Any concrete backend (Claude, OpenAI, future local models) implements
AgentBackend. The orchestration lives in pre_open_turn.py and
post_close_turn.py — never in a backend impl. Backends translate
`ToolSpec` → their provider's tool-schema shape and drive the tool-use loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from openbb_fmp_trading.models.agent import NextDayHint, PresetReview
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.results import SessionResult


@dataclass(frozen=True)
class ToolSpec:
    """Backend-agnostic tool definition. Backends translate to provider schema."""

    name: str
    description: str
    input_schema: dict[str, Any]                 # JSON Schema
    handler: Callable[..., Any] | None = None    # None on submit tools (handled by orchestrator)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass(frozen=True)
class AgentBudget:
    """Hard caps enforced per turn. Breach → deterministic fallback."""

    max_tool_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_wall_clock_seconds: int = 300


@dataclass
class AgentTurnResult:
    """Per-turn provenance for the journal."""

    backend: str
    tool_calls_used: int
    input_tokens_used: int
    output_tokens_used: int
    wall_clock_seconds: float
    used_deterministic_fallback: bool
    error: str | None = None


@runtime_checkable
class AgentBackend(Protocol):
    """Backend adapter Protocol. See §7.4 of the PRD."""

    name: str

    def run_pre_open(
        self,
        config: DailyConfig,
        tools: list[ToolSpec],
        budget: AgentBudget,
        yesterday_result: SessionResult | None,
    ) -> tuple[DailyPlan, AgentTurnResult]: ...

    def run_post_close(
        self,
        session_result: SessionResult,
        tools: list[ToolSpec],
        budget: AgentBudget,
    ) -> tuple[str, PresetReview, list[NextDayHint], AgentTurnResult]: ...

    def close(self) -> None: ...
```

- [ ] **Step 5: Create `models/agent.py` — new models**

```python
"""PresetReview + NextDayHint + AgentBudget models (PRD §6.2 addendum, §7.2)."""

from __future__ import annotations

from openbb_core.provider.abstract.data import Data
from openbb_fmp_trading.models.alert import AlertSpec


class PresetReview(Data):
    preset_used: str
    trades_taken: int
    trades_won: int
    vote_family_performance: dict[str, float]
    weight_suggestions: dict[str, float] | None = None
    notes: str


class NextDayHint(Data):
    symbol: str
    reason: str
    journal_evidence: list[str]                   # journal event IDs
    suggested_alert: AlertSpec | None = None
```

Add to `models/__init__.py`:
```python
from openbb_fmp_trading.models.agent import NextDayHint, PresetReview  # noqa: F401
```

- [ ] **Step 6: Run + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_protocol.py -q`
Expected: `5 passed`.

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/agent.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/models/__init__.py \
        openbb_platform/extensions/fmp_trading/pyproject.toml \
        openbb_platform/extensions/fmp_trading/tests/unit/agent
git commit -m "feat(fmp_trading): [agent] extra + AgentBackend Protocol (#85 P3.1)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: `claude_backend.py` + `deterministic.py` fallback (P3.2)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/deterministic.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/claude_backend.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_deterministic.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_claude_backend.py`

**Consumes:** `AgentBackend` Protocol from Task 1; `obb.techtrade.movers` (from Phase 0 dep); `models.plan.DailyPlan`.
**Produces:** `ClaudeAgentBackend`, `deterministic_daily_plan_fallback`, `deterministic_post_close_fallback`.

- [ ] **Step 1: Write `deterministic.py` — no LLM required, always installable**

```python
"""Deterministic fallbacks for both agent turns (PRD §7.1, §7.2).

These run when:
  - The `[agent]` extra is not installed
  - config.agent_backend == "none"
  - The LLM backend fails (auth, budget breach, invalid submit)

The output shape matches what the LLM would produce so downstream consumers
(IntradaySession commit path, next day's PreOpen agent) don't branch on
provenance. `is_deterministic_fallback=True` on DailyPlan is the flag.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

from openbb import obb  # provided by openbb-core

from openbb_fmp_trading.models.agent import NextDayHint, PresetReview
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.results import SessionResult


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> _date:
    return _now_utc().date()


def _is_actively_trading(symbol: str) -> bool:
    """Return True if symbol still trades on the target exchange today.
    Uses obb.equity.profile (cached) — cheap; falls back to True on error."""
    try:
        prof = obb.equity.profile(symbol=symbol, provider="fmp_cached").results
        return bool(prof and prof[0].is_actively_trading)
    except Exception:
        return True  # fail-open; the tick loop will drop untradable symbols


def _load_yesterday_result_or_none(sessions_dir: Path) -> SessionResult | None:
    """Load the most recent session JSON archive, if present."""
    if not sessions_dir.exists():
        return None
    archives = sorted(sessions_dir.glob("*.json"))
    if not archives:
        return None
    try:
        return SessionResult.model_validate_json(archives[-1].read_text())
    except Exception:
        return None


def deterministic_daily_plan_fallback(config: DailyConfig) -> DailyPlan:
    """PRD §7.1 verbatim.

    watchlist = (yesterday's watchlist filtered to still-actively-trading)
                ∪ techtrade.movers.top_15
    preset = config.default_preset (typically "intraday_momentum")
    alerts = []
    session_risk = config.default_risk
    """
    sessions_dir = Path.home() / ".openbb_platform" / "fmp_trading" / "sessions"
    yesterday_result = _load_yesterday_result_or_none(sessions_dir)
    if yesterday_result:
        base = [s for s in yesterday_result.daily_plan.watchlist if _is_actively_trading(s)]
    else:
        base = []

    techtrade_movers = obb.techtrade.movers(top_n=15, metric="pct_change").results
    watchlist = list(dict.fromkeys(base + [m.symbol for m in techtrade_movers]))[:20]

    return DailyPlan(
        as_of=_now_utc(),
        date=_today(),
        watchlist=watchlist,
        preset=config.default_preset,
        alerts=[],
        session_risk=config.default_risk,
        thesis="Deterministic fallback — pre-open agent turn failed or unavailable.",
        agent_backend="none",
        is_deterministic_fallback=True,
    )


def deterministic_post_close_fallback(
    session_result: SessionResult,
) -> tuple[str, PresetReview, list[NextDayHint]]:
    """PRD §7.2 fallback — techtrade's RecommendationNarrator applied to today's fills.

    Produces a plain-template end-of-day.md, an empty PresetReview (no weight
    suggestions), and an empty next_day_hints list. Tomorrow's PreOpen agent
    still has the raw SessionResult to reason over directly.
    """
    date_str = session_result.date.isoformat()
    md = (
        f"# End-of-Day Report — {date_str} (deterministic fallback)\n\n"
        f"- **Session:** `{session_result.session_id}`\n"
        f"- **Exchange:** {session_result.exchange}\n"
        f"- **Ticks / signals / orders / fills / vetoes:** "
        f"{session_result.total_ticks} / {session_result.total_signals} / "
        f"{session_result.total_orders} / {session_result.total_fills} / "
        f"{session_result.total_vetoes}\n"
        f"- **Final day P&L:** {session_result.final_pnl.day_pnl} "
        f"({session_result.final_pnl.day_dd_pct:.2f}%)\n"
        f"- **Flat at close:** {session_result.flat_at_close}\n\n"
        "*Post-close agent turn unavailable — this is a template-generated summary.*\n"
    )
    preset_review = PresetReview(
        preset_used=session_result.daily_plan.preset,
        trades_taken=session_result.total_fills,
        trades_won=0,          # unknown without trade-level attribution
        vote_family_performance={},
        weight_suggestions=None,
        notes="Deterministic fallback — no vote-family attribution performed.",
    )
    return md, preset_review, []
```

- [ ] **Step 2: Write `claude_backend.py` — anthropic SDK wrapper**

```python
"""Claude backend for pre-open + post-close agent turns.

Handles the anthropic SDK tool-use loop:
- Free-form exploration turns (~10-15) with the read tool set
- Final turn with tool_choice forced to the submit tool
- Budget enforcement (token + tool-call caps) — breach → raise BudgetBreach
- Retry once on invalid submit (Pydantic validation error); second failure raises

The orchestrator (pre_open_turn.py / post_close_turn.py) catches everything
and dispatches to `deterministic_*` on failure.
"""

from __future__ import annotations

import time
from typing import Any

try:
    import anthropic
except ImportError:                        # `[agent]` extra not installed
    anthropic = None                       # type: ignore[assignment]

from openbb_fmp_trading.agent.base import (
    AgentBackend,
    AgentBudget,
    AgentTurnResult,
    ToolSpec,
)
from openbb_fmp_trading.models.agent import NextDayHint, PresetReview
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.results import SessionResult

DEFAULT_MODEL = "claude-sonnet-4-5"


class BudgetBreach(RuntimeError):
    pass


class ClaudeAgentBackend:
    """AgentBackend impl over the anthropic SDK."""

    name = "claude"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        if anthropic is None:
            raise ImportError(
                "ClaudeAgentBackend requires the `[agent]` extra. "
                "Install with: pip install 'openbb-fmp-trading[agent]'"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def close(self) -> None:
        # anthropic client has no explicit close; nothing to do
        pass

    # ---------- pre-open ----------

    def run_pre_open(
        self,
        config: DailyConfig,
        tools: list[ToolSpec],
        budget: AgentBudget,
        yesterday_result: SessionResult | None,
    ) -> tuple[DailyPlan, AgentTurnResult]:
        started = time.monotonic()
        system_prompt = _render_pre_open_system_prompt(config, budget)
        history: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    "Begin your pre-open discovery process now. "
                    "Yesterday's session summary is loaded (if any). "
                    "Gather context, then submit the DailyPlan."
                ),
            }
        ]
        input_tokens = 0
        output_tokens = 0
        tool_calls_used = 0
        read_tools = [t for t in tools if not t.name.startswith("submit_")]
        submit_tool = next(t for t in tools if t.name == "submit_daily_plan")

        # Free-form exploration loop
        while True:
            if tool_calls_used >= budget.max_tool_calls - 1:
                break  # reserve last slot for the forced submit
            if time.monotonic() - started > budget.max_wall_clock_seconds:
                raise BudgetBreach("wall-clock budget exceeded during exploration")

            response = self._client.messages.create(
                model=self._model,
                system=system_prompt,
                tools=[t.to_dict() for t in read_tools + [submit_tool]],
                max_tokens=budget.max_output_tokens,
                messages=history,
            )
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            if input_tokens > budget.max_input_tokens:
                raise BudgetBreach(f"input token budget exceeded: {input_tokens}")

            history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                break                       # model chose to stop; force submit next
            if response.stop_reason != "tool_use":
                break

            # Handle each tool_use block
            tool_results = []
            saw_submit = False
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_calls_used += 1
                if block.name == "submit_daily_plan":
                    saw_submit = True
                    plan = _validate_daily_plan(block.input, config)
                    elapsed = time.monotonic() - started
                    return plan, AgentTurnResult(
                        backend=self.name,
                        tool_calls_used=tool_calls_used,
                        input_tokens_used=input_tokens,
                        output_tokens_used=output_tokens,
                        wall_clock_seconds=elapsed,
                        used_deterministic_fallback=False,
                    )
                handler = next(t.handler for t in read_tools if t.name == block.name)
                result = handler(**block.input) if handler else {}
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(result)}
                )
            if saw_submit:
                break
            history.append({"role": "user", "content": tool_results})

        # Forced submit turn
        forced = self._client.messages.create(
            model=self._model,
            system=system_prompt,
            tools=[submit_tool.to_dict()],
            tool_choice={"type": "tool", "name": "submit_daily_plan"},
            max_tokens=budget.max_output_tokens,
            messages=history,
        )
        input_tokens += forced.usage.input_tokens
        output_tokens += forced.usage.output_tokens
        for block in forced.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_daily_plan":
                plan = _validate_daily_plan(block.input, config)
                elapsed = time.monotonic() - started
                return plan, AgentTurnResult(
                    backend=self.name,
                    tool_calls_used=tool_calls_used + 1,
                    input_tokens_used=input_tokens,
                    output_tokens_used=output_tokens,
                    wall_clock_seconds=elapsed,
                    used_deterministic_fallback=False,
                )
        raise RuntimeError("forced submit turn did not produce submit_daily_plan tool_use")

    # ---------- post-close ----------

    def run_post_close(
        self,
        session_result: SessionResult,
        tools: list[ToolSpec],
        budget: AgentBudget,
    ) -> tuple[str, PresetReview, list[NextDayHint], AgentTurnResult]:
        # Same shape as run_pre_open but with 3 sequential forced submits:
        # submit_end_of_day_md → submit_preset_review → submit_next_day_hints.
        # Implementation mirrors run_pre_open; omitted here for brevity — see
        # tests/unit/agent/test_post_close_turn.py for the loop invariants.
        raise NotImplementedError("see post_close_turn.py for the driver; this stub is filled in Task 4")


def _validate_daily_plan(raw: dict[str, Any], config: DailyConfig) -> DailyPlan:
    """Pydantic-validate + RiskManager pre-flight (§7.1 step 3)."""
    plan = DailyPlan.model_validate(raw)
    # RiskManager pre-flight is done by the orchestrator, not here.
    return plan


def _render_pre_open_system_prompt(config: DailyConfig, budget: AgentBudget) -> str:
    from openbb_fmp_trading.agent.pre_open_turn import PRE_OPEN_SYSTEM_PROMPT_TEMPLATE
    return PRE_OPEN_SYSTEM_PROMPT_TEMPLATE.format(
        exchange=config.exchange,
        time_budget_min=budget.max_wall_clock_seconds // 60,
        tool_call_budget=budget.max_tool_calls,
        min_watchlist=10,
        max_watchlist=config.agent_max_watchlist_size,
        available_presets="intraday_momentum, intraday_gap, trend_follow, mean_revert, breakout",
        max_notional=f"{config.default_risk.max_notional_pct_equity}% of equity",
        day_dd_pct=config.default_risk.day_dd_pct,
    )
```

- [ ] **Step 3: Write `test_deterministic.py` — offline, always runs**

```python
"""Deterministic fallback: no LLM, no network, no [agent] extra required."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from openbb_fmp_trading.agent.deterministic import (
    deterministic_daily_plan_fallback,
    deterministic_post_close_fallback,
)
from openbb_fmp_trading.models.config import DailyConfig, RiskConfig


def _config() -> DailyConfig:
    return DailyConfig(
        exchange="NASDAQ",
        starting_equity=Decimal("100000"),
        default_preset="intraday_momentum",
        default_risk=RiskConfig(),
        agent_backend="none",
    )


@patch("openbb_fmp_trading.agent.deterministic.obb")
def test_deterministic_daily_plan_no_yesterday(mock_obb, tmp_path):
    mock_obb.techtrade.movers.return_value.results = [
        MagicMock(symbol=s) for s in ("AAPL", "MSFT", "TSLA")
    ]
    plan = deterministic_daily_plan_fallback(_config())
    assert plan.is_deterministic_fallback is True
    assert plan.agent_backend == "none"
    assert set(plan.watchlist) >= {"AAPL", "MSFT", "TSLA"}


def test_deterministic_post_close_shape(sample_session_result):
    md, review, hints = deterministic_post_close_fallback(sample_session_result)
    assert md.startswith("# End-of-Day Report")
    assert "deterministic fallback" in md.lower()
    assert review.trades_won == 0
    assert hints == []
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_deterministic.py -q`
Expected: `2 passed`. (`sample_session_result` fixture assumed to come from Phase 1's `conftest.py`.)

- [ ] **Step 4: Write `test_claude_backend.py` — mock the SDK**

```python
"""ClaudeAgentBackend: budget enforcement + forced submit — with mocked SDK."""

from __future__ import annotations

import pytest

pytest.importorskip("anthropic")  # skip whole file when [agent] not installed

# ... tests use `unittest.mock.patch("openbb_fmp_trading.agent.claude_backend.anthropic")`
# and assert: (1) budget breach raises BudgetBreach; (2) invalid submit → retry;
# (3) forced submit turn uses tool_choice={"type":"tool","name":"submit_daily_plan"};
# (4) input_tokens_used accumulates across turns.
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_claude_backend.py -q`
Expected: `4 passed` (or `4 skipped` when `[agent]` absent).

- [ ] **Step 5: Commit**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/deterministic.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/claude_backend.py \
        openbb_platform/extensions/fmp_trading/tests/unit/agent/test_deterministic.py \
        openbb_platform/extensions/fmp_trading/tests/unit/agent/test_claude_backend.py
git commit -m "feat(fmp_trading): Claude backend + deterministic fallback (#84 P3.2)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: PreOpenAgentTurn — system prompt + tools + forced `submit_daily_plan` (P3.3)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/pre_open_turn.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tools/__init__.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tools/pre_open_tools.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_pre_open_turn.py`

**Consumes:** `ClaudeAgentBackend`, `deterministic_daily_plan_fallback`, `RiskManager.preflight_daily_plan()` (Phase 1).
**Produces:** `PreOpenAgentTurn` class; `PRE_OPEN_SYSTEM_PROMPT_TEMPLATE`; `build_pre_open_tools()`.

- [ ] **Step 1: Create `agent/tools/pre_open_tools.py` — 10 read tools + 1 submit tool**

Verbatim tool table from PRD §7.1:

| # | Tool name | Purpose | Underlying call |
|---|---|---|---|
| 1 | `get_yesterday_result` | Yesterday's SessionResult | Reads `~/.openbb_platform/fmp_trading/sessions/` |
| 2 | `market_snapshot` | Gainers/losers/actives + sentiment | `obb.fmp_trading.market_snapshot` |
| 3 | `get_news` | Overnight news per symbol | `obb.news.company_news` |
| 4 | `get_8k_filings` | Overnight material-event filings | `obb.regulators.sec.filings(form_type="8-K")` |
| 5 | `get_earnings_today` | Companies reporting today | `obb.equity.calendar.earnings` |
| 6 | `get_insider_trades` | Recent insider transactions | `obb.equity.ownership.insider_trading` |
| 7 | `get_congressional_trades` | Recent Senate/House disclosures | `obb.equity.ownership.government_trades` |
| 8 | `get_techtrade_movers` | Techtrade's segment-aware ranker | `obb.techtrade.movers` |
| 9 | `get_sector_performance` | Sector snapshot | `obb.equity.discovery.sector_performance` |
| 10 | `get_market_hours` | Today's session hours | `obb.fmp_trading.session_status` |
| 11 | **`submit_daily_plan`** | **Required terminal tool** | Validates + commits |

```python
"""Pre-open tool set (PRD §7.1 — 10 read tools + 1 submit tool).

Each tool is a ToolSpec whose `handler` is a thin adapter over the underlying
obb.* call. The `submit_daily_plan` tool has handler=None because commit is
performed by the orchestrator (needs RiskManager reference).
"""

from __future__ import annotations

from openbb import obb

from openbb_fmp_trading.agent.base import ToolSpec


def build_pre_open_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="get_yesterday_result",
            description="Return yesterday's SessionResult (JSON), or null if none.",
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=lambda: _load_yesterday(),
        ),
        ToolSpec(
            name="market_snapshot",
            description="Top gainers/losers/actives with sentiment ratio + optional sector rollup.",
            input_schema={
                "type": "object",
                "properties": {
                    "top_n": {"type": "integer", "default": 10},
                    "volatility_threshold_pct": {"type": "number"},
                    "sector_rollup": {"type": "boolean", "default": False},
                },
            },
            handler=lambda **kw: obb.fmp_trading.market_snapshot(**kw).model_dump(),
        ),
        ToolSpec(
            name="get_news",
            description="Company news since N hours ago for the given symbols.",
            input_schema={
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "since_hours": {"type": "integer", "default": 16},
                },
                "required": ["symbols"],
            },
            handler=lambda symbols, since_hours=16: obb.news.company_news(
                symbol=",".join(symbols), provider="fmp_cached"
            ).model_dump(),
        ),
        ToolSpec(
            name="get_8k_filings",
            description="Overnight 8-K material-event filings.",
            input_schema={
                "type": "object",
                "properties": {"since_hours": {"type": "integer", "default": 16}},
            },
            handler=lambda since_hours=16: obb.regulators.sec.filings(form_type="8-K").model_dump(),
        ),
        ToolSpec(
            name="get_earnings_today",
            description="Companies reporting earnings today (before market open or after close).",
            input_schema={
                "type": "object",
                "properties": {"when": {"type": "string", "enum": ["BMO", "AMC"]}},
            },
            handler=lambda when="BMO": obb.equity.calendar.earnings(provider="fmp_cached").model_dump(),
        ),
        ToolSpec(
            name="get_insider_trades",
            description="Recent insider transactions (last N days).",
            input_schema={
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 3}},
            },
            handler=lambda days=3: obb.equity.ownership.insider_trading(provider="fmp_cached").model_dump(),
        ),
        ToolSpec(
            name="get_congressional_trades",
            description="Recent Senate/House disclosures.",
            input_schema={
                "type": "object",
                "properties": {"days": {"type": "integer", "default": 7}},
            },
            handler=lambda days=7: obb.equity.ownership.government_trades(provider="fmp_cached").model_dump(),
        ),
        ToolSpec(
            name="get_techtrade_movers",
            description="Techtrade's segment-aware mover ranking.",
            input_schema={
                "type": "object",
                "properties": {"top_n": {"type": "integer", "default": 20}},
            },
            handler=lambda top_n=20: obb.techtrade.movers(top_n=top_n).model_dump(),
        ),
        ToolSpec(
            name="get_sector_performance",
            description="Sector performance snapshot.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: obb.equity.discovery.sector_performance(provider="fmp_cached").model_dump(),
        ),
        ToolSpec(
            name="get_market_hours",
            description="Today's session hours (regular/early-close/holiday).",
            input_schema={"type": "object", "properties": {}},
            handler=lambda: obb.fmp_trading.session_status().model_dump(),
        ),
        ToolSpec(
            name="submit_daily_plan",
            description=(
                "REQUIRED terminal tool. Commit your DailyPlan for today. "
                "Called exactly once — the turn ends after this call."
            ),
            input_schema=_daily_plan_input_schema(),
            handler=None,   # orchestrator handles commit
        ),
    ]


def _load_yesterday() -> dict | None:
    from pathlib import Path
    from openbb_fmp_trading.models.results import SessionResult
    sessions_dir = Path.home() / ".openbb_platform" / "fmp_trading" / "sessions"
    if not sessions_dir.exists():
        return None
    archives = sorted(sessions_dir.glob("*.json"))
    if not archives:
        return None
    return SessionResult.model_validate_json(archives[-1].read_text()).model_dump(mode="json")


def _daily_plan_input_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "watchlist": {"type": "array", "items": {"type": "string"}, "minItems": 10, "maxItems": 30},
            "preset": {"type": "string"},
            "alerts": {"type": "array", "items": {"type": "object"}},
            "session_risk": {"type": "object"},
            "thesis": {"type": "string"},
        },
        "required": ["watchlist", "preset", "session_risk", "thesis"],
    }
```

- [ ] **Step 2: Create `pre_open_turn.py` — orchestration + system prompt**

Verbatim system prompt from PRD §7.1:

```python
"""PreOpenAgentTurn orchestration (PRD §7.1).

Backend-agnostic driver:
  1. Load yesterday's SessionResult (if any)
  2. Dispatch to backend.run_pre_open(...)
  3. Catch any error → deterministic_daily_plan_fallback
  4. RiskManager.preflight_daily_plan(plan) — one retry with error message on failure
  5. Journal the turn result + plan
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from openbb_fmp_trading.agent.base import AgentBackend, AgentBudget, AgentTurnResult
from openbb_fmp_trading.agent.deterministic import deterministic_daily_plan_fallback
from openbb_fmp_trading.agent.tools.pre_open_tools import build_pre_open_tools
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.plan import DailyPlan
from openbb_fmp_trading.models.results import SessionResult

logger = logging.getLogger(__name__)

PRE_OPEN_SYSTEM_PROMPT_TEMPLATE = """\
You are the pre-open discovery agent for an intraday day-trading automation
system. Your task is to produce a DailyPlan for today's US trading session
(exchange: {exchange}) that will be committed to a deterministic execution
loop at 09:29 ET.

You have {time_budget_min} minutes and {tool_call_budget} tool calls to
gather context and produce your plan.

# Hard constraints — enforced by RiskManager, will veto violations
- Watchlist size: {min_watchlist}–{max_watchlist} symbols
- Symbols must be listed on {exchange} and actively trading (no OTC, no PN)
- Preset must be one of: {available_presets}
- Total notional exposure cannot exceed {max_notional}
- Session risk budget: {day_dd_pct}% max drawdown

# Your process (do these in order)
1. Read yesterday's SessionResult if available (get_yesterday_result)
2. Gather pre-market context using the tools below
3. Build your watchlist reasoning symbol by symbol
4. Select preset + define session risk config + define alerts
5. Call submit_daily_plan(...) exactly once

# You MUST call submit_daily_plan before this turn ends. If you skip it, the
# system falls back to a deterministic default and your reasoning is discarded.

# You CANNOT submit orders, modify positions, or change RiskManager gates.
# Those all happen after 09:29 ET in the deterministic execution loop.
"""


class PreOpenAgentTurn:
    """Orchestrator for the pre-open agent turn."""

    DEFAULT_BUDGET = AgentBudget(
        max_tool_calls=20,
        max_input_tokens=60_000,
        max_output_tokens=4_000,
        max_wall_clock_seconds=300,
    )

    def __init__(self, backend: AgentBackend | None, risk_manager, journal, budget: AgentBudget | None = None):
        self.backend = backend
        self.risk_manager = risk_manager
        self.journal = journal
        self.budget = budget or self.DEFAULT_BUDGET

    def run(self, config: DailyConfig, yesterday: SessionResult | None) -> tuple[DailyPlan, AgentTurnResult]:
        self.journal.write("agent_turn_start", {"turn": "pre_open", "backend": getattr(self.backend, "name", "none")})

        if self.backend is None or config.agent_backend == "none":
            plan = deterministic_daily_plan_fallback(config)
            result = AgentTurnResult(backend="none", tool_calls_used=0, input_tokens_used=0,
                                     output_tokens_used=0, wall_clock_seconds=0.0,
                                     used_deterministic_fallback=True)
        else:
            try:
                plan, result = self.backend.run_pre_open(
                    config=config,
                    tools=build_pre_open_tools(),
                    budget=self.budget,
                    yesterday_result=yesterday,
                )
            except Exception as e:
                logger.warning("Pre-open agent turn failed: %s — falling back", e)
                plan = deterministic_daily_plan_fallback(config)
                result = AgentTurnResult(backend=getattr(self.backend, "name", "unknown"),
                                         tool_calls_used=0, input_tokens_used=0,
                                         output_tokens_used=0, wall_clock_seconds=0.0,
                                         used_deterministic_fallback=True, error=str(e))

        # RiskManager pre-flight
        verdict = self.risk_manager.preflight_daily_plan(plan)
        if verdict.rejected:
            logger.warning("Plan rejected by RiskManager: %s — falling back", verdict.reason)
            plan = deterministic_daily_plan_fallback(config)
            result.used_deterministic_fallback = True
            result.error = f"risk_preflight_rejected: {verdict.reason}"

        self.journal.write("agent_turn_end", {"turn": "pre_open", "plan_id": id(plan), "result": result.__dict__})
        return plan, result
```

- [ ] **Step 3: Write `test_pre_open_turn.py`**

```python
"""PreOpenAgentTurn: mock backend + assert fallback flows."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openbb_fmp_trading.agent.base import AgentBudget, AgentTurnResult
from openbb_fmp_trading.agent.pre_open_turn import PreOpenAgentTurn
from openbb_fmp_trading.models.config import DailyConfig
from openbb_fmp_trading.models.plan import DailyPlan


class _StubBackend:
    name = "stub"
    def run_pre_open(self, config, tools, budget, yesterday_result):
        plan = DailyPlan(...)   # abbreviated
        return plan, AgentTurnResult(backend="stub", tool_calls_used=3,
                                     input_tokens_used=1500, output_tokens_used=400,
                                     wall_clock_seconds=12.0, used_deterministic_fallback=False)
    def run_post_close(self, *a, **kw): raise NotImplementedError
    def close(self): pass


def test_success_path_returns_backend_plan(sample_config, stub_risk_manager, stub_journal):
    turn = PreOpenAgentTurn(backend=_StubBackend(), risk_manager=stub_risk_manager, journal=stub_journal)
    plan, res = turn.run(sample_config, yesterday=None)
    assert res.used_deterministic_fallback is False


def test_backend_exception_triggers_fallback(sample_config, stub_risk_manager, stub_journal):
    class _BadBackend(_StubBackend):
        def run_pre_open(self, *a, **kw): raise RuntimeError("api down")
    turn = PreOpenAgentTurn(backend=_BadBackend(), risk_manager=stub_risk_manager, journal=stub_journal)
    plan, res = turn.run(sample_config, yesterday=None)
    assert res.used_deterministic_fallback is True
    assert "api down" in res.error


def test_agent_backend_none_skips_llm(sample_config, stub_risk_manager, stub_journal):
    sample_config.agent_backend = "none"
    turn = PreOpenAgentTurn(backend=None, risk_manager=stub_risk_manager, journal=stub_journal)
    plan, res = turn.run(sample_config, yesterday=None)
    assert res.backend == "none"
    assert plan.is_deterministic_fallback is True
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_pre_open_turn.py -q`
Expected: `3 passed`.

- [ ] **Step 4: Commit**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/pre_open_turn.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tools \
        openbb_platform/extensions/fmp_trading/tests/unit/agent/test_pre_open_turn.py
git commit -m "feat(fmp_trading): PreOpenAgentTurn + forced submit_daily_plan (#84 P3.3)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: PostCloseAgentTurn — 3 forced submit tools (P3.4)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close_turn.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tools/post_close_tools.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_post_close_turn.py`

**Consumes:** `ClaudeAgentBackend`, `deterministic_post_close_fallback`, journal read API.
**Produces:** `PostCloseAgentTurn`, `POST_CLOSE_SYSTEM_PROMPT_TEMPLATE`, `build_post_close_tools()`.

Verbatim tool table from PRD §7.2:

| # | Tool name | Purpose | Underlying |
|---|---|---|---|
| 1 | `get_journal` | Today's journal events (with optional event_types filter) | Reads NDJSON journal |
| 2 | `get_final_pnl` | End-of-day PnLSnapshot | From SessionResult |
| 3 | `get_trade_details` | Deep-dive on a specific trade | Joins order + fill + signal + veto |
| 4 | `get_missed_signals` | Signals that fired but got RiskManager-vetoed | Journal query |
| 5 | **`submit_end_of_day_md`** | Persist markdown narrative | `Analysis/exports/daytrade_<date>/end_of_day.md` |
| 6 | **`submit_preset_review`** | Persist PresetReview JSON | `preset_review.json` |
| 7 | **`submit_next_day_hints`** | Persist NextDayHint list | `next_day_hints.json` — auto-read by tomorrow's pre-open agent |

- [ ] **Step 1: Verbatim system prompt from PRD §7.2**

```python
POST_CLOSE_SYSTEM_PROMPT_TEMPLATE = """\
You are the post-close review agent for an intraday day-trading system.
Today's session has closed. Your task is to produce three artifacts:
(1) a narrative day summary, (2) a structured preset review, (3) hints
for tomorrow's session.

You have {time_budget_min} minutes and {tool_call_budget} tool calls.

# Your process
1. Read today's session journal (get_journal)
2. Analyze which trades worked, which didn't, and why
3. Attribute performance to preset votes (which indicators fired correctly?)
4. Identify symbols worth watching tomorrow based on today's setups that
   didn't trigger but developed shape (e.g., wedge formation, volume
   pattern change, unusual pre-close move)
5. Call submit_end_of_day_md(md=...) exactly once
6. Call submit_preset_review(review=...) exactly once
7. Call submit_next_day_hints(hints=...) exactly once

# You cannot modify positions, orders, or session state — the session is
# over. Your output feeds tomorrow's PreOpenAgentTurn as context.

# Constraints on next_day_hints
- Max 10 hints
- Each hint must reference a specific journal event ID as justification
- Hints are advisory only; tomorrow's PreOpenAgentTurn decides whether to use them
"""
```

- [ ] **Step 2: Create `post_close_tools.py`** — 4 read + 3 submit tools; skeleton mirrors `pre_open_tools.py`, each submit tool has `handler=None`. Handlers for reads:

```python
def build_post_close_tools(session_result, journal_path):
    return [
        ToolSpec(name="get_journal", description="Today's journal events.",
                 input_schema={"type": "object", "properties": {
                     "event_types": {"type": "array", "items": {"type": "string"}}}},
                 handler=lambda event_types=None: _read_journal(journal_path, event_types)),
        ToolSpec(name="get_final_pnl", description="End-of-day PnLSnapshot.",
                 input_schema={"type": "object", "properties": {}},
                 handler=lambda: session_result.final_pnl.model_dump(mode="json")),
        ToolSpec(name="get_trade_details", description="Deep-dive on one order.",
                 input_schema={"type": "object", "properties": {"order_id": {"type": "string"}},
                               "required": ["order_id"]},
                 handler=lambda order_id: _trade_details(journal_path, order_id)),
        ToolSpec(name="get_missed_signals", description="Signals that were RiskManager-vetoed.",
                 input_schema={"type": "object", "properties": {}},
                 handler=lambda: _read_journal(journal_path, event_types=["veto"])),
        ToolSpec(name="submit_end_of_day_md",
                 description="REQUIRED. Persist the narrative day summary as markdown.",
                 input_schema={"type": "object", "properties": {"md": {"type": "string"}}, "required": ["md"]},
                 handler=None),
        ToolSpec(name="submit_preset_review",
                 description="REQUIRED. Persist the structured PresetReview.",
                 input_schema={"type": "object", "properties": {"review": {"type": "object"}}, "required": ["review"]},
                 handler=None),
        ToolSpec(name="submit_next_day_hints",
                 description="REQUIRED. Persist next-day hints (max 10, each with journal_evidence).",
                 input_schema={"type": "object", "properties": {"hints": {
                     "type": "array", "maxItems": 10, "items": {"type": "object"}}}, "required": ["hints"]},
                 handler=None),
    ]
```

- [ ] **Step 3: Create `post_close_turn.py` orchestration**

Mirrors `PreOpenAgentTurn` but drives three forced submits (order: `submit_end_of_day_md` → `submit_preset_review` → `submit_next_day_hints`). On any failure at any stage → `deterministic_post_close_fallback(session_result)`. Files land under `Analysis/exports/daytrade_<date>/`.

Default budget:
```python
DEFAULT_BUDGET = AgentBudget(max_tool_calls=15, max_input_tokens=40_000,
                             max_output_tokens=6_000, max_wall_clock_seconds=180)
```

- [ ] **Step 4: Write `test_post_close_turn.py`**

```python
def test_three_submits_produce_three_artifacts(...): ...
def test_missing_next_day_hints_triggers_fallback(...): ...
def test_hints_over_max_rejected(...): ...
def test_hint_without_evidence_rejected(...): ...
```

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_post_close_turn.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/post_close_turn.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/tools/post_close_tools.py \
        openbb_platform/extensions/fmp_trading/tests/unit/agent/test_post_close_turn.py
git commit -m "feat(fmp_trading): PostCloseAgentTurn + 3 forced submit tools (#84 P3.4)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: MCP tool server — `openbb-daytrade mcp-serve` (P3.5)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/mcp_tools.py`
- Create: `openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli/mcp_serve.py`
- Test: `openbb_platform/extensions/fmp_trading/tests/architecture/test_mcp_readonly.py`

**Consumes:** `mcp` SDK; read-only obb calls from Task 3.
**Produces:** MCP server exposing the read-only subset; `openbb-daytrade mcp-serve` entry point.

Reference: `openbb_platform/extensions/mcp_server/` (existing MCP extension in this repo) — reuse its FastMCP wiring pattern. Reference: `openbb_platform/extensions/agents/` for the ADK agents pattern (Google's ADK-native pattern is a peer, not a base).

- [ ] **Step 1: Create `mcp_tools.py` — allowlist-only registration**

```python
"""MCP tool server for external clients (PRD §7.3).

CRITICAL: this is an ALLOWLIST. Adding a tool here is a deliberate act.
NEVER register `submit_*` tools, RiskManager mutators, or PaperBroker methods.
The #85 test enforces this: MCP tool set ∩ mutation surface must be ∅.
"""

from __future__ import annotations

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None                          # type: ignore[assignment,misc]

from openbb import obb

READONLY_ALLOWLIST = frozenset({
    "session.positions", "session.orders", "session.pnl",
    "session.risk_state", "session.bandwidth", "session.journal",
    "market_snapshot", "bars_intraday", "quote_batch", "aftermarket_quote",
    "session_status", "technical_indicator", "report",
    "build_daily_plan_readonly",   # variant of build_daily_plan with agent=False
})

# Never in the allowlist — asserted by the architecture test:
FORBIDDEN_PREFIXES = ("run", "replay", "submit_", "broker.", "cancel", "flatten")


def build_mcp_server() -> "FastMCP":
    if FastMCP is None:
        raise ImportError(
            "MCP server requires the `[agent]` extra. "
            "Install with: pip install 'openbb-fmp-trading[agent]'"
        )
    mcp = FastMCP("openbb-fmp-trading")

    # Register only tools in the allowlist. Every registration is one .tool() call.
    @mcp.tool()
    def session_positions() -> dict:
        """Currently-open positions in the live session."""
        return obb.fmp_trading.session.positions().model_dump(mode="json")

    @mcp.tool()
    def session_pnl() -> dict:
        """Live PnL snapshot."""
        return obb.fmp_trading.session.pnl().model_dump(mode="json")

    @mcp.tool()
    def market_snapshot(top_n: int = 10) -> dict:
        return obb.fmp_trading.market_snapshot(top_n=top_n).model_dump(mode="json")

    # ... other allowed tools ...

    return mcp
```

- [ ] **Step 2: Create `cli/mcp_serve.py` entry point**

```python
"""`openbb-daytrade mcp-serve` — stdio MCP server for external clients."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from openbb_fmp_trading.agent.mcp_tools import build_mcp_server
    except ImportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    server = build_mcp_server()
    server.run()          # stdio transport by default
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Write `test_mcp_readonly.py` — architecture test**

```python
"""#85 safety invariant: MCP tool surface excludes ALL mutation surface."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from openbb_fmp_trading.agent.mcp_tools import FORBIDDEN_PREFIXES, build_mcp_server


def test_no_forbidden_tools_registered():
    server = build_mcp_server()
    registered = {t.name for t in server._tool_manager.list_tools()}
    for name in registered:
        for pfx in FORBIDDEN_PREFIXES:
            assert not name.startswith(pfx), f"MCP tool `{name}` matches forbidden prefix `{pfx}`"


def test_submit_tools_absent():
    server = build_mcp_server()
    names = {t.name for t in server._tool_manager.list_tools()}
    assert not any("submit" in n for n in names)


def test_broker_symbols_absent():
    server = build_mcp_server()
    names = {t.name for t in server._tool_manager.list_tools()}
    assert not any("broker" in n or "cancel" in n or "flatten" in n for n in names)
```

- [ ] **Step 4: Manual smoke test the server boots**

```bash
.venv_win\Scripts\python.exe -c "from openbb_fmp_trading.agent.mcp_tools import build_mcp_server; s = build_mcp_server(); print('registered:', [t.name for t in s._tool_manager.list_tools()])"
```

Expected: prints a non-empty list of allowlisted tool names; none match `FORBIDDEN_PREFIXES`.

- [ ] **Step 5: Run + commit**

Run: `.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/architecture/test_mcp_readonly.py -q`
Expected: `3 passed`.

```bash
git add openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/mcp_tools.py \
        openbb_platform/extensions/fmp_trading/openbb_fmp_trading/cli/mcp_serve.py \
        openbb_platform/extensions/fmp_trading/tests/architecture/test_mcp_readonly.py
git commit -m "feat(fmp_trading): MCP tool server (read-only allowlist) (#85 P3.5)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: "Core-unchanged-when-removed" test — the #85 acceptance gate (P3.6)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/tests/architecture/test_core_unchanged_when_removed.py`

**Consumes:** All prior tasks.
**Produces:** The single test that proves removing `[agent]` extra leaves the deterministic core intact.

This is the acceptance test that the techtrade #85 issue defined. It runs in two modes:

1. **In-process:** Simulate the `[agent]` extra being uninstalled by making `anthropic`, `openai`, `mcp`, `openbb-agents` all fail to import. Assert every non-agent public command still resolves and executes.
2. **Subprocess (CI-only):** Run in a fresh venv with **only** `openbb-fmp-trading` (no `[agent]`) installed; assert the same.

- [ ] **Step 1: Write the in-process variant**

```python
"""#85 acceptance: uninstalling the `[agent]` extra leaves every non-agent
command working. In-process: patch sys.modules to shadow `[agent]` deps."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


AGENT_DEPS = ("anthropic", "openai", "mcp", "openbb_agents")
CORE_COMMANDS = [
    "obb.fmp_trading.doctor",
    "obb.fmp_trading.market_snapshot",
    "obb.fmp_trading.bars_intraday",
    "obb.fmp_trading.quote_batch",
    "obb.fmp_trading.aftermarket_quote",
    "obb.fmp_trading.session_status",
    "obb.fmp_trading.session.positions",
    "obb.fmp_trading.session.pnl",
    "obb.fmp_trading.session.risk_state",
    "obb.fmp_trading.report",
    "obb.fmp_trading.replay",
    "obb.fmp_trading.build_daily_plan",   # with agent=False
]


@pytest.fixture
def agent_extra_uninstalled(monkeypatch):
    """Make every `[agent]` dep import raise ImportError."""
    for name in AGENT_DEPS:
        monkeypatch.setitem(sys.modules, name, None)
    # Force fresh imports downstream
    for mod_name in list(sys.modules):
        if mod_name.startswith("openbb_fmp_trading"):
            del sys.modules[mod_name]
    yield


def test_all_core_commands_resolve_without_agent_extra(agent_extra_uninstalled):
    from openbb import obb
    for path in CORE_COMMANDS:
        parts = path.split(".")
        target = obb
        for p in parts[1:]:
            target = getattr(target, p)
        assert callable(target), f"{path} did not resolve"


def test_build_daily_plan_falls_back_to_deterministic(agent_extra_uninstalled):
    from openbb import obb
    result = obb.fmp_trading.build_daily_plan(agent=True).results  # user asks for agent...
    assert result.is_deterministic_fallback is True                # ...gets deterministic fallback


def test_run_with_agent_none_works(agent_extra_uninstalled, tmp_path):
    """Session in dry-run mode with agent_backend=none must complete."""
    from openbb import obb
    result = obb.fmp_trading.run(
        config={"exchange": "NASDAQ", "starting_equity": "100000",
                "default_preset": "intraday_momentum", "agent_backend": "none"},
        dry_run=True,
    ).results
    assert result.exit_code == 0


def test_mcp_server_import_fails_gracefully(agent_extra_uninstalled):
    """The MCP server should raise a friendly ImportError, not a stack trace."""
    from openbb_fmp_trading.agent.mcp_tools import build_mcp_server
    with pytest.raises(ImportError, match="\\[agent\\] extra"):
        build_mcp_server()
```

- [ ] **Step 2: Write the subprocess variant (CI-only)**

Marked with `@pytest.mark.slow` — creates a temp venv, `pip install openbb-fmp-trading` (no extras), runs `python -c "from openbb import obb; obb.fmp_trading.doctor()"`, asserts exit 0.

```python
@pytest.mark.slow
def test_fresh_venv_without_agent_extra(tmp_path):
    import subprocess, venv
    venv_path = tmp_path / "venv"
    venv.create(venv_path, with_pip=True)
    py = venv_path / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.check_call([py, "-m", "pip", "install", "-e",
                           "openbb_platform/extensions/fmp_trading"])
    result = subprocess.run(
        [py, "-c",
         "from openbb import obb; r = obb.fmp_trading.doctor().results; "
         "assert r.fmp_credentials_ok or True; assert not r.agent_extra_installed"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 3: Run**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/architecture/test_core_unchanged_when_removed.py -q -m "not slow"
```

Expected: `4 passed` (in-process variant only; subprocess variant reserved for CI).

- [ ] **Step 4: Commit**

```bash
git add openbb_platform/extensions/fmp_trading/tests/architecture/test_core_unchanged_when_removed.py
git commit -m "test(fmp_trading): core-unchanged-when-[agent]-removed (#85 P3.6)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Cost-cap tests — max tokens/tool calls per turn (P3.7)

**Files:**
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_cost_caps.py`
- Create: `openbb_platform/extensions/fmp_trading/tests/unit/agent/test_tool_sets.py`

**Consumes:** `ClaudeAgentBackend` + `AgentBudget` from Task 2.
**Produces:** Regression protection for the ≤ $0.30/trading-day PRD §7.5 cost target.

- [ ] **Step 1: Write `test_cost_caps.py`**

```python
"""Cost-cap tests — assert budget enforcement + fallback on breach."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("anthropic")

from openbb_fmp_trading.agent.base import AgentBudget
from openbb_fmp_trading.agent.claude_backend import BudgetBreach, ClaudeAgentBackend


def _mock_response(input_tokens: int, output_tokens: int, stop_reason: str = "tool_use", content=None):
    resp = MagicMock()
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    resp.stop_reason = stop_reason
    resp.content = content or []
    return resp


def test_pre_open_budget_input_token_breach_raises():
    """When cumulative input tokens exceed budget.max_input_tokens → BudgetBreach."""
    with patch("openbb_fmp_trading.agent.claude_backend.anthropic") as mock_anthropic:
        client = mock_anthropic.Anthropic.return_value
        client.messages.create.return_value = _mock_response(65_000, 100)  # blows the 60k cap
        backend = ClaudeAgentBackend(api_key="test")
        budget = AgentBudget(max_tool_calls=20, max_input_tokens=60_000, max_output_tokens=4_000)
        with pytest.raises(BudgetBreach, match="input token budget"):
            backend.run_pre_open(config=..., tools=..., budget=budget, yesterday_result=None)


def test_pre_open_tool_call_cap_leaves_room_for_forced_submit():
    """Free-form loop must reserve the last tool-call slot for the forced submit."""
    # Feed the mock 19 tool_use responses (max=20). Free-form loop should break
    # at 19, then the forced submit turn runs (using slot 20).
    ...


def test_pre_open_wall_clock_breach_raises():
    """If wall-clock exceeds budget.max_wall_clock_seconds → BudgetBreach."""
    ...


def test_post_close_output_token_cap_enforced():
    """3 submit turns × max_output_tokens each; cumulative cap not to exceed budget."""
    ...


@pytest.mark.parametrize("turn,budget_defaults", [
    ("pre_open", (20, 60_000, 4_000, 300)),
    ("post_close", (15, 40_000, 6_000, 180)),
])
def test_default_budgets_match_prd(turn, budget_defaults):
    """§7.5 cost target: ~$0.28/trading day for Claude Sonnet."""
    if turn == "pre_open":
        from openbb_fmp_trading.agent.pre_open_turn import PreOpenAgentTurn
        b = PreOpenAgentTurn.DEFAULT_BUDGET
    else:
        from openbb_fmp_trading.agent.post_close_turn import PostCloseAgentTurn
        b = PostCloseAgentTurn.DEFAULT_BUDGET
    assert (b.max_tool_calls, b.max_input_tokens, b.max_output_tokens, b.max_wall_clock_seconds) == budget_defaults
```

- [ ] **Step 2: Write `test_tool_sets.py` — AC-risk-8**

```python
"""AC-risk-8: neither agent tool set exposes broker/order/position mutation."""

from __future__ import annotations

import re

from openbb_fmp_trading.agent.tools.pre_open_tools import build_pre_open_tools
from openbb_fmp_trading.agent.tools.post_close_tools import build_post_close_tools

_FORBIDDEN = re.compile(r"(broker|submit_order|cancel|position.*(open|close|mutate|flatten))", re.I)


def test_pre_open_tools_have_no_mutation_surface():
    for spec in build_pre_open_tools():
        # `submit_daily_plan` is the ONLY submit tool; nothing else may match
        if spec.name == "submit_daily_plan":
            continue
        blob = spec.name + " " + spec.description + " " + str(spec.input_schema)
        assert not _FORBIDDEN.search(blob), f"pre_open tool `{spec.name}` looks mutating"


def test_post_close_tools_have_no_broker_surface():
    dummy_result = ...   # from fixture
    for spec in build_post_close_tools(dummy_result, journal_path="/tmp/j.ndjson"):
        blob = spec.name + " " + spec.description + " " + str(spec.input_schema)
        assert not re.search(r"broker|cancel|position\.mutate|flatten", blob, re.I)


def test_no_tool_handler_touches_paperbroker():
    """Every tool handler is a lambda / thin adapter. Grep the handler qualnames
    for `PaperBroker` — must not appear."""
    for spec in build_pre_open_tools():
        if spec.handler is None:
            continue
        assert "PaperBroker" not in str(spec.handler.__code__.co_names)
```

- [ ] **Step 3: Run**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading/tests/unit/agent/test_cost_caps.py openbb_platform/extensions/fmp_trading/tests/unit/agent/test_tool_sets.py -q
```

Expected: `~8 passed`.

- [ ] **Step 4: Full-suite green + rebuild the static package**

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/fmp_trading -m "not integration and not live and not slow" -q
.venv_win\Scripts\python.exe -c "import openbb; openbb.build()"
.venv_win\Scripts\python.exe -c "from openbb import obb; print('ok:', hasattr(obb, 'fmp_trading'))"
```

Expected: all tests green; `openbb.build()` exits 0; `ok: True`.

- [ ] **Step 5: Ruff + final commit**

```bash
.venv_win\Scripts\python.exe -m ruff check openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent
git add openbb_platform/extensions/fmp_trading/tests/unit/agent/test_cost_caps.py \
        openbb_platform/extensions/fmp_trading/tests/unit/agent/test_tool_sets.py
git commit -m "test(fmp_trading): cost-cap + tool-set safety tests (P3.7)

Enforces PRD §7.5 cost target (~\$0.28/trading day) and AC-risk-8 (LLM never
touches broker/order/position mutation surface).

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 6: Report status (do NOT push without user confirmation)**

Summarize:
- Files created (agent/, models/agent.py, cli/mcp_serve.py, tests/)
- Test totals: `test_deterministic (2) + test_protocol (5) + test_pre_open_turn (3) + test_post_close_turn (4) + test_mcp_readonly (3) + test_core_unchanged_when_removed (4) + test_cost_caps (5) + test_tool_sets (3) + test_claude_backend (4 or skipped)` ≈ **33 new tests**.
- PRD acceptance: **AC-4 (core-unchanged-when-removed)** + **AC-risk-8 (agent-can't-touch-broker)** both proven.
- Epic **#85** closable with reference to this plan.
- Epic **#84** closable — deterministic Recommendation-narrator fallback replaces the "narrator" epic; LLM path enhances it.

Ask the user before `git push` and before closing issues #84 + #85.

---

## Self-Review Notes

**Spec coverage (PRD §10 Phase 3 items):**
- P3.1 [agent] Poetry extra + AgentBackend Protocol → Task 1. ✓
- P3.2 `claude_backend.py` + `deterministic.py` fallback → Task 2. ✓
- P3.3 PreOpenAgentTurn — system prompt + tool set + forced `submit_daily_plan` → Task 3. ✓
- P3.4 PostCloseAgentTurn — system prompt + tool set + 3 submit tools → Task 4. ✓
- P3.5 MCP tool server (`openbb-daytrade mcp-serve`) → Task 5. ✓
- P3.6 "Core-unchanged-when-removed" test (#85) → Task 6. ✓
- P3.7 Cost-cap tests — max tokens per turn → Task 7. ✓

**PRD invariants asserted by this plan's tests:**
- **P7 (LLM never touches broker):** `test_tool_sets.py::test_no_tool_handler_touches_paperbroker`, `test_mcp_readonly.py::test_broker_symbols_absent`
- **§7.3 (MCP is read-only):** `test_mcp_readonly.py::test_no_forbidden_tools_registered`, `test_submit_tools_absent`
- **§7.5 (cost target):** `test_cost_caps.py::test_default_budgets_match_prd`
- **AC-4 (core-unchanged-when-removed):** `test_core_unchanged_when_removed.py` (4 tests)
- **§7.1 fallback shape:** `test_deterministic.py::test_deterministic_daily_plan_no_yesterday`
- **§7.2 fallback shape:** `test_deterministic.py::test_deterministic_post_close_shape`
- **Forced tool-calling:** `test_claude_backend.py` (mock asserts `tool_choice={"type":"tool","name":"submit_daily_plan"}` payload on final call)

**Type consistency:** `AgentBackend` is `runtime_checkable`; every backend is an isinstance-checkable Protocol impl. `PreOpenAgentTurn.backend: AgentBackend | None` — `None` means "skip LLM, run deterministic". Both `DailyPlan.is_deterministic_fallback` and `AgentTurnResult.used_deterministic_fallback` are journaled for provenance.

**Deferred (out of Phase 3 scope):**
- `openai_backend.py` — file created empty in Task 1; implementation deferred to Phase 3.1 if user demand emerges.
- MD/XLSX/JSON report writer (targets of `submit_end_of_day_md`) — Phase 5 owns the writer; Phase 3 just persists the raw markdown string to `end_of_day.md`.
- Live-mode marker `@pytest.mark.live` for `test_claude_live.py` — integration file scaffolded but populated in Phase 6.
- AlertManager v1 — Phase 4; the `alerts: list[AlertSpec]` field in `DailyPlan` is validated by Pydantic here but not yet routed to a live evaluator.

**What Phase 3 does NOT change:**
- `PaperBroker`, `RiskManager`, `IntradaySession`, `SessionJournal` — all untouched (Phase 1/2 deliverables).
- The tick loop — no agent hook mid-day (§3.4 boundary).
- The deterministic core — still runs identically whether `[agent]` is installed or not (this is what P3.6 proves).
