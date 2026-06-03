# FinanceToolkit Rules

> **Purpose:** Contextual rules for working with the FinanceToolkit library.
> The source code lives in the git submodule at `FinanceToolkit/`.
> These rules establish deep familiarity with its architecture, API,
> patterns, and integration points within this project.
>
> **Author:** Jeroen Bouma | **Version:** 2.0.6 | **License:** MIT
> **Python:** >=3.10, <3.14

---

## 1. Project Location & Structure

- **Submodule path:** `FinanceToolkit/` (root of this workspace)
- **Package directory:** `FinanceToolkit/financetoolkit/`
- **Examples:** `FinanceToolkit/examples/` (13 Jupyter notebooks)
- **Tests:** `FinanceToolkit/tests/` (snapshot-based, record/replay)
- **Normalization CSVs:** `FinanceToolkit/financetoolkit/normalization/`

### Module Layout

| Module | Controller | Purpose |
|--------|-----------|---------|
| `ratios/` | `Ratios` | 77 financial ratios (efficiency, liquidity, profitability, solvency, valuation) |
| `models/` | `Models` | Valuation models (DuPont, Altman Z, Piotroski, WACC, DCF, Gordon Growth) |
| `risk/` | `Risk` | VaR, CVaR, EVaR, GARCH, drawdown, skewness, kurtosis |
| `performance/` | `Performance` | CAPM, Fama-French, Sharpe, Sortino, Treynor, Jensen's Alpha, Beta |
| `options/` | `Options` | Black-Scholes, binomial trees, Greeks (1st/2nd/3rd order) |
| `technicals/` | `Technicals` | Momentum, overlap, volatility, breadth, statistical indicators |
| `economics/` | `Economics` | OECD macroeconomic data (GDP, CPI, unemployment, etc.) |
| `fixedincome/` | `FixedIncome` | Bond analytics, yield curves, central bank rates, ICE BofA indices |
| `discovery/` | `Discovery` | Stock screener, gainers/losers, active, delisted, crypto/forex/ETF lists |
| `portfolio/` | `Portfolio` | Portfolio tracking, benchmarking, transaction analysis |
| `utilities/` | — | Caching (`cache_model.py`), error handling, logging |

### Key Root-Level Files

| File | Purpose |
|------|---------|
| `toolkit_controller.py` | Main `Toolkit` class — central API entry point (3844 lines) |
| `fmp_model.py` | FMP API client with three-tier data source fallback (2022 lines) |
| `fundamentals_model.py` | Financial statement collection (FMP → YFinance fallback) |
| `historical_model.py` | Historical OHLCV retrieval with threading |
| `yfinance_model.py` | Yahoo Finance fallback client |
| `normalization_model.py` | Normalizes FMP/YFinance fields to consistent internal format |
| `currencies_model.py` | Currency detection and cross-listed company conversion |
| `helpers.py` | Utilities: `calculate_growth`, `combine_dataframes`, `handle_portfolio` |

---

## 2. Core API — Toolkit Class

### Initialization

```python
from financetoolkit import Toolkit

# Standard usage
companies = Toolkit(
    tickers=["AAPL", "MSFT", "GOOGL"],
    api_key="YOUR_FMP_KEY",
    start_date="2021-01-01",
    end_date="2024-12-31",
)

# Without FMP key (Yahoo Finance fallback only)
companies = Toolkit(["AAPL"], enforce_source="YahooFinance")

# With caching enabled
companies = Toolkit(["AAPL"], api_key="KEY", use_cached_data=True)

# Custom data injection (no API calls needed)
companies = Toolkit(
    tickers=["AAPL"],
    historical=my_historical_df,
    balance=my_balance_df,
    income=my_income_df,
    cash=my_cashflow_df,
)
```

### Constructor Parameters

| Parameter | Type | Default | Notes |
|-----------|------|---------|-------|
| `tickers` | `list\|str\|None` | `None` | Ticker symbols |
| `api_key` | `str` | `""` | FMP API key |
| `start_date` | `str\|None` | 5 years back | `YYYY-MM-DD` format |
| `end_date` | `str\|None` | today | `YYYY-MM-DD` format |
| `quarterly` | `bool` | `False` | Quarterly vs annual statements |
| `use_cached_data` | `bool\|str` | `False` | Pickle-based local caching |
| `risk_free_rate` | `str` | `"10y"` | Treasury yield (`13w`, `5y`, `10y`, `30y`) |
| `benchmark_ticker` | `str\|None` | `"SPY"` | For CAPM, Alpha, Beta |
| `enforce_source` | `str\|None` | `None` | `"FinancialModelingPrep"` or `"YahooFinance"` |
| `historical` | `pd.DataFrame` | empty | Inject custom historical data |
| `balance` / `income` / `cash` | `pd.DataFrame` | empty | Inject custom statements |
| `convert_currency` | `bool\|None` | `None` | Cross-currency conversion |
| `reverse_dates` | `bool` | `True` | Oldest-first column ordering |
| `intraday_period` | `str\|None` | `None` | `1min`, `5min`, `15min`, `30min`, `1hour` |
| `rounding` | `int\|None` | `4` | Decimal places |
| `remove_invalid_tickers` | `bool` | `False` | Auto-remove failing tickers |
| `sleep_timer` | `bool\|None` | `None` | API rate limit handling |
| `progress_bar` | `bool` | `True` | tqdm progress bars |

### Module Access (Properties)

```python
companies.ratios        # → Ratios controller
companies.models        # → Models controller
companies.options       # → Options controller
companies.technicals    # → Technicals controller
companies.performance   # → Performance controller
companies.risk          # → Risk controller
companies.fixedincome   # → FixedIncome controller (standalone, no tickers needed)
companies.economics     # → Economics controller (standalone, no tickers needed)
```

### Direct Toolkit Methods

```python
# Company info
companies.get_profile()
companies.get_quote()
companies.get_rating()
companies.get_analyst_estimates()
companies.get_earnings_calendar()
companies.get_esg_scores()
companies.get_dividend_calendar()

# Historical data
companies.get_historical_data()          # Daily OHLCV
companies.get_intraday_data()            # Intraday OHLCV
companies.get_historical_statistics()

# Financial statements
companies.get_balance_sheet_statement()
companies.get_income_statement()
companies.get_cash_flow_statement()
companies.get_statistics_statement()

# Market data
companies.get_treasury_data()
companies.get_exchange_rates()

# Revenue breakdowns
companies.get_revenue_geographic_segmentation()
companies.get_revenue_product_segmentation()
```

---

## 3. Data Source Fallback — Three-Tier System

The library implements a three-tier data fallback in `fmp_model.py`:

1. **Tier 1: OpenBB fmp_cached provider** — Uses MySQL cache via
   `from openbb import obb; obb.equity.price.historical(provider="fmp_cached")`.
   Enabled when `openbb` package is installed (`ENABLE_OBB_CACHED = True`).

2. **Tier 2: Direct FMP API** — Standard HTTPS calls to
   `financialmodelingprep.com`. Requires valid `api_key`.

3. **Tier 3: CBOE free provider** — Free fallback when FMP
   authentication/rate limits fail. Uses OpenBB:
   `obb.equity.price.historical(provider="cboe")`.

### Financial Statements Fallback

- FMP API tried first (if `api_key` provided and `enforce_source` allows)
- Falls back to **Yahoo Finance** via `yfinance_model.py` if FMP fails
- Controlled by `enforce_source`: `None` (auto), `"FinancialModelingPrep"`, `"YahooFinance"`

### Integration with This Project

In this workspace, the fmp_cached provider is **installed and active**.
This means Tier 1 (MySQL cache) is the primary data source. The
`openbb_fmp_cache_test` database serves as the cache backend.

---

## 4. Architecture Patterns

### Controller + Model Pattern

Every module follows a two-layer architecture:
- **Controller** (`*_controller.py`) — Public API, data orchestration,
  lazy loading, parameter validation
- **Model** (`*_model.py`) — Pure calculation functions, no side effects

```python
# Controller handles data fetching + delegates to model
class Ratios:
    def get_return_on_equity(self):
        # Ensures income_statement and balance_sheet are loaded
        # Calls profitability_model.get_return_on_equity(income, balance)
        ...
```

### Lazy Loading

Module properties auto-fetch missing data on first access:
```python
companies = Toolkit(["AAPL"], api_key="KEY")
# No API calls yet

roe = companies.ratios.get_return_on_equity()
# NOW fetches: historical data + income statement + balance sheet
# Then calculates ROE
```

### `get_` vs `collect_` Convention

- **`get_*`** — Returns a single metric/indicator (e.g., `get_current_ratio()`)
- **`collect_*`** — Returns an aggregation of multiple related metrics
  (e.g., `collect_liquidity_ratios()` returns all 8 liquidity ratios)

### Threading

Both `historical_model.py` and `fundamentals_model.py` use Python
`threading` for parallel API calls across tickers. The soft limit
is `TICKER_LIMIT = 20` concurrent tickers.

### Error Handling

The `@handle_errors` decorator in `utilities/error_model.py` catches
`KeyError`, `ValueError`, `AttributeError`, `ZeroDivisionError`,
`IndexError` and logs them gracefully instead of crashing.

### Multi-Period Historical Data

Historical data is stored in period-specific DataFrames:
- `_daily_historical_data`
- `_weekly_historical_data`
- `_monthly_historical_data`
- `_quarterly_historical_data`
- `_yearly_historical_data`

### Portfolio Weights

Optional portfolio weighting support is threaded through all analytical
modules via `_portfolio_weights`. When set, ratios and metrics can be
calculated as portfolio-weighted aggregates.

---

## 5. Normalization System

The `normalization/` directory contains CSV mapping files that translate
provider-specific field names into a consistent internal format:

| File | Source | Statement |
|------|--------|-----------|
| `balance.csv` | FMP | Balance Sheet |
| `balance_yf.csv` | Yahoo Finance | Balance Sheet |
| `income.csv` | FMP | Income Statement |
| `income_yf.csv` | Yahoo Finance | Income Statement |
| `cash.csv` | FMP | Cash Flow |
| `cash_yf.csv` | Yahoo Finance | Cash Flow |
| `statistics.csv` | FMP | Statistics |

Custom normalization files can be provided via the `format_location`
parameter in the Toolkit constructor.

---

## 6. Key Method Reference

### Ratios (77 methods)

**Efficiency** (14): `get_asset_turnover_ratio`, `get_inventory_turnover_ratio`,
`get_days_of_inventory_outstanding`, `get_days_of_sales_outstanding`,
`get_operating_cycle`, `get_accounts_payables_turnover_ratio`,
`get_days_of_accounts_payable_outstanding`, `get_cash_conversion_cycle`,
`get_cash_conversion_efficiency`, `get_receivables_turnover`,
`get_sga_to_revenue_ratio`, `get_fixed_asset_turnover`, `get_operating_ratio`,
`collect_efficiency_ratios`

**Liquidity** (8): `get_current_ratio`, `get_quick_ratio`, `get_cash_ratio`,
`get_working_capital`, `get_operating_cash_flow_ratio`,
`get_operating_cash_flow_sales_ratio`, `get_short_term_coverage_ratio`,
`collect_liquidity_ratios`

**Profitability** (19): `get_gross_margin`, `get_operating_margin`,
`get_net_profit_margin`, `get_interest_burden_ratio`,
`get_income_before_tax_profit_margin`, `get_effective_tax_rate`,
`get_return_on_assets`, `get_return_on_equity`,
`get_return_on_invested_capital`, `get_income_quality_ratio`,
`get_return_on_tangible_assets`, `get_return_on_capital_employed`,
`get_net_income_per_ebt`, `get_free_cash_flow_operating_cash_flow_ratio`,
`get_tax_burden_ratio`, `get_EBT_to_EBIT`, `get_EBIT_to_revenue`,
`collect_profitability_ratios`

**Solvency** (12): `get_debt_to_assets_ratio`, `get_debt_to_equity_ratio`,
`get_interest_coverage_ratio`, `get_equity_multiplier`,
`get_debt_service_coverage_ratio`, `get_free_cash_flow_yield`,
`get_net_debt_to_ebitda_ratio`, `get_cash_flow_coverage_ratio`,
`get_capex_coverage_ratio`, `get_capex_dividend_coverage_ratio`,
`collect_solvency_ratios`

**Valuation** (22): `get_earnings_per_share`, `get_revenue_per_share`,
`get_price_to_earnings_ratio`, `get_price_to_earnings_growth_ratio`,
`get_book_value_per_share`, `get_price_to_book_ratio`,
`get_interest_debt_per_share`, `get_capex_per_share`,
`get_dividend_yield`, `get_weighted_dividend_yield`,
`get_price_to_cash_flow_ratio`, `get_price_to_free_cash_flow_ratio`,
`get_market_cap`, `get_enterprise_value`, `get_ev_to_sales_ratio`,
`get_ev_to_ebitda_ratio`, `get_ev_to_operating_cashflow_ratio`,
`get_earnings_yield`, `get_dividend_payout_ratio`,
`get_reinvestment_rate`, `get_tangible_asset_value`,
`get_net_current_asset_value`, `get_ev_to_ebit`,
`collect_valuation_ratios`, `collect_all_ratios`, `collect_custom_ratios`

### Models (9 methods)

`get_dupont_analysis`, `get_extended_dupont_analysis`,
`get_enterprise_value_breakdown`, `get_weighted_average_cost_of_capital`,
`get_intrinsic_valuation`, `get_gorden_growth_model`,
`get_altman_z_score`, `get_piotroski_score`,
`get_present_value_of_growth_opportunities`

### Risk (10 methods)

`get_value_at_risk`, `get_conditional_value_at_risk`,
`get_entropic_value_at_risk`, `get_maximum_drawdown`,
`get_ulcer_index`, `get_garch`, `get_garch_forecast`,
`get_skewness`, `get_kurtosis`, `collect_all_metrics`

### Performance (16 methods)

`get_beta`, `get_capital_asset_pricing_model`,
`get_factor_asset_correlations`, `get_factor_correlations`,
`get_fama_and_french_model`, `get_alpha`, `get_jensens_alpha`,
`get_treynor_ratio`, `get_sharpe_ratio`, `get_sortino_ratio`,
`get_ulcer_performance_index`, `get_m2_ratio`,
`get_tracking_error`, `get_information_ratio`,
`get_compound_growth_rate`, `collect_all_metrics`

### Options (28 methods)

`get_option_chains`, `get_black_scholes_model`,
`get_implied_volatility`, `get_binomial_model`,
`get_stock_price_simulation`, `collect_all_greeks`,
`collect_first_order_greeks` (delta, dual_delta, vega, theta, rho, epsilon, lambda),
`collect_second_order_greeks` (gamma, dual_gamma, vanna, charm, vomma, vera, veta),
`collect_third_order_greeks` (speed, zomma, color, ultima)

### Technicals (36 methods)

**Momentum** (17): RSI, MACD, Stochastic, Williams %R, Aroon, CCI,
Money Flow Index, Force Index, Ultimate Oscillator, PPO, DPO, ADX,
Chande Momentum, Ichimoku Cloud, Relative Vigor, Balance of Power

**Overlap** (8): SMA, EMA, DEMA, TRIX, Bollinger Bands,
Triangular MA, Support/Resistance Levels

**Volatility** (4): True Range, ATR, Keltner Channels

**Breadth** (5): McClellan Oscillator, Advancers/Decliners,
OBV, A/D Line, Chaikin Oscillator

### Economics (45 methods)

GDP, CPI, inflation, unemployment, labor productivity, consumer/business
confidence, CLI, house/rent/share prices, exchange rates, money supply,
central bank rates, interest rates, government debt/revenue/tax,
renewable energy, carbon footprint, income inequality, population, poverty

### Fixed Income (13 methods)

Bond present value, duration, YTM, derivative pricing,
government bond yields, ICE BofA indices (OAS, effective yield,
total return, yield to worst), Euribor, ECB rates, Fed rates

### Discovery (14 methods)

`search_instruments`, `get_stock_screener`, `get_stock_list`,
`get_biggest_gainers`, `get_biggest_losers`, `get_most_active_stocks`,
`get_delisted_stocks`, `get_crypto_list`, `get_forex_list`,
`get_commodity_list`, `get_etf_list`, `get_index_list`,
`get_stock_shares_float`, `get_sectors_performance`

### Portfolio (8 methods)

`read_portfolio_dataset`, `collect_benchmark_historical_data`,
`collect_historical_data`, `get_positions_overview`,
`get_portfolio_overview`, `get_portfolio_performance`,
`get_transactions_overview`, `get_transactions_performance`

---

## 7. Common Usage Patterns

### Basic Analysis

```python
from financetoolkit import Toolkit

companies = Toolkit(["AAPL", "MSFT"], api_key="FMP_KEY", start_date="2020-01-01")

# Financial statements
income = companies.get_income_statement()
balance = companies.get_balance_sheet_statement()
cashflow = companies.get_cash_flow_statement()

# All profitability ratios at once
profitability = companies.ratios.collect_profitability_ratios()

# Specific ratio
roe = companies.ratios.get_return_on_equity()

# Valuation models
wacc = companies.models.get_weighted_average_cost_of_capital()
dcf = companies.models.get_intrinsic_valuation()
altman = companies.models.get_altman_z_score()
piotroski = companies.models.get_piotroski_score()
```

### Risk & Performance

```python
# Risk metrics
var = companies.risk.get_value_at_risk()
cvar = companies.risk.get_conditional_value_at_risk()
drawdown = companies.risk.get_maximum_drawdown()

# Performance metrics (vs SPY benchmark)
sharpe = companies.performance.get_sharpe_ratio()
sortino = companies.performance.get_sortino_ratio()
beta = companies.performance.get_beta()
capm = companies.performance.get_capital_asset_pricing_model()
fama = companies.performance.get_fama_and_french_model()
```

### Technical Analysis

```python
rsi = companies.technicals.get_relative_strength_index()
macd = companies.technicals.get_moving_average_convergence_divergence()
bb = companies.technicals.get_bollinger_bands()
all_technicals = companies.technicals.collect_all_indicators()
```

### Options Analysis

```python
chains = companies.options.get_option_chains()
bs = companies.options.get_black_scholes_model()
greeks = companies.options.collect_all_greeks()
iv = companies.options.get_implied_volatility()
```

### Economics (No Tickers Needed)

```python
from financetoolkit import Economics

econ = Economics()
gdp = econ.get_gross_domestic_product()
cpi = econ.get_consumer_price_index()
unemployment = econ.get_unemployment_rate()
rates = econ.get_long_term_interest_rate()
```

### Fixed Income (No Tickers Needed)

```python
from financetoolkit import FixedIncome

fi = FixedIncome(api_key="FMP_KEY")
gov_yields = fi.get_government_bond_yield()
fed_rates = fi.get_federal_reserve_rates()
duration = fi.get_duration(par_value=100, coupon_rate=0.05, years_to_maturity=10)
```

### Custom Data Injection

```python
# Use your own DataFrames — no API calls needed
companies = Toolkit(
    tickers=["AAPL"],
    historical=my_ohlcv_df,       # DatetimeIndex, columns: Open/High/Low/Close/Volume
    balance=my_balance_df,         # Normalized field names
    income=my_income_df,
    cash=my_cashflow_df,
)

# All ratio/model/risk calculations work on injected data
ratios = companies.ratios.collect_all_ratios()
```

### Caching

```python
# Cache to default location (~/.financetoolkit/)
companies = Toolkit(["AAPL"], api_key="KEY", use_cached_data=True)

# Cache to custom directory
companies = Toolkit(["AAPL"], api_key="KEY", use_cached_data="./my_cache/")
```

---

## 8. Integration with This Project

### Where FinanceToolkit Fits

| Component | Role |
|-----------|------|
| `FinanceToolkit/` (submodule) | Library source code — DO NOT modify unless contributing upstream |
| `openbb_fmp_cached` provider | Provides Tier 1 data source for FinanceToolkit's fallback chain |
| `portfolio_app/` | Uses similar data from MySQL but via its own `data.py` / `service.py` layers |
| `Analysis/` notebooks | Some notebooks use FinanceToolkit directly for ratio/model analysis |

### FMP API Key Configuration

The FMP API key can be provided:
1. **Constructor parameter:** `Toolkit(api_key="YOUR_KEY")`
2. **Environment variable:** Set `FMP_API_KEY` in `.env`
3. **OpenBB user settings:** `~/.openbb_platform/user_settings.json` →
   `credentials.fmp_api_key`

### Dependencies

```
pandas>=2.2
scikit-learn>=1.6
requests>=2.32
yfinance
openpyxl>=3.1
tqdm>=4.67
```

### Running Tests

```bash
# From FinanceToolkit/ directory
pytest tests/ -v --tb=short

# Cached integration tests (uses MySQL cache)
pytest test_cached_integration.py -v -s
pytest test_toolkit_cached.py -v -s
```

---

## 9. Development Rules for FinanceToolkit

### DO

- **Use the `Toolkit` class** as the primary entry point — never import
  model functions directly unless building custom calculations
- **Prefer `collect_*`** over individual `get_*` calls when you need
  multiple related metrics
- **Set `start_date`** explicitly — the 5-year default may fetch
  excessive data
- **Use `use_cached_data=True`** in notebooks to avoid redundant API calls
- **Inject custom data** via constructor when working with local
  MySQL-cached data to avoid API overhead
- **Use `enforce_source="YahooFinance"`** when FMP key is unavailable
- **Check the example notebooks** in `FinanceToolkit/examples/` for
  reference patterns

### DO NOT

- **Do not modify** files in `FinanceToolkit/` unless contributing
  upstream — it is a git submodule
- **Do not hard-code API keys** — use environment variables or
  OpenBB settings
- **Do not exceed 20 tickers** per Toolkit instance without good reason
  (`TICKER_LIMIT = 20`)
- **Do not mix FMP and YFinance** field names — the normalization
  layer handles this internally
- **Do not call `fmp_model.py` functions directly** — use the Toolkit
  or controller APIs
- **Do not assume data availability** — handle empty DataFrames
  gracefully (FMP free tier has limited history)

### Gotchas

- **FMP free tier** limits historical data to ~5 years and has
  rate limits — use `sleep_timer=True` for large requests
- **Yahoo Finance** does not provide all fields that FMP does —
  some ratios may return NaN when using YFinance source
- **Quarterly data** requires `quarterly=True` at construction time —
  it cannot be toggled after initialization
- **Currency conversion** adds API calls — only enable when analyzing
  cross-listed companies
- **`reverse_dates=True`** (default) means columns are ordered
  oldest → newest; set `False` for most-recent-first

---

## 10. Example Notebooks Index

| # | Notebook | Topics |
|---|----------|--------|
| 0 | README Examples | Quick-start snippets from the README |
| 1 | Getting Started | Toolkit init, historical data, statements, basic ratios |
| 2 | Discovery Module | Stock screener, gainers/losers, search |
| 3 | Ratios Module | All 77 ratios across 5 categories |
| 4 | Models Module | DuPont, Altman Z, Piotroski, WACC, DCF |
| 5 | Options Module | Black-Scholes, Greeks, chains, binomial trees |
| 6 | Technicals Module | RSI, MACD, Bollinger, Ichimoku, all indicators |
| 7 | Risk Module | VaR, CVaR, EVaR, GARCH, drawdown |
| 8 | Performance Module | Sharpe, Sortino, CAPM, Fama-French, Alpha/Beta |
| 9 | Economics Module | OECD macro data — GDP, CPI, unemployment |
| 10 | Fixed Income Module | Bonds, yield curves, central bank rates |
| 11 | Portfolio Module | Portfolio tracking, benchmarking, transactions |
| ext | Using External Datasets | Custom data injection without API |
