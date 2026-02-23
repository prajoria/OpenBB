# FinanceToolkit OpenBB App — System Architecture

## 1. Architecture Overview

The FinanceToolkit OpenBB App follows the same architectural pattern established by the existing Portfolio App: a **standalone FastAPI microservice** that registers with OpenBB Pro via `widgets.json` and `apps.json`, served over HTTPS alongside the existing services.

```
┌─────────────────────────────────────────────────────────────────┐
│                        OpenBB Pro UI                            │
│                   https://pro.openbb.co                         │
│                                                                 │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐  │
│  │ Portfolio     │  │ FinanceToolkit   │  │ OpenBB Platform   │  │
│  │ Dashboards   │  │ Dashboards       │  │ Dashboards        │  │
│  └──────┬───────┘  └────────┬─────────┘  └────────┬──────────┘  │
│         │                   │                      │            │
└─────────┼───────────────────┼──────────────────────┼────────────┘
          │ HTTPS             │ HTTPS                │ HTTPS
          ▼                   ▼                      ▼
┌─────────────────┐ ┌──────────────────┐ ┌────────────────────────┐
│  Portfolio App  │ │ FinanceToolkit   │ │  OpenBB API            │
│  FastAPI        │ │ App (FastAPI)    │ │  (openbb-api)          │
│  :6902          │ │ :6903            │ │  :6901                 │
│                 │ │                  │ │                        │
│  MySQL DB       │ │  FinanceToolkit  │ │  OpenBB Extensions     │
│  (positions)    │ │  Library         │ │  (fmp, yfinance, etc.) │
└─────────────────┘ └────────┬─────────┘ └────────────────────────┘
                             │
                    ┌────────┴─────────┐
                    │  External APIs   │
                    │                  │
                    │  ┌─────────────┐ │
                    │  │ FMP API     │ │  (Primary — financials, historical, options)
                    │  └─────────────┘ │
                    │  ┌─────────────┐ │
                    │  │ Yahoo Fin   │ │  (Fallback — historical prices)
                    │  └─────────────┘ │
                    │  ┌─────────────┐ │
                    │  │ OECD / FRED │ │  (Economics module)
                    │  └─────────────┘ │
                    │  ┌─────────────┐ │
                    │  │ ECB/Euribor │ │  (Fixed Income module)
                    │  └─────────────┘ │
                    └──────────────────┘
```

---

## 2. Service Architecture

### 2.1 Three-Service Topology

| Service | Port | Purpose | Tech Stack |
|---------|------|---------|------------|
| **OpenBB API** | `:6901` | OpenBB Platform core — equity data, news, economics via extensions | `openbb-api`, uvicorn |
| **Portfolio App** | `:6902` | Personal portfolio tracking — positions, cost basis, tax lots, ESPP | FastAPI, MySQL |
| **FinanceToolkit App** | `:6903` | Financial analysis — ratios, models, Greeks, technicals, risk, performance | FastAPI, `financetoolkit` |

All three services:
- Serve over HTTPS with shared self-signed certificates (`cert.pem`, `key.pem`)
- Configure CORS for `https://pro.openbb.co` and `https://127.0.0.1:*`
- Expose `/widgets.json` and a subset expose `/apps.json` for OpenBB Pro registration
- Include a `/health` endpoint for monitoring

### 2.2 Why a Separate Service (Not an OpenBB Extension)?

| Consideration | OpenBB Extension | Standalone FastAPI |
|--------------|------------------|--------------------|
| Deployment independence | Tied to OpenBB API lifecycle | Independent start/stop/upgrade |
| Dependency isolation | Shares OpenBB's virtualenv & dependency tree | Own virtualenv, no conflicts |
| FinanceToolkit version pinning | Must align with OpenBB releases | Pin independently |
| Custom caching strategies | Limited to OpenBB's caching | Full control (LRU, pickle, Redis) |
| Widget JSON control | Must follow OpenBB extension patterns | Full `widgets.json`/`apps.json` control |
| Development velocity | Slower (PR-based contribution) | Fast iteration |

**Decision: Standalone FastAPI service** — mirrors the proven Portfolio App pattern.

---

## 3. Internal Architecture

```
finance_toolkit_openbb/app/
│
├── main.py                     ← FastAPI app factory, middleware, CORS
│
├── config.py                   ← Settings (FMP key, ports, cache config)
│   └── reads from: .env, environment variables, OpenBB config
│
├── toolkit_manager.py          ← Session management & Toolkit lifecycle
│   ├── ToolkitSession           (dataclass: tickers, api_key, start_date, toolkit)
│   ├── SessionCache             (LRU cache of active Toolkit instances)
│   └── get_or_create_toolkit()  (factory with cache lookup)
│
├── routers/                    ← FastAPI APIRouter modules (one per FT module)
│   ├── core.py                  ← 18 endpoints: historical, statements, profile
│   ├── ratios.py                ← ~25 endpoints: 5 collect + 20 individual ratios
│   ├── models.py                ← 9 endpoints: DuPont, WACC, DCF, Altman, etc.
│   ├── options.py               ← ~22 endpoints: pricing, Greeks, chains
│   ├── technicals.py            ← ~19 endpoints: 4 collect + 15 individual
│   ├── performance.py           ← 16 endpoints: Sharpe, Beta, CAPM, Fama-French
│   ├── risk.py                  ← 10 endpoints: VaR, CVaR, drawdown, GARCH
│   ├── economics.py             ← ~15 endpoints (grouped): CPI, GDP, rates, etc.
│   ├── fixedincome.py           ← 13 endpoints: bonds, yields, central banks
│   ├── discovery.py             ← 13 endpoints: screener, gainers, sectors
│   └── portfolio.py             ← 9 endpoints: positions, transactions, PnL
│
├── utils/
│   ├── serializers.py           ← DataFrame → JSON for OpenBB widget consumption
│   │   ├── df_to_records()       (multi-index aware, handles NaN)
│   │   ├── df_to_chart_data()    (time-series format for line/bar charts)
│   │   └── df_to_grid_data()     (strike×expiry grid for options heatmaps)
│   ├── cache.py                 ← Caching layer
│   │   ├── InMemoryCache         (LRU with TTL)
│   │   ├── PickleCache           (disk-based, leverages FT's use_cached_data)
│   │   └── cache_key_from()      (deterministic key generation)
│   └── rate_limiter.py          ← Token bucket rate limiter for FMP
│       ├── RateLimiter class
│       └── Middleware integration
│
├── widgets.json                 ← ~50 widget definitions
└── apps.json                    ← Dashboard with 10 tabs
```

---

## 4. Key Architectural Decisions

### 4.1 Toolkit Session Management

The FinanceToolkit's `Toolkit` class is the central object — it holds tickers, API keys, date ranges, and fetched data. Creating a new instance triggers API calls. We need to **reuse instances** across requests.

```
┌────────────────────────────────────────────────────┐
│              Toolkit Session Cache                  │
│                                                     │
│  Key: (frozenset(tickers), api_key, start_date)    │
│  Value: Toolkit instance + last_accessed timestamp  │
│                                                     │
│  Policy: LRU with max 20 sessions, 30min TTL       │
│  Background: evict expired sessions every 5min      │
└────────────────────────────────────────────────────┘
```

**Request flow:**
1. Incoming request → extract `tickers`, `start_date` from query params
2. Look up `(tickers, api_key, start_date)` in session cache
3. Cache hit → reuse Toolkit instance (data already fetched) → fast response
4. Cache miss → create new Toolkit instance → fetch data → cache → respond

### 4.2 DataFrame Serialization Strategy

The FinanceToolkit returns pandas DataFrames with multi-level indices (ticker × date). OpenBB widgets expect flat JSON arrays. The serialization layer must handle:

| FT Output Format | Widget Type | Serialization |
|-----------------|-------------|---------------|
| DataFrame with MultiIndex (ticker, date) | Table | Flatten to records, add `ticker` column |
| DataFrame with period columns (2019, 2020, ...) | Table | Transpose or pivot as needed |
| DataFrame with strike × expiry grid | Heatmap / Table | Grid format with row/column headers |
| Single-value Series | KPI card | `{"ticker": "AAPL", "value": 0.28, "metric": "ROE"}` |
| Time-series DataFrame | Line chart | `[{"date": "2023-01-01", "AAPL": 0.28, "MSFT": 0.35}]` |

### 4.3 Parameter Inheritance Pattern

Many FinanceToolkit methods accept the same cross-cutting parameters. These should be exposed as reusable widget filter controls:

```
Universal Parameters (appear on most widgets):
├── tickers      : text (comma-separated, e.g., "AAPL,MSFT,GOOGL")
├── start_date   : date picker
├── end_date     : date picker
├── quarterly    : boolean (annual vs. quarterly data)
├── growth       : boolean (show growth rates)
├── trailing     : integer (trailing periods, e.g., 4 for TTM)
└── lag          : integer (lagged growth periods)

Module-Specific Parameters:
├── Ratios/Models: (no additional)
├── Options:      strike_price_range, expiration_time_range, put_option
├── Technicals:   window (lookback period)
├── Performance:  period (daily/weekly/monthly/quarterly/yearly)
├── Risk:         period, alpha (confidence level)
├── Economics:    countries (multi-select), indicator_type
├── Fixed Income: maturity, bond_type
└── Discovery:    exchange, market_cap_min/max, sector
```

### 4.4 Caching Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Caching Layers                           │
│                                                                 │
│  Layer 1: Toolkit Instance Cache (in-memory LRU)               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Caches entire Toolkit objects (with pre-fetched data)       ││
│  │ Key: (tickers, api_key, start_date)                        ││
│  │ TTL: 30 minutes  │  Max entries: 20                        ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  Layer 2: FinanceToolkit's Built-in Cache (pickle files)       │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ `Toolkit(use_cached_data="./cache/")`                      ││
│  │ Caches raw FMP/YF API responses to disk                    ││
│  │ Survives service restarts                                  ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  Layer 3: Response Cache (optional, in-memory)                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ Caches serialized JSON responses                           ││
│  │ Key: (endpoint, all_params_hash)                           ││
│  │ TTL: 5 minutes  │  Invalidated on ticker/date change       ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 4.5 Error Handling Strategy

```
FinanceToolkit Exception Hierarchy:
│
├── FMP API errors (401, 403, 429)
│   ├── 401/403 → "Invalid or missing FMP API key"
│   ├── 429 → "Rate limit exceeded, retry after {N}s"
│   └── Fallback → Try Yahoo Finance if enforce_source != "FinancialModelingPrep"
│
├── Data unavailability
│   ├── Ticker not found → 404 with helpful message
│   ├── No data for date range → 200 with empty result + warning
│   └── Partial data (some tickers failed) → 200 with available data + warnings
│
├── Computation errors
│   ├── Division by zero in ratios → NaN in DataFrame → null in JSON
│   ├── Missing prerequisite data (e.g., need balance sheet for ratios) → auto-fetch
│   └── Invalid parameters → 422 with validation error details
│
└── Infrastructure errors
    ├── Timeout → 504 with retry guidance
    ├── OOM (too many tickers) → 413 with pagination guidance
    └── General → 500 with error ID for debugging
```

---

## 5. Data Flow Diagrams

### 5.1 Standard Request Flow (e.g., Profitability Ratios)

```
OpenBB Pro UI                    FT App (:6903)              FinanceToolkit           FMP API
     │                                │                          │                      │
     │  GET /ratios/profitability     │                          │                      │
     │  ?tickers=AAPL,MSFT            │                          │                      │
     │  &start_date=2020-01-01        │                          │                      │
     │  &trailing=4&quarterly=true    │                          │                      │
     │ ──────────────────────────────►│                          │                      │
     │                                │                          │                      │
     │                                │  Check session cache     │                      │
     │                                │  Key=(AAPL,MSFT,2020)   │                      │
     │                                │                          │                      │
     │                          [CACHE MISS]                     │                      │
     │                                │                          │                      │
     │                                │  Toolkit(                │                      │
     │                                │    tickers=[AAPL,MSFT],  │                      │
     │                                │    api_key=XXX,          │                      │
     │                                │    start_date=2020-01-01,│                      │
     │                                │    quarterly=True        │                      │
     │                                │  )                       │                      │
     │                                │ ────────────────────────►│                      │
     │                                │                          │  GET /income-statement│
     │                                │                          │  GET /balance-sheet   │
     │                                │                          │  GET /cash-flow       │
     │                                │                          │──────────────────────►│
     │                                │                          │                      │
     │                                │                          │◄─────(JSON data)─────│
     │                                │                          │                      │
     │                                │  tk.ratios               │                      │
     │                                │    .collect_profitability │                      │
     │                                │    _ratios(trailing=4)   │                      │
     │                                │ ────────────────────────►│                      │
     │                                │                          │                      │
     │                                │◄──(DataFrame)────────────│                      │
     │                                │                          │                      │
     │                                │  serialize(df)           │                      │
     │                                │  cache session           │                      │
     │                                │                          │                      │
     │◄──────(JSON array)─────────────│                          │                      │
     │                                │                          │                      │
     │  Render table widget           │                          │                      │
```

### 5.2 Economics Module Flow (No Ticker Required)

```
OpenBB Pro UI                    FT App (:6903)              FinanceToolkit           OECD API
     │                                │                          │                      │
     │  GET /economics/unemployment   │                          │                      │
     │  ?countries=US,GB,DE,JP        │                          │                      │
     │  &start_date=2010-01-01        │                          │                      │
     │ ──────────────────────────────►│                          │                      │
     │                                │                          │                      │
     │                                │  Economics(              │                      │
     │                                │    countries=US,GB,DE,JP │                      │
     │                                │  )                       │                      │
     │                                │  .get_unemployment_rate()│                      │
     │                                │ ────────────────────────►│                      │
     │                                │                          │  GET OECD endpoint   │
     │                                │                          │──────────────────────►│
     │                                │                          │◄────(data)───────────│
     │                                │◄──(DataFrame)────────────│                      │
     │                                │                          │                      │
     │◄──────(JSON array)─────────────│                          │                      │
```

The Economics module is notable because it uses `from financetoolkit import Economics` as a standalone class — no tickers or FMP key needed. Similarly, `from financetoolkit import FixedIncome` is standalone.

---

## 6. Security Architecture

### 6.1 HTTPS / TLS

- Reuse the self-signed cert/key pair from `portfolio_app/` (or generate a dedicated pair)
- `uvicorn` runs with `ssl_certfile` and `ssl_keyfile` parameters
- All inter-service communication (if any) uses `verify=False` for self-signed certs

### 6.2 API Key Management

```
Priority chain for FMP API key:
1. FMP_API_KEY environment variable
2. OPENBB_FMP_API_KEY environment variable  
3. .env file in service directory
4. OpenBB user preferences (~/.openbb_platform/)
5. Request-level header: X-FMP-API-Key (per-request override)
```

The API key is **never logged** and **never returned** in API responses.

### 6.3 CORS Policy

```python
ALLOWED_ORIGINS = [
    "https://pro.openbb.co",
    "https://excel.openbb.co",
    "https://127.0.0.1:1420",   # Tauri desktop app
    "https://localhost:1420",
    "http://localhost:3000",     # Local development
]
```

### 6.4 Input Validation

- Tickers: validated against `[A-Z0-9.\-^]+` pattern, max 50 per request
- Dates: validated as ISO 8601 (`YYYY-MM-DD`), max range 30 years
- Numeric params (trailing, lag, window): validated range with sensible defaults
- Countries: validated against known ISO 3166-1 alpha-2 codes

---

## 7. Deployment Architecture

### 7.1 Development (Current Setup)

```
Windows machine (I:\masterswork\git\OpenBB\)
│
├── .venv_openbb/                    ← Shared virtualenv (OR)
├── finance_toolkit_openbb/.venv/    ← Dedicated virtualenv
│
├── portfolio_app/
│   └── run_portfolio.py             ← python run_portfolio.py (port 6902)
│
├── finance_toolkit_openbb/
│   └── run_service.py               ← python run_service.py (port 6903)
│
└── portfolio_app/
    └── run_openbb_api.py            ← python run_openbb_api.py (port 6901)
```

### 7.2 Production (Future)

```
┌─────────────────────────────────────────────────┐
│              Reverse Proxy (nginx/caddy)         │
│              HTTPS termination                   │
│              *.yourdomain.com                    │
│                                                  │
│  /api/openbb/*     → localhost:6901              │
│  /api/portfolio/*  → localhost:6902              │
│  /api/toolkit/*    → localhost:6903              │
└──────────────────────┬──────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    OpenBB API    Portfolio App  FT App
    (uvicorn)     (uvicorn)     (uvicorn)
    :6901         :6902         :6903
```

### 7.3 Docker (Future)

```yaml
# docker-compose.yml (conceptual)
services:
  openbb-api:
    build: ./portfolio_app
    command: python run_openbb_api.py
    ports: ["6901:6901"]
    
  portfolio-app:
    build: ./portfolio_app
    command: python run_portfolio.py
    ports: ["6902:6902"]
    depends_on: [mysql]
    
  finance-toolkit:
    build: ./finance_toolkit_openbb
    command: python run_service.py
    ports: ["6903:6903"]
    environment:
      - FMP_API_KEY=${FMP_API_KEY}
    volumes:
      - ft-cache:/app/cache  # Persistent pickle cache
      
  mysql:
    image: mysql:8.0
    ports: ["3306:3306"]

volumes:
  ft-cache:
```

---

## 8. Integration Points

### 8.1 With OpenBB Pro UI

| Integration | Mechanism |
|------------|-----------|
| Widget registration | `GET /widgets.json` returns all widget definitions |
| Dashboard registration | `GET /apps.json` returns tabbed dashboard layout |
| Data retrieval | Individual widget endpoints return JSON arrays |
| Parameter options | Dynamic option endpoints (e.g., `/get_tickers`, `/get_countries`) |
| Linked filters | `groups` in `apps.json` link parameters across widgets on same tab |

### 8.2 With Existing Portfolio App (Optional Future)

| Integration | Description |
|------------|-------------|
| Ticker sync | Portfolio App's positions → auto-populate FinanceToolkit's tickers |
| Portfolio analysis | Run FinanceToolkit's ratios/performance on portfolio holdings |
| Unified dashboard | Combined tab showing portfolio positions + toolkit analysis |

### 8.3 With OpenBB API (Optional Future)

| Integration | Description |
|------------|-------------|
| Data sourcing | Use OpenBB API's FMP extension instead of direct FMP calls |
| Extension bridging | Expose FinanceToolkit calculations as an OpenBB extension |

---

## 9. Performance Considerations

### 9.1 Bottlenecks & Mitigations

| Bottleneck | Expected Impact | Mitigation |
|-----------|----------------|------------|
| Toolkit instantiation (API calls) | 5-15s for 5 tickers | Session cache, pickle cache, pre-warming |
| Large DataFrame serialization | 100-500ms for 30yr×100 tickers | Streaming JSON, pagination, truncation |
| Concurrent requests to same Toolkit | Lock contention | Read-write lock per session, async where possible |
| FMP rate limits | 250 req/day (free), 250 req/min (starter) | Server-side rate limiter, batch requests, fallback to Yahoo |
| OECD/FRED API latency | 2-5s for economics data | Aggressive disk caching (data changes monthly) |

### 9.2 Scalability Limits

- **Single Toolkit instance**: handles well up to ~100 tickers × 30 years
- **Concurrent users**: uvicorn workers (recommend 2-4 for development)
- **Memory**: ~500MB per Toolkit instance with 50 tickers
- **Disk cache**: ~10MB per ticker set (pickle files)

---

## 10. Technology Stack Summary

```
┌──────────────────────────────────────┐
│           Presentation Layer         │
│  OpenBB Pro (React, AG-Grid, D3.js) │
└──────────────┬───────────────────────┘
               │ HTTPS / JSON
┌──────────────┴───────────────────────┐
│           API Layer                   │
│  FastAPI + uvicorn + Pydantic        │
│  10 APIRouters (one per module)      │
└──────────────┬───────────────────────┘
               │
┌──────────────┴───────────────────────┐
│           Business Logic Layer       │
│  FinanceToolkit v2.0.6               │
│  256 methods, 10 modules             │
│  Pandas DataFrames                   │
└──────────────┬───────────────────────┘
               │
┌──────────────┴───────────────────────┐
│           Data Layer                 │
│  FMP API (primary)                   │
│  Yahoo Finance (fallback)            │
│  OECD / FRED / ECB (economics)       │
│  Pickle cache (disk persistence)     │
└──────────────────────────────────────┘
```
