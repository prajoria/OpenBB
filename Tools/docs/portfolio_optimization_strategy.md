# Portfolio Optimization Strategy

> **Notebook:** `Analysis/myPortfolioOptimization.ipynb`
> **Script dependency:** Data from `parse_fidelity_positions.py` + `fetch_position_history.py`

---

## 1. Overview

This document describes the portfolio optimization strategy implemented in
the Jupyter notebook.  The approach applies **Modern Portfolio Theory (MPT)**
to real equity positions loaded from the MySQL database.

### Data Sources

| Source | Table | Content |
|--------|-------|---------|
| Fidelity HTML parser | `Portfolio_Positions` | Current holdings: symbol, quantity, value, cost basis, account |
| FMP price cache | `equity_historical` | 3 years of daily OHLCV prices for 80+ symbols |
| Computed | `Account_Owner` | Account → owner mapping |

### Inspiration

Based on the OpenBB example notebook
`Analysis/portfolioOptimizationUsingModernPortfolioTheory.ipynb` (crypto MPT
by Ambrose Ikpele), adapted for real equity portfolios.

---

## 2. Strategy Steps

### Step 1 — Load Current Positions

```sql
SELECT account_name, symbol, SUM(quantity), SUM(current_value), ...
FROM Portfolio_Positions
WHERE snapshot_date = (SELECT MAX(snapshot_date) ...)
GROUP BY account_name, symbol
```

Aggregates cost-basis lots into per-symbol totals.  Excludes cash and
zero-quantity positions.

### Step 2 — Build Price Matrix

Load 3 years of daily close prices from `equity_historical`.
- Pivot to wide format: `date × symbol`
- Drop symbols with <60% coverage
- Forward-fill gaps (up to 5 days) for holidays
- Result: clean matrix suitable for return/covariance estimation

**Why 3 years?** Shorter windows are too noisy; longer windows may include
regime changes (COVID, rate hikes) that distort covariance estimates.

### Step 3 — Expected Returns

Uses `pypfopt.expected_returns.mean_historical_return()`:

$$\mu_i = \left(\prod_{t=1}^{N}(1 + r_{i,t})\right)^{252/N} - 1$$

- **Frequency:** 252 trading days/year (equities, not 365 for crypto)
- **Compounding:** True (geometric returns are more realistic than arithmetic)

### Step 4 — Covariance Matrix

Uses **Ledoit-Wolf shrinkage** (`pypfopt.CovarianceShrinkage`):

$$\hat{\Sigma} = \alpha \cdot S + (1 - \alpha) \cdot F$$

Where:
- $S$ = sample covariance matrix (noisy with many assets)
- $F$ = structured target (constant correlation model)
- $\alpha$ = shrinkage intensity (estimated from data)

**Why shrinkage?**  With 80+ assets and ~750 trading days, the sample
covariance is poorly conditioned.  Shrinkage regularizes it, producing
more stable optimization weights.

### Step 5 — Optimization

Three portfolios are computed:

| Portfolio | Objective | Constraint |
|-----------|-----------|------------|
| **Max Sharpe** | Maximize $\frac{\mu_p - r_f}{\sigma_p}$ | Long-only, ≤25% per asset |
| **Min Volatility** | Minimize $\sigma_p$ | Long-only, ≤25% per asset |
| **Current** | (measured, not optimized) | Actual allocations |

The 25% per-asset cap prevents extreme concentration.

### Step 6 — Comparison & Visualization

- **Efficient frontier** plot with all three portfolios marked
- **Diverging bar chart** showing rebalancing direction (buy ↑ / sell ↓)
- **Treemap** of current allocation with gain/loss coloring
- **Sunburst** chart showing account → symbol hierarchy
- **Correlation heatmap** for top 20 holdings
- **Cumulative returns** backtest: current vs optimal

### Step 7 — Discrete Allocation

Converts fractional optimal weights into whole-share trade orders
using `pypfopt.DiscreteAllocation` with a greedy algorithm.

---

## 3. Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| History window | 3 years | Balance between recency and statistical significance |
| Trading frequency | 252 days/year | US equity market convention |
| Risk-free rate | 4.5% | Approximate T-bill rate (2025–2026) |
| Max weight per asset | 25% | Prevent over-concentration |
| Min data coverage | 60% | Exclude recently listed or thinly-traded symbols |
| Compounding | True | Geometric returns are more realistic |
| Covariance method | Ledoit-Wolf | Robust with $p > N/5$ assets |

---

## 4. Limitations & Caveats

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| **Normality assumption** | MPT assumes Gaussian returns; real returns have fat tails | Use shrinkage; consider Black-Litterman in future |
| **Stationarity assumption** | Past correlations may not persist | Use 3-year window; rerun periodically |
| **No transaction costs** | Optimal portfolio ignores trading fees | Use discrete allocation to minimize small trades |
| **No tax modeling** | Rebalancing in taxable accounts triggers capital gains | Future: add tax-aware rebalancing layer |
| **No wash-sale detection** | Selling at a loss and rebuying within 30 days is tax-inefficient | Future: add wash-sale constraint |
| **No sector constraints** | Optimizer may concentrate in one sector | Future: add sector-level diversification constraints |
| **Survivorship bias** | Only current holdings are optimized; past failures excluded | Accept as limitation of available data |

---

## 5. Future Enhancements

| # | Enhancement | Description |
|---|-------------|-------------|
| 1 | **Black-Litterman model** | Incorporate subjective views (e.g., "I expect MSFT to outperform by 2%") into expected returns |
| 2 | **Tax-aware rebalancing** | Minimize capital gains in Individual (TOD) account; prioritize rebalancing in tax-sheltered accounts (Roth, 401k) |
| 3 | **Sector constraints** | Force diversification across GICS sectors (pulled from FMP company profiles) |
| 4 | **Dividend optimization** | Incorporate dividend yield into expected returns; optimize for total return |
| 5 | **Monte Carlo simulation** | Generate confidence intervals around expected returns using bootstrapped return distributions |
| 6 | **Risk parity** | Equal risk contribution from each asset (alternative to mean-variance) |
| 7 | **Regime detection** | Detect bull/bear regimes and adjust covariance estimates accordingly |
| 8 | **Automated scheduling** | Re-run optimization monthly; compare allocation drift over time |

---

## 6. Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pyportfolioopt` | 1.5.6 | MPT optimization (EfficientFrontier, CLA, CovarianceShrinkage) |
| `cvxpy` | 1.8+ | Convex optimization solver (backend for pypfopt) |
| `pymysql` | — | MySQL database connection |
| `pandas` | 3.0+ | Data manipulation |
| `plotly` | 5.24+ | Interactive charts |
| `matplotlib` | 3.10+ | Static charts (fallback) |
| `numpy` | 2.4+ | Numerical computation |
| `scipy` | 1.17+ | Statistical functions |

---

## 7. How to Run

```powershell
# 1. Ensure positions and history are loaded
python Tools/parse_fidelity_positions.py --file "<HTML_PATH>" --owner <OWNER>
python Tools/fetch_position_history.py --database openbb_fmp_cache_test

# 2. Open and run the notebook
jupyter lab Analysis/myPortfolioOptimization.ipynb
# Or run all cells in VS Code
```

---

*Last updated: 2026-02-21*
