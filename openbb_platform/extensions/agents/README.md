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

The extension depends on a fork of `google-adk`
([`prajoria/adk-python`](https://github.com/prajoria/adk-python)). Install it
first, then the extension in editable mode.

The fork is vendored as a git submodule at `third_party/adk-python` to avoid
machine-specific paths. Initialize the submodule, then install both packages:

```bash
# from repo root, inside .venv_win
git submodule update --init third_party/adk-python
.venv_win\Scripts\pip.exe install -e third_party/adk-python
.venv_win\Scripts\pip.exe install -e openbb_platform/extensions/agents
```

> If you prefer not to use the submodule, install the fork directly:
> `pip install -e "git+https://github.com/prajoria/adk-python@main#egg=google-adk"`

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

Configure your MCP client by copying `.mcp.json.example` (at the repo root) to
`.mcp.json` and replacing `${workspaceFolder}` with your local checkout path.
`.mcp.json` is gitignored so machine-specific paths never get committed.

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
