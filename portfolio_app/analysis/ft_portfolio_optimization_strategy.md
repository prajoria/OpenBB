# Portfolio Optimization Strategy — FinanceToolkit Enhanced

> **Planned Notebook:** `portfolio_app/analysis/ft_portfolio_optimization.ipynb`  
> **Companion:** `portfolio_app/analysis/portfolio_optimization.ipynb` (existing MPT notebook)  
> **Library:** [FinanceToolkit v2.0.6](https://github.com/JerBouma/FinanceToolkit) by Jeroen Bouma  
> **Author:** Prashant Rajoria | **Date:** 2026-02-26 | **Branch:** `openbb_learning`

---

## 1. Motivation

The existing `portfolio_optimization.ipynb` applies **classical MPT** — mean-variance
optimization using `pypfopt`, producing Max Sharpe and Min Volatility portfolios.

This new notebook extends the analysis using **FinanceToolkit**, which provides:
- **150+ financial ratios** for fundamental quality scoring
- **Fama-French 5-factor model** for factor exposure analysis
- **Risk metrics** (VaR, CVaR, Maximum Drawdown, Ulcer Index) for tail-risk-aware optimization
- **Portfolio-level weighted metrics** via the `portfolio.toolkit` bridge
- **Standalone model functions** that work with our own cached data (no FMP API dependency)

**Goal:** Build a multi-factor, risk-aware portfolio optimization that goes beyond
mean-variance by incorporating fundamental quality, factor exposures, and downside
risk constraints — all using techniques demonstrated in the FinanceToolkit example notebooks.

---

## 2. FinanceToolkit Example Notebook References

Each section below references the specific FinanceToolkit example notebook
that demonstrates the technique being applied.

| Notebook | Path | Techniques Used |
|----------|------|-----------------|
| **11. Portfolio Module** | `FinanceToolkit/examples/Finance Toolkit - 11. Portfolio Module.ipynb` | Portfolio overview, P&L tracking, `portfolio.toolkit` bridge for weighted metrics |
| **8. Performance Module** | `FinanceToolkit/examples/Finance Toolkit - 8. Performance Module.ipynb` | Sharpe Ratio, Jensen's Alpha, CAPM, Beta, Fama-French 5-Factor, factor correlations |
| **7. Risk Module** | `FinanceToolkit/examples/Finance Toolkit - 7. Risk Module.ipynb` | VaR, CVaR, Maximum Drawdown, Ulcer Index, Skewness, Kurtosis |
| **4. Models Module** | `FinanceToolkit/examples/Finance Toolkit - 4. Models Module.ipynb` | Extended DuPont, WACC, Altman Z-Score, Piotroski F-Score |
| **3. Ratios Module** | `FinanceToolkit/examples/Finance Toolkit - 3. Ratios Module.ipynb` | 100+ ratios (efficiency, liquidity, profitability, solvency, valuation), custom ratios |
| **Using External Datasets** | `FinanceToolkit/examples/Finance Toolkit - Using External Datasets.ipynb` | Loading custom data, normalization, `combine_dataframes()`, using Toolkit without FMP API |

---

## 3. Strategy Steps

### Step 1 — Load Positions & Price History (Reuse)

Reuse **Sections 1–4** from `portfolio_optimization.ipynb`:
- Load current positions from MySQL via `data.get_positions_df()`
- Build 3-year daily close price matrix via direct SQL on `equity_historical`
- Aggregate by symbol, compute current weights

No changes needed — data layer is already in place.

### Step 2 — Initialize FinanceToolkit with Cached Data

Use the **External Datasets** pattern (Notebook: *Using External Datasets*):

```python
from financetoolkit import Toolkit

# Initialize Toolkit with our portfolio symbols
# Use enforce_source="YahooFinance" or provide custom data to avoid FMP API calls
companies = Toolkit(
    tickers=portfolio_symbols,
    api_key=FMP_API_KEY,       # from .env
    start_date=start_date,
    end_date=end_date,
)
```

Alternatively, load financial statements from our own cache and pass them
using the `balance=`, `income=`, `cash=` parameters with normalization files
(see *Using External Datasets* notebook for the pattern).

### Step 3 — Fundamental Quality Screening

**Goal:** Score each holding on fundamental quality to filter the optimization universe.

*Ref: Notebook 4 (Models Module), Notebook 3 (Ratios Module)*

| Metric | Method | Purpose | Screen Rule |
|--------|--------|---------|-------------|
| **Piotroski F-Score** | `models.get_piotroski_score()` | Fundamental strength (0–9) | Keep ≥ 5 |
| **Altman Z-Score** | `models.get_altman_z_score()` | Bankruptcy risk | Drop < 1.8 (distress zone) |
| **Current Ratio** | `ratios.get_current_ratio()` | Liquidity | Drop < 1.0 |
| **Debt-to-Equity** | `ratios.get_debt_to_equity_ratio()` | Leverage | Flag > 3.0 |

**Output:** A filtered universe of fundamentally sound stocks, along with a quality
score DataFrame showing each metric per symbol.

### Step 4 — Multi-Factor Expected Returns (CAPM + Fama-French)

Replace simple mean-historical returns with factor-model-based expected returns.

*Ref: Notebook 8 (Performance Module)*

#### 4a. CAPM Expected Returns

```python
capm = companies.performance.get_capital_asset_pricing_model(period="yearly")
```

$$E(R_i) = R_f + \beta_i \cdot (E(R_m) - R_f)$$

#### 4b. Fama-French 5-Factor Decomposition

```python
ff5 = companies.performance.get_fama_and_french_model(period="yearly", method="simple")
factor_corr = companies.performance.get_factor_asset_correlations(period="quarterly")
```

Five factors: Market (Mkt-RF), Size (SMB), Value (HML), Profitability (RMW), Investment (CMA).

**Output:** Per-stock factor exposures and R² values. Identify which factors
are driving each holding's returns — useful for understanding concentration
in factor space (e.g., "Am I too heavy on growth/momentum?").

#### 4c. Blended Expected Returns

Blend historical and CAPM-implied returns:

$$\mu_{\text{blend}} = \alpha \cdot \mu_{\text{historical}} + (1-\alpha) \cdot \mu_{\text{CAPM}}$$

Choose $\alpha = 0.5$ as default. This dampens extreme historical returns
toward the equilibrium implied by beta.

### Step 5 — Enhanced Risk Assessment

Go beyond volatility with tail-risk and drawdown metrics.

*Ref: Notebook 7 (Risk Module)*

| Metric | Method | What It Captures |
|--------|--------|-----------------|
| **Value at Risk (95%)** | `risk.get_value_at_risk()` | Worst expected daily loss (5% tail) |
| **CVaR / Expected Shortfall** | `risk.get_conditional_value_at_risk()` | Average loss beyond VaR |
| **Maximum Drawdown** | `risk.get_maximum_drawdown(period="quarterly")` | Peak-to-trough decline |
| **Ulcer Index** | `risk.get_ulcer_index(period="yearly")` | Duration-weighted drawdown pain |
| **Skewness** | `risk_model.get_skewness()` | Asymmetry of return distribution |
| **Kurtosis** | `risk_model.get_kurtosis()` | Fat tails / extreme event frequency |

**Output:** A risk dashboard DataFrame with all metrics per symbol, plus portfolio-level
aggregates. Identify which holdings contribute the most tail risk.

### Step 6 — Performance Benchmarking

*Ref: Notebook 8 (Performance Module), Notebook 11 (Portfolio Module)*

| Metric | Method | What It Measures |
|--------|--------|-----------------|
| **Sharpe Ratio** | `performance.get_sharpe_ratio(period="monthly", rolling=12)` | Risk-adjusted return |
| **Jensen's Alpha** | `performance.get_jensens_alpha(period="quarterly")` | Stock-picking skill vs. market |
| **Beta** | `performance.get_beta()` | Sensitivity to market movements |
| **Rolling Sharpe** | `performance.get_sharpe_ratio(rolling=12)` | Time-varying risk-adjusted return |

**Output:** Rolling Sharpe Ratio chart per holding. Identify which stocks have
*consistently* good risk-adjusted returns vs. those that look good only in recent
windows.

### Step 7 — DuPont Analysis (ROE Decomposition)

Understand *why* certain stocks are profitable.

*Ref: Notebook 4 (Models Module)*

```python
dupont = companies.models.get_extended_dupont_analysis()
```

Extended DuPont decomposes ROE into 5 components:
- Tax Burden × Interest Burden × Operating Margin × Asset Turnover × Equity Multiplier

**Output:** Heatmap showing which profitability driver dominates each holding.
Companies with high ROE from operating margin (quality) are preferable to those
with high ROE from equity multiplier (leverage).

### Step 8 — Optimization with Risk Constraints

Build on the existing MPT optimization but add constraints informed by Steps 3–5.

**Three optimization variants:**

| Portfolio | Objective | Extra Constraints |
|-----------|-----------|-------------------|
| **Max Sharpe (Enhanced)** | Max $\frac{\mu_{\text{blend}} - r_f}{\sigma_p}$ | Only quality-screened stocks (Piotroski ≥ 5, Z > 1.8) |
| **Min CVaR** | Minimize portfolio CVaR | Replace volatility with Expected Shortfall as risk measure |
| **Risk Parity** | Equal risk contribution per asset | Each asset contributes equally to portfolio variance |

Use `pypfopt.EfficientFrontier` with blended expected returns from Step 4c,
and filter the universe based on the quality screen from Step 3.

### Step 9 — Factor Exposure Comparison

*Ref: Notebook 8 (Performance Module)*

Compare factor exposures of current portfolio vs. each optimized portfolio:

```python
factor_corr = companies.performance.get_factor_asset_correlations(period="quarterly")
```

**Visualization:** Radar chart showing factor loadings (Market, Size, Value, Profitability,
Investment) for Current vs. Max Sharpe (Enhanced) vs. Min CVaR vs. Risk Parity.

### Step 10 — Portfolio-Level Weighted Metrics

*Ref: Notebook 11 (Portfolio Module)*

Use the `portfolio.toolkit` bridge to compute weighted portfolio-level metrics:

```python
# After setting up Portfolio with transactions
portfolio_ratios = portfolio.toolkit.ratios.get_net_profit_margin()
portfolio_beta = portfolio.toolkit.performance.get_beta()
portfolio_var = portfolio.toolkit.risk.get_value_at_risk()
```

The automatic `"Portfolio"` row shows the weighted-average metric across all holdings.

**Output:** Side-by-side table comparing:
- Current portfolio's weighted fundamentals
- Max Sharpe (Enhanced) portfolio's weighted fundamentals
- Which optimization improves quality while maintaining returns

### Step 11 — Summary & Comparison Dashboard

Final dashboard combining all analyses:

| Metric | Current | Max Sharpe (Enhanced) | Min CVaR | Risk Parity |
|--------|---------|----------------------|----------|-------------|
| Expected Return | — | — | — | — |
| Volatility | — | — | — | — |
| Sharpe Ratio | — | — | — | — |
| CVaR (95%) | — | — | — | — |
| Max Drawdown | — | — | — | — |
| Avg Piotroski | — | — | — | — |
| Avg Beta | — | — | — | — |
| # Assets | — | — | — | — |

---

## 4. Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| History window | 3 years | Consistent with existing notebook |
| Risk-free rate | 4.5% | T-bill rate (2025–2026) |
| Max weight per asset | 25% | Prevent over-concentration |
| Piotroski minimum | ≥ 5 | Exclude fundamentally weak companies |
| Altman Z minimum | > 1.8 | Exclude distress zone |
| VaR confidence | 95% | Standard institutional confidence level |
| CAPM blend α | 0.5 | Equal weight to historical and implied returns |
| Fama-French period | Quarterly | Balance between noise and recency |

---

## 5. Data Flow

### 5a. Available Cached Tables (MySQL `openbb_fmp_cache_test`)

All data below is **already cached** via fmp_cached provider — no live API calls needed.

| Category | Table | Key Columns | FT Module |
|----------|-------|-------------|-----------|
| **Prices** | `equity_historical` | symbol, date, open, high, low, close, volume | `.get_historical_data()` |
| **Fundamentals** | `income_statement` | symbol, date, revenue, net_income, eps, ebitda, … | `.get_income_statement()` |
| | `balance_sheet` | symbol, date, total_assets, total_equity, total_debt, … | `.get_balance_sheet_statement()` |
| | `cash_flow` | symbol, date, operating_cash_flow, capex, free_cash_flow, … | `.get_cash_flow_statement()` |
| **Growth** | `income_statement_growth` | symbol, date, revenue_growth, eps_growth, … | `.get_income_statement(growth=True)` |
| | `balance_sheet_growth` | symbol, date, total_assets_growth, … | `.get_balance_sheet_statement(growth=True)` |
| | `cash_flow_growth` | symbol, date, operating_cash_flow_growth, … | `.get_cash_flow_statement(growth=True)` |
| **Ratios/Metrics** | `financial_ratios` | symbol, date, pe_ratio, pb_ratio, roe, roa, … | `.ratios` module |
| | `key_metrics` | symbol, date, market_cap, enterprise_value, … | `.ratios` module |
| **Company** | `equity_profile` | symbol, company_name, sector, industry, country, … | Toolkit metadata |
| | `equity_quote` | symbol, price, market_cap, eps, pe, … | Latest quote |
| | `equity_peers` | symbol, peers_list | Peer comparison |
| **Positions** | `portfolio_positions` | account_name, symbol, quantity, current_value, cost_basis, … | Portfolio module |
| | `account_owner` | account_name, owner | Account mapping |
| **Earnings/Estimates** | `historical_eps` | symbol, date, eps_actual, eps_estimated | Earnings analysis |
| | `forward_eps_estimates` | symbol, date, estimated_eps_avg, … | Forward estimates |
| | `forward_ebitda_estimates` | symbol, date, estimated_ebitda_avg, … | Forward estimates |
| **Dividends/Splits** | `historical_dividends` | symbol, date, dividend | Dividend analysis |
| | `historical_splits` | symbol, date, numerator, denominator | Split adjustments |
| **Other** | `executive_compensation` | symbol, name, pay, … | Governance |
| | `insider_trading` | symbol, date, transaction_type, … | Insider activity |
| | `institutional_ownership` | symbol, holder, shares, … | Ownership analysis |
| | `price_performance` | symbol, 1d, 5d, 1m, 3m, 6m, ytd, 1y, 3y, 5y, 10y | Performance |
| | `share_statistics` | symbol, shares_outstanding, float, … | Share data |
| | `treasury_rates` | date, 1m, 3m, 6m, 1y, 2y, 5y, 10y, 30y | Risk-free rates |

> **Total: 70+ cached tables.** The translation layer (Step 2) maps these directly
> to FinanceToolkit's expected DataFrame formats, eliminating live API calls.

### 5b. Data Flow Architecture

```
MySQL cache (70+ tables — see above)
    │
    ├─► portfolio_app/src/data.py     ──► Positions & prices (existing)
    ├─► portfolio_app/src/db.py       ──► Direct SQL queries
    │
    └─► Translation Layer (ft_data_bridge.py)
            │
            ├─► Map cached tables → FT normalization format
            ├─► combine_dataframes() → multi-index DataFrames
            │
            └─► FinanceToolkit(tickers, balance=, income=, cash=)
                    │
                    ├─► .ratios      → Quality ratios (P/E, ROA, D/E)
                    ├─► .models      → Piotroski, Altman, DuPont, WACC
                    ├─► .performance → CAPM, Fama-French, Sharpe, Alpha, Beta
                    ├─► .risk        → VaR, CVaR, Max Drawdown, Ulcer Index
                    └─► .portfolio   → Portfolio-level weighted metrics
                            │
                            └─► pypfopt optimization (filtered, blended)
                                    │
                                    └─► comparison dashboard
```

---

## 6. Differences from Existing Notebook

| Aspect | Existing (`portfolio_optimization.ipynb`) | This Notebook |
|--------|-------------------------------------------|---------------|
| **Expected returns** | Mean historical (geometric) | Blended: historical + CAPM |
| **Risk measure** | Volatility only | Volatility + VaR + CVaR + Max Drawdown |
| **Universe filtering** | Data coverage only (≥60%) | Coverage + Piotroski + Altman Z |
| **Optimization variants** | Max Sharpe, Min Vol | Max Sharpe (Enhanced), Min CVaR, Risk Parity |
| **Factor analysis** | None | Fama-French 5-Factor decomposition |
| **Quality assessment** | None | DuPont analysis, fundamental ratios |
| **Portfolio metrics** | Return / Vol / Sharpe | + CVaR, Max Drawdown, weighted fundamentals |
| **Library dependency** | pypfopt only | pypfopt + FinanceToolkit |

---

## 7. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `financetoolkit` | 2.0.6 | 150+ ratios, models, performance, risk metrics |
| `pyportfolioopt` | 1.5.6 | MPT optimization (EfficientFrontier, CLA) |
| `cvxpy` | 1.8+ | Convex optimization solver |
| `pymysql` | — | MySQL database connection |
| `pandas` | 3.0+ | Data manipulation |
| `plotly` | 5.24+ | Interactive charts |
| `numpy` | 2.4+ | Numerical computation |

---

## 8. Limitations & Caveats

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **FMP API dependency** | FinanceToolkit requires FMP API for financial statements | Use cached data via External Datasets pattern; or accept API calls |
| **Piotroski/Altman data gaps** | Not all symbols may have financial statements | Exclude from quality screen; keep in universe with neutral score |
| **Fama-French data lag** | Factor data from Dartmouth may lag by ~1 month | Acceptable for strategic (not tactical) allocation |
| **CAPM assumptions** | Single-factor model oversimplifies expected returns | Blending with historical returns mitigates this |
| **No shorting** | Long-only constraint limits diversification benefit | Acceptable for personal brokerage portfolio |

---

## 9. Suggested Notebook Section Layout

| # | Section | Cells | Key Output |
|---|---------|-------|------------|
| 1 | Setup & Imports | 2 | Import FinanceToolkit + existing data layer |
| 2 | Load Positions & Prices | 1 | Reuse from existing notebook or re-run |
| 3 | Initialize FinanceToolkit | 1 | `Toolkit(tickers, api_key)` |
| 4 | Fundamental Quality Screen | 3 | Piotroski, Altman Z, quality score table |
| 5 | CAPM & Beta Analysis | 2 | CAPM expected returns, beta bar chart |
| 6 | Fama-French Factor Decomposition | 3 | Factor exposures, R² chart, factor correlations |
| 7 | Risk Dashboard | 3 | VaR, CVaR, Max Drawdown, Ulcer Index table + chart |
| 8 | Rolling Sharpe & Jensen's Alpha | 2 | Rolling Sharpe line plot, Alpha table |
| 9 | DuPont ROE Decomposition | 2 | Heatmap of ROE components |
| 10 | Blended Expected Returns | 1 | Historical + CAPM blend |
| 11 | Optimization (Enhanced) | 3 | Max Sharpe (Enhanced), Min CVaR, Risk Parity |
| 12 | Factor Exposure Comparison | 2 | Radar chart: Current vs Optimized |
| 13 | Portfolio-Level Weighted Metrics | 2 | Weighted fundamentals comparison table |
| 14 | Summary Dashboard | 2 | Final comparison table + chart |
| 15 | Key Takeaways & Next Steps | 1 | Markdown summary |
| | **Total** | **~30** | |

---

*Last updated: 2026-02-26*
