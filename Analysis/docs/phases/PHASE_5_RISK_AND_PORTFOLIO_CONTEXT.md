# Phase 5: Risk Assessment & Portfolio Context

**Version:** 1.1 — Updated 2026-03-22 (added Calmar Ratio, Gain-to-Pain, regime-conditional beta, drawdown recovery analysis, Kelly position sizing, and balanced fundamental-risk integration)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| Benchmark historical prices | `obb.equity.price.historical` (SPY) | Implemented (Cell 21) |
| Sharpe Ratio | Return per total risk | Implemented (Cell 21) |
| Sortino Ratio | Return per downside risk | Implemented (Cell 21) |
| Jensen's Alpha | CAPM excess return | Implemented (Cell 21) |
| Beta | Market sensitivity | Implemented (Cell 21) |
| VaR (95%) | Tail loss threshold | Implemented (Cell 21) |
| CVaR / Expected Shortfall | Average tail loss | Implemented (Cell 21) |
| Max Drawdown | Worst peak-to-trough | Implemented (Cell 21) |
| Ulcer Index | Drawdown depth+duration | Implemented (Cell 21) |
| Correlation vs benchmark | Co-movement measure | **Not implemented** (computed in Phase 6 heatmap but not standalone) |
| Correlation vs existing holdings | Portfolio overlap | **Not implemented** |
| Position sizing template | Conviction-to-size rules | **Not implemented** |
| Stress scenario notes | Market -20%, rates +100bps | **Not implemented** |
| Portfolio fit rules | Core/satellite classification | **Not implemented** |
| **Calmar Ratio** | Return per unit of max drawdown | **Not implemented** |
| **Gain-to-Pain Ratio** | Ratio of total gains to total losses | **Not implemented** |
| **Regime-conditional beta** | Separate beta in up-markets vs down-markets | **Not implemented** |
| **Drawdown recovery analysis** | How long does this stock take to recover from drawdowns? | **Not implemented** |
| **Kelly position sizing** | Mathematically optimal position size from win rate and R-ratio | **Not implemented** |
| **Fundamental risk integration** | Using Phase 2 accruals, leverage, and operating leverage to adjust risk score | **Not implemented** |
| Provider | FinanceToolkit `ft_ta.performance/risk` | Computed manually with pandas/numpy |

**Current notebook outputs:** 8 risk KPIs in `risk_kpi_df` — all 8 core metrics implemented.
**Well-implemented phase.** Gaps: position sizing, stress scenarios, correlation vs holdings, portfolio classification, Calmar, Gain-to-Pain, regime beta, recovery analysis, Kelly sizing, fundamental risk integration.

---

## Objective
Decide whether the stock fits the risk budget and portfolio role — not just whether it looks attractive standalone. A position that is fundamentally compelling but risk-incompatible with the portfolio should either be sized down or excluded. Risk management is not a secondary concern; it is the primary constraint on position construction.

---

## Risk KPI Set

### A) Return-Per-Risk KPIs
| KPI | Layman explanation | Typical reading | Example |
|---|---|---|---|
| Sharpe Ratio | Return per unit of *total* volatility (up and down moves counted equally) | > 1.0 good; > 1.5 strong | Sharpe 0.3: returns did not compensate the volatility experienced. |
| Sortino Ratio | Return per unit of *downside* volatility only (only counts losses, not gains) | Higher than Sharpe in quality names | Sortino much lower than Sharpe = downside shocks are asymmetrically large. |
| Jensen's Alpha | Return beyond what CAPM predicted given the stock's market risk | Positive and significant preferred | Alpha +3% = outperformed the risk-adjusted market expectation by 3 percentage points. |
| **Calmar Ratio** | Annualised return divided by maximum drawdown — captures if the ride was worth the worst pain | > 1.0 acceptable; > 2.0 strong | Calmar 0.4: you earned 40% of what you lost at the worst point — poor risk/reward. |
| **Gain-to-Pain Ratio** | Total of all positive returns divided by absolute total of all negative returns | > 1.0 means more gained than lost on aggregate | A ratio of 1.5 means for every $1 lost on down days, $1.50 was gained on up days. |

**Why Calmar Ratio was added:** The Sharpe Ratio penalises all volatility equally — a stock that shoots up fast gets penalised the same as one that crashes down. The Calmar Ratio answers a more practical question: "If I had the worst luck and bought at the top, would the long-run return justify that pain?" Investors with loss aversion (psychologically, almost everyone) benefit more from the Calmar frame than from Sharpe. A stock with Sharpe 1.4 but Calmar 0.3 had a catastrophic drawdown that the Sharpe ratio masked.
*Reference: Young, T.W. (1991). "Calmar Ratio: A Smoother Tool." Futures, 20(1). Also used extensively in hedge fund due diligence frameworks.*

**Why Gain-to-Pain Ratio was added:** Developed by Jack Schwager (author of the Market Wizards series), the Gain-to-Pain Ratio captures the day-to-day quality of returns — whether the stock consistently delivers positive days that outweigh its negative days. Unlike Sharpe, it is not sensitive to whether gains/losses are normally distributed, making it a more robust measure for skewed return distributions typical of individual equities.
*Reference: Schwager, J.D. (2012). Hedge Fund Market Wizards. Wiley, Appendix A — introduces and explains the Gain-to-Pain Ratio.*

### B) Drawdown & Tail Risk KPIs
| KPI | Layman explanation | Threshold guidance | Example |
|---|---|---|---|
| Max Drawdown | Worst peak-to-trough percentage loss in the period | < 30% preferred for core holdings | −52% MDD: needs very high conviction and small position. |
| VaR (95%) | One-day loss that occurs on only 5% of days | Compare vs daily risk budget | VaR −2.5%: on a typical bad day, expect 2.5% loss. |
| CVaR / Expected Shortfall | The *average* loss on the worst 5% of days (beyond VaR) | Must survive under stress | CVaR −5%: in a tail event, average loss is 5%. |
| Ulcer Index | Combines drawdown depth *and* duration — penalises prolonged losses more | Lower is better; > 10 is uncomfortable | Two stocks with equal MDD but different Ulcer Index: the higher one stayed underwater longer. |
| **Drawdown Recovery Analysis** | How many trading days does it typically take to recover from a 10%+ drawdown? | < 60 days = resilient; > 180 days = sticky drawdowns | A stock with 45-day average recovery vs peers at 120 days recovers significantly faster. |

**Why Drawdown Recovery Analysis was added:** Max Drawdown tells you the worst drop but nothing about how quickly the stock recovered. A value investor who expects a catalyst within 12 months needs to know if prior drawdowns typically resolved within that window. A stock that took 3 years to recover from its last major drawdown is a much riskier bet on a 12-month thesis than one that recovered in 8 weeks, even if the drawdown magnitudes were identical.
*Reference: Magdon-Ismail, M. & Atiya, A. (2004). "Maximum Drawdown." Risk Magazine, 17(10), 99–102. Also covered in Bacon, C. (2008). Practical Portfolio Performance Measurement and Attribution. Wiley, Ch. 4.*

### C) Market Exposure KPIs
| KPI | Layman explanation | Decision use | Threshold |
|---|---|---|---|
| Beta | Sensitivity to market moves | Beta > 1.2 = amplifies portfolio swings | Match to portfolio risk budget |
| Correlation vs benchmark | How closely the stock tracks the index | High correlation = less diversification value | < 0.7 preferred for portfolio diversification benefit |
| **Regime-Conditional Beta (up/down)** | Beta is *not* constant — it is typically higher in crashes than in rallies (downside correlation is sticky) | Upside beta > downside beta = asymmetric (favourable); Downside beta > upside beta = unfavourable | Stock with up-beta 0.8 and down-beta 1.6 participates less in rallies but amplifies crashes. |

**Why Regime-Conditional Beta was added:** Standard beta is a single average computed over all market conditions. But correlations and betas notoriously rise during market stress — stocks that appear to have moderate betas (0.8) can behave like high-beta stocks (1.4) during a market panic, precisely when you least want amplified losses. Separating "up-market beta" and "down-market beta" reveals this asymmetry and is critical for any portfolio that needs downside protection.
*Reference: Ang, A., Chen, J. & Xing, Y. (2006). "Downside Risk." Review of Financial Studies, 19(4), 1191–1239. Patton, A. & Verardo, M. (2012). "Does Beta Move with News? Firm-Specific Information Flows and Learning about Profitability." Review of Financial Studies, 25(9), 2789–2839.*

---

## Fundamental–Risk Integration (new in v1.1)

The Phase 5 risk score should not be purely statistical (based on historical price returns). It should also incorporate the **structural risk signals from Phase 2** that lead price risk:

| Phase 2 signal | Risk implication | Adjustment |
|---|---|---|
| Accruals Ratio > 15% | Earnings likely to disappoint; idiosyncratic downside risk elevated | Reduce risk score by 0.5 points |
| Operating Leverage > 2.5× | High sensitivity to revenue shortfalls; amplifies business cycle risk | Increase estimated downside beta by 0.2 |
| Net Debt/EBITDA > 4× | Refinancing risk in a rising rate environment | Reduce max position size by 25% |
| Interest Coverage < 2× | Distress proximity; downside tail is larger than historical data suggests | Flag as satellite-only; hard-cap position at 2% |
| Share dilution trend positive | EPS per share being diluted; less price support from buybacks | Reduce conviction-based sizing upward adjustment by 1 step |

**Rationale:** Historical return-based risk metrics measure what *has* happened. Fundamental risk signals from the balance sheet and income statement are leading indicators of what *will* happen to the price distribution. A company with rising leverage and poor earnings quality has a fundamentally different risk profile than its trailing Sharpe ratio suggests — typically overstating the quality of the position.

---

## Position Sizing Framework (updated v1.1)

### Method 1: Conviction-based sizing
```
base_size = 1%
add = 1% per conviction point above 2   (max conviction = 5 → max add = 3%)
max_size = 4%
```
Reductions:
- Max Drawdown > 40% → reduce by 1%
- CVaR in worst quartile vs peers → reduce by 0.5%
- Accruals Ratio > 15% → reduce by 0.5%
- Net Debt/EBITDA > 4× → reduce by 1%

### Method 2: Fractional Kelly Criterion
```
Kelly fraction = (Win rate × Avg win / Avg loss − (1 − Win rate)) / (Avg win / Avg loss)
# Win rate = % of days with positive return (use trailing 252 days)
# R-ratio  = avg positive day / abs(avg negative day)
# Use half-Kelly: position_size = 0.5 × Kelly_fraction × max_portfolio_allocation
```
The Kelly Criterion gives the mathematically optimal bet size to maximise long-run geometric growth. Full-Kelly is theoretically optimal but practically dangerous because it maximises drawdown volatility. Half-Kelly (50% of the Kelly fraction) is the standard institutional compromise — it gives ~75% of the optimal growth rate at roughly half the volatility.
*Reference: Kelly, J.L. (1956). "A New Interpretation of Information Rate." Bell System Technical Journal, 35(4), 917–926. Thorpe, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market." Handbook of Asset and Liability Management. North-Holland.*

Use the **lower of** conviction-based and half-Kelly sizing as the final position recommendation.

---

## Portfolio Fit Rules (updated v1.1)
- **Core position candidate:** Sharpe > 1.0, Max Drawdown < 35%, downside beta ≤ upside beta, accruals ratio < 10%, Calmar > 0.8
- **Satellite position candidate:** Higher growth / higher MOS but capped at 2.5% of portfolio due to elevated drawdown, tail risk, or leverage
- **Reject / avoid entirely:** Altman Z < 1.81, interest coverage < 2×, Accruals Ratio > 20%, or CVaR worse than −8% on a daily basis

## Stress Scenario Template
The module computes three structured stress scenarios using beta and known macro sensitivities:

| Scenario | Market proxy move | Estimated stock impact |
|---|---|---|
| Market correction −20% | SPY −20% | `−20% × beta_down × (1 + leverage_adj)` |
| Rising rates +100bps | Long-duration growth stocks typically −8–12% | Apply sector-based rate sensitivity factor |
| Sector-specific shock −30% | Sector ETF −30% | `−30% × sector_correlation` |

Document whether each scenario produces an acceptable loss given the position size. If the worst scenario produces a portfolio-level loss exceeding the max drawdown budget, reduce position size until it is within budget.

---

## Programmatic Pull

### Currently implemented in notebook (Cell 21)
```python
# Sharpe, Sortino, Alpha, Beta, VaR(95%), CVaR, MaxDD, Ulcer — all computed manually
sharpe = (annual_ret - Rf) / annual_vol
sortino = (annual_ret - Rf) / downside_vol
beta = cov(asset_rets, bench_rets) / var(bench_rets)
max_drawdown = (equity_curve / equity_curve.cummax() - 1).min()
ulcer = np.sqrt((drawdowns ** 2).mean())
```

### Planned module additions (`phase5_risk`)
```python
# Calmar
calmar = annual_ret / abs(max_drawdown)

# Gain-to-Pain
gains  = returns[returns > 0].sum()
pains  = returns[returns < 0].abs().sum()
gain_to_pain = gains / pains

# Regime-conditional beta
up_mask   = bench_rets > 0
down_mask = bench_rets < 0
beta_up   = returns[up_mask].cov(bench_rets[up_mask]) / bench_rets[up_mask].var()
beta_down = returns[down_mask].cov(bench_rets[down_mask]) / bench_rets[down_mask].var()

# Drawdown recovery: time from trough to new high
drawdown_series  = equity_curve / equity_curve.cummax() - 1
recovery_periods = []  # compute per-drawdown-episode recovery in trading days

# Kelly
win_rate  = (returns > 0).mean()
avg_win   = returns[returns > 0].mean()
avg_loss  = returns[returns < 0].abs().mean()
kelly     = (win_rate * avg_win / avg_loss - (1 - win_rate)) / (avg_win / avg_loss)
half_kelly_size = 0.5 * kelly * MAX_PORTFOLIO_ALLOCATION
```

---

## Exit Criteria (updated v1.1)
- All 8 original risk KPIs computed and recorded in `risk_kpi_df`
- Calmar Ratio, Gain-to-Pain, regime betas, recovery analysis computed
- Position size documented using both conviction-based and half-Kelly methods; lower value selected
- Three stress scenarios estimated and recorded
- Fundamental risk adjustments from Phase 2 applied to position sizing
- Portfolio fit classification (Core / Satellite / Reject) documented

---

*Phase 5 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` §5*
