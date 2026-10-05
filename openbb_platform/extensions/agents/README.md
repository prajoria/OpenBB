# OpenBB Agents

Google ADK agents on top of the OpenBB platform.

The implemented product currently contains one Portfolio Q&A agent and an
explicitly allowlisted two-tool MCP surface:

- `get_positions`
- `get_sector_exposure`

Stock-analysis orchestration, brokerage import, cache stewardship, and ESPP
planning are separately scoped expansion products. They are not registered MCP
tools and must not be described as enabled until their own implementation,
privacy, and protocol reviews are complete.

> **Status:** Phase A (foundation). See
> [`docs/OpenBB Agent/DESIGN.md`](../../../docs/OpenBB%20Agent/DESIGN.md) for the
> full design.

## Current guarantees

- **No investment advice.** Agents surface data; they never recommend buy/sell/hold.
- **Two read-only tools.** No autonomous trading, brokerage import, cache
  mutation, ESPP planning, or writes.
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

Tool discovery is fail-closed. A synchronous function is exposed only when it:

1. is defined by an owned module in the registry;
2. carries the explicit `@mcp_tool` marker;
3. is public under both its module alias and underlying function name; and
4. is synchronous.

Undecorated functions, re-exported/public aliases of private functions, async
functions, and private dependency-injection parameters are excluded. Missing
tool dependencies return a sanitized `tool_failed` response and log details
locally.

## Layout

```
openbb_agents/
  config.py        # dynamic LiteLLM model selection
  guardrails.py    # PII redaction before_model_callback
  mcp_server.py    # stdio MCP entry-point
  router.py        # FastAPI /agents/* routes
  tools/           # implemented sanitized portfolio tool layer
  agents/          # implemented Portfolio Q&A agent
  evals/           # adk eval golden test cases
```

## Tests

```bash
.venv_win\Scripts\python.exe -m pytest openbb_platform/extensions/agents/tests -v
```
