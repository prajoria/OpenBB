# OpenBB Portfolio Extension

An official OpenBB Platform extension that integrates personal portfolio management, ESPP tracking, and 7-phase single-stock analysis into the OpenBB Workspace as first-class widgets.

## Architecture

This extension is a **unified service** — it runs inside the same `openbb-api` process as the OpenBB Platform API.  There is no separate service, no HTTP proxy, and no second port to manage.

```
OpenBB Workspace
      │
      ▼  https://127.0.0.1:6902
┌─────────────────────────────────┐
│  OpenBB Platform API            │
│  (openbb-api --app launch.py)   │
│                                 │
│  /api/v1/*  ←── market data     │
│  /portfolio/* ─── portfolio DB  │
│  /stock/*   ─── stock analysis  │
│  /espp/*    ─── ESPP tracking   │
│                                 │
│  /widgets.json  (merged)        │
│  /apps.json     (merged)        │
└─────────────────────────────────┘
         │  in-process
         ▼  obb.equity.price.quote(...)
  OpenBB Python SDK → FMP / yfinance / ...
```

## Data Sources

| Route prefix | Data source |
|---|---|
| `/api/v1/*` | OpenBB Platform providers (FMP, yfinance, etc.) |
| `/portfolio/*` | MySQL — `portfolio_basket` table (sanitised, safe to serve) |
| `/stock/*` | OpenBB Python SDK → `obb.*` calls (in-process, no HTTP proxy) |
| `/espp/*` | MySQL — `ESPP_Plan` table |
| `/equity/historical` | MySQL — `equity_historical` cache table |

## Setup

### Prerequisites
- Python 3.10–3.13
- OpenBB Platform installed (editable or from PyPI)
- MySQL database with `portfolio_basket`, `equity_historical`, `ESPP_Plan` tables
- `.env` at the project root with `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`

### Install

```bash
cd openbb_platform/extensions/portfolio
pip install -e .
```

### Start

```bash
# With HTTPS (recommended for OpenBB Workspace)
openbb-api --app openbb_platform/extensions/portfolio/launch.py \
  --ssl_certfile portfolio_app/cert.pem \
  --ssl_keyfile  portfolio_app/key.pem \
  --port 6902

# Without SSL (development)
openbb-api --app openbb_platform/extensions/portfolio/launch.py --port 6900
```

### Configure OpenBB Workspace

Add a single backend: `https://127.0.0.1:6902`

The **Portfolio Overview** app (with tabs: Overview, Positions, Cost Basis & Tax, Trends, ESPP, Stock Analysis) will appear automatically.

## Extension Structure

```
portfolio/
├── openbb_portfolio/
│   ├── __init__.py
│   ├── portfolio_router.py  ← All FastAPI route handlers (APIRouter)
│   ├── _obb_data.py         ← OpenBB SDK data helpers (in-process market data)
│   ├── _cache.py            ← TTL async cache for stock analysis results
│   ├── stock_analysis.py    ← 7-phase analysis pure functions
│   ├── db.py                ← MySQL connection utilities
│   └── data.py              ← Portfolio data layer (DataFrame queries)
├── assets/
│   ├── widgets.json         ← 15 widget definitions for OpenBB Workspace
│   └── apps.json            ← Portfolio Overview app template
├── launch.py                ← Entry script for openbb-api --app
├── pyproject.toml
└── README.md
```

## Widget Index

### Portfolio Widgets
| Widget | Endpoint | Description |
|---|---|---|
| Portfolio Summary | `/portfolio/summary` | Aggregated per-symbol totals |
| Portfolio Positions | `/portfolio/positions` | Lot-level positions (blocked in API) |
| Account Allocation | `/portfolio/allocation` | Per-account breakdown |
| Cost Basis Detail | `/portfolio/cost_basis` | Lot-level cost basis |
| Tax Summary | `/portfolio/tax_summary` | Short/long-term classification |
| Performance Ranking | `/portfolio/performance` | Top gainers/losers |
| Snapshot History | `/portfolio/snapshots` | Portfolio value over time |
| ESPP Purchases | `/espp/purchases` | ESPP discount analysis |
| Price History | `/equity/historical` | Daily OHLCV from cache DB |

### Stock Analysis Widgets (7-phase)
| Widget | Endpoint | Phase |
|---|---|---|
| Stock Context | `/stock/context` | 0 — Symbol anchor |
| Stock Profile | `/stock/profile` | 1 — Company overview |
| Stock Fundamentals | `/stock/fundamentals` | 2 — Revenue/margins/ROIC |
| Stock Technicals | `/stock/technicals` | 3 — RSI/ADX/ATR/MACD |
| Stock Valuation | `/stock/valuation` | 4 — P/E / EV/EBITDA / P/FCF |
| Stock Risk Metrics | `/stock/risk` | 5 — Sharpe / Beta / VaR |
| Peer Relative Analysis | `/stock/relative` | 6 — Peer comparison table |
| Decision Score | `/stock/decision` | 7 — Composite buy/hold/avoid |
