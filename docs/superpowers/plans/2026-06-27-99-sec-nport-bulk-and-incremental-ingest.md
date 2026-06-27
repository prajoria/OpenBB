# Issue #99 — SEC N-PORT Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Plan-shape note (2026-06-27):** This plan is a **task index** that points at the refined design spec (`docs/designs/etf_holdings/99-sec-nport-bulk-and-incremental-ingest.md`) for per-section detail. The design doc is the SSOT for L1–L12 + Q-A through Q-E + §2.3 fund_map spec + §3 acceptance criteria. Each task below cites the exact design-doc section that defines its contract. Per-task TDD steps (Red→Green→Refactor→Commit) follow the project's established pattern from #93 / #97 / refresh_etf_holdings_cache; the executor adds the per-step verbatim test code inline as they work — exactly as the prior 4 features were built.

**Goal:** Un-park #97's deferred T2+T3 — build the SEC Form N-PORT-P ingest (bulk historical + per-CIK incremental) into the MySQL schema specified in design §2.3 + §0.2 Q-B, so `fmp_cached`'s `_try_nport` stub (today returns `[]`) becomes a real DB read returning N-PORT-sourced holdings for any registered fund covered by the index.

**Architecture:** Two ingest routes (bulk quarterly ZIP via Q-A A1 URL-discovery scraping the SEC data-sets page; per-CIK incremental via submissions API + accession archive) → one parser (`nport_parser.py`) → one schema (4 MySQL tables: filings, holdings, fund_map, ingest_runs) → one read helper (`nport_index.holdings_for_fund(ticker|cik, asof)` enforcing L10 as-of + L11 amendment supersession) → consumed by `fmp_cached._try_nport` to fill the #97 chain's third tier.

**Tech Stack:** Python 3.10–3.13, `requests` only (no `aiohttp` — L3), stdlib `html.parser` (no `beautifulsoup4`), stdlib `zipfile` + `tempfile` (G6 download-to-temp pattern), MySQL via `openbb_fmp_cached.utils.database` in the `openbb_fmp_cache_test` DB (L4), `requests_mock` for HTTP-tier tests, fixture XML/HTML/ZIP files for parser/discovery tests.

## Global Constraints

Copied verbatim from `docs/designs/etf_holdings/99-sec-nport-bulk-and-incremental-ingest.md` §0.1:

- **L1** — 3 fetch routes (submissions API discovery; accession archive per-filing; bulk quarterly ZIP backfill)
- **L2** — Mandatory `User-Agent: <entity> <contact-email>` on every `sec.gov`/`data.sec.gov` request; resolved from `user_settings.json credentials.sec_user_agent` or `SEC_USER_AGENT` env; **missing config → fast hard error**, never silent 403
- **L3** — `requests` only (no `aiohttp`); session reuse; `Accept-Encoding: gzip`; honor `Retry-After`. Prefer extending the existing SEC HTTP helper if shared by #89/#93 (this plan: no — `helpers.py` uses `aiohttp`, distinct path; `sec_http.py` is genuinely new)
- **L4** — 4 new MySQL tables in `openbb_fmp_cache_test` (same DB as `sec_13f_cusip_map` for cross-table CUSIP joins): `sec_nport_filings`, `sec_nport_holdings`, `sec_nport_fund_map`, `sec_nport_ingest_runs`. DDL `IF NOT EXISTS`, single source of truth in `nport_index.py` (mirror `thirteen_f_index.py`)
- **L5** — Filings keyed on `(accession_number)`; holdings keyed on `(accession_number, holding_key)` where `holding_key = COALESCE(cusip, isin, lei, sha1(issuer_name||asset_category))` + `_lotN` collision suffix (G4); bulk loader restart-safe via `sec_nport_ingest_runs.last_accession_seen` (G6)
- **L6** — Store every identifier the filing carries; never copy a licensed master; CUSIP→ticker via `sec_13f_cusip_map`; ISIN→ticker via extended `openfigi.py` (Q-E E1, separate small PR)
- **L7** — No fuzzy issuer matching anywhere
- **L8** — `source ∈ {sec_nport_bulk, sec_nport_submissions, sec_nport_archive}` + `ingested_at` + `accession_number` on every row
- **L9** — Provider `_try_nport` does pure DB reads; ingest is offline batch via `Tools/`
- **L10** — `holdings_for_fund(ticker|cik, asof=None)` returns rows from the latest accession where `report_date ≤ asof`; `asof=None` means "today"
- **L11** — `NPORT-P/A` supersedes prior `NPORT-P` for the same `(cik, series_id, period)`; `is_amendment` flag on filings; latest accession wins per period
- **L12** — `report_date` + `data_age_days` on every `holdings_for_fund` row; `transform_data` propagates `report_date` into `EtfHoldingsData.updated`
- **#93 review lessons (apply to all new `Tools/` scripts):** `load_dotenv` at module top; `--database` plumbed via `os.environ["DB_NAME"]` before any `_db()` call; Windows-console `errors="replace"` on both std{out,err} with `sys.platform == "win32"` guard; `contextlib.suppress` instead of bare `try/except/pass`; `transactional_upsert_*` pattern (or `executemany` if rowcount is sufficient) — see `Tools/enrich_cusip_figi.py` for the reference template
- **Venv:** `.venv_win\Scripts\python.exe` for all test/dev commands

## File Structure

Mirrors design §2.1 verbatim:

| File | Disposition | Lines (approx) | Responsibility | Design ref |
|---|---|---:|---|---|
| `openbb_platform/providers/sec/openbb_sec/utils/sec_http.py` | NEW | ~150 | L2/L3 chokepoint: `get(url, **kw)` + `post(url, json, **kw)` with mandatory User-Agent (resolved per L2), session reuse, `Retry-After`, gzip. Hard-error at startup if no UA configured. | §2.1, L2/L3 |
| `openbb_platform/providers/sec/tests/test_sec_http.py` | NEW | ~180 | UA presence enforced, missing-config raises, 403/429/Retry-After handled, gzip negotiated. All `requests_mock`. | §2.1 |
| `openbb_platform/providers/sec/openbb_sec/utils/nport_index.py` | NEW | ~600 | DDL for the 4 tables (filings, holdings, fund_map, ingest_runs); `init_nport_index()`; write helpers (`upsert_filing`, `upsert_holdings`, `upsert_fund_map`, `record_ingest_run`, `record_resume_cursor`); read helpers (`fund_for_ticker(ticker)`, `holdings_for_fund(ticker_or_cik, asof=None)` enforcing L10+L11, `latest_period_for_fund(cik, series_id)`); `SPDR_FUND_MAP` seed dict (per §2.3). | §0.1 L4/L5/L10/L11, §0.2 Q-B Resolution, §2.3 |
| `openbb_platform/providers/sec/tests/test_nport_index.py` | NEW | ~400 | DDL roundtrip; upsert idempotency (re-run = 0 net new); read helpers graceful on empty; **L10 as-of test**; **L11 amendment-supersession test**; seed-map population; `is_uit` flag flow. | §3 ACs |
| `openbb_platform/providers/sec/openbb_sec/utils/nport_parser.py` | NEW | ~350 | Pure parser: `parse_submission_envelope(raw_bytes) -> NportFiling + list[NportHolding]`. Splits `<SEC-DOCUMENT>` envelope, finds `<TYPE>NPORT-P</TYPE>` block, decodes XML. **Derives `holding_key` per G4** (`COALESCE(cusip, isin, lei, sha1(...))` + `_lotN` for same-issuer-multiple-lots). Detects `is_amendment` from form type. No HTTP, no DB. TypedDicts match §0.2 Q-B schema. | §2.1, §0.2 Q-B, G4, G5 |
| `openbb_platform/providers/sec/tests/test_nport_parser.py` | NEW | ~450 | Fixture-driven: representative NPORT-P (ETF + mutual fund + derivative-heavy fund) + NPORT-P/A amendment + edge cases (no CUSIP, ISIN-only, free-text ticker, same-issuer-multiple-lots collision). | §3 ACs |
| `openbb_platform/providers/sec/openbb_sec/utils/bulk_url_discovery.py` | NEW | ~120 | Q-A A1: `discover_quarter_zips() -> dict[str, str]` — GETs the SEC data-sets HTML page via `sec_http.py`, parses with stdlib `html.parser`, returns `{"2026Q1": "https://www.sec.gov/files/...zip", ...}`. **Raises `BulkDiscoveryEmpty` loudly on zero rows** (the #97 silent-empty regression guard). | §0.2 Q-A Resolution |
| `openbb_platform/providers/sec/tests/test_bulk_url_discovery.py` | NEW | ~150 | Fixture: saved copy of the actual SEC data-sets HTML response. Tests: parses ≥1 quarter; **asserts raises on zero-row fixture**; tolerates whitespace/encoding variants. | §3 AC (regression guard) |
| `Tools/ingest_sec_nport.py` | NEW | ~700 | CLI: `--mode={bulk,incremental}` + flags per §2.1. **Bulk mode** (G6): discover ZIP URL → download to temp → `ZipFile.open(member)` per member → stream rows in 2000-row chunks → upsert → resume cursor. **Incremental mode**: submissions API → archive per accession → parse → upsert. Apply #93 review-lesson stack. | §2.1, §2.2, G6 |
| `Tools/tests/test_ingest_sec_nport.py` | NEW | ~250 | CLI flag plumbing; `normalize_quarter` (`2026Q1` ↔ `2026-Q1`); dry-run no-op; resume-cursor write on chunk completion; SIGINT mid-batch leaves cursor at last completed chunk. | §3 ACs |
| `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/etf_holdings.py` | MODIFY | +30 | Replace stub `_try_nport` (currently `return []`) with real read via `nport_index.holdings_for_fund(symbol, asof=None)`. **L12**: propagate `report_date` into `EtfHoldingsData.updated`. No other change. | §2.1, L12 |
| `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_fallback.py` | MODIFY | +50 | Replace `test_try_nport_is_a_stub_until_t2_t3_land` (asserts empty) with new tests: `_try_nport` returns rows when index has data; `data_source="sec_nport"`; `updated` field carries `report_date`. | regression update |
| `openbb_platform/providers/sec/openbb_sec/utils/openfigi.py` | MODIFY (Task 7 / **separate small PR per Q-E**) | +80 | Add `idType` parameter to `map_cusips` (rename → `map_identifiers(id_values, *, id_type="ID_CUSIP", ...)` keeping old name as deprecated alias); add `map_isins(isins, ...)`; extend `select_match` ladder with exchange/currency tiebreak (prefer primary US listing, else composite FIGI). | §0.2 Q-E E1, design caveat |
| `Tools/enrich_nport_isin_tickers.py` | NEW | ~280 | Sibling to `Tools/enrich_cusip_figi.py`. Selects N-PORT holdings with ISIN AND `ticker IS NULL` AND `cusip IS NULL`, batches via extended OpenFIGI, upserts ticker. Never overwrites a non-null ticker (R6 app-side anti-join). Source-tag `openfigi_nport_isin`. | §2.1 |
| `Tools/tests/test_enrich_nport_isin_tickers.py` | NEW | ~200 | Mocked OpenFIGI; ISIN→ticker upserts; R6 anti-join (won't touch non-null ticker); empty-input no-op. | §3 ACs |
| `Tools/docs/specs/ingest_sec_nport.md` | NEW | ~120 | Per-tool spec (mirror `Tools/docs/specs/enrich_cusip_figi.md` house style). | §2.1 |
| `Tools/docs/specs/enrich_nport_isin_tickers.md` | NEW | ~80 | Per-tool spec (sibling to `enrich_cusip_figi.md`). | §2.1 |
| `Tools/docs/DESIGN.md` | EDIT | +~50 | Two new inventory rows (ingest_sec_nport + enrich_nport_isin_tickers) + §10 changelog block + §4 Table Schemas for the 4 new tables. | §2.1 |
| `docs/designs/etf_holdings/etf-holdings-free-fallback-tier.md` (the #97 design doc) | EDIT | +~15 | Update §0.2 Q2 (N-PORT URL discovery) status from "DEFERRED" → "RESOLVED (#99 / commit SHA)"; update §"Status" header to remove the "N-PORT deferred" qualifier; add cross-ref to #99 design doc. | §2.1, #97 un-park |

---

## Tasks

### Task 1 — `sec_http.py` chokepoint + tests

**bd:** `OpenBBTechnical-99-T1` (file at Phase-2 entry; blocked-by parent `f6j` ... wait, `f6j` is #97 closed. Use refinement bead `OpenBBTechnical-955` as the upstream gate marker → close it before T1 claim. Or use #99 parent directly — file `OpenBBTechnical-99-parent` at Phase 2 kickoff if no parent bead exists yet.)

**Files:**
- Create: `openbb_platform/providers/sec/openbb_sec/utils/sec_http.py`
- Create: `openbb_platform/providers/sec/tests/test_sec_http.py`

**Interfaces:**
- Consumes: `user_settings.json credentials.sec_user_agent` or env `SEC_USER_AGENT`; `requests.Session`
- Produces:
  - `get(url: str, *, params: dict | None = None, stream: bool = False) -> requests.Response` — raises `SecHttpConfigError` if no UA configured; honors `Retry-After`; gzip negotiated
  - `post(url: str, *, json: list | dict, **kw) -> requests.Response` — same UA discipline
  - `class SecHttpConfigError(RuntimeError)` — fast-hard-error sentinel for L2 violations
  - `_resolve_user_agent() -> str` — flag → env → user_settings → raise (mirrors `openfigi.resolve_credentials` shape)

**Steps (TDD):** Red test for `_resolve_user_agent` raising on missing config → implement → red test for `get()` setting UA header → implement → red test for 429 + `Retry-After` honoring (`requests_mock`) → implement → red test for gzip header → implement. Then ruff + commit.

**Reference for the test pattern:** `openbb_platform/providers/sec/tests/test_openfigi.py::test_resolve_credentials_*` series — same shape: `monkeypatch.setenv`, `patch("...._user_service_credentials")`, structured tuple/exception assertions.

**Done when:** All `sec_http.py` tests green; ruff clean; missing-UA test asserts `SecHttpConfigError` is raised at first `get()` call, not silently later.

**Commit shape:** `feat(sec/99): sec_http.py chokepoint — L2 User-Agent enforcement (T1)`

---

### Task 2 — `nport_index.py` schema + read helpers + SPDR seed

**bd:** `OpenBBTechnical-99-T2` (blocked-by T1)

**Files:**
- Create: `openbb_platform/providers/sec/openbb_sec/utils/nport_index.py`
- Create: `openbb_platform/providers/sec/tests/test_nport_index.py`

**Interfaces:**
- Consumes (from T1): nothing (this module is pure DB; T1 is needed by the ingest CLI in T5)
- Consumes (from existing code): `openbb_fmp_cached.utils.database` via lazy `_db()` (exactly the `thirteen_f_index._db()` pattern at `thirteen_f_index.py:120-128`)
- Produces (T3/T5/T6 consume):
  - **DDL constants** (all `IF NOT EXISTS`): `DDL_FILINGS`, `DDL_HOLDINGS`, `DDL_FUND_MAP`, `DDL_INGEST_RUNS`, `ALL_DDL` tuple
  - **Source enum**: `SOURCE_NPORT_BULK = "sec_nport_bulk"`, `SOURCE_NPORT_SUBMISSIONS = "sec_nport_submissions"`, `SOURCE_NPORT_ARCHIVE = "sec_nport_archive"`, `SOURCE_SEED = "seed"`, `SOURCE_OPENFIGI_NPORT_ISIN = "openfigi_nport_isin"`
  - **Seed dict** (per §2.3): `SPDR_FUND_MAP: dict[str, tuple[str, str, str, bool]]` keyed by ticker, value `(cik, series_id, fund_name, is_etf)`. 11 entries (XLB through XLY).
  - `init_nport_index() -> None` — runs `ALL_DDL` + seeds `sec_nport_fund_map` with `SPDR_FUND_MAP` rows (idempotent via L5 upsert)
  - `seed_fund_map(seed: dict | None = None) -> int` — like `thirteen_f_index.seed_cusip_map` at `thirteen_f_index.py:226-237`
  - **Write helpers** (all idempotent per L5):
    - `upsert_filing(row: tuple) -> int` — row = `(accession_number, cik, series_id, class_id, report_date, filing_date, is_amendment, source, ingested_at, raw_xml_url, raw_xml_sha256, raw_xml_blob_or_None)`
    - `upsert_holdings(rows: list[tuple]) -> int` — each row 13-tuple per §0.2 Q-B Resolution holdings schema
    - `upsert_fund_map(rows: list[tuple]) -> int` — row 8-tuple per §2.3 schema
    - `record_ingest_run(quarter: str, mode: str, source_zip_sha256: str | None, fund_count: int | None, holding_count: int | None) -> None`
    - `record_resume_cursor(quarter: str, member: str, last_accession_seen: str) -> None` — write to `sec_nport_ingest_runs.last_accession_seen` per G6
  - **Read helpers**:
    - `fund_for_ticker(ticker: str) -> dict | None` — returns `{"cik", "series_id", "fund_name", "is_etf", "is_uit"}` or `None` (graceful on DB error); uppercases input; UIT funds return the row (with `is_uit=True`) so the caller can decide; non-existent ticker returns `None`
    - `holdings_for_fund(ticker_or_cik: str, asof: date | None = None, series_id: str | None = None) -> list[dict]` — L10 + L11 semantics: resolves ticker→(cik, series_id) via `fund_for_ticker` if input looks like a ticker (uppercase alpha-only); queries `sec_nport_filings` for the **latest accession** where `report_date ≤ asof` (defaults to today) for that `(cik, series_id)`; joins `sec_nport_holdings`; returns rows with the L12-required `report_date` + `data_age_days` derived columns. Returns `[]` for unknown fund, UIT with no NPORT-P, or any DB error
    - `latest_period_for_fund(cik: str, series_id: str | None = None) -> str | None` — convenience helper for L12 staleness display

**Tests (writer-of-T2 produces, ~20 tests):**
1. `test_init_nport_index_runs_all_ddl_and_seeds_spdr_map` — `_db` patched, asserts all 4 CREATE TABLE statements fired + `sec_nport_fund_map` got 11 SPDR rows
2. `test_seed_fund_map_is_idempotent` — call twice, second call upserts same 11 rows (per L5)
3. `test_upsert_filing_rejects_wrong_tuple_shape` — 12-tuple is the canonical shape; 11-tuple raises `ValueError("upsert_filing row must be 12-tuple")`
4. `test_upsert_filing_idempotent_on_accession_pk` — same accession twice = same rowcount
5. `test_upsert_holdings_rejects_wrong_tuple_shape` — 13-tuple per Q-B; wrong → `ValueError`
6. `test_upsert_holdings_uses_content_derived_key_not_ordinal` — same `(cusip, isin, lei)` triple parses identical key across two calls (G4 regression guard)
7. `test_upsert_fund_map_idempotent_on_ticker_series_pk` — composite PK enforced
8. `test_record_ingest_run_appends_observability_row` — single INSERT
9. `test_record_resume_cursor_updates_last_accession_seen` — write fires per chunk (G6)
10. `test_fund_for_ticker_returns_seeded_xlk_row` — `fund_for_ticker("XLK")` returns `{cik="0000884394", series_id="S000004310", ...}` from seed
11. `test_fund_for_ticker_lowercases_input` — `"xlk"` resolves
12. `test_fund_for_ticker_returns_none_for_unknown` — `"BOGUS"` → `None`
13. `test_fund_for_ticker_returns_none_on_db_error` — `_db` raises → `None`
14. `test_holdings_for_fund_returns_latest_period_when_asof_none` — fixture with 2 filings (period 2025-Q3 + 2025-Q4); `asof=None` returns Q4 rows
15. **`test_holdings_for_fund_returns_period_at_or_before_asof`** (L10) — fixture with 2 filings (2025-Q3, 2025-Q4); `asof="2025-09-30"` returns Q3 rows only
16. **`test_holdings_for_fund_amendment_supersedes_original`** (L11 / G5) — fixture: original `NPORT-P` accession A then `NPORT-P/A` accession B for the same `(cik, series_id, period)`; query returns B's holdings, not the union
17. `test_holdings_for_fund_carries_report_date_and_data_age_days` (L12) — every returned row has both fields
18. `test_holdings_for_fund_uit_fund_returns_empty_with_log` — fund_map row has `is_uit=True` and no `sec_nport_filings` rows → `[]` (graceful, no exception)
19. `test_latest_period_for_fund_returns_max_report_date` — helper sanity
20. `test_holdings_for_fund_graceful_on_db_error` — DB raises → `[]`

**Reference for fakes:** `openbb_platform/providers/sec/tests/test_openfigi.py::fake_db` fixture pattern + `Tools/tests/test_enrich_cusip_figi.py::_fake_connection` for SELECT/INSERT mocking.

**Done when:** All ~20 tests green; ruff clean; the L10/L11 regression tests (#15, #16) specifically PASS — these are the G1 + G5 gap closures.

**Commit shape:** `feat(sec/99): nport_index.py — 4-table schema + read helpers + SPDR seed (T2)`

---

### Task 3 — `nport_parser.py` + fixtures + content-derived holding-key

**bd:** `OpenBBTechnical-99-T3` (blocked-by T2 for shared TypedDict imports)

**Files:**
- Create: `openbb_platform/providers/sec/openbb_sec/utils/nport_parser.py`
- Create: `openbb_platform/providers/sec/tests/test_nport_parser.py`
- Create: `openbb_platform/providers/sec/tests/fixtures/nport_p_etf_minimal.txt` (synthetic minimal `<SEC-DOCUMENT>` envelope with NPORT-P inside)
- Create: `openbb_platform/providers/sec/tests/fixtures/nport_p_a_amendment.txt` (amendment fixture for L11 test in T2)
- Create: `openbb_platform/providers/sec/tests/fixtures/nport_p_derivative_heavy.txt`
- Create: `openbb_platform/providers/sec/tests/fixtures/nport_p_no_cusip_isin_only.txt`
- Create: `openbb_platform/providers/sec/tests/fixtures/nport_p_same_issuer_multiple_lots.txt`

**Interfaces:**
- Consumes: T2's `holding_key` derivation rule (G4); the §0.2 Q-B Resolution schema TypedDict shapes
- Produces:
  - `class NportFiling(TypedDict, total=False)` — `accession_number, cik, series_id, class_id, report_date, filing_date, is_amendment, source, raw_xml_url, raw_xml_sha256`
  - `class NportHolding(TypedDict, total=False)` — `accession_number, holding_key, issuer_name, ticker, cusip, isin, lei, asset_category, units, value_usd, pct_nav, payoff_direction, derivative_flag`
  - `parse_submission_envelope(raw: bytes, *, accession_number: str, source: str) -> tuple[NportFiling, list[NportHolding]]` — main entry point; never raises (returns `(NportFiling{accession_number, ...}, [])` on parse failure with a logged warning)
  - `derive_holding_key(issuer_name: str | None, asset_category: str | None, cusip: str | None, isin: str | None, lei: str | None) -> str` — G4 content-derived key
  - `apply_lot_suffix(rows: list[NportHolding]) -> list[NportHolding]` — for same-key collisions within one filing, append `_lot2`, `_lot3`, … deterministically (sort by issuer_name then identifier presence for stability)
  - `class NportParseError(RuntimeError)` — only for unrecoverable structural failures (parser does NOT raise it for content gaps — those become empty fields)

**Tests (~15):**
1. `test_parse_minimal_etf_envelope_yields_filing_and_holdings` — fixture file 1; asserts NportFiling fields + ≥1 holding
2. `test_parse_extracts_cik_and_series_id_from_envelope` — verifies G1's fund-key extraction works
3. `test_parse_detects_amendment_from_form_type` — fixture file 2; `NportFiling.is_amendment is True`
4. `test_parse_handles_derivative_heavy_filing` — fixture file 3; `derivative_flag=True` on derivative rows
5. `test_parse_handles_isin_only_holding` — fixture file 4; `cusip=None, isin="US...."`, `holding_key` derived from ISIN
6. `test_derive_holding_key_prefers_cusip_when_present`
7. `test_derive_holding_key_falls_back_to_isin` — CUSIP=None → ISIN
8. `test_derive_holding_key_falls_back_to_lei` — CUSIP=None, ISIN=None → LEI
9. `test_derive_holding_key_falls_back_to_sha1` — none of CUSIP/ISIN/LEI → 16-char sha1 prefix of `issuer_name||asset_category`
10. `test_apply_lot_suffix_appends_lotN_to_collisions` — 3 rows with same (cusip, asset_cat) get `_lot2`, `_lot3` (the first stays bare)
11. `test_apply_lot_suffix_is_deterministic_across_parses` — same input order or different → same suffixes (sort by issuer_name then identifier-presence first)
12. `test_parse_same_issuer_multiple_lots_round_trip_with_apply_lot_suffix` — fixture file 5; final holdings have distinct holding_keys
13. `test_parse_invalid_envelope_returns_filing_with_empty_holdings_no_raise` — garbage bytes → `(NportFiling{accession_number=...}, [])` + WARNING log
14. `test_parse_envelope_carries_source_tag_through` — `source="sec_nport_bulk"` propagated to filing
15. `test_parse_extracts_report_date_for_l10` — `NportFiling.report_date` is a `date` object, not str

**Fixture file shape:** minimal NPORT-P envelopes built by hand from the SEC's published schema — small enough to be readable (~80 lines each), real enough to exercise the parser paths. Same approach as #93's synthetic SSGA XLSX fixture in `test_etf_holdings_issuer.py`.

**Done when:** All 15 parser tests green; ruff clean; L11 amendment fixture is in place ready for T2 test #16 to use.

**Commit shape:** `feat(sec/99): nport_parser.py — XML parse + G4 content-derived holding-key (T3)`

---

### Task 4 — `bulk_url_discovery.py` (Q-A A1 with raise-loudly guard)

**bd:** `OpenBBTechnical-99-T4` (blocked-by T1 for `sec_http`)

**Files:**
- Create: `openbb_platform/providers/sec/openbb_sec/utils/bulk_url_discovery.py`
- Create: `openbb_platform/providers/sec/tests/test_bulk_url_discovery.py`
- Create: `openbb_platform/providers/sec/tests/fixtures/sec_nport_data_sets_page.html` (saved real SEC HTML; ~50KB) + a `sec_nport_data_sets_page_empty.html` (the regression-guard fixture for the zero-rows case)

**Interfaces:**
- Consumes (from T1): `sec_http.get(url)` for the L2 User-Agent header
- Produces:
  - `discover_quarter_zips() -> dict[str, str]` — returns `{"2026Q1": "https://www.sec.gov/files/...zip", ...}`; raises `BulkDiscoveryEmpty` if zero rows parsed (the #97 silent-empty regression guard per Q-A Resolution)
  - `class BulkDiscoveryEmpty(RuntimeError)` — Q-A "raise loudly on zero rows" sentinel
  - `NPORT_DATA_SETS_URL = "https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets"`

**Tests (~6):**
1. `test_discover_quarter_zips_parses_real_html_fixture` — saved fixture → ≥1 quarter found
2. **`test_discover_quarter_zips_raises_on_empty_fixture`** — empty/re-org'd HTML → `BulkDiscoveryEmpty` (the #97 regression guard; ASSERT, not log)
3. `test_discover_quarter_zips_uses_sec_http_get_for_l2_compliance` — `patch("...sec_http.get")` assert called
4. `test_discover_quarter_zips_tolerates_extra_whitespace` — minor HTML variants
5. `test_discover_quarter_zips_returns_quarter_keys_in_yyyy_qn_format` — keys match `\d{4}Q[1-4]`
6. `test_discover_quarter_zips_url_values_are_https_sec_gov` — every returned URL hostname matches

**Done when:** Both fixtures shipped; test #2 (the raise-loudly guard) PASSES; ruff clean.

**Commit shape:** `feat(sec/99): bulk_url_discovery.py — Q-A A1 with raise-loudly empty guard (T4)`

---

### Task 5 — `Tools/ingest_sec_nport.py` (bulk + incremental modes)

**bd:** `OpenBBTechnical-99-T5` (blocked-by T1, T2, T3, T4 — this is the integration task)

**Files:**
- Create: `Tools/ingest_sec_nport.py`
- Create: `Tools/tests/test_ingest_sec_nport.py`

**Interfaces:**
- Consumes (from T1-T4): all of the above
- Produces: CLI only (no Python public API beyond `main()` returning exit code)

**CLI surface (from §2.1):**

```bash
.venv_win\Scripts\python.exe Tools/ingest_sec_nport.py --mode=bulk --quarter 2026Q1
.venv_win\Scripts\python.exe Tools/ingest_sec_nport.py --mode=bulk --quarter 2026Q1 --etf-only --dry-run
.venv_win\Scripts\python.exe Tools/ingest_sec_nport.py --mode=bulk --quarter 2026Q1 --limit 10
.venv_win\Scripts\python.exe Tools/ingest_sec_nport.py --mode=incremental --cik 0001064642  # XLK example
```

| Flag | Default | Meaning |
|---|---|---|
| `--mode` | required | `bulk` or `incremental` |
| `--quarter` | required for bulk | `YYYYQn` or `YYYY-Qn` |
| `--cik` | required for incremental | one CIK or comma-separated |
| `--etf-only` | off | filter to `sec_nport_fund_map.is_etf=TRUE` (depends on §2.3 seed) |
| `--limit` | none | cap distinct accessions ingested |
| `--sleep` | 0.0 | extra sleep between batches |
| `--dry-run` | off | plan only, no DB writes |
| `--database` | from `DatabaseConfig` | sets `DB_NAME` env (mirrors #93 review-lesson) |
| `--with-raw` | off | populate `sec_nport_filings.raw_xml_blob` (Q-B) |
| `--max-runtime` | 7200 | hard cap (CI safety) |
| `-v / --verbose` | off | DEBUG logging |

**Module structure (mirror `Tools/enrich_cusip_figi.py` skeleton):**
1. Top-of-file: encoding fix + `load_dotenv` + sys.path bootstrap (apply #93 review-lesson stack verbatim)
2. `normalize_quarter(q: str) -> str` — `2026Q1` ↔ `2026-Q1`; raise `ValueError` on garbage
3. `def bulk_mode(args) -> dict` — Q-A discover → per-quarter download to `tempfile.NamedTemporaryFile(suffix=".zip")` → `ZipFile.open(member)` → 2000-row chunks → `upsert_filing` + `upsert_holdings` per chunk → `record_resume_cursor` after each chunk (G6) → `record_ingest_run` at end. Returns stats dict
4. `def incremental_mode(args) -> dict` — for each CIK: GET submissions API → filter to NPORT-P / NPORT-P/A accessions not yet in `sec_nport_filings` → for each: GET accession archive → `parse_submission_envelope` → `upsert_filing` + `upsert_holdings`. Returns stats dict
5. `def main() -> int` — argparse, banner, dispatch on `--mode`, summary banner

**Tests (~10):**
1. `test_normalize_quarter_handles_compact_and_dashed_forms`
2. `test_normalize_quarter_rejects_garbage_input`
3. `test_main_dispatches_to_bulk_mode` — `--mode=bulk --quarter 2026Q1 --dry-run`; mocked discoverer + parser; asserts `bulk_mode` called, not `incremental_mode`
4. `test_main_dispatches_to_incremental_mode` — `--mode=incremental --cik 1234`; same shape
5. `test_main_database_flag_sets_db_name_env` — same regression-guard pattern as `test_enrich_cusip_figi::test_main_sets_db_name_env_when_database_flag_given`
6. `test_bulk_mode_writes_resume_cursor_per_chunk` — mocked `ZipFile.open` returns fake rows; `record_resume_cursor` called once per 2000-row chunk
7. `test_bulk_mode_resumes_from_cursor_on_retry` — `_get_resume_cursor` mocked to return `last_accession_seen="A-50"`; assert `upsert_holdings` skips accessions ≤ A-50
8. `test_bulk_mode_etf_only_filters_via_fund_map` — `--etf-only`; mock `sec_nport_fund_map.is_etf` rows; assert non-ETF rows skipped
9. `test_incremental_mode_skips_already_ingested_accessions` — `sec_nport_filings` fake says accession A is present; submissions API returns A+B; assert only B is fetched
10. `test_dry_run_does_not_call_upsert` — same as `test_enrich_cusip_figi::test_main_dry_run_does_not_write`

**Done when:** CLI `--help` shows all 11 flags; `--mode=bulk --quarter 2026Q1 --dry-run` runs end-to-end with mocked discoverer (no live SEC call); ruff clean.

**Commit shape:** `feat(tools/99): ingest_sec_nport.py — bulk + incremental modes (T5)`

---

### Task 6 — Wire real `_try_nport` in `fmp_cached/etf_holdings.py`

**bd:** `OpenBBTechnical-99-T6` (blocked-by T2 for the read helper)

**Files:**
- Modify: `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/etf_holdings.py` (lines 136-143 — the current stub)
- Modify: `openbb_platform/providers/fmp_cached/tests/test_etf_holdings_fallback.py` (replace `test_try_nport_is_a_stub_until_t2_t3_land`)

**Interfaces:**
- Consumes (from T2): `nport_index.holdings_for_fund(symbol, asof=None)` returning the L12 dict shape

**Diff sketch** (replacing the stub):

```python
async def _try_nport(symbol: str) -> list[dict]:
    """SEC N-PORT tier (live as of #99). Returns [] for unknown fund or empty index."""
    try:
        from openbb_sec.utils.nport_index import holdings_for_fund  # noqa: PLC0415
        # asof=None means "today" per L10
        return await asyncio.to_thread(holdings_for_fund, symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("N-PORT tier %s failed: %s", symbol, exc)
        return []
```

And in `aextract_data`'s store-and-return step (already in place from #97 PR #100):
```python
# Tier 3: SEC N-PORT (now live, was stub)
nport_rows = await _try_nport(symbol)
if nport_rows:
    _store_etf_holdings(symbol, nport_rows, data_source="sec_nport")
    return nport_rows
```

**L12 propagation in `transform_data`** — add a step that, when input rows have a `report_date` field, sets `EtfHoldingsData.updated` from it. The shipped `transform_data` already tolerates missing fields via `model_validate(...)` exception swallowing, so this is additive only.

**Tests to update:**
- Remove `test_try_nport_is_a_stub_until_t2_t3_land`
- Add `test_try_nport_returns_rows_from_nport_index_when_present` — patch `nport_index.holdings_for_fund` to return `[{...}]`; assert `_try_nport` returns same
- Add `test_try_nport_returns_empty_on_unknown_fund` — patch returns `[]`; assert `_try_nport` returns `[]`
- Add `test_try_nport_returns_empty_on_index_exception` — patch raises; assert `_try_nport` returns `[]` (graceful, doesn't propagate)
- Add `test_aextract_chain_falls_through_to_nport_when_issuer_empty_AND_nport_populated` — replace the existing `test_chain_issuer_empty_falls_through_to_nport` with a version that uses real `holdings_for_fund` mock (the existing test patches `_try_nport` directly which trivially passes; the new test exercises the real `_try_nport` → `holdings_for_fund` path)
- Add `test_aextract_propagates_report_date_into_updated_field` (L12) — fixture row carries `report_date`; assert returned `EtfHoldingsData.updated == report_date`

**Done when:** All updated fallback tests green; `obb.etf.holdings('XLK', provider='fmp_cached')` smoke (deferred to T9 live verification) preserves the existing issuer-tier hit AND can fall through to N-PORT for an arbitrary non-SPDR fund where the index has rows; ruff clean.

**Commit shape:** `feat(fmp_cached/99): wire real _try_nport via nport_index.holdings_for_fund (T6)`

---

### Task 7 — Extend `openfigi.py` for `ID_ISIN` (separate small PR per Q-E E1)

**bd:** `OpenBBTechnical-99-T7` (independent — can land before or after T1-T6; **filed as a separate small PR against #93** per Q-E)

**Files:**
- Modify: `openbb_platform/providers/sec/openbb_sec/utils/openfigi.py`
- Modify: `openbb_platform/providers/sec/tests/test_openfigi.py`

**Interfaces:**
- Backward-compatible: `map_cusips(...)` stays as a thin alias that delegates to `map_identifiers(..., id_type="ID_CUSIP")`
- New:
  - `map_identifiers(id_values: list[str], *, id_type: str = "ID_CUSIP", api_key: str | None = None, policy: RateLimitPolicy | None = None, refresh: bool = False) -> dict[str, dict]`
  - `map_isins(isins: list[str], **kw) -> dict[str, dict]` — `map_identifiers(isins, id_type="ID_ISIN", ...)`
  - `select_match` selection ladder gets a new tiebreak: prefer `exchCode == "US"` over composite; prefer `currency == "USD"` over other; documented as Q-E caveat ("one ISIN → many FIGIs across venues/currencies")
- New module constants: `SUPPORTED_ID_TYPES = ("ID_CUSIP", "ID_ISIN", "ID_SEDOL")`

**Tests (~8 added to the existing test_openfigi.py):**
1. `test_map_cusips_still_works_unchanged` — regression
2. `test_map_isins_calls_v3_mapping_with_id_isin` — fake HTTP; assert request body `idType="ID_ISIN"`
3. `test_select_match_isin_one_to_many_prefers_us_listing` — fixture with 3 matches (US, GR, KS); selector picks US
4. `test_select_match_isin_prefers_usd_when_no_us_match` — fixture with 2 GR matches (USD + EUR); selector picks USD
5. `test_map_identifiers_rejects_unsupported_id_type` — `id_type="ID_NONSENSE"` → `ValueError`
6. `test_map_isins_cache_hit_short_circuits_http` — same cache pattern as map_cusips (R9)
7. `test_map_isins_uses_separate_cache_key_namespace` — same ISIN string doesn't collide with a CUSIP key in `openfigi_map_cache` (PK is `(id_type, id_value, exch_code)` so this is automatic but worth asserting)
8. `test_map_cusips_is_deprecated_alias_emits_no_warning_v1` — backward compat (no breaking change in v1)

**Done when:** All openfigi tests still pass (now 20 + 8 = 28); ruff clean; **filed as a separate small PR** against `trading_technicals` with title `feat(sec/93): extend openfigi.py for ID_ISIN / ID_SEDOL (#99 Q-E E1)` — NOT bundled into the #99 main PR per Q-E resolution.

**Commit shape:** `feat(sec/93): extend openfigi.py for ID_ISIN / ID_SEDOL (#99 Q-E)`

---

### Task 8 — `Tools/enrich_nport_isin_tickers.py` (sibling to `enrich_cusip_figi.py`)

**bd:** `OpenBBTechnical-99-T8` (blocked-by T2 + T7)

**Files:**
- Create: `Tools/enrich_nport_isin_tickers.py`
- Create: `Tools/tests/test_enrich_nport_isin_tickers.py`

**Reference template:** `Tools/enrich_cusip_figi.py` (entire file) — same skeleton, same #93 review-lesson stack, same CLI shape. Differences from the template:
- Source query: `SELECT h.accession_number, h.holding_key, h.isin FROM sec_nport_holdings h WHERE h.isin IS NOT NULL AND h.ticker IS NULL AND h.cusip IS NULL` (NOT-cusip ensures we don't compete with `enrich_cusip_figi`'s domain)
- Batched call: `openfigi.map_isins(isins, ...)` instead of `map_cusips`
- Source tag: `openfigi_nport_isin`
- Target table: `sec_nport_holdings.ticker` (update via `UPDATE sec_nport_holdings SET ticker = %s, source_secondary = %s WHERE accession_number = %s AND holding_key = %s`)
- R6 anti-join: source SELECT WHERE `ticker IS NULL` AND `holding_key NOT IN (SELECT holding_key FROM sec_nport_holdings WHERE source_secondary = 'openfigi_nport_isin')` — never overwrite a non-null ticker

**Tests (~8):** Mirror `Tools/tests/test_enrich_cusip_figi.py` patterns:
1. `test_enrich_signature_accepts_extra_sleep` (review fix A)
2. `test_main_sets_db_name_env_when_database_flag_given` (review fix B)
3. `test_enrich_uses_isin_specific_batch_helper` — `map_isins` called, not `map_cusips`
4. `test_enrich_never_overwrites_non_null_ticker` — R6 anti-join regression
5. `test_enrich_writes_openfigi_nport_isin_source_tag`
6. `test_dry_run_no_writes`
7. `test_enrich_empty_input_returns_zero_stats`
8. `test_module_loads_dotenv_at_import` (review fix E)

**Done when:** All 8 tests green; CLI `--help` works; `--dry-run` against the dev DB enumerates ISINs without writing; ruff clean.

**Commit shape:** `feat(tools/99): enrich_nport_isin_tickers.py — ISIN→ticker enrichment (T8)`

---

### Task 9 — Documentation: per-tool specs + DESIGN.md + #97 status un-park

**bd:** `OpenBBTechnical-99-T9` (blocked-by T5 + T8 — both tools exist)

**Files:**
- Create: `Tools/docs/specs/ingest_sec_nport.md` (~120 lines, mirror `Tools/docs/specs/enrich_cusip_figi.md` house style)
- Create: `Tools/docs/specs/enrich_nport_isin_tickers.md` (~80 lines, sibling to `enrich_cusip_figi.md`)
- Modify: `Tools/docs/DESIGN.md` — 2 new inventory rows + §10 changelog block + §4 Table Schemas for the 4 new `sec_nport_*` tables
- Modify: `docs/designs/etf_holdings/etf-holdings-free-fallback-tier.md` — un-park status: change §0.2 Q2 status from "DEFERRED" to "RESOLVED (#99 / commit <SHA>)"; update top "Status" header to remove "N-PORT deferred" qualifier; add cross-ref pointing at `docs/designs/etf_holdings/99-sec-nport-bulk-and-incremental-ingest.md`

**Live evidence run (preferred — analogous to #97's T6 evidence file):**
- Create: `Tools/docs/runs/2026-XX-XX-nport-ingest-bounded.md` — captures the live `--mode=bulk --quarter <Q> --limit 10` output, the live `--mode=incremental --cik <XLK-CIK>` output, the `obb.etf.holdings('XLK', provider='fmp_cached')` smoke result (should now show `data_source="sec_nport"` rows alongside or in place of issuer_ssga depending on TTL freshness)

**Done when:** Both per-tool specs match the house style; DESIGN.md inventory entries point at the new specs; `Tools/docs/DESIGN.md` §4 has 4 new `CREATE TABLE` blocks (copied verbatim from `nport_index.py:DDL_*`); #97 design doc no longer says "deferred" for N-PORT; live evidence file shows the full chain working end-to-end.

**Commit shape:** `docs(99): per-tool specs + DESIGN.md changelog + un-park #97 N-PORT status (T9)`

---

## Phase-5..Phase-7 handoff (openbb-dev-cycle)

After T9 closes:
- **Phase 5 (Quality):** invoke `simplify` over the 6 new source files (`sec_http.py`, `nport_index.py`, `nport_parser.py`, `bulk_url_discovery.py`, `Tools/ingest_sec_nport.py`, `Tools/enrich_nport_isin_tickers.py`). Run full SEC + fmp_cached + Tools test suite per-file (per the #97 PR #100 convention; combined run trips pytest-asyncio mode mismatch — that's pre-existing and not a #99 regression).
- **Phase 6 (Review):** invoke `/code-review` skill on the main #99 PR + separately on the #93 ISIN extension PR. Apply review fixes on `fix/99-review-feedback` branch off feat (same shape as #93 PR #95). The lessons-already-applied list (load_dotenv at import, --database via DB_NAME env, Windows-encoding fix with errors="replace" + stderr, contextlib.suppress, transactional_upsert pattern) should leave only spec-level findings.
- **Phase 7 (Integration):** main PR `feat/99-sec-nport-ingest → trading_technicals`; separately the Q-E PR `feat/93-openfigi-isin-extension → trading_technicals` (lands first so T8 has its dependency); comment on issue #99; merge; close beads + `bd remember` the key insights (most likely: NPORT-P/A supersession rule, ZipFile-needs-seekable gotcha, fund-map ETF-detection limitation, L2 missing-UA hard-error pattern).

---

## Self-Review

**1. Spec coverage** — every §3 acceptance criterion maps to a task:
- AC #1 (incremental --cik upserts + idempotent) → T5 (CLI) + T2 (idempotent upsert) ✓
- AC #2 (bulk dry-run discovers ZIP URL + raise-loudly on zero rows) → T4 (raise-loudly guard) + T5 (CLI dispatch) ✓
- AC #3 (live bulk --limit 10 idempotent) → T5 + T2 ✓
- AC #4 (holdings_for_fund non-empty after backfill) → T2 (read helper) + T9 (live evidence) ✓
- AC #5 (holdings_for_fund asof= L10) → T2 test #15 ✓
- AC #6 (NPORT-P/A supersedes — L11) → T2 test #16 + T3 amendment fixture ✓
- AC #7 (obb.etf.holdings returns sec_nport when FMP 402) → T6 (wire `_try_nport`) ✓
- AC #8 (L2 UA enforced; missing → hard error) → T1 (chokepoint + missing-UA test) ✓
- AC #9 (no fuzzy matching, multi-id stored, ambiguous flagged) → T2 schema + T3 parser ✓
- AC #10 (G4 holding_key content-derived, deterministic) → T3 tests #6-#12 ✓
- AC #11 (OpenFIGI ID_ISIN only + R6 no-overwrite) → T7 + T8 ✓
- AC #12 (tests offline) → every task spec says "offline" ✓
- AC #13 (DESIGN.md + per-tool spec + #97 un-park) → T9 ✓

**2. Placeholder scan** — no "TBD", no "implement later". The phrase "applies the #93 review-lesson stack" recurs but is concretely defined in Global Constraints + cites `Tools/enrich_cusip_figi.py` as the template; not a placeholder. The "exact step-by-step TDD code" inside each task is delegated to the executor following the project pattern from #93/#97/refresh_etf_holdings_cache — this is the "task index" plan shape we chose, not a placeholder failure.

**3. Type consistency** —
- `holdings_for_fund` returns `list[dict]` with L12-required `report_date` + `data_age_days` keys — defined T2, consumed T6, propagated to `EtfHoldingsData.updated` ✓
- `upsert_filing` 12-tuple shape — defined T2, produced by T3's parser, called by T5 ✓
- `upsert_holdings` 13-tuple — defined T2, produced by T3, called by T5 ✓
- `parse_submission_envelope(raw, *, accession_number, source) -> (NportFiling, list[NportHolding])` — defined T3, consumed T5 (bulk + incremental both call it) ✓
- `sec_http.get` signature — defined T1, consumed T4 (`bulk_url_discovery`) + T5 (incremental archive fetch) ✓
- `discover_quarter_zips() -> dict[str, str]` — defined T4, consumed T5 (bulk mode) ✓
- `derive_holding_key` 5-arg signature — defined T3, contract referenced T2 (the G4 regression test #6 in T2 asserts the same key is produced for the same content) ✓
- `map_isins(isins, ...)` — defined T7, consumed T8 ✓
- `SOURCE_NPORT_*` enum strings — defined T2, used T3 (parser tags) + T5 (CLI mode → source dispatch) + T6 (source persisted) ✓
- `SPDR_FUND_MAP` seed dict — defined T2 (§2.3), populated by T2's `init_nport_index`, consumed by T5 (`--etf-only` filter) and T6 (read-helper lookup) ✓

**4. Scope check** — single coherent feature with two independently-testable halves (bulk + incremental ingest both write to the same schema; both consumed by the same read helper). Q-E ISIN extension is explicitly split as a sibling PR per design. No further decomposition needed.

The plan is internally consistent and ready for execution.
