# TechTrade Snapshot Consumers Design

- **Status:** Approved for autonomous implementation
- **Issues:** #1968, #1969, #1942, #1943, #1944, #1945
- **Parent:** #1932
- **Target:** `portfolio`

## Purpose and success criteria

Finish the TechTrade EOD snapshot program by moving every data-bearing
Portfolio Intelligence widget onto `openbb_techtrade.snapshot`, the canonical
generic persistence layer delivered by #1963-#1967. Widget requests must perform
only bounded LIVE-pointer reads, return in under 500 ms, and never invoke market
data, scanning, validation, tuning, or simulation.

The first proving dataset is `techtrade.movers`, keyed by
`segment=<GICS>`. A post-close run stages every segment, applies dataset-specific
validation, and atomically publishes only a complete successful run. A partial
or rejected run records sanitized per-segment errors while every LIVE pointer
continues to serve the prior successful session.

The same contract then fans out to `scan`, `signals`, `plan`, `orders`,
`simulate`, `validate`, `tune`, and `audit`. All definitions are PII-free and
versioned. Every response exposes the exchange/session badge, trading-session
freshness, and the exact disclaimer
`EOD planning snapshot — not a live/intraday quote`. A cold store is loudly
empty and provides post-close job guidance.

## Approaches considered

1. **Generic adapters plus a legacy compatibility facade (selected).** Dataset
   adapters compute widget-ready payloads into `openbb_techtrade.snapshot`.
   Portfolio Intel reads that store directly. The old
   `openbb_techtrade.snapshots` API becomes a thin adapter over the generic
   tables, preserving callers without preserving a second database or LIVE
   algorithm.
2. **Dual-write generic and scan-specific stores.** This minimizes immediate
   edits but creates two authorities, divergent promotion semantics, and
   ambiguous recovery. Rejected.
3. **Delete the legacy API immediately.** This creates the cleanest tree but
   unnecessarily breaks existing imports and operational commands. Rejected in
   favor of a compatibility facade with one source of truth.

## Components and boundaries

### Dataset contracts

`snapshot.registry` registers all nine public datasets with
`pii_scoped=False`, schema version `1`, a versioned reader, and a
dataset-specific validator. Payloads use a shared envelope:

```text
{
  rows: [...],
  segment: <GICS>,
  as_of_session: YYYY-MM-DD,
  exchange_calendar: XNYS,
  earnings_symbols: [...],
  excluded_symbols: [...],
  survivorship: corrected | in-sample · survivorship-uncorrected
}
```

Validators require this envelope, reject all-null rows and non-positive price
fields, enforce monotonic row dates where present, and reject an implausible
row-count drop relative to the current LIVE row. Empty-but-valid results remain
representable when the compute completed honestly.

### Compute adapters and jobs

An adapter module owns production compute seams and JSON serialization; the
store remains unaware of TechTrade models. Movers calls the existing movers
engine once per segment. The fan-out adapters consume the existing
scan/signal/plan/validation/tuning surfaces and persist only widget-shaped,
public rows. Orders and simulation are materialized artifacts, not request-time
derivations.

The jobs extension exposes one post-close job per dataset and an all-datasets
fan-out job. Each handler runs the generic refresh orchestrator on the calling
main thread. Scheduled runs occur after the XNYS close. Retry remains targeted
through `snapshot_job_error`.

### Read model

Portfolio Intel depends only on the generic `SnapshotStore` protocol and
registry. Reads use explicit LIVE pointers. Segment widgets use a single key;
symbol widgets make a bounded pass over the eleven canonical segment keys and
filter already-materialized rows. No endpoint imports compute routers.

The compatibility implementation for `openbb_techtrade.snapshots` translates
its historical `ScanSnapshot` DTO to and from generic rows. It does not create,
query, or retain the old `scan_snapshot` table.

## Event risk and survivorship

The adapter contract accepts a first-class event-risk provider. Earnings report
dates force the affected symbol into the post-close refresh input and set the
display annotation. Delisted or halted symbols are excluded before validation;
their identifiers are recorded only in the public dataset payload. Event data
is part of the input hash, so changes cannot be mistaken for an unchanged run.

Historical membership is not yet available uniformly. Therefore
`validate`, `tune`, and `audit` fail closed to the required explicit label
`in-sample · survivorship-uncorrected` in both payload and widget display.
They may switch to `corrected` only when an adapter supplies as-of membership
with the same session and calendar.

Multi-exchange semantics are made explicit rather than inferred: every payload
stores `exchange_calendar`, every display names the calendar, and freshness is
calculated with that calendar. The initial adapters emit `XNYS`; future
non-US adapters can select their own calendar without changing storage schema.

## Error handling

- Compute and validation failures use sanitized categories; raw provider
  exceptions, credentials, and entity payloads never enter job errors.
- Any failed key prevents dataset publication for that run. Previously promoted
  LIVE pointers remain authoritative.
- Unknown datasets, schema versions, calendars, or malformed payloads fail
  closed.
- Missing LIVE data returns a deterministic loud-empty response, never a live
  fallback.

## Verification

Strict RED/GREEN/refactor tests cover registry privacy, validators, adapters,
event filtering, job definitions, compatibility storage, every widget shape,
fresh/stale/cold responses, and the sub-500 ms compute-free contract.

The Phase 6 real SQLite harness exercises:

1. successful Information Technology movers publish and read;
2. one forced segment failure preserving all prior LIVE pointers and recording
   the failed key;
3. all-null and implausible-row-count rejection preserving last-good;
4. empty-store widget reads without compute.

It also verifies each fan-out dataset, event-risk metadata, survivorship labels,
calendar-aware display, process reopen, and absence of credentials or personal
data.

## Scope

No intraday refresh or quote semantics are introduced. No account-scoped data
is persisted. Existing TechTrade compute algorithms are reused rather than
reimplemented, and unrelated Portfolio Intelligence widgets are unchanged.
