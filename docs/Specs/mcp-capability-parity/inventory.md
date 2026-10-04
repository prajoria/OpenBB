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

Only committed, non-comment profile fields enter the fingerprint. Fields whose
names imply credentials, auth, tokens, secrets, passwords, API keys or headers
are excluded before hashing. No environment values enter the fingerprint.

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

Missing optional packages produce explicit unavailable-component rows. They do
not remove expected distributions from provenance or fabricate provider rows.

## Runtime provenance

Runtime metadata contains:

- Python implementation and version (not executable path);
- repository HEAD and clean/dirty state;
- registered submodule path and pinned SHA (not remote URL);
- selected distribution version/editable state;
- normalized module origin (`repo://`, `site-packages://`, or external filename);
- profile source and safe configuration fingerprint;
- declared service states as `not_probed_metadata_only`.

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
