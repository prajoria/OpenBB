# Notebook MCP Companion: product and acceptance specification

**Status:** Approved for planning and Project #4 tracking; implementation is
sequenced after the base MCP parity release, not delivered by this document.
**Baseline:** Portfolio `39f171603c9bc4a28778e668ba981cf0e4358b9a`, plus the
preserved, pre-existing working-copy notebook edit.

- [Notebook coverage report](../../cross_repo_workflow/notebook-mcp-story-coverage.md)
- [Engineering design](../../designs/notebook-mcp-agent-design.md)
- [Implementation plan](../../superpowers/plans/2026-10-03-notebook-mcp-agent.md)
- [Prerequisite MCP program](../../superpowers/plans/2026-10-03-portfolio-mcp-capability-parity.md)

## 1. User outcome

A developer can ask a Python agent to work through the same analytical story
as a repository notebook, explain each stage, produce the same classes of
tables/charts/workbooks, and resume or inspect the run without copying notebook
code into a kernel. The agent obtains data and performs financial work through
approved MCP tools. It demonstrates that MCP is sufficient for those stories,
rather than disguising missing tools with direct Python imports.

The product is **Notebook MCP Companion**, implemented inside the existing
`openbb-agents` extension, with the proposed console command
`openbb-notebook-agent`. It is separate from the existing direct-function
`portfolio_qa` agent.

## 2. Scope and sequencing

The source corpus is 25 notebooks: eight Portfolio, eight Portfolio YFinance,
and nine TechTrade notebooks. The eight similarly named provider pairs remain
distinct acceptance cases. The optional analyst-basket chapter remains included
in the denominator; it is not silently dropped from acceptance.

The preserved Portfolio deep-dive source calls `run_full_analysis` from
`Analysis/stock_analysis.py`, including seven phases and feature-flag/regime
variants. This is not interchangeable with the older pure computation module
`openbb_portfolio.stock_analysis` merely because both describe seven phases.
The free-provider deep dive is a distinct implementation and cannot be treated
as the same pipeline with a changed provider argument.

The source audit also found narrative text mislabeled as a code cell in
TechTrade morning-scan cell 7. Source classification must record this explicitly;
no original-notebook execution or silent source correction is authorized here.

Planning, source inspection, and issue creation occur now. Implementation begins
only after MCP task T44's release evidence is accepted. Notebook-specific MCP
bridges are a follow-on delivery phase: the existing API-parity program does not
prove that notebook-local analytics, files, and state are already tool-callable.
The Python agent's tool loop additionally waits for those story-specific bridges.

The first release includes:

1. Story catalog, narrative stages, input schemas, prerequisite inspection, and
   source provenance for all 25 notebooks.
2. Typed analytical, replay, state, and artifact MCP bridges where existing
   approved tools cannot express a notebook outcome.
3. Local vLLM/NVIDIA Nemotron Nano planning and explanation, with explicit
   OpenAI-compatible endpoint/model configuration.
4. Read-only research by default; authenticated sandbox paper workflows with
   human approvals; no autonomous live orders.
5. CLI and an existing-protocol Workspace agent adapter, sharing one engine.
6. Offline differential acceptance, live-model opt-in evaluation, reproducible
   demonstrations, and a transparent capability/limitations report.

## 3. Functional requirements

| ID | Requirement | Acceptance owner |
| --- | --- | --- |
| FR-01 | Enumerate all 25 notebook sources; map family, provider variant, ordered stages, source-only hashes and cell references. Never read saved outputs into prompts or fixtures. | N01, N02 |
| FR-02 | Present a story catalog and inspect a story without executing it. Show required tools, providers, permissions, artifacts, unsupported stages and readiness. | N04, N06, N16 |
| FR-03 | Select a named story or resolve a natural-language goal to one; show a deterministic stage plan with provider, date range, budget and required approvals before execution. | N14, N16 |
| FR-04 | Execute financial data retrieval, analysis, scoring, attribution, tuning, backtesting, replay and paper fills only through approved MCP tools. Reuse existing engines behind server adapters. | N05, N08, N09, N10, N13 |
| FR-05 | Support both Portfolio and free-provider variants without promising identical live results. Display provider availability, subscription/credential requirements, as-of dates and data gaps. | N03, N10, N18 |
| FR-06 | Preserve story state and artifact lineage across chapters using typed JSON-compatible schemas and run IDs, not notebook pickle files or arbitrary filesystem paths. | N02, N06, N07, N21 |
| FR-07 | Produce normalized tables, chart specifications/data, Markdown reports, JSON audit/replay artifacts, and required XLSX workbooks through bounded server-side artifact tools. | N07, N15 |
| FR-08 | Run expensive backtests/tuning/replay through the existing job system with inspect, cancel and explicit terminal states. Never replay a mutation just because a client timed out. | N08, N12, N21 |
| FR-09 | Support paper scenarios, validation gates, order batches and fill simulation only in a named isolated sandbox with a request-specific human approval. Preserve separate Portfolio and TechTrade paper-engine semantics. | N09, N20 |
| FR-10 | Inspect discovered tool schemas, activate required categories, qualify colliding tool names by server and version, and fail before starting if mandatory capabilities are absent. | N04, N12, N13 |
| FR-11 | Use the configured locally hosted vLLM endpoint and explicit served model ID. Validate native tool calling before a run; never probe cloud/Copilot/Ollama fallback providers. | N11, N19 |
| FR-12 | Explain results with tool-call/artifact citations and distinguish observations, calculations, assumptions, missing evidence and suggestions. Never invent values after a tool error. | N15, N19 |
| FR-13 | Resume a interrupted run from verified checkpoints with the same manifest/catalog versions, authorizations and idempotency keys. Detect and reject incompatible state drift. | N21 |
| FR-14 | Showcase complete notebook-equivalent journeys in CLI and Workspace; the Workspace adapter delegates to the same engine and MCP sessions. | N16, N22, N24 |
| FR-15 | Keep coverage synchronized with `origin/portfolio` and future notebook/engine/API changes; record new gaps instead of silently shrinking the corpus or passing skipped cases. | N01, N18, N23 |

## 4. Intended developer experience

Examples are proposed interfaces, not commands that exist today:

```powershell
openbb-notebook-agent stories list
openbb-notebook-agent stories inspect portfolio/03
openbb-notebook-agent doctor --story portfolio_yfinance/02
openbb-notebook-agent plan --story techtrade/09 --mode fixture
openbb-notebook-agent run --story portfolio/03 --mode fixture
openbb-notebook-agent run --story techtrade/09 --mode paper --sandbox demo-paper
openbb-notebook-agent runs inspect <RUN_ID>
openbb-notebook-agent runs resume <RUN_ID>
openbb-notebook-agent artifacts list <RUN_ID>
```

`stories inspect` and `plan` must not submit analytical jobs, change paper
accounts, access a browser, or consume paid provider quota. `doctor` performs
only expressly described metadata checks and a bounded model tool-call probe.
A missing browser blocks Workspace publication, not a CLI read-only story.

Inputs include story ID, variant, analysis dates, synthetic/public symbol
selection, input dataset references, provider preference, execution mode and
bounded budgets. No account credentials or local files are included in model
prompts. Private portfolio references are opaque, authorized server-side IDs.

A run presents:

1. Selected narrative and prerequisite report.
2. Stage plan and evidence expectations.
3. Progress and explicit approvals where needed.
4. Stage results, charts and artifact links with provenance.
5. Final comparison to the notebook's learning/business outcomes.
6. Limitations and exact failed/unavailable stages.

## 5. Model contract

Use these product configuration names:

| Setting | Meaning |
| --- | --- |
| `OPENBB_NOTEBOOK_LLM_BASE_URL` | Required OpenAI-compatible local endpoint ending in `/v1`; no implicit port. |
| `OPENBB_NOTEBOOK_LLM_MODEL` | Required served model ID verified by `/v1/models`. |
| `OPENBB_NOTEBOOK_LLM_API_KEY` | Optional secret for a local authenticated deployment; never logged. |
| `OPENBB_NOTEBOOK_MCP_CONFIG` | Required configuration file for approved server IDs, URLs and secret references. |

The exact Nemotron model/revision, vLLM version, chat template, tool-call parser,
context limit and hardware are deployment inputs to record during qualification,
not guessed constants. Port 8000 is already used by the self-hosted Workspace
deployment; the agent must not appropriate it. No model downloads, model-server
startup, GPU reconfiguration or remote hosting is part of this planning work.

Default endpoint policy is loopback only. A local-network deployment requires an
explicit operator allowlist and appropriate transport/authentication; it must not
silently authorize public or cloud endpoints. Follow redirects only within that
allowlist. Tool-call preflight must fail clearly if the served model/template
cannot return a valid structured tool call.

## 6. Safety and non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR-01 | Preserve Python package floors; test the existing Portfolio Python 3.12 and supported launcher Python 3.13. Do not raise the base OpenBB range `>=3.10,<3.14`. |
| NFR-02 | Reuse existing MCP SDK, LiteLLM, Pydantic, pytest and approved job/artifact infrastructure. No additional agent framework without a demonstrated need. |
| NFR-03 | No `eval`, `exec`, notebook-kernel execution, arbitrary shell, SQL, direct `obb`/provider calls or dynamic imports in the agent tool loop. Server adapters may call reviewed existing engines. |
| NFR-04 | Model output and tool-returned text are untrusted data. Only known schema-valid tools and approved argument values may execute. |
| NFR-05 | Preserve credentials and private data boundaries across all four MCP implementations. A Workspace token is not a universal Platform/Jobs/Agents credential. |
| NFR-06 | Default run budget: 40 tool calls, two argument-repair attempts per failed call, 15 minutes wall time, one mutating call at a time. Operators can lower limits; increases require explicit configuration before the run. |
| NFR-07 | Default provider-network budget is zero in fixture mode. Live read mode requires affirmative consent to declared provider/quota/cache-write effects. |
| NFR-08 | Request-specific paper approvals bind principal, sandbox, tool, normalized arguments, manifest version and expiration. Approval cannot be supplied by the LLM or reused for different arguments. |
| NFR-09 | Artifacts are authorized opaque references with hashes, content types, sizes and retention. Reject traversal, external symlinks, overwrite and unauthorized cross-run access. |
| NFR-10 | Logs contain redacted structural provenance; no raw prompts with private positions, access tokens, saved notebook outputs or provider secrets. |
| NFR-11 | Errors are typed and visible: unavailable capability, authorization required/denied, provider unavailable, invalid arguments, budget exceeded, expired approval, failed job, incompatible checkpoint. |
| NFR-12 | Monetary results use existing engine precision and explicit currency; ratios, dates, time zones and tolerances are part of each artifact schema. |

## 7. Acceptance gates

| ID | Measurable release gate |
| --- | --- |
| AC-N01 | 25/25 notebooks have unique source manifests and a reviewed ordered-stage mapping. All provider variants and the optional eighth Portfolio chapter remain represented. |
| AC-N02 | 100% of required stage outcomes have approved tool mappings or visible blocking issues. Release requires zero unresolved mandatory outcomes; exclusions cannot be called coverage. |
| AC-N03 | All 25 fixture stories pass the deterministic MCP runner on two repeated runs. Zero fixture-mode provider-network calls; stable normalized artifacts on replay. |
| AC-N04 | Differential tests compare independent frozen expectations or isolated developer notebook oracles against MCP results. Money, schema, IDs, dates and order are exact where specified; other numeric outputs meet reviewed per-metric tolerances. |
| AC-N05 | On the pinned local Nemotron deployment, run all 25 fixture cases twice: at least 48/50 end-to-end successes, and 100% of the designated showcase journeys pass. Record failures, latency, tool count and token usage without hiding retries. |
| AC-N06 | Every denial, malformed-call, injection, unavailable-provider, timeout and resume/idempotency case passes. Zero unauthorized mutations, zero live orders, zero cloud fallback, zero secrets in captured logs. |
| AC-N07 | Required tables, chart data/specifications, XLSX sheets/cells, JSON replay records and Markdown citations meet story-specific schemas. A narrative-only answer cannot pass an artifact-producing stage. |
| AC-N08 | CLI and Workspace invoke the same orchestration engine and emit equivalent run IDs/evidence. An absent browser session yields an explicit publication error without falsifying analytical completion. |
| AC-N09 | CI detects changed source-only notebook hashes and `origin/portfolio` capability drift. New or changed stories fail classification until reviewed. |
| AC-N10 | T44 and all follow-on bridge, safety, parity, model and release tasks have verified evidence linked in Project #4. Branch/PR integration remains `portfolio`. |

## 8. Showcase journeys

All 25 notebooks are tested; these are the public demonstrations, not a smaller
replacement acceptance corpus:

- Portfolio: provider orientation -> single-name analysis -> basket x-ray ->
  events/smart-money -> what-if/attribution -> backtest -> offline replay.
- Free-provider track: the same staged story with explicit free-provider
  limitations, and the analyst-recommendation basket extension.
- TechTrade: foundations -> morning scan -> single-position analysis ->
  validation -> per-sector tuning -> audit/replay.
- T5: validated plan -> order batch -> XLSX workbook -> human-approved sandbox
  paper run -> fills and reconciled evidence.

Demonstrations use synthetic or redistributable frozen data. Executing original
notebooks is allowed only in separately authorized, isolated developer parity
tests, never as a hidden implementation of the product agent.

## 9. Non-goals

No general-purpose coding assistant, arbitrary notebook editing/execution,
broker credentials, live trading, replacement financial engine, training or
fine-tuning Nemotron, unsupported provider data fabrication, full notebook
pixel-perfect rendering, or automatically installing/starting local services.
Exporting a new tutorial notebook is an optional later feature, not required for
first-release analytical and artifact parity.
