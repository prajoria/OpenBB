# Project Context

> **Purpose:** Comprehensive project overview for AI session startup.
> Load this file at the beginning of every collaboration session so the
> assistant understands the project's goals, architecture, and current state.

---

## 1. What This Project Is

A **personal finance data platform** built on top of a fork of
[OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB).
The fork adds:

1. **`fmp_cached` provider** — A MySQL-backed caching layer for
   Financial Modeling Prep (FMP) API data.  Fetches once, serves from
   cache thereafter.  Supports 67+ financial data models (equity quotes,
   financial statements, ETF holdings, etc.).

2. **`Tools/` scripts** — Standalone CLI utilities that parse brokerage
   exports (Fidelity HTML, ESPP TSV/CSV) and persist structured data to
   MySQL for analysis.

3. **`Tools/fetch_position_history.py`** — Fetches 10 years of daily
   equity price history for every symbol in the portfolio, using the
   `fmp_cached` provider's sync HTTP path.

The upstream OpenBB platform provides the router, provider interface,
data models, and extension system.  This fork's work lives entirely on
the `openbb_learning` branch.

---

## 2. Key Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenBB Platform                         │
│  openbb_platform/core          — Router, provider interface  │
│  openbb_platform/extensions/*  — Equity, ETF, Crypto, etc.  │
│  openbb_platform/providers/*   — Data source adapters        │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │   fmp_cached provider       │
        │   67+ cached models         │
        │   MySQL ← API fallback      │
        └──────────────┬──────────────┘
                       │
        ┌──────────────┴──────────────┐
        │   Tools/ CLI scripts        │
        │   Fidelity parser           │
        │   ESPP loader               │
        │   Position history fetcher  │
        │   Market holidays populator │
        │   Cost basis analyzer       │
        └─────────────────────────────┘
```

### Data Flow

1. **Brokerage HTML/CSV** → `Tools/parse_fidelity_positions.py` or
   `Tools/load_espp_plan.py` → MySQL tables (`Portfolio_Positions`,
   `ESPP_Plan`, `Account_Owner`)

2. **Portfolio symbols** → `Tools/fetch_position_history.py` →
   `fmp_cached` provider → MySQL `equity_historical` table (with
   FMP API as fallback for cache misses)

3. **Any fmp_cached query** → Check MySQL cache → If miss, fetch from
   FMP API → Store in cache → Return data

---

## 3. Technology Stack

| Component      | Technology                                            |
|----------------|-------------------------------------------------------|
| Language       | Python 3.12                                           |
| Platform       | OpenBB v4 (provider/router architecture)              |
| Database       | MySQL 8 (localhost:3306)                              |
| DB driver      | PyMySQL                                               |
| HTTP (sync)    | `requests` library (aiohttp broken on Windows 3.12)  |
| HTTP (async)   | aiohttp (NOT usable on Windows — CancelledError bug)  |
| Data frames    | pandas                                                |
| HTML parsing   | BeautifulSoup4                                        |
| API source     | Financial Modeling Prep (FMP)                         |
| OS             | Windows (primary development)                         |
| Venv           | `.venv_win` (project-local, Windows-specific)         |
| Git branch     | `openbb_learning`                                     |

---

## 4. Databases

Two MySQL databases are in use:

| Database              | Purpose                                            |
|-----------------------|----------------------------------------------------|
| `openbb_fmp_cache`    | Default fmp_cached provider cache (67+ tables)     |
| `openbb_fmp_cache_test` | Portfolio-specific data (positions, history, holidays) |

**Important:** Most Tools/ scripts and portfolio data live in
`openbb_fmp_cache_test`.  The default `openbb_fmp_cache` is for general
provider caching.

### Key Tables (in `openbb_fmp_cache_test`)

| Table                 | Rows    | Source Script                   |
|-----------------------|---------|---------------------------------|
| `Portfolio_Positions` | ~185+   | `parse_fidelity_positions.py`   |
| `Account_Owner`       | 6       | `parse_fidelity_positions.py`   |
| `ESPP_Plan`           | varies  | `load_espp_plan.py`             |
| `equity_historical`   | 143,936 | `fetch_position_history.py`     |
| `market_holidays`     | 162     | `populate_market_holidays.py`   |

---

## 5. FMP API Details

- **Endpoint:** `https://financialmodelingprep.com/stable/historical-price-eod/full`
- **Date params:** `from` and `to` (NOT `start_date`/`end_date`)
- **API key source:** `~/.openbb_platform/user_settings.json`
  (under `credentials.fmp_api_key`)
- **Sync fetcher:** `_fetch_from_fmp_sync()` in
  `openbb_fmp_cached/models/equity_historical.py` — uses `requests`
- **Async fetcher:** `_fetch_from_fmp_direct()` — uses aiohttp
  (BROKEN on Windows, do not use)

---

## 6. Known Platform Gotchas

| Issue | Details |
|-------|---------|
| **aiohttp CancelledError** | `asyncio.CancelledError` in `protocol.read()` on Windows Python 3.12. Workaround: use sync `requests` path. |
| **Windows encoding** | Must call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` before any Unicode output. |
| **Auto-create overhead** | Set `FMP_CACHE_AUTO_CREATE_DB=false` env var to skip 67-table creation on every import. |
| **BRKB ticker** | Stored as `BRKB` in portfolio but FMP expects `BRK-B`. Not yet mapped. |
| **Holiday gap detection** | `_get_basic_market_holidays()` has a comprehensive computed fallback but DB-sourced holidays may not cover all edge cases. |

---

## 7. Current State (as of latest session)

- **83/83 portfolio symbols** fetched successfully (100,399 rows)
- **82/83 symbols** have history in `equity_historical` (143,936 rows)
- Only **BRKB** is missing (needs `BRK-B` mapping)
- **162 market holidays** populated (2010–2026)
- **6 Fidelity accounts** mapped to owner
- All Tools/ scripts functional and tested

---

## 8. Files to Load for Full Context

| File | Purpose | Committed? |
|------|---------|------------|
| `rules/PROJECT_CONTEXT.md` | This file — project overview | Yes |
| `rules/CODEBASE_MAP.md` | File inventory and navigation guide | Yes |
| `rules/DEVELOPMENT_RULES.md` | Technical coding standards | Yes |
| `rules/DOMAIN_KNOWLEDGE.md` | Finance & tax domain concepts | Yes |
| `rules/COLLABORATION_RULES.md` | PII hygiene, git workflow, checklists | Yes |
| `Tools/docs/DESIGN.md` | Architecture, schemas, changelog | Yes |
| `Tools/docs/CONTEXT_LOCAL.md` | Local paths, credentials, state | No (git-ignored) |

---

*Last updated: 2026-02-20*
