# MySQL Positions Store — Decision Record + Design (#1744)

**Date:** 2026-08-02
**Status:** Accepted — PR pending
**Reverses:** `docs/superpowers/specs/2026-07-18-portfolio-snapshot-importer-design.md` §13 [Q1], [Q5]

## Context

Portfolio Intelligence today has **two divergent stores for the same
Fidelity CSV data**:

- **SQLite** (`~/.portfolio_importer/positions.db`) via
  `openbb_platform/tools/portfolio_snapshot_importer/`.
- **MySQL** (`openbb_fmp_cache_test.Portfolio_Positions` +
  `portfolio_basket`) via
  `openbb_platform/tools/portfolio_utils/parse_fidelity_positions.py`.

The widget-backend at
`extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets_endpoints.py:2074`
returns HTTP 422 for any non-demo `basket_id`, pointing at #1714 which
was blocked on this decision. Downstream, this blocks Phase 2B of
#1715 (16 basket-consuming endpoints).

Filing #1744 forced the choice. The prior spec's [Q1] "SQLite for
portability" and [Q5] "punt the store abstraction" decisions were made
in isolation — together they cemented the two-store drift.

## Decision

**MySQL `openbb_fmp_cache_test` is the canonical positions store.**
SQLite is optional-offline only.

Two new **additive** tables:

- `pi_snapshot` — mirrors the SQLite `snapshot` shape (10 cols),
  `UNIQUE(source_sha256, user_id)` for idempotence.
- `pi_position` — mirrors the SQLite `position` shape (21 cols), FK to
  `pi_snapshot`, indexed by `(snapshot_id)`, `(snapshot_date, user_id,
  symbol)`, `(snapshot_date, user_id, account_number)`.

The corporate `Portfolio_Positions` / `portfolio_basket` pipeline is
**not touched**. The `pi_*` prefix keeps the boundary explicit.

## Design

### PortfolioStore Protocol

`store.py` now exposes:

- `PortfolioStore` — a `Protocol` with 8 methods (`snapshot_exists`,
  `insert_snapshot`, `insert_positions`, `list_snapshots`,
  `positions_for`, `latest_snapshot`, `transaction`, `close`).
- `SqlitePortfolioStore` — the original class, renamed. Behavior
  unchanged.
- `get_default_store(prefer=None, sqlite_path=None)` factory —
  precedence:
  1. Explicit `prefer` arg.
  2. `PI_PORTFOLIO_STORE` env var (`mysql|sqlite`).
  3. Default `mysql`.
  On MySQL failure without explicit opt-in, falls back to SQLite with a
  WARNING log.

`MySqlPortfolioStore` in `mysql_store.py` implements the same Protocol.
Backed by
`openbb_fmp_cached.utils.database.DatabaseConfig.get_connection_pool()`.
Idempotency via `INSERT IGNORE`.

### Backfill

New CLI subcommand:

```bash
portfolio-snapshot-import backfill-to-mysql --from ~/.portfolio_importer/positions.db [--dry-run] [--user-id ID]
```

Idempotent one-shot. `INSERT IGNORE` on `pi_snapshot`; per-snapshot
positions loop.

### Consumer wiring

- `ingest.py`, `basket_bridge.py` — parameter types tightened to the
  Protocol (no behavior change).
- `cli.py` — new `--store {mysql,sqlite}` global flag + `backfill-to-mysql`
  subcommand. Existing `--db` path stays for SQLite fallback.
- Widget backend — **not** touched here. #1714 wires
  `pi_equity_basket_analyst_consensus` and Phase 2B endpoints to the
  MySQL-backed store in a separate cycle.

## PII posture

The existing `mask_account_number()` at
`parse_fidelity_positions.py:157` (last-4-digit mask) is retained.
`account_number` is stored as `****1234`, never raw. No salted-hash
upgrade needed because the raw value is never persisted in either
store.

## Tests

- **`test_mysql_store.py`** (14 tests) — every method against a
  SQLite-backed fake pool. Fast, no live DB.
- **`test_portfolio_store_protocol_parity.py`** (12 tests, 6 × 2
  backends) — same contract tests run against both `SqlitePortfolioStore`
  and `MySqlPortfolioStore(fake_pool)`. Loud proof of interchangeability.
- **`test_backfill.py`** (7 tests) — copy semantics, idempotence,
  dry-run, user-id filter, CLI wiring.

Live-MySQL integration tests are deferred until we have a shared
credential/DB provisioning story (there are no `@pytest.mark.integration`
DB tests anywhere in `portfolio_utils/` today either — the pattern
doesn't exist yet in this repo).

## Non-goals

- Do not modify `Portfolio_Positions` / `portfolio_basket`.
- Do not rewire widget-backend endpoints (that's #1714 / #1715 Phase 2B).
- Do not build a schema-migration framework. The additive `SHOW COLUMNS`
  pattern from `parse_fidelity_positions.py:1097` is enough for two
  tables.

## Follow-ups

- **#1714** — unblocked. Next PR wires the widget backend against
  `MySqlPortfolioStore`, removes the 422 gate at
  `widgets_endpoints.py:2074`.
- **#1715 Phase 2B** — 16 basket-consuming endpoints route through
  `ChainedFetcher` once #1714 lands.
- **SQLite retirement** — after 30 days of MySQL-primary running,
  file a follow-up to require `--store sqlite` explicit opt-in.
