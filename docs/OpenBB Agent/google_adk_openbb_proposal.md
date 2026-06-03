# Proposal: Google ADK Agents on Top of OpenBB

## 1. Why this is a natural fit

OpenBB already gives us three things ADK needs to be useful:

1. A **typed function surface** — `obb.equity.*`, `obb.economy.*`, the `fmp_cached` provider, the Portfolio App endpoints, the `Analysis/` 7-phase pipeline. ADK tools are just Python callables with type hints — your existing functions become agent tools with near-zero glue code.
2. A **local privacy boundary** — MySQL (`openbb_fmp_cache`, `openbb_fmp_cache_test`) stays on the user's machine. ADK agents run in-process, so raw positions never leave the box. The LLM only sees what a tool explicitly returns.
3. A **cache-first cost model** — `fmp_cached` already absorbs API spend. An agent doing 50 lookups for a portfolio question costs essentially $0 after the first warm-up.

ADK adds: deterministic tool routing, multi-step orchestration, session/state memory, a built-in eval harness, and a local web UI for testing — without locking you to Vertex AI (LiteLLM lets you point it at the Copilot proxy, OpenAI, Anthropic, Gemini, or local models).

---

## 2. Concrete agents we can build (and what each is worth)

### 2.1 Portfolio Q&A Agent
- **Wraps:** `Portfolio_Positions`, `Account_Owner`, `equity_historical` tables, `fmp_cached` quote/profile fetchers.
- **Capabilities:** "What's my tech exposure?" / "Show concentration risk in account X" / "How did my portfolio move vs SPY last week?"
- **Customer gain:** Natural-language access to MySQL data they already paid to collect. No SQL required. No data leaves the laptop.

### 2.2 Stock Analysis Orchestrator (multi-agent)
- **Wraps:** `Analysis/stock_analysis.py` — one ADK sub-agent per phase (P1 valuation → P7 composite), coordinated by a parent agent.
- **Capabilities:** "Run a full analysis on MSFT and tell me which phase is the weakest." Agent can re-run only the phases needed when inputs change.
- **Customer gain:** Reproducible, explainable analysis. Each phase is independently auditable. Output is the same numbers the existing pipeline produces — the agent just plans, sequences, and narrates.

### 2.3 Brokerage Import Assistant
- **Wraps:** `Tools/parse_fidelity_positions.py`, `Tools/load_espp_plan.py`, `Tools/fetch_position_history.py`.
- **Capabilities:** Walks user through "drop your Fidelity HTML export here," validates the parse, reports new vs. changed positions, suggests history backfill range.
- **Customer gain:** Removes the manual CLI ordering and "which script do I run next" problem. Same scripts, friendlier surface.

### 2.4 Cache Steward Agent
- **Wraps:** `fmp_cached` metadata + MySQL freshness queries.
- **Capabilities:** "What data is stale for my watchlist?" / "Refresh fundamentals older than 30 days for these 12 tickers." Respects FMP rate limits.
- **Customer gain:** Predictable, bounded API spend. No accidental cache-miss storms.

### 2.5 ESPP / Tax-lot Planning Agent
- **Wraps:** `ESPP_Plan` table + `equity_historical` + holiday calendar.
- **Capabilities:** "When do my next qualifying dispositions land?" / "Project after-tax proceeds if I sell lots from 2024 grant."
- **Customer gain:** Turns existing structured ESPP data into actionable planning answers. No tax advice — just deterministic projections from the user's own data.

### 2.6 OpenBB Pro Widget Backend
- **Wraps:** Portfolio App FastAPI endpoints on :6902.
- **Capabilities:** Agent exposed as an extra endpoint the Pro dashboard can query; returns chart-ready synthetic data alongside a narrative.
- **Customer gain:** Same widget surface gets a conversational layer without changing the Pro dashboard contract.

---

## 3. Proposed architecture (additive, non-invasive)

```
openbb_platform/extensions/agents/        <- NEW extension (optional install)
  pyproject.toml                          <- declares google-adk dep
  openbb_agents/
    router.py                             <- /agents/* endpoints
    tools/
      portfolio_tools.py                  <- thin wrappers over Tools/ + MySQL
      analysis_tools.py                   <- wrappers over Analysis/stock_analysis.py
      fmp_cache_tools.py                  <- wrappers over fmp_cached
    agents/
      portfolio_qa.py
      stock_analysis_orchestrator.py
      brokerage_import.py
      cache_steward.py
    config.py                             <- model selection (LiteLLM)
    guardrails.py                         <- callbacks: PII redaction, cost cap
```

Key design rules:
1. **Zero changes** to existing `Tools/`, `Analysis/`, `fmp_cached`, or `portfolio_app` code. Agents only consume them.
2. **Optional extension** — installs only if user does `pip install -e openbb_platform/extensions/agents`. Core OpenBB unaffected.
3. **Model-agnostic via LiteLLM** — can point at the local Copilot proxy at `http://127.0.0.1:4141`, Vertex, OpenAI, or a local model. No vendor lock-in.
4. **Guardrails as ADK callbacks** — pre-tool callback redacts account numbers, owner names, dollar amounts before anything is sent to the model.
5. **Eval harness** — ADK's `adk eval` runs a fixed set of golden questions (e.g., "MSFT P7 composite score") against the pipeline on every change.

---

## 4. What we can honestly promise

| Claim | Honest? | Why |
|---|---|---|
| Natural-language interface to local MySQL portfolio data | Yes | Tools wrap existing queries; deterministic output |
| Reproducible multi-step analysis with audit trail | Yes | ADK records every tool call + arguments; phases already exist |
| Privacy preserved — raw PII never sent to LLM | Yes | Tool return values are the only thing the model sees; callback redaction enforced |
| Near-zero incremental API cost | Yes | `fmp_cached` already handles this |
| Pluggable model backend (Copilot proxy, Vertex, OpenAI, local) | Yes | LiteLLM is a documented ADK path |
| Same tools usable from CLI, FastAPI, OpenBB Pro widgets | Yes | ADK agents are Python objects; wrap once, expose anywhere |
| Eval-gated quality regressions | Yes | `adk eval` is built in |

## 5. What we will NOT claim

1. **No investment advice.** Agents surface data and run user-defined analysis. They do not recommend buy/sell.
2. **No autonomous trading.** Out of scope. Read-only tools only.
3. **No "AI predictions of returns."** Forecasts only exist if your existing pipeline produces them; the agent just narrates.
4. **No magic data quality fixes.** Garbage in, garbage out — same as today.
5. **No multi-user SaaS hosting.** Designed for single-user local deployment; matches OpenBB's current privacy model.

---

## 6. How a user would actually use it (illustrative, not implemented)

After installing the new extension:

```python
from openbb_agents import portfolio_qa

# Same MySQL, same fmp_cached, same Analysis/ pipeline underneath
response = portfolio_qa.ask(
    "Across all my accounts, what's my unrealized gain in semiconductors, "
    "and which positions are within 5% of a 52-week high?"
)
print(response.answer)        # narrative
print(response.tool_trace)    # every SQL/fmp_cached call it made
```

From the Portfolio App (`:6902`):

```
POST /agents/portfolio_qa
{ "question": "Show concentration risk in account <ACCT>" }
```

From the OpenBB CLI:

```
/agents portfolio_qa "Project ESPP qualifying dispositions for next 90 days"
```

From the existing `adk web` dev UI (for testing):

```powershell
adk web openbb_platform/extensions/agents/openbb_agents
```

Same tools. Three surfaces. Zero duplication.

---

## 7. Phased delivery (spec only — no work performed)

1. **Phase A — Foundation:** new `agents` extension skeleton, LiteLLM config pointing at local Copilot proxy, one read-only tool (`get_positions`), one trivial agent, one eval case. Proves the wiring.
2. **Phase B — Portfolio Q&A:** wrap remaining MySQL queries as tools, add guardrail callbacks, expose `/agents/portfolio_qa` on Portfolio App.
3. **Phase C — Analysis Orchestrator:** sub-agents per Analysis phase, parent planner, eval harness against MSFT/AAPL golden outputs.
4. **Phase D — Brokerage Import + Cache Steward:** operational agents that reduce manual CLI work.
5. **Phase E — Pro Widget surface:** agent-backed endpoint that returns the same dataframe shape Pro widgets already consume, plus narrative.

Each phase is independently shippable and independently revertible.

---

## 8. Risks worth naming up front

1. **Model variance** — same question, different runs may phrase differently. Mitigation: temperature 0 for analytical agents, eval harness gates regressions.
2. **Tool-call latency** — agent loops can multiply MySQL queries. Mitigation: cache steward sets per-session caps; `fmp_cached` already deduplicates.
3. **ADK API stability** — it is a young framework. Mitigation: thin wrapper layer in `agents/tools/` so the OpenBB-facing API stays stable even if ADK changes.
4. **Copilot-proxy model availability** — must use a model ID the proxy actually supports (you already hit this with `claude-opus-4.6-1m`). Mitigation: model config in one place; fallback list.

---

## 9. Using these agents from different AI surfaces

The agents extension exposes a **single set of tools** (portfolio queries, analysis phases, cache steward, etc.). Each surface below is just a different "front door" into those same tools — no duplication, no separate implementations.

---

### 9.1 Claude Code (this CLI)

**How it works:** Claude Code supports MCP servers. The Portfolio App already has an MCP server scaffold (Phase 7 of development history). The agents extension adds an `adk`-backed MCP server that Claude Code connects to automatically.

**Setup (once):**
```json
// .claude/settings.json (repo root)
{
  "mcpServers": {
    "openbb-agents": {
      "command": ".venv_win\\Scripts\\python.exe",
      "args": ["-m", "openbb_agents.mcp_server"],
      "cwd": "REPO_ROOT"
    }
  }
}
```

**Usage inside Claude Code:**
```
You: What's my current tech sector exposure across all accounts?
Claude: [calls get_positions tool → queries MySQL locally → returns answer]

You: Run a full Phase 4 valuation on MSFT
Claude: [calls run_phase4 tool → calls stock_analysis.py locally → returns DCF, MOS, sensitivity table]
```

Raw PII (account numbers, dollar amounts) never leaves the machine — the MCP server enforces the same guardrail callbacks as every other surface.

---

### 9.2 VS Code Copilot Chat (`@workspace` / `#tool`)

**How it works:** VS Code Copilot supports MCP tool servers (available in VS Code 1.99+). The same MCP server used by Claude Code is registered in VS Code's MCP settings — Copilot Chat can then call the tools via `#tool` references or automatically when the question matches.

**Setup (once):**
```json
// .vscode/mcp.json  (or VS Code User settings → MCP servers)
{
  "servers": {
    "openbb-agents": {
      "type": "stdio",
      "command": "REPO_ROOT\\.venv_win\\Scripts\\python.exe",
      "args": ["-m", "openbb_agents.mcp_server"],
      "cwd": "REPO_ROOT"
    }
  }
}
```

**Usage in Copilot Chat panel:**
```
@workspace #openbb-agents What are my top 5 positions by market value?
@workspace #openbb-agents Run stock analysis on AAPL and summarize phase 3 signals
```

Copilot invokes the tool, gets back structured data, and writes a natural-language answer inline in the chat panel. Your code editor and your portfolio data are in the same conversation.

---

### 9.3 `adk web` — Local Dev UI (built-in to ADK)

**How it works:** ADK ships a local web UI for testing agents interactively. Zero additional setup — it reads your agents directly.

```powershell
# Start the dev UI
.venv_win\Scripts\python.exe -m adk web openbb_platform/extensions/agents/openbb_agents

# Opens at http://localhost:8000/dev-ui
```

Use this for:
- Testing new tools before wiring to Claude or Copilot
- Inspecting full tool call traces (every SQL query, every fmp_cached call)
- Running eval harness: `adk eval openbb_agents --test_file evals/golden_msft.json`

---

### 9.4 Portfolio App REST API (`:6902`) — for OpenBB Workspace / Pro widgets

**How it works:** Phase B adds `/agents/*` endpoints to the existing FastAPI app. OpenBB Workspace widgets, curl, or any HTTP client can call them.

```
POST http://localhost:6902/agents/portfolio_qa
Content-Type: application/json

{ "question": "What's my unrealized gain in semiconductors?" }
```

Response:
```json
{
  "answer": "Your semiconductor exposure ...",
  "tool_trace": [{"tool": "get_positions", "args": {}, "rows_returned": 12}],
  "pii_redacted": true
}
```

OpenBB Workspace Pro widgets can be pointed at this endpoint to get a narrative alongside their existing chart data — same widget contract, no dashboard changes needed.

---

### 9.5 Plain Python / Jupyter Notebooks

**How it works:** ADK agents are plain Python objects. Import and call them directly — no server required.

```python
# In any notebook or script using .venv_win kernel
from openbb_agents.agents.portfolio_qa import PortfolioQAAgent

agent = PortfolioQAAgent()
result = agent.run("What positions are within 5% of a 52-week high?")

print(result.answer)       # narrative
print(result.tool_trace)   # full audit trail
result.data                # raw DataFrame if tool returned one
```

This is the easiest surface to start with during Phase A — no MCP, no server, just a Python call.

---

### 9.6 Surface Comparison Matrix

| Surface | Setup effort | Best for | Data leaves machine? |
|---|---|---|---|
| Claude Code (MCP) | Low — edit `.claude/settings.json` | Development, code + data questions together | No |
| VS Code Copilot Chat (MCP) | Low — edit `.vscode/mcp.json` | Daily use while coding | No |
| `adk web` dev UI | Zero — built in | Tool testing, trace inspection, eval runs | No |
| Portfolio App REST (`:6902`) | Already running | OpenBB Workspace widgets, curl, automation | No |
| Python / Jupyter | Zero — direct import | Notebooks, scripting, ad-hoc analysis | No |

All five surfaces call the same underlying tools. Adding a new tool (e.g., wrapping a new fmp_cached endpoint) automatically makes it available in every surface simultaneously.

---

### 9.7 Which surface to use when

- **Coding session** → Claude Code (MCP) or VS Code Copilot Chat — your AI assistant can query your portfolio and your code in the same chat
- **Manual analysis** → `adk web` dev UI — best trace visibility, easy to iterate on prompts
- **Automated / scheduled** → Portfolio App REST endpoint — cron job, webhook, or OpenBB Workspace widget
- **Notebooks** → Direct Python import — cleanest for reproducible research
- **Sharing a demo** → `adk web` on localhost — no credentials exposed, self-contained

---

**Status:** Spec only. No code changes. Next possible step: draft a Phase A file/entry-point map for review.
