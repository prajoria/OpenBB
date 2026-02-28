# Phase 7: Decision, Execution, and Monitoring

## Objective
Convert all prior phases into an actionable, auditable trade decision and maintenance process.

## Decision Engine (scored)

### Composite Score
| Block | Weight |
|---|---:|
| Business quality (Phase 1) | 8% |
| Fundamentals (Phase 2) | 25% |
| Technical timing (Phase 3) | 15% |
| Valuation (Phase 4) | 20% |
| Risk fit (Phase 5) | 12% |
| Relative market & peer score (Phase 6) | 20% |

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
| Entry quality (`R` basis) | Standardizes reward-to-risk | Enter only if expected payoff >= 2R |
| Slippage | Real execution cost | Keep below defined bps budget |
| Stop distance (ATR-based) | Volatility-aware risk control | Initial stop = 1.5–2.5 x ATR |
| Time stop | Prevent dead-money traps | Reassess if thesis not working in defined window |

## Monitoring KPIs (post-entry)
| KPI | Cadence | Trigger |
|---|---|---|
| Thesis KPI set (top 5) | Quarterly | Any 2 degrade for 2 consecutive periods |
| Technical regime (50/200 DMA, ADX) | Weekly | Regime flip from bullish to bearish |
| Relative rank vs peers | Monthly | Falls below peer median for 2 consecutive windows |
| Valuation gap vs fair value | Monthly | MOS closes or flips to overvaluation |
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

block_scores = {
    "business_quality": 4.0,
    "fundamentals": 3.8,
    "technicals": 3.6,
    "valuation": 4.2,
    "risk_fit": 3.5,
    "relative_peer_score": 3.9,
}
weights = {
    "business_quality": 0.08,
    "fundamentals": 0.25,
    "technicals": 0.15,
    "valuation": 0.20,
    "risk_fit": 0.12,
    "relative_peer_score": 0.20,
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
5. Peer-relative verdict (where target ranks and why)
6. Entry plan, stop, size, and review triggers

## Exit Criteria
- Decision and score saved in repository
- Entry/exit plan explicitly documented
- Monitoring calendar and KPI triggers assigned
