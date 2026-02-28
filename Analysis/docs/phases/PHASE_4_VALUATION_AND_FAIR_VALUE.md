# Phase 4: Valuation & Fair Value Estimation

## Objective
Convert business quality into a price decision: cheap, fair, or expensive.

## Valuation Approach (triangulation)
Use three lenses together:
1. Relative multiples vs history and peers
2. Intrinsic value (DCF)
3. Quality overlays (Piotroski, Altman, ROIC spread)

## KPI Set and Interpretation

### A) Relative Multiples
| KPI | Layman explanation | Practical use | Example |
|---|---|---|---|
| P/E | Years of earnings market is paying for | Compare vs 5Y median and sector | P/E 18 vs own 5Y median 24 may indicate derating opportunity. |
| EV/EBITDA | Enterprise-level operating multiple | Better cross-company compare than P/E alone | EV/EBITDA 9 vs peers 13 can suggest undervaluation. |
| P/FCF | Price paid for real cash | High signal for capital-heavy firms | P/FCF 14 with stable FCF margin is often healthier than low P/E with weak cash. |
| P/S | Useful when earnings are cyclical/noisy | Context with gross margin profile | P/S expansion without margin improvement is risky. |

### B) Intrinsic Value KPIs
| KPI | Layman explanation | Decision use |
|---|---|---|
| DCF Fair Value | Estimated present value of future cash flows | Anchor long-term worth |
| Margin of Safety | Discount vs fair value | Buy zone often starts at ≥ 15–20% discount |
| WACC | Required return hurdle for capital providers | Sensitivity driver; higher WACC lowers fair value |
| Terminal Growth | Long-run growth assumption | Keep conservative (e.g., 2–3% for mature firms) |

### C) Quality Overlay KPIs
| KPI | Layman explanation | Rule of thumb |
|---|---|---|
| Piotroski F-Score | 9-point financial health checklist | ≥ 7 strong, ≤ 3 weak |
| Altman Z-Score | Distress risk score | > 2.99 safer zone |
| ROIC - WACC spread | Value creation gap | Positive and stable preferred |

## Programmatic Pull

```python
# Relative valuation
metrics = obb.equity.fundamental.metrics(symbol=SYMBOL, period="annual", limit=5, provider="fmp")

# FinanceToolkit ratios/models
ratios = ft.ratios
models = ft.models

pe = ratios.get_price_earnings_ratio()
ev_ebitda = ratios.get_ev_to_ebitda()
p_fcf = ratios.get_price_to_free_cash_flow_ratio()
ps = ratios.get_price_to_sales_ratio()

wacc = models.get_weighted_average_cost_of_capital()
intrinsic = models.get_intrinsic_valuation()
piotroski = models.get_piotroski_score()
altman = models.get_altman_z_score()
```

## Valuation Decision Grid
| Condition | Interpretation | Action |
|---|---|---|
| MOS ≥ 20% and quality strong | Attractive asymmetry | Candidate buy |
| MOS 5–20% | Mildly attractive/fair | Watchlist or partial entry |
| MOS within ±5% | Fair value | Hold / wait for setup |
| Overvalued > 15% with weak momentum | Poor risk-reward | Avoid / trim |

## Exit Criteria
- Fair value from at least 2 methods aligns in direction
- Margin of safety explicitly computed
- Sensitivity table completed (WACC ±1%, terminal growth ±0.5%)
