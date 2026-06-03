# Next Steps — Proposal & Specification

> **Date:** 2026-05-31
> **Branch:** `openbb_learning`
> **Last commit:** 2026-03-20 (2+ months idle)

---

## Current State Assessment

The platform has five functional layers, all operational but with known gaps:

| Layer | Maturity | Key Gaps |
|---|---|---|
| FMP Cached Provider | ✅ Production | Stable; no major gaps |
| Personal Finance Tools | ✅ Complete | One-time ingestion scripts; working |
| Portfolio App | ✅ Functional | Cache-only pricing; no live refresh path |
| 7-Phase Analysis Module | ⚠️ 40–75% per phase | See detailed gap table below |
| MCP / API Integration | ⚠️ Scaffold | Endpoints exist but call into incomplete phases |

### Analysis Module Gap Summary (from phase docs)

| Phase | Completion | Critical Missing Pieces |
|---|---|---|
| P1 Company Profile | ~40% | Revenue geo/segment, insider/institutional ownership, analyst revisions, qualitative gate |
| P2 Fundamentals | ~55% | 5Y CAGR (only YoY now), quarterly data, interest coverage, net debt/EBITDA, cash quality KPIs, Sloan accruals ratio, phase gate |
| P3 Technicals | ~35% | SMA 50/200 in scoring, Stochastic, MACD scoring, BB scoring, VWAP, Ichimoku, ROC, CMF, earnings guard, gap analysis, Fibonacci, multi-timeframe |
| P4 Valuation | ~50% | **DCF entirely absent**, margin of safety, sensitivity table (3×3), historical multiple trends, Piotroski F-Score, Altman Z-Score, reverse DCF |
| P5 Risk | ~75% | Position sizing, stress scenarios, correlation vs holdings, Calmar/Gain-to-Pain, regime beta, Kelly sizing |
| P6 Peer Relative | ~60% | Sortino/Beta per peer, rolling relative strength, 4-block scoring grid |
| P7 Decision | ~55% | Execution KPIs (fill price tracking), monitoring cadence rules, handoff template |

### Cross-Cutting Gaps
- No per-phase gates — all phases run unconditionally
- FinanceToolkit imported but never called
- No quarterly fundamental comparison
- No notebook that exercises the Python module end-to-end (notebook is separate from `stock_analysis.py`)

---

## Proposed Next Steps

### Stream A — Complete the Analysis Module (Highest Priority)

The 7-phase analysis module (`Analysis/stock_analysis.py`) is the intellectual core of the project. Completing it to 100% against the phase specs is the single most impactful workstream.

#### A1. Phase 4 — DCF & Valuation (Priority: 🔴 Critical)
**Why first:** DCF is the largest gap and blocks meaningful Phase 7 composite scores.

- Implement 2-stage DCF model (high-growth + terminal) using fmp_cached fundamentals
- Build 3×3 sensitivity table (WACC × terminal growth rate)
- Compute margin of safety: `(dcf_fair_value - current_price) / dcf_fair_value`
- Add Piotroski F-Score (9-point checklist from income/balance/cash statements)
- Add Altman Z-Score (5-ratio bankruptcy predictor)
- Add historical multiple trend (5Y P/E, EV/EBITDA charts)
- Implement phase gate: ≥2 valuation methods agree on direction + MOS computed
- **Tests:** ~15 unit + ~10 integration

#### A2. Phase 3 — Extended Technicals (Priority: 🟠 High)
- Wire SMA 50/200, Stochastic, MACD, BB into the bullish/bearish scoring dict
- Add v1.1 indicators: VWAP, Ichimoku cloud, ROC (20/60/120), CMF(21), earnings proximity guard, price gap analysis, Fibonacci retracement levels
- Add weekly-timeframe confluence check
- Implement phase gate: ≥4 of 6 bullish conditions
- **Tests:** ~10 unit + ~8 integration

#### A3. Phase 1 — Full Profile (Priority: 🟡 Medium)
- Add revenue geography/segment breakdown DataFrames
- Add insider trading + institutional ownership summaries
- Add analyst price target consensus
- Implement qualitative gate (business understandable + no existential risk flag)
- **Tests:** ~8 unit + ~6 integration

#### A4. Phase 2 — Extended Fundamentals (Priority: 🟡 Medium)
- Convert YoY growth to proper 5Y CAGR calculations
- Add interest coverage, net debt/EBITDA, accruals ratio (Sloan)
- Add quarterly comparison option
- Implement weighted score gate (≥3.5/5.0)
- **Tests:** ~8 unit + ~8 integration

#### A5. Phase 5 — Position Sizing & Stress (Priority: 🟢 Low)
- Add conviction-based position sizing (1%–5% of portfolio)
- Add stress scenario narrative (-20% market / +100bps rate)
- Add correlation check against existing holdings
- Add Calmar ratio, Gain-to-Pain ratio
- **Tests:** ~6 unit + ~4 integration

#### A6. Phase 6 — Enhanced Peer Analysis (Priority: 🟢 Low)
- Add Sortino and Beta per peer
- Add rolling 3M relative strength
- Add 4-block scoring grid (quality × value)
- Implement relative score gate (≥3.5/5.0)
- **Tests:** ~6 unit + ~4 integration

#### A7. Phase 7 — Decision Polish (Priority: 🟢 Low)
- Add execution KPIs (entry price vs VWAP, fill quality)
- Add monitoring cadence template (daily/weekly/monthly check items)
- Add PDF/markdown report export
- **Tests:** ~4 unit + ~4 integration

---

### Stream B — End-to-End Notebook & Reporting

#### B1. Create Consolidated Analysis Notebook
- Build `Analysis/01. phased_stock_analysis.ipynb` that calls `stock_analysis.py` functions
- Show gate pass/fail at each phase boundary
- Include visualization cells (charts, tables, heatmaps) for each phase
- Make it runnable for any symbol by changing one cell

#### B2. PDF/HTML Report Generation
- Generate a one-click investment memo from `run_full_analysis()` output
- Include all charts, tables, scores, and the final decision
- Template-based (Jinja2 or similar)

---

### Stream C — Portfolio App Enhancements

#### C1. Live Data Refresh
- Add a `/refresh` endpoint that triggers fmp_cached to fetch latest prices
- Schedule daily cache warm-up (pre-market)

#### C2. Multi-Stock Screening
- Endpoint to run Phase 1+2 on a watchlist (e.g., S&P 500 constituents)
- Return ranked table by composite quality score
- Useful for finding new analysis candidates

#### C3. Portfolio-Level Analysis
- Aggregate risk metrics across all held positions
- Portfolio-level Sharpe, drawdown, sector concentration
- Rebalancing suggestions based on MPT optimization

---

### Stream D — Infrastructure & Quality

#### D1. CI/CD Pipeline
- GitHub Actions workflow for:
  - Unit tests on every push (`pytest -m "not integration"`)
  - Linting (ruff, black)
  - Type checking (mypy on Analysis/ and portfolio_app/)

#### D2. Per-Phase Gate Enforcement
- Add `enforce_gates=True` flag to `AnalysisConfig`
- When enabled, `run_full_analysis()` stops at the first failing gate and returns partial results
- Default: False (backward compatible)

#### D3. FinanceToolkit Integration
- Wire FinanceToolkit as a complementary data source for ratios/metrics not available via fmp_cached
- Use for Piotroski, Altman, DuPont decomposition where FT has cleaner implementations

---

## Recommended Execution Order

```
Week 1-2:  A1 (DCF/Valuation — critical gap)
Week 3:    A2 (Extended Technicals)
Week 4:    A3 + A4 (Profile + Fundamentals — can parallelize)
Week 5:    D2 (Gate enforcement) + B1 (Consolidated notebook)
Week 6:    A5 + A6 + A7 (Polish remaining phases)
Week 7:    B2 (Report generation) + C1 (Live refresh)
Week 8:    C2 + C3 (Screening + Portfolio analysis)
Ongoing:   D1 (CI/CD), D3 (FinanceToolkit)
```

---

## Success Criteria

| Milestone | Metric |
|---|---|
| Analysis module 100% | All 7 phases match their spec docs; all gates functional; 200+ tests passing |
| Notebook works E2E | Single notebook runs all 7 phases for any symbol with one cell change |
| Report generation | One-click PDF/HTML memo from `run_full_analysis()` |
| Portfolio screening | Screen 50+ stocks and rank by composite score in <5 minutes |
| CI green | All unit tests + lint + type checks pass on push |

---

## Files to Create/Modify

| Action | File | Stream |
|---|---|---|
| Modify | `Analysis/stock_analysis.py` | A1–A7 |
| Modify | `Analysis/tests/test_stock_analysis.py` | A1–A7 |
| Create | `Analysis/01. phased_stock_analysis.ipynb` | B1 |
| Create | `Analysis/report_generator.py` | B2 |
| Create | `Analysis/templates/investment_memo.html` | B2 |
| Modify | `portfolio_app/main.py` | C1–C3 |
| Modify | `portfolio_app/service.py` | C1–C3 |
| Create | `.github/workflows/ci.yml` | D1 |
