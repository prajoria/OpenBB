# Repository inventory

## Inventory method

The inventory treats a project as canonical when it has its own Git metadata
and remote. It excludes virtual environments, dependency caches,
`node_modules`, generated build output, and alternate Git worktrees. Internal
packages and applications are catalogued beneath their owning repository but
are not counted as independent repositories.

## Canonical repositories

| Repository | Role | Default working branch at audit | Audited revision | Tracked files |
| --- | --- | --- | --- | ---: |
| `OpenBB` | Platform fork and integration control plane | `feature/dual-mcp-launcher` | `1acb29387fe3` | 4,680 |
| `workspace` | Workspace product source | `main` | `be00e95019a5` | 2,287 |
| `openbb-workspace-bench` | Workspace/MCP benchmark and simulator | `main` | `b11572b59b7a` | 517 |
| `backends-for-openbb` | Custom backend examples | `main` | `a6293707576e` | 163 |
| `agents-for-openbb` | Custom agent examples | `main` | `aa1073d2b098` | 89 |
| `openbb-rag-financial-research-agent` | Deployable RAG agent | `main` | `a69cbce56cc8` | 30 |

Revision and file-count values are a point-in-time audit snapshot, not a
release compatibility promise.

## Workspace roots and non-project directories

### `OpenBBAll`

`OpenBBAll` is a filesystem/IDE aggregation root. Its workspace file opens the
aggregation root and the adjacent `OpenBB-Portfolio` root. The five child
repositories retain independent histories, remotes, dependency managers, and
release cycles.

### `OpenBB-Portfolio`

`OpenBB-Portfolio/OpenBB` is the canonical Git repository. The following
sibling directories are not additional canonical projects:

- `.worktrees/` and `worktrees/` contain alternate worktree checkouts.
- `openbb_platform/` and `theme-parity-1837/` are adjacent task/worktree
  artifacts, not independent repositories.
- `.venv/`, `.pytest_cache/`, and `.ruff_cache/` are generated local state.

## `OpenBB`: platform and integration control plane

### Main product areas

| Area | Responsibility | Relationship to other repositories |
| --- | --- | --- |
| `openbb_platform/core` | Core OpenBB Python runtime and extension loading | Foundation for Platform extensions and providers |
| `openbb_platform/providers` | 34 provider projects | Supplies normalized market/economic data |
| `openbb_platform/extensions` | 28 extension projects | Domain commands plus fork-specific portfolio, agents, MCP, backtest, techtrade, and intelligence surfaces |
| `openbb_platform/tools` | Five supporting projects | Portfolio export/import, utilities, scraping, and browser harnesses |
| `openbb_platform/extensions/platform_api` | `openbb-api` launcher and Workspace manifest aggregation | Hosts custom backend contracts used by Workspace |
| `openbb_platform/extensions/mcp_server` | OpenBB Platform MCP server | Exposes Platform API routes as MCP tools/resources |
| `openbb_platform/extensions/portfolio` | Unified portfolio/stock/ESPP backend and local copilot | Produces Workspace manifests and uses `openbb-ai` |
| `openbb_platform/extensions/portfolio_intel` | Portfolio intelligence, risk, events, paper trading | Depends on sibling `openbb-backtest` and `openbb-techtrade` |
| `openbb_platform/extensions/agents` | Google ADK-based portfolio agents | Directly depends on the `adk-python` submodule and sibling Portfolio services |
| `desktop` | Desktop shell | Packages local OpenBB-facing desktop behavior |
| `apps/vscode-terminal-extension` | VS Code integration | Developer-facing client surface |
| `copilot-api` | OpenAI-compatible model proxy submodule | Optional runtime for Portfolio Copilot and local agents |
| `third_party` | Pinned adjacent projects, examples, docs, and references | Canonical cross-repository dependency view |

### Internal package relationships

The top-level `openbb` distribution aggregates `openbb-core`,
`openbb-platform-api`, domain extensions, and provider packages. Fork-specific
packages are editable path dependencies from `openbb_platform/pyproject.toml`.
Notable internal dependencies are:

- `openbb-portfolio-intel` -> `openbb-backtest` and
  `openbb-techtrade`;
- `openbb-agents` -> `adk-python`, portfolio tools, cached FMP data, and an
  OpenAI-compatible LiteLLM endpoint;
- `openbb-portfolio-custom` -> `openbb-core`, `openbb-ai`, MySQL, and the
  OpenAI SDK;
- `openbb-platform-api` -> `openbb-core` and manifest-merging logic;
- `openbb-mcp-server` -> `openbb-core` and FastMCP.

## `workspace`: Workspace product

| Internal project | Stack | Responsibility |
| --- | --- | --- |
| `terminalpro` | React 18, TypeScript, Vite | Workspace UI, backend connectors, widget/app rendering, agent UI, browser side of Workspace MCP |
| `backend-api/backend` | Python 3.13, FastAPI, SQLAlchemy | Accounts, persistence, marketplace, custom backend metadata, agent services, integrated Workspace MCP |
| `backend-api/admin_frontend` | Web frontend | Workspace administration UI |
| `backend-api/admin_cli` | CLI | Administrative operations |
| `lite` | Docker packaging | Assembles a self-host-oriented frontend/backend image |
| `excel-add-in` | Office.js, TypeScript/React | Excel integration |

The backend declares `openbb-ai ^2.1.0` and FastMCP. It validates and caches
third-party `widgets.json` and `apps.json` documents and exposes integrated
Workspace MCP routes. The frontend fetches those manifests and executes the
configured endpoints.

This repository is a **consumer** of custom backend and agent protocols. It
does not need to import the `OpenBB` repository to connect to the Portfolio
backend.

## `backends-for-openbb`: backend contract examples

This repository contains getting-started applications and focused widget
examples. Most use FastAPI; some demonstrate Streamlit, database connectors,
iframe communication, server-side row models, advanced charting, and MCP tool
matching.

Its contract with Workspace is:

1. serve CORS-enabled JSON data endpoints;
2. serve `widgets.json`;
3. optionally serve `apps.json`;
4. optionally advertise or pair widgets with MCP tools.

It is a reference and compatibility corpus for the Portfolio fork and
Workspace source, not a source-code dependency.

## `agents-for-openbb`: agent contract examples

The repository contains 15 example areas covering:

- prompt improvement;
- raw widget data and citations;
- reasoning events;
- chart/table/PDF output;
- dashboard and context access;
- MCP tool use;
- custom features, dynamic skills, and feedback.

The root Poetry environment depends on `openbb-ai ^2.0.1`, FastAPI,
SSE-Starlette, OpenAI, and supporting model SDKs. Each deployable agent exposes
an `agents.json` descriptor and a query endpoint, commonly `/v1/query`, whose
stream follows OpenBB AI SDK event models.

## `openbb-rag-financial-research-agent`: specialized agent

This repository is an independently deployable FastAPI/SSE agent that combines:

- OpenBB widget data obtained through `openbb-ai`;
- SEC filings, transcripts, PDFs, and custom documents;
- ChromaDB vector search;
- OpenAI-compatible language and embedding endpoints.

It depends on `openbb-ai ^1.7.5`, exposes `/agents.json` and `/v1/query`, and
supports OpenAI, Azure OpenAI, Ollama, vLLM, and other compatible endpoints.
Its architecture is a specialization of the patterns demonstrated by
`agents-for-openbb`, not a dependency of that example repository.

## `openbb-workspace-bench`: validation layer

The benchmark has no mandatory runtime dependencies beyond the standard Python
package itself. Optional extras add test tooling and live MCP clients.

Its three execution modes have different dependency meanings:

| Mode | Dependency | What it proves |
| --- | --- | --- |
| Simulator | Bundled schemas, fixtures, and state machine | Deterministic agent/tool behavior |
| Live smoke/parity | Hosted or local Workspace MCP endpoint | Transport and tool-surface compatibility |
| Harbor export | A separate committed `workspace-mcp` repository | Reproducible sidecar-backed evaluation bundle |

The committed tasks and fixture backends mirror Workspace concepts and backend
examples. That is data/schema provenance, not an import dependency.

## Externally owned dependencies that shape the graph

| Dependency | Used by | Why it matters |
| --- | --- | --- |
| `openbb-ai` | Workspace backend, agent examples, RAG agent, Portfolio custom copilot | Defines the custom-agent HTTP/SSE contract |
| FastMCP / MCP SDK | OpenBB MCP, Workspace MCP, benchmark live path, agent examples | Defines tool/resource/prompt transport |
| OpenAI-compatible API | RAG agent, example agents, Portfolio copilot, local agents | Decouples model hosting from application code |
| Google ADK fork | `openbb-agents` extension | Direct source dependency pinned as `third_party/adk-python` |
| MySQL / Redis | Portfolio and Workspace backends | Runtime infrastructure; not vendored source |
| Browser/Workspace hosted services | Workspace and live benchmark checks | External runtime boundary |

