# MCP cache-job operator runbook

This runbook covers the operator boundary introduced in T29-T30. Use the
[Portfolio MCP operator runbook](./portfolio-mcp.md) for profile setup,
authentication, controlled restart, exact-PID rollback, and general
troubleshooting.

## Preconditions

- Select the `portfolio-ops` runtime and capability profiles.
- Configure nonblank `OPENBB_MCP_SERVER_AUTH`.
- Explicitly set `OPENBB_MCP_ENABLE_MAINTENANCE_OPERATIONS=true`.
- Install the checkout-local `openbb-portfolio-utils` job extension.
- Run a separate OpenBB jobs worker. MCP only persists queued work; it never
  executes a handler in the request process.

Read and standard profiles do not expose cache-job tools. Authentication is
required before the original `JobService` dependency is returned.

## Allowed operations

- List the two definitions: `portfolio.position_history` and
  `portfolio.etf_holdings`.
- Read aggregate worker/queue health.
- Read a durable run by its returned run ID.
- Enqueue either allowlisted definition with its typed parameters and an
  optional bounded idempotency key.

Idempotency keys are namespaced by job. Reusing a key for the same job returns
the same durable run; a cross-job collision is rejected.

## Recovery

Run IDs and queue state are stored in the core SQLite job store and remain
queryable after MCP or worker restart. An absent worker is reported in health;
it is not presented as successful execution. Partial item failures are retained
as bounded warnings on the durable job result.

## Deliberately unavailable

- No arbitrary job name, script, SQL, cron, or worker execution endpoint.
- No raw table or endpoint invalidation.
- No MCP cancellation endpoint. Core queued-only cancellation semantics remain
  unchanged, and running work is never advertised as cancellable.
- No API keys, database names, credentials, or dry-run overrides in persisted
  job parameters.

Any expansion after this baseline requires a new exact policy/catalog entry, typed
parameters, original service authentication, durable-run evidence, and
separate review of mutation and cancellation semantics.

If `cache_health` reports `unavailable` or `permission_denied`, repair
least-privilege database connectivity before enqueueing work. Do not use raw
SQL, reveal connection details, or reinterpret an unavailable database as an
empty cache.
