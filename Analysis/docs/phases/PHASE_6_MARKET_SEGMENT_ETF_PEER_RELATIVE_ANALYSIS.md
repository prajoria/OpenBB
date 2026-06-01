# Phase 6: Market Segment, ETF Benchmark, and Peer Relative Analysis

**Version:** 1.1 — Updated 2026-03-22 (added rolling relative strength, information ratio vs ETF, peer fundamental quality comparison, and balanced relative-valuation layer)

## Implementation Status (vs Notebook `00. single_stock_analysis_playbook_template.ipynb`)

| Item | Plan | Notebook Status |
|------|------|-----------------|
| Sector identification | From profile | Implemented (Cell 23, via Phase 1 profile) |
| Sector ETF map (11 sectors) | Static lookup | Implemented (Cell 23, 12 sector variants mapped) |
| Peer discovery | 5-12 peers, industry-matched | Implemented (Cell 23, up to 10 from `obb.equity.compare.peers`, no cap/industry filter) |
| Universe building | Symbol + peers + ETFs + SPY | Implemented (Cell 23) |
| Historical prices (universe) | `obb.equity.price.historical` (multi-symbol) | Implemented (Cell 25) |
| Annualised Return per asset | Relative metric | Implemented (Cell 27) |
| Annualised Volatility per asset | Relative metric | Implemented (Cell 27) |
| Sharpe per asset | Relative metric | Implemented (Cell 27) |
| VaR 95% per asset | Tail risk | Implemented (Cell 27) |
| CVaR 95% per asset | Tail risk | Implemented (Cell 27) |
| Max Drawdown per asset | Downside metric | Implemented (Cell 27) |
| Sortino per asset | Downside-adj return | **Not implemented** in relative table |
| Correlation vs ETF | Diversification signal | **Not implemented** as standalone metric |
| Beta vs ETF/SPY | Sensitivity per asset | **Not implemented** in relative table |
| Correlation heatmap | Visual | Implemented (Cell 32, custom emotion colormap) |
| Risk-return scatter | Visual | Implemented (Cell 32, bubbles = Sharpe) |
| Symbol legend (ticker-to-name) | Chart readability | Implemented (Cell 30, fetches profile for each) |
| Rolling 60-day relative strength | Visual | **Not implemented** |
| Drawdown chart (vs top 3 peers) | Visual | **Not implemented** |
| 4-block relative scorecard (25% each) | Gate scoring | **Not implemented** |
| Phase gate (>= 3.5) | Exit criteria | **Not implemented** |
| **Information Ratio vs sector ETF** | Alpha per unit of tracking error vs benchmark | **Not implemented** |
| **Peer fundamental quality comparison** | Compare P2 KPIs across peers — not just prices | **Not implemented** |
| **Relative valuation layer** | Is the target cheap/expensive vs peers on multiples? | **Not implemented** |
| **Rolling 12-month relative strength** | Extended window vs ETF | **Not implemented** |
| Provider | `yfinance` in plan code sample | Uses `fmp_cached`/`fmp` via `call_obb()` |

**Current notebook scoring:** `relative_peer_score` uses 70% Sharpe rank + 30% return rank.
**Plan scoring:** 4-block model (return, risk-adjusted, downside, consistency) at 25% each.
**v1.1 additions:** Information Ratio vs ETF, peer fundamental quality overlay, relative valuation (P/E and EV/EBITDA vs peer median), extended rolling relative strength.

---

## Objective
Prevent single-stock tunnel vision by asking: "Is this the *best* way to own exposure to this sector/theme, or are peers offering similar or better risk-adjusted returns at lower valuations?" A balanced analyst does not just check if a stock has positive momentum — they verify the stock is worth owning *relative to its alternatives*.

---

## 6.1 Identify Market Segment

### Required fields
| Field | Why it matters |
|---|---|
| Sector | Top-down regime exposure |
| Industry / Sub-industry | Better peer matching than sector alone |
| Market cap bucket | Never compare large-caps vs micro-caps on risk-return; the distributions are incomparable |
| Region/listing | Consistent accounting standards and macro regime |

### Programmatic pull
```python
# Reuse Phase 1 profile data — no new API call needed
sector      = p1.profile_df["sector"].iloc[0]
industry    = p1.profile_df["industry"].iloc[0]
market_cap  = p1.quote_df["market_cap"].iloc[0]
```

---

## 6.2 Sector ETF Map and Peer Basket

### Sector ETF map (canonical — from existing notebook Cell 23)
| Sector (FMP name) | Primary ETF | Secondary ETF |
|---|---|---|
| Technology | XLK | VGT |
| Financial Services | XLF | VFH |
| Financial | XLF | VFH |
| Healthcare | XLV | VHT |
| Health Care | XLV | VHT |
| Industrials | XLI | VIS |
| Consumer Cyclical | XLY | VCR |
| Consumer Defensive | XLP | VDC |
| Energy | XLE | VDE |
| Basic Materials | XLB | VAW |
| Utilities | XLU | VPU |
| Real Estate | XLRE | VNQ |
| Communication Services | XLC | VOX |
| *(fallback)* | SPY | — |

### Peer selection rules
- Minimum 5 peers, ideal 8–12
- Same industry/sub-industry first; sector fallback only if < 5 peers found
- Market cap within 0.5×–2× of target cap (avoids comparing MSFT vs a small-cap software firm)
- Sufficient liquidity: exclude thinly traded names with < $5M average daily volume

---

## 6.3 Price-Based Relative Metrics

### KPI table
| KPI | Layman explanation | Good signal for target |
|---|---|---|
| Annualised Return | Average yearly gain | Higher than peers and sector ETF |
| Annualised Volatility | Typical fluctuation size | Lower for same return = superior efficiency |
| Sharpe Ratio | Return per unit of total risk | Top 25th percentile in peer set |
| Sortino Ratio | Return per downside risk | Higher than Sharpe ratio (asymmetric upside) |
| Max Drawdown | Worst historical loss | Smaller than peers preferred |
| VaR 95% | Typical bad-day loss | Less negative is safer |
| CVaR 95% | Average loss on worst days | Lower tail loss better |
| Beta vs ETF/SPY | Market sensitivity | Consistent with portfolio risk appetite |
| Correlation vs ETF | Diversification value | Moderate correlation (0.4–0.7) ideal |
| **Information Ratio vs ETF** | Alpha per unit of tracking error — how much is the stock outperforming its benchmark per unit of deviation from it? | > 0.5 is good; > 1.0 is strong | See rationale below |

**Why Information Ratio was added:** The Sharpe Ratio tells you how the stock performed relative to the risk-free rate. The Information Ratio tells you how it performed relative to its *own benchmark* (the sector ETF) per unit of active risk (tracking error). This is the metric that professional active managers are evaluated on — because it answers: "Am I adding value by holding this stock instead of just buying the ETF?" An Information Ratio of 0.5 means for every 1% of tracking error the stock takes vs the ETF, it returned 0.5% of outperformance. Below 0 means the stock underperformed the ETF for the active risk taken.
```
Information Ratio = (Ann. Return_stock − Ann. Return_ETF) / Tracking_Error
Tracking_Error = annualised std of (daily_returns_stock − daily_returns_ETF)
```
*Reference: Grinold, R. & Kahn, R. (1999). Active Portfolio Management (2nd ed.). McGraw-Hill, Ch. 6 — the foundational text on Information Ratio as the key active management performance metric.*

---

## 6.4 Peer Fundamental Quality Overlay (new in v1.1)

A balanced analyst does not compare stocks on price returns alone. Two stocks with identical Sharpe ratios can have very different fundamental quality profiles — one is compounding value at high ROIC, the other is a cyclical that happened to catch a tide. The peer comparison should include a fundamentals layer.

**KPIs fetched per peer (reuse fmp_cached `key_metrics.py` model):**

| KPI | Why compare across peers |
|---|---|
| P/E vs peer median | Is target cheaper or more expensive than peers on earnings? |
| EV/EBITDA vs peer median | Enterprise-level valuation relative to operating performance |
| ROIC vs peer median | Is the target creating more value per invested dollar than peers? |
| FCF Margin vs peer median | Is the target generating more cash per revenue dollar? |
| Revenue Growth (1Y) vs peer median | Is the target growing faster than its peer group? |

```python
# Fetch key_metrics for each peer symbol — uses confirmed fmp_cached model
peer_metrics_list = []
for peer in peers:
    m = obb.equity.fundamental.metrics(symbol=peer, period="annual", limit=1,
                                        provider=cfg.provider).to_df()
    peer_metrics_list.append(m)
peer_fundamental_df = pd.concat(peer_metrics_list)
peer_fundamental_df.index = peers
```

**Relative fundamental score:** Compute the target's percentile rank on each of the 5 KPIs above vs the peer group. A target in the top-quartile on ROIC and FCF Margin but cheap on EV/EBITDA = the most attractive combination.

---

## 6.5 Relative Valuation Layer (new in v1.1)

Is the target stock cheap or expensive relative to its peers on standard multiples? This is independent of the absolute DCF from Phase 4 — relative valuation answers: "Even if the fair value is debatable, is the market assigning a lower multiple to this stock than to peers of similar quality?"

| Check | Signal |
|---|---|
| Target P/E < peer median P/E AND target ROIC ≥ peer median ROIC | Cheap quality — strongest relative signal |
| Target EV/EBITDA < peer median AND target FCF Margin ≥ peer median | Operationally undervalued relative to peers |
| Target P/S < peer median AND target Revenue Growth ≥ peer median | Growing faster but valued cheaper — momentum + value alignment |

```python
pe_rank       = percentileofscore(peer_fundamental_df["pe_ratio"], target_pe)
ev_rank       = percentileofscore(peer_fundamental_df["ev_to_ebitda"], target_ev)
roic_rank     = percentileofscore(peer_fundamental_df["roic"], target_roic)
# pe_rank low + roic_rank high = cheap quality (target percentile)
relative_valuation_score = (100 - pe_rank) * 0.5 + roic_rank * 0.5  # 0-100 scale
```

---

## 6.6 Visual Diagnostics
- **Correlation heatmap** of all basket daily returns
- **Risk-return scatter** with Sharpe as bubble size — target should be in upper-left quadrant (high return, low volatility)
- **Rolling 60-day and 12-month relative strength** of target vs sector ETF
- **Drawdown comparison chart** for target vs top 3 peers by Sharpe
- **Peer fundamental comparison bar chart** (ROIC, FCF Margin, P/E vs peer median)

---

## 6.7 Relative Scorecard (5-block — updated v1.1)

| Block | Weight | KPIs used |
|---|---:|---|
| Return rank vs peers | 20% | Ann. Return percentile rank |
| Risk-adjusted rank | 20% | Sharpe + Sortino percentile rank |
| Downside risk rank | 20% | MDD + CVaR percentile rank (lower = better) |
| Consistency (rolling outperformance) | 20% | % of rolling 30-day windows target beats ETF |
| **Relative fundamental quality** | 20% | ROIC rank, FCF Margin rank, relative P/E/EBITDA |

Rules:
- Score each block 1–5.
- Weighted score ≥ 3.5 required to proceed.
- If score < 3.0 AND Information Ratio vs ETF < 0, hard-cap Phase 7 composite at "Hold/Watch" — the stock is not adding enough active value over the passive ETF to justify single-stock risk.

---

## Exit Criteria (updated v1.1)
- Sector ETF and peer basket documented and justified
- Full relative KPI table (price-based + fundamental overlay) completed
- Information Ratio vs ETF computed and classified
- Relative valuation layer computed (peer P/E and ROIC comparison)
- Relative score ≥ 3.5 (or documented exception with rationale)
- If Information Ratio vs ETF < 0 for the full lookback period: flag — investor would have done better just buying the ETF

---

*Phase 6 spec version 1.1 | Updated 2026-03-22 | Cross-reference: `PHASED_ANALYSIS_MASTER_PLAN.md` §6*
