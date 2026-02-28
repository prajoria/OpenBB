# Phase 6: Market Segment, ETF Benchmark, and Peer Relative Analysis

## Objective
Prevent single-stock tunnel vision by evaluating the target symbol against its market segment ETF and top comparable stocks before final decisioning.

This phase is adapted from the workflow patterns in `Analysis/riskReturnAnalysis.ipynb` (correlation heatmap, return-volatility-Sharpe ranking, and VaR/CVaR views).

## Scope (Your Requested Flow)
1. Determine the stock's market segment.
2. Identify best ETFs for that segment and comparable stocks.
3. Perform detailed relative comparison to test whether the target truly outperforms peers on both return and risk.

## 6.1 Identify Market Segment

### Required fields
| Field | Why it matters |
|---|---|
| Sector | Top-down regime exposure (e.g., Tech, Health Care) |
| Industry / Sub-industry | Better peer matching than sector alone |
| Market cap bucket | Avoid comparing large caps with small caps |
| Region/listing | Keeps macro and accounting context consistent |

### Programmatic pull
```python
profile = obb.equity.profile(symbol=SYMBOL, provider="fmp")
quote = obb.equity.price.quote(symbol=SYMBOL, provider="fmp")

sector = profile.results[0].sector
industry = profile.results[0].industry
market_cap = quote.results[0].market_cap
```

## 6.2 Choose Segment ETF Benchmarks and Peer Basket

### Sector ETF baseline (US default map)
| Sector | Primary ETF | Secondary ETF |
|---|---|---|
| Technology | XLK | VGT |
| Financials | XLF | VFH |
| Health Care | XLV | VHT |
| Industrials | XLI | VIS |
| Consumer Discretionary | XLY | VCR |
| Consumer Staples | XLP | VDC |
| Energy | XLE | VDE |
| Materials | XLB | VAW |
| Utilities | XLU | VPU |
| Real Estate | XLRE | VNQ |
| Communication Services | XLC | VOX |

### Comparable stock selection rules
- Minimum 5 peers, ideal 8–12.
- Same industry/sub-industry first, then sector fallback.
- Similar market-cap bucket (within ~0.5x to 2x target cap).
- Sufficient trading liquidity.

### Peer candidate pull (example pattern)
```python
# Discovery path can vary by provider; keep this as pseudo-template
peer_candidates = obb.equity.discovery.active(provider="fmp")

# Practical fallback: manually curated peer list stored in config
peer_symbols = ["PEER1", "PEER2", "PEER3", "PEER4", "PEER5"]
benchmark_symbols = ["SPY", "XLK"]  # choose sector ETF dynamically
universe = [SYMBOL] + peer_symbols + benchmark_symbols
```

## 6.3 Relative Performance & Risk Comparison (Detailed)

### KPI table (adapted from riskReturnAnalysis approach)
| KPI | Layman explanation | Good signal |
|---|---|---|
| Annualized Return | Average yearly gain | Higher than peers and ETF |
| Annualized Volatility | Typical fluctuation size | Lower for same return is better |
| Sharpe Ratio | Return earned per unit of risk | Top quartile in peer set |
| Sortino Ratio | Return per downside risk | Stronger than Sharpe in asymmetric names |
| Max Drawdown | Worst historical loss | Smaller than peers preferred |
| VaR 95% | Typical bad-day loss threshold | Less negative is safer |
| CVaR 95% | Average loss in worst days | Lower tail loss is better |
| Correlation vs ETF | How tightly stock tracks segment ETF | Moderate correlation improves diversification |
| Beta vs ETF/SPY | Sensitivity to market moves | Match to portfolio risk appetite |

### Programmatic metrics block
```python
import numpy as np
import pandas as pd

prices = obb.equity.price.historical(
    symbol=",".join(universe),
    start_date=START_DATE_TECHNICALS,
    provider="yfinance",
).to_df()

close = prices.pivot(index="date", columns="symbol", values="close").dropna(how="all")
returns = close.pct_change().dropna()

risk_free_rate = 0.02
annual_ret = returns.mean() * 252
annual_vol = returns.std() * np.sqrt(252)
sharpe = (annual_ret - risk_free_rate) / annual_vol
var_95 = returns.quantile(0.05)
cvar_95 = returns[returns.le(var_95)].mean()
correlation = returns.corr()

relative_table = pd.DataFrame({
    "Annual Return": annual_ret,
    "Volatility": annual_vol,
    "Sharpe": sharpe,
    "VaR 95%": var_95,
    "CVaR 95%": cvar_95,
}).sort_values("Sharpe", ascending=False)
```

### Visual diagnostics to include
- Correlation heatmap of all basket returns.
- Return vs volatility scatter with Sharpe as color/size.
- Rolling 60-day relative strength of target vs segment ETF.
- Drawdown chart for target vs top 3 peers.

## 6.4 Relative Scorecard (Gate Before Final Decision)
| Block | Weight |
|---|---:|
| Return rank vs peers | 25% |
| Risk-adjusted rank (Sharpe/Sortino) | 25% |
| Downside risk rank (MDD/VaR/CVaR) | 25% |
| Consistency (rolling outperformance) | 25% |

Rules:
- Score each block 1–5.
- Weighted score >= 3.5 required to proceed.
- If score < 3.0, force “hold/watch” or reject unless strong valuation dislocation exists.

## 6.5 Example Interpretation (Simple)
- If target has **higher return but much worse drawdown/tail risk** than peers, it may be a weak core holding.
- If target has **similar return but better Sharpe + lower CVaR** than peers, it is a stronger quality candidate.
- If target underperforms both peers and sector ETF for multiple windows, thesis likely needs reset.

## Exit Criteria
- Sector ETF and peer basket are documented and justified.
- Relative KPI table + required visuals are completed.
- Relative score >= 3.5 (or exception rationale documented).
