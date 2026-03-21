# Plan: Single-Stock Analysis Widget for Portfolio App

## Context

The notebook `Analysis/00. single_stock_analysis_playbook_template.ipynb` implements a full 7-phase single-stock analysis pipeline (profile, fundamentals, technicals, valuation, risk, peer-relative, decision scoring). The `portfolio_app` is a FastAPI backend that serves OpenBB Workspace widgets via `widgets.json` / `apps.json`. The goal is to expose all notebook capabilities as proper OpenBB widgets in the portfolio app so they can be used interactively in the dashboard — with a symbol dropdown, date range inputs, and live data from OpenBB/FMP.

## Status: ✅ IMPLEMENTED

All 4 files were created/modified. Implementation is complete.

---

## What Was Built

### New FastAPI endpoints in `portfolio_app/src/main.py`

| Endpoint | Maps to Notebook Phase | Returns |
|---|---|---|
| `GET /stock/profile` | Phase 1 — Company Profile | Company profile + quote + peer count summary |
| `GET /stock/fundamentals` | Phase 2 — Fundamental KPIs | Revenue growth, margins, ROIC, D/E, current ratio |
| `GET /stock/technicals` | Phase 3 — Technical Indicators | RSI, ADX, ATR, OBV, MACD signal, Bollinger % |
| `GET /stock/valuation` | Phase 4 — Valuation Ratios | P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield |
| `GET /stock/risk` | Phase 5 — Risk Metrics | Sharpe, Sortino, Beta, Alpha, VaR, CVaR, Max DD, Ulcer |
| `GET /stock/relative` | Phase 6 — Peer Relative | Return, Vol, Sharpe, VaR, Max DD per asset in peer universe |
| `GET /stock/decision` | Phase 7 — Decision Score | 6 dimension scores + total composite + decision label |

All endpoints accept:
- `symbol: str` (required, e.g. `CLS`)
- `benchmark: str` (optional, default `SPY`)
- `lookback_years: int` (optional, default `1` for technicals/risk; `5` for fundamentals)

### New analysis module: `portfolio_app/src/stock_analysis.py`

Pure-function module — no OpenBB imports, no HTTP calls. Receives DataFrames, returns dicts/DataFrames.

| Function | Description |
|---|---|
| `build_phase1_summary()` | Profile + quote + peers → flat summary dict |
| `compute_fundamental_kpis()` | Revenue growth, margins, ROIC, D/E, current ratio |
| `compute_technical_kpis()` | RSI(14), ADX(14), ATR, OBV, MACD signal, Bollinger %B |
| `compute_valuation_kpis()` | P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield, WACC, Piotroski, Altman Z |
| `compute_risk_kpis()` | Sharpe, Sortino, Beta, Jensen Alpha, VaR 95%, CVaR 95%, Max DD, Ulcer |
| `compute_relative_table()` | Peer/ETF/benchmark return-risk comparison table |
| `build_close_matrix()` | Long-format historical DF → wide close-price pivot |
| `build_peer_universe()` | Stock + peers + sector ETFs + benchmark universe list |
| `compute_decision_scores()` | 6-dimension weighted composite score + decision label |

### Updated `portfolio_app/widgets.json`

7 new widget definitions added:
```
stock_profile          → /stock/profile       (category: Equity / Analysis)
stock_fundamentals     → /stock/fundamentals  (category: Equity / Analysis)
stock_technicals       → /stock/technicals    (category: Equity / Analysis)
stock_valuation        → /stock/valuation     (category: Equity / Analysis)
stock_risk             → /stock/risk          (category: Equity / Analysis)
stock_relative         → /stock/relative      (category: Equity / Analysis)
stock_decision         → /stock/decision      (category: Equity / Analysis)
```

Each widget has:
- `symbol` param (type: `endpoint`, optionsEndpoint: `/get_symbols`)
- `benchmark` param (type: `text`, default: `SPY`, optional)

### Updated `portfolio_app/apps.json`

- New **"Stock Analysis"** tab added to the Portfolio Overview app
- Layout: profile (full width) → fundamentals + valuation (side by side) → technicals + risk (side by side) → relative (full width) → decision
- New **"Analysis Symbol"** group linking all 7 widgets — changing symbol in one updates all

---

## Critical Files Modified

| File | Change |
|---|---|
| `portfolio_app/src/stock_analysis.py` | **New file** — 19 pure functions, ~430 lines |
| `portfolio_app/src/main.py` | Added 7 `/stock/*` route handlers + `_gather()` helper |
| `portfolio_app/widgets.json` | Added 7 widget definitions |
| `portfolio_app/apps.json` | Added `stock_analysis` tab + `Analysis Symbol` group |

---

## Reuse Patterns

- `openbb_client.OpenBBClient.get_df()` — all OpenBB API calls (handles results envelope + DataFrame conversion)
- `asyncio.gather()` via `_gather()` helper — parallel API calls in `/stock/decision`
- `service._filter()` / `_pct_return()` patterns — consistent data shaping
- `to_df()` / `first_available_value()` / `last_numeric()` from notebook Cell 6 — ported into `stock_analysis.py`

---

## Verification

```bash
# Start the app
python portfolio_app/run_portfolio.py

# Health check
curl -k https://127.0.0.1:6903/health
# Expect: {"openbb_api": true, ...}

# Test decision endpoint
curl -k "https://127.0.0.1:6903/stock/decision?symbol=CLS"
# Expect: [{business_quality, fundamentals, technicals, valuation, risk_fit, relative_peer_score, total_score, decision}]

# Test relative endpoint
curl -k "https://127.0.0.1:6903/stock/relative?symbol=CLS"
# Expect: table rows with Annual Return, Volatility, Sharpe, VaR 95%, CVaR 95%, Max Drawdown per peer

# Verify widget registry
curl -k https://127.0.0.1:6903/widgets.json | python -m json.tool | grep '"stock_'

# OpenBB Workspace
# → Add backend: https://127.0.0.1:6903
# → Navigate to "Stock Analysis" tab
# → Set symbol to any ticker (e.g. CLS, MSFT, AAPL)
# → All 7 widgets should populate with live data
```
