# Issue #97 — ETF Holdings Free Fallback Tier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Plan-file note (2026-06-27):** This plan exists as a **task index** and Phase-5..7 handoff guide. The detailed per-task implementation lives in the design spec (`docs/designs/etf_holdings/etf-holdings-free-fallback-tier.md`) which is the SSOT for L1–L9 + Q1–Q4 + the §"Tasks" checklist. The original full-fidelity plan was lost to a tool-edit accident mid-session; rather than re-derive 2000 lines of TDD steps before any code lands, the implementation proceeds inline against the design doc with each task's deliverables recorded in its beads close-reason.

**Goal:** Convert `fmp_cached`'s thin `etf_holdings` wrapper into a multi-tier fallback fetcher (cache → FMP API → issuer-file → SEC N-PORT) so `obb.etf.holdings(symbol=…, provider="fmp_cached")` returns real constituents on this checkout where FMP `EtfHoldings` returns `402 Restricted`. Fixes the downstream EURKR symptom in `obb.techtrade.scan`.

**Architecture:** Two independently shippable halves modeled on #89: (1) **read/fallback** — `FMPCachedEtfHoldingsFetcher` subclass (structure copied from `institutional_ownership.py`) with cache → FMP → issuer → N-PORT chain + a new `etf_holdings_cache` MySQL table; (2) **ingest** — `Tools/ingest_sec_nport.py` + `openbb_sec/utils/nport_index.py` quarterly bulk loader. Both halves normalize every tier to the standard `EtfHoldingsData` schema with a `data_source` provenance tag.

**Tech Stack:** Python 3.10–3.13, `requests` (no `aiohttp`), `openpyxl` for SSGA workbooks, MySQL via `openbb_fmp_cached.utils.database` helpers, SEC N-PORT bulk data sets (quarterly ZIP), State Street SSGA daily holdings files.

## Global Constraints (from design §0.1)

- **L1** Fallback lives inside `fmp_cached` only; no edit to consumers.
- **L2** Normalize EVERY tier to `EtfHoldingsData`; each row carries `data_source`.
- **L3** Fallback order: cache → FMP API → issuer-file → SEC N-PORT.
- **L4** `requests` only (no `aiohttp`); descriptive UA `OpenBBTechnical/etf-holdings/0.1`.
- **L5** N-PORT delivery is bulk-ingest once per quarter into MySQL.
- **L6** Issuer registry is a small `ETF → (url, parser)` table, seeded with 11 SPDRs.
- **L7** Reuse `openbb_fmp_cached.utils.database`; new tables `CREATE TABLE IF NOT EXISTS`.
- **L8** Persist in a NEW `etf_holdings_cache` table (the existing `etf_holdings` table is OHLCV-shaped — schema mismatch we leave alone). TTL by source: issuer 1d, N-PORT 30d, FMP 1d.
- **L9** No emoji, `logging` not `print` in libraries, type hints, idempotent ingest.
- **Codebase conventions:** Ruff line-length 122; tests offline; apply the #93 review-lesson stack — `load_dotenv` at module top of any new Tools/ script, `--database` plumbed via `os.environ["DB_NAME"]`, Windows-console `errors="replace"` + stderr, `contextlib.suppress`.
- **Venv:** all test/dev commands use `.venv_win\\Scripts\\python.exe`.

---

## Files

| File | Disposition | Lines (approx) | Responsibility |
|---|---|---:|---|
| `openbb_platform/providers/sec/openbb_sec/utils/nport_index.py` | NEW | ~380 | DDL + `init_nport_index()` + read/write helpers (mirrors `thirteen_f_index.py`) |
| `openbb_platform/providers/sec/tests/test_nport_index.py` | NEW | ~350 | ~10 offline tests |
| `Tools/ingest_sec_nport.py` | NEW | ~420 | Quarterly bulk loader (download → stream-parse TSV → batched upserts) |
| `Tools/tests/test_ingest_sec_nport.py` | NEW | ~150 | ~5 offline tests (normalize_period, parser shape, dry-run no-op) |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/etf_holdings_issuer.py` | NEW | ~260 | `ISSUER_REGISTRY` (11 SPDRs) + `fetch_issuer_holdings` + `_parse_ssga_xlsx` |
| `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_issuer.py` | NEW | ~280 | ~12 tests using a synthetic fixture XLSX |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/etf_holdings.py` | MODIFY (full rewrite from 10 LoC stub) | ~280 | `FMPCachedEtfHoldingsFetcher` subclass with `aextract_data` chain + cache helpers + `_try_fmp`/`_try_issuer`/`_try_nport`/`transform_data` |
| `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_fallback.py` | NEW | ~350 | ~8 chain tests (cache hit, FMP 402 → issuer, issuer empty → N-PORT, all-empty → []) |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/utils/cache_schema.py` | MODIFY | +30 | Add `create_etf_holdings_cache_table` + registry entry |
| `Tools/docs/specs/ingest_sec_nport.md` | NEW | ~90 | Per-tool spec |
| `Tools/docs/DESIGN.md` | EDIT | +~25 | Inventory + §10 changelog + §4 schemas |
| `docs/designs/etf_holdings/etf-holdings-free-fallback-tier.md` | EDIT (status) | +~10 | Mark Q1/Q2 resolved + status → "implemented" |

---

## Task index (detailed steps in the design doc §Tasks + applied as TDD inline)

### T1 — Spike (no code)
Run the live HTTP probes documented in design §"Task 1": fetch one SSGA `.xlsx` for XLK (record URL, sheet name, header row, column names) and download one small slice of a recent N-PORT quarter (record TSV filenames + columns). Commit the findings into the design doc as §0.4 "Resolved (post-spike)".

### T2 — `nport_index.py` (read half)
Module with `DDL_FUND_MAP`, `DDL_HOLDINGS`, `DDL_INGEST_RUNS`, `ALL_DDL`, `SOURCE_NPORT_BULK`, lazy `_db()`, `init_nport_index()`, `fund_for_ticker(ticker) -> dict | None`, `holdings_for_fund(cik, period=None) -> list[dict]`. All graceful on DB error. Write half (`upsert_*`, `record_ingest_run`) stubbed; implemented in T3. ~10 unit tests.

### T3 — Write helpers + `Tools/ingest_sec_nport.py`
Implement `upsert_fund_map` (6-tuple), `upsert_holdings` (9-tuple), `record_ingest_run`. Create `Tools/ingest_sec_nport.py` with `--period --database --dry-run --limit --max-runtime -v` flags; download ZIP, stream-parse SUBMISSION + HOLDINGS TSVs (joining accession→fund), batched upserts at 2000 rows. Apply #93 review-lesson stack. ~5 CLI tests.

### T4 — Issuer-file tier
`etf_holdings_issuer.py` with `IssuerSpec(url, parser, issuer_id)` NamedTuple, `_parse_ssga_xlsx(content, *, ticker)` (skips cash/dash rows, normalizes weight to fraction), `ISSUER_REGISTRY` seeded with all 11 SPDRs (`XLB/XLC/XLE/XLF/XLI/XLK/XLP/XLRE/XLU/XLV/XLY`) using the spike-confirmed `holdings-daily-us-en-<ticker>.xlsx` URL template, `fetch_issuer_holdings(symbol, *, http=requests)` returning dict rows with `data_source="issuer_ssga"`. Never raises. Fixture-XLSX-based unit tests (~12 tests).

### T5 — Wire chain into `FMPCachedEtfHoldingsFetcher`
Add `create_etf_holdings_cache_table` to `cache_schema.py` (new `etf_holdings_cache` table — distinct from the pre-existing OHLCV-shaped `etf_holdings`). Full rewrite of `etf_holdings.py`: `TTL_BY_SOURCE = {"fmp": 1d, "issuer_ssga": 1d, "sec_nport": 30d}`, `_get_cached_etf_holdings`/`_store_etf_holdings` (delete-then-insert per `(etf, data_source)`), `_try_fmp`/`_try_issuer`/`_try_nport` (each returns `[]` on any error), `FMPCachedEtfHoldingsFetcher` subclass with `aextract_data` implementing the L3 chain + `transform_data` tolerating missing fields. ~8 chain tests.

### T6 — Rebuild + integration + notebook regression
`openbb.build()` → live `obb.etf.holdings('XLK')` smoke (expect `data_source="issuer_ssga"`, 70-80 rows) → cache-hit verification (second call ≪ first) → multi-ETF distinct-top-5 check (XLK/XLF/XLE/XLV) → `obb.techtrade.scan` regression (asserts not `EURKR`-degenerate). Record evidence in `Tools/docs/runs/2026-06-27-etf-holdings-fallback-bounded.md`.

### T7 — Docs
`Tools/docs/specs/ingest_sec_nport.md` (mirror `ingest_sec_13f.md` house style); `Tools/docs/DESIGN.md` inventory row + §10 changelog block + §4 Table Schemas for `nport_*`; `docs/designs/etf_holdings/etf-holdings-free-fallback-tier.md` status → "implemented" + Q1/Q2 resolved.

---

## Phase-5..Phase-7 handoff (openbb-dev-cycle)

After T7 closes:
- **Phase 5 (Quality):** invoke `simplify` over the 4 new source files. Run full SEC + fmp_cached + Tools test suite for evidence-before-completion.
- **Phase 6 (Review):** invoke `/code-review` skill on PR. Apply review fixes on `fix/97-review-feedback` branch off feat (same shape as #93/PR #95). The lessons-already-applied list should leave only spec-level findings.
- **Phase 7 (Integration):** PR `feat/97-etf-holdings-free-fallback-tier → trading_technicals`; comment on issue #97; merge after review; close beads + `bd remember`.

---

## Beads

- Parent: `OpenBBTechnical-f6j` (filed pre-design)
- Children (T1-T7) filed at Phase 2 entry of execution.
