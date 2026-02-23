# FinanceToolkit OpenBB App — Project Plan

## 1. Executive Summary

This project exposes the [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) (v2.0.6, 4.5k GitHub stars, MIT license) as a full-fledged OpenBB Pro application with interactive widgets, dashboards, and a rich UX. The FinanceToolkit provides 256+ transparent financial calculations across 10 modules — ratios, models, options/Greeks, technicals, performance, risk, economics, fixed income, discovery, and portfolio — making it one of the most comprehensive open-source financial analysis libraries available.

The app will be deployed as a standalone FastAPI service (similar to the existing Portfolio App on `:6902`) and registered with OpenBB Pro via `widgets.json` and `apps.json`. Users will interact with the toolkit through an intuitive tabbed dashboard interface with filterable, configurable widgets.

---

## 2. Goals & Non-Goals

### Goals

| # | Goal | Rationale |
|---|------|-----------|
| G1 | Expose all 256 FinanceToolkit methods as REST endpoints | Full coverage of the library's capabilities |
| G2 | Design ~50 OpenBB widgets grouped into logical dashboard tabs | Balance granularity vs. usability (many methods are aggregated via `collect_*` functions) |
| G3 | Support multi-ticker analysis (core FinanceToolkit strength) | Comparative analysis is a primary use case |
| G4 | Integrate with the existing OpenBB ecosystem (API key management, CORS, HTTPS) | Seamless user experience alongside Portfolio App and OpenBB API |
| G5 | Leverage FMP API key already configured in OpenBB | Avoid duplicate API key management |
| G6 | Provide caching layer to minimize redundant API calls | FinanceToolkit natively supports `use_cached_data`; extend with server-side cache |
| G7 | Support growth, trailing (TTM), and lag parameters as universal filters | These cross-cutting capabilities apply to all ratio/statement endpoints |

### Non-Goals

- **Not a replacement** for the FinanceToolkit library itself — users can still use it directly in Python/Jupyter
- **Not building charting/visualization logic** — OpenBB Pro handles rendering via widget type definitions
- **Not modifying** the upstream FinanceToolkit source code — we wrap it as-is
- **Not implementing real-time streaming** — the toolkit is batch-oriented by design

---

## 3. Stakeholders & Dependencies

| Stakeholder | Role |
|------------|------|
| End User | Financial analyst using OpenBB Pro dashboard |
| OpenBB Platform | Provides the widget rendering framework, CORS, TLS infrastructure |
| FinancialModelingPrep (FMP) | Primary data source (API key required, free tier = 250 req/day, 5yr data) |
| Yahoo Finance | Fallback data source (no API key, but rate-limited) |
| OECD / FRED / ECB / Euribor | Data sources for Economics and Fixed Income modules |

### External Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| `financetoolkit` | ≥ 2.0.6 | Core library |
| `fastapi` | ≥ 0.100 | REST API framework |
| `uvicorn` | ≥ 0.20 | ASGI server |
| `pandas` | ≥ 2.0 | DataFrame handling |
| Python | ≥ 3.10 | Runtime |

---

## 4. Phased Delivery Plan

### Phase 1: Foundation & Core Data (Weeks 1–2)

**Objective:** Stand up the FastAPI service, expose core Toolkit data retrieval, and register with OpenBB Pro.

| Task | Description | Deliverable |
|------|-------------|-------------|
| 1.1 | Project scaffolding — `finance_toolkit_openbb/` folder structure, `pyproject.toml`, virtual environment | Bootable service |
| 1.2 | FastAPI app with HTTPS (reuse cert infrastructure from `portfolio_app/`) | `main.py`, `run_service.py` |
| 1.3 | Toolkit session manager — singleton Toolkit instance per (tickers, api_key, start_date) combo with caching | `toolkit_manager.py` |
| 1.4 | Core data endpoints: historical data, income statement, balance sheet, cash flow statement, company profile | 5 endpoints |
| 1.5 | `widgets.json` for core widgets (historical table, financial statements) | Widget definitions |
| 1.6 | `apps.json` with initial dashboard layout (2 tabs: Overview, Statements) | App registration |
| 1.7 | Ticker & date parameter endpoints (`/get_tickers`, `/get_periods`) | Filter support |
| 1.8 | Health check, CORS config, error handling middleware | Production readiness |

**Exit Criteria:** Service starts on HTTPS, core data widgets render in OpenBB Pro.

---

### Phase 2: Financial Ratios & Models (Weeks 3–4)

**Objective:** Expose the Ratios module (77 methods) and Models module (9 methods) as widgets.

| Task | Description | Deliverable |
|------|-------------|-------------|
| 2.1 | Ratios collection endpoints — `collect_efficiency_ratios`, `collect_liquidity_ratios`, `collect_profitability_ratios`, `collect_solvency_ratios`, `collect_valuation_ratios` | 5 aggregate endpoints |
| 2.2 | Individual ratio endpoints for the most popular metrics (P/E, P/B, ROE, ROA, Current Ratio, D/E, etc.) | ~20 specific endpoints |
| 2.3 | Growth & trailing parameter support on all ratio endpoints (`growth=True`, `trailing=N`, `lag=N`) | Universal filter controls |
| 2.4 | Models endpoints: DuPont analysis (simple & extended), WACC, DCF intrinsic value, Altman Z-Score, Piotroski F-Score, Gordon Growth, Enterprise Value Breakdown | 9 endpoints |
| 2.5 | Widget definitions for ratio tables and model outputs | `widgets.json` additions |
| 2.6 | Dashboard tabs: "Ratios" and "Models" | `apps.json` update |

**Exit Criteria:** All 5 ratio categories and all 9 models visible as widgets.

---

### Phase 3: Performance, Risk & Technicals (Weeks 5–6)

**Objective:** Expose Performance (16 methods), Risk (10 methods), and Technicals (36 methods).

| Task | Description | Deliverable |
|------|-------------|-------------|
| 3.1 | Performance endpoints: Sharpe, Sortino, Treynor, Jensen's Alpha, Beta, CAPM, Fama-French factors, factor correlations | 16 endpoints |
| 3.2 | Risk endpoints: VaR (Historical, Gaussian, Student-t, Cornish-Fisher), CVaR, EVaR, max drawdown, GARCH, EWMA, Ulcer Index | 10 endpoints |
| 3.3 | Technicals collection endpoints: breadth, momentum, overlap, volatility indicator groups | 4 aggregate + ~15 popular individual endpoints |
| 3.4 | Period parameter support (daily, weekly, monthly, quarterly, yearly) | Universal filter |
| 3.5 | Widget definitions with chart types (line charts for time-series risk/performance metrics) | `widgets.json` additions |
| 3.6 | Dashboard tabs: "Performance & Risk" and "Technicals" | `apps.json` update |

**Exit Criteria:** All three modules fully exposed with appropriate widget types.

---

### Phase 4: Options & Fixed Income (Weeks 7–8)

**Objective:** Expose Options/Greeks (28 methods) and Fixed Income (13 methods).

| Task | Description | Deliverable |
|------|-------------|-------------|
| 4.1 | Options endpoints: Black-Scholes pricing (call/put), Delta, Gamma, Theta, Vega, Rho, and higher-order Greeks (Vomma, Charm, Veta, Vera, Speed, Zomma, Color, Ultima) | 20 endpoints |
| 4.2 | Options collection endpoints: `collect_first_order_greeks`, `collect_second_order_greeks`, `collect_third_order_greeks`, `collect_all_greeks` | 4 aggregate endpoints |
| 4.3 | Options chain data with expiration time range parameter | Chain data endpoint |
| 4.4 | Fixed income endpoints: bond pricing, Macaulay/Modified duration, convexity, YTM, ICE BofA yields, government yields, central bank rates | 13 endpoints |
| 4.5 | Heatmap-style widget support for Options Greeks grids (strike × expiry) | Widget type exploration |
| 4.6 | Dashboard tabs: "Options" and "Fixed Income" | `apps.json` update |

**Exit Criteria:** Full Options Greeks grid and Fixed Income dashboard functional.

---

### Phase 5: Economics, Discovery & Portfolio (Weeks 9–10)

**Objective:** Expose Economics (45 methods), Discovery (13 methods), and Portfolio (9 methods).

| Task | Description | Deliverable |
|------|-------------|-------------|
| 5.1 | Economics endpoints: CPI, GDP, unemployment, interest rates, government debt, trade balance, and 35+ more indicators across 60+ countries | 45 endpoints (grouped into ~10 widgets) |
| 5.2 | Country selector parameter with multi-select support | Country filter |
| 5.3 | Discovery endpoints: stock screener, gainers/losers, most active, sector performance, company quotes | 13 endpoints |
| 5.4 | Portfolio endpoints: load portfolio from XLSX/CSV, get positions, get transactions, calculate PnL (FIFO/LIFO/Average), track positions over time | 9 endpoints |
| 5.5 | Integration with existing Portfolio App data (MySQL) — optional bridge | Cross-app synergy |
| 5.6 | Dashboard tabs: "Economics", "Discovery", "Portfolio" | `apps.json` update |

**Exit Criteria:** All 10 modules fully exposed. Complete feature parity with FinanceToolkit library.

---

### Phase 6: Polish, Optimization & Documentation (Weeks 11–12)

**Objective:** Production hardening, performance optimization, and user documentation.

| Task | Description | Deliverable |
|------|-------------|-------------|
| 6.1 | Server-side caching: LRU cache for Toolkit instances, pickle-based data cache for FMP responses | Cache layer |
| 6.2 | Rate limiting middleware (respect FMP free tier: 250 req/day, starter: 250 req/min) | Rate limiter |
| 6.3 | Error handling: graceful degradation when FMP unavailable, auto-fallback to Yahoo Finance | Resilience |
| 6.4 | Widget parameter groups (linked filters across widgets on same tab) | UX refinement |
| 6.5 | Comprehensive test suite (unit tests for endpoints, integration tests with mock data) | Test coverage |
| 6.6 | User guide: README, setup instructions, screenshots | Documentation |
| 6.7 | Performance benchmarks and optimization (threaded fetching, batch ticker processing) | Performance report |

**Exit Criteria:** Production-ready service with tests, docs, and sub-second widget response times.

---

## 5. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| FMP API rate limits on free tier (250/day) | High | Medium | Server-side caching, Yahoo Finance fallback, batch requests |
| Toolkit object creation is slow for many tickers | Medium | Medium | Singleton session manager with LRU cache; background pre-warming |
| Large DataFrames (1000+ tickers × 30 years) cause timeouts | Medium | High | Pagination, lazy loading, limit default date range |
| FinanceToolkit upstream breaking changes | Low | High | Pin version, integration tests, periodic upgrade checks |
| OpenBB Pro widget schema changes | Low | Medium | Abstract widget config generation; automated schema validation |
| Self-signed HTTPS cert warnings in browsers | Low | Low | Document trust procedure; offer Let's Encrypt alternative |

---

## 6. Success Metrics

| Metric | Target |
|--------|--------|
| Endpoint coverage | 100% of FinanceToolkit's 256 public methods exposed |
| Widget count | ~50 widgets across 10 dashboard tabs |
| Response time (cached) | < 500ms for 95th percentile |
| Response time (cold, 5 tickers) | < 10s for 95th percentile |
| Test coverage | > 80% line coverage on API layer |
| Uptime | Service starts reliably, handles 100 concurrent requests |

---

## 7. Timeline Summary

```
Week  1-2:   Phase 1 — Foundation & Core Data          ████████
Week  3-4:   Phase 2 — Financial Ratios & Models       ████████
Week  5-6:   Phase 3 — Performance, Risk & Technicals  ████████
Week  7-8:   Phase 4 — Options & Fixed Income          ████████
Week  9-10:  Phase 5 — Economics, Discovery & Portfolio ████████
Week 11-12:  Phase 6 — Polish & Documentation          ████████
```

Total estimated effort: **12 weeks** (solo developer, part-time)

---

## 8. Folder Structure (Proposed)

```
finance_toolkit_openbb/
├── docs/
│   ├── PROJECT_PLAN.md          ← This document
│   ├── ARCHITECTURE.md          ← System architecture
│   └── APP_DESIGN.md            ← Detailed widget/UX design
├── app/
│   ├── main.py                  ← FastAPI application
│   ├── toolkit_manager.py       ← Toolkit singleton/session management
│   ├── routers/
│   │   ├── core.py              ← Historical data, financial statements
│   │   ├── ratios.py            ← 77 ratio endpoints
│   │   ├── models.py            ← 9 model endpoints
│   │   ├── options.py           ← 28 options/Greeks endpoints
│   │   ├── technicals.py        ← 36 technical indicator endpoints
│   │   ├── performance.py       ← 16 performance endpoints
│   │   ├── risk.py              ← 10 risk metric endpoints
│   │   ├── economics.py         ← 45 economics endpoints
│   │   ├── fixedincome.py       ← 13 fixed income endpoints
│   │   ├── discovery.py         ← 13 discovery endpoints
│   │   └── portfolio.py         ← 9 portfolio endpoints
│   ├── utils/
│   │   ├── cache.py             ← Caching utilities
│   │   ├── serializers.py       ← DataFrame → JSON serialization
│   │   └── rate_limiter.py      ← FMP rate limiting
│   ├── widgets.json             ← OpenBB widget definitions
│   ├── apps.json                ← OpenBB dashboard layout
│   └── config.py                ← Environment & settings
├── run_service.py               ← HTTPS launcher script
├── cert.pem                     ← SSL certificate (generated)
├── key.pem                      ← SSL private key (generated)
├── pyproject.toml               ← Project metadata & dependencies
├── tests/
│   ├── test_core.py
│   ├── test_ratios.py
│   ├── test_models.py
│   └── ...
└── README.md
```

---

## 9. Open Questions

| # | Question | Options | Decision |
|---|----------|---------|----------|
| Q1 | Should the FinanceToolkit service share the same virtualenv as the Portfolio App (`.venv_openbb`) or have its own? | Shared (simpler) vs. Isolated (cleaner) | TBD |
| Q2 | Should the Portfolio module in FinanceToolkit replace or complement the existing Portfolio App? | Replace / Complement / Bridge | TBD |
| Q3 | What port should the service run on? | `:6903` (next in sequence after `:6901` OpenBB, `:6902` Portfolio) | Recommend `:6903` |
| Q4 | Should we build a unified "super dashboard" that combines Portfolio App + FinanceToolkit widgets? | Yes / No / Later | TBD |
| Q5 | How should FMP API key be managed? | Read from OpenBB config / Separate `.env` / Pass as header | TBD |
