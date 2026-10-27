# Portfolio MCP parity release record

This is the release record for the Portfolio MCP capability-parity program
(#2123), produced by T44 (#2194). The release is delivered only through a pull
request targeting the `portfolio` integration branch. The pull request head is
the release candidate, its exact base SHA is the rollback baseline, and the
merged PR SHA is the promoted release SHA.

## Promotion decision

The operator approved finishing the program on 2026-10-27. The decision is:

1. **Compatibility retained.** `platform-standard` stays the default. It does
   not compose Portfolio-private adapters.
2. **`portfolio-read` is promoted** as the opt-in Portfolio profile. Clients
   select it explicitly and connect with effective HTTP authentication.
3. **`portfolio-ops` is promoted separately.** Its cache-job tools also
   require `OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS=true`.
4. Promotion takes effect when the release PR merges after its required checks
   pass at the same head SHA: Python 3.12/3.13 wheel replay, Python 3.14
   rejection, profile protocol, Workspace contract, controlled operator
   fixture, and Portfolio base/head inventory drift.

No profile enables broker or order execution, raw private portfolio rows,
arbitrary jobs, scripts, SQL, cache invalidation, or unrestricted cancellation.

## Release evidence

### Metadata readiness

Run without data access:

```powershell
.\scripts\test_portfolio_mcp.ps1 `
    -Profile portfolio-read `
    -Mode metadata `
    -PythonExecutable $env:OPENBB_PORTFOLIO_PYTHON `
    -RepositoryRoot (Get-Location).Path
```

The probe calls `scripts/audit_mcp_capabilities.py --metadata-only`. It does
not call providers, cache databases, jobs, browser sessions, or personal
portfolio services, and it fails on any capability collision.

Result at the release candidate, measured in the operator's
`.venv_portfolio` (FinancialToolkit not installed there):

| Profile | Capability records | Collisions | FMP models | Policy-admitted tools |
| --- | --- | --- | --- | --- |
| `platform-standard` | 401 | 0 | 181 | — |
| `portfolio-read` | 488 | 0 | 181 | 412 |
| `portfolio-ops` | 494 | 0 | 181 | 421 |

Capability records are registrations. A record is exposed only when
`evaluate_exposure` admits it for the profile, which is why the four raw
private Portfolio reads appear as records but are never admitted.

### Rollback proof

Rollback never restores personal databases and never kills processes by name.

1. Record the PR base SHA and release head SHA from the CI event.
2. Stop the launcher with `start-dual-mcp.ps1 -Action Stop`. It verifies the
   exact PID, start time, and executable identity before terminating.
3. Create a detached worktree at the base SHA and use a Python environment
   owned by that worktree.
4. Run `test_portfolio_mcp.ps1 -Mode metadata -RepositoryRoot <rollback
   worktree>`. The audit script puts its own checkout's sources first on
   `sys.path`, so it measures the rollback code, not the release code.
5. Confirm the base inventory matches the CI base artifact and starts with the
   same declared profile.
6. Start the rollback worktree only after readiness succeeds.

Exercised on 2026-10-27 against two rollback points:

- **PR base `9525279`:** all three profiles ready, with the same counts as
  the release candidate.
- **`cb0c226`, the profile pin before #2294** (admit SSRF-hardened document
  URL fetchers): all three profiles ready. The coverage diff from that pin to
  the release candidate is non-blocking. It shows exactly the 9 #2290 routes
  as reviewed additions, with no lost capabilities, models or tools, no
  duplicate names, no unknown capabilities, and no unreviewed widening.
  Rolling back removes exactly those 9 routes.

The release CI runs the equivalent proof on every PR: it checks out the exact
`portfolio` base and PR head independently, recreates isolated environments,
exports both inventories, and requires a non-blocking comparison.

## Final reviewed metrics

| Surface | Reviewed evidence |
| --- | --- |
| FMP Cached | 181/181 registrations routed |
| Persistence | 123 dedicated/persistent; 58 explicitly non-persistent (inventory and `cache_coverage` agree since #2298) |
| Portfolio adapter | 19 operations: 15 sanitized direct reads; 4 permanently denied raw private reads |
| Intelligence | 69 reviewed operations; 60 read-profile tools; 1 additional ops-only scan trigger |
| FinancialToolkit | 67 conditional tools when the extension and underlying package are installed |
| Cache operations | 2 sanitized observability tools; 5 authenticated, opt-in durable job tools |
| Agents | 2 sanitized real-stdio tools |
| Daytrade | 6 read-only real-stdio tools |
| Workspace | 18 tools, 16 resources plus 1 result-offload resource template, and 2 prompts on the separate authenticated browser-bridge surface |
| Prompts | 42 bundled prompts with structured readiness. 40/43 served prompts are available in the Portfolio profiles; the rest name an uninstalled optional package (#2300) |
| Operator fixture | 196 offline cache, job, and policy cases pass |

### Program metrics

These are reported separately and are never summed into one coverage figure.

| Metric | Value | Evidence |
| --- | --- | --- |
| `gross_model_reachability` | 181/181 | Every registration is routed (`test_default_inventory_accounts_for_every_fmp_cached_registration`) |
| `approved_model_reachability` | 181/181 | The routed-provider policy rule admits every routed model to all three profiles |
| `persistence_coverage` | 123/181 | Reviewed `persistence_descriptors.json`; the other 58 are labelled non-persistent |
| `api_disposition_coverage` | 317/317 | Every audited operation classifies to one disposition: 298 direct, 10 metadata-only, 9 restricted (`test_exposure_policy.py`) |
| `api_invocation_coverage` (FMP) | 181/181 | 112 provider-owned models (`test_every_provider_owned_tool_is_callable_through_mcp`) plus 70 legacy mappings (#2302), one model shared |
| `prompt_dependency_coverage` | 40/43 served prompts available in the Portfolio profiles | Declared tools and providers all exist (#2300); the remaining 3 depend on uninstalled optional packages or providers and say so |

## Program acceptance criteria

| ID | Status | Evidence |
| --- | --- | --- |
| AC-01 | Satisfied | Hashed dual-MCP lock enforced at launch (#2245, #2282); CI replays the profile on Python 3.12 and 3.13 and on a clean Windows cache |
| AC-02 | Satisfied | Every audited operation has a disposition and access class; all 19 policy rules have an owner in `traceability.rule_owners`. The inventory's per-record `owner_lane` remains a placeholder, declared as a scope limitation |
| AC-03 | Satisfied | 181/181 routed and invoked offline through MCP; the 70 existing mappings are preserved |
| AC-04 | Satisfied | No routing gaps remain (181/181); the original 111 gaps closed through provider-owned routes |
| AC-05 | Satisfied | 58 fallbacks are marked non-persistent in both the inventory and `cache_coverage` |
| AC-06 | Satisfied | 19 Portfolio and 69 Intelligence operations have reviewed dispositions with contract and authorization tests |
| AC-07 | Satisfied | Prompts reference only emitted tools and registered providers (#2300); unavailable prompts give actionable reasons |
| AC-08 | Satisfied | 18-tool Workspace surface on its authenticated bridge; metadata, live read, and scoped mutation suites are separate |
| AC-09 | Satisfied | Six Daytrade observation tools over real stdio; submit and broker operations are unreachable |
| AC-10 | Satisfied | Agents documentation, two registered tools, and callable entry points agree |
| AC-11 | Satisfied | Observability is read-only; maintenance needs `portfolio-ops`, authentication, and an explicit opt-in |
| AC-12 | Satisfied | CI compares route, model, prompt, and catalog drift against the PR base; this record holds provenance, rollback, and coverage |

This release re-ran the metadata readiness, rollback, operator-fixture,
prompt-dependency, and FMP invocation checks. For AC-08 to AC-10 the evidence
is the merged task suites (#2191, #2192, #2193) and the CI jobs that run them.

## Exceptions and remaining expansion

- Live provider spot checks do not replace the 181-model contract. Untested
  entitlements stay `unverified`.
- Caller-controlled document URL fetchers are admitted only after SSRF
  hardening (#2242, #2290).
- Workspace browser-backed live reads need an authenticated browser bridge.
  Mutation checks need separate approval and a dashboard whose own name is
  marked `MCP parity disposable`. Temporary widgets are deleted and prior
  dashboard and tab navigation is restored.
- Personal MySQL portfolio data is never part of CI evidence.
- Brokerage execution remains an approved exclusion.
- Future provider persistence conversions need their own storage, TTL,
  entitlement, and atomic-write review.
- The Notebook Companion program (#2195) starts after this release gate
  merges and is tracked separately on Project #4.

See the [Portfolio MCP operator runbook](./portfolio-mcp.md), the
[coverage report](../cross_repo_workflow/mcp-coverage-report.md), and the
[capability decisions](../cross_repo_workflow/mcp-capability-decisions.md).
