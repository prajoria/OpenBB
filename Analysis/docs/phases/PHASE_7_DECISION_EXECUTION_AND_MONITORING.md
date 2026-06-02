# Phase 7: Decision, Execution, and Monitoring

**Version:** 1.1 — Updated 2026-03-22 (added fundamental-technical balance rules, thesis invalidation framework, staged entry logic, time-stop discipline, and structured monitoring cadence)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| Composite scoring (6 dimensions) | Weighted 0-5 scale | Implemented (Cell 36) |
| Weights (BQ 8%, Fund 25%, Tech 15%, Val 20%, Risk 12%, Peer 20%) | As specified | Implemented, matches plan exactly |
| Action bands (Strong Buy/Buy/Hold/Avoid) | 4.2/3.6/2.8 thresholds | Implemented, matches plan exactly |
| Score explanation table | Plain-language legend | Implemented (Cell 36, `legend_df`) |
| Strengths/weaknesses summary | Top 2 each | Implemented (Cell 36, printed briefing) |
| Executive export (Excel + PDF) | Not in plan | **Implemented** (Cell 37, ~900 lines) |
| Segment alternatives scoring | Not in plan | **Implemented** (Cell 37) |
| Entry quality (R basis) | Execution KPI | **Not implemented** |
| Slippage tracking | Execution KPI | **Not implemented** |
| Stop distance (ATR-based) | Risk control | **Not implemented** |
| Time stop | Dead-money prevention | **Not implemented** |
| Monitoring KPI cadence table | Quarterly/weekly/monthly triggers | **Not implemented** |
| Thesis KPI set tracking | Ongoing monitoring | **Not implemented** |
| Handoff template (6 items) | Knowledge transfer | **Not implemented** |
| `decision_label()` function | Score-to-action mapper | Implemented (Cell 36) |
| **Fundamental–technical balance rules** | Entry size conditional on both dimensions | **Not implemented** |
| **Staged entry logic** | Scale in, not all-at-once | **Not implemented** |
| **Thesis invalidation framework** | What specific events kill the thesis? | **Not implemented** |
| **Time stop** | Exit if thesis not working within defined window | **Not implemented** |
| **Trailing stop migration** | Move stop to break-even after 1R gain | **Not implemented** |

---

## Objective
Convert all prior phase outputs into a single actionable, auditable decision — and then build the process to manage the position from entry through monitoring to exit. The decision is not a one-off event; it is the start of a structured management process.

A balanced fundamental-technical approach means:
- **Fundamentals determine what to buy and what size to target**
- **Technicals determine when to buy and where the stop goes**
- **Risk controls limit how wrong you can be**

---

## Decision Engine

### Composite Score and Weights

| Block | Weight | Score Source |
|---|---:|---|
| Business quality (Phase 1) | 8% | Quantitative proxies: market cap, data coverage, peer count |
| Fundamentals (Phase 2) | 25% | `p2.score` — weighted 6-category scorecard |
| Technical timing (Phase 3) | 15% | `p3.bullish_count / 11 × 5` (normalised to 0–5) |
| Valuation (Phase 4) | 20% | MOS zone + multiples vs history |
| Risk fit (Phase 5) | 12% | Sharpe, Calmar, MaxDD, downside beta vs portfolio thresholds |
| Peer relative (Phase 6) | 20% | `p6.score` — 5-block scorecard |

**Total = weighted sum on 0–5 scale.**

### Action Bands
| Composite Score | Label | Action |
|---:|---|---|
| ≥ 4.2 | **Strong Buy** | Full target size; staged entry over 2–3 sessions |
| ≥ 3.6 | **Buy** | Partial entry (50–75%); add on technical confirmation |
| ≥ 2.8 | **Hold / Watch** | No fresh capital; reassess at next earnings or when technicals improve |
| < 2.8 | **Avoid / Sell** | Reduce or avoid exposure |

### Hard Override Rules (v1.1)
These override the composite score regardless of the numeric result:

| Condition | Override |
|---|---|
| Altman Z-Score < 1.81 | Force **Avoid** — distress risk; multiples are unreliable |
| Accruals Ratio > 20% | Cap at **Hold/Watch** — earnings quality too low for conviction |
| Net Debt/EBITDA > 5× | Cap at **Hold/Watch** — refinancing risk dominates |
| Phase 3 `weekly_trend_bullish == False` | Cap technical score at 2.0; max composite effectively capped |
| Phase 3 `earnings_safe_window == False` | Add mandatory note: "Earnings within 5 days — defer entry" |
| Information Ratio vs ETF < 0 (full period) | Add mandatory note: "Consider sector ETF as superior alternative" |

---

## Fundamental–Technical Balance Rules (new in v1.1)

The standard composite score treats all blocks as independent. These balance rules add cross-block logic that a holistic analyst applies naturally:

### Rule 1: Valuation–Timing Alignment
```
if p4.margin_of_safety >= 0.20 and p3.bullish_count >= 6:
    entry_quality = "High Conviction"    # best setup: cheap AND timed
elif p4.margin_of_safety >= 0.20 and p3.bullish_count >= 3:
    entry_quality = "Value Entry"        # cheap, incomplete timing; initial 50%
elif p4.margin_of_safety >= 0.05 and p3.bullish_count >= 6:
    entry_quality = "Momentum Entry"     # fair value but strong technicals
else:
    entry_quality = "Wait"               # neither cheap enough nor technically ready
```

### Rule 2: Fundamental Quality Cap on Leverage
If the Phase 2 composite score is ≥ 3.5 but Balance Sheet Safety category scores ≤ 2.0, **cap the Phase 7 composite at 3.8** — preventing a fundamentally leveraged business from reaching "Strong Buy" based on other metrics alone.

### Rule 3: Peer Relative Override
If Phase 6 Information Ratio vs ETF < 0 and the Phase 6 relative score < 3.0, add a mandatory output: `"Consider ETF alternative: holding {sector_etf} would have produced better risk-adjusted returns over the lookback period."`

---

## Execution Plan (updated v1.1)

### Entry Mechanics
| Parameter | Calculation | Example |
|---|---|---|
| Stop price | `entry − 2 × ATR(14)` | Entry $100, ATR $3 → stop $94 |
| Risk per share (R) | `entry − stop` | R = $6 per share |
| Target 1 (1R) | `entry + 1 × R` | $106 — move stop to break-even here |
| Target 2 (2R) | `entry + 2 × R` | $112 — take 50% off position here |
| Target 3 (3R) | `entry + 3 × R` | $118 — trail remainder with 1.5× ATR stop |
| Entry condition | R/R ratio ≥ 2.0 | Only enter if distance to Target 2 ≥ 2× risk |

### Staged Entry Logic (new in v1.1)
Never enter a full position in a single order. Scale in over sessions to reduce timing risk:

| Entry quality | Tranche 1 | Tranche 2 condition | Tranche 3 condition |
|---|---|---|---|
| High Conviction | 50% of target | +25% if price holds above VWAP after 3 days | +25% after 1R gained |
| Value Entry | 33% of target | +33% when Phase 3 bullish count improves to ≥ 6 | +33% after 1R |
| Momentum Entry | 40% of target | +30% after price holds above entry for 5 days | +30% after 1R |
| Wait | 0% — do not enter | Re-evaluate when valuation or technicals improve | — |

**Rationale:** Staged entries reduce the impact of being wrong about exact timing. A position built in three tranches reduces average entry cost if the stock dips after the first tranche, and prevents committing full capital before the setup has confirmed.
*Reference: O'Neil, W.J. (2009). How to Make Money in Stocks. McGraw-Hill, 4th ed. — the "add on the way up, not the way down" principle. Also: Schwager, J.D. (1989). Market Wizards. Wiley — consistent pattern across top traders: small initial entry, add after confirmation.*

### Time Stop (new in v1.1)
```
time_stop_days = 63  # 3 calendar months (one earnings cycle)
```
If the stock has not moved in the direction of the thesis within `time_stop_days` of entry, exit the position regardless of whether the stop has been hit. This prevents capital being trapped in "dead money" positions while opportunity cost accumulates elsewhere.
*Reference: Elder, A. (2002). Come Into My Trading Room. Wiley, Ch. 9: "If a trade is not working within a reasonable time frame, it is probably wrong — exit and redeploy."*

---

## Thesis Invalidation Framework (new in v1.1)

At entry, define **explicitly** the events that would invalidate the investment thesis. These are not the same as the technical stop — the technical stop limits loss; thesis invalidation triggers a *complete reassessment* even if the stock has not hit the stop yet.

| Thesis pillar | Invalidation event |
|---|---|
| Revenue growth (Phase 2) | Two consecutive quarters of revenue below analyst consensus by > 5% |
| Margin expansion (Phase 2) | Gross margin declines by > 2 percentage points in any quarter |
| Capital allocation quality (Phase 2) | Net dilution in any 12-month period exceeding 3% |
| Valuation thesis (Phase 4) | DCF fair value drops below current price (MOS closes to negative) |
| Technical regime (Phase 3) | Weekly SMA50 crosses below weekly SMA200 (Death Cross on weekly chart) |
| Peer relative (Phase 6) | Stock falls below peer median Sharpe for 2 consecutive rolling 60-day windows |
| Management integrity | SEC filing or earnings restatement; key executive departure without succession |

```python
monitoring_triggers = {
    "revenue_miss_threshold":      -0.05,    # two consecutive quarters > 5% miss
    "gross_margin_decline":        -0.02,    # per-quarter threshold
    "dilution_12m":                 0.03,    # net share increase > 3% in 12 months
    "mos_negative":                 0.00,    # DCF fair value drops below price
    "weekly_death_cross":          True,     # SMA50_weekly < SMA200_weekly
    "peer_sharpe_rank_threshold":  0.50,     # below 50th percentile for 2 windows
}
```

---

## Monitoring Cadence (updated v1.1)

| KPI | Cadence | Trigger Action |
|---|---|---|
| Thesis KPI set (revenue growth, margins, FCF margin, accruals) | **Quarterly** (after each earnings) | If any 2 degrade consecutively: full reassessment, reduce to 50% size |
| Technical regime (SMA50/200 weekly, ADX) | **Weekly** | Weekly death cross: exit half the position; re-evaluate full exit |
| Relative rank vs peers (Sharpe, Information Ratio) | **Monthly** | Falls below peer median for 2 consecutive months: reduce to satellite size |
| Valuation gap vs DCF fair value | **Monthly** | MOS closes to < 5% or turns negative: trim to 50%; do not add |
| Risk budget usage | **Daily/weekly** | Any tranche > 5% of portfolio: rebalance down regardless of conviction |
| Earnings date proximity | **Weekly** | Within 5 days: review position sizing; apply earnings risk guard logic |
| Stop distance vs ATR | **Weekly** | After 1R gain: move stop to break-even; trail with 1.5× ATR |

---

## Handoff Template (for new joiners or position transfers)
1. **Investment thesis** (3 lines max): what is the key driver of value creation?
2. **Top 3 bullish drivers**: specific and measurable (e.g., "FCF margin expanding from 12% to 16% by FY2026")
3. **Top 3 invalidation events**: what would make this thesis wrong immediately?
4. **Fair value range and MOS**: DCF range + MOS at current price; when does it no longer look cheap?
5. **Peer-relative verdict**: where does the target rank vs peers on Sharpe and ROIC? Is holding the sector ETF a superior alternative?
6. **Trade plan**: entry tranches, current stop, take-profit levels, time stop date, next monitoring checkpoint

---

## Programmatic Skeleton (updated)
```python
def phase7_decision(cfg, p1, p2, p3, p4, p5, p6):
    scores = {
        "business_quality": _score_phase1(p1),
        "fundamentals":     p2.score,
        "technicals":       p3.bullish_count / 11 * 5,
        "valuation":        _score_phase4(p4),
        "risk_fit":         _score_phase5(p5),
        "peer_relative":    p6.score,
    }
    weights = {"business_quality":0.08,"fundamentals":0.25,"technicals":0.15,
               "valuation":0.20,"risk_fit":0.12,"peer_relative":0.20}
    composite = sum(scores[k] * weights[k] for k in weights)

    # Apply hard overrides
    override = None
    if p4.altman < 1.81:
        composite = min(composite, 2.0); override = "Altman distress"
    if p2.accruals_ratio > 0.20:
        composite = min(composite, 2.8); override = "High accruals"
    if not p3.signals.get("weekly_trend_bullish"):
        scores["technicals"] = min(scores["technicals"], 2.0)

    label = _decision_label(composite)

    # Execution plan
    atr        = p3.price_df["atr"].iloc[-1]
    price      = p3.price_df["close"].iloc[-1]
    stop       = price - 2 * atr
    r          = price - stop
    target_2r  = price + 2 * r
    entry_qual = _entry_quality(p4.margin_of_safety, p3.bullish_count)

    return Phase7Result(
        composite_score=composite, action_label=label,
        score_breakdown=scores, atr_stop=stop,
        target_2r=target_2r, entry_quality=entry_qual,
        monitoring_triggers=monitoring_triggers,
        hard_override=override,
        handoff=_build_handoff(p1,p2,p3,p4,p5,p6,composite),
    )
```

---

## Exit Criteria
- Decision and score saved; hard overrides documented
- Entry/exit plan with all 3 tranches, stops, and targets explicitly recorded
- Time stop date set (entry date + 63 trading days)
- Thesis invalidation events enumerated per pillar
- Monitoring calendar assigned with cadence and trigger thresholds
- Handoff template completed

---

*Phase 7 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` §9–10*
