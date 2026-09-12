# FMP Cached Request-Scoped Database Override

## Scope

Fix #2051 so the position-history and ETF-holdings warmers use their explicit
`database` argument for every `fmp_cached` cache read, initialization, and write.
The jobs adapters remain unchanged: they intentionally expose no database
override and continue using process configuration.

## Considered approaches

1. **Make `DB_NAME` override user settings.** Small, but mutates process-global
   configuration and is unsafe when concurrent jobs target different databases.
2. **Add a database parameter to every cached fetcher helper.** Explicit, but
   cross-cuts the provider's entire model surface and is disproportionate to the
   two callers.
3. **Request-scoped database context (chosen).** A `ContextVar`-backed context
   manager selects a database at the provider's connection boundary. The
   warmers enter the scope around each provider operation. Existing callers
   without an override retain the singleton configured pool.

## Design

`openbb_fmp_cached.utils.database` will expose a validated
`database_override(name)` context manager. Within its scope,
`get_connection_pool()` returns a connection manager whose copied connection
parameters use `name`; it never mutates the process-wide pool or environment.
Nested scopes restore the prior value, and concurrent async contexts remain
isolated.

The position-history warmer will pass `database` through `fetch_history` into
its default per-symbol fetcher, which wraps gap analysis, cache writes, and the
final cache read in the override scope. Injected test/job fetch functions retain
their current signature.

The ETF warmer will pass `database` through `refresh_universe` into
`refresh_one_etf`, which wraps the real `obb.etf.holdings` call. Injected
holdings functions run inside the same scope, making the contract directly
testable without MySQL or network access.

## Validation

Tests will first demonstrate that an explicit database reaches provider writes,
that no override preserves configured behavior, and that nested/concurrent
scopes do not leak. Targeted unit tests, lint/format diagnostics, and an offline
real-path harness will then validate the final implementation.
