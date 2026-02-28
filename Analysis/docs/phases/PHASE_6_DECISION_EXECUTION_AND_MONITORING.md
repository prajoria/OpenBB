# Phase 6: Decision, Execution, and Monitoring

## Objective
Convert analysis into an actionable, auditable trade decision and maintenance process.

## Decision Engine (scored)

### Composite Score
| Block | Weight |
|---|---:|
| Business quality (Phase 1) | 10% |
| Fundamentals (Phase 2) | 30% |
| Technical timing (Phase 3) | 20% |
| Valuation (Phase 4) | 25% |
| Risk fit (Phase 5) | 15% |

Total score = weighted average (0–5 scale).

### Action Bands
| Score | Decision | Typical action |
|---:|---|---|
| 4.2–5.0 | Strong Buy | Full target size, staged entries |
| 3.6–4.1 | Buy | Partial size, add on confirmation |
| 2.8–3.5 | Hold / Watch | No fresh risk unless setup improves |
| < 2.8 | Avoid / Sell | Reduce or avoid exposure |

## Execution KPIs
| KPI | Why it matters | Rule |
|---|---|---|
| Entry quality (`R` basis) | Standardizes reward-to-risk | Enter only if expected payoff ≥ 2R |
| Slippage | Real execution cost | Keep below defined bps budget |
| Stop distance (ATR-based) | Volatility-aware risk control | Initial stop = 1.5–2.5 × ATR |
| Time stop | Prevent dead-money traps | Reassess if thesis not working in defined window |

## Monitoring KPIs (post-entry)
| KPI | Cadence | Trigger |
|---|---|---|
| Thesis KPI set (top 5) | Quarterly | Any 2 degrade for 2 consecutive periods |
| Technical regime (50/200 DMA, ADX) | Weekly | Regime flip from bullish to bearish |
| Valuation gap vs fair value | Monthly | Close MOS gap or move to overvaluation |
| Risk budget usage | Daily/weekly | Breach of position or portfolio limits |

## Programmatic Skeleton

```python
def decision_label(score: float) -> str:
    if score >= 4.2:
        return "Strong Buy"
    if score >= 3.6:
        return "Buy"
    if score >= 2.8:
        return "Hold/Watch"
    return "Avoid/Sell"

# Example: combine block scores
block_scores = {
    "business_quality": 4.0,
    "fundamentals": 3.8,
    "technicals": 3.6,
    "valuation": 4.2,
    "risk_fit": 3.5,
}
weights = {
    "business_quality": 0.10,
    "fundamentals": 0.30,
    "technicals": 0.20,
    "valuation": 0.25,
    "risk_fit": 0.15,
}

total = sum(block_scores[k] * weights[k] for k in block_scores)
label = decision_label(total)
print(total, label)
```

## Handoff Template (for new joiners)
1. Thesis in 3 lines
2. Top 3 bullish drivers
3. Top 3 invalidation risks
4. Fair value range and margin of safety
5. Entry plan, stop, and size
6. Review date and KPI trigger list

## Exit Criteria
- Decision and score saved in repository
- Entry/exit plan explicitly documented
- Monitoring calendar and KPI triggers assigned
