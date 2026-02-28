# Phase 2: 5-Year Fundamental Analysis

## Objective
Measure business quality, durability, and improvement trend using 5 years of statements and ratio KPIs.

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

## Programmatic Pull

```python
from financetoolkit import Toolkit

ft = Toolkit([SYMBOL], api_key=API_KEY, start_date="2021-01-01", quarterly=False)
ratios = ft.ratios

income = ft.get_income_statement()
balance = ft.get_balance_sheet_statement()
cash = ft.get_cash_flow_statement()

growth = {
    "revenue_growth": ratios.get_revenue_growth(),
    "eps_growth": ratios.get_earnings_per_share_growth(),
    "fcf_growth": ratios.get_free_cash_flow_growth(),
}

profitability = {
    "gross_margin": ratios.get_gross_margin(),
    "operating_margin": ratios.get_operating_margin(),
    "net_margin": ratios.get_net_profit_margin(),
    "roic": ratios.get_return_on_invested_capital(),
}
```

## Fundamental Scorecard (weighted)
| Category | Weight | Scoring logic |
|---|---:|---|
| Growth quality | 25% | CAGR strength + consistency |
| Profitability quality | 25% | Margin level + trend |
| Capital efficiency | 20% | ROIC spread vs WACC |
| Balance sheet safety | 20% | Leverage + liquidity |
| Cash flow quality | 10% | CFO/NI + FCF stability |

- Score each category from 1 to 5
- Weighted score ≥ 3.5 required to continue

## Exit Criteria
- No major accounting quality concern
- Weighted score ≥ 3.5/5.0
- At least 3 of 5 categories trend-improving
