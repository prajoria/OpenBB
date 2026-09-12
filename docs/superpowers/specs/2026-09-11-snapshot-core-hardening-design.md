# Snapshot Core Hardening Design

- **Status:** Approved for autonomous implementation
- **Issues:** #1964, #1965, #1966, #1967
- **Parent:** #1932
- **Target:** `portfolio`

## Decision

Extend `openbb_techtrade.snapshot` as the single generic EOD persistence
layer. Do not add behavior to the legacy scan-specific
`openbb_techtrade.snapshots` package. A future compatibility adapter may map
legacy scan records into the generic API, but only when a consumer migration
proves it is necessary.

Three approaches were considered:

1. **Harden the generic package (selected).** Keeps one lower-level store for
   techtrade writers and portfolio-intel readers, avoids a dependency cycle,
   and makes correctness and privacy policy reusable.
2. Expand the legacy scan store. This duplicates lifecycle, provenance, and
   privacy rules and is rejected.
3. Put orchestration and persistence in `openbb_portfolio_intel`. This makes
   techtrade import upward and is rejected.

The selected design preserves the compute-free read contract and keeps
consumer dataset fan-out (#1968, #1969, #1942-#1945) out of this change.

## Persistence and promotion

`pi_eod_snapshot` remains immutable history. A new
`pi_eod_live_pointer(dataset, entity_key, as_of_session, job_run_id,
updated_at)` table is the sole authority for LIVE resolution. Its composite
foreign key references one history row. `get_live()` performs one indexed
pointer join and never derives LIVE with `MAX(as_of_session)`.

Promotion accepts only a validated `status='ok'` staging row. In one
transaction it locks the candidate and pointer, changes the prior and target
history-state labels for audit compatibility, and upserts the pointer. A
partial, stale, or failed run remains history and cannot move the pointer.
Rollback receives an exact historical `(as_of_session, job_run_id)`, verifies
that it is a validated `ok` row for the same canonical key, and atomically
repoints LIVE. The pointer is authoritative if a compatibility state label and
the pointer ever disagree.

Schema version 2 adds the pointer and job tables. Existing version-1 databases
are migrated transactionally by seeding pointers from their unique
`state='live'` rows before the version stamp advances. New databases create
the version-2 schema directly. SQLite and MySQL retain their existing schema,
collation, transaction, and guard verification discipline.

## Provenance and payload contracts

`snapshot_input_hash(inputs, engine_version)` hashes deterministic JSON
containing both values. Orchestration uses only this helper, so unchanged data
under changed code never skips recomputation. `engine_version` and
`payload_schema_version` remain first-class columns and are required for new
orchestrated writes.

A `SnapshotDatasetRegistry` owns immutable `DatasetDefinition` records:
canonical dataset name, `pii_scoped`, current payload schema version, and
version-keyed payload decoders. `read_live_payload()` resolves the row, selects
the decoder by the stored version, and fails closed on an unknown version.
The core registers PII-free interface definitions for movers and scans, but no
consumer compute implementation.

## PII boundary and routing

`SnapshotStoreRouter` is the only orchestration-facing store selector.
PII-free datasets route to the shared store. A `pii_scoped` dataset routes only
to an explicitly configured user-local SQLite store; without one it is
refused. `MysqlSnapshotStore` also rejects direct writes for registered
PII-scoped datasets, providing defense in depth.

Every SQLite snapshot path is expanded, resolved, and checked by
`config._validate_outside_repo()` before directories or files are created.
Paths inside the repository are refused with `ConfigError`. Defaults remain in
the user's home data directory.

Job errors store only sanitized error categories, never exception messages.
Logs and EOD display metadata never include entity keys, account identifiers,
holdings, or dollar values.

## EOD session semantics

`snapshot.semantics` uses the XNYS calendar from `exchange_calendars`.
`last_completed_session(now)` compares the UTC instant to each real session
close, including early closes. Weekends and holidays therefore resolve to the
previous completed session.

Staleness is the count of completed XNYS sessions after `as_of_session`:

- 0: green
- 1: amber
- 2 or more, or no snapshot: red

The display contract always includes the exact disclaimer
`EOD planning snapshot — not a live/intraday quote`. It may include the
PII-free annotation `Reports before next open` when supplied by a consumer.
This issue provides the contract/helper only; wiring individual widgets remains
in the consumer issues.

## Standalone orchestration

`python -m openbb_techtrade.snapshot.refresh --dataset <name>` is a main-thread
entry point. Dataset compute adapters are injected or discovered separately;
the core runner accepts an entity-key source and a per-key compute callable.

Before compute, `start_job()` atomically enforces one running job per dataset.
A second fresh run is refused. A run older than two hours is marked failed
with a generic `stale_reclaimed` code and replaced. Every accepted run gets a
`snapshot_job` row and always finishes as `succeeded`, `partial`, or `failed`
with accurate counts.

Per-key failures are written to `snapshot_job_error` with a sanitized category.
`retry_failed()` reads only those entity keys, recomputes only that set, and
promotes only after all failures recover. A still-partial retry leaves the
existing LIVE pointers unchanged.

## Error handling and tests

- Schema mismatch, unsafe paths, unknown datasets/schema versions, and PII
  routing violations fail closed.
- Expected lifecycle refusals are typed and do not become database-connection
  errors.
- Tests cover SQLite and the existing PyMySQL-shaped double: version-1
  migration, pointer reads, rollback, partial invisibility, version-sensitive
  hashes, schema dispatch, targeted retry, single flight and stale reclaim,
  bookkeeping, PII routes, and XNYS weekend/holiday/early-close semantics.
- A real-path harness uses synthetic public rows and an outside-repository
  SQLite database. It exercises stage, promote, rollback, orchestration, retry,
  reopen, and display metadata without credentials or personal data.

## Scope boundary

This change does not implement movers, scan, signals, portfolio widgets, or
other dataset fan-out. It ships only the generic store, registry, semantics,
orchestration interfaces, and the tests/harness needed to prove the core.
