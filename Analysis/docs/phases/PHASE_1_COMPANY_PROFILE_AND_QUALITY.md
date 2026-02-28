# Phase 1: Company Profile & Business Quality Screen

## Objective
Build a business-first view before touching charts. This phase answers: “Is this a business we should even spend time analyzing?”

## Inputs
- Stock symbol (single ticker)
- Country/listing exchange
- Benchmark ETF (default: `SPY`)

## KPIs and Why They Matter

| KPI | What it means (simple) | Practical threshold / check | Example interpretation |
|---|---|---|---|
| Market Cap | Company size bucket | Large / Mid / Small | A $200B company usually has lower survival risk than a $1B company. |
| Revenue Mix by Geography | Dependence on regions | No single risky region > 50% unless justified | If 70% revenue is from one region under trade pressure, risk is concentrated. |
| Revenue Mix by Segment | Product concentration | Top segment concentration understood and tracked | If one segment is 80%, demand shock can hurt total revenue fast. |
| Insider Ownership | Management skin-in-the-game | Positive if meaningful and stable | Rising insider ownership can signal confidence. |
| Institutional Ownership | Professional participation | Track trend, not absolute alone | Sharp drop in institutional ownership can indicate changing conviction. |
| Analyst Revision Trend | Forward expectation changes | Upward revisions preferred | EPS estimate revisions up for 3 months often support rerating. |

## Mandatory Qualitative Questions
1. What exactly does the company sell, and to whom?
2. What moat exists: brand, switching costs, patents, network effects, scale?
3. What can break the thesis in 12 months?
4. Is management capital allocation shareholder-friendly (buybacks/dividends/ROIC discipline)?
5. Which external factors dominate outcomes (rates, commodities, regulation)?

## Programmatic Workflow (OpenBB + FinanceToolkit)

```python
from openbb import obb

profile = obb.equity.profile(symbol=SYMBOL, provider="fmp")
metrics = obb.equity.fundamental.metrics(symbol=SYMBOL, period="annual", limit=5, provider="fmp")
geo = obb.equity.fundamental.revenue_per_geography(symbol=SYMBOL, period="annual", provider="fmp")
insiders = obb.equity.ownership.insider_trading(symbol=SYMBOL, provider="fmp")
institutions = obb.equity.ownership.institutional(symbol=SYMBOL, provider="fmp")
price_targets = obb.equity.estimates.price_target(symbol=SYMBOL, provider="benzinga")
```

## Deliverable
Produce a one-page profile note with:
- Business summary (5 lines)
- Top 3 growth drivers
- Top 3 risks
- “Proceed / Do Not Proceed” decision for Phase 2

## Exit Criteria
Proceed only if all are true:
- Business model is understandable
- No unpriced existential risk identified
- Data coverage is sufficient for 5-year analysis
