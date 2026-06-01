# Single-Stock Analysis Playbook (OpenBB + FinanceToolkit)

This is the master playbook for analyzing one stock symbol end-to-end with a repeatable, engineering-friendly workflow.

Audience: new joiners who are strong in Python/software engineering and want a practical, senior-trader style framework for financial analysis.

## Implementation Status Summary

The notebook `Analysis/00. single_stock_analysis_playbook_template.ipynb` implements the core pipeline. Each phase document now includes a detailed status table. High-level summary:

| Phase | Plan Completeness | Key Gaps |
|-------|------------------|----------|
| Phase 1 | ~40% | Missing: revenue geography/segment, insider/institutional ownership, analyst revisions, qualitative gate |
| Phase 2 | ~55% | Missing: 5Y CAGR (only YoY), quarterly data, Interest Coverage, Net Debt/EBITDA, cash quality KPIs, phase gate |
| Phase 3 | ~35% | Missing: SMA 50/200, Stochastic, MACD in scoring, BB in scoring, multi-timeframe, trade checklist |
| Phase 4 | ~50% | Missing: DCF intrinsic valuation, Margin of Safety, sensitivity analysis, historical multiples |
| Phase 5 | ~75% | All 8 core risk KPIs implemented. Missing: position sizing, stress scenarios, correlation vs holdings |
| Phase 6 | ~60% | Core relative table + visuals done. Missing: Sortino/Beta per peer, rolling strength, 4-block scoring |
| Phase 7 | ~55% | Scoring engine + export done. Missing: execution KPIs, monitoring cadence, handoff template |

**Cross-cutting gaps:**
- FinanceToolkit is imported but never called (all data via OpenBB `fmp_cached`/`fmp`)
- No per-phase gates (proceed/reject) — all phases run unconditionally
- No quarterly fundamental comparison
- No DCF / intrinsic valuation

---

## How to Use This Playbook

1. Start with this file to understand flow and standards.
2. Execute each phase in order.
3. Record outputs (tables, scores, verdicts) in your notebook/research artifact.
4. Do not skip phases; each phase gates the next.

## Phase Documents

- Phase 1 — Company Profile & Business Quality: [PHASE_1_COMPANY_PROFILE_AND_QUALITY.md](phases/PHASE_1_COMPANY_PROFILE_AND_QUALITY.md)
- Phase 2 — Five-Year Fundamentals: [PHASE_2_FIVE_YEAR_FUNDAMENTALS.md](phases/PHASE_2_FIVE_YEAR_FUNDAMENTALS.md)
- Phase 3 — Technical Analysis & Timing: [PHASE_3_TECHNICAL_ANALYSIS_AND_TIMING.md](phases/PHASE_3_TECHNICAL_ANALYSIS_AND_TIMING.md)
- Phase 4 — Valuation & Fair Value: [PHASE_4_VALUATION_AND_FAIR_VALUE.md](phases/PHASE_4_VALUATION_AND_FAIR_VALUE.md)
- Phase 5 — Risk & Portfolio Context: [PHASE_5_RISK_AND_PORTFOLIO_CONTEXT.md](phases/PHASE_5_RISK_AND_PORTFOLIO_CONTEXT.md)
- Phase 6 — Market Segment, ETF Benchmark & Peer Relative Analysis: [PHASE_6_MARKET_SEGMENT_ETF_PEER_RELATIVE_ANALYSIS.md](phases/PHASE_6_MARKET_SEGMENT_ETF_PEER_RELATIVE_ANALYSIS.md)
- Phase 7 — Decision, Execution & Monitoring: [PHASE_7_DECISION_EXECUTION_AND_MONITORING.md](phases/PHASE_7_DECISION_EXECUTION_AND_MONITORING.md)

## End-to-End Workflow

| Stage | What you produce | Gate to next stage | Notebook Implementation |
|---|---|---|---|
| Phase 1 | Business quality note + red flags | Business is understandable; no fatal risk discovered | Partial: profile/quote/peers only, no gate |
| Phase 2 | 5-year KPI scorecard | Weighted score >= 3.5 / 5.0 | Partial: 9 KPIs extracted, no per-phase score/gate |
| Phase 3 | Technical setup sheet | >= 4/6 bullish timing conditions | Partial: 6 indicators computed, only 3 in scoring, no gate |
| Phase 4 | Fair-value range + MOS | Margin of safety and sensitivity completed | Partial: multiples extracted, no DCF/MOS/sensitivity |
| Phase 5 | Risk-fit and sizing suggestion | Position fits portfolio risk budget | Good: 8 risk KPIs, no sizing logic |
| Phase 6 | Segment ETF + peer-relative scorecard | Relative score >= 3.5 and no major weakness vs peers | Good: relative table + visuals, simplified scoring, no gate |
| Phase 7 | Final decision memo | Buy/Hold/Sell + execution + monitoring triggers | Good: scoring + export, no execution/monitoring KPIs |

## Core KPI Families (used across phases)

- Business Quality KPIs: concentration, ownership, revisions, segment/geographic dependence.
- Fundamental KPIs: growth (revenue/EPS/FCF), profitability (margins/ROIC), balance-sheet safety, cash-flow quality.
- Technical KPIs: trend (SMA/ADX), momentum (RSI/MACD), volatility (ATR/Bollinger), volume confirmation (OBV/breakout ratio).
- Valuation KPIs: P/E, EV/EBITDA, P/FCF, DCF fair value, margin of safety, Piotroski, Altman.
- Risk KPIs: Sharpe/Sortino/Alpha, VaR/CVaR, Max Drawdown, Beta/correlation.
- Relative KPIs: peer/ETF return rank, Sharpe rank, drawdown and tail-risk rank, rolling relative strength.

Each phase document now includes:
- Metric definition in plain English
- Why it matters
- Practical threshold/range
- Example interpretation
- Programmatic extraction snippets using OpenBB and/or FinanceToolkit

## Standard Environment Setup

### Currently used in notebook (Cell 3)
```python
import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from dotenv import load_dotenv

warnings.filterwarnings("ignore")

from openbb import obb
import openbb
from financetoolkit import Toolkit  # imported but not actively used

load_dotenv(r"I:\masterswork\git\OpenBB\.env", override=True)
fmp_api_key = os.getenv("FMP_API_KEY") or os.getenv("FMP_API")

if fmp_api_key:
    obb.user.credentials.fmp_api_key = fmp_api_key
    obb.user.credentials.fmp_cached_api_key = fmp_api_key
```

### Configuration (Cell 5)
```python
SYMBOL = "CLS"          # replace with incoming ticker
BENCHMARK = "SPY"
today = pd.Timestamp.today().normalize()
START_DATE_FUNDAMENTALS = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
START_DATE_TECHNICALS = (today - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
END_DATE = today.strftime("%Y-%m-%d")

PRIMARY_PROVIDER = "fmp_cached"
FALLBACK_PROVIDER = "fmp"
RISK_FREE_RATE = 0.02

obb.user.preferences.output_type = "dataframe"
```

Note: The notebook uses dynamic date computation (today - 5yr / today - 1yr) rather than hardcoded dates. Provider is `fmp_cached` with `fmp` fallback via `call_obb()` wrapper.

## Quality Standards for New Joiners

- Always include a bull case and bear case.
- Never use one metric in isolation.
- Keep assumptions explicit (WACC, terminal growth, benchmark, date range).
- Keep code reproducible and auditable.
- Re-run review after earnings, guidance updates, or major macro regime change.

## Suggested Repository Structure for Deliverables

- `Analysis/<ticker>/01_profile.md`
- `Analysis/<ticker>/02_fundamentals.ipynb`
- `Analysis/<ticker>/03_technicals.ipynb`
- `Analysis/<ticker>/04_valuation.ipynb`
- `Analysis/<ticker>/05_risk.md`
- `Analysis/<ticker>/06_relative_analysis.ipynb`
- `Analysis/<ticker>/07_decision_memo.md`

## Final Output Requirement (for each ticker)

A single decision memo containing:
1. Investment thesis (3-5 bullets)
2. Key KPI dashboard snapshot
3. Fair value and margin-of-safety range
4. Position size + stop logic
5. Monitoring triggers and invalidation conditions

---

Version: 2.2  
Updated: 2026-03-22  
Owner: Research Engineering / Quantamental Team  
Last consistency check: 2026-03-22 (vs notebook `00. single_stock_analysis_playbook_template.ipynb`)
