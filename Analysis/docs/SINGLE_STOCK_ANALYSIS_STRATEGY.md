# Single-Stock Analysis Playbook (OpenBB + FinanceToolkit)

This is the master playbook for analyzing one stock symbol end-to-end with a repeatable, engineering-friendly workflow.

Audience: new joiners who are strong in Python/software engineering and want a practical, senior-trader style framework for financial analysis.

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
- Phase 6 — Decision, Execution & Monitoring: [PHASE_6_DECISION_EXECUTION_AND_MONITORING.md](phases/PHASE_6_DECISION_EXECUTION_AND_MONITORING.md)

## End-to-End Workflow

| Stage | What you produce | Gate to next stage |
|---|---|---|
| Phase 1 | Business quality note + red flags | Business is understandable; no fatal risk discovered |
| Phase 2 | 5-year KPI scorecard | Weighted score >= 3.5 / 5.0 |
| Phase 3 | Technical setup sheet | >= 4/6 bullish timing conditions |
| Phase 4 | Fair-value range + MOS | Margin of safety and sensitivity completed |
| Phase 5 | Risk-fit and sizing suggestion | Position fits portfolio risk budget |
| Phase 6 | Final decision memo | Buy/Hold/Sell + execution + monitoring triggers |

## Core KPI Families (used across phases)

- Business Quality KPIs: concentration, ownership, revisions, segment/geographic dependence.
- Fundamental KPIs: growth (revenue/EPS/FCF), profitability (margins/ROIC), balance-sheet safety, cash-flow quality.
- Technical KPIs: trend (SMA/ADX), momentum (RSI/MACD), volatility (ATR/Bollinger), volume confirmation (OBV/breakout ratio).
- Valuation KPIs: P/E, EV/EBITDA, P/FCF, DCF fair value, margin of safety, Piotroski, Altman.
- Risk KPIs: Sharpe/Sortino/Alpha, VaR/CVaR, Max Drawdown, Beta/correlation.

Each phase document now includes:
- Metric definition in plain English
- Why it matters
- Practical threshold/range
- Example interpretation
- Programmatic extraction snippets using OpenBB and/or FinanceToolkit

## Standard Environment Setup

```python
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, r"I:\masterswork\git\OpenBB\FinanceToolkit")

from openbb import obb
from financetoolkit import Toolkit

load_dotenv(r"I:\masterswork\git\OpenBB\.env")
API_KEY = os.getenv("FMP_API_KEY")

SYMBOL = "CLS"  # replace with incoming ticker
BENCHMARK = "SPY"
START_DATE_FUNDAMENTALS = "2021-01-01"
START_DATE_TECHNICALS = "2024-01-01"
```

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
- `Analysis/<ticker>/06_decision_memo.md`

## Final Output Requirement (for each ticker)

A single decision memo containing:
1. Investment thesis (3-5 bullets)
2. Key KPI dashboard snapshot
3. Fair value and margin-of-safety range
4. Position size + stop logic
5. Monitoring triggers and invalidation conditions

---

Version: 2.0  
Updated: 2026-02-27  
Owner: Research Engineering / Quantamental Team
