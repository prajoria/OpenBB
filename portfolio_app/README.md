# Portfolio App — Standalone Backend

This app runs as a *separate* service from the OpenBB Platform API.
It queries the MySQL database for `Portfolio_Positions` data and can
also proxy requests to the OpenBB API for market data enrichment.

## Architecture

```
┌──────────────┐       ┌──────────────────┐
│  OpenBB API  │ :6902 │  Portfolio App    │ :6903
│  (market     │◄──────│  (positions,      │
│   data)      │ httpx │   allocation,     │
└──────────────┘       │   cost basis)     │
                       └──────────────────┘
                               ▲
                               │
                       ┌──────────────────┐
                       │  OpenBB Workspace │
                       │  (widgets.json)   │
                       └──────────────────┘
```

## Configuration

- **MySQL credentials are required** — set `MYSQL_USER` and `MYSQL_PASSWORD`
  (plus optional `MYSQL_HOST`, `MYSQL_PORT`, `PORTFOLIO_DATABASE`) via
  environment variables or a `.env` file. There are no hardcoded credential
  defaults; the app fails fast if they are unset.
- **CORS origins** are environment-driven via `PORTFOLIO_CORS_ORIGINS`
  (comma-separated). The built-in default is a *local dev* allow-list
  (desktop/Tauri + OpenBB Pro) and must not be used for a public deployment.

## Run

```bash
cd portfolio_app
python run_portfolio.py
```

Or from the project root:

```bash
.venv_win/Scripts/python portfolio_app/run_portfolio.py
```
