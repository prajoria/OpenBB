# MCP capability exposure policy

Status: implementation specification for
[#2154 (classify every capability and publish profile policy)](https://github.com/prajoria/OpenBB/issues/2154),
under [#2133 (reviewed exposure and invocation policy)](https://github.com/prajoria/OpenBB/issues/2133).
Integration target: `portfolio`.

## Purpose

Classify the complete audited operation/provider/specialist denominator without
using HTTP method as a side-effect proxy. The policy is admission metadata; it
does not replace authentication or endpoint authorization.

Unknown capabilities are denied. Restricted and unimplemented decisions remain
in gross counts and require a reason. Rules are ordered, stable, and
independently reviewable in `assets/capability_policy.json`.
Each core/Intelligence scope ends in a restricted catch-all; reviewed category
and path families must match at a higher priority before admission.

## Profiles

| Profile | Admitted access |
| --- | --- |
| `platform-standard` | `public_metadata`, `provider_read` |
| `portfolio-read` | Standard plus `private_portfolio_read` |
| `portfolio-ops` | Read plus `filesystem_write`, `cache_maintenance`, `job_control`, `workspace_mutation` |

`financial_mutation` is not admitted by these profiles. Paper/order/broker-like
actions require a later explicit sandbox/approval contract; no profile entry
alone authorizes invocation.

## Operation rules

1. Manifests, roots, health/about, catalogs and coverage metadata are
   `public_metadata`.
2. Core data, analytics, backtest, validation, tuning and text-download
   operations are `provider_read` even when their transport method is POST,
   except persisted bundle/tuning writes and URL-fetch operations awaiting SSRF
   hardening.
3. Portfolio holdings, allocation, cost/tax, snapshots, ESPP, book context,
   lookthrough, account-scoped analytics and paper-state reads are
   `private_portfolio_read`.
4. File/workbook/order-batch exports are `filesystem_write`.
5. Trigger/cancel job-control operations are `job_control`.
6. Workspace-only widget/application surfaces are `workspace_indirect`.
7. Approval/order/fill/cancel execution actions are `financial_mutation` and
   restricted in every current profile.
8. Custom Portfolio routes remain restricted until the reviewed T21 adapter;
   their access class still records the privilege they would require.
9. Coverage routes remain metadata-only rather than disappearing.

The committed 317-row audit fixture must have exactly one winning rule per row.
Policy drift fails if a row becomes unclassified or equally matches rules at the
same priority.

## Provider and specialist rules

- A provider/model registration with one or more current commands and the
  provider registered for that model is `direct` / `provider_read`.
- An unrouted registration is `unimplemented`, retained in gross coverage, and
  denied until the routing tasks close it.
- Agents tools currently registered in the catalog are restricted pending the
  specialist MCP verification tasks.
- Daytrade declarations without callable protocol handlers are
  `unimplemented`.
- Metadata-only admin/catalog helpers are admitted only where their access class
  is allowed by the selected profile.

Provider routed/unrouted decisions and specialist defaults live in the JSON
asset rather than Python constants. Restricted/unimplemented asset entries may
not list admitted profiles.

## Interfaces

```python
class ExposureDecision(BaseModel):
    capability_id: str
    rule_id: str
    disposition: Disposition
    access_class: AccessClass
    admitted_profiles: tuple[ProfileName, ...]
    reason: str | None

class ExposurePolicy:
    def classify_operation(self, scope: str, method: str, path: str) -> ExposureDecision: ...
    def classify_provider_model(self, row: ProviderModelMetadata) -> ExposureDecision: ...
    def evaluate_exposure(self, record: CapabilityRecord, profile_name: ProfileName) -> bool: ...
```

`evaluate_exposure` requires a prior policy decision and admits only
`direct`, `workspace_indirect`, or `metadata_only` decisions whose access class
is in the profile. It returns false for unknown IDs, restricted/unimplemented
records, and all financial mutation.

## Acceptance

1. All 317 audit rows classify exactly once with zero unknowns.
2. All current FMP Cached rows classify; the routed/unrouted partition remains
   explicit.
3. Catalog specialist declarations classify without overstating callability.
4. POST compute/read operations are not mislabeled as mutation.
5. Execution/broker-like operations are denied in every current profile.
6. Operator-only access cannot leak into `portfolio-read`.
7. Reasons are mandatory for restricted/unimplemented decisions.
8. Unknown routes and unknown capability IDs are denied by default.
