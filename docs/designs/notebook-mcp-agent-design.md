# Notebook MCP Companion: engineering design

**Status:** Design for future Python implementation, after MCP T44.

- [Source specification](../Specs/notebook-mcp-agent/requirements.md)
- [Implementation plan](../superpowers/plans/2026-10-03-notebook-mcp-agent.md)
- [Source coverage report](../cross_repo_workflow/notebook-mcp-story-coverage.md)

## 1. Component boundaries

```text
CLI / existing Workspace agent HTTP+SSE protocol
  -> shared Python notebook_guide orchestrator
       -> configured local vLLM OpenAI-compatible chat endpoint
       -> authenticated MCP clients + policy/approval enforcement
            -> Platform/Portfolio read and story adapters
            -> existing jobs workers and financial engines
            -> authorized artifact/run registry
            -> optional Workspace MCP publication bridge
```

The model proposes plans, tool calls and explanations. The orchestrator checks
them; the MCP server performs financial work. Python is the implementation
language, not an escape hatch for executing model-generated financial code.

Do not reuse the existing agent configuration's automatic model-provider probing.
Reuse the existing LiteLLM dependency as a transport only with one explicit
OpenAI-compatible model/base URL and fallback disabled. Use the official MCP
client SDK for initialized sessions and structured tool results. Existing
`portfolio_qa` and its two direct `FunctionTool` calls remain unchanged.

## 2. File ownership

All paths below are planned, not claims that these files already exist.

| Path relative to repository root | Responsibility |
| --- | --- |
| `scripts/notebook_story_inventory.py` | Source-only notebook inventory; no kernel/provider imports. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/contracts.py` | Typed manifests, stages, capability references, evidence, plans and run states. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/stories/` | 25 reviewed JSON manifests and versioned synthetic scenario inputs. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/local_model.py` | Endpoint validation, model/tool-call preflight and configured model transport. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/mcp_client.py` | Server-qualified schemas, sessions, discovery activation, auth and reconnect rules. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/policy.py` | Argument/access policy, budgets and approval request binding. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/runner.py` | Bounded tool loop and deterministic stage orchestration. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/planner.py` | Story selection and stage DAG planning. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/evidence.py` | Evidence envelope and cited explanations; no financial calculations. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/checkpoints.py` | Resume validation and idempotency reconciliation. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/cli.py` | Console entry point and explicit approval UX. |
| `openbb_platform/extensions/agents/openbb_agents/notebook_guide/workspace_app.py` | Existing Workspace manifest/query/SSE contract over the same runner. |
| `openbb_platform/extensions/agents/tests/notebook_guide/` | Offline contracts, policy, transport, differential and end-to-end tests. |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/story_adapters/` | Thin typed MCP-facing story/analytics/job/artifact adapters. |
| `openbb_platform/extensions/mcp_server/tests/story_adapters/` | Server adapter authorization and engine-equivalence tests. |

Keep scenario definitions and display narrative free of personal data. Reuse
existing Portfolio/TechTrade/backtest engine packages rather than moving their
business logic into the agent. During N05, extract notebook-local reusable
calculations to their owning engine with backward-compatible notebook imports;
do not duplicate a risk/attribution/backtest implementation inside an adapter.

The current Portfolio deep dive imports `stock_analysis` from the repository's
`Analysis` area and calls `run_full_analysis(AnalysisConfig(...))`. N05 must
bridge that actual pipeline and its `AnalysisFeatureFlags`/regime-dependent
outputs. The existing `openbb_portfolio.stock_analysis` module and `/stock/*`
widget routes are older related calculations, not proven-equivalent substitutes.
Use `Analysis/tests/test_stock_analysis.py` as prior art and regression coverage.
If packaging the pipeline is necessary, preserve its public import contract and
avoid making a second copy in the MCP extension.
Retain all seven intermediate phase outputs and diagnostics, not only the final
decision score. Fixture execution must use an isolated server/provider context;
never globally monkeypatch a live server's data client to supply synthetic data.

## 3. Versioned contracts

Implement Pydantic models with `extra="forbid"` and explicit versions:

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class CapabilityRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: str
    tool: str
    schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    access: Literal["metadata", "provider_read", "analysis", "artifact", "paper"]

class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    artifact_id: str
    media_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)

class StageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_id: str
    status: Literal["succeeded", "failed", "unavailable", "approval_required"]
    tool_call_ids: list[str]
    artifacts: list[ArtifactRef]
    limitations: list[str]
```

The implementation extends this core with:

- `StoryManifest`: schema version, story ID, family/variant, relative notebook
  path, source-only SHA256, numbered cell references, ordered `StoryStage`s,
  typed input/output schema references and independent acceptance case IDs.
- `StoryStage`: ID, prerequisite stage IDs, required capabilities, input
  bindings, access class, artifact expectations and explicit optional status.
- `RunPlan`: manifest/catalog version, normalized inputs, provider mode,
  sandbox reference, ordered stage IDs and approved budgets.
- `RunState`: run/plan IDs, state version, stage statuses, job references,
  evidence references and pending approval IDs.
- `ApprovalRequest`: principal, sandbox, tool, normalized argument hash,
  manifest version, expiration and one-use nonce; never an LLM boolean.

Source fingerprinting serializes the ordered `(cell_type, source_text)` pairs
of code/Markdown cells, not outputs, execution counts or metadata. Cell
references are one-based notebook positions. The inventory stores hashes and
safe extracted symbols, not full notebook source or copied outputs.
Static parse failures are explicit inventory diagnostics: TechTrade morning-scan
cell 7 currently contains narrative in a code cell. Review/classify it before
oracle execution; do not silently discard an unparsed cell or rewrite the source.

Run state uses authenticated server-side JSON schemas with optimistic
concurrency. Do not deserialize notebook pickle files. An input dataset must be
an authorized opaque reference, not an arbitrary Python expression or local
path.

## 4. MCP surfaces and reuse

Existing typed tools remain canonical when they already meet a stage contract.
The following are **proposed semantic operations**, not current discovered tool
names. N04 binds them to actual server-qualified tools and schema hashes.

| Adapter group | Proposed operations | Existing ownership |
| --- | --- | --- |
| Story metadata/state | list stories, describe story, validate prerequisites, create/inspect run, checkpoint stage | New bounded registry using existing auth/persistence conventions |
| Analytics | basket risk/lookthrough, event timeline join, attribution comparison, recommendation basket evaluation | Portfolio Intelligence, backtest and existing provider engines |
| TechTrade | validation evidence, tuning, order-batch construction, replay inspection | TechTrade analysis/validation/tuning/execution packages |
| Jobs | submit allowlisted stock-pipeline/backtest/tuning/replay job, inspect result/status, cancel | Existing authenticated durable jobs router and workers |
| Artifacts | render table/chart/report, create XLSX, list/read authorized run artifacts | Existing render/workbook helpers behind bounded artifact storage |
| Paper | prepare sandbox action, request approval, apply approved action, inspect fills/state | Separate Portfolio and TechTrade paper engines |
| Provider mode | inspect provenance/availability, validate frozen/live provider inputs | Existing provider machinery and MCP cache policy |

Do not add a generic `run_python`, `execute_notebook`, `query(model, params)`,
`sql`, `read_file(path)` or `call_function(import_path)` MCP tool. Narrow bridge
schemas explicitly enumerate supported operations and dataset/state references.

Where N05 extracts a notebook-local calculation, first characterize it with
frozen inputs and expected values. The MCP adapter and notebook then use that
reviewed engine function, while an independent oracle/fixture still checks
financial correctness. Two wrappers calling the same broken implementation are
not sufficient parity evidence.

## 5. Tool-discovery and local-model protocol

1. Validate configuration and endpoint policy without importing cloud-agent
   defaults. Require an explicit model and base URL.
2. Probe `/v1/models` and one bounded native-tool-call fixture. Verify returned
   tool name, JSON arguments and expected argument types.
3. Initialize each configured MCP session with its own authorization; list
   helpers/categories and activate only categories needed by the story.
4. Build the union catalog keyed by `(server_id, tool_name, schema_sha256)`.
   Expose collision-free model aliases, retaining original protocol names.
5. Confirm required resources/prompts/tools and argument schemas before
   planning. Treat missing, forbidden and browser-unavailable distinctly.
6. Supply the model only reviewed stage context and necessary schemas. Do not
   dump all 236 tools or private raw data into the context.
7. Validate every native tool call, bind dataset/run IDs, check capability
   policy, get human approval if needed, and call MCP.
8. Record structured result or error. The model may explain a failure but may
   not fabricate a successful financial result.

Do not treat text that resembles JSON as a successful native tool call.
Two repair attempts apply only to malformed proposed arguments; they do not
authorize repeating a provider call or mutation after uncertain completion.
Read-only retries require an explicit retryable error and remaining budget.

## 6. Execution and recovery

Run states:

```text
planned -> ready -> running -> succeeded
                   |    |
                   |    +-> awaiting_approval -> running
                   +------> failed / cancelled / budget_exceeded
```

Individual stage evidence also records unavailable capabilities. A cancelled or
failed run does not become succeeded merely because some artifacts exist.
Optional stages may be explicitly declined, but a release story's mandatory
outcomes cannot be replaced with optional status.
Cross-chapter feedback, such as a scenario triggering a new concentration
analysis, creates a new plan revision/run. It is not a cycle inside one stage DAG.

Each side-effecting request has a persistent operation ID and normalized input
hash. On timeout/reconnect, inspect the operation/job state before retrying.
Deduplicate paper action IDs server-side. Resume revalidates principal, sandbox,
manifest/catalog versions, permissions, evidence hashes, pending jobs and
remaining budget. Approvals expire and are never silently renewed by resume.

Job cancellation uses existing worker semantics: report requested, confirmed,
or too-late-to-cancel distinctly. Do not equate transport disconnect with
successful cancellation.

## 7. Artifacts and presentation

- Tables: schema, units/currency, as-of date, provider, null semantics and row
  ordering.
- Charts: versioned chart specification plus exact underlying data; test these,
  not screenshots.
- XLSX: expected sheets, columns, formulas/values and numeric precision; exclude
  unstable archive timestamps from comparisons.
- JSON: typed replay/audit/state exports without pickle or embedded secrets.
- Markdown: evidence references per factual result, limitations and stage
  completion summary.

Artifact identifiers are scoped to a run/principal. The server owns storage
roots and generates file names. Resolve and validate paths against those roots,
including symlinks; deny cross-run access and overwrites. Apply configured
retention and size limits before publication. Model-generated labels/cells must
not become executable spreadsheet formulas.

Workspace registers an agent through the existing `agents.json` and query/SSE
contracts. It publishes artifacts through authenticated existing interfaces,
not direct browser storage manipulation. Browser/widget mutations require their
own consent and must not inherit paper approvals. CLI remains usable without
the Workspace adapter.

## 8. Evaluation and release

Use the existing pytest runner, frozen/synthetic data and fake local-model/MCP
transports for default CI. Real local-model evaluation is opt-in and records the
exact deployment tuple; real provider or paper operational tests require their
own approval.

Maintain three separate measurements:

1. **Source/stage coverage:** all 25 manifests and required outcomes mapped.
2. **Deterministic protocol parity:** all fixture stages invoke actual MCP
   adapters and match independent expectations.
3. **Model orchestration reliability:** 50 bounded local-model runs with at
   least 48 successful outcomes and every showcase journey passing.

Task status, catalog count and model fluency are not substitutes for these
measurements. CI compares current `origin/portfolio` ancestry and source hashes,
then requires human review of new or changed capabilities.

## 9. Acceptance mapping

| Design section | Specification |
| --- | --- |
| Component boundaries, file ownership | FR-04, FR-14, NFR-01..03 |
| Versioned contracts | FR-01, FR-06, FR-13, AC-N01 |
| MCP surfaces | FR-02, FR-04..10, AC-N02..04 |
| Model and discovery protocol | FR-10..12, NFR-04..08, AC-N05..06 |
| Execution/recovery | FR-08..09, FR-13, NFR-06..11 |
| Artifacts/presentation | FR-07, FR-12, FR-14, AC-N07..08 |
| Evaluation/release | FR-15, AC-N03..06, AC-N09..10 |
