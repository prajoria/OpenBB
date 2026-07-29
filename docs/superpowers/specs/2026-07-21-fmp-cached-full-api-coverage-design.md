# fmp_cached — Full FMP Stable API Coverage with Persistent Layer

**Date:** 2026-07-21
**Status:** Design / Plan (implementation not started)
**Owner:** `fmp_cached` provider team (see governance note §12)
**Provider path:** `openbb_platform/providers/fmp_cached/openbb_fmp_cached/`
**Source of truth (API surface):** `H:\masterswork\git\OpenBBTechnical\temp\fmp_api_docs\api-docs.md` (FMP stable, 635 KB)
**Related:**
- Architecture: [docs/OpenBBPlatform/architecture/providers/fmp-cached.md](../../OpenBBPlatform/architecture/providers/fmp-cached.md)
- Prior audit: [scripts/audit_fmp_cached_coverage.py](../../../scripts/audit_fmp_cached_coverage.py), [docs/reports/2026-07-19-fmp-cached-coverage-audit.md](../../reports/2026-07-19-fmp-cached-coverage-audit.md)
- Program epic: [scripts/fmp_cache_epic_body.md](../../../scripts/fmp_cache_epic_body.md)

---

## 1. Goal

Deliver **complete FMP stable API coverage across two providers in tandem**:

- **`openbb_fmp` (live layer)** — the direct, non-cached FMP provider. Every FMP
  stable endpoint gets a live fetcher here (many already exist; ~150+ are
  net-new). This is where the raw HTTP call, Query/Data models, and
  request/response transforms live.
- **`fmp_cached` (persistence layer)** — subclasses/wraps the corresponding
  `openbb_fmp` fetcher and adds the MySQL persistent layer (read-through +
  gap/TTL/event freshness). It never re-implements the HTTP call; it reuses the
  live fetcher and overrides only `aextract_data` to read/write the cache.

> **Both providers are enhanced together, endpoint by endpoint.** For any
> endpoint missing today, the unit of work is a *pair*: (1) add the live fetcher
> to `openbb_fmp`, then (2) add the persistence wrapper to `fmp_cached` that
> subclasses it. `fmp_cached` is always a thin persistence skin over an
> `openbb_fmp` fetcher — the existing dedicated models (`equity_quote.py`,
> `balance_sheet.py`, …) already follow exactly this subclass pattern.

Today `fmp_cached` covers a partial subset (~73 model files, ~18 with real
database persistence, the rest pass-through fallbacks or absent), and `openbb_fmp`
exposes ~74 fetchers. The target end-state is:

- **Full endpoint parity** with FMP stable: every one of the **276 HTTP
  endpoints** (across **31 categories / 87 groups**) has a live `openbb_fmp`
  fetcher **and** a persistence-backed `fmp_cached` fetcher, reachable through
  either a first-class OpenBB router endpoint or a provider-specific fetcher.
- **Full persistent layer** for every endpoint whose data is cacheable: each
  endpoint writes to and reads from a MySQL table using the archetype-appropriate
  freshness strategy (gap detection, point-in-time by fiscal period, short-TTL
  snapshot, or append-only event feed).
- **Graceful degradation on plan limits.** Some endpoints require a higher FMP
  subscription tier than our key holds. The provider **still implements them
  fully** (fetcher + schema + persistence path); when the upstream returns
  `403/402/empty`, the fetcher records the miss and returns an empty result set
  without raising. Coverage is a code property, not a function of our key.

### Non-goals

- No generic multi-provider cache framework. This is FMP-specific (matches the
  program epic's stated non-goal).
- WebSocket / Socket.io streaming endpoints (§7 Archetype H) are **out of scope
  for persistence** — they are stateful streams, not request/response calls.
- No implementation in this PR. This document is the plan; implementation lands
  as the phased waves in §9, each as its own issue/branch/PR.

---

## 2. Current state (baseline)

| Dimension | Today |
|---|---|
| FMP stable HTTP endpoints (target) | **276** (+ ~11 websocket/socket.io, out of scope) |
| Categories / groups | 31 / 87 |
| `fmp_cached` model files | ~73 |
| Tier-1 dedicated DB-persistent fetchers | ~18 |
| Upstream `openbb_fmp` fetchers available to reuse | ~74 |
| Endpoints with **no** live `openbb_fmp` fetcher (net-new in `openbb_fmp` **and** `fmp_cached`) | **~150+** (see §8) |

### 2.1 Existing architecture (must be preserved and extended)

Two-tier `fetcher_dict` assembled in
[`openbb_fmp_cached/__init__.py`](../../../openbb_platform/providers/fmp_cached/openbb_fmp_cached/__init__.py):

- **Tier 1 — dedicated persistence.** A fetcher subclass overrides
  `aextract_data` to read/write a MySQL table; on any DB error it falls back to
  a direct upstream FMP call. Examples: `EquityHistorical` (gap detection),
  `EquityQuote` (short-TTL snapshot), `BalanceSheet`/`IncomeStatement`/`CashFlow`
  (point-in-time by fiscal period).
- **Tier 2 — fallback wrapper.** `create_fallback_fetcher_class(original, name)`
  wraps an upstream `openbb_fmp` fetcher, translating credentials
  (`fmp_cached_api_key → fmp_api_key`) and delegating — **no persistence**.

Persistence internals (`openbb_fmp_cached/utils/`):

| File | Role |
|---|---|
| `database.py` | `pymysql` pool; `execute_query` / `execute_many`; `replace_rows` (atomic DELETE+INSERT, bd-kh08); `safe_identifier` (identifier allowlist); `init_database`. Fails fast if MySQL creds missing. |
| `cache_schema.py` | Per-endpoint `create_<name>_table()` DDL; `get_table_name()` applies `test_` prefix + validates identifier. |
| `cache_manager.py` | `DatabaseManager`: endpoint→table map, WHERE-builders, `INSERT … ON DUPLICATE KEY UPDATE`, unknown-field JSON stuffing, soft-delete via `is_valid`, hit/miss/store/error stats. |
| `security.py` | apikey-scrub log filters (installed at import time, #963). |
| `models/base_cached.py` | `create_fallback_fetcher_class`; `create_ttl_wrapper_class` (global `ttl_cache` table, keyed `(cache_name, query_hash)`). |
| `complementary/` | free fallback sources (FRED/Yahoo) for e.g. yields. |

**This plan extends — never replaces — these primitives.** Every new endpoint
reuses `database.py` helpers, adds a `create_<name>_table()` to `cache_schema.py`,
and registers in `__init__.py`.

---

## 3. Design principles

1. **Persistence is storage, not TTL-only caching.** Match the existing intent:
   avoid unnecessary API calls by persisting rows durably and detecting what's
   already present. TTL is one of several freshness strategies, not the default.
2. **Never lose fresh data on a cache-write failure.** All new fetchers follow
   the established rule (bd-e3v8/bd-n3sf): if the DB write throws, log and return
   the freshly-fetched data anyway.
3. **DB failure ⇒ direct upstream, never a hard error.** `init_database()` /
   read failures fall through to a live FMP call (existing pattern).
4. **Atomic replace for per-key rewrites.** Use `replace_rows(table, key_col,
   key_val, rows)` so a partial write never empties a symbol's cache.
5. **Identifier safety.** Every table/column name flows through
   `safe_identifier` / `get_table_name`. No f-string interpolation of untrusted
   identifiers into DDL/DML.
6. **Credential + secret hygiene.** Reuse `_resolve_credentials` (creds →
   `UserService` fallback, `SecretStr` unwrap) and the apikey-scrub filters.
   No API keys in logs, table rows, or error messages.
7. **Plan-tier tolerance.** A `402/403`/empty upstream response is a *data*
   condition, not a *coverage* gap. The fetcher returns `[]` and records a
   `plan_limited` marker (see §6.4) so callers/tests can distinguish "no data"
   from "not implemented."
8. **Deterministic tests without network.** Every endpoint ships structural
   tests (schema DDL parses, fetcher registers) plus a fixture-replay integration
   test using the recorded FMP JSON in `api-docs.md` / the fixture harness
   ([2026-07-21-fmp-fixture-harness-design.md](./2026-07-21-fmp-fixture-harness-design.md)).

---

## 4. Endpoint classification model

Every endpoint gets two orthogonal labels.

### 4.1 Coverage status (build effort)

| Code | Meaning | Work required |
|---|---|---|
| **D** | Live `openbb_fmp` fetcher exists **and** `fmp_cached` has dedicated persistence | None (verify at runtime) |
| **F** | Live `openbb_fmp` fetcher exists; `fmp_cached` is only a tier-2 fallback (no persistence) | Add the `fmp_cached` persistence wrapper subclassing the existing live fetcher |
| **N** | No live fetcher in `openbb_fmp` | **Two-part:** (1) add net-new live fetcher (raw HTTP + Query/Data models) to `openbb_fmp`; (2) add `fmp_cached` persistence wrapper subclassing it |

> The Coverage column in §8 is a **best-effort seed** derived from the model-file
> inventory. **Wave 0** (§9) produces the authoritative status by extending
> `audit_fmp_cached_coverage.py` to walk all 276 endpoints and probe the router.

### 4.2 Persistence archetype (freshness strategy)

| Archetype | Data shape | Freshness strategy | Table key | Example endpoints |
|---|---|---|---|---|
| **A · Reference** | Static/slow lists | Long TTL (24 h–7 d), replace-all | list-name | `stock-list`, `available-exchanges`, `commodities-list`, `cik-list`, SIC list |
| **B · Time-series** | EOD/intraday bars, historical series | **Gap detection** over date range (reuse `equity_historical` pattern) | `(entity, date, interval, variant)` | `historical-price-eod/*`, `historical-chart/*`, `historical-market-capitalization`, `historical-sector-performance`, technical-indicators |
| **C · Periodic PIT** | Point-in-time by fiscal period | Key by `(symbol, period, calendar_year)`; refresh only newest period | `(symbol, period, year)` | statements (+TTM +growth +as-reported), `key-metrics`, `ratios`, `financial-scores`, `enterprise-values`, `owner-earnings`, DCF, revenue segmentation, `analyst-estimates` |
| **D · Snapshot** | Volatile current values | **Short TTL** (60 s–1 h) via dedicated snapshot table or `ttl_cache` wrapper | `(symbol[/exchange], as_of)` | quotes (short/full/batch), aftermarket, `stock-price-change`, `market-capitalization`, ratings snapshot, price-target summary/consensus, gainers/losers/actives, sector/industry snapshot, market hours |
| **E · Event feed** | Append-only filings/news/trades | Idempotent upsert on natural event key; incremental page fetch; long retention | natural key (filing id / date+symbol / txn id) | news (all), SEC filings (all), insider trades, senate/house, 13F, calendars (div/earn/split/ipo), mergers, crowdfunding, delisted, symbol-changes, transcripts, economic calendar, ESG disclosures |
| **F · Bulk** | CSV part-file dumps | Key by `(dataset, part\|year\|period)`; long TTL; warmer-oriented | `(dataset, part)` | `*-bulk` endpoints |
| **G · Partner** | TipRanks / COT / specialty | Snapshot or PIT depending on shape; frequently premium-gated | endpoint-specific | `tipranks-*`, `commitment-of-traders-*`, `esg-benchmark` |
| **H · Streaming** | WebSocket / Socket.io | **N/A — not persisted** (documented pass-through) | — | `Websockets`, `Socket.io` |

---

## 5. Net-new endpoint pattern (two-provider, the core new capability)

~150+ endpoints have **no** `openbb_fmp` fetcher today. For these the unit of
work is a **pair of changes**, done in order:

### 5.1 Step 1 — live fetcher in `openbb_fmp`

Add a standard OpenBB fetcher to
`openbb_platform/providers/fmp/openbb_fmp/models/<endpoint>.py` using
`openbb_fmp`'s existing HTTP helpers (`openbb_fmp.utils.helpers.get_data_many` /
`get_data_one`, `create_url`, `response_callback`). This is the normal way
`openbb_fmp` fetchers are written — nothing bespoke:

```python
# openbb_fmp/models/<endpoint>.py  (LIVE layer)
class FMP<Endpoint>QueryParams(QueryParams):
    ...  # from api-docs "Parameters" table (required marked *)

class FMP<Endpoint>Data(Data):
    ...  # from api-docs "Example Response"

class FMP<Endpoint>Fetcher(Fetcher[FMP<Endpoint>QueryParams, list[FMP<Endpoint>Data]]):
    @staticmethod
    def transform_query(params): ...
    @staticmethod
    async def aextract_data(query, credentials, **kwargs):
        api_key = credentials.get("fmp_api_key") if credentials else ""
        url = create_url(version="stable", endpoint="<path>", api_key=api_key, query=query)
        return await get_data_many(url, **kwargs)
    @staticmethod
    def transform_data(query, data, **kwargs): ...
```

Register it in `openbb_fmp/__init__.py`'s `fetcher_dict` (under the OpenBB
standard model key when one exists, else a provider-specific key). This makes the
endpoint available for **live, non-cached** use immediately.

### 5.2 Step 2 — persistence wrapper in `fmp_cached`

Add `fmp_cached/models/<endpoint>.py` that **subclasses the live fetcher** and
overrides only `aextract_data` to read/write MySQL — identical in shape to the
existing dedicated models (`equity_quote.py`, `balance_sheet.py`):

```python
# fmp_cached/models/<endpoint>.py  (PERSISTENCE layer)
from openbb_fmp.models.<endpoint> import (
    FMP<Endpoint>QueryParams, FMP<Endpoint>Data, FMP<Endpoint>Fetcher,
)
from openbb_fmp_cached.utils.database import init_database, replace_rows, execute_query
from openbb_fmp_cached.utils.cache_schema import create_<endpoint>_table

class FMPCached<Endpoint>Fetcher(FMP<Endpoint>Fetcher):        # subclass the LIVE fetcher
    @staticmethod
    def transform_query(params): return FMP<Endpoint>QueryParams(**params)

    @staticmethod
    async def aextract_data(query, credentials, **kwargs) -> list[dict]:
        creds = _resolve_credentials(credentials)            # existing helper
        try:
            init_database(); create_<endpoint>_table()
        except Exception as exc:                             # DB down → live only
            logger.warning("cache init failed: %s", exc)
            return await FMP<Endpoint>Fetcher.aextract_data(query, creds, **kwargs)
        cached = _read(query)                                # archetype-specific
        if _fresh(cached, query):                            # HIT
            return cached
        fresh = await FMP<Endpoint>Fetcher.aextract_data(query, creds, **kwargs)  # MISS
        try: _write(query, fresh)                            # never lose fresh data
        except Exception as exc: logger.warning("cache write failed: %s", exc)
        return fresh or cached

    @staticmethod
    def transform_data(query, data, **kwargs):               # reuse live transform
        return FMP<Endpoint>Fetcher.transform_data(query, data, **kwargs)
```

Because `fmp_cached` subclasses the live fetcher, it inherits
`transform_query`/`transform_data` and the HTTP call for free; it owns only the
cache read/write and freshness logic. **No raw HTTP client is added to
`fmp_cached`** — all live I/O routes through `openbb_fmp`.

### 5.3 Plan-limit tolerance

The live `openbb_fmp` fetcher is where a `402/403`/empty upstream response is
normalized to an empty result (so coverage is independent of our key tier). The
`fmp_cached` wrapper surfaces the same empty result and records a `plan_limited`
marker (§6.4) rather than raising. Fixing plan-limit handling once in the live
fetcher benefits both providers.

### 5.4 Schema-generation convention (`fmp_cached` only)

Each net-new endpoint adds one `create_<name>_table()` to `cache_schema.py`
following the existing flattened pattern: typed columns for the primary/queryable
fields from the response, a `data_json JSON` column for the full raw payload, an
`additional_fields JSON` catch-all, plus standard metadata (`cached_at`,
`is_valid`) and the archetype's indexes. Reserved words (`change`) are renamed
(`change_amount`) per the existing convention. (No schema work in `openbb_fmp` —
it is stateless.)

---

## 6. Cross-cutting concerns

### 6.1 Registration (both providers)

Each endpoint is registered twice, once per provider:

- **`openbb_fmp/__init__.py`** — the live fetcher joins its `fetcher_dict` under
  the OpenBB standard model key when one exists, else a provider-specific key.
- **`fmp_cached/__init__.py`** — `create_all_cached_fetchers()` grows to include
  the persistence wrapper under the **same** key so the cached provider is a
  drop-in for the live one. Where an OpenBB standard model exists (e.g.
  `EquityQuote`, `BalanceSheet`) both register under that key; endpoints with
  **no** OpenBB standard model register under a stable, matching
  provider-specific key in both providers (documented in each README). This
  keeps full surface parity even for endpoints the OpenBB core router doesn't
  model.

### 6.2 MySQL schema management & migrations

- ~150 new tables. `create_all_tables()` gains the new `create_*` calls; DDL is
  idempotent (`CREATE TABLE IF NOT EXISTS`), gated by `FMP_CACHE_AUTO_CREATE_DB`.
- Add a **schema-version table** (`fmp_cache_schema_version`) and a one-shot
  `setup_database.py --migrate` path so large deployments don't rely solely on
  lazy per-fetcher `create_*` calls. Test DBs keep the `test_` prefix
  (`FMP_CACHE_TEST_MODE`).
- Table-count budget: group rarely-used specialty endpoints (Archetype G, bulk)
  behind opt-in creation to avoid 150 empty tables on every fresh DB.

### 6.3 Config & credentials

No new required config. Reuse `fmp_cached_api_key` + the MySQL connection block
from `user_settings.json`. Net-new fetchers reuse the same `_resolve_credentials`
chain (explicit creds → translated key → `UserService` default → `SecretStr`).

### 6.4 Plan-limit signalling

The live `openbb_fmp` fetcher normalizes FMP `402/403`/subscription errors and
empty envelopes (`{"Error Message": ...}`) to an empty result. The `fmp_cached`
wrapper surfaces that empty result and sets a lightweight, thread-local
`plan_limited` marker, returning a `plan_limited=True` row-less result with a
one-line WARN. This lets integration tests assert "fully wired but key-gated"
distinctly from "not implemented," satisfying "provider should have full support
even if our key doesn't."

### 6.5 Rate limiting & warmers

Live HTTP throttling is handled in `openbb_fmp`'s request path (shared across
both providers since `fmp_cached` calls through it). Reference/bulk archetypes
get scheduled `fmp_cached` warmers analogous to
`Tools/refresh_etf_holdings_cache.py` that backfill MySQL off-peak.

### 6.6 Security review checklist (per wave)

- No SQL identifier interpolation without `safe_identifier`.
- All user-supplied query values parameterized (`%s`), never f-stringed.
- apikey never logged/persisted; scrub filters cover any new logger names.
- No secrets or raw brokerage/portfolio data written to cache tables.
- Response payloads size-bounded before JSON-storing (guard oversized `data_json`).

---

## 7. Persistence archetype → schema/read/write templates

For each archetype, the concrete template new endpoints follow.

**A · Reference** — table `(name PK-ish, item columns…, data_json, cached_at)`;
read = `SELECT … WHERE list_name=%s AND cached_at > now()-ttl`; write =
`replace_rows(table, 'list_name', name, rows)`. TTL 24 h+.

**B · Time-series** — reuse `equity_historical` gap-detection verbatim:
`_analyze_cache_gaps` → `_detect_missing_ranges` (skip weekends/holidays) →
fetch only missing → UPSERT → re-read. Key `(entity, date, interval, variant)`.

**C · Periodic PIT** — read = `SELECT … WHERE symbol=%s AND period=%s ORDER BY
calendar_year DESC LIMIT n`; MISS only when the requested period count exceeds
stored; refresh the newest period on a soft-TTL (e.g. 24 h) so the latest filing
updates. Key `(symbol, period, calendar_year)` unique.

**D · Snapshot** — dedicated table with `cached_at`; read within short TTL else
refetch; `replace_rows(table, 'symbol', sym, [row])`. Or, for trivial cases,
`create_ttl_wrapper_class(inner, name, ttl_seconds)` against the shared
`ttl_cache` table. TTL 60 s (quotes) … 3600 s (sector snapshot).

**E · Event feed** — unique natural key (e.g. `filing_id`, or
`(symbol, filing_date, type)`); write = `INSERT … ON DUPLICATE KEY UPDATE`;
read = `SELECT … WHERE <filters> ORDER BY date DESC LIMIT/OFFSET`; incremental
fetch pulls only pages newer than the max stored date. Long retention.

**F · Bulk** — one row per `(dataset, part)` storing the parsed rows or a pointer;
long TTL; consumed by warmers, not latency-critical reads.

**G · Partner** — pick D or C by shape; wrap in plan-limit tolerance since these
are frequently premium.

**H · Streaming** — not persisted; document as unsupported in `fmp_cached`
(callers use a live streaming client).

---

## 8. Complete endpoint catalog (276 HTTP endpoints)

Legend — **Cov**: D=dedicated today · F=upstream-fallback today · N=net-new
required. **Arc**: archetype from §4.2. Cov is a seed; Wave 0 finalizes it.

### 8.1 Search (7)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Stock Symbol Search | `search-symbol` | N | A |
| Company Name Search | `search-name` | N | A |
| Search CIK | `search-cik` | N | A |
| CUSIP | `search-cusip` | N | A |
| Search ISIN | `search-isin` | N | A |
| Stock Screener | `company-screener` | F | A |
| Exchange Variants | `search-exchange-variants` | N | A |

### 8.2 Directory (11)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Company Symbols List | `stock-list` | N | A |
| Financial Statement Symbols List | `financial-statement-symbol-list` | N | A |
| CIK List | `cik-list` | N | A |
| Symbol Changes List | `symbol-change` | N | E |
| ETF Symbol Search | `etf-list` | F | A |
| Actively Trading List | `actively-trading-list` | N | A |
| Earnings Transcript List | `earnings-transcript-list` | N | A |
| Available Exchanges | `available-exchanges` | N | A |
| Available Sectors | `available-sectors` | N | A |
| Available Industries | `available-industries` | N | A |
| Available Countries | `available-countries` | N | A |

### 8.3 Analyst (8)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Financial Estimates | `analyst-estimates` | D | C |
| Ratings Snapshot | `ratings-snapshot` | F/D | D |
| Historical Ratings | `ratings-historical` | F/D | B |
| Price Target Summary | `price-target-summary` | N | D |
| Price Target Consensus | `price-target-consensus` | D | D |
| Stock Grades | `grades` | N | E |
| Historical Stock Grades | `grades-historical` | N | B |
| Stock Grades Summary | `grades-consensus` | N | D |

### 8.4 Calendar (9)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Dividends Company | `dividends` | F | C |
| Dividends Calendar | `dividends-calendar` | F | E |
| Earnings Report | `earnings` | F | E |
| Earnings Calendar | `earnings-calendar` | F | E |
| IPOs Calendar | `ipos-calendar` | F | E |
| IPOs Disclosure | `ipos-disclosure` | N | E |
| IPOs Prospectus | `ipos-prospectus` | N | E |
| Stock Split Details | `splits` | F | C |
| Stock Splits Calendar | `splits-calendar` | F | E |

### 8.5 Chart (10)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Stock Chart Light | `historical-price-eod/light` | F | B |
| Stock Price and Volume Data | `historical-price-eod/full` | D | B |
| Unadjusted Stock Price | `historical-price-eod/non-split-adjusted` | N | B |
| Dividend Adjusted Price Chart | `historical-price-eod/dividend-adjusted` | N | B |
| 1/5/15/30 Min, 1 h, 4 h Interval Stock Chart | `historical-chart/{1min,5min,15min,30min,1hour,4hour}` | D/F | B |

*(6 intraday interval rows collapsed — each is a distinct `interval` value of the intraday fetcher.)*

### 8.6 Company (17)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Company Profile Data | `profile` | D | C |
| Company Profile by CIK | `profile-cik` | N | C |
| Company Notes | `company-notes` | N | A |
| Stock Peer Comparison | `stock-peers` | D | A |
| Delisted Companies | `delisted-companies` | N | E |
| Company Employee Count | `employee-count` | F | C |
| Company Historical Employee Count | `historical-employee-count` | F | B |
| Company Market Cap | `market-capitalization` | N | D |
| Batch Market Cap | `market-capitalization-batch` | N | D |
| Historical Market Cap | `historical-market-capitalization` | F | B |
| Company Share Float & Liquidity | `shares-float` | F | D |
| All Shares Float | `shares-float-all` | N | A |
| Latest Mergers & Acquisitions | `mergers-acquisitions-latest` | N | E |
| Search Mergers & Acquisitions | `mergers-acquisitions-search` | N | E |
| Company Executives | `key-executives` | F | C |
| Executive Compensation | `governance-executive-compensation` | F | C |
| Executive Compensation Benchmark | `executive-compensation-benchmark` | N | A |

### 8.7 CommitmentOfTraders (3)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| COT Report | `commitment-of-traders-report` | N | G |
| COT Analysis By Dates | `commitment-of-traders-analysis` | N | G |
| COT Report List | `commitment-of-traders-list` | N | A |

### 8.8 DiscountedCashFlow (4)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| DCF Valuation | `discounted-cash-flow` | N | C |
| Levered DCF | `levered-discounted-cash-flow` | N | C |
| Custom DCF Advanced | `custom-discounted-cash-flow` | N | C |
| Custom DCF Levered | `custom-levered-discounted-cash-flow` | N | C |

### 8.9 Economics (4)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Treasury Rates | `treasury-rates` | D | B |
| Economics Indicators | `economic-indicators` | N | B |
| Economic Data Releases Calendar | `economic-calendar` | D | E |
| Market Risk Premium | `market-risk-premium` | F | A |

### 8.10 ESG (3)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| ESG Investment Search | `esg-disclosures` | F | E |
| ESG Ratings | `esg-ratings` | F | C |
| ESG Benchmark Comparison | `esg-benchmark` | N | G |

### 8.11 EtfAndMutualFunds (10)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| ETF & Fund Holdings | `etf/holdings` | D | C |
| ETF & Mutual Fund Information | `etf/info` | F | A |
| ETF & Fund Country Allocation | `etf/country-weightings` | F | A |
| ETF Asset Exposure | `etf/asset-exposure` | F | A |
| ETF Sector Weighting | `etf/sector-weightings` | F | A |
| Mutual Fund & ETF Disclosure (latest holders) | `funds/disclosure-holders-latest` | N | E |
| Mutual Fund Disclosures | `funds/disclosure` | F | E |
| Disclosure Name Search | `funds/disclosure-holders-search` | N | E |
| Fund & ETF Disclosures by Date | `funds/disclosure-dates` | N | E |

### 8.12 Statements (24)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Income Statement | `income-statement` | D | C |
| Balance Sheet Statement | `balance-sheet-statement` | D | C |
| Cash Flow Statement | `cash-flow-statement` | D | C |
| Latest Financial Statements | `latest-financial-statements` | N | E |
| Income Statements TTM | `income-statement-ttm` | N | C |
| Balance Sheet Statements TTM | `balance-sheet-statement-ttm` | N | C |
| Cashflow Statements TTM | `cash-flow-statement-ttm` | N | C |
| Key Metrics | `key-metrics` | D | C |
| Financial Ratios | `ratios` | D | C |
| Key Metrics TTM | `key-metrics-ttm` | N | C |
| Financial Ratios TTM | `ratios-ttm` | N | C |
| Financial Scores | `financial-scores` | N | C |
| Owner Earnings | `owner-earnings` | N | C |
| Enterprise Values | `enterprise-values` | N | C |
| Income Statement Growth | `income-statement-growth` | F | C |
| Balance Sheet Statement Growth | `balance-sheet-statement-growth` | F | C |
| Cashflow Statement Growth | `cash-flow-statement-growth` | F | C |
| Financial Statement Growth | `financial-growth` | N | C |
| Financial Reports Dates | `financial-reports-dates` | N | E |
| Financial Reports Form 10-K JSON | `financial-reports-json` | N | C |
| Financial Reports Form 10-K XLSX | `financial-reports-xlsx` | N | C |
| Revenue Product Segmentation | `revenue-product-segmentation` | F | C |
| Revenue Geographic Segments | `revenue-geographic-segmentation` | F | C |
| As Reported Income Statements | `income-statement-as-reported` | N | C |
| As Reported Balance Statements | `balance-sheet-statement-as-reported` | N | C |
| As Reported Cashflow Statements | `cash-flow-statement-as-reported` | N | C |
| As Reported Financial Statements | `financial-statement-full-as-reported` | N | C |

### 8.13 Form13F (8)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Institutional Ownership Filings | `institutional-ownership/latest` | D | E |
| Filings Extract | `institutional-ownership/extract` | D | E |
| Form 13F Filings Dates | `institutional-ownership/dates` | N | E |
| Extract With Analytics By Holder | `institutional-ownership/extract-analytics/holder` | N | C |
| Holder Performance Summary | `institutional-ownership/holder-performance-summary` | N | C |
| Holders Industry Breakdown | `institutional-ownership/holder-industry-breakdown` | N | C |
| Positions Summary | `institutional-ownership/symbol-positions-summary` | N | C |
| Industry Performance Summary | `institutional-ownership/industry-summary` | N | C |

### 8.14 Indexes (15)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Stock Market Indexes List | `index-list` | F | A |
| Index Quote | `quote` (index) | D/F | D |
| Index Short Quote | `quote-short` | N | D |
| All Index Quotes | `batch-index-quotes` | N | D |
| Historical Index Light/Full Chart | `historical-price-eod/{light,full}` | F | B |
| Index Intraday 1min/5min/1hour | `historical-chart/{1min,5min,1hour}` | F | B |
| S&P 500 / Nasdaq / Dow Constituents | `sp500-constituent`, `nasdaq-constituent`, `dowjones-constituent` | D/N | A |
| Historical S&P 500 / Nasdaq / Dow | `historical-{sp500,nasdaq,dowjones}-constituent` | N | E |

### 8.15 Commodity (9)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Commodities List | `commodities-list` | N | A |
| Commodities Quote / Short | `quote`, `quote-short` | N | D |
| All Commodities Quotes | `batch-commodity-quotes` | N | D |
| Light / Full Chart | `historical-price-eod/{light,full}` | F | B |
| Intraday 1min/5min/1hour | `historical-chart/{1min,5min,1hour}` | F | B |

### 8.16 Crypto (9)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Cryptocurrency List | `cryptocurrency-list` | F | A |
| Full / Short Quote | `quote`, `quote-short` | N | D |
| All Crypto Quotes | `batch-crypto-quotes` | N | D |
| Historical Light / Full Chart | `historical-price-eod/{light,full}` | F | B |
| Intraday 1min/5min/1hour | `historical-chart/{1min,5min,1hour}` | F | B |

### 8.17 Fundraisers (6)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Latest Crowdfunding Campaigns | `crowdfunding-offerings-latest` | N | E |
| Crowdfunding Campaign Search | `crowdfunding-offerings-search` | N | E |
| Crowdfunding By CIK | `crowdfunding-offerings` | N | E |
| Equity Offering Updates | `fundraising-latest` | N | E |
| Equity Offering Search | `fundraising-search` | N | E |
| Equity Offering By CIK | `fundraising` | N | E |

### 8.18 Forex (9)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Forex Currency Pairs | `forex-list` | F | A |
| Forex Quote / Short | `quote`, `quote-short` | N | D |
| Batch Forex Quotes | `batch-forex-quotes` | N | D |
| Historical Light / Full Chart | `historical-price-eod/{light,full}` | F | B |
| Intraday 1min/5min/1hour | `historical-chart/{1min,5min,1hour}` | F | B |

### 8.19 InsiderTrades (6)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Latest Insider Trading | `insider-trading/latest` | F | E |
| Search Insider Trades | `insider-trading/search` | F | E |
| Search by Reporting Name | `insider-trading/reporting-name` | N | E |
| All Insider Transaction Types | `insider-trading-transaction-type` | N | A |
| Insider Trade Statistics | `insider-trading/statistics` | N | C |
| Acquisition Ownership | `acquisition-of-beneficial-ownership` | N | E |

### 8.20 MarketPerformance (11)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Market Sector Performance Snapshot | `sector-performance-snapshot` | N | D |
| Industry Performance Snapshot | `industry-performance-snapshot` | N | D |
| Historical Market Sector Performance | `historical-sector-performance` | N | B |
| Historical Industry Performance | `historical-industry-performance` | N | B |
| Sector PE Snapshot | `sector-pe-snapshot` | N | D |
| Industry PE Snapshot | `industry-pe-snapshot` | N | D |
| Historical Sector PE | `historical-sector-pe` | N | B |
| Historical Industry PE | `historical-industry-pe` | N | B |
| Biggest Stock Gainers | `biggest-gainers` | D | D |
| Biggest Stock Losers | `biggest-losers` | D | D |
| Top Traded Stocks | `most-actives` | D | D |

### 8.21 MarketHours (3)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Global Exchange Market Hours | `exchange-market-hours` | D | D |
| Holidays By Exchange | `holidays-by-exchange` | N | A |
| All Exchange Market Hours | `all-exchange-market-hours` | N | D |

### 8.22 TechnicalIndicators (9)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| SMA / EMA / WMA / DEMA / TEMA | `technical-indicators/{sma,ema,wma,dema,tema}` | N | B |
| RSI | `technical-indicators/rsi` | N | B |
| Standard Deviation | `technical-indicators/standarddeviation` | N | B |
| Williams | `technical-indicators/williams` | N | B |
| Average Directional Index | `technical-indicators/adx` | N | B |

### 8.23 News (10)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| FMP Articles | `fmp-articles` | N | E |
| General News | `news/general-latest` | N | E |
| Press Releases | `news/press-releases-latest` | N | E |
| Stock News | `news/stock-latest` | F | E |
| Crypto News | `news/crypto-latest` | N | E |
| Forex News | `news/forex-latest` | N | E |
| Search Press Releases | `news/press-releases` | N | E |
| Search Stock News | `news/stock` | F | E |
| Search Crypto News | `news/crypto` | N | E |
| Search Forex News | `news/forex` | N | E |

### 8.24 Quote (15)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Stock Quote | `quote` | D | D |
| Stock Quote Short | `quote-short` | N | D |
| Aftermarket Trade | `aftermarket-trade` | F | D |
| Aftermarket Quote | `aftermarket-quote` | D | D |
| Stock Price Change | `stock-price-change` | N | D |
| Stock Batch Quote | `batch-quote` | N | D |
| Stock Batch Quote Short | `batch-quote-short` | F | D |
| Batch Aftermarket Trade | `batch-aftermarket-trade` | N | D |
| Batch Aftermarket Quote | `batch-aftermarket-quote` | N | D |
| Exchange Stock Quotes | `batch-exchange-quote` | N | D |
| Mutual Fund Price Quotes | `batch-mutualfund-quotes` | N | D |
| ETF Price Quotes | `batch-etf-quotes` | N | D |
| Full Commodities Quotes | `batch-commodity-quotes` | N | D |
| Full Cryptocurrency Quotes | `batch-crypto-quotes` | N | D |
| Full Forex / Index Quotes | `batch-forex-quotes`, `batch-index-quotes` | N | D |

### 8.25 SecFilings (12)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Latest 8-K SEC Filings | `sec-filings-8k` | N | E |
| Latest SEC Filings | `sec-filings-financials` | F | E |
| SEC Filings By Form Type | `sec-filings-search/form-type` | N | E |
| SEC Filings By Symbol | `sec-filings-search/symbol` | F | E |
| SEC Filings By CIK | `sec-filings-search/cik` | N | E |
| SEC Filings By Name | `sec-filings-company-search/name` | N | E |
| Company Search By Symbol | `sec-filings-company-search/symbol` | N | A |
| Company Search By CIK | `sec-filings-company-search/cik` | N | A |
| SEC Company Full Profile | `sec-profile` | N | C |
| Industry Classification List | `standard-industrial-classification-list` | N | A |
| Industry Classification Search | `industry-classification-search` | N | A |
| All Industry Classification | `all-industry-classification` | N | A |

### 8.26 EarningsTranscript (4)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Latest Earning Transcripts | `earning-call-transcript-latest` | N | E |
| Earnings Transcript | `earning-call-transcript` | F | E |
| Transcripts Dates By Symbol | `earning-call-transcript-dates` | N | A |
| Available Transcript Symbols | `earnings-transcript-list` | N | A |

### 8.27 Senate (12)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Latest Senate Disclosures | `senate-latest` | F | E |
| Latest House Disclosures | `house-latest` | F | E |
| Senate Trading Activity | `senate-trades` | F | E |
| Senate Trades By Name | `senate-trades-by-name` | N | E |
| Senate Trades By ID | `senate-trades-by-id` | N | E |
| U.S. House Trades | `house-trades` | F | E |
| House Trades By Name | `house-trades-by-name` | N | E |
| House Trades By ID | `house-trades-by-id` | N | E |
| Senate Profiles | `senate-profile` | N | A |
| Senate Positions | `senate-positions` | N | A |
| Senate Net Worth | `senate-net-worth` | N | C |
| Senate Net Worth Aggregated | `senate-net-worth-aggregated` | N | C |

### 8.28 Bulk (20)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Company Profile Bulk | `profile-bulk` | N | F |
| Stock Rating Bulk | `rating-bulk` | N | F |
| DCF Valuations Bulk | `dcf-bulk` | N | F |
| Financial Scores Bulk | `scores-bulk` | N | F |
| Price Target Summary Bulk | `price-target-summary-bulk` | N | F |
| ETF Holder Bulk | `etf-holder-bulk` | N | F |
| Upgrades Downgrades Consensus Bulk | `upgrades-downgrades-consensus-bulk` | N | F |
| Key Metrics TTM Bulk | `key-metrics-ttm-bulk` | N | F |
| Ratios TTM Bulk | `ratios-ttm-bulk` | N | F |
| Stock Peers Bulk | `peers-bulk` | N | F |
| Earnings Surprises Bulk | `earnings-surprises-bulk` | N | F |
| Income Statement Bulk | `income-statement-bulk` | N | F |
| Income Statement Growth Bulk | `income-statement-growth-bulk` | N | F |
| Balance Sheet Bulk | `balance-sheet-statement-bulk` | N | F |
| Balance Sheet Growth Bulk | `balance-sheet-statement-growth-bulk` | N | F |
| Cash Flow Bulk | `cash-flow-statement-bulk` | N | F |
| Cash Flow Growth Bulk | `cash-flow-statement-growth-bulk` | N | F |
| EOD Bulk | `eod-bulk` | N | F |

### 8.29 Partners — TipRanks (7)
| Endpoint | stable path | Cov | Arc |
|---|---|---|---|
| Analyst Ratings Search | `tipranks-search` | N | G |
| PIT Ratings by Symbol | `tipranks-pit-symbol` | N | G |
| PIT Ratings by Analyst | `tipranks-pit-analyst` | N | G |
| Ratings Summary by Symbol | `tipranks-symbol-summary` | N | G |
| Ratings Summary by Analyst | `tipranks-analyst-summary` | N | G |
| Ratings Summary by Firm | `tipranks-firm-summary` | N | G |
| Analyst Directory Lookup | `tipranks-analysts` | N | G |

### 8.30 Websockets & Socket.io (out of scope)
`Websockets`, `Socket.io` groups — **Archetype H, not persisted.** Documented in
the provider README as unsupported by `fmp_cached` (use a live streaming client).

> **Catalog note.** A few interval/asset-class rows are collapsed (e.g. the six
> intraday chart intervals, or `quote` shared by index/commodity/crypto/forex).
> Wave 0's expanded audit enumerates each concrete `(path, param-variant)` so the
> final tracked count reconciles to the 276 authoritative URLs.

---

## 9. Phased implementation roadmap

Each wave = one tracking issue + child issues per endpoint, one branch/PR per
endpoint or tight cluster. Sequencing favours (a) unblocking Analysis/portfolio
consumers first, (b) reusing an archetype template before spreading it.

| Wave | Theme | Endpoints | Rationale |
|---|---|---|---|
| **0** | **Inventory + harness** | — | Extend `audit_fmp_cached_coverage.py` to all 276 endpoints + router probe across **both** providers → authoritative D/F/N. Establish the `openbb_fmp` live-fetcher template + plan-limit normalization, the schema-version migration, and the fixture-replay test template. **Gate for all later waves.** |
| **1** | Fundamentals completion (Arc C) | Statements TTM, as-reported, growth (`financial-growth`), `financial-scores`, `owner-earnings`, `enterprise-values`, `key-metrics-ttm`, `ratios-ttm`, DCF ×4 | Highest analytical value; reuses the PIT template already proven by statements. |
| **2** | Quotes & snapshots (Arc D) | All `quote`/`quote-short`/`batch-*`/aftermarket/`stock-price-change`/`market-capitalization*` for equities, index, commodity, crypto, forex | One snapshot template ×N asset classes; unblocks live pricing across markets. |
| **3** | Time-series completion (Arc B) | EOD variants (unadjusted, dividend-adjusted), all intraday intervals for index/commodity/crypto/forex, technical indicators ×9, `historical-market-cap`, historical sector/industry perf & PE | Reuses gap-detection template. |
| **4** | Reference/directory (Arc A) | Search ×7, Directory ×11, lists (commodities/crypto/forex/index), classification lists, holidays, transcript symbol lists | Cheap, high-reuse, powers screeners/warmers. |
| **5** | Event feeds — filings & governance (Arc E) | SEC filings ×12, insider ×6, senate/house ×12, 13F remainder ×6, mergers, delisted, symbol-changes | Append-only template; overlaps existing 13F/insider work. |
| **6** | Event feeds — news, calendars, transcripts, fundraisers, ESG (Arc E) | News ×10, calendars remainder, transcripts ×4, crowdfunding/fundraising ×6, ESG ×3 | Same template as Wave 5. |
| **7** | Analyst & market performance remainder | grades ×3, price-target-summary, ratings history, gainers/losers/actives (verify D), sector/industry snapshots | Fills the Analyst + MarketPerformance gaps. |
| **8** | Bulk (Arc F) + Partners/COT/TipRanks (Arc G) | Bulk ×20, COT ×3, TipRanks ×7 | Lowest priority / most premium-gated; warmer-oriented. |
| **9** | Hardening & docs | — | Full integration sweep, warmers for reference/bulk, README + architecture doc update, plan-limit matrix, mypy/ruff cleanup of new modules. |

**Definition of done per endpoint (two-provider):** (1) **`openbb_fmp` live
fetcher** added (raw HTTP + Query/Data models) and registered, with plan-limit
normalization; (2) `fmp_cached` fetcher subclasses the live fetcher and overrides
`aextract_data`; (3) `create_<name>_table()` added + idempotent; (4) fetcher
registered in `fmp_cached/__init__.py`; (5) structural tests (schema DDL +
registration in **both** providers); (6) fixture integration test asserting
HIT/MISS + plan-limit tolerance; (7) mypy/ruff clean; (8) architecture doc row
added.

---

## 10. Testing strategy

- **Structural (no network, no DB):** each `create_<name>_table()` DDL parses;
  each fetcher subclasses `Fetcher[Q, R]` with resolvable type params (guards the
  RegistryMap `~Q` failure class from `base_cached.py`); `__init__.py` registers
  every new key exactly once.
- **Fixture replay (no live network):** feed the recorded FMP JSON from
  `api-docs.md`/fixture harness through `transform_data`; assert model validation,
  cache write, then a second call reads from cache (HIT) without a live call.
- **Plan-limit path:** simulate `402/403` → assert empty result + `plan_limited`
  marker, no exception.
- **DB-down path:** simulate `init_database()` raising → assert direct-upstream
  fallback.
- **Integration (opt-in, needs key + MySQL):** a nightly job hits a curated
  subset live and records which endpoints are key-gated into the plan-limit
  matrix (§9 Wave 9). Follows the two-phase harness rule (harness writes local
  bug files; a human/agent validates before filing).

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **150+ net-new endpoints** × two providers = large surface | Per-archetype templates + the standard `openbb_fmp` helper pattern make each endpoint near-mechanical; live and persistence changes ship in one paired PR; waves are independently shippable. |
| Table sprawl (~150 tables) | Schema-version migration + opt-in creation for specialty/bulk tables; group-scoped `create_*`. |
| Key tier gates many endpoints | Plan-limit tolerance makes coverage independent of key; matrix documents what's gated. |
| Endpoints reusing shared paths (`quote`, `historical-*`) across asset classes | Register distinct fetchers keyed by asset class / OpenBB router key in both providers; disambiguate by `symbol` semantics in the live fetcher. |
| OpenBB core has no standard model for many endpoints | Register as provider-specific fetchers in **both** `openbb_fmp` and `fmp_cached` under a matching key; document in each README (§6.1). |
| FMP rate limits during warmers | Throttle in `openbb_fmp`'s request path (shared by both providers). |
| Schema drift vs FMP response changes | `data_json` raw column preserves full payload; typed columns are additive/nullable. |

---

## 12. Governance & ownership

This effort spans **two providers**:

- **`openbb_fmp` (live)** — the net-new live fetchers land here. If this fork
  treats `openbb_fmp` as vendored-from-upstream, coordinate these additions with
  whoever owns the upstream sync so they aren't clobbered on the next merge;
  otherwise they are ordinary fork-local provider additions.
- **`fmp_cached` (persistence)** — owned by the **`fmp_cached` provider team**.
  Per the portfolio team's skill policy, portfolio-side work must not open PRs
  adding endpoints to `providers/fmp_cached/`; it files `area:fmp-cached-gap`
  issues instead.

**This document is the `fmp_cached` team's own roadmap** and the consolidation
target for those gap issues. Each paired change (live + persistence) ships
together. Cross-reference the program epic
([scripts/fmp_cache_epic_body.md](../../../scripts/fmp_cache_epic_body.md)) as
the root tracking issue; each wave attaches as a child.

---

## 13. Acceptance criteria (program-level)

1. All **276** FMP stable HTTP endpoints have a live fetcher in **`openbb_fmp`**
   and a persistence-backed fetcher in **`fmp_cached`**, reachable through a
   router endpoint or a provider-specific fetcher; websocket groups documented
   as out of scope in both providers.
2. Every cacheable endpoint has a dedicated MySQL table and archetype-appropriate
   read/write path in `fmp_cached`; no endpoint is a bare credential-only
   fallback except where the data is non-cacheable.
3. `audit_fmp_cached_coverage.py` (extended, probing **both** providers) reports
   **0 N-status and 0 F-without-persistence** endpoints outside the documented
   streaming exclusions.
4. Plan-gated endpoints return empty + `plan_limited` (no exceptions); a matrix
   documents which endpoints our key can/can't reach.
5. Structural + fixture tests green for every endpoint; mypy/ruff clean for all
   new modules; architecture doc lists every endpoint and its archetype.
