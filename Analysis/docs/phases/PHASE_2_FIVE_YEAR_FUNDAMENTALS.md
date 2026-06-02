# Phase 2: 5-Year Fundamental Analysis

**Version:** 1.1 — Updated 2026-03-22 (added earnings-quality, capital-efficiency, and structural-efficiency KPI packs)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| Income statement (5yr annual) | `obb.equity.fundamental.income` | Implemented (Cell 13) |
| Balance sheet (5yr annual) | `obb.equity.fundamental.balance` | Implemented (Cell 13) |
| Cash flow (5yr annual) | `obb.equity.fundamental.cash` | Implemented (Cell 13) |
| Financial ratios (5yr annual) | `obb.equity.fundamental.ratios` | Implemented (Cell 13) |
| Quarterly data (8 quarters) | Trend confirmation | **Not implemented** |
| Revenue CAGR (5Y) | Compound growth | **Not implemented** (only single YoY growth) |
| EPS CAGR (5Y) | Compound growth | **Not implemented** (only single YoY growth) |
| FCF CAGR (5Y) | Compound growth | **Not implemented** (only single YoY growth) |
| Gross Margin | Profitability | Implemented (Cell 15) |
| Operating Margin | Profitability | Implemented (Cell 15) |
| Net Margin | Profitability | Implemented (Cell 15) |
| ROIC | Capital efficiency | Implemented (Cell 15) |
| Debt/Equity | Balance sheet | Implemented (Cell 15) |
| Current Ratio | Liquidity | Implemented (Cell 15) |
| Interest Coverage | Solvency | **Not implemented** |
| Net Debt/EBITDA | Leverage | **Not implemented** |
| CFO/Net Income | Cash quality | **Not implemented** |
| FCF Margin | Cash quality | **Not implemented** |
| Capex/Revenue | Reinvestment | **Not implemented** |
| Per-phase scoring (6 categories) | Weighted 1-5 | **Not implemented** (scoring only in Phase 7) |
| Phase gate (>= 3.5) | Exit criteria | **Not implemented** |
| Provider | FinanceToolkit `ft.ratios` | Uses OpenBB endpoints directly |
| **DuPont ROE Decomposition (3-factor)** | `income_df`, `balance_df` | **Not implemented** |
| **Asset Turnover Trend (5Y)** | `income_df`, `balance_df` | **Not implemented** |
| **Accruals Ratio (Sloan Ratio)** | `income_df`, `cash_df`, `balance_df` | **Not implemented** |
| **Gross Profitability Ratio (Novy-Marx)** | `income_df`, `balance_df` | **Not implemented** |
| **Share Dilution / Buyback Trend (5Y)** | `income_df` or `metrics_df` | **Not implemented** |
| **Operating Leverage (5Y avg)** | `income_df` | **Not implemented** |
| **Dividend FCF Payout Ratio** | `cash_df` | **Not implemented** |
| **SG&A Efficiency Trend (5Y)** | `income_df` | **Not implemented** |

**Current notebook produces:** 9 KPIs in `fundamental_kpi_df` (3 growth, 3 margins, ROIC, Current Ratio, D/E).
**Original plan KPIs not yet in notebook:** 5Y CAGR (uses YoY instead), Interest Coverage, Net Debt/EBITDA, CFO/NI, FCF Margin, Capex/Revenue, quarterly comparison.
**v1.1 additions not yet in notebook:** DuPont ROE decomposition, Asset Turnover Trend, Accruals Ratio, Gross Profitability, Share Dilution, Operating Leverage, Dividend FCF Payout, SG&A Efficiency Trend.
**Key difference:** Growth metrics are single-period YoY, not 5-year compound growth rates. No earnings quality layer exists.

---

## Objective
Measure business quality, durability, and improvement trend using 5 years of statements and ratio KPIs. The v1.1 extension adds a full **earnings quality and capital efficiency layer** to catch businesses whose reported numbers look good but whose cash generation, capital allocation, or structural efficiency is deteriorating — all without adding any new data source beyond the four statement endpoints.

## Data Window
- Annual: last 5 fiscal years
- Quarterly: last 8 quarters (trend confirmation)

## KPI Packs (with layman logic)

### 1) Growth KPIs
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| Revenue CAGR (5Y) | Is the business getting bigger consistently? | > 8% for growth names, > 3% for mature names | 12% CAGR means revenue roughly doubled in ~6 years. |
| EPS CAGR (5Y) | Are profits per share compounding? | Positive and above revenue CAGR | If EPS grows faster than revenue, operating leverage is improving. |
| Free Cash Flow CAGR (5Y) | Is real cash generation growing? | Positive, stable | Revenue up but FCF flat can signal weak cash conversion. |

### 2) Profitability KPIs
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| Gross Margin | Pricing power after direct costs | Stable or rising | 45% to 48% over 5Y suggests stronger pricing or better mix. |
| Operating Margin | Efficiency after operating costs | Stable/rising trend | Margin dropping from 18% to 11% is a red flag. |
| Net Margin | Bottom-line efficiency | Positive and resilient | Net margin staying > 10% in downturn indicates resilience. |
| ROIC | Return on invested capital | > WACC + 3% | ROIC 16% vs WACC 9% implies value creation spread of 7%. |
| **Gross Profitability Ratio (Novy-Marx)** | Gross profit per dollar of assets — cleanest quality anchor | > 33% strong; rising trend preferred | A rising gross profitability ratio signals pricing power and moat strengthening. |

### 3) Balance Sheet & Solvency KPIs
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| Debt/Equity | How debt-heavy is the structure? | Sector-relative; avoid rising stress trend | Rising from 0.6 to 1.8 in 3 years needs debt-servicing review. |
| Interest Coverage | Can earnings cover interest bills? | > 4x safer | 2x means small earnings drop could pressure debt service. |
| Current Ratio | Near-term liquidity buffer | > 1.2 generally safer | 0.9 indicates short-term obligations exceed current assets. |
| Net Debt / EBITDA | Debt payback capacity | < 3x generally manageable | 5x suggests elevated refinancing risk. |

### 4) Cash Flow Quality KPIs
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| CFO / Net Income | Are reported profits backed by cash? | 0.9 to 1.2 healthy band | 0.5 means accrual-heavy earnings quality concern. |
| FCF Margin | Cash left after capex per revenue | Stable/rising | 14% FCF margin supports buybacks/deleveraging. |
| Capex / Revenue | Reinvestment intensity | Context-specific, stable regime | Sudden capex spike may be growth investment or stress. |
| **Accruals Ratio (Sloan Ratio)** | Gap between net income and cash earnings — measures earnings quality | Negative preferred (cash > income); > 10% is concern | Accruals ratio of +18% signals income is accrual-heavy and may revert. |

### 5) Capital Efficiency KPIs (Extended — v1.1)
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| **DuPont ROE (3-factor)** | Breaks ROE into margin × turnover × leverage so you can see *why* ROE is what it is | ROE > 15% driven by margin/turnover, not leverage | ROE 22% with equity multiplier 5× is a debt story, not a quality story. |
| **Asset Turnover Trend** | Is revenue growing proportionally to the asset base? | Stable or rising over 5Y | Falling asset turnover means each dollar of assets generates less revenue — a capital allocation warning. |
| **Share Dilution / Buyback Trend** | Is management returning capital (buybacks) or issuing new shares (dilution)? | Net shares reduced over 5Y | Shares up 20% over 5 years means EPS growth has been partly funded by dilution. |

### 6) Structural Efficiency KPIs (New category — v1.1)
| KPI | Layman explanation | Preferred signal | Example |
|---|---|---|---|
| **Operating Leverage** | How much do profits swing relative to revenue swings? | 1.0–1.5× manageable; > 2.5× high-risk in downturns | Operating leverage 2.0× means a 10% revenue drop creates a 20% profit decline. |
| **SG&A / Revenue Trend** | Is the cost of selling and running the business rising or falling as a share of revenue? | Declining over 5Y (operating leverage kicking in) | SG&A ratio rising from 22% to 28% means the business needs more effort to generate the same revenue — moat erosion signal. |
| **Dividend FCF Payout Ratio** | Can the company sustain its dividend purely from free cash flow? | < 75% FCF payout is comfortable | FCF payout > 100% means dividends are debt-funded — cut risk is high. For non-payers: N/A. |

---

## Analyst Rationale and References for v1.1 Additions

### DuPont ROE Decomposition
**Why it was added:** ROE in isolation is one of the most misleading metrics in fundamental analysis. A highly leveraged firm and a capital-light compounder can post identical ROE figures. The three-factor DuPont decomposition (Net Margin × Asset Turnover × Equity Multiplier) makes this distinction explicit and is a prerequisite for any serious capital efficiency assessment.
**Formula:** `ROE = (Net Income / Revenue) × (Revenue / Total Assets) × (Total Assets / Equity)`
**Reference:** Penman, S. (2013). *Financial Statement Analysis and Security Valuation* (5th ed.). McGraw-Hill, Ch. 11. Lev, B. & Thiagarajan, S.R. (1993). "Fundamental Information Analysis." *The Accounting Review*, 68(3), 190–215.
**Threshold:** ROE > 15% with Equity Multiplier < 2.5 = quality signal. ROE > 15% but Equity Multiplier > 4× = investigate leverage.

### Asset Turnover Trend
**Why it was added:** A business can look profitable while quietly becoming less capital-efficient — more assets required to produce the same revenue. This is an early warning of failed acquisitions, competitive moat erosion, or capital misallocation, and it surfaces in the asset turnover trend before it shows up in margins.
**Formula:** `Asset Turnover = Revenue / Average Total Assets` (5-year time series)
**Reference:** Fairfield, P.M., Whisenant, J.S. & Yohn, T.L. (2003). "Accrued Earnings and Growth: Implications for Future Profitability and Market Mispricing." *The Accounting Review*, 78(1), 353–371.
**Threshold:** Declining by > 0.10 per year for 3+ consecutive years = capital allocation concern.

### Accruals Ratio (Sloan Ratio)
**Why it was added:** This is the single most powerful earnings quality screen available from statement data alone. When a company's net income consistently exceeds its operating cash flow, the gap is made of accounting accruals — entries that book revenue or defer costs without real cash movement. High accruals statistically predict earnings reversals, restatements, and subsequent stock underperformance. The Sloan (1996) finding has been replicated across markets and decades.
**Formula:** `Accruals = Net Income − CFO`; `Accruals Ratio = Accruals / Average Net Operating Assets`
where `Net Operating Assets = (Total Assets − Cash) − (Total Liabilities − Total Debt)`
**Reference:** Sloan, R.G. (1996). "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?" *The Accounting Review*, 71(3), 289–315. — One of the 20 most-cited papers in accounting research. Richardson, S., Sloan, R., Soliman, M. & Tuna, I. (2005). "Accrual Reliability, Earnings Persistence and Stock Prices." *Journal of Accounting and Economics*, 39(3), 437–485.
**Threshold:** Ratio < 0% = cash earnings exceed reported income (strong quality). 0–10% = acceptable. > 10% = elevated concern. > 20% = automatic gate warning.

### Gross Profitability Ratio (Novy-Marx)
**Why it was added:** Net income is easy to depress with legitimate or aggressive accounting choices (D&A policy, R&D capitalisation, restructuring charges). Gross profit — revenue minus cost of goods sold only — is the least manipulable income line because it reflects actual product economics most directly. Novy-Marx showed it predicts future stock returns as powerfully as the book-to-market value factor, and it works especially well for identifying quality growth companies that screens based on P/E miss.
**Formula:** `Gross Profitability = Gross Profit / Total Assets`
**Reference:** Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1–28. The gross profitability concept is the basis for the RMW (Robust Minus Weak profitability) factor in: Fama, E.F. & French, K.R. (2015). "A Five-Factor Asset Pricing Model." *Journal of Financial Economics*, 116(1), 1–22.
**Threshold:** > 33% = strong quality signal (Novy-Marx long-side selection threshold). < 20% = weak quality profile.

### Share Dilution / Buyback Trend
**Why it was added:** EPS growth is the most-watched metric by equity investors, but it can be manufactured by shrinking the share count through buybacks, or artificially suppressed by dilution from stock-based compensation and secondary offerings. Tracking the net change in shares outstanding over 5 years exposes whether EPS growth is business-driven or financial-engineering-driven.
**Formula:** `Dilution 5Y = (shares_latest / shares_5yr_ago) − 1`; `Annual Dilution Rate = shares.pct_change()` per year
**Reference:** Loughran, T. & Ritter, J.R. (1995). "The New Issues Puzzle." *Journal of Finance*, 50(1), 23–51 — dilutors underperform by ~7% per year over 5 years post-issuance. Ikenberry, D., Lakonishok, J. & Vermaelen, T. (1995). "Market Underreaction to Open Market Share Repurchases." *Journal of Financial Economics*, 39(2), 181–208 — buyback announcers earn ~12% abnormal returns over 4 years. Pontiff, J. & Woodgate, A. (2008). "Share Issuance and Cross-Sectional Returns." *Journal of Finance*, 63(2), 921–945.
**Threshold:** Net 5Y share reduction > 5% = strong capital return signal. Net 5Y dilution > 10% = investigate rationale. > 20% = strong negative signal.

### Operating Leverage
**Why it was added:** Two businesses with identical revenue CAGR and margins can have very different risk profiles depending on the proportion of fixed costs. A high-operating-leverage company will see profits collapse disproportionately in a revenue downturn — exactly the scenario that catches investors off-guard in sector rotations or recessions. Knowing operating leverage ahead of entry lets you right-size positions and stress-test the thesis properly.
**Formula:** `Operating Leverage = %ΔEBIT / %ΔRevenue` (year-over-year, averaged over 5 years)
**Reference:** Novy-Marx, R. (2011). "Operating Leverage." *Review of Finance*, 15(1), 103–134 — formalises how operating leverage creates systematic risk independent of financial leverage. Lev, B. (1974). "On the Association Between Operating Leverage and Risk." *Journal of Financial and Quantitative Analysis*, 9(4), 627–641 — foundational empirical paper on operating leverage and beta.
**Threshold:** 1.0–1.5× = moderate. 1.5–2.5× = high; requires confidence in revenue trajectory. > 2.5× = very high; strong cyclical risk.

### Dividend FCF Payout Ratio
**Why it was added:** Many income investors monitor the earnings payout ratio, which management can manipulate through depreciation policy and non-cash charges. The FCF payout ratio exposes the true cash burden of the dividend. A company paying out 95% of earnings but 130% of FCF is funding the dividend from debt — dividend cut risk is high and under-appreciated.
**Formula:** `FCF Payout = Dividends Paid / Free Cash Flow` (set to N/A if dividends paid = 0)
**Reference:** Lintner, J. (1956). "Distribution of Incomes of Corporations Among Dividends, Retained Earnings, and Taxes." *American Economic Review*, 46(2), 97–113 — established that managers smooth dividends and resist cuts until they become unavoidable. DeAngelo, H., DeAngelo, L. & Stulz, R.M. (2006). "Dividend Policy and the Earned/Contributed Capital Mix." *Journal of Financial Economics*, 81(2), 227–254.
**Threshold:** FCF payout < 50% = very sustainable. 50–75% = sustainable, monitor trend. > 90% = stress zone. > 100% = automatic flag.

### SG&A / Revenue Trend
**Why it was added:** Rising selling and administrative costs as a share of revenue is one of the subtlest early signals that a moat is softening. A truly dominant business should require proportionally less SGA spend as it scales — lower customer acquisition costs, stronger word-of-mouth, established distribution. When SGA/Revenue rises consistently over 5 years, the business is working harder to maintain the same revenue base.
**Formula:** `SG&A Ratio = SG&A Expenses / Revenue` (5-year time series); `SG&A Trend = average annual change in ratio`
**Reference:** Anderson, M.C., Banker, R.D. & Janakiraman, S.N. (2003). "Are Selling, General, and Administrative Costs 'Sticky'?" *The Accounting Review*, 78(1), 47–63 — documented cost stickiness asymmetry: SGA rises faster with revenue growth than it falls with revenue decline, making the trend ratio informative about underlying business dynamics.
**Threshold:** SG&A ratio declining over 5Y = operating leverage at work (positive). Rising > 2 percentage points over 5Y = investigate. > 35% in a mature non-growth business = structural inefficiency.

---

## Programmatic Pull

### Currently implemented in notebook (Cell 13)
```python
income_obj, income_provider = call_obb(obb.equity.fundamental.income, symbol=SYMBOL, period="annual", limit=5)
balance_obj, balance_provider = call_obb(obb.equity.fundamental.balance, symbol=SYMBOL, period="annual", limit=5)
cash_obj, cash_provider = call_obb(obb.equity.fundamental.cash, symbol=SYMBOL, period="annual", limit=5)
ratios_obj, ratios_provider = call_obb(obb.equity.fundamental.ratios, symbol=SYMBOL, period="annual", limit=5)
```

KPI extraction in Cell 15 uses `latest_col_value()` with multiple column-name candidates and `growth_from_two_rows()` for YoY growth. Fallback computation from raw statements when ratio fields are missing.

### Planned module implementation (`phase2_fundamentals` in `stock_analysis.py`)
```python
# All four endpoints — no new API calls required for v1.1 additions
income_df  = obb.equity.fundamental.income(symbol=cfg.symbol, period="annual", limit=5, provider=cfg.provider).to_df()
balance_df = obb.equity.fundamental.balance(symbol=cfg.symbol, period="annual", limit=5, provider=cfg.provider).to_df()
cash_df    = obb.equity.fundamental.cash(symbol=cfg.symbol, period="annual", limit=5, provider=cfg.provider).to_df()
ratios_df  = obb.equity.fundamental.ratios(symbol=cfg.symbol, period="annual", limit=5, provider=cfg.provider).to_df()

# --- Original KPIs ---
revenue_cagr  = _cagr(income_df["revenue"], years=5)
eps_cagr      = _cagr(income_df["eps_diluted"], years=5)
fcf_cagr      = _cagr(cash_df["free_cash_flow"], years=5)

# --- v1.1 additions (all from existing DataFrames) ---

# DuPont ROE decomposition
net_margin_5y   = income_df["net_income"] / income_df["revenue"]
asset_turn_5y   = income_df["revenue"] / balance_df["total_assets"].rolling(2).mean()
equity_mult_5y  = balance_df["total_assets"] / balance_df["total_equity"]
roe_decomp_df   = pd.DataFrame({
    "net_margin": net_margin_5y,
    "asset_turnover": asset_turn_5y,
    "equity_multiplier": equity_mult_5y,
    "roe_check": net_margin_5y * asset_turn_5y * equity_mult_5y,
})

# Asset turnover trend
asset_turn_trend = asset_turn_5y.diff().mean()

# Accruals ratio (Sloan)
accruals          = income_df["net_income"] - cash_df["operating_cash_flow"]
net_op_assets     = (balance_df["total_assets"] - balance_df["cash_and_equivalents"]) \
                  - (balance_df["total_liabilities"] - balance_df["total_debt"])
accruals_ratio    = (accruals / net_op_assets.rolling(2).mean()).iloc[-1]

# Gross profitability (Novy-Marx)
gross_profitability = (income_df["gross_profit"] / balance_df["total_assets"]).iloc[-1]

# Share dilution
shares_series  = income_df.get("shares_outstanding", ratios_df.get("shares"))
dilution_5y    = (shares_series.iloc[-1] / shares_series.iloc[0]) - 1 if shares_series is not None else float("nan")

# Operating leverage
pct_ebit_chg   = income_df["operating_income"].pct_change()
pct_rev_chg    = income_df["revenue"].pct_change()
op_leverage_5y = (pct_ebit_chg / pct_rev_chg).replace([np.inf, -np.inf], np.nan).mean()

# SG&A efficiency trend
sga_ratio_series = income_df["selling_general_administrative_expenses"] / income_df["revenue"]
sga_ratio_trend  = sga_ratio_series.diff().mean()

# Dividend FCF payout
dividends_paid   = cash_df["dividends_paid"].abs()
fcf_payout_ratio = (dividends_paid / cash_df["free_cash_flow"]).iloc[-1] \
                   if dividends_paid.sum() > 0 else float("nan")
```

### Planned but not yet implemented (legacy FinanceToolkit path — superseded)
```python
# This path is superseded by the module implementation above.
# Retained here for reference only; the module does NOT use FinanceToolkit.
from financetoolkit import Toolkit
ft = Toolkit([SYMBOL], api_key=API_KEY, start_date="2021-01-01", quarterly=False)
...
```

---

## Fundamental Scorecard (updated — v1.1)

The original five categories are extended to six. Weights are rebalanced to give more credit to earnings quality and capital efficiency, which are empirically stronger return predictors than aggregate growth alone.

| Category | Weight | KPIs Included | Change from v1.0 |
|---|---:|---|---|
| Growth quality | 20% | Revenue CAGR (5Y), EPS CAGR (5Y), FCF CAGR (5Y) | Reduced from 25% |
| Profitability quality | 20% | Gross Margin trend, Op. Margin trend, Net Margin, ROIC, **Gross Profitability (Novy-Marx)** | Unchanged weight; gross profitability added |
| Capital efficiency | 20% | ROIC spread vs WACC, **DuPont ROE decomposition**, **Asset Turnover trend**, **Share Dilution 5Y** | Unchanged weight; three new inputs |
| Balance sheet safety | 15% | D/E, Interest Coverage, Current Ratio, Net Debt/EBITDA | Reduced from 20% |
| Cash flow & earnings quality | 15% | CFO/NI, FCF Margin, Capex/Revenue, **Accruals Ratio (Sloan)** | Increased from 10%; Sloan ratio added |
| Structural efficiency | 10% | **Operating Leverage**, **SG&A Efficiency Trend**, **Dividend FCF Payout** | **New category** |

**Total: 100%**

Scoring rules:
- Score each category 1–5 using the thresholds documented per KPI above.
- Weighted score ≥ 3.5 required to continue.
- **Hard floor rule:** Any single category scoring ≤ 1.5 triggers a mandatory "Hold/Watch" cap on the Phase 7 composite score — even if the aggregate score passes 3.5. This prevents a catastrophically weak dimension from being averaged away.
- At least 3 of 6 categories must show a trend-improving signal.

---

## Exit Criteria
- No major accounting quality concern (Accruals Ratio < 20%; no going-concern flags)
- Weighted score ≥ 3.5/5.0
- At least 3 of 6 categories trend-improving
- Hard floor rule: no category at ≤ 1.5

---

*Phase 2 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` Appendix C*
