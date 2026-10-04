# MCP metadata-only capability inventory

Status: implementation specification for
[#2153 (metadata-only inventory CLI)](https://github.com/prajoria/OpenBB/issues/2153),
under [#2132 (versioned source/API/MCP inventory)](https://github.com/prajoria/OpenBB/issues/2132).
Integration target: `portfolio`.

This specification builds on the
[capability contract](./contracts.md) delivered by #2152.

## Purpose and boundary

Produce a reproducible source/runtime inventory that joins:

- FastAPI route and method identity;
- effective MCP tool/resource name, category and subcategory;
- source model and `CommandMap` route;
- provider/model/fetcher registrations, including FMP Cached persistence class;
- inline and bundled prompt metadata;
- selected profile metadata;
- source, submodule, distribution, import-origin and interpreter provenance.

Collection is **metadata-only**. It may import registration modules and inspect
classes, routes, package metadata and Git metadata. It must not:

- call endpoint functions or fetcher extraction/test methods;
- create a query executor;
- read user settings, credentials or environment-variable values;
- connect to a provider, cache, database, browser or MCP transport;
- create or modify the user's MCP settings file;
- start FastAPI, FastMCP, Uvicorn or a worker.

Registration imports run with a temporary home, credential-bearing environment
values removed, Python sockets blocked, and installed OpenBB entry points
filtered to entry points both declared by this checkout and resolving inside it.
Checkout declarations missing from the environment and installed registrations
not declared by the checkout are reported. Installed and checkout-declared target
callables must match exactly; stale target metadata is rejected. The guard executes trusted checkout
registration code only; it never loads arbitrary installed extensions.

The guard is process-global and protected by a re-entrant lock. Environment
restoration runs for failures as well as success. A document with foreign
loaded entry-point/source markers, no direct route capabilities, or an
unexplained empty provider-model set is refused as parity evidence and the CLI
exits nonzero. Checkout registrations that are not installed remain explicit
`missing_from_environment` prerequisites; they do not silently reduce the
denominator and are not confused with executing foreign code.
The library refuses collection when OpenBB's singleton extension loader was
initialized before the guard, because installed registrations could already have
been snapshotted without filtering.
Safely excluded extra installed entry points remain disclosures rather than
fatal errors; foreign or target-mismatched loaded core/provider registrations
are fatal.

The CLI requires `--metadata-only`; there is no implicit active-probe mode.

## Inputs and profiles

```text
python scripts/audit_mcp_capabilities.py \
  --profile portfolio-read \
  --metadata-only \
  --output-dir <OUTPUT_DIR>
```

Supported inventory labels are `platform-standard`, `portfolio-read` and
`portfolio-ops`. Until the runtime-profile tasks #2158/#2159 are delivered,
these labels resolve only to committed profile metadata:

- `platform-standard` -> bundled `full.json`;
- `portfolio-read` -> bundled `portfolio.json`;
- `portfolio-ops` -> bundled `portfolio.json`, with the inventory label retained.

This alias is an audit input, not an exposure-policy decision. The report records
the source profile and configuration fingerprint so later profile work can
replace it without silently changing evidence.
The profile metadata also records `alias_group`; `portfolio-read` and
`portfolio-ops` therefore explicitly disclose their shared provisional
`portfolio.json` source rather than implying distinct exposure policies.

Only committed, non-comment profile fields enter the fingerprint. Fields whose
names imply credentials, auth, tokens, secrets, passwords, API keys or headers
are excluded before hashing. No environment values enter the fingerprint.
The checkout-controlled default `/api/v1` prefix is materialized into the safe
profile before hashing, so route identity never falls back to user system settings.

## Stable output set

The output directory contains:

| File | Contract |
| --- | --- |
| `inventory.json` | Complete versioned document, sorted deterministically. |
| `capabilities.csv` | One row per `CapabilityRecord`, with canonical operation and evidence fields. |
| `provider_models.csv` | One row per provider/model registration, joined to command routes and MCP tool names. |

No timestamps, process IDs, temporary paths, host names or absolute machine
paths are included. Repeated runs against the same source/runtime metadata must
produce byte-identical files.

`inventory.json.denominators` separates route, direct-route, restricted-route,
prompt and profile records and lists missing core entry points. Route parity is
computed from records with a non-null operation, never from the mixed
`CapabilityInventory.coverage_counts().gross_records`.

Every CSV text cell beginning with a spreadsheet-active prefix is apostrophe
neutralized, including TAB/CR/LF prefixes. JSON retains the original validated
value.

An output directory inside the repository must already be ignored by Git.
Otherwise the CLI rejects it before collection. This prevents output creation
from changing the recorded untracked state between repeated runs.

Writes are atomic per file. Existing files are replaced only after the new bytes
are complete. CSV uses UTF-8, LF line endings and a fixed column order.

## Route and prompt inventory

Route inspection walks `APIRoute` objects without calling
`process_fastapi_routes_for_mcp`, because that function intentionally mutates the
application's route collection. It reuses shared pure helpers for:

- normalized API prefix;
- route MCP configuration;
- effective category/subcategory/name;
- inline prompt definition.

`HEAD` and `OPTIONS` are excluded. `expose=false` and module exclusions remain
in the gross denominator as restricted records with reasons. Explicit resource
and resource-template routes are metadata-only records; effective tool routes
are direct records. Catch-all behavior follows the selected MCP settings.

Tool, operation and prompt-name collisions are listed explicitly. They do not
silently replace records. Python implementation identity is a hash of the
callable module/qualname; multiple routes may therefore be measured as aliases
of one implementation.

Route requirements record profile-default enablement, explicit enable overrides,
and that owner/access classification remains provisional for #2154. The required
`owner_lane` uses `D-Widgets+QA` as a schema-compatible placeholder and every
route carries `owner-classification:provisional-placeholder`; consumers must not
route ownership from that field until #2154. `direct`
means registered/directly adaptable, not necessarily enabled at profile startup.
CSV includes distinct exclusion reasons for code-declared and module-derived
restrictions.

Each route also records extra MCP tags, fixed-toolset selection, discovery mode,
and effective startup enablement. Discovery profiles therefore correctly report
all non-admin route tools disabled at startup even when their categories belong
to the fixed toolset.

Prompt records retain the readable prompt name, the runtime path-derived tool
join key, and the effective component name separately. A name override mismatch
therefore remains observable. Prompts from excluded routes are not reported as
available prompt metadata.

Method access classification is conservative pending #2154:

- `GET` -> `provider_read`;
- every other HTTP method -> `financial_mutation`.

This classification is an input to policy review, not authorization.

## Provider-model join

`ProviderInterface`, `CommandMap` and provider fetcher dictionaries are inspected
as metadata. For each provider/model row record:

- model and provider;
- fetcher class/module and stable implementation identity;
- `dedicated`, `fallback_none` or `unverified` persistence;
- zero or more command routes;
- zero or more effective MCP tool names;
- routed/unrouted status;
- credential **field names** required by that provider, never their values.

FMP Cached classification uses only the fetcher class module:
`openbb_fmp_cached.models.base_cached` is fallback/non-persistent; other
registered modules are dedicated. No fetcher is instantiated or invoked.
`routed` additionally requires that the provider is registered for the standard
model; a fetcher class and unrelated model command are insufficient.

Missing optional packages produce explicit unavailable-component rows. They do
not remove expected distributions from provenance or fabricate provider rows.
The first release explicitly scopes `provider_models.csv` to FMP Cached and
records that limitation alongside the omitted FastMCP admin tools and
skills-derived prompts.

`build_inventory(validate=True)` fails closed by default. Diagnostic callers may
request `validate=False` to inspect an invalid document, but the CLI always
validates before writing evidence.

`inventory.json` is the authoritative evidence root because it contains scope
limitations, collisions, provenance and unavailability. The CSV files are
normalized projections for analysis and must not be used alone to compute a
gross parity denominator.
The first release explicitly marks Portfolio launcher-composed routes and the
Agents surface as not enumerated by the default core app. Profile categories
with no matching routes are emitted as unavailable components.

## Runtime provenance

Runtime metadata contains:

- Python implementation and version (not executable path);
- repository HEAD and clean/dirty state;
- tracked-dirty and untracked state separately;
- registered submodule path and pinned SHA (not remote URL);
- selected distribution version/editable state;
- normalized distribution source (`repo://`, `site-packages://`, or hashed
  `external://`) independently from import origin;
- normalized module origin (`repo://`, `site-packages://`, or external filename);
- profile source and safe configuration fingerprint;
- declared service states as `not_probed_metadata_only`.
- route-affecting `DEV_MODE` and `JOBS_ENABLED` booleans.

Every module that contributes a route or provider fetcher is included in import
provenance. The CLI prefers this checkout's extension/provider roots. If a
contributor still resolves outside the checkout, its normalized origin uses a
hashed `external://` namespace and the document adds
`source:<module>:outside_repo_root`; it never stamps a foreign source silently
with the current repository commit.

Git absence/failure and missing distributions/modules are explicit unavailable
states. The collector does not infer source provenance from a version alone.

## Acceptance

1. Synthetic tests prove no endpoint/fetcher/query executor/database/network
   function executes.
2. Missing packages/services, duplicate operations/names, aliases and collisions
   are explicit.
3. Current FMP Cached registrations are all represented and joined to current
   command/tool metadata.
4. JSON and CSV ordering/bytes are stable across identical repeated inputs.
5. Provenance contains no secrets or machine-specific absolute paths.
6. The required CLI harness completes for `portfolio-read` and reports
   metadata-only operation.
7. Targeted tests, Black, mypy, Pylint, Ruff, real harness, local review and PR
   convergence pass before merge.
