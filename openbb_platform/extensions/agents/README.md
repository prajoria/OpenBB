# OpenBB Agents

Google ADK agents on top of the OpenBB platform. Surfaces five agents
(portfolio Q&A, stock-analysis orchestration, brokerage import, cache
stewardship, ESPP planning) through MCP, `adk web`, the Portfolio App REST
API, and plain Python — with a single shared tool layer.

> **Status:** Phase A (foundation). See
> [`docs/OpenBB Agent/DESIGN.md`](../../../docs/OpenBB%20Agent/DESIGN.md) for the
> full design.

## Guarantees

- **No investment advice.** Agents surface data; they never recommend buy/sell/hold.
- **Read-only tools.** No autonomous trading, no writes.
- **PII never reaches the LLM.** Account numbers and owner names are redacted by
  an ADK `before_model_callback` guardrail.
- **`fmp_cached` only.** All market data flows through the cached FMP provider.

## Install

The extension depends on a local fork of `google-adk`. Install it first, then
the extension in editable mode:

```bash
# from repo root, inside .venv_win
.venv_win\Scripts\pip.exe install -e I:/masterswork/git/adk-python
.venv_win\Scripts\pip.exe install -e openbb_platform/extensions/agents
```

## Configuration

Model selection is dynamic — `config.py` probes a candidate list against your
LiteLLM endpoint and uses whatever responds. Override via env vars:

| Env var | Default | Purpose |
|---|---|---|
| `LITELLM_BASE_URL` | `http://127.0.0.1:4141` | LiteLLM / Copilot proxy base URL |
| `LITELLM_API_KEY` | `copilot` | API key for the proxy |
| `OPENBB_AGENTS_MODEL` | _(probe)_ | Force the analytical model, skip probe |
| `OPENBB_AGENTS_CONV_MODEL` | _(probe)_ | Force the conversational model |
| `OPENBB_AGENTS_PROBE_TIMEOUT` | `6` | Per-model probe timeout (seconds) |

## Run the MCP server

```bash
.venv_win\Scripts\python.exe -m openbb_agents.mcp_server
```

## Layout

```
openbb_agents/
  config.py        # dynamic LiteLLM model selection
  guardrails.py    # PII redaction before_model_callback
  mcp_server.py    # stdio MCP entry-point
  router.py        # FastAPI /agents/* routes
  tools/           # portfolio, analysis, fmp_cache, espp tool layers
  agents/          # the five LlmAgent / SequentialAgent definitions
  evals/           # adk eval golden test cases
```

## Tests

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/agents/tests -v
```
