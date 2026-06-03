# Plan: Tier-Aware Complementary Market Data Module (Aligned with `fmp_cached`)

## 1) Objective
Build a **separate Python module** (not notebook logic) that fetches ticker data with **FMP as primary source**, and only falls back to free sources when the FMP subscription tier/endpoint access cannot satisfy the request. Data is cached in MySQL and aligned with existing `fmp_cached` schema conventions so it behaves as a **complementary capability** to FMP-backed cached data.

The external API experience must remain **single-provider**: callers use only `fmp_cached` endpoints, while any fallback to other providers is handled internally and transparently.

---

## 2) Requested Constraints (Captured)
1. Keep implementation outside notebooks.
2. Add database caching mechanism.
3. Align with `fmp_cached` table/schema style so new ticker data can be inserted consistently.
4. Deliver proper planning first; no implementation until approval.
5. Keep fallback behavior silent behind `fmp_cached` APIs; do not require caller-side provider switching.
6. Add clear structured log messaging whenever fallback to non-FMP providers is triggered.

---

## 3) Proposed Scope (Phase-1)
### In Scope
- A new module under `openbb_fmp_cached` for tier-aware market yield history.
- Initial support for US10Y-style retrieval with source chain:
   1. **OpenBB FMP provider (primary)**
   2. **OpenBB FRED provider** when FMP tier/endpoint access is unavailable
   3. **OpenBB YFinance provider** (`^TNX`) if FRED path is unavailable
   4. Optional direct-source break-glass (disabled by default)
- MySQL persistence with `fmp_cached`-style schema fields (`symbol`, `date`, `close`, `data_json`, `cached_at`, `is_valid`, indexes).
- TTL-aware cache read-through behavior.
- Retrieval API callable from notebooks/scripts (not notebook-embedded helper functions).
- Tests for cache-hit, cache-miss, tier-aware source-fallback, and schema insert/read path.

### Out of Scope (Phase-1)
- Broad macro data catalog beyond initial US10Y.
- UI/CLI surface changes in OpenBB app layer.
- Historical backfill for many years (optional follow-up).

---

## 4) Architecture Proposal
### 4.1 New Module Layout
Proposed files:
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/__init__.py`
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/free_yield_service.py`
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/sources/fmp_source.py`
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/sources/fred_source.py`
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/sources/yahoo_source.py`
- `openbb_platform/providers/fmp_cached/openbb_fmp_cached/complementary/repository.py`

Notes:
- Source adapters should call **OpenBB provider fetchers** (or OpenBB provider facade methods), not raw HTTP endpoints.
- Direct HTTP/CSV fetching remains optional break-glass behavior behind a feature flag.

Purpose split:
- **sources/**: provider-specific fetch + normalization
- **repository.py**: DB read/write primitives
- **service.py**: cache-first orchestration and fallback chain

### 4.2 Data Flow
1. Caller requests series (`symbol`, `start_date`, `end_date`).
2. Service checks DB cache for date range and freshness.
3. If sufficient cache exists, return cached data.
4. If missing/stale segments exist, fetch from source chain (FMP first).
5. Normalize to canonical dataframe rows.
6. Upsert rows into DB.
7. Return merged ordered result.

### 4.3 Single-Provider API Contract
- Public callers interact only with `fmp_cached` API surface.
- Internal orchestration may call FMP/FRED/YFinance providers, but that must be hidden from caller inputs/outputs.
- No required API-level `provider` parameter for fallback control in consumer-facing methods.
- Response shape remains stable regardless of which internal source served cache refresh.

---

## 5) Database Strategy (Aligned with `fmp_cached`)
### 5.1 Table Option
Create a dedicated table (recommended): `complementary_market_yields`.

### 5.2 Schema Alignment Rules
Use same structural style as existing `cache_schema.py` tables:
- `id BIGINT AUTO_INCREMENT PRIMARY KEY`
- `symbol VARCHAR(50)`
- `date DATE`
- OHLC-compatible columns where applicable (`open`, `high`, `low`, `close`, `volume`)
- `currency`, `period` (nullable)
- `data_json JSON`, `additional_fields JSON`
- `cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
- `is_valid BOOLEAN DEFAULT TRUE`
- Indexes:
  - `idx_symbol`, `idx_date`, `idx_symbol_date`, `idx_cached_at`, `idx_is_valid`
  - unique key on (`symbol`, `date`) for deterministic upsert

### 5.3 Value Mapping for Yield Series
For FMP / FRED / `^TNX` normalized series:
- `symbol`: canonical symbol (`^TNX`)
- `date`: observation date
- `close`: yield percent value (e.g., `4.23`)
- `data_json`: full normalized row payload
- `additional_fields`: source metadata (`source`, `source_symbol`, `retrieved_at`)

### 5.4 Tier-Aware Fallback Rules
Fallback to non-FMP providers only when FMP is not usable for the requested data, for example:
- HTTP authorization/access errors (e.g., 401/403) indicating plan restriction
- Endpoint-not-available for current subscription tier
- Explicit "upgrade required"-type provider messages

Do **not** bypass FMP on generic transient issues unless retry policy is exhausted.

---

## 6) Caching Policy
- Default TTL for yield data: **1 day**.
- If latest business day is already cached and fresh, skip network calls.
- For partial ranges, fetch only missing segments where possible.
- On FMP tier/access limitation, fallback to next **OpenBB provider** before failing request.
- On transient FMP failures, apply retry policy first, then fallback if still unresolved.
- Persist successful source in metadata for observability.

### 6.2 Logging Policy for Silent Fallback
- Log at `INFO` when fallback path is entered (from `fmp` to `fred`/`yfinance`) with context: `symbol`, date range, trigger class (`tier_access`, `endpoint_unavailable`, `transient_after_retries`).
- Log at `WARNING` when all upstream providers fail and static fallback is used.
- Do not raise provider-specific UX noise to callers when fallback succeeds; return normalized `fmp_cached` response.
- Include correlation/request id (if available) in logs for traceability.

### 6.1 Provider Fallback Order (Planned)
1. **FMP provider** (`TreasuryRates` first)
2. **FRED provider** (`TreasuryConstantMaturity` and/or `FredSeries` using `DGS10`)
3. **YFinance provider** (`IndexHistorical` with `^TNX`)
4. Optional direct-source fallback (disabled by default)

---

## 7) Public API Proposal (Module-Level)
In `free_yield_service.py`:
- `get_us10y_series(start_date: str, end_date: str) -> pd.DataFrame`
- `get_latest_us10y_rate(start_date: str, end_date: str, fallback: float = 0.02) -> tuple[float, str]`

Behavior:
- Returns `date`, `yield_pct`, `source` columns.
- Uses DB cache first.
- Uses FMP as primary upstream source when cache miss occurs.
- Keeps provider fallback internal; caller still uses only `fmp_cached` entrypoints.
- On total failure, returns fallback only via `get_latest_us10y_rate` (with source label `fallback:static`).

---

## 8) Integration Plan with Current Notebook
After implementation approval:
1. Remove notebook-level helper duplication.
2. Import module function in setup/helper cell, e.g.:
   - `from openbb_fmp_cached.complementary.free_yield_service import get_latest_us10y_rate`
3. Keep notebook logic minimal and declarative.

---

## 9) Testing Plan
### 9.1 Unit Tests
- Source adapters normalize expected columns.
- Repository read/write/upsert behavior.
- Cache freshness checks and miss logic.

### 9.2 Integration Tests (Mocked Network)
- FMP success path.
- FMP tier/access failure -> FRED success path.
- FMP + FRED failure -> YFinance success path.
- Both fail -> fallback path (`get_latest_us10y_rate`).

### 9.3 DB Contract Tests
- Table creation idempotency.
- Upsert uniqueness on (`symbol`, `date`).
- Correct round-trip values (`close` <-> `yield_pct`).

### 9.4 Regression Tests
- Ensure no side-effects on existing `fmp_cached` endpoint fetchers.

---

## 10) Migration & Rollout
### Step 1
Add schema function in `cache_schema.py`:
- `create_complementary_market_yields_table()`

### Step 2
Hook into optional init path (if desired) or lazy-create on first call.

### Step 3
Add module + tests.

### Step 4
Notebook migration to import the module.

### Step 5
Validation run and documentation update.

---

## 11) Documentation Updates
Planned docs:
- Add section in `openbb_platform/providers/fmp_cached/README.md`:
  - “Complementary free-source market data cache”.
- Add env/TTL knobs to `DATABASE_CONFIGURATION.md` if configurable.

---

## 12) Risks & Mitigations
1. **Free source schema drift**
   - Mitigation: strict normalization layer + tests + fallback chain.
2. **Yahoo intermittency/rate limits**
   - Mitigation: source fallback + cache-first behavior.
3. **Incorrect fallback trigger from FMP**
   - Mitigation: explicit classifier for tier/access errors vs transient transport errors.
4. **Table sprawl in cache schema**
   - Mitigation: one focused complementary table with generic OHLC-compatible shape.
5. **Data consistency (percent vs decimal)**
   - Mitigation: store percent in DB (`close`), convert to decimal only at consumer function.

---

## 13) Acceptance Criteria
Implementation is complete when:
1. A separate module (outside notebook) provides tier-aware retrieval with **FMP first**, then free-source fallback only when tier/endpoint access cannot satisfy request.
2. A separate module provides tier-aware retrieval with **OpenBB providers in order: FMP -> FRED -> YFinance**.
3. Caller-facing API experience remains single-provider (`fmp_cached`); fallback to other providers is internal and silent when successful.
4. Data persists in MySQL with `fmp_cached`-aligned schema and indexes.
5. Repeated calls hit cache and avoid unnecessary external requests.
6. Notebook can call module function instead of inline helper logic.
7. Structured logs are emitted for fallback transitions and total upstream failure paths.
8. Automated tests pass for cache-hit/miss/fallback/upsert paths.

---

## 14) Execution Checklist (Post-Approval)
1. Add complementary schema function + table creation path.
2. Implement source adapters (FMP/FRED/YFinance), error classifier, and normalization.
3. Implement repository and cache-first service.
4. Add tests.
5. Wire notebook import and remove inline duplicate helper.
6. Run targeted tests and smoke test notebook flow.
7. Prepare commit with docs.

---

## 15) Decision Points for Your Approval
Please confirm before implementation:
1. Table name: `complementary_market_yields` (recommended) vs alternative naming.
2. TTL default: 1 day (recommended).
3. Keep source order as **FMP -> FRED -> YFinance**.
4. Notebook migration included in same implementation PR.

---

## 16) Relevant OpenBB APIs in Fallback Order

### 16.1 Primary: FMP Provider (Subscription-Aware)
Planned endpoint usage:
- `FMPTreasuryRatesFetcher` (`openbb_fmp.models.treasury_rates`)
   - Extract US10Y from `year10`

Rationale:
- Uses your paid FMP subscription first.
- Best alignment with existing `fmp_cached` domain.

### 16.2 Secondary: FRED Provider
Planned endpoint usage (in order):
- `FREDTreasuryConstantMaturityFetcher` (`openbb_fred.models.tmc`)
- `FredSeriesFetcher` (`openbb_fred.models.series`) with series id `DGS10` as fallback within FRED path

Rationale:
- OpenBB-supported macro provider.
- Strong data quality and continuity for US10Y-like series.

### 16.3 Tertiary: YFinance Provider
Planned endpoint usage:
- `YFinanceIndexHistoricalFetcher` (`openbb_yfinance.models.index_historical`) with symbol `^TNX`

Rationale:
- OpenBB-supported market data fallback for index-style yield proxy.

### 16.4 Optional Break-Glass (Disabled by Default)
- Direct-source call only if explicitly enabled by config flag (e.g., `FMP_CACHE_ENABLE_DIRECT_BREAKGLASS=true`).
- Intended for emergency continuity, not normal operation.

### 16.5 Source Metadata Saved Per Row
`additional_fields` will include at minimum:
- `provider` (fmp/fred/yfinance/direct)
- `endpoint` (e.g., `TreasuryRates`, `TreasuryConstantMaturity`, `IndexHistorical`)
- `source_symbol` (e.g., `year10`, `DGS10`, `^TNX`)
- `retrieved_at`

Once approved, implementation will proceed exactly per this plan.