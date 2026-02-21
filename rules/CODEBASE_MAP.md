# Codebase Map

> **Purpose:** Quick-reference inventory of all custom files in this fork.
> Use this to navigate the codebase and understand file relationships.

---

## 1. Tools/ — CLI Scripts

| File | Lines | Purpose | DB Tables | Status |
|------|-------|---------|-----------|--------|
| `parse_fidelity_positions.py` | ~870 | Parse Fidelity "Portfolio Positions" HTML (ag-grid) into structured rows | `Portfolio_Positions`, `Account_Owner` | Complete |
| `load_espp_plan.py` | ~540 | Parse ESPP purchase history (TSV/CSV) into MySQL | `ESPP_Plan` | Complete |
| `fetch_position_history.py` | ~395 | Fetch daily equity price history for all portfolio symbols via fmp_cached sync path | `equity_historical` | Complete |
| `populate_market_holidays.py` | ~200 | Compute and populate US stock market holidays (NYSE/NASDAQ) | `market_holidays` | Complete |
| `share_cost_basis.py` | ~310 | Standalone cost-basis / gain-loss analyzer (no DB) | — | Complete |
| `build_sp500_constituents.py` | ~100 | Populate `sp500_constituents` via fmp_cached provider | (via provider) | Complete |
| `_query_history_stats.py` | ~50 | Quick stats query: portfolio symbols in equity_historical | — | Utility |
| `_debug_cols.py` | small | Debug helper for column inspection | — | Utility |

### Tools/docs/

| File | Purpose | Committed? |
|------|---------|------------|
| `DESIGN.md` | Living architecture doc: schemas, decisions, changelog | Yes |
| `CONTEXT_LOCAL.md` | Local paths, credentials, account details | No (git-ignored) |
| `load_espp_plan.md` | User-facing documentation for ESPP loader | Yes |

---

## 2. rules/ — Session Context & Standards

| File | Purpose |
|------|---------|
| `PROJECT_CONTEXT.md` | Project overview, architecture, stack, current state |
| `CODEBASE_MAP.md` | This file — file inventory and navigation |
| `DEVELOPMENT_RULES.md` | Technical coding standards, patterns, gotchas |
| `COLLABORATION_RULES.md` | PII hygiene, git workflow, session checklists |

---

## 3. fmp_cached Provider

Located at `openbb_platform/providers/fmp_cached/`.

### Core Module: `openbb_fmp_cached/`

| File | Purpose |
|------|---------|
| `__init__.py` | Provider registration with OpenBB |
| `models/__init__.py` | Model registry |
| `models/equity_historical.py` | **Key file (~1219 lines)**: Cache gap detection, sync+async FMP fetching, MySQL storage, holiday-aware gap analysis |
| `models/base_cached.py` | Base class for all cached models |
| `models/*.py` (65+ files) | Cached models for financial data (balance sheet, income statement, ETF holdings, etc.) |
| `utils/database.py` | `DatabaseConfig`, `get_connection()`, `init_database()` |

### Key Functions in `equity_historical.py`

| Function | Purpose |
|----------|---------|
| `_analyze_cache_gaps()` | Detect missing date ranges in cached data |
| `_detect_missing_ranges()` | Compare expected trading days vs cached dates |
| `_store_in_database_cache()` | Write fetched data to MySQL |
| `_fetch_from_fmp_sync()` | **Sync HTTP fetch** using `requests` (Windows-safe) |
| `_fetch_from_fmp_direct()` | Async HTTP fetch using aiohttp (BROKEN on Windows) |
| `_get_basic_market_holidays()` | Holiday computation with DB + computed fallback |
| `_is_trading_day()` | Check if a date is a valid trading day |

### Supporting Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Package configuration |
| `pytest.ini` | Test configuration |
| `tests/` | Test suite |
| `README.md` | Provider documentation |
| Various `.md` files | Migration/setup guides |

---

## 4. Project Root Files (Custom)

| File | Purpose |
|------|---------|
| `pytest.ini` | Root pytest configuration |
| `pyrightconfig.json` | Type-checking configuration |
| `ruff.toml` | Linter configuration |
| `docs/PROJECT_DOCUMENTATION.md` | Comprehensive OpenBB platform documentation |
| `SETUP_GUIDE.md` | Environment setup instructions |
| `QUICK_START.md` | Getting started guide |
| `examples_usage.py` | Usage examples |
| `test_openbb.py` | Platform integration test |
| `test_db_creation_flag.py` | DB creation flag test |

---

## 5. Key Dependencies Between Files

```
Tools/parse_fidelity_positions.py
  └── imports: openbb_fmp_cached.utils.database (DatabaseConfig, get_connection)

Tools/load_espp_plan.py
  └── imports: openbb_fmp_cached.utils.database (DatabaseConfig, get_connection)

Tools/fetch_position_history.py
  └── imports: openbb_fmp_cached.utils.database (DatabaseConfig, init_database)
  └── imports: openbb_fmp_cached.models.equity_historical
      (FMPEquityHistoricalFetcher, _fetch_from_fmp_sync,
       _analyze_cache_gaps, _store_in_database_cache)
  └── imports: openbb_core.app.service.user_service (API key resolution)

Tools/populate_market_holidays.py
  └── imports: openbb_fmp_cached.utils.database (DatabaseConfig, get_connection)

Tools/build_sp500_constituents.py
  └── imports: fmp_cached provider (via OpenBB router)
```

---

## 6. MySQL Table Dependencies

```
Portfolio_Positions ──┐
                      ├── account_name links to ──► Account_Owner
                      │
equity_historical ────┤
                      ├── symbol matches Portfolio_Positions.symbol
                      │
market_holidays ──────┘  (used by equity_historical gap detection)

ESPP_Plan ──── standalone (symbol = 'MSFT')
```

---

## 7. sys.path Bootstrap Pattern

All Tools/ scripts use this pattern to enable source-tree imports without
`pip install -e`:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[1]
for sub in ["openbb_platform/providers/fmp_cached",
            "openbb_platform/providers/fmp",
            "openbb_platform/core",
            "openbb_platform/platform",
            ...all extensions...]:
    sys.path.insert(0, str(PROJECT_ROOT / sub))
```

---

*Last updated: 2026-02-20*
