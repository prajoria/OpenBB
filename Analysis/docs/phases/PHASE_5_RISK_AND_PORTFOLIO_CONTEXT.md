# Phase 5: Risk Assessment & Portfolio Context

## Objective
Decide if the stock fits risk budget and portfolio role, not just if it looks attractive standalone.

## Risk KPI Set

### A) Return-Per-Risk KPIs
| KPI | Layman explanation | Typical reading | Example |
|---|---|---|---|
| Sharpe Ratio | Return earned per unit of total volatility | > 1.0 good, > 1.5 strong | Sharpe 0.3 means returns did not compensate volatility. |
| Sortino Ratio | Return per downside volatility only | Better for skewed returns | Sortino much lower than Sharpe implies downside shocks are driving risk. |
| Jensen’s Alpha | Return beyond CAPM expectation | Positive preferred | Alpha +3% suggests outperformance after market beta adjustment. |

### B) Drawdown & Tail Risk KPIs
| KPI | Layman explanation | Threshold guidance | Example |
|---|---|---|---|
| Max Drawdown | Worst peak-to-trough loss historically | < 30% preferred for core holdings | -52% drawdown requires very high conviction and smaller sizing. |
| VaR (95%) | One-day loss level not exceeded 95% of days | Compare vs risk budget | VaR -2.5% means typical bad day can lose 2.5%. |
| CVaR / Expected Shortfall | Average loss on worst days | Must be acceptable under stress | CVaR -5% implies severe downside on tail events. |
| Ulcer Index | Depth + duration of drawdowns | Lower is better | Two stocks with same volatility can have very different ulcer index. |

### C) Market Exposure KPIs
| KPI | Layman explanation | Decision use |
|---|---|---|
| Beta | Sensitivity to market moves | Beta > 1.2 increases portfolio swing |
| Correlation vs benchmark | Similarity to index behavior | High correlation adds less diversification |
| Correlation vs existing holdings | Position overlap risk | Avoid stacking highly correlated bets |

## Programmatic Pull

```python
perf = ft_ta.performance
risk = ft_ta.risk

sharpe = perf.get_sharpe_ratio()
sortino = perf.get_sortino_ratio()
alpha = perf.get_jensens_alpha()
beta = perf.get_beta()

var_95 = risk.get_value_at_risk()
cvar_95 = risk.get_conditional_value_at_risk()
mdd = risk.get_maximum_drawdown()
ulcer = risk.get_ulcer_index()
```

## Portfolio Fit Rules
- Core position candidate: Sharpe > 1, Max Drawdown < 35%, Beta near portfolio target
- Satellite position candidate: higher growth but capped size due to drawdown/tail risk
- Reject if tail risk breaches portfolio stress tolerance

## Position Sizing Template
- Conviction score 1–5 from prior phases
- Base size = 1%
- Add 1% per conviction point above 2
- Cap by risk: reduce size if `Max Drawdown > 40%` or `CVaR` in worst quartile

## Exit Criteria
- Position size recommendation documented with risk rationale
- Stress scenario note included (market -20%, rates +100 bps, sector shock)
