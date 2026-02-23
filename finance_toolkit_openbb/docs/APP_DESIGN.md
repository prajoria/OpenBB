# FinanceToolkit OpenBB App — Detailed App Design

## 1. Design Philosophy

The FinanceToolkit OpenBB app exposes 256 financial analysis methods through a clean, tabbed dashboard interface. The design follows these principles:

1. **Module-per-tab mapping** — each FinanceToolkit module gets its own dashboard tab
2. **Collect-first, drill-down-second** — aggregate `collect_*` widgets show category overviews; individual `get_*` endpoints power drill-down or linked detail views
3. **Universal filter bar** — tickers, date range, quarterly/annual, growth, trailing, and lag controls appear consistently across all ticker-based tabs
4. **Data-dense tables with chart companions** — primary widget is always a table (leveraging AG-Grid); secondary widgets provide visual context (line charts, heatmaps)
5. **Consistent with existing Portfolio App** — same `widgets.json`/`apps.json` schema, same param patterns, same styling conventions

---

## 2. Dashboard Layout (apps.json)

The app defines a single dashboard named **"Financial Analysis"** with **10 tabs** corresponding to the 10 FinanceToolkit modules, plus a **Home** tab for cross-module summary.

### 2.1 Tab Structure

| Tab # | Tab ID | Tab Name | Primary Widgets | Module Methods |
|-------|--------|----------|-----------------|----------------|
| 0 | `home` | Home | Ticker summary card, company profile, historical chart | Core (18) |
| 1 | `statements` | Statements | Income Statement, Balance Sheet, Cash Flow | Core (3) |
| 2 | `ratios` | Ratios | 5 ratio category tables + ratio comparison chart | Ratios (77) |
| 3 | `models` | Models | DuPont, WACC, DCF, Altman, Piotroski, Gordon Growth | Models (9) |
| 4 | `performance` | Performance | Performance metrics table, Fama-French factors, Beta chart | Performance (16) |
| 5 | `risk` | Risk | VaR table, CVaR, drawdown chart, GARCH | Risk (10) |
| 6 | `options` | Options | Greeks grid, options pricing, P&L diagrams | Options (28) |
| 7 | `technicals` | Technicals | Momentum, overlap, volatility, breadth tables | Technicals (36) |
| 8 | `fixedincome` | Fixed Income | Bond yields, duration, central bank rates | Fixed Income (13) |
| 9 | `economics` | Economics | GDP, CPI, unemployment, interest rates by country | Economics (45) |
| 10 | `discovery` | Discovery | Stock screener, gainers/losers, sector performance | Discovery (13) |
| 11 | `portfolio_ft` | Portfolio | Positions, transactions, PnL tracking | Portfolio (9) |

---

## 3. Universal Parameters

These parameters appear on all ticker-based widgets (tabs 0–7) via the `groups` mechanism in `apps.json`:

### 3.1 Ticker Input

```json
{
  "paramName": "tickers",
  "label": "Tickers",
  "description": "Comma-separated stock tickers (e.g., AAPL,MSFT,GOOGL)",
  "type": "text",
  "value": "AAPL,MSFT",
  "optional": false,
  "show": true,
  "style": { "popupWidth": 400 }
}
```

### 3.2 Date Range

```json
{
  "paramName": "start_date",
  "label": "Start Date",
  "type": "date",
  "value": "2020-01-01",
  "optional": true,
  "show": true
},
{
  "paramName": "end_date",
  "label": "End Date",
  "type": "date",
  "value": null,
  "optional": true,
  "show": true
}
```

### 3.3 Cross-Cutting Analysis Parameters

```json
{
  "paramName": "quarterly",
  "label": "Quarterly",
  "description": "Use quarterly data (default: annual)",
  "type": "text",
  "value": "false",
  "optional": true,
  "show": true,
  "options": [
    { "label": "Annual", "value": "false" },
    { "label": "Quarterly", "value": "true" }
  ]
},
{
  "paramName": "growth",
  "label": "Growth",
  "description": "Show period-over-period growth rates",
  "type": "text",
  "value": "false",
  "optional": true,
  "show": false,
  "options": [
    { "label": "Off", "value": "false" },
    { "label": "On", "value": "true" }
  ]
},
{
  "paramName": "trailing",
  "label": "Trailing",
  "description": "Trailing periods (e.g., 4 for TTM with quarterly=true)",
  "type": "text",
  "value": "",
  "optional": true,
  "show": false
},
{
  "paramName": "lag",
  "label": "Lag",
  "description": "Lagged growth comparison periods",
  "type": "text",
  "value": "",
  "optional": true,
  "show": false
}
```

---

## 4. Widget Catalog — Detailed Design

### 4.0 Home Tab

#### Widget: `ft_company_profile`

| Property | Value |
|----------|-------|
| **Name** | Company Profile |
| **Type** | `table` |
| **Endpoint** | `GET /core/profile?tickers=AAPL,MSFT` |
| **Description** | Company overview: sector, industry, market cap, employees, description |
| **Grid** | `w: 40, h: 8` |
| **Params** | tickers |

**Column Definitions:**
| Field | Header | Type | Notes |
|-------|--------|------|-------|
| `ticker` | Ticker | text | pinned left |
| `company_name` | Company | text | |
| `sector` | Sector | text | |
| `industry` | Industry | text | |
| `market_cap` | Market Cap | number | formatterFn: "int" |
| `country` | Country | text | |
| `exchange` | Exchange | text | |
| `ipo_date` | IPO Date | date | |
| `description` | Description | text | truncated to 200 chars |

#### Widget: `ft_historical_prices`

| Property | Value |
|----------|-------|
| **Name** | Historical Prices |
| **Type** | `table` |
| **Endpoint** | `GET /core/historical?tickers=AAPL&start_date=2023-01-01` |
| **Description** | OHLCV with returns, cumulative returns, and volatility |
| **Grid** | `w: 40, h: 16` |
| **Params** | tickers, start_date, end_date |

**Column Definitions:**
| Field | Header | Type | Formatter | Render |
|-------|--------|------|-----------|--------|
| `date` | Date | date | none | |
| `ticker` | Ticker | text | | |
| `open` | Open | number | none | |
| `high` | High | number | none | |
| `low` | Low | number | none | |
| `close` | Close | number | none | |
| `adj_close` | Adj Close | number | none | |
| `volume` | Volume | number | int | |
| `return` | Return | number | percent | greenRed |
| `cumulative_return` | Cum Return | number | percent | greenRed |
| `volatility` | Volatility | number | percent | |

#### Widget: `ft_cumulative_returns_chart`

| Property | Value |
|----------|-------|
| **Name** | Cumulative Returns |
| **Type** | `chart` |
| **Endpoint** | `GET /core/cumulative_returns?tickers=AAPL,MSFT` |
| **Description** | Line chart of cumulative returns vs. benchmark (S&P 500) |
| **Grid** | `w: 40, h: 14` |
| **Chart Config** | Line chart, x-axis: date, y-axis: cumulative return |

---

### 4.1 Statements Tab

#### Widget: `ft_income_statement`

| Property | Value |
|----------|-------|
| **Name** | Income Statement |
| **Type** | `table` |
| **Endpoint** | `GET /core/income_statement?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |
| **Params** | tickers, start_date, quarterly, growth, trailing |

**Column Definitions:**
| Field | Header | Type | Notes |
|-------|--------|------|-------|
| `ticker` | Ticker | text | pinned left |
| `period` | Period | text | "2021", "2022Q3", etc. |
| `revenue` | Revenue | number | |
| `cost_of_goods_sold` | COGS | number | |
| `gross_profit` | Gross Profit | number | |
| `gross_profit_ratio` | Gross Margin | number | formatterFn: percent |
| `rd_expenses` | R&D | number | |
| `operating_income` | Operating Income | number | |
| `operating_income_ratio` | Operating Margin | number | formatterFn: percent |
| `net_income` | Net Income | number | greenRed |
| `net_income_ratio` | Net Margin | number | formatterFn: percent, greenRed |
| `ebitda` | EBITDA | number | |
| `eps` | EPS | number | |

#### Widget: `ft_balance_sheet`

| Property | Value |
|----------|-------|
| **Name** | Balance Sheet |
| **Type** | `table` |
| **Endpoint** | `GET /core/balance_sheet?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |
| **Params** | tickers, start_date, quarterly, growth, trailing |

**Key columns:** Total Assets, Total Liabilities, Total Equity, Cash & Equivalents, Total Debt, Current Assets, Current Liabilities, Retained Earnings, Goodwill

#### Widget: `ft_cash_flow`

| Property | Value |
|----------|-------|
| **Name** | Cash Flow Statement |
| **Type** | `table` |
| **Endpoint** | `GET /core/cash_flow?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |
| **Params** | tickers, start_date, quarterly, growth, trailing |

**Key columns:** Operating CF, Capital Expenditures, Free Cash Flow, Investing CF, Financing CF, Dividends Paid, Share Repurchases

---

### 4.2 Ratios Tab

The ratios tab contains 5 aggregate ratio tables (one per category) plus a comparative chart widget.

#### Widget: `ft_profitability_ratios`

| Property | Value |
|----------|-------|
| **Name** | Profitability Ratios |
| **Type** | `table` |
| **Endpoint** | `GET /ratios/profitability?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 14` (left half) |
| **Params** | tickers, start_date, quarterly, growth, trailing, lag |

**Column Definitions:**
| Field | Header | Formatter | Render |
|-------|--------|-----------|--------|
| `ticker` | Ticker | | pinned left |
| `period` | Period | | |
| `gross_margin` | Gross Margin | percent | greenRed |
| `operating_margin` | Operating Margin | percent | greenRed |
| `net_profit_margin` | Net Margin | percent | greenRed |
| `return_on_equity` | ROE | percent | greenRed |
| `return_on_assets` | ROA | percent | greenRed |
| `return_on_invested_capital` | ROIC | percent | greenRed |
| `return_on_capital_employed` | ROCE | percent | greenRed |
| `income_quality_ratio` | Income Quality | percent | |
| `effective_tax_rate` | Tax Rate | percent | |

#### Widget: `ft_valuation_ratios`

| Property | Value |
|----------|-------|
| **Name** | Valuation Ratios |
| **Type** | `table` |
| **Endpoint** | `GET /ratios/valuation?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 14` (right half) |

**Key Columns:** P/E, Forward P/E, P/B, P/S, P/CF, P/FCF, EV/EBITDA, EV/Revenue, EV/FCF, Earnings Yield, Dividend Yield, PEG Ratio, Price to Tangible Book

#### Widget: `ft_efficiency_ratios`

| Property | Value |
|----------|-------|
| **Name** | Efficiency Ratios |
| **Endpoint** | `GET /ratios/efficiency?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Key Columns:** Asset Turnover, Inventory Turnover, Receivables Turnover, Payables Turnover, Days Sales Outstanding, Days Inventory, Days Payables, Cash Conversion Cycle, SGA-to-Revenue, Fixed Asset Turnover, Operating Ratio

#### Widget: `ft_liquidity_ratios`

| Property | Value |
|----------|-------|
| **Name** | Liquidity Ratios |
| **Endpoint** | `GET /ratios/liquidity?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Key Columns:** Current Ratio, Quick Ratio, Cash Ratio, Working Capital, Operating Cash Flow Ratio, Short Term Coverage Ratio

#### Widget: `ft_solvency_ratios`

| Property | Value |
|----------|-------|
| **Name** | Solvency Ratios |
| **Endpoint** | `GET /ratios/solvency?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Key Columns:** Debt-to-Equity, Debt-to-Assets, Interest Coverage, Equity Multiplier, Debt Service Coverage, Financial Leverage, Free Cash Flow to Debt

---

### 4.3 Models Tab

#### Widget: `ft_dupont_analysis`

| Property | Value |
|----------|-------|
| **Name** | Extended DuPont Analysis |
| **Type** | `table` |
| **Endpoint** | `GET /models/dupont?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 12` |
| **Params** | tickers, start_date, quarterly |

**Column Definitions:**
| Field | Header | Formatter |
|-------|--------|-----------|
| `ticker` | Ticker | |
| `period` | Period | |
| `interest_burden_ratio` | Interest Burden | percent |
| `tax_burden_ratio` | Tax Burden | percent |
| `operating_profit_margin` | Operating Margin | percent |
| `asset_turnover` | Asset Turnover | none |
| `equity_multiplier` | Equity Multiplier | none |
| `return_on_equity` | ROE | percent, greenRed |

#### Widget: `ft_dcf_valuation`

| Property | Value |
|----------|-------|
| **Name** | DCF Intrinsic Valuation |
| **Type** | `table` |
| **Endpoint** | `GET /models/dcf?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 10` |
| **Params** | tickers, growth_rate (optional), perpetual_growth_rate (optional) |

**Key Columns:** Ticker, Intrinsic Value, Current Price, Upside/Downside %, WACC Used, Growth Rate Assumed

#### Widget: `ft_wacc`

| Property | Value |
|----------|-------|
| **Name** | Weighted Average Cost of Capital |
| **Endpoint** | `GET /models/wacc?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 10` |

**Key Columns:** Ticker, Period, Cost of Equity, Cost of Debt, Tax Rate, Equity Weight, Debt Weight, WACC

#### Widget: `ft_altman_zscore`

| Property | Value |
|----------|-------|
| **Name** | Altman Z-Score |
| **Endpoint** | `GET /models/altman?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 8` |

**Key Columns:** Ticker, Period, X1 (WC/TA), X2 (RE/TA), X3 (EBIT/TA), X4 (MVE/TL), X5 (Sales/TA), Z-Score, Zone (Safe/Grey/Distress)

#### Widget: `ft_piotroski_fscore`

| Property | Value |
|----------|-------|
| **Name** | Piotroski F-Score |
| **Endpoint** | `GET /models/piotroski?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 8` |

**Key Columns:** Ticker, Period, ROA, CFO, Δ ROA, Accrual, Δ Leverage, Δ Current Ratio, Δ Shares, Δ Gross Margin, Δ Asset Turnover, F-Score (0-9)

#### Widget: `ft_enterprise_value`

| Property | Value |
|----------|-------|
| **Endpoint** | `GET /models/enterprise_value?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 8` |

**Key Columns:** Market Cap, Total Debt, Cash, Minority Interest, Preferred Equity, Enterprise Value

---

### 4.4 Performance Tab

#### Widget: `ft_performance_summary`

| Property | Value |
|----------|-------|
| **Name** | Performance Metrics |
| **Type** | `table` |
| **Endpoint** | `GET /performance/summary?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |
| **Params** | tickers, start_date, period (daily/weekly/monthly/quarterly/yearly) |

**Column Definitions:**
| Field | Header | Formatter | Render |
|-------|--------|-----------|--------|
| `ticker` | Ticker | | pinned |
| `period_label` | Period | | |
| `sharpe_ratio` | Sharpe | none | greenRed |
| `sortino_ratio` | Sortino | none | greenRed |
| `treynor_ratio` | Treynor | none | greenRed |
| `jensens_alpha` | Jensen's α | percent | greenRed |
| `beta` | Beta | none | |
| `information_ratio` | Info Ratio | none | |
| `calmar_ratio` | Calmar | none | greenRed |
| `sterling_ratio` | Sterling | none | |
| `m2_ratio` | M² | percent | |
| `tracking_error` | Track Error | percent | |

#### Widget: `ft_fama_french_factors`

| Property | Value |
|----------|-------|
| **Name** | Fama-French Factor Correlations |
| **Endpoint** | `GET /performance/fama_french?tickers=AAPL,MSFT&period=quarterly` |
| **Grid** | `w: 40, h: 12` |

**Key Columns:** Ticker, Period, Market (Mkt-RF), Size (SMB), Value (HML), Profitability (RMW), Investment (CMA)

#### Widget: `ft_capm`

| Property | Value |
|----------|-------|
| **Name** | CAPM Analysis |
| **Endpoint** | `GET /performance/capm?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 8` |

**Key Columns:** Ticker, Risk-Free Rate, Beta, Market Premium, Expected Return

---

### 4.5 Risk Tab

#### Widget: `ft_value_at_risk`

| Property | Value |
|----------|-------|
| **Name** | Value at Risk |
| **Type** | `table` |
| **Endpoint** | `GET /risk/var?tickers=AAPL,MSFT&period=weekly` |
| **Grid** | `w: 40, h: 14` |
| **Params** | tickers, period, alpha (default 0.05) |

**Column Definitions:**
| Field | Header | Formatter | Render |
|-------|--------|-----------|--------|
| `period_range` | Period | | |
| `ticker` | Ticker | | |
| `historical_var` | Historical VaR | percent | greenRed |
| `gaussian_var` | Gaussian VaR | percent | greenRed |
| `studentt_var` | Student-t VaR | percent | greenRed |
| `cornish_fisher_var` | CF VaR | percent | greenRed |

#### Widget: `ft_cvar`

| Property | Value |
|----------|-------|
| **Name** | Conditional VaR (Expected Shortfall) |
| **Endpoint** | `GET /risk/cvar?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

#### Widget: `ft_max_drawdown`

| Property | Value |
|----------|-------|
| **Name** | Maximum Drawdown |
| **Type** | `chart` (line) |
| **Endpoint** | `GET /risk/drawdown?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Chart:** Drawdown percentage over time, one line per ticker, always negative, filled area.

#### Widget: `ft_garch`

| Property | Value |
|----------|-------|
| **Name** | GARCH Volatility |
| **Endpoint** | `GET /risk/garch?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 10` |

---

### 4.6 Options Tab

#### Widget: `ft_options_greeks_grid`

| Property | Value |
|----------|-------|
| **Name** | Options Greeks Grid |
| **Type** | `table` |
| **Endpoint** | `GET /options/greeks?tickers=AAPL&expiration_time_range=180` |
| **Grid** | `w: 40, h: 16` |
| **Params** | tickers (single), expiration_time_range, put_option (bool), risk_free_rate (optional) |

**This is a special grid-style widget** where rows = strike prices and columns = expiration dates. The cell values are the computed Greek (Delta, Gamma, etc.).

**Column Definitions (dynamic — generated from expiration dates):**
| Field | Header | Notes |
|-------|--------|-------|
| `strike_price` | Strike | pinned left |
| `exp_30d` | 30 Days | Greek value |
| `exp_60d` | 60 Days | Greek value |
| `exp_90d` | 90 Days | Greek value |
| `exp_120d` | 120 Days | Greek value |
| `exp_150d` | 150 Days | Greek value |
| `exp_180d` | 180 Days | Greek value |

**Greek Selector Parameter:**
```json
{
  "paramName": "greek",
  "label": "Greek",
  "type": "text",
  "value": "delta",
  "options": [
    { "label": "Delta", "value": "delta" },
    { "label": "Gamma", "value": "gamma" },
    { "label": "Theta", "value": "theta" },
    { "label": "Vega", "value": "vega" },
    { "label": "Rho", "value": "rho" }
  ]
}
```

#### Widget: `ft_options_pricing`

| Property | Value |
|----------|-------|
| **Name** | Black-Scholes Option Pricing |
| **Endpoint** | `GET /options/pricing?tickers=AAPL` |
| **Grid** | `w: 40, h: 12` |

**Key Columns:** Strike, Expiry, Call Value, Put Value, Implied Volatility, Stock Price, Risk-Free Rate

#### Widget: `ft_all_greeks_summary`

| Property | Value |
|----------|-------|
| **Name** | All Greeks Summary |
| **Endpoint** | `GET /options/all_greeks?tickers=AAPL` |
| **Grid** | `w: 40, h: 14` |

**Data:** `collect_all_greeks()` output — Delta, Dual Delta, Gamma, Vega, Theta, Rho, Epsilon, Lambda, plus second-order (Vomma, Charm, Veta, Vera, Vanna, Speed, Zomma, Color) and third-order (Ultima).

---

### 4.7 Technicals Tab

#### Widget: `ft_momentum_indicators`

| Property | Value |
|----------|-------|
| **Name** | Momentum Indicators |
| **Type** | `table` |
| **Endpoint** | `GET /technicals/momentum?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |

**Key Columns:** Date, Ticker, RSI, MACD, MACD Signal, MACD Histogram, Stochastic %K, Stochastic %D, Williams %R, CCI, ROC, Aroon Up, Aroon Down, Aroon Oscillator

#### Widget: `ft_overlap_indicators`

| Property | Value |
|----------|-------|
| **Name** | Overlap Indicators |
| **Endpoint** | `GET /technicals/overlap?tickers=AAPL,MSFT` |
| **Grid** | `w: 40, h: 14` |

**Key Columns:** Date, Ticker, SMA 20, SMA 50, SMA 200, EMA 20, EMA 50, EMA 200, Bollinger Upper, Bollinger Mid, Bollinger Lower, Ichimoku Conv, Ichimoku Base, Ichimoku Span A, Ichimoku Span B

#### Widget: `ft_volatility_indicators`

| Property | Value |
|----------|-------|
| **Name** | Volatility Indicators |
| **Endpoint** | `GET /technicals/volatility?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Key Columns:** Date, Ticker, ATR, True Range, Keltner Upper, Keltner Mid, Keltner Lower

#### Widget: `ft_breadth_indicators`

| Property | Value |
|----------|-------|
| **Name** | Breadth Indicators |
| **Endpoint** | `GET /technicals/breadth?tickers=AAPL,MSFT` |
| **Grid** | `w: 20, h: 12` |

**Key Columns:** Date, Ticker, McClellan Oscillator, Advancers/Decliners, OBV

---

### 4.8 Fixed Income Tab

#### Widget: `ft_ice_bofa_yields`

| Property | Value |
|----------|-------|
| **Name** | ICE BofA Corporate Bond Yields |
| **Type** | `table` |
| **Endpoint** | `GET /fixedincome/ice_bofa_yields` |
| **Grid** | `w: 40, h: 14` |
| **Params** | start_date, end_date |

**Column Definitions:**
| Field | Header | Formatter |
|-------|--------|-----------|
| `date` | Date | date |
| `aaa` | AAA | percent |
| `aa` | AA | percent |
| `a` | A | percent |
| `bbb` | BBB | percent |
| `bb` | BB | percent |
| `b` | B | percent |
| `ccc` | CCC | percent |

#### Widget: `ft_government_yields`

| Property | Value |
|----------|-------|
| **Name** | Government Bond Yields |
| **Endpoint** | `GET /fixedincome/government_yields` |
| **Grid** | `w: 20, h: 12` |
| **Params** | start_date, end_date |

**Key Columns:** Date, Country, Short-term rates, Long-term rates

#### Widget: `ft_bond_calculator`

| Property | Value |
|----------|-------|
| **Name** | Bond Calculator |
| **Endpoint** | `GET /fixedincome/bond_valuation` |
| **Grid** | `w: 20, h: 10` |
| **Params** | par_value, coupon_rate, years_to_maturity, yield_to_maturity, frequency |

**Key Columns:** Present Value, Macaulay Duration, Modified Duration, Effective Duration, Dollar Duration, Convexity, YTM

#### Widget: `ft_central_bank_rates`

| Property | Value |
|----------|-------|
| **Name** | Central Bank Policy Rates |
| **Endpoint** | `GET /fixedincome/central_bank_rates` |
| **Grid** | `w: 20, h: 10` |

**Key Columns:** Date, Federal Funds Rate, ECB Rate, BOE Rate, BOJ Rate

---

### 4.9 Economics Tab

The Economics tab uses **country selectors** instead of ticker selectors. The `Economics` class can be used standalone without FMP API key.

#### Widget: `ft_gdp`

| Property | Value |
|----------|-------|
| **Name** | Gross Domestic Product |
| **Type** | `table` |
| **Endpoint** | `GET /economics/gdp?countries=US,GB,DE,JP,CN` |
| **Grid** | `w: 20, h: 12` |
| **Params** | countries (multi-select), start_date |

**Columns:** Year, one column per country with GDP value

#### Widget: `ft_cpi`

| Property | Value |
|----------|-------|
| **Name** | Consumer Price Index |
| **Endpoint** | `GET /economics/cpi?countries=US,GB,DE` |
| **Grid** | `w: 20, h: 12` |

#### Widget: `ft_unemployment`

| Property | Value |
|----------|-------|
| **Name** | Unemployment Rate |
| **Endpoint** | `GET /economics/unemployment?countries=US,GB,DE,JP` |
| **Grid** | `w: 20, h: 12` |

#### Widget: `ft_interest_rates`

| Property | Value |
|----------|-------|
| **Name** | Government Interest Rates |
| **Endpoint** | `GET /economics/interest_rates?countries=US,GB,DE` |
| **Grid** | `w: 20, h: 12` |

**Columns:** Year, Country, 3-Month Rate, 10-Year Rate

#### Widget: `ft_trade_balance`

| Property | Value |
|----------|-------|
| **Name** | Trade Balance |
| **Endpoint** | `GET /economics/trade_balance?countries=US,CN,DE` |
| **Grid** | `w: 20, h: 10` |

#### Additional Economics Widgets (collapsed by default):

| Widget ID | Name | Endpoint |
|-----------|------|----------|
| `ft_government_debt` | Government Debt | `/economics/government_debt` |
| `ft_government_spending` | Government Spending | `/economics/government_spending` |
| `ft_exchange_rates` | Exchange Rates | `/economics/exchange_rates` |
| `ft_population` | Population | `/economics/population` |
| `ft_poverty_rate` | Poverty Rate | `/economics/poverty_rate` |
| `ft_house_prices` | House Price Index | `/economics/house_prices` |
| `ft_composite_leading` | Composite Leading Indicator | `/economics/composite_leading` |
| `ft_trust_in_government` | Trust in Government | `/economics/trust_government` |
| `ft_labour_productivity` | Labour Productivity | `/economics/labour_productivity` |
| `ft_environmental_tax` | Environmental Tax Revenue | `/economics/environmental_tax` |

**Country Selector Parameter:**
```json
{
  "paramName": "countries",
  "label": "Countries",
  "description": "Comma-separated ISO country codes (e.g., US,GB,DE,JP,CN)",
  "type": "text",
  "value": "US,GB,DE,JP",
  "optional": false,
  "show": true,
  "style": { "popupWidth": 400 }
}
```

---

### 4.10 Discovery Tab

#### Widget: `ft_stock_screener`

| Property | Value |
|----------|-------|
| **Name** | Stock Screener |
| **Type** | `table` |
| **Endpoint** | `GET /discovery/screener?exchange=NASDAQ&market_cap_min=1000000000` |
| **Grid** | `w: 40, h: 18` |
| **Params** | exchange, sector, industry, market_cap_min, market_cap_max, beta_min, beta_max, dividend_min, limit |

**Column Definitions:**
| Field | Header | Type | Render |
|-------|--------|------|--------|
| `symbol` | Symbol | text | cellOnClick (link to set tickers) |
| `company_name` | Company | text | |
| `sector` | Sector | text | |
| `industry` | Industry | text | |
| `market_cap` | Market Cap | number | |
| `price` | Price | number | |
| `beta` | Beta | number | |
| `volume` | Volume | number | |
| `last_annual_dividend` | Dividend | number | |
| `exchange` | Exchange | text | |

#### Widget: `ft_gainers_losers`

| Property | Value |
|----------|-------|
| **Name** | Top Gainers & Losers |
| **Endpoint** | `GET /discovery/gainers_losers` |
| **Grid** | `w: 20, h: 14` |

**Key Columns:** Symbol, Company, Price, Change, Change %, Volume

#### Widget: `ft_most_active`

| Property | Value |
|----------|-------|
| **Name** | Most Active Stocks |
| **Endpoint** | `GET /discovery/most_active` |
| **Grid** | `w: 20, h: 14` |

#### Widget: `ft_sector_performance`

| Property | Value |
|----------|-------|
| **Name** | Sector Performance |
| **Endpoint** | `GET /discovery/sector_performance` |
| **Grid** | `w: 20, h: 10` |

**Key Columns:** Sector, Change %, rendered as horizontal bar chart

---

### 4.11 Portfolio Tab

The Portfolio module uses a file upload or pre-configured data source (XLSX/CSV) to track personal portfolio positions.

#### Widget: `ft_portfolio_positions`

| Property | Value |
|----------|-------|
| **Name** | Portfolio Positions |
| **Endpoint** | `GET /portfolio/positions` |
| **Grid** | `w: 40, h: 14` |

**Key Columns:** Ticker, Shares Bought, Shares Sold, Average Price, Cost Basis, Current Price, Current Value, Total Return, Total Return %, Annualized Return, Weight

#### Widget: `ft_portfolio_pnl`

| Property | Value |
|----------|-------|
| **Name** | Portfolio P&L |
| **Endpoint** | `GET /portfolio/pnl?method=FIFO` |
| **Grid** | `w: 40, h: 12` |
| **Params** | method (FIFO / LIFO / AVERAGE) |

**Key Columns:** Ticker, Cost Method, Realized P&L, Unrealized P&L, Total P&L, % Return

#### Widget: `ft_portfolio_transactions`

| Property | Value |
|----------|-------|
| **Name** | Transaction History |
| **Endpoint** | `GET /portfolio/transactions` |
| **Grid** | `w: 40, h: 14` |

---

## 5. Parameter Groups (apps.json `groups`)

Parameter groups link filter controls across multiple widgets on the same tab so changing "tickers" in one widget updates all widgets.

### 5.1 Ticker Group (applied to tabs 0–7)

```json
{
  "name": "Tickers",
  "type": "param",
  "paramName": "tickers",
  "defaultValue": "AAPL,MSFT",
  "widgetIds": ["ft_company_profile", "ft_historical_prices", "ft_income_statement", "ft_profitability_ratios", "ft_valuation_ratios", "ft_dupont_analysis", "ft_performance_summary", "ft_value_at_risk", "ft_momentum_indicators", "ft_options_greeks_grid"]
}
```

### 5.2 Date Range Group

```json
{
  "name": "Start Date",
  "type": "param",
  "paramName": "start_date",
  "defaultValue": "2020-01-01",
  "widgetIds": ["ft_historical_prices", "ft_income_statement", "ft_balance_sheet", "ft_cash_flow", "ft_profitability_ratios", "ft_valuation_ratios", "ft_efficiency_ratios", "ft_liquidity_ratios", "ft_solvency_ratios", "ft_dupont_analysis", "ft_performance_summary", "ft_value_at_risk"]
}
```

### 5.3 Country Group (Economics tab)

```json
{
  "name": "Countries",
  "type": "param",
  "paramName": "countries",
  "defaultValue": "US,GB,DE,JP",
  "widgetIds": ["ft_gdp", "ft_cpi", "ft_unemployment", "ft_interest_rates", "ft_trade_balance", "ft_government_debt"]
}
```

---

## 6. Widget Count Summary

| Tab | Widgets | Underlying FT Methods |
|-----|---------|----------------------|
| Home | 3 | 18 |
| Statements | 3 | 3 |
| Ratios | 5 | 77 |
| Models | 6 | 9 |
| Performance | 3 | 16 |
| Risk | 4 | 10 |
| Options | 3 | 28 |
| Technicals | 4 | 36 |
| Fixed Income | 4 | 13 |
| Economics | 15 | 45 |
| Discovery | 4 | 13 |
| Portfolio | 3 | 9 |
| **Total** | **~57** | **~277** (some shared across widgets) |

---

## 7. UX Interaction Patterns

### 7.1 Ticker Drill-Down Flow

```
Discovery Tab                         Home Tab                    Ratios Tab
┌─────────────────────┐              ┌──────────────────┐        ┌──────────────────┐
│ Stock Screener      │   click      │ Company Profile  │  tab   │ Profitability    │
│                     │  ticker      │                  │ switch │ Ratios           │
│ AAPL  Apple  ...    │─────────────►│ AAPL  Apple Inc  │───────►│ AAPL  ROE: 171%  │
│ MSFT  Microsoft ... │              │ Sector: Tech     │        │ MSFT  ROE: 39%   │
│ GOOGL Alphabet  ... │              │ Market Cap: 3.2T │        │                  │
└─────────────────────┘              └──────────────────┘        └──────────────────┘
```

### 7.2 Analysis Deepening Flow

```
Profitability Ratios (collect_*)      Individual Ratio (get_*)
┌─────────────────────────┐          ┌─────────────────────────┐
│ Gross Margin   28%      │  click   │ Return on Equity        │
│ Operating Mgn  24%      │  "ROE"   │                         │
│ Net Margin     21%      │─────────►│ 2020: 87.9%             │
│ ROE            171%     │          │ 2021: 147.4%            │
│ ROA            28%      │          │ 2022: 175.5%            │
│ ROIC           56%      │          │ 2023: 171.9%            │
└─────────────────────────┘          └─────────────────────────┘
```

### 7.3 Cross-Module Comparison

The Groups mechanism allows users to change tickers once and have all widgets on the tab update simultaneously. This enables seamless comparative analysis:

1. Enter `AAPL,MSFT,GOOGL,AMZN,META` in the Tickers group
2. Switch between Ratios → Performance → Risk tabs
3. All widgets show the same 5 companies consistently

---

## 8. Response Format Standards

### 8.1 Table Widget Response

```json
[
  {
    "ticker": "AAPL",
    "period": "2023",
    "gross_margin": 0.4413,
    "operating_margin": 0.2967,
    "net_profit_margin": 0.2531,
    "return_on_equity": 1.7195,
    "return_on_assets": 0.2826
  },
  {
    "ticker": "MSFT",
    "period": "2023",
    "gross_margin": 0.6892,
    "operating_margin": 0.4177,
    "net_profit_margin": 0.3415,
    "return_on_equity": 0.3896,
    "return_on_assets": 0.1933
  }
]
```

### 8.2 Chart Widget Response

```json
[
  { "date": "2020-12-31", "AAPL": 0.8096, "MSFT": 0.3022 },
  { "date": "2021-12-31", "AAPL": 1.4744, "MSFT": 0.4316 },
  { "date": "2022-12-31", "AAPL": 1.7546, "MSFT": 0.4413 },
  { "date": "2023-12-31", "AAPL": 1.7195, "MSFT": 0.3896 }
]
```

### 8.3 Grid Widget Response (Options)

```json
{
  "columns": ["Strike", "30 Days", "60 Days", "90 Days", "120 Days", "180 Days"],
  "data": [
    { "strike": 170, "30d": 0.8521, "60d": 0.7834, "90d": 0.7512, "120d": 0.7298, "180d": 0.7102 },
    { "strike": 175, "30d": 0.7686, "60d": 0.7178, "90d": 0.6967, "120d": 0.6857, "180d": 0.6759 },
    { "strike": 180, "30d": 0.6659, "60d": 0.6400, "90d": 0.6318, "120d": 0.6290, "180d": 0.6291 }
  ]
}
```

---

## 9. Endpoint Summary

| # | Endpoint | Method | Module | Widget |
|---|----------|--------|--------|--------|
| 1 | `/core/profile` | GET | Core | `ft_company_profile` |
| 2 | `/core/historical` | GET | Core | `ft_historical_prices` |
| 3 | `/core/cumulative_returns` | GET | Core | `ft_cumulative_returns_chart` |
| 4 | `/core/income_statement` | GET | Core | `ft_income_statement` |
| 5 | `/core/balance_sheet` | GET | Core | `ft_balance_sheet` |
| 6 | `/core/cash_flow` | GET | Core | `ft_cash_flow` |
| 7 | `/ratios/profitability` | GET | Ratios | `ft_profitability_ratios` |
| 8 | `/ratios/valuation` | GET | Ratios | `ft_valuation_ratios` |
| 9 | `/ratios/efficiency` | GET | Ratios | `ft_efficiency_ratios` |
| 10 | `/ratios/liquidity` | GET | Ratios | `ft_liquidity_ratios` |
| 11 | `/ratios/solvency` | GET | Ratios | `ft_solvency_ratios` |
| 12 | `/models/dupont` | GET | Models | `ft_dupont_analysis` |
| 13 | `/models/dcf` | GET | Models | `ft_dcf_valuation` |
| 14 | `/models/wacc` | GET | Models | `ft_wacc` |
| 15 | `/models/altman` | GET | Models | `ft_altman_zscore` |
| 16 | `/models/piotroski` | GET | Models | `ft_piotroski_fscore` |
| 17 | `/models/enterprise_value` | GET | Models | `ft_enterprise_value` |
| 18 | `/performance/summary` | GET | Performance | `ft_performance_summary` |
| 19 | `/performance/fama_french` | GET | Performance | `ft_fama_french_factors` |
| 20 | `/performance/capm` | GET | Performance | `ft_capm` |
| 21 | `/risk/var` | GET | Risk | `ft_value_at_risk` |
| 22 | `/risk/cvar` | GET | Risk | `ft_cvar` |
| 23 | `/risk/drawdown` | GET | Risk | `ft_max_drawdown` |
| 24 | `/risk/garch` | GET | Risk | `ft_garch` |
| 25 | `/options/greeks` | GET | Options | `ft_options_greeks_grid` |
| 26 | `/options/pricing` | GET | Options | `ft_options_pricing` |
| 27 | `/options/all_greeks` | GET | Options | `ft_all_greeks_summary` |
| 28 | `/technicals/momentum` | GET | Technicals | `ft_momentum_indicators` |
| 29 | `/technicals/overlap` | GET | Technicals | `ft_overlap_indicators` |
| 30 | `/technicals/volatility` | GET | Technicals | `ft_volatility_indicators` |
| 31 | `/technicals/breadth` | GET | Technicals | `ft_breadth_indicators` |
| 32 | `/fixedincome/ice_bofa_yields` | GET | Fixed Income | `ft_ice_bofa_yields` |
| 33 | `/fixedincome/government_yields` | GET | Fixed Income | `ft_government_yields` |
| 34 | `/fixedincome/bond_valuation` | GET | Fixed Income | `ft_bond_calculator` |
| 35 | `/fixedincome/central_bank_rates` | GET | Fixed Income | `ft_central_bank_rates` |
| 36 | `/economics/gdp` | GET | Economics | `ft_gdp` |
| 37 | `/economics/cpi` | GET | Economics | `ft_cpi` |
| 38 | `/economics/unemployment` | GET | Economics | `ft_unemployment` |
| 39 | `/economics/interest_rates` | GET | Economics | `ft_interest_rates` |
| 40 | `/economics/trade_balance` | GET | Economics | `ft_trade_balance` |
| 41–50 | `/economics/{indicator}` | GET | Economics | Additional economics widgets |
| 51 | `/discovery/screener` | GET | Discovery | `ft_stock_screener` |
| 52 | `/discovery/gainers_losers` | GET | Discovery | `ft_gainers_losers` |
| 53 | `/discovery/most_active` | GET | Discovery | `ft_most_active` |
| 54 | `/discovery/sector_performance` | GET | Discovery | `ft_sector_performance` |
| 55 | `/portfolio/positions` | GET | Portfolio | `ft_portfolio_positions` |
| 56 | `/portfolio/pnl` | GET | Portfolio | `ft_portfolio_pnl` |
| 57 | `/portfolio/transactions` | GET | Portfolio | `ft_portfolio_transactions` |
| — | `/widgets.json` | GET | System | Widget catalog |
| — | `/apps.json` | GET | System | Dashboard definition |
| — | `/health` | GET | System | Health check |
| — | `/get_tickers` | GET | System | Ticker filter options |
| — | `/get_countries` | GET | System | Country filter options |

---

## 10. Future Enhancements (Post-MVP)

| Enhancement | Description | Priority |
|-------------|-------------|----------|
| **FinanceDatabase integration** | Use FinanceDatabase (300k+ symbols) for ticker discovery and auto-complete | High |
| **Custom ratios** | Allow users to define custom ratios via UI and calculate automatically | Medium |
| **Comparison dashboard** | Dedicated tab for side-by-side ticker comparison across all modules | Medium |
| **Watchlist integration** | Save ticker lists, auto-refresh widgets with watchlist tickers | Medium |
| **Export to Excel/CSV** | Download widget data in spreadsheet format | Medium |
| **Portfolio App bridge** | Auto-populate tickers from Portfolio App positions | High |
| **Alerting** | Notify when Altman Z-Score enters distress zone, or P/E crosses threshold | Low |
| **Historical snapshots** | Save analysis snapshots for comparison over time | Low |
| **AI commentary** | LLM-powered narrative summary of financial metrics | Low |
