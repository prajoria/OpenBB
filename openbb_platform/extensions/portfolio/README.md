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

**Recommended — use the run helper (Windows PowerShell):**

```powershell
# First run: creates .venv_portfolio, editable-installs deps, generates a
# self-signed dev cert, and serves HTTPS on 127.0.0.1:6902.
.\scripts\run_portfolio_backend.ps1

# Subsequent runs (skip the install step):
.\scripts\run_portfolio_backend.ps1 -SkipInstall

# Plain-HTTP dev path (no certs), on port 6900:
.\scripts\run_portfolio_backend.ps1 -NoSsl -Port 6900
```

The helper mirrors `scripts/run_widget_backend.ps1` (which starts the
*separate* `portfolio_intel` widget backend on port 6120 — a different set
of apps). It handles the venv, editable install, MySQL `.env` check, and
TLS-cert bootstrap so no manual step is required. See issue #1786.

**Manual — raw `openbb-api` (any OS):**

```bash
# With HTTPS (recommended for OpenBB Workspace). Generate the dev cert first:
python scripts/gen_selfsigned_cert.py \
  --cert portfolio_app/cert.pem --key portfolio_app/key.pem

openbb-api --app openbb_platform/extensions/portfolio/launch.py \
  --ssl_certfile portfolio_app/cert.pem \
  --ssl_keyfile  portfolio_app/key.pem \
  --port 6902

# Without SSL (development)
openbb-api --app openbb_platform/extensions/portfolio/launch.py --port 6900
```

> **TLS certs are per-machine dev artifacts.** `portfolio_app/cert.pem` and
> `portfolio_app/key.pem` are gitignored and generated on demand — never
> committed. Your browser warns on first use of a self-signed cert; accept
> the exception for `127.0.0.1`, or trust the cert in your OS store.

### Configure OpenBB Workspace

Add a single backend at the **canonical port `6902`** (HTTPS):
`https://127.0.0.1:6902`.

> **Port note.** `6902` is canonical for this backend (HTTPS). The
> plain-HTTP dev path uses `6900` (`-NoSsl`). If Workspace shows requests to
> `6901`, that is a stale saved data-source config — update the saved app's
> data source to `https://127.0.0.1:6902` so a single port/scheme is
> expected.

The **Portfolio Overview** app (with tabs: Overview, Positions, Cost Basis &
Tax, Trends, ESPP, Stock Analysis) will appear automatically.

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
