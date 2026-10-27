# Portfolio MCP Capability Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task after approval. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Portfolio fork's implemented, approved capabilities discoverable and usable through MCP, with reproducible runtime profiles, truthful cache semantics, explicit access boundaries, and continuously measured coverage.

**Architecture:** Retain the Platform, Workspace, Agents, and Daytrade boundaries rather than replace them with one indiscriminate server. Build a shared capability inventory and reviewed exposure policy; route existing FMP fetchers through OpenBB's provider machinery; compose approved application adapters into a Portfolio MCP profile; retain the authenticated browser bridge for Workspace state.

**Tech Stack:** Existing Python/OpenBB Router, FastAPI, FastMCP/MCP SDK, Pydantic, pytest, PowerShell/Pester, GitHub Actions, GitHub Projects, existing Workspace browser harness, and existing cache/jobs infrastructure.

## Global Constraints

- **Planning and tracking only.** The original delivery was plan-only. The subsequent notebook-agent request authorized creating this hierarchy in Project #4; it did not start implementation, deployments, or live-data validation.
- Target project: [Portfolio Intelligence Engine, Project #4, Board view](https://github.com/users/prajoria/projects/4/views/2).
- Parent repository: `prajoria/OpenBB`. Parent-repository feature PRs target `portfolio`, never `develop` or an upstream fork.
- Audited baseline: `39f171603c9bc4a28778e668ba981cf0e4358b9a`. Reconcile subsequent Portfolio changes before implementation; do not reset them.
- Current branch: `feature/dual-mcp-launcher`, tracking `origin/portfolio`. Preserve this tracking when publishing; do not use `git push -u` to replace it.
- No automatic trading, broker submission, raw brokerage import, arbitrary SQL, arbitrary filesystem access, or secret-setting tools in the default MCP profile.
- Existing Platform behavior remains the compatibility default. The new Portfolio profile is explicit opt-in until its acceptance gates pass.
- Reuse existing provider fetchers, authentication, job workers, token lifecycle wrappers, browser adapters, and test runners. Do not create a parallel financial-data implementation.
- Preserve declared runtime ranges: base OpenBB and FMP Cached currently require Python `>=3.10,<3.14`. Validate this launcher on Python 3.13 and the existing Portfolio environment on Python 3.12; do not silently change package Python support.
- Core/MCP source and compatible dependencies must be pinned or otherwise reproducibly resolved; do not infer installed source provenance from a version number alone.
- Never store credentials, tokens, real account identifiers, personal records, or machine-specific absolute paths in plans, issues, fixtures, logs, or committed artifacts.
- Provider reads may perform cache writes and consume paid quota. Treat that separately from portfolio mutations and describe it truthfully.
- Missing credentials, unavailable browser sessions, missing packages, and denied operations produce explicit errors or unavailable capability states, not fabricated successful results.
- Test offline first. Paid-provider calls, personal-data calls, cache maintenance, and real-browser mutation suites require their own explicit execution gates.

---

## 1. Approval boundary and deliverables

**Tracking update:** the user subsequently authorized Project #4 creation.
The program is now [#2123 (Portfolio MCP capability parity)](https://github.com/prajoria/OpenBB/issues/2123):
72 new issues plus reused [#386 (Daytrade MCP tool server)](https://github.com/prajoria/OpenBB/issues/386).
See the [complete issue map](../../cross_repo_workflow/project-issue-map.md)
for actual hierarchy, metadata and dependency read-back. The follow-on
[#2195 (Python Notebook MCP Companion)](https://github.com/prajoria/OpenBB/issues/2195)
is blocked by [#2194 (T44 base MCP release)](https://github.com/prajoria/OpenBB/issues/2194).
All implementation work remains planned; the original plan-only boundary below
is retained as approval history, not a statement that issues are still absent.

### Original plan-only delivery

1. Defines the proposed program, epics, features, tasks, dependency graph, and milestones.
2. Maps every finding in the [MCP coverage report](../../cross_repo_workflow/mcp-coverage-report.md) to an owned work package.
3. Specifies testable outcomes and the later Project #4 issue-creation procedure.
4. Identifies existing work for reuse before new issues are created.

### Original plan-only boundary

- No GitHub issues or labels are being created.
- No project status, assignee, parent relationship, or view is being modified.
- No implementation task is claimed or started.
- No existing MCP server, backend, package installation, cache, or database is changed.
- No commit, push, or PR is made.

**Approval gates:**

- **A1 - Plan approval:** approve the scope, architectural decisions, proposed hierarchy, and access policy.
- **A2 - Tracking approval:** authorize creation of the reviewed issue set and its placement on Project #4. Re-run deduplication before creation.
- **A3 - Implementation approval:** claim and execute dependency-ready tasks through fork-internal PRs.
- **A4 - Operational approval:** separately authorize installations/restarts and any live data or maintenance validation.

The original issue counts below were a proposed maximum before deduplication.
Tracking approval A2 was subsequently granted by the notebook-agent request.
The companion notebook-agent program is sequenced after T44; issue creation
does not satisfy A3/A4 or mean that MCP coverage gaps have been closed.

## 2. Starting evidence and measurable targets

### Baseline

| Surface | Verified baseline | What the number does not prove |
| --- | ---: | --- |
| In-process richer Platform profile | 226 API tools; 10 initial helpers; 236 after activation | Default isolated launcher coverage or successful financial execution |
| Installed core OpenAPI | 229 operations, including three intentionally excluded coverage routes | All custom application APIs |
| FMP Cached provider registrations | 181: 123 dedicated implementations and 58 non-persistent fallbacks | 181 reachable commands or 181 persistent implementations |
| FMP model registrations with command/MCP route | 70; 111 without a registered command | Subscription entitlement or cache hit behavior |
| Custom Portfolio app | 19 additional schema-visible operations | Safe default exposure of personal data |
| Intelligence widget app | 69 operations, including manifests/root | One distinct financial capability per widget/route |
| Workspace MCP | 18 tools, 16 resources, one template, two prompts, live metadata verified | Active browser bridge or successful mutating commands |
| Agents MCP | Two registered tools | Five implemented agents |
| Daytrade MCP | Six declarations; no wire handler registration | Six callable tools |
| Recent Portfolio history | 948 commits, 857 non-merge commits, through the audited SHA | Every commit introduces a distinct capability |

Inputs:

- [HTTP operation inventory](../../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/mcp-api-inventory.csv)
- [FMP registration inventory](../../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/mcp-fmp-model-coverage.csv)
- [Catalog snapshot](../../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/mcp-catalog-snapshot.json)
- [Recent commit ledger](../../../openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/portfolio-recent-commits.csv)

### Program-level acceptance criteria

| ID | Required outcome |
| --- | --- |
| AC-01 | A clean, documented Portfolio profile reproduces its dependency set, source origins, category inventory, and MCP catalog without relying on a developer's pre-populated venv. |
| AC-02 | Every audited and newly discovered capability has an owner, source, exposure disposition, access class, credential requirements, and test evidence. No unclassified rows remain. |
| AC-03 | All 181 FMP registrations are accounted for. Every model approved for public use has a typed command, discoverable tool, validated provider schema, and offline invocation evidence. Preserve the existing 70 mappings. |
| AC-04 | The 111 current routing gaps are closed or individually approved as exclusions with reasons. An exclusion remains visible in gross coverage; it cannot silently reduce the denominator. |
| AC-05 | All 58 fallback registrations are visibly marked non-persistent unless converted and verified. No blanket assertion of cache hits, offline operation, or unlimited quota remains. |
| AC-06 | All 19 custom Portfolio and 69 Intelligence operations have reviewed direct, indirect, metadata-only, or restricted dispositions. Every approved direct adapter has contract and authorization tests. |
| AC-07 | Every prompt and client profile references only capabilities available to that profile; required unavailable dependencies are actionable. |
| AC-08 | Workspace's 18-tool surface retains authenticated user isolation and browser requirements; metadata, live read parity, and scoped UI mutation tests are reported separately. |
| AC-09 | Daytrade's six approved observation tools are callable over a real stdio MCP session; submit/broker operations remain unreachable. |
| AC-10 | Agents documentation, registered tools, and callable agent entry points agree. New agent products are not implied by a two-tool registry. |
| AC-11 | Cache observability is read-only; maintenance is a separate explicitly enabled/authenticated profile backed by the existing job service. |
| AC-12 | CI detects route/model/prompt/catalog drift against the Portfolio PR base, and releases include provenance, rollback instructions, and a current coverage report. |

Publish these separate metrics, never one inflated "MCP coverage" percentage:

```text
gross_model_reachability = reachable_FMP_models / registered_FMP_models
approved_model_reachability = reachable_approved_models / approved_public_models
persistence_coverage = verified_persistent_models / registered_FMP_models
api_disposition_coverage = classified_operations / inventoried_operations
api_invocation_coverage = tested_approved_operations / approved_direct_operations
prompt_dependency_coverage = satisfied_required_references / required_references
```

Counts are frozen as audit evidence, not permanent architecture limits. New capabilities grow the live denominator and require an explicit baseline update.

## 3. Architectural decisions proposed for approval

### D1. Reproducible named profiles, not "install everything"

Keep the existing launcher behavior as `platform-standard`. Add explicit profiles:

| Profile | Purpose | Default allowed effects |
| --- | --- | --- |
| `platform-standard` | Existing behavior and migration compatibility | Existing API semantics, clearly documented |
| `portfolio-read` | Approved core, Portfolio, Intelligence, FMP, and analytics capabilities | Market-data/cache-populating reads; separately classified private portfolio reads; no financial mutations |
| `portfolio-ops` | Operator-only cache/job maintenance | Only named, authenticated maintenance operations after explicit configuration |
| Workspace integrated | Existing authenticated port-8000 MCP | Existing user/browser-scoped Workspace capabilities |
| Agents stdio | Sanitized portfolio tools | Existing reviewed data access only |
| Daytrade stdio | Curated observation tools | No plan submission, broker access, or report-writing operations |

FinancialToolkit, Agents, and Daytrade remain declared optional capabilities. Their absence must disable dependent prompts and report the missing package; it must not prevent a read profile from loading unrelated approved tools.

### D2. One inventory and policy contract; separate execution adapters

Proposed new implementation files, **not created by this plan**:

| Path relative to repository root | Responsibility |
| --- | --- |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/models/capability.py` | Typed capability, disposition, dependency, and verification records |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/service/capability_inventory.py` | Metadata-only join of provider registrations, commands, API operations, MCP components, and provenance |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/service/exposure_policy.py` | Profile-specific admission and invocation policy; default-deny for newly composed surfaces |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/service/runtime_profiles.py` | Validated package/app/profile configuration and source provenance |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/adapters/portfolio.py` | Approved custom Portfolio application bridge |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/adapters/portfolio_intel.py` | Approved Intelligence application bridge |
| `openbb_platform/extensions/mcp_server/openbb_mcp_server/adapters/cache_admin.py` | Typed cache observability and allowlisted operator-job adapters |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/fmp_cached_router.py` | Provider-owned public route assembly for model keys lacking canonical routes |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/routers/` | Reviewed domain adapters; never a user-supplied arbitrary fetcher dispatch endpoint |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/assets/model_routes.json` | Reviewed model-to-command mappings and persistence descriptors |
| `scripts/audit_mcp_capabilities.py` | Stable metadata-only audit CLI producing sanitized JSON/CSV |
| `scripts/test_portfolio_mcp.ps1` | Bounded profile/transport acceptance wrapper using existing lifecycle helpers |
| `.github/workflows/portfolio-mcp-coverage.yml` | Offline contract and drift gates, with separately gated operational validation |

Reuse existing `MCPSettings`, route `mcp_config`, `CategoryIndex`, OpenBB `Router`,
`CommandMap`, `ProviderInterface`, fetchers, and FastMCP facilities. Do not
duplicate route-name normalization or authentication in every adapter.

Proposed capability record, shown as a concrete contract example:

```json
{
  "schema_version": 1,
  "id": "fmp_cached:model:StockList",
  "surface": "platform",
  "owner_lane": "A-Data",
  "source_refs": ["openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/symbol_lists.py"],
  "source_model": "StockList",
  "operation": {"method": "GET", "path": "/api/v1/fmp_cached/reference/stock_list"},
  "tool_name": "fmp_cached_reference_stock_list",
  "disposition": "direct",
  "access_class": "provider_read",
  "persistence": "dedicated",
  "requirements": ["package:openbb-fmp-cached", "credential:fmp_cached"],
  "verification": {"schema": true, "offline_call": false, "live_call": false}
}
```

`offline_call=false` is incomplete verification, not a reason to conceal the
capability. Credential requirements are identifiers only, never values.

Disposition enum: `direct`, `workspace_indirect`, `metadata_only`,
`restricted`, `unimplemented`. Access classes: `public_metadata`,
`provider_read`, `private_portfolio_read`, `filesystem_write`,
`cache_maintenance`, `job_control`, `workspace_mutation`,
`financial_mutation`. Persistence: `dedicated`, `ttl`, `fallback_none`,
`not_applicable`, `unverified`. A dedicated class name is not automatically
live persistence evidence.

### D3. Preserve canonical financial tools; add provider-owned routes only for gaps

Retain the 70 existing model mappings and their tool names. For genuinely
unrouted model keys, use a provider-owned namespace such as
`/api/v1/fmp_cached/reference/stock_list`, with domain routers beneath it.

This reuses the existing dual provider/core entry-point pattern in
[the IMF provider manifest](../../../openbb_platform/providers/imf/pyproject.toml).
The proposed FMP Cached registration is:

```toml
[tool.poetry.plugins."openbb_core_extension"]
fmp_cached = "openbb_fmp_cached.fmp_cached_router:router"
```

T11 must prove the current Router/registry supports custom model keys before
the batches land. Reuse the query, result, normalization, credential, and
validation contracts already attached to each fetcher. Do not rename a model
or substitute a loosely typed `query(model, params)` MCP tool merely to
increase the count.

### D4. Compose applications without bypassing their original boundaries

Keep core tool names stable. The Portfolio and Intelligence adapters use
explicitly reviewed source applications and allowlists, preserving their
validation and authentication. They must not copy financial formulas.

Use in-process ASGI adaptation for packaged apps where original middleware
and dependencies can be preserved. If the independently managed widget
service is used instead, use a configured fixed service origin and the
same route allowlist; arbitrary caller-provided destinations are forbidden.
T21 validates the ASGI composition seam; T24 validates the independently
served application contract. Do not mount an entire app and assume its
nested OpenAPI or authorization automatically propagates.

One inventory resource can describe all four MCP surfaces without claiming
they share sessions or execution semantics. A "single view" is a catalog
and client configuration, not a single unconstrained dispatch function.

### D5. Honest completion scope

Mandatory scope is parity for **implemented capabilities**, truthful
documentation, and reviewed controls. Completing the four additional Agents
products advertised but absent in source is a separate product expansion,
not silently included as four trivial MCP wrapper tasks.

Likewise, implementing persistent storage for all 58 fallback fetchers is not
implied by routing them. This program classifies and exposes those semantics,
tests existing persistent implementations, and produces an explicit
conversion backlog for any separately approved persistence expansion.
A persistence claim requires cache-hit/miss/freshness/invalidation evidence.

## 4. Proposed Project #4 hierarchy and metadata

### Verified board configuration

Read-only inspection confirmed:

- Project ID: `PVT_kwHOAOc7384BdSTg`.
- View 2 is **Board**, `BOARD_LAYOUT`, with an empty filter.
- Status options: **Todo**, **In Progress**, **Done**.
- Type options: **Epic**, **Feature**, **Task**, **Bug**.
- Phase options: **M0**, **P0**, **P1**, **P2**, **P3**, **M4**.
- Lane options: **A-Data**, **B-Analytics**, **C-App+Paper**,
  **D-Widgets+QA**, **PM**, **QA**.
- Parent issue and Sub-issues progress fields already exist.

Reuse these fields. There is no need to create a new board or invent a
`Blocked` status. Pending dependencies remain Todo with explicit blocking links.
Leave Start/End unset until ownership and scheduling are approved.

Set the program epic to Type Epic, Phase M0, Lane PM and priority P0.
Delivery epics use their table's primary lane and the first phase in their
phase range. Features use the earliest child-task phase, highest child-task
priority, and shared child-task lane; if lanes differ, use the parent epic's
primary lane. Tasks use their explicit card metadata. These are single-select
field values, not literal phase-range strings.

Use existing labels `type:epic`, `type:feature`, `type:task`, `area:mcp`,
`area:fmp_cached`, `area:providers`, `area:portfolio-intel`, `area:workspace`,
`area:techtrade`, `area:backtest`, `area:fmp_trading`, and `priority:P0/P1/P2`
as applicable. Propose one new label, `program:mcp-capability-parity`, only
at A2. Project Phase is authoritative; do not repurpose unrelated
TechTrade-specific phase-label descriptions.

### Existing work to reuse, not duplicate

| Existing issue | Observed state | Planned treatment |
| --- | --- | --- |
| [#386 - Daytrade MCP tool server](https://github.com/prajoria/OpenBB/issues/386) | Open; no Project items; no structured parent; body refers to the Daytrade phase/epic | Reuse for T31. Add to Project #4 after approval; cross-link F6.1. Do not silently reparent or duplicate it. |
| [#360 - Daytrade agent turns and MCP phase](https://github.com/prajoria/OpenBB/issues/360) | Open | Keep as domain coordination context for T31/T32. |
| [#356 - FMP Trading program epic](https://github.com/prajoria/OpenBB/issues/356) | Open | Preserve its program ownership and link cross-program dependencies. |
| [#491 - Portfolio Intelligence Engine epic](https://github.com/prajoria/OpenBB/issues/491) | Closed | Link as predecessor/context; do not reopen a completed program to hide new scope. |
| [#116 - Pine MCP registration](https://github.com/prajoria/OpenBB/issues/116) | Open, in-progress label | Track as adjacent work. Do not absorb or duplicate it without a source/capability overlap review. |

Search again at A2: other agents may create overlapping issues between plan
approval and issue creation. Existing closed implementation issues can be
referenced as provenance without being reopened.

### Program structure

**Proposed program epic:** `[mcp-parity] Portfolio capability coverage and trusted MCP delivery`.

| Epic | Title | Priority | Phase range | Primary lane |
| --- | --- | --- | --- | --- |
| E1 | Capability inventory and exposure policy | P0 | M0-P0 | D-Widgets+QA |
| E2 | Reproducible Portfolio runtime profiles | P0 | P0-P1 | C-App+Paper |
| E3 | FMP Cached model-to-command parity | P0 | P1-P2 | A-Data |
| E4 | Portfolio and Intelligence application parity | P0 | P1-P2 | B-Analytics |
| E5 | Cache observability and controlled operations | P1 | P2-P3 | A-Data |
| E6 | Specialist MCP correctness | P1 | P1-P3 | B-Analytics |
| E7 | Truthful prompts, client configuration, and unified discovery | P1 | P2-P3 | D-Widgets+QA |
| E8 | CI, live acceptance, and release rollout | P0 | P0-M4 | QA |

Proposed hierarchy: **1 program epic + 8 delivery epics + 20 features +
44 tasks = 73 logical work items**. T31 reuses an existing issue, so the
maximum is **72 new issues plus one reused issue**, before further deduplication.
The logical dependency to T31 is cross-linked rather than forcing a new parent.

### Features and tasks

| Feature | Parent | Outcome | Tasks |
| --- | --- | --- | --- |
| F1.1 | E1 | Versioned source/API/MCP inventory | T01, T02 |
| F1.2 | E1 | Reviewed exposure and invocation policy | T03, T04 |
| F1.3 | E1 | Portfolio lineage and recent-work traceability | T05, T06 |
| F2.1 | E2 | Deterministic package and profile resolution | T07, T08 |
| F2.2 | E2 | Profile-aware launcher and readiness | T09, T10 |
| F3.1 | E3 | Typed provider route framework and complete regression gate | T11, T20 |
| F3.2 | E3 | Reference, search, price and intraday coverage | T12, T13, T14, T15 |
| F3.3 | E3 | Analyst, sector and statement coverage | T16, T17 |
| F3.4 | E3 | Corporate, government, news and COT coverage | T18, T19 |
| F4.1 | E4 | Reviewed custom Portfolio API adapter | T21, T22 |
| F4.2 | E4 | Reviewed Intelligence and Trading Desk adapter | T23, T24 |
| F4.3 | E4 | Analytics optional-package contract | T25, T26 |
| F5.1 | E5 | Cache observability and truthful persistence | T27, T28 |
| F5.2 | E5 | Authenticated job-backed maintenance | T29, T30 |
| F6.1 | E6 | Callable read-only Daytrade MCP | T31, T32 |
| F6.2 | E6 | Accurate and verified Agents MCP | T33, T34 |
| F7.1 | E7 | Prompt and skills dependency integrity | T35, T36 |
| F7.2 | E7 | Unified catalog and client/operator guidance | T37, T38 |
| F8.1 | E8 | Offline protocol and Portfolio drift gates | T39, T40, T41 |
| F8.2 | E8 | Live acceptance and staged release | T42, T43, T44 |

## 5. Execution mechanics and shared test contracts

### Standard task cycle

Every task below is a separately reviewable deliverable, not merely an
unchecked line in an epic. Before executing it, expand its named acceptance
cases into the specified test file and follow this cycle:

- [ ] Claim its approved GitHub issue, set Project Status to In Progress,
  and begin the repository heartbeat protocol.
- [ ] Add the listed failing test cases using synthetic fixtures.
- [ ] Run that exact test file/selector and record the expected failure.
- [ ] Make only the specified changes, preserving adjacent contracts.
- [ ] Re-run the focused tests and required protocol/CLI harness.
- [ ] Review the diff, sanitize evidence, and update the relevant docs.
- [ ] Commit only the task's intended paths once authorized; include the
  required co-author trailer and reference the issue with its title.
- [ ] Open a fork-internal PR into `portfolio` with valid `Closes` syntax.
  Mark work Done only after merge and acceptance verification.

Use the existing selected interpreter. From the parent repository:

```powershell
$Python = '.\.venv_portfolio\Scripts\python.exe'
& $Python -m pytest openbb_platform\extensions\mcp_server\tests\models\test_capability.py -q
```

That is T01's concrete command. Each task card supplies its own validation
command. Group related files using the same runner into one invocation. For Pester:

```powershell
Invoke-Pester -Path .\scripts\tests\Start-DualMcp.Tests.ps1 -Output Detailed
```

That Pester file is a proposed new regression file under the existing
runner. Do not install a new testing framework. For code inside Workspace,
use its existing project environment and pytest configuration, not an
accidentally incompatible parent venv.

### Exact cross-task interfaces

T01 owns these types and field names; downstream tasks must not invent
alternate spellings:

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict

class OperationKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str

class VerificationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema: bool = False
    offline_call: bool = False
    live_call: bool = False

class CapabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    id: str
    surface: Literal["platform", "workspace", "agents", "daytrade"]
    owner_lane: Literal["A-Data", "B-Analytics", "C-App+Paper",
                        "D-Widgets+QA", "PM", "QA"]
    source_refs: list[str]
    decision_ref: str | None = None
    exclusion_reason: str | None = None
    source_model: str | None = None
    operation: OperationKey | None = None
    tool_name: str | None = None
    disposition: Literal["direct", "workspace_indirect", "metadata_only",
                         "restricted", "unimplemented"]
    access_class: Literal["public_metadata", "provider_read",
                         "private_portfolio_read", "filesystem_write",
                         "cache_maintenance", "job_control",
                         "workspace_mutation", "financial_mutation"]
    persistence: Literal["dedicated", "ttl", "fallback_none",
                         "not_applicable", "unverified"]
    requirements: list[str]
    verification: VerificationState
```

These are proposed design contracts, not code installed by this planning
task. T01 adds semantic validation: nonempty stable IDs, normalized methods,
absolute API paths, unique records, and no direct disposition without a
tool/operation or explicitly registered specialist tool.

**Policy interface owned by T03/T04:**
`evaluate_exposure(record: CapabilityRecord, profile_name: str) -> bool`.
It is admission logic, not authentication. Invocation must additionally
preserve the original principal/authorization checks.

**Inventory interface owned by T02:**
`collect_capabilities(profile_name: str) -> list[CapabilityRecord]`.
It must not execute a provider fetcher, connect to a personal database, or
read secrets merely to enumerate capabilities.

**Profile interface owned by T07/T08:**
profile name resolves to declared package requirements, app adapters,
admitted access classes, optional components, and expected capability IDs.
Credentials are resolved at runtime outside this public structure.

**FMP route manifest interface owned by T11:**
each row has `model`, `route`, `domain`, `canonical_existing`,
`persistence`, and `batch`. Every model key is unique; provider-controlled
arguments cannot be changed into an arbitrary model/module import by clients.

**Acceptance wrapper interface owned by T10, extended by T41-T43:**
`scripts/test_portfolio_mcp.ps1` takes `-Profile` and `-Mode`. Supported
modes are `metadata`, `protocol`, `workspace-read`, `workspace-mutation`,
`operator-fixture`, and `provider-live`. It reuses ignored local connection
configuration and the existing Workspace token wrapper.
`workspace-mutation` additionally requires `-AllowWorkspaceMutation`;
`operator-fixture` requires `-AllowMaintenance` and a verified disposable
fixture environment; `provider-live` requires `-AllowPaidRequests` and
`-MaxProviderRequests` greater than zero. The default request budget is zero.
No mode can silently fall back from a disposable environment to a personal
database or dashboard. Early T10 supports metadata/protocol and rejects
not-yet-implemented modes explicitly; the later owners add their modes.

Example protocol acceptance test structure for a real in-process client:

```python
import pytest
from fastmcp import Client
from fastapi import FastAPI
from openbb_mcp_server.app.app import create_mcp_server
from openbb_mcp_server.models.settings import MCPSettings

@pytest.mark.asyncio
async def test_activation_preserves_sessions():
    app = FastAPI()

    @app.get("/api/v1/audit/ping")
    def ping():
        return {"ok": True}

    server = create_mcp_server(MCPSettings(enable_tool_discovery=True), app)
    async with Client(server) as first, Client(server) as second:
        await first.call_tool("activate_tools", {"tool_names": ["audit_ping"]})
        assert "audit_ping" in {tool.name for tool in await first.list_tools()}
        assert "audit_ping" not in {tool.name for tool in await second.list_tools()}
        result = await first.call_tool("audit_ping", {})
        assert not result.is_error
```

T39 extends this concrete test with pagination, denied invocation, resources,
prompts, and malformed inputs. Mocking only decorator registration is not
the protocol acceptance gate.

## 6. E1 - Capability inventory and exposure policy

**Epic exit:** the source/API/MCP denominator is reproducible and policy
decisions are machine-readable, reviewed, and enforced without changing
ordinary REST behavior.

### T01 - Define capability contracts and immutable audit fixtures

**Feature:** F1.1. **Priority/phase/lane:** P0 / M0 / D-Widgets+QA.
**Dependencies:** none. **Estimate:** 1-2 engineer-days.

**Files:** create `openbb_platform/extensions/mcp_server/openbb_mcp_server/models/capability.py`;
create `openbb_platform/extensions/mcp_server/tests/models/test_capability.py`;
use the four existing audit artifacts linked above as immutable inputs.

- [ ] Add the exact shared models and a synthetic fixture for each disposition/access class.
- [ ] Test unknown fields, duplicate IDs, absent direct-tool identity, and credential-shaped values.
- [ ] Preserve gross and approved denominators independently; distinguish aliases from unique implementations.
- [ ] Validate round-trip JSON without dropping false verification flags.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\models\test_capability.py -q`.
**Acceptance:** invalid records fail validation; original counts remain traceable; no fixture contains private data.

### T02 - Build the metadata-only inventory CLI

**Feature:** F1.1. **Priority/phase/lane:** P0 / M0 / D-Widgets+QA.
**Dependencies:** T01. **Estimate:** 2-3 days.

**Files:** create `service/capability_inventory.py` under the MCP package;
create `scripts/audit_mcp_capabilities.py`;
create `openbb_platform/extensions/mcp_server/tests/service/test_capability_inventory.py`.

- [ ] Join fetcher keys, `CommandMap`, route/method identity, effective tool names, prompts, and profile metadata.
- [ ] Record source SHAs, submodule SHAs, distribution versions, import origins, interpreter, and explicit configuration fingerprint without secrets.
- [ ] Test missing optional packages, method/path collisions, duplicate names, aliases, and unavailable runtime services.
- [ ] Add `--profile`, `--output-dir`, and `--metadata-only`; produce stable-order JSON and CSV.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_capability_inventory.py -q`.
**Harness:** `& $Python scripts\audit_mcp_capabilities.py --profile portfolio-read --metadata-only --output-dir .dev-cycle\mcp-audit`.
**Acceptance:** no business function executes; repeated identical inputs produce identical normalized inventories; missing prerequisites are explicit.

### T03 - Classify every capability and publish profile policy

**Feature:** F1.2. **Priority/phase/lane:** P0 / P0 / D-Widgets+QA.
**Dependencies:** T02. **Estimate:** 2-3 days.

**Files:** create `openbb_platform/extensions/mcp_server/openbb_mcp_server/assets/capability_policy.json`;
create `service/exposure_policy.py` and
`openbb_platform/extensions/mcp_server/tests/service/test_exposure_policy.py`.

- [ ] Classify all 317 audited operation rows and all provider/specialist rows without equating HTTP method with side effects.
- [ ] Treat manifests as metadata, cache-populating reads as provider reads, private basket data as private reads, and writes as their actual privilege class.
- [ ] Require documented reasons for restricted/unimplemented entries and retain them in the gross inventory.
- [ ] Test that an unknown route is denied in the new profile and that opt-in operator entries cannot leak into `portfolio-read`.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_exposure_policy.py -q`.
**Acceptance:** zero unclassified rows; execution/broker endpoints denied by default; policy decisions independently reviewable.

### T04 - Enforce policy at discovery and invocation

**Feature:** F1.2. **Priority/phase/lane:** P0 / P0 / D-Widgets+QA.
**Dependencies:** T03. **Estimate:** 2-3 days.

**Files:** modify MCP `utils/fastapi.py`, `app/app.py`, `models/settings.py`;
extend `tests/utils/test_fastapi.py`;
create `tests/app/test_exposure_enforcement.py` under the MCP extension.

- [ ] Reuse current route exposure metadata while making new-profile policy authoritative.
- [ ] Avoid mutating the original REST application's route collection during MCP filtering; operate on an isolated composition.
- [ ] Reject denied names on direct `tools/call`, not merely hide them from discovery.
- [ ] Test policy-denied GET writes, approved analytical POSTs, session activation, and REST route preservation.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\utils\test_fastapi.py openbb_platform\extensions\mcp_server\tests\app\test_exposure_enforcement.py -q`.
**Acceptance:** activation cannot elevate privileges; existing standard-profile behavior remains compatible.

### T05 - Automate Portfolio lineage and baseline comparison

**Feature:** F1.3. **Priority/phase/lane:** P0 / M0 / PM.
**Dependencies:** T02. **Estimate:** 1 day.

**Files:** extend `scripts/audit_mcp_capabilities.py`;
create `openbb_platform/extensions/mcp_server/tests/service/test_audit_lineage.py`;
update `docs/cross_repo_workflow/mcp-coverage-report.md`.

- [ ] Record current HEAD, explicit comparison SHA, ahead/behind state, and submodule pins.
- [ ] In CI, use the PR base SHA rather than an assumed local `origin/portfolio`.
- [ ] Test missing refs, shallow history, non-Portfolio PR bases, and a stale local branch.
- [ ] Emit a failure/warning category without fetching or moving branches implicitly.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_audit_lineage.py -q`.
**Acceptance:** lineage evidence is reproducible and independent from branch tracking configuration.

### T06 - Map recent work and exceptions to accountable capabilities

**Feature:** F1.3. **Priority/phase/lane:** P0 / P0 / PM.
**Dependencies:** T03, T05. **Estimate:** 1-2 days.

**Files:** extend `assets/capability_policy.json`;
create `docs/cross_repo_workflow/mcp-capability-decisions.md`;
extend `tests/service/test_capability_inventory.py`.

- [ ] Map FMP endpoint waves, Intelligence live widgets, snapshots, jobs, execution controls, and specialist adapters to capability IDs.
- [ ] Require owner issue, rationale, source evidence, and review trigger for every exclusion.
- [ ] Separate absent product implementations from broken adapters around implemented code.
- [ ] Test that a newly registered model or API route cannot disappear behind a stale fixed denominator.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_capability_inventory.py -q`.
**Acceptance:** every audit recommendation and recent-work family maps to a task or approved exclusion; no "implemented" status derives only from a commit subject.

## 7. E2 - Reproducible Portfolio runtime profiles

**Epic exit:** an isolated profile can start with known provenance, effective
catalog assertions, and owned-process lifecycle behavior.

### T07 - Define the install/profile manifests

**Feature:** F2.1. **Priority/phase/lane:** P0 / P0 / C-App+Paper.
**Dependencies:** T03. **Estimate:** 1-2 days.

**Files:** create `service/runtime_profiles.py`;
modify MCP `models/settings.py`, `assets/profiles/portfolio.json`;
create `tests/service/test_runtime_profiles.py` under the MCP extension.

- [ ] Define `platform-standard`, `portfolio-read`, and `portfolio-ops` with explicit core/fork requirements.
- [ ] Treat `.venv_portfolio` and isolated `uv` environments as different installations.
- [ ] Make custom-app composition, optional analytical packages, and operator access separately selectable.
- [ ] Test unknown profiles, conflicting config, missing required components, and no implicit maintenance enablement.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_runtime_profiles.py -q`.
**Acceptance:** profile JSON validates and yields an explicit dependency/app/policy manifest.

### T08 - Establish clean-install and import-provenance checks

**Feature:** F2.1. **Priority/phase/lane:** P0 / P0 / C-App+Paper.
**Dependencies:** T07. **Estimate:** 2-3 days.

**Files:** modify `scripts/start-dual-mcp.ps1`, `openbb_platform/pyproject.toml`
only where package metadata requires it; create `scripts/tests/Start-DualMcp.Tests.ps1`;
extend `tests/service/test_runtime_profiles.py`.

- [ ] Resolve selected editable/local distributions consistently; pin tested external dependencies without broad unbounded upgrades.
- [ ] Detect an optional package imported from an unintended sibling worktree or an outdated installed copy.
- [ ] Test an empty environment, missing optional package, mismatched source origin, and compatible Python 3.12/3.13 profiles.
- [ ] Record a replayable resolution artifact using the repository's existing packaging workflow.

**Run:** `Invoke-Pester -Path .\scripts\tests\Start-DualMcp.Tests.ps1 -Output Detailed`;
`& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_runtime_profiles.py -q`.
**Acceptance:** startup does not silently mix source checkouts; no install occurs during metadata-only inventory; reproducibility is demonstrated from a fresh profile environment.

### T09 - Add explicit launcher profile selection and safe lifecycle behavior

**Feature:** F2.2. **Priority/phase/lane:** P0 / P1 / C-App+Paper.
**Dependencies:** T04, T08. **Estimate:** 2-3 days.

**Files:** modify `scripts/start-dual-mcp.ps1`, `.mcp.json.example`;
extend `scripts/tests/Start-DualMcp.Tests.ps1`;
update the launcher's README section.

- [ ] Add a validated `-Profile` parameter, keeping the compatibility default unchanged.
- [ ] Launch the profile's registered app factory and dependencies rather than infer capabilities from installed names.
- [ ] Retain exact PID/start-time ownership, port conflict checks, timeout cleanup, and external runtime state.
- [ ] Test partial startup, unrelated listeners, stale state files, paths containing spaces, and restart cleanup.

**Run:** `Invoke-Pester -Path .\scripts\tests\Start-DualMcp.Tests.ps1 -Output Detailed`.
**Acceptance:** failure is explicit, owned processes are cleaned, and no unrelated backend or browser is stopped.

### T10 - Make readiness assert the effective capability contract

**Feature:** F2.2. **Priority/phase/lane:** P0 / P1 / C-App+Paper.
**Dependencies:** T02, T09. **Estimate:** 1-2 days.

**Files:** extend `scripts/start-dual-mcp.ps1`;
create `scripts/test_portfolio_mcp.ps1` and
`scripts/tests/Test-PortfolioMcp.Tests.ps1`.

- [ ] Replace the one-equity-category proxy with profile-required category, provider, adapter, auth, and prompt checks.
- [ ] Follow MCP initialization, pagination, discovery and activation without invoking paid financial tools.
- [ ] Fail readiness for missing FMP provider choices or required custom adapters even if an equity category exists.
- [ ] Test diagnostic redaction and close the readiness MCP session on success or failure.

**Run:** `Invoke-Pester -Path .\scripts\tests\Test-PortfolioMcp.Tests.ps1 -Output Detailed`.
**Acceptance:** readiness distinguishes missing package, missing route, denied capability, and unavailable transport.

## 8. E3 - FMP Cached model-to-command parity

**Epic exit:** all public model registrations have typed OpenBB and MCP
routes, the original 70 mappings are preserved, and every exception remains
visible. Model implementations are reused rather than rewritten.

### Exact ownership of the current 111 gaps

The table partitions all current unrouted models once, by source module,
not by ambiguous title keywords. `base_cached` here has four registrations:
one TTL-backed market-hours registration and three non-persistent fallbacks.

| Task | Source model module groups | Gap count |
| --- | --- | ---: |
| T12 | `available_directories`, `market_directories`, `reference_directories`, `symbol_lists` | 18 |
| T13 | `historical_directories`, `search_endpoints` | 11 |
| T14 | `stock_quotes` | 11 |
| T15 | `aftermarket_quote`, `base_cached`, `equity_intraday_historical`, `single_param_endpoints` | 9 |
| T16 | `analyst_ratings`, `analyst_recommendations`, `sector_performance` | 15 |
| T17 | `as_reported_statements`, `statement_extras` | 17 |
| T18 | Corporate/SEC/fundraising subset of `w5_w6_w8_extras`, enumerated below | 17 |
| T19 | Government/news/COT subset of `w5_w6_w8_extras`, enumerated below | 13 |
| **Total** | Complete current unrouted-model set | **111** |

All source modules are under
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/`.
Tasks T11 and T20 own framework/integration, not additional model counts.

### T11 - Introduce typed provider-owned route assembly

**Feature:** F3.1. **Priority/phase/lane:** P0 / P1 / A-Data.
**Dependencies:** T04, T07. **Estimate:** 2-3 days.

**Files:** modify FMP Cached `pyproject.toml`;
create `openbb_fmp_cached/fmp_cached_router.py`,
`openbb_fmp_cached/assets/model_routes.json`,
`tests/test_provider_router_contract.py`, and `tests/test_model_route_manifest.py`
inside the FMP Cached provider.

- [ ] Demonstrate one unrouted model (`StockList`) through the existing Router/provider dispatcher with its real query/result schema.
- [ ] Register the provider-owned core entry point following the IMF precedent.
- [ ] Validate uniqueness, canonical-route preservation, provider binding, aliases, and permitted argument names.
- [ ] Test package discovery/build and real MCP activation/call with a patched fetcher transport returning synthetic rows.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_provider_router_contract.py openbb_platform\providers\fmp_cached\tests\test_model_route_manifest.py -q`.
**Acceptance:** no arbitrary model dispatch parameter; no direct raw SQL; existing 70 tool names and contracts unchanged.

### T12 - Route static directories, lists and references

**Feature:** F3.2. **Priority/phase/lane:** P0 / P1 / A-Data.
**Dependencies:** T11. **Estimate:** 2-3 days.

**Files:** create `openbb_fmp_cached/routers/reference_router.py`;
update `assets/model_routes.json`;
create `tests/test_reference_router.py` in the provider.

- [ ] Bind all 18 registrations owned by T12 to explicit, documented operations.
- [ ] Test no-parameter list calls and each model's real optional filters; reject unknown arguments.
- [ ] Verify `StockList`, `EtfList`, country/exchange/industry/sector lists,
  commodity/crypto/forex/index lists, constituent lists and market-risk references.
- [ ] Assert each manifest row appears in OpenAPI, `CommandMap`, and activated MCP schemas.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_reference_router.py -q`.
**Acceptance:** 18/18 batch registrations are covered or explicitly rejected by an approved exception; empty lists remain valid data, not fabricated success.

### T13 - Route historical reference and identifier search

**Feature:** F3.2. **Priority/phase/lane:** P0 / P1 / A-Data.
**Dependencies:** T11. **Estimate:** 2-3 days.

**Files:** create `routers/search_router.py`, `routers/reference_history_router.py`,
`tests/test_search_router.py`, `tests/test_reference_history_router.py`;
update the provider route manifest.

- [ ] Bind the five historical-directory and six search registrations.
- [ ] Test CIK/CUSIP/ISIN as strings, including leading zeros; reuse existing identifier normalization.
- [ ] Test missing required search text, exchange variants, historical date filters, and empty results.
- [ ] Verify provider errors survive API/MCP conversion without secret-bearing URLs.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_search_router.py openbb_platform\providers\fmp_cached\tests\test_reference_history_router.py -q`.
**Acceptance:** 11 mappings; no lossy numeric coercion or undocumented identifier transformations.

### T14 - Route batch quotes, market cap and stock-price extras

**Feature:** F3.2. **Priority/phase/lane:** P0 / P1 / A-Data.
**Dependencies:** T11. **Estimate:** 2-3 days.

**Files:** create `routers/quote_router.py`, `tests/test_quote_router.py`;
update the provider manifest; reuse `models/stock_quotes.py`.

- [ ] Bind all 11 stock-quote registrations, including exchange market hours.
- [ ] Test single/multiple symbol input exactly as declared by each query model,
  duplicate symbols, empty inputs, numeric fields, and partial upstream responses.
- [ ] Preserve query limits and entitlement errors; do not introduce an unbounded batch interface.
- [ ] Assert existing `EquityQuote` and its canonical tool still dispatch unchanged.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_quote_router.py -q`.
**Acceptance:** 11 new model routes; canonical quote regression remains green.

### T15 - Route intraday, aftermarket, hours and single-parameter extras

**Feature:** F3.2. **Priority/phase/lane:** P0 / P1 / A-Data.
**Dependencies:** T11. **Estimate:** 2-3 days.

**Files:** create `routers/intraday_router.py`, `tests/test_intraday_router.py`;
update the provider manifest; reuse the four module groups assigned above.

- [ ] Bind nine registrations, including `EquityIntradayHistorical`,
  `ExchangeMarketHours`, aftermarket data, company notes, compensation benchmark, and exchange holidays.
- [ ] Test interval/date/session filters, unsupported intervals, timezone-aware boundaries, and empty market sessions.
- [ ] Preserve `fallback_none` for AftermarketTrade, EquityQuoteBatchShort and TechnicalIndicatorIntraday.
- [ ] Test the TTL market-hours descriptor separately from fallback credential translation.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_intraday_router.py -q`.
**Acceptance:** nine routes with correct cache/entitlement semantics; no new trading or order-submission tools.

### T16 - Route analyst and sector/industry families

**Feature:** F3.3. **Priority/phase/lane:** P0 / P2 / A-Data.
**Dependencies:** T11. **Estimate:** 3-4 days.

**Files:** create `routers/analyst_router.py`, `routers/market_performance_router.py`,
`tests/test_analyst_router.py`, `tests/test_market_performance_router.py`;
update the provider manifest.

- [ ] Bind six ratings/grades models, AnalystRecommendations, and eight sector/industry models.
- [ ] Test snapshot versus historical schemas, symbol/date filters, nullable values and response cardinality.
- [ ] Keep canonical AnalystEstimates mapped to `equity.estimates.historical`.
- [ ] Verify all 15 batch entries through protocol discovery and patched-fetcher calls.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_analyst_router.py openbb_platform\providers\fmp_cached\tests\test_market_performance_router.py -q`.
**Acceptance:** no swapped estimate/recommendation endpoints or snapshot/history conflation.

### T17 - Route statement extras, TTM, DCF and as-reported data

**Feature:** F3.3. **Priority/phase/lane:** P0 / P2 / A-Data.
**Dependencies:** T11. **Estimate:** 3-4 days.

**Files:** create `routers/statements_router.py`, `tests/test_statements_router.py`;
update the provider manifest; reuse `models/statement_extras.py` and
`models/as_reported_statements.py`.

- [ ] Bind all 17 registrations without changing existing balance/income/cash/ratios/metrics tools.
- [ ] Test fiscal period, annual/quarterly/TTM distinctions, nullable fields,
  CIK input, and DCF parameter bounds using each existing model.
- [ ] Keep financial-report JSON structured and bounded by the actual endpoint contract.
- [ ] Verify entitlement failures and no unsupported "cached therefore free" fallback.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_statements_router.py -q`.
**Acceptance:** 17 mappings with schema and synthetic execution parity; existing fundamental tools unchanged.

### T18 - Route corporate, SEC and fundraising extras

**Feature:** F3.4. **Priority/phase/lane:** P0 / P2 / A-Data.
**Dependencies:** T11. **Estimate:** 3-4 days.

**Files:** create `routers/corporate_router.py`, `tests/test_corporate_router.py`;
update the provider manifest; reuse `models/w5_w6_w8_extras.py`.

Owned model keys:

```text
AcquisitionOfBeneficialOwnership, AllIndustryClassification,
CrowdfundingOfferings, CrowdfundingOfferingsLatest, CrowdfundingOfferingsSearch,
DelistedCompanies, Fundraising, FundraisingLatest, FundraisingSearch,
IndustryClassificationSearch, IposDisclosure, IposProspectus,
MergersAcquisitionsLatest, MergersAcquisitionsSearch,
SecFilings8K, SecProfile, StandardIndustrialClassificationList
```

- [ ] Bind these 17 keys only; expose no user-supplied arbitrary filing URL fetch.
- [ ] Test identifier strings, paging/search parameters, missing records,
  entitlement errors, and nested-document response serialization.
- [ ] Preserve declared schema fields without injecting summaries presented as source data.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_corporate_router.py -q`.
**Acceptance:** exact batch ownership, no overlap with T19, and typed offline API/MCP round trips.

### T19 - Route government, news and COT extras

**Feature:** F3.4. **Priority/phase/lane:** P0 / P2 / A-Data.
**Dependencies:** T11. **Estimate:** 2-3 days.

**Files:** create `routers/government_news_router.py`,
`tests/test_government_news_router.py`; update the provider manifest.

Owned model keys:

```text
CommitmentOfTradersAnalysis, CommitmentOfTradersReport,
FmpArticles, HouseLatest, NewsCrypto, NewsCryptoLatest,
NewsForex, NewsForexLatest, SenateLatest, SenateNetWorth,
SenateNetWorthAggregated, SenatePositions, SenateProfile
```

- [ ] Bind these 13 keys with their actual filters and pagination contracts.
- [ ] Treat external news/article text as data, never as tool instructions.
- [ ] Test empty pages, malformed query inputs, long content, and missing entitlements.
- [ ] Keep public disclosure data distinct from personal Portfolio records.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_government_news_router.py -q`.
**Acceptance:** exact 13-key batch; no duplicate routes; provider errors and output types preserved.

### T20 - Prove full FMP routing and persistence-descriptor regression

**Feature:** F3.1. **Priority/phase/lane:** P0 / P2 / A-Data.
**Dependencies:** T12, T13, T14, T15, T16, T17, T18, T19.
**Estimate:** 2-3 days.

**Files:** extend existing `tests/test_fetcher_dict_coverage.py`,
`tests/test_two_provider_coverage.py`;
create `tests/test_mcp_model_route_coverage.py` in the FMP provider;
extend the MCP inventory tests.

- [ ] Parametrize over every provider model, not a hand-picked successful subset.
- [ ] Assert each approved model has a typed route, provider binding and callable MCP tool with synthetic transport data.
- [ ] Assert all original 70 command/tool mappings retain compatible schemas.
- [ ] Assert the eight gap batches are disjoint and their union equals the original 111-key set.
- [ ] Report all 58 fallback registrations as non-persistent unless separately converted with evidence.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_fetcher_dict_coverage.py openbb_platform\providers\fmp_cached\tests\test_two_provider_coverage.py openbb_platform\providers\fmp_cached\tests\test_mcp_model_route_coverage.py -q`.
**Acceptance:** AC-03/04/05, with no paid network calls in the contract suite.

## 9. E4 - Portfolio and Intelligence application parity

**Epic exit:** every custom operation has a reviewed disposition and approved
direct operations are callable without changing their financial logic or
authorization.

### T21 - Implement the custom Portfolio composition seam

**Feature:** F4.1. **Priority/phase/lane:** P0 / P1 / B-Analytics.
**Dependencies:** T04, T07. **Estimate:** 2-3 days.

**Files:** create MCP `adapters/portfolio.py`;
modify `app/app.py` only at the app/profile composition seam;
inspect/reuse `openbb_platform/extensions/portfolio/launch.py` and
`openbb_portfolio/portfolio_router.py`;
create `tests/app/test_portfolio_adapter.py` in the MCP extension.

- [ ] Compose approved existing routers without copying data functions or importing the UI viewer into the financial catalog.
- [ ] Preserve dependency injection, response models, exception behavior and authentication.
- [ ] Test that filtering leaves the original Portfolio REST app unchanged.
- [ ] Test route-name collisions and prevent copilot streaming/viewer/manifests from becoming accidental business tools.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_portfolio_adapter.py -q`.
**Acceptance:** composition is deterministic, independently testable, and gated by the new profile.

### T22 - Verify all 19 Portfolio operations and private-data boundaries

**Feature:** F4.1. **Priority/phase/lane:** P0 / P2 / B-Analytics.
**Dependencies:** T21, T06. **Estimate:** 2-3 days.

**Files:** extend MCP `tests/app/test_portfolio_adapter.py`;
create `tests/app/test_portfolio_data_boundaries.py`;
update `assets/capability_policy.json`.

- [ ] Classify and test seven portfolio, one ESPP, one historical, two market, and eight stock-analysis operations.
- [ ] Use synthetic sanitized basket rows; verify rejected/omitted owner and account identifiers.
- [ ] Test missing database configuration as an explicit availability failure, not an empty "healthy" portfolio.
- [ ] Keep private portfolio reads unavailable to unauthenticated/general public clients even when metadata is discoverable.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_portfolio_adapter.py openbb_platform\extensions\mcp_server\tests\app\test_portfolio_data_boundaries.py -q`.
**Acceptance:** all 19 operation dispositions accounted for; every approved direct operation has positive and negative access tests.

### T23 - Map Intelligence, provenance, snapshots and Trading Desk effects

**Feature:** F4.2. **Priority/phase/lane:** P0 / P1 / B-Analytics.
**Dependencies:** T03, T06. **Estimate:** 2 days.

**Files:** update MCP `assets/capability_policy.json`;
inspect/reuse Intelligence `widget_backend/main.py`, `widget_backend/_app.py`,
`widget_backend/widgets.json`, `widget_backend/apps.json`;
create MCP `tests/app/test_intelligence_dispositions.py`.

- [ ] Account for all 69 operations: 48 `/pi`, 18 `/tt`, root and manifests.
- [ ] Separate provider-health/provenance reads, analytic reads, paper state,
  scan triggers, export, execution approval/write/cancel, and metadata.
- [ ] Mark direct versus Workspace-mediated capability relationships without counting two representations twice.
- [ ] Assert new unknown widget routes cannot enter the read profile automatically.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_intelligence_dispositions.py -q`.
**Acceptance:** complete 69-operation review, including state-changing GETs if present; no blanket allow-by-prefix.

### T24 - Add approved Intelligence adapters and contract parity tests

**Feature:** F4.2. **Priority/phase/lane:** P0 / P2 / B-Analytics.
**Dependencies:** T21, T23. **Estimate:** 3-4 days.

**Files:** create MCP `adapters/portfolio_intel.py`,
`tests/app/test_portfolio_intel_adapter.py`;
reuse existing Intelligence widget-backend unit fixtures and route handlers.

- [ ] Bridge approved operations to their original application or fixed configured service, preserving schema and access checks.
- [ ] Test symbol/book context, financials, history, peers, ownership, provenance, provider health and snapshot-backed reads.
- [ ] Ensure aliases do not overwrite existing `portfolio_intel_*` core tools.
- [ ] Test service unavailable, stale schema, upstream auth rejection, invalid parameters, and prohibited destination overrides.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_portfolio_intel_adapter.py -q`.
**Acceptance:** approved operation responses match existing API fixtures; execution controls remain excluded.

### T25 - Lock analytical extension coverage and behavior

**Feature:** F4.3. **Priority/phase/lane:** P0 / P2 / B-Analytics.
**Dependencies:** T08, T04. **Estimate:** 2-3 days.

**Files:** create MCP `tests/app/test_analytics_profiles.py`;
reuse Backtest, TechTrade, Regime and Intelligence core router tests;
update profile policy and expectations.

- [ ] Account for baseline Backtest 10, TechTrade 11, Intelligence core 10,
  and Regime 1 without requiring every operation in the read profile.
- [ ] Classify bundle ingestion, exports, tune/validate, and long-running work separately from read-only results.
- [ ] Test optional module import errors, required numerical dependencies, and source-origin consistency.
- [ ] Preserve deterministic fixtures, cancellation/time limits where supported, and original analytical errors.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_analytics_profiles.py -q`.
**Acceptance:** all 32 baseline analytical routes classified and approved ones callable; absent optional packages are explicit.

### T26 - Reconcile FinancialToolkit router assembly

**Feature:** F4.3. **Priority/phase/lane:** P1 / P2 / B-Analytics.
**Dependencies:** T04, T08. **Estimate:** 2-3 days.

**Files:** modify
`openbb_platform/extensions/financialtoolkit/openbb_financialtoolkit/financialtoolkit_router.py`;
reuse its `ratios/ratios_router.py` and `technicals/technicals_router.py`;
create `openbb_platform/extensions/financialtoolkit/tests/test_router_coverage.py`;
extend MCP `tests/app/test_analytics_profiles.py`.

- [ ] Verify and include the existing ratios/technicals routers where their implemented contracts support registration.
- [ ] Test required dependency absence without breaking unrelated profiles.
- [ ] Validate real tool schemas for the performance/valuation prompt dependencies.
- [ ] Add accurate optional-package installation and availability descriptions.

**Run:** `& $Python -m pytest openbb_platform\extensions\financialtoolkit\tests\test_router_coverage.py -q`.
**Acceptance:** documented implemented subrouters equal actual registered subrouters; no invented toolkit methods.

## 10. E5 - Cache observability and controlled operations

**Epic exit:** agents can inspect truthful cache health; operators can enqueue
only approved maintenance through existing durable jobs.

### T27 - Expose sanitized cache health and coverage

**Feature:** F5.1. **Priority/phase/lane:** P1 / P2 / A-Data.
**Dependencies:** T04, T11. **Estimate:** 2-3 days.

**Files:** create MCP `adapters/cache_admin.py`,
`tests/app/test_cache_observability.py`;
reuse FMP Cached `utils/cache_manager.py`, `utils/database.py`, and
Intelligence provider-health/provenance contracts where applicable.

- [ ] Define bounded health/coverage responses with counts, freshness timestamps, implementation type, and availability.
- [ ] Return no raw rows, account data, SQL text, credentials, or connection strings.
- [ ] Test absent DB, permission failure, empty tables, stale entries, and non-persistent fetchers.
- [ ] Do not call schema creation or refresh helpers to make a health check pass.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_cache_observability.py -q`.
**Acceptance:** read-only health checks have explicit failure states and no hidden writes.

### T28 - Verify persistence semantics and prioritize conversion gaps

**Feature:** F5.1. **Priority/phase/lane:** P1 / P2 / A-Data.
**Dependencies:** T20, T27. **Estimate:** 2-3 days.

**Files:** extend FMP Cached `tests/test_cache_manager.py`,
`tests/test_cache_replace_atomic.py`;
create `tests/test_persistence_contract.py`;
update `docs/cross_repo_workflow/mcp-capability-decisions.md`.

- [ ] Verify cache hit, miss, stale record, failed read/write, and atomic replace behavior using isolated fixtures.
- [ ] Test TTL model semantics independently from dedicated-table storage.
- [ ] Classify each fallback registration explicitly; rank desired persistent conversions by actual consumer demand and entitlement.
- [ ] Keep conversion work as separately approved issues, not fabricated coverage in this program.

**Run:** `& $Python -m pytest openbb_platform\providers\fmp_cached\tests\test_cache_manager.py openbb_platform\providers\fmp_cached\tests\test_cache_replace_atomic.py openbb_platform\providers\fmp_cached\tests\test_persistence_contract.py -q`.
**Acceptance:** every persistence claim has evidence; inability to cache is visible to operators and prompts.

### T29 - Wire operator tools to existing job definitions

**Feature:** F5.2. **Priority/phase/lane:** P1 / P3 / A-Data.
**Dependencies:** T27, T04. **Estimate:** 2-3 days.

**Files:** extend MCP `adapters/cache_admin.py`;
reuse core `api/router/jobs.py`, `api/dependency/jobs.py`, `app/service/job_service.py`,
and `openbb_platform/tools/portfolio_utils/portfolio_utils/jobs.py`;
create MCP `tests/app/test_cache_job_adapter.py`.

- [ ] Expose approved job definitions/status/health and specifically allowlisted enqueue operations only in `portfolio-ops`.
- [ ] Reuse `portfolio.position_history` and `portfolio.etf_holdings` definitions and typed parameters.
- [ ] Require explicit maintenance enablement and original job-service authentication; return durable run IDs.
- [ ] Test idempotency, unknown jobs, invalid params, absent worker, and prohibition of in-request handler execution.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_cache_job_adapter.py openbb_platform\core\tests\api\test_jobs.py -q`.
**Acceptance:** no parallel worker, cron, SQL, or arbitrary script execution facility is introduced.

### T30 - Prove maintenance isolation and recovery

**Feature:** F5.2. **Priority/phase/lane:** P1 / P3 / A-Data.
**Dependencies:** T29. **Estimate:** 2 days.

**Files:** extend MCP `tests/app/test_cache_job_adapter.py`;
extend `openbb_platform/tools/portfolio_utils/tests/test_jobs.py`;
update operator runbook through T38.

- [ ] Test direct-call denial from the read profile and unauthenticated sessions.
- [ ] Preserve existing queued-only cancellation semantics; do not advertise cancellation of already running work.
- [ ] Test duplicate submission, partial failures, bounded warnings, shutdown/restart status, and secret-free persisted parameters.
- [ ] Keep invalidation unavailable until an explicit scoped operation and acceptance policy exists; never expose raw endpoint/table deletion.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_cache_job_adapter.py openbb_platform\tools\portfolio_utils\tests\test_jobs.py -q`.
**Acceptance:** operator actions are auditable and recoverable, and ordinary data discovery cannot initiate maintenance.

## 11. E6 - Specialist MCP correctness

**Epic exit:** specialist declarations match real transport behavior and
documentation, without adding autonomous financial mutation.

### T31 - Complete Daytrade stdio handlers using existing issue #386

**Feature:** F6.1. **Priority/phase/lane:** P1 / P1 / B-Analytics.
**Dependencies:** T03. **Estimate:** 2-3 days.
**Existing tracking:** [#386 - Daytrade MCP tool server](https://github.com/prajoria/OpenBB/issues/386).

**Files:** modify
`openbb_platform/extensions/fmp_trading/openbb_fmp_trading/agent/mcp_server.py`,
`agent/tool_registry.py`;
extend `tests/unit/test_mcp_readonly_surface.py`;
create `tests/unit/test_mcp_dispatch.py`.

- [ ] Register `tools/list` and `tools/call` for the six explicitly approved tools.
- [ ] Wire dispatch to real existing provider/session/journal readers; retain typed schema validation and sanitized errors.
- [ ] Replace name/description-only drift assertions with actual handler/schema contract checks.
- [ ] Test unknown tools, malformed arguments, no dispatch function, and denied `submit_*` names.

**Run:** `& $Python -m pytest openbb_platform\extensions\fmp_trading\tests\unit\test_mcp_readonly_surface.py openbb_platform\extensions\fmp_trading\tests\unit\test_mcp_dispatch.py -q`.
**Acceptance:** six working observation dispatchers; no broker/session mutation references returned.

### T32 - Verify Daytrade over an actual stdio connection

**Feature:** F6.1. **Priority/phase/lane:** P1 / P2 / B-Analytics.
**Dependencies:** T31. **Estimate:** 1-2 days.

**Files:** create
`openbb_platform/extensions/fmp_trading/tests/integration/test_mcp_stdio.py`;
update its CLI/MCP documentation.

- [ ] Start the real CLI in an owned bounded subprocess with synthetic provider/journal fixtures.
- [ ] Perform initialize, list all six tools, invoke each, and terminate cleanly.
- [ ] Test missing agent extra, handler exception, schema mismatch, and direct attempts at submit/order tools.
- [ ] Assert stdout contains protocol data only and errors never expose local journal paths or credentials.

**Run:** `& $Python -m pytest openbb_platform\extensions\fmp_trading\tests\integration\test_mcp_stdio.py -q`.
**Acceptance:** the transport test fails if handler registration is removed, even if declaration tests remain green.

### T33 - Align Agents scope, schemas and documentation

**Feature:** F6.2. **Priority/phase/lane:** P1 / P1 / B-Analytics.
**Dependencies:** T02, T03. **Estimate:** 1-2 days.

**Files:** modify `openbb_platform/extensions/agents/README.md`,
`openbb_agents/mcp_server.py`;
extend `tests/test_mcp_server.py`.

- [ ] State the implemented two-tool surface and portfolio Q&A agent accurately.
- [ ] Preserve explicit marker opt-in, module ownership, private injection-argument exclusion, and synchronous dispatch constraints.
- [ ] Test public aliases, undecorated functions, async functions, and missing tool dependencies.
- [ ] Record the four absent agent products as separately scoped expansion, not enabled tools.

**Run:** `& $Python -m pytest openbb_platform\extensions\agents\tests\test_mcp_server.py -q`.
**Acceptance:** README, tool schemas, and registry agree on two implemented tools until additional products are approved.

### T34 - Validate Agents transport and sanitized portfolio access

**Feature:** F6.2. **Priority/phase/lane:** P1 / P2 / B-Analytics.
**Dependencies:** T33. **Estimate:** 1-2 days.

**Files:** create `openbb_platform/extensions/agents/tests/test_mcp_stdio.py`;
extend `tests/test_portfolio_tools.py` and its synthetic fixtures.

- [ ] Exercise real initialization/list/call for positions and sector exposure.
- [ ] Assert no owner/account/raw-lot data crosses the tool boundary.
- [ ] Test unavailable basket data, failed profile enrichment, empty basket, and error signaling.
- [ ] Verify callbacks/guardrails are not assumed to protect direct MCP tool calls unless actually invoked there.

**Run:** `& $Python -m pytest openbb_platform\extensions\agents\tests\test_mcp_stdio.py openbb_platform\extensions\agents\tests\test_portfolio_tools.py -q`.
**Acceptance:** sanitization and failure behavior hold over the wire, not just inside an agent conversation.

## 12. E7 - Truthful prompts, client configuration, and unified discovery

**Epic exit:** users and agents see an accurate capability map, prerequisites,
and operational instructions for the profiles they actually run.

### T35 - Add structured prompt dependencies and readiness checks

**Feature:** F7.1. **Priority/phase/lane:** P1 / P2 / D-Widgets+QA.
**Dependencies:** T02, T07. **Estimate:** 2 days.

**Files:** modify MCP `models/prompts.py`, `app/app.py`,
`assets/server_prompts.json`;
extend `tests/app/test_server_prompts.py`;
create `tests/app/test_prompt_dependencies.py`.

- [ ] Declare required tool names, provider selections, and optional packages for each bundled prompt.
- [ ] Validate dependencies against discoverable tools, not only the initial ten-tool list.
- [ ] Hide or explicitly mark unavailable prompts per profile; never suggest a missing operation as ready.
- [ ] Test conditional dependencies, resources, tool renaming, and optional FinancialToolkit absence.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_server_prompts.py openbb_platform\extensions\mcp_server\tests\app\test_prompt_dependencies.py -q`.
**Acceptance:** every required reference resolves or the prompt is explicitly unavailable.

### T36 - Correct cache, stock and FinancialToolkit instructions

**Feature:** F7.1. **Priority/phase/lane:** P1 / P3 / D-Widgets+QA.
**Dependencies:** T20, T22, T26, T28, T35. **Estimate:** 1-2 days.

**Files:** modify MCP `assets/server_prompts.json`, `assets/system_prompt.txt`,
`assets/profiles/portfolio.json`;
extend `tests/app/test_prompt_dependencies.py`.

- [ ] Replace the nonexistent `equity_fundamental_overview` reference with an actually supported operation and validated parameters.
- [ ] Remove unsupported historical `limit` assumptions and unlimited-quota/local-only claims.
- [ ] Make stock-deep-dive and toolkit prompts conditional on the required adapters/packages.
- [ ] Separate cache inspection from operator refresh instructions; never imply a prompt itself executes maintenance.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_prompt_dependencies.py -q`.
**Acceptance:** all bundled references and example arguments pass dependency/schema validation for each supported profile.

### T37 - Publish a unified capability resource and client examples

**Feature:** F7.2. **Priority/phase/lane:** P1 / P3 / D-Widgets+QA.
**Dependencies:** T10, T24, T25, T32, T34, T36. **Estimate:** 2 days.

**Files:** modify MCP resource registration in `app/app.py`, `.mcp.json.example`;
create `tests/app/test_capability_resource.py`;
update the cross-repository documentation index.

- [ ] Expose one versioned catalog resource showing each capability's owning surface, connection prerequisite, direct/indirect mapping, and verification level.
- [ ] Provide separate Platform, Workspace, Agents and Daytrade connection examples; no credentials embedded.
- [ ] Distinguish integrated Workspace port 8000 from optional standalone 8787.
- [ ] Test absence/disabled states rather than infer live availability from a static configuration file.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\app\test_capability_resource.py -q`.
**Acceptance:** the single view is truthful about separate sessions and transports; no capability is duplicated as independently verified coverage.

### T38 - Write operator setup, maintenance and rollback runbooks

**Feature:** F7.2. **Priority/phase/lane:** P1 / P3 / D-Widgets+QA.
**Dependencies:** T30, T37. **Estimate:** 1-2 days.

**Files:** create `docs/operations/portfolio-mcp.md`;
update `docs/cross_repo_workflow/mcp-coverage-report.md`,
`docs/cross_repo_workflow/README.md`, and launcher usage docs.

- [ ] Document clean profile setup, credential prerequisites, source provenance,
  bridge activation, read versus ops access, and metadata-only readiness.
- [ ] Document controlled service restart after source changes and exact-PID rollback.
- [ ] Include missing-package, missing-provider, unreachable-route, unavailable-browser,
  auth-denied and cache-DB-unavailable troubleshooting paths.
- [ ] Document Portfolio branch/PR direction and explicit pushes without changing upstream tracking.

**Validation:** relative links, configuration examples, CLI help consistency, and replay of the documented metadata-only path.
**Acceptance:** a new operator can reproduce catalog readiness without access to personal data or the author's local paths.

## 13. E8 - CI, live acceptance, and release rollout

**Epic exit:** acceptance proves callable approved capabilities, denied
privileges, source lineage, and recovery. Claims distinguish offline,
transport, browser and paid-data evidence.

### T39 - Build a shared real-protocol regression matrix

**Feature:** F8.1. **Priority/phase/lane:** P0 / P0 / QA.
**Dependencies:** T04, T07. **Estimate:** 2-3 days.

**Files:** create MCP `tests/integration/test_profile_protocol.py`;
reuse existing `tests/app/test_tool_execution.py`,
`tests/app/test_auth.py`, and FastMCP Client fixtures.

- [ ] Add real-client initialize/list/activate/call tests, including the concrete two-session test in section 5.
- [ ] Test pagination, schema serialization, prompt/resource access, direct denied calls, and independent client activation.
- [ ] Assert output protocol errors for handler failures and unavailable prerequisites.
- [ ] Keep separate baselines for the compatibility and Portfolio profiles.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\integration\test_profile_protocol.py -q`.
**Acceptance:** protocol tests fail on registration, invocation, isolation or policy regressions rather than merely checking decorators.

### T40 - Add Portfolio-based capability and prompt drift CI

**Feature:** F8.1. **Priority/phase/lane:** P0 / P2 / QA.
**Dependencies:** T06, T20, T22, T24, T25, T26, T35, T39.
**Estimate:** 2-3 days.

**Files:** create `.github/workflows/portfolio-mcp-coverage.yml`;
reuse existing base-guard conventions;
extend `scripts/audit_mcp_capabilities.py`;
create MCP `tests/service/test_coverage_diff.py`.

- [ ] Compare the exact PR base/head source inventories with compatible profile configuration.
- [ ] Fail on lost approved models/routes/tools, unknown capabilities, duplicate names,
  stale prompt references, or newly widened access without an approved policy change.
- [ ] Permit reviewed additive changes with updated evidence rather than freezing tool counts forever.
- [ ] Publish sanitized coverage artifacts; normal CI uses no live credentials or database.

**Run:** `& $Python -m pytest openbb_platform\extensions\mcp_server\tests\service\test_coverage_diff.py -q`.
**Acceptance:** a deliberate missing route or invalid prompt dependency causes CI failure; base is Portfolio, not upstream develop.

### T41 - Certify package and interpreter replay

**Feature:** F8.1. **Priority/phase/lane:** P0 / P2 / QA.
**Dependencies:** T10, T39. **Estimate:** 2 days.

**Files:** extend profile workflow and `scripts/test_portfolio_mcp.ps1`;
extend `scripts/tests/Test-PortfolioMcp.Tests.ps1`.

- [ ] Recreate the tested Python 3.12 and 3.13 environments from declared manifests.
- [ ] Verify import origins, optional-package behavior, packaged assets, entry points, and profile catalog assertions.
- [ ] Test an environment without the developer's existing cached wheel or editable installs.
- [ ] Report unsupported/missing interpreter conditions explicitly without changing declared package support.

**Run:** `Invoke-Pester -Path .\scripts\tests\Test-PortfolioMcp.Tests.ps1 -Output Detailed`;
`.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-read -Mode protocol`
in each approved interpreter environment.
**Acceptance:** two reproducible tested runtimes; no undocumented manual package installation needed for advertised profiles.

### T42 - Revalidate integrated Workspace and registered backend parity

**Feature:** F8.2. **Priority/phase/lane:** P1 / P3 / QA.
**Dependencies:** T24, T37, T39. **Estimate:** 2-3 days.

**Files:** extend parent `scripts/test_portfolio_mcp.ps1`;
reuse `scripts/invoke_workspace_mcp_command.ps1`,
the browser harness, and Workspace
`backend-api/backend/tests/test_workspace_mcp_surface_parity.py`,
`test_workspace_mcp_bridge.py`, `test_workspace_mcp_resources.py`.

- [ ] Verify authenticated live 18-tool metadata and distinguish resource descriptor differences from missing resources.
- [ ] Verify no-browser failure and browser-backed read operations against registered Portfolio/Intelligence connectors.
- [ ] In a disposable user/dashboard context, separately test approved create/update/delete/navigation behavior with cleanup.
- [ ] Record only sanitized structure/status; revoke temporary tokens and restore disposable UI state.

**Run:** `.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-read -Mode workspace-read`.
After separate disposable-state approval:
`.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-read -Mode workspace-mutation -AllowWorkspaceMutation`.
**Acceptance:** metadata, read parity, and mutation parity have separate pass/fail evidence; no tests modify the user's real dashboards or holdings.

### T43 - Validate controlled data and operator workflows

**Feature:** F8.2. **Priority/phase/lane:** P1 / P3 / QA.
**Dependencies:** T28, T30, T32, T34, T41. **Estimate:** 2-3 days.

**Files:** extend MCP integration fixtures and `scripts/test_portfolio_mcp.ps1`;
reuse isolated provider cache and jobs tests.

- [ ] Use a disposable database and bounded synthetic/public symbols for end-to-end cache and job tests.
- [ ] First verify fixture-backed full coverage; run paid-provider spot checks only with explicit scope and quota approval.
- [ ] Verify cache miss/hit, stale data, entitlement errors, worker absence, job warnings, retry/idempotency, and denied financial mutations.
- [ ] Require expected evidence for each live-tested capability instead of treating one successful symbol as universal provider support.

**Run:** `.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-ops -Mode operator-fixture -AllowMaintenance`.
After separate paid-request approval:
`.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-read -Mode provider-live -AllowPaidRequests -MaxProviderRequests 2`.
The paid spot check is explicitly not the 181-model contract suite.
**Acceptance:** live verification level is accurately recorded; untested entitlements remain unverified, not passed.

### T44 - Release, update coverage evidence, and prove rollback

**Feature:** F8.2. **Priority/phase/lane:** P0 / M4 / QA.
**Dependencies:** T38, T40, T41, T42, T43. **Estimate:** 1-2 days.

**Files:** update profile manifests, release documentation, current
`docs/cross_repo_workflow` coverage artifacts, and parent submodule pins
only where reviewed child-repository work is required.

- [ ] Stage rollout: compatibility profile retained, opt-in Portfolio canary,
  operator profile separately enabled, then documented promotion decision.
- [ ] Verify required tests, expected catalogs, source lineage, error handling and access boundaries at the release SHA.
- [ ] Roll back to the prior profile/source pins and verify readiness without restoring personal databases or killing unrelated services.
- [ ] Publish final gross/approved/persistence/invocation metrics with exceptions and remaining expansion work.

**Run:** `.\scripts\test_portfolio_mcp.ps1 -Profile portfolio-read -Mode metadata`
at both the release SHA and the restored rollback baseline, alongside the
required merged CI evidence.
**Acceptance:** all program ACs satisfied or explicitly rejected by the user;
no remaining work is hidden by lowering a coverage denominator. Release is
through Portfolio-targeted PRs, not a direct push to the integration branch.

## 14. Dependency order, parallel work and effort

### Milestones

| Gate | Required tasks | Demonstrable result |
| --- | --- | --- |
| M0 - Baseline agreed | T01, T02, T05 | Stable denominator, provenance and lineage |
| P0 - Foundation safe | T03, T04, T06, T07, T08, T39 | Reviewed policy, profiles and real-protocol regression harness |
| P1 - First useful increment | T09, T10, T11, T12-T15, T21, T23, T31, T33 | Reproducible profile, first routed batches and specialist corrections |
| P2 - Existing API parity | T16-T20, T22, T24-T28, T32, T34, T35, T40, T41 | All existing model/API families dispositioned and approved routes tested |
| P3 - Operator/client acceptance | T29, T30, T36-T38, T42, T43 | Truthful prompts, controlled operations, unified view and live acceptance |
| M4 - Release | T44 | Reproducible release and exercised rollback |

Milestone membership does not override task dependencies. For example,
T40 cannot pass just because CI scaffolding exists before its model/app
coverage dependencies are complete.

### Parallel lanes

- After T11, FMP batches can proceed in parallel **only with separate router/test files**.
  The FMP route manifest and root assembly have one integration owner to prevent conflicting edits.
- T21/T22 and T23/T24 can proceed alongside FMP batches after policy approval.
- T31/T32 and T33/T34 are independent specialist lanes once the baseline policy exists.
- T25/T26 can run independently of the custom-widget adapters.
- T35 may begin with declared dependencies; T36 waits for the actual approved tools.
- Runtime launcher work has one owner for `start-dual-mcp.ps1`; others contribute tests or reviewed patches.
- Do not parallel-edit the central policy, profile manifest, workflow, or capability model without an explicit single integration owner.

### Effort assumptions

Task estimates are engineering effort ranges, not calendar commitments.
The proposed work is approximately **81-119 engineer-days**, excluding
review queues, separately approved new agent products, and conversion of
all non-persistent fallback fetchers.

A three-lane execution model with a shared integration/QA owner is a
planning option, not an assignment. Schedule Start/End dates only after
owners, dependency availability, and approved live-test access are known.
Large batches should be split further if their first contract test reveals
nonuniform schemas or missing underlying implementations.

## 15. Later issue creation procedure - do not execute yet

After A1 and explicit A2 authorization:

1. Re-read this plan against current `origin/portfolio`; refresh counts and
   search existing open/closed issues for duplicates.
2. Present the final creation count and reused issues. The current maximum
   is 72 new issues plus the existing Daytrade task.
3. Create the new program epic, then delivery epics, features, and new tasks,
   using stable plan IDs in titles/bodies for idempotent reconciliation.
4. Use actual GitHub parent/sub-issue relationships for newly created
   hierarchy nodes. Use database issue IDs where the REST relationship API
   requires them; do not substitute visible issue numbers.
5. Keep reused Daytrade work's ownership/parenting intact and link it as a
   dependency of the new F6.1 feature. Add it to Project #4 only after approval.
6. Add each approved issue to Project #4; set Type, Phase, Lane and Status
   using the already verified fields. Initial Status is Todo.
7. Apply the existing type/area/priority labels and the approved program label.
8. Add dependency relationships and reciprocal cross-program links; do not
   rely only on a checklist of issue numbers in an epic body.
9. Read back every created issue, hierarchy edge, project item and field.
   Record real URLs in an execution mapping artifact; never manufacture them.
10. Do not assign/claim implementation tasks until A3. At execution, use the
    repository claim/heartbeat protocol and merge-completion conventions.

### Issue body content

Each task issue must include its title and stable plan ID, exact parent
feature, the linked plan/task section, owned source files, task checklist,
acceptance criteria, dependencies, test commands, expected failure/success,
privacy/access constraints, estimate, and evidence requirements.

Each feature issue must list its tasks and the feature-level outcome.
Each epic must contain its scope, exclusions, features, exit gate and
cross-epic dependencies. The program epic links the predecessor Portfolio
work, this plan, the audit, milestones, and the definition of coverage.

When a new issue replaces or extends existing work, include:

```text
Provenance: MCP capability audit at 39f171603c9
Tracking: Project #4, Portfolio Intelligence Engine
Integration target: portfolio (prajoria/OpenBB)
Plan ID: the corresponding E/F/T identifier in this document
Scope: implemented-capability parity; no implicit new trading privileges
Evidence: source/API/MCP layer and required validation level
```

This is a body schema, not a fabricated issue URL or a pending remote action.

## 16. Risk, rollout and scope controls

| Risk | Prevention and detection | Owner |
| --- | --- | --- |
| Coverage inflated by counting prompts, widgets or aliases as independent APIs | Separate metrics and typed identities; gross denominator retained | E1/E8 |
| New packages silently expand privileges | Opt-in profiles, explicit policy, discovery and invocation tests | E1/E2 |
| 111 registrations hide incompatible or missing models | First vertical slice, typed manifest, per-batch execution fixtures | E3 |
| Financial results change during adapter work | Reuse original dispatch, compare API/MCP fixtures, preserve canonical names | E3/E4 |
| Cached provider still calls upstream | Explicit persistence/entitlement descriptors and hit/miss tests | E3/E5 |
| Private portfolio data bypasses agent guardrails | Direct tool-level authorization and sanitization tests | E4/E6 |
| Workspace catalog works without a browser but operations do not | Separate no-browser/live bridge evidence | E8 |
| Existing Daytrade task duplicated or ownership overwritten | Reuse/link existing task; verify relationships before writes | E6/PM |
| Mixed checkouts yield unreproducible success | Profile origin checks and clean installs | E2/E8 |
| Scoped maintenance becomes arbitrary code/SQL execution | Allowlisted existing jobs, typed params, original auth, no raw dispatch | E5 |
| Massive coordinated PR blocks delivery | Reviewable task PRs, dependency order, compatibility profile retained | All epics |
| Parent/submodule changes race | Child-repository review in its owning repo, then parent pin/update acceptance | E8 |

If a task finds an absent underlying business implementation, classify it
`unimplemented`, preserve the gross gap, and request separately scoped
product approval. Do not stub a successful data response or claim the adapter
alone completed the capability.

## 17. Plan self-review and approval checklist

- [ ] Approve profile architecture and the distinction between read,
  private-data, operator, and Workspace mutation capabilities.
- [ ] Approve routing existing FMP gaps through a provider-owned namespace
  while retaining all existing canonical tool names.
- [ ] Approve the proposed 1 program epic, 8 delivery epics, 20 features,
  and 44 tasks, subject to refreshed issue deduplication.
- [ ] Confirm reuse of the existing Daytrade MCP task rather than duplicate creation.
- [ ] Approve scope boundaries for absent Agents products and future
  persistent-cache conversions.
- [ ] Authorize GitHub issue/project creation as the next action, separately
  from implementation and operational validation.

### Audit recommendation-to-task completeness map

| Audit recommendation | Planned coverage |
| --- | --- |
| Reproducible Portfolio MCP dependency/app profile | T07-T10, T21, T24, T41 |
| Reconcile 111 unrouted FMP registrations | T11-T20 |
| Review custom Portfolio/Intelligence exposure | T03/T04, T21-T24 |
| Fix prompt and profile dependency drift | T35/T36 |
| Deliberate cache observability and maintenance | T27-T30 |
| Complete Daytrade protocol registration | T31/T32 |
| Align Agents documentation and real functionality | T33/T34 |
| Expand readiness beyond equity presence | T10, T39, T41 |
| Eliminate accidental mixed-source runtime assumptions | T02, T08, T41 |
| Continuously compare capability coverage against Portfolio | T05/T06, T40, T44 |
| Preserve Workspace authentication/bridge and separate parity claims | T37, T42 |
| Maintain safe merge direction and tracked delivery | T05, T38, section 15 |

**Handoff:** approve or revise the plan first. The next authorized action
should be issue deduplication and Project #4 hierarchy creation, not automatic
code execution. Implementation can then proceed through reviewed parallel
task execution or sequential dependency-ready batches.
