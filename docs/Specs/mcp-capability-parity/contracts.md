# MCP capability inventory contracts

Status: implementation specification for
[#2152 (capability contracts and immutable audit fixtures)](https://github.com/prajoria/OpenBB/issues/2152),
under [#2132 (versioned source/API/MCP inventory)](https://github.com/prajoria/OpenBB/issues/2132)
and [the MCP parity program](https://github.com/prajoria/OpenBB/issues/2123).
Integration target: `portfolio`.

## Scope

Define validated metadata shared by later inventory, policy, runtime-profile and
coverage work. Importing or validating these contracts must not initialize OpenBB,
read credentials, contact providers, connect to databases or start an MCP server.
This task does not expose new tools or implement authorization.

The approved program's `OperationKey`, `VerificationState` and
`CapabilityRecord` wire fields are retained. `CapabilityInventory` validates
record identity and provides coverage counts without changing the denominator.

## Validation

- Unknown fields, coercion of flags, empty identifiers and unsupported schema
  versions fail validation.
- HTTP methods normalize surrounding whitespace and case. API paths must be
  absolute path-only templates, without origins, queries, fragments, traversal,
  backslashes or control characters.
- Source references are nonempty repository-relative paths or qualified symbols;
  absolute local paths and traversal are rejected.
- Requirement strings name prerequisites; they never contain credential values.
  Recognizable key/password/token assignments, bearer tokens, URL userinfo and
  private-key material are rejected wherever metadata accepts text. This is a
  metadata hygiene guard, not a general-purpose secret detector.
- Pydantic retains rejected values in raw `ValidationError.errors()` data even
  when human-readable input display is disabled. API/logging boundaries must use
  `sanitized_validation_errors()` or `sanitized_validation_error_json()` and
  must never serialize a raw validation exception.
- Direct Platform records need both an operation and a tool name. Direct
  Workspace/Agents/Daytrade records need a tool name and source references to
  their explicit registration; HTTP operation metadata is optional.
- Restricted and unimplemented records need an explanatory reason or a reviewed
  decision reference. They remain in gross coverage.
- Duplicate capability IDs are rejected by the inventory. Aliases with distinct
  IDs may share an implementation.
- JSON round trips preserve all three false verification flags.

## Small refinements to the planning pseudocode

`VerificationState` uses the Python attribute `schema_verified`, accepting and
serializing the wire alias `schema`. Pydantic's inherited deprecated
`BaseModel.schema()` conflicts with the draft's Python field name: an observed
runtime probe emitted a shadowing warning. The alias preserves the published
JSON contract without suppressing warnings or overriding a framework method.
Default serialization uses aliases, including nested inventory serialization.

Validated records, evidence states, inventories and nested sequences are
immutable. Collectors construct replacement models when evidence changes rather
than mutating a previously validated contract. Disposition counts use an
immutable mapping-compatible Pydantic model so their JSON wire shape remains an
object while post-validation item mutation is impossible.

`CapabilityRecord` adds optional `implementation_id`. An inventory cannot
reliably infer implementation identity from a tool alias, route or model-key
count. Collectors supply the identity when verified; absent identity remains
unknown rather than being guessed.

## Counting contract

- `gross_records`: every validated record, including restricted/unimplemented.
- `approved_records`: direct, workspace-indirect and metadata-only records.
- `unique_implementations`: distinct `(surface, implementation_id)` identities
  explicitly present in records.
- `implementation_aliases`: identified records beyond those unique identities.
- `unidentified_records`: records with no implementation identity.
- Disposition counts retain all five categories, including zero counts.

Counts describe inventory records and declared implementation identities. They
are not evidence of successful calls, entitlement, cache persistence or financial
workflow completion.

## Immutable evidence

Four existing sanitized audit artifacts are copied byte-for-byte to
`openbb_platform/extensions/mcp_server/tests/fixtures/capability_audit/`:

- `mcp-api-inventory.csv`: 317 operation rows.
- `mcp-fmp-model-coverage.csv`: 181 model rows, 70 routed and 111 unrouted.
- `mcp-catalog-snapshot.json`: the audited multi-surface catalog.
- `portfolio-recent-commits.csv`: 948 recent commits.

The fixture manifest records their SHA256 values and source baseline
`39f171603c9bc4a28778e668ba981cf0e4358b9a`. Tests verify bytes and historical
counts. Later capability changes require new versioned evidence, not silent
rewriting of this baseline.

Synthetic contract records cover every disposition and access class. No
financial outputs, account identifiers, credentials or machine-specific paths
are part of valid fixtures.

## Acceptance and verification

1. Targeted new tests demonstrate failure before implementation.
2. Contract tests cover validation, aliases, duplicates, counting, serialization
   and evidence hashes; existing neighboring model tests stay green.
3. A real metadata-only harness loads the synthetic inventory, serializes it,
   reconstructs it and verifies the immutable evidence without network access.
4. Existing lint/type diagnostics and local/PR review gates pass.
5. The issue closes only after the accepted PR merges into `portfolio`.
