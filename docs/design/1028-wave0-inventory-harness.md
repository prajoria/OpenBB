# Design — Wave 0: Inventory + harness (#1028)

**Date:** 2026-07-22
**Author:** portfolio-team session
**Status:** DRAFT — for user approval before Phase 2
**Parent epic:** #844 · **Wave issue:** #1028
**Downstream waves:** #1029 (W1 Fundamentals) → #1037 (W9 Hardening) — 168 endpoint tasks total

## 1. Problem

The FMP-cached full-coverage epic (#844) organizes ~168 endpoint tasks across 9 downstream waves (#1029–#1037). Every one of those endpoint tasks currently repeats the same setup work:

1. Discover the FMP endpoint shape (URL, params, response fields).
2. Write a raw `openbb_fmp` live fetcher (Query + Data + Fetcher class + HTTP call).
3. Wrap it in an `fmp_cached` persistence layer (subclass + `aextract_data` read/write against a MySQL table).
4. Write the DDL for that table + register in both providers.
5. Write structural + fixture-replay tests, record a cassette, register with the coverage gate.

**Without a template + audit, each downstream task ships bespoke code**, drift accumulates fast, and reviewers cannot spot missing pieces.

## 2. What Wave 0 must ship

Per #1028's stated scope:

1. **Coverage audit extension** — the current `test_fetcher_dict_coverage.py` in `openbb_platform/providers/fmp_cached/tests/` audits fmp_cached only. Extend it to also audit `openbb_fmp` (75 models registered there today, some of which might not yet have `fmp_cached` wrappers or cassettes).
2. **Fetcher template** — a documented pattern (both a written spec + a small example) for the two-provider unit of work. Options:
   - **(A) Cookiecutter-style script** that scaffolds `openbb_fmp/models/<name>.py` + `openbb_fmp_cached/models/<name>.py` + DDL entry + test stub from a single `endpoint.yaml`.
   - **(B) Reference example** — pick one endpoint that lands in a downstream wave (e.g. `stock_peers` in W4, or something in W1 Statements), ship it as the canonical template, document what patterns to copy.
   - Recommendation: **B first (real reference), A later (nice-to-have)** — scaffolding without a proven pattern gets rewritten.
3. **Plan-limit normalization** — the shim/util that FMP's per-plan endpoint limits (Free / Starter / Premium / Ultimate) surface consistently in our code. Live discovery: yesterday's #955 drain showed 10 endpoints are permanently 402 on our tier. Codify this by adding an `_PLAN_LIMITED` allowlist next to `_KNOWN_UNCOVERED` with `{endpoint: {"tier": "Starter", "since": "2026-07-21"}}` so downstream waves know at manifest-write-time which endpoints won't record.
4. **Schema-version migration** — the `cache_schema.py` file already has a `create_all_flattened_tables()` iterator + `FLATTENED_TABLES` registry. Wave 0 needs to add a `schema_version` table that tracks which migrations have run, so downstream waves can add tables idempotently and a fresh install can bootstrap from empty.
5. **Fixture-replay test template** — the `@pytest.mark.record_http` pattern is already well-established (75 tests use it). Document the "one endpoint → one @record_http test → one cassette file → one allowlist entry" flow as a checked-in playbook (`docs/design/fmp-cached-endpoint-playbook.md`).

## 3. Scope for THIS PR (Wave 0 cut 1)

Because Wave 0 is a gate for 168 downstream tasks, over-engineering here delays everything. **Ship the smallest set of tooling that lets a downstream wave-task PR land in 1-2 hours** rather than 4-6.

**Minimum viable Wave 0:**

- [ ] **A1** — Extend `test_fetcher_dict_coverage.py` to cover `openbb_fmp` in addition to `fmp_cached`. Emits a report of gaps: (a) endpoints registered in fmp but NOT in fmp_cached, (b) endpoints registered in either but lacking a cassette.
- [ ] **A2** — Ship a `docs/design/fmp-cached-endpoint-playbook.md` that documents the two-provider unit of work end-to-end, using `FMPCachedAnalystRecommendationsFetcher` (#1022, just shipped) as the reference example. Downstream contributors read this before their first wave-task PR.
- [ ] **A3** — Add a `_PLAN_LIMITED` allowlist next to `_KNOWN_UNCOVERED` in `test_fetcher_dict_coverage.py`, seeded with the 10 permanent-402 endpoints identified in the #955 drain. A coverage-gate test asserts every entry cites a tier + a discovery date.
- [ ] **A4** — Add a `schema_version` table + a `record_migration(version: str)` helper in `cache_schema.py`. Not a wire-up-existing-tables migration (that's out of scope); just the mechanism so downstream wave DDL can `if not migration_ran("W1-statements-add-ttm-tables"): create_..._table(); record_migration(...)`.

**Explicitly deferred to Wave 0 cut 2 (separate PR):**

- Cookiecutter-style scaffolding script (#A5) — needs A2's playbook to stabilize first.
- Retro-migrating existing tables to use `schema_version` — hazardous on production data, needs its own design cycle.

## 4. Non-goals

- Wiring up any downstream-wave endpoints (that's what #1029–#1036 are for).
- Refactoring existing `fmp_cached` models to a new base class (churn without benefit; existing models work).
- A general-purpose "endpoint framework" — YAGNI until Wave 1 shows what commonality actually looks like.

## 5. Acceptance criteria

- [ ] Coverage gate now checks both providers; new report file `docs/reports/fmp-two-provider-coverage.md` regenerated on each test run
- [ ] Playbook doc committed under `docs/design/`
- [ ] `_PLAN_LIMITED` allowlist seeded from #955 findings with lint test enforcing (tier, discovery date) shape
- [ ] `schema_version` table + `record_migration` helper landed with unit tests
- [ ] All existing tests still pass (150 widget-backend + 40 fmp_cached tests must not regress)
