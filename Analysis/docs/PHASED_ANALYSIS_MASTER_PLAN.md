# Phased Single-Stock Analysis — Master Plan

**Version:** 1.1
**Date:** 2026-03-22
**Owner:** Research Engineering / Quantamental Team
**Status:** Approved for implementation

**Changelog v1.1:** Added §A — Extended Fundamental KPI Pack (Phase 2) and §B — Extended Technical Timing Stack (Phase 3), with full analyst and trader rationale plus educational references.

---

## Purpose

This document is the single authoritative reference that ties together all seven phase design documents into a coherent module + notebook implementation plan. It maps each phase to its module function, fmp_cached endpoints, KPIs, gate conditions, and notebook structure — and tracks every gap between the existing partial notebook and the target state.

Audience: engineers picking up the implementation from Step A (module) through Step C (notebook).

---

## Table of Contents

1. [Project Overview Table](#1-project-overview-table)
2. [Provider Consistency Rules (fmp_cached)](#2-provider-consistency-rules-fmp_cached)
3. [Phase 4 DCF Decision](#2b-phase-4-dcf-decision)
4. [Module Architecture — `Analysis/stock_analysis.py`](#3-module-architecture--analysissstock_analysispy)
5. [Test Strategy — `Analysis/tests/test_stock_analysis.py`](#4-test-strategy--analysisteststest_stock_analysispy)
6. [Notebook Architecture — `Analysis/01. phased_stock_analysis.ipynb`](#5-notebook-architecture--analysis01-phased_stock_analysisipynb)
7. [Gap Resolution Table](#6-gap-resolution-table)
8. [File Layout](#7-file-layout)
9. [Phase-by-Phase Quick Reference](#8-phase-by-phase-quick-reference)
10. [Composite Score Weights (Phase 7)](#9-composite-score-weights-phase-7)
11. [Implementation Sequence](#10-implementation-sequence)
12. [Extended Fundamental KPI Pack — Phase 2 Additions](#appendix-c-extended-fundamental-kpi-pack--phase-2-additions)
13. [Extended Technical Timing Stack — Phase 3 Additions](#appendix-d-extended-technical-timing-stack--phase-3-additions)

---

## 1. Project Overview Table

This table is the single-line summary of the entire analysis pipeline. Every column is cross-referenced to the relevant phase document.

| # | Phase Name | Core Objective | Primary fmp_cached Endpoints | Key KPIs Produced | Module Function | Notebook Section | Gate Condition | Current Notebook % |
|---|---|---|---|---|---|---|---|---|
| 1 | [Company Profile & Quality](#phase-1) | Build a business-first view; determine if the company is worth analysing further | `equity.profile`, `equity.price.quote`, `equity.fundamental.metrics`, `equity.compare.peers`, `equity.fundamental.revenue_per_geography`, `equity.ownership.insider_trading`, `equity.ownership.institutional`, `equity.estimates.price_target` | Market Cap, Sector, Industry, Peer Count, Revenue Mix (Geo/Segment), Insider %, Institutional %, Analyst Price Targets | `phase1_company_profile(cfg)` | **§1 Company Profile & Quality** | Business understandable + no unpriced existential risk | ~40% |
| 2 | [5-Year Fundamentals](#phase-2) | Measure business quality, durability, and improvement trend over 5 years | `equity.fundamental.income`, `equity.fundamental.balance`, `equity.fundamental.cash`, `equity.fundamental.ratios` | Revenue CAGR (5Y), EPS CAGR (5Y), FCF CAGR (5Y), Gross/Operating/Net Margin, ROIC, D/E, Interest Coverage, Net Debt/EBITDA, CFO/NI, FCF Margin, Capex/Revenue | `phase2_fundamentals(cfg)` | **§2 Five-Year Fundamentals** | Weighted score ≥ 3.5 / 5.0 | ~55% |
| 3 | [Technical Analysis & Timing](#phase-3) | Time entries and exits using full indicator stack after fundamentals pass | `equity.price.historical` (1yr daily) | RSI(14), MACD(12,26,9), ADX(14), ATR(14), OBV, SMA50, SMA200, Stochastic(14,3,3), BB Width, Breakout Vol Ratio | `phase3_technicals(cfg)` | **§3 Technical Analysis & Timing** | ≥ 4 of 6 bullish conditions true | ~35% |
| 4 | [Valuation & Fair Value](#phase-4) | Convert business quality into a price decision using three valuation lenses | `equity.fundamental.metrics`, `equity.fundamental.ratios`, `equity.fundamental.income`, `equity.fundamental.cash` | P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield, DCF Fair Value, Margin of Safety, WACC proxy, Sensitivity Table (3×3), Piotroski F-Score, Altman Z-Score | `phase4_valuation(cfg)` | **§4 Valuation & Fair Value** | ≥ 2 methods agree on direction + MOS computed | ~50% |
| 5 | [Risk & Portfolio Context](#phase-5) | Determine if the stock fits risk budget and portfolio role | `equity.price.historical` (symbol + SPY) | Sharpe, Sortino, Jensen's Alpha, Beta, VaR(95%), CVaR(95%), Max Drawdown, Ulcer Index | `phase5_risk(cfg)` | **§5 Risk & Portfolio Context** | Position sized + stress scenario documented | ~75% |
| 6 | [Market Segment & Peer Relative](#phase-6) | Evaluate the symbol against its segment ETF and peer basket | `equity.price.historical` (universe), `equity.profile` (peers) | Ann. Return, Ann. Vol, Sharpe, Sortino, MDD, VaR, CVaR, Beta, Correlation vs ETF — all per peer/ETF | `phase6_peer_relative(cfg)` | **§6 Peer Relative Analysis** | Relative score ≥ 3.5 / 5.0 | ~60% |
| 7 | [Decision & Monitoring](#phase-7) | Convert all prior phases into an actionable, auditable trade decision | (uses phase 1–6 results) | Composite Score (0–5), Action Label, Score Breakdown, ATR Stop, 2R Target, Monitoring Triggers | `phase7_decision(cfg, p1…p6)` | **§7 Decision & Monitoring** | Composite score + action label produced | ~55% |

> **Source documents:**
> Phase 1 → [`phases/PHASE_1_COMPANY_PROFILE_AND_QUALITY.md`](phases/PHASE_1_COMPANY_PROFILE_AND_QUALITY.md)
> Phase 2 → [`phases/PHASE_2_FIVE_YEAR_FUNDAMENTALS.md`](phases/PHASE_2_FIVE_YEAR_FUNDAMENTALS.md)
> Phase 3 → [`phases/PHASE_3_TECHNICAL_ANALYSIS_AND_TIMING.md`](phases/PHASE_3_TECHNICAL_ANALYSIS_AND_TIMING.md)
> Phase 4 → [`phases/PHASE_4_VALUATION_AND_FAIR_VALUE.md`](phases/PHASE_4_VALUATION_AND_FAIR_VALUE.md)
> Phase 5 → [`phases/PHASE_5_RISK_AND_PORTFOLIO_CONTEXT.md`](phases/PHASE_5_RISK_AND_PORTFOLIO_CONTEXT.md)
> Phase 6 → [`phases/PHASE_6_MARKET_SEGMENT_ETF_PEER_RELATIVE_ANALYSIS.md`](phases/PHASE_6_MARKET_SEGMENT_ETF_PEER_RELATIVE_ANALYSIS.md)
> Phase 7 → [`phases/PHASE_7_DECISION_EXECUTION_AND_MONITORING.md`](phases/PHASE_7_DECISION_EXECUTION_AND_MONITORING.md)

---

## 2. Provider Consistency Rules (fmp_cached)

### 2.1 Single-provider mandate

```python
PRIMARY_PROVIDER = "fmp_cached"
```

**The module (`Analysis/stock_analysis.py`) uses `fmp_cached` as the only provider.** There is no `fmp` fallback in any module function. This is a hard constraint that differs from the existing notebook's `call_obb()` wrapper (which tries `fmp_cached` first and falls back to `fmp`).

Rationale: the notebook's fallback logic masks caching failures and makes outputs non-deterministic. The module must be fully deterministic and testable.

### 2.2 Credential setup

Every caller of the module must set credentials before invoking any phase function:

```python
from openbb import obb
import os

fmp_api_key = os.getenv("FMP_API_KEY") or os.getenv("FMP_API")
obb.user.credentials.fmp_api_key = fmp_api_key
obb.user.credentials.fmp_cached_api_key = fmp_api_key
obb.user.preferences.output_type = "dataframe"
```

The `AnalysisConfig` dataclass (see §3) stores the provider string and passes it through all phase functions so the caller can change it at construction time for testing without monkey-patching globals.

### 2.3 Confirmed fmp_cached endpoint coverage

The following endpoints are confirmed available in `openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/`:

| OpenBB endpoint | fmp_cached model file | Used in phase |
|---|---|---|
| `equity.profile` | `equity_profile.py` | 1 |
| `equity.price.quote` | `equity_quote.py` | 1 |
| `equity.fundamental.metrics` | `key_metrics.py` | 1, 4 |
| `equity.compare.peers` | `equity_peers.py` | 1 |
| `equity.fundamental.revenue_per_geography` | `revenue_geographic.py` | 1 |
| `equity.ownership.insider_trading` | `insider_trading.py` | 1 |
| `equity.ownership.institutional` | `institutional_ownership.py` | 1 |
| `equity.estimates.price_target` | `price_target.py` | 1 |
| `equity.estimates.price_target_consensus` | `price_target_consensus.py` | 1 |
| `equity.fundamental.income` | `income_statement.py` | 2, 4 |
| `equity.fundamental.balance` | `balance_sheet.py` | 2, 4 |
| `equity.fundamental.cash` | `cash_flow.py` | 2, 4 |
| `equity.fundamental.ratios` | `financial_ratios.py` | 2, 4 |
| `equity.price.historical` | `equity_historical.py` | 3, 5, 6 |
| `equity.fundamental.revenue_per_segment` | `revenue_business_line.py` | 1 |

All endpoints above are called with `provider="fmp_cached"` in the module. No endpoint in the module uses any other provider string.

### 2.4 What is NOT in fmp_cached (handled differently)

- **Technical indicators**: computed from OHLCV data returned by `equity.price.historical` using pure pandas/numpy in `_compute_technicals()` — no provider call needed.
- **Risk metrics**: computed from price returns using pandas/numpy — no provider call needed.
- **DCF / MOS**: computed from raw financial statement data using the formula in §2b — no provider call needed.

---

## 2b. Phase 4 DCF Decision

### Design principle

The DCF is computed entirely from `fmp_cached` raw data (cash flow statement + key metrics for WACC proxy) using pure OpenBB + pandas arithmetic. No external library dependency (no FinancialModelingPrep SDK, no FinanceToolkit) is introduced. All numbers come from the data already fetched in `phase4_valuation()`.

### Inputs

| Input | Source field | Fallback |
|---|---|---|
| Latest FCF | `cash_df["free_cash_flow"]` latest row | `operating_cash_flow - capital_expenditures` |
| Short-term growth `g_short` | revenue CAGR from `phase2_fundamentals` | 0.05 |
| Terminal growth `g_term` | hard-coded conservative default | 0.025 |
| WACC proxy | `ratios_df["wacc"]` latest row | `0.09` if missing/NaN |
| Current price | `quote_df["last_price"]` | `metrics_df["price"]` |
| Shares outstanding | `metrics_df["shares_outstanding"]` | from income_df |

### DCF formula (5-year explicit + terminal value)

```
# Explicit 5-year period
PV_explicit = sum(
    FCF_latest * (1 + g_short)^t / (1 + WACC)^t
    for t in range(1, 6)
)

# Terminal value (Gordon Growth Model)
FCF_year5 = FCF_latest * (1 + g_short)^5
TV         = FCF_year5 * (1 + g_term) / (WACC - g_term)
PV_TV      = TV / (1 + WACC)^5

# Intrinsic equity value per share
DCF_fair_value = (PV_explicit + PV_TV) / shares_outstanding
```

Guard: if `WACC <= g_term`, clamp `g_term = WACC - 0.01` to prevent division by zero.

### Sensitivity table (3×3 grid)

Axes: WACC ∈ {base−1%, base, base+1%} × terminal growth ∈ {g_term−0.5%, g_term, g_term+0.5%}

```python
import pandas as pd

def _dcf_sensitivity(fcf, g_short, wacc_base, g_term_base, shares):
    rows = {}
    for dw in [-0.01, 0.0, 0.01]:
        row = {}
        for dg in [-0.005, 0.0, 0.005]:
            w = wacc_base + dw
            g = g_term_base + dg
            if w <= g:
                g = w - 0.01
            pv = sum(fcf * (1 + g_short)**t / (1 + w)**t for t in range(1, 6))
            fcf5 = fcf * (1 + g_short)**5
            tv = fcf5 * (1 + g) / (w - g)
            pv_tv = tv / (1 + w)**5
            row[f"g={g_term_base+dg:.1%}"] = (pv + pv_tv) / shares
        rows[f"WACC={wacc_base+dw:.1%}"] = row
    return pd.DataFrame(rows).T
```

### Margin of Safety

```python
margin_of_safety = (DCF_fair_value - current_price) / DCF_fair_value
```

Interpretation:
- MOS ≥ 20%: attractive buy zone
- MOS 5–20%: mildly attractive / fair
- MOS ±5%: at fair value
- MOS < −15%: overvalued — avoid / trim

### Output fields added to `Phase4Result`

```python
@dataclass
class Phase4Result:
    multiples_df: pd.DataFrame       # P/E, EV/EBITDA, P/FCF, P/S, Earnings Yield
    dcf_estimate: float              # per-share intrinsic value
    dcf_sensitivity: pd.DataFrame    # 3×3 grid (WACC rows × g_term cols)
    margin_of_safety: float          # (dcf - price) / dcf
    wacc_used: float                 # actual WACC used (from data or default)
    g_short_used: float              # short-term growth rate used
    g_term_used: float               # terminal growth rate used
    piotroski: float                 # Piotroski F-Score
    altman: float                    # Altman Z-Score
    gate_passed: bool                # True if ≥ 2 methods agree + MOS computed
```

---

## 3. Module Architecture — `Analysis/stock_analysis.py`

### 3.1 Configuration dataclass

```python
from dataclasses import dataclass, field
from datetime import date

@dataclass
class AnalysisConfig:
    symbol: str
    benchmark: str = "SPY"
    start_fundamentals: str = field(default_factory=lambda: ...)   # today - 5yr
    start_technicals: str  = field(default_factory=lambda: ...)    # today - 1yr
    end_date: str          = field(default_factory=lambda: date.today().isoformat())
    provider: str          = "fmp_cached"
    risk_free_rate: float  = 0.02
```

The `start_fundamentals` and `start_technicals` defaults are computed dynamically (not hardcoded) using `pd.Timestamp.today()` minus the relevant offset, matching the notebook's existing convention.

### 3.2 Result dataclasses

Each phase function returns a typed dataclass so callers can access fields by name. All dataclasses carry a `gate_passed: bool` field that encodes the proceed/reject decision for that phase.

```python
@dataclass
class Phase1Result:
    profile_df: pd.DataFrame
    quote_df: pd.DataFrame
    metrics_df: pd.DataFrame
    peers: list[str]
    revenue_geo_df: pd.DataFrame
    revenue_seg_df: pd.DataFrame
    insider_df: pd.DataFrame
    institutional_df: pd.DataFrame
    price_targets_df: pd.DataFrame
    summary_df: pd.DataFrame          # one-row summary card
    gate_passed: bool

@dataclass
class Phase2Result:
    income_df: pd.DataFrame
    balance_df: pd.DataFrame
    cash_df: pd.DataFrame
    ratios_df: pd.DataFrame
    kpi_df: pd.DataFrame              # all KPIs in one indexed DataFrame
    score: float                      # weighted 1–5 score
    gate_passed: bool                 # score >= 3.5

@dataclass
class Phase3Result:
    price_df: pd.DataFrame            # OHLCV + all 10 indicators as columns
    signals: dict[str, bool]          # name → bullish/bearish bool per condition
    bullish_count: int
    gate_passed: bool                 # bullish_count >= 4

@dataclass
class Phase4Result:
    multiples_df: pd.DataFrame
    dcf_estimate: float
    dcf_sensitivity: pd.DataFrame
    margin_of_safety: float
    wacc_used: float
    g_short_used: float
    g_term_used: float
    piotroski: float
    altman: float
    gate_passed: bool

@dataclass
class Phase5Result:
    risk_kpi_df: pd.DataFrame         # Sharpe, Sortino, Alpha, Beta, VaR, CVaR, MaxDD, Ulcer
    stress_note: str                  # narrative for -20% market / +100bps rate scenario
    position_size_pct: float          # conviction-based sizing (1%–5%)
    gate_passed: bool

@dataclass
class Phase6Result:
    universe: list[str]
    universe_df: pd.DataFrame         # per-asset metrics
    relative_table: pd.DataFrame      # ranked by Sharpe
    corr_matrix: pd.DataFrame
    sector_etf: str
    score: float                      # 4-block weighted score
    gate_passed: bool                 # score >= 3.5

@dataclass
class Phase7Result:
    composite_score: float
    action_label: str                 # "Strong Buy" / "Buy" / "Hold/Watch" / "Avoid/Sell"
    score_breakdown: dict[str, float] # per-block scores
    atr_stop: float                   # current_price - 2 * ATR
    target_2r: float                  # current_price + 2 * risk_per_share
    monitoring_triggers: dict[str, str]
    handoff: dict[str, str]           # 6-item handoff template
```

### 3.3 Phase function signatures

```python
def phase1_company_profile(cfg: AnalysisConfig) -> Phase1Result: ...
def phase2_fundamentals(cfg: AnalysisConfig) -> Phase2Result: ...
def phase3_technicals(cfg: AnalysisConfig) -> Phase3Result: ...
def phase4_valuation(cfg: AnalysisConfig) -> Phase4Result: ...
def phase5_risk(cfg: AnalysisConfig) -> Phase5Result: ...
def phase6_peer_relative(cfg: AnalysisConfig, peers: list[str] | None = None) -> Phase6Result: ...
def phase7_decision(
    cfg: AnalysisConfig,
    p1: Phase1Result, p2: Phase2Result, p3: Phase3Result,
    p4: Phase4Result, p5: Phase5Result, p6: Phase6Result,
) -> Phase7Result: ...
```

`phase6_peer_relative` accepts an optional `peers` override; if `None` it auto-discovers peers from `equity.compare.peers`.

### 3.4 Private helper functions

| Helper | Signature | Purpose |
|---|---|---|
| `_to_df` | `(result) → pd.DataFrame` | Safe `.to_df()` call — returns empty DataFrame on error/None instead of raising |
| `_latest_col` | `(df, candidates: list[str]) → str \| None` | Returns the first column name from `candidates` that exists in `df`; returns `None` if none match |
| `_cagr` | `(series: pd.Series, years: int) → float` | `(series.iloc[-1] / series.iloc[0]) ** (1/years) - 1`; guards against zero/negative base |
| `_compute_technicals` | `(df: pd.DataFrame) → pd.DataFrame` | Adds all 10 indicator columns (RSI, MACD, ADX, ATR, OBV, SMA50, SMA200, Stochastic %K/%D, BB Width, Breakout Vol Ratio) to an OHLCV DataFrame using pandas/numpy only |
| `_decision_label` | `(score: float) → str` | Maps composite score to action string using the 4-band thresholds |
| `_clamp` | `(x, lo, hi) → float` | Clamps a value to [lo, hi] for score normalisation |
| `_dcf_sensitivity` | `(fcf, g_short, wacc_base, g_term_base, shares) → pd.DataFrame` | Computes the 3×3 sensitivity grid (see §2b) |

### 3.5 Technical indicator computation detail (`_compute_technicals`)

All indicators are computed from the `close`, `high`, `low`, `volume` columns of the OHLCV DataFrame returned by `equity.price.historical`. No external TA library is required.

| Indicator | Formula / Method |
|---|---|
| RSI(14) | Standard Wilder smoothing: avg gain / avg loss over 14-period rolling window |
| MACD(12,26,9) | `ema12 - ema26`; signal = `ema9(macd_line)`; histogram = `macd_line - signal` |
| ADX(14) | True range → +DI / −DI → DX → Wilder-smoothed ADX |
| ATR(14) | Wilder-smoothed true range |
| OBV | Cumulative signed volume (sign of close-to-close return) |
| SMA50 | `close.rolling(50).mean()` |
| SMA200 | `close.rolling(200).mean()` |
| Stochastic %K/%D (14,3,3) | `%K = (close - low14) / (high14 - low14) * 100`; `%D = %K.rolling(3).mean()` |
| BB Width (20,2) | `(upper - lower) / middle` where upper/lower are `SMA20 ± 2×std20` |
| Breakout Vol Ratio | `volume / volume.rolling(20).mean()` |

---

## 4. Test Strategy — `Analysis/tests/test_stock_analysis.py`

### 4.1 Structure

```
tests/
└── test_stock_analysis.py
    ├── TestPhase1MSFT
    ├── TestPhase1AAPL
    ├── TestPhase2MSFT
    ├── TestPhase2AAPL
    ├── TestPhase3MSFT
    ├── TestPhase3AAPL
    ├── TestPhase4MSFT
    ├── TestPhase4AAPL
    ├── TestPhase5MSFT
    ├── TestPhase5AAPL
    ├── TestPhase6MSFT
    ├── TestPhase6AAPL
    └── TestPhase7Decision          # mocked — no live API
```

### 4.2 Per-class test pattern

Each `TestPhaseN<TICKER>` class verifies three things:

1. **No exception** — function returns without raising
2. **Required fields present** — all dataclass fields are non-None / non-empty
3. **Plausibility checks** — KPI values are within reasonable financial ranges

Example for Phase 2:

```python
@pytest.mark.integration
class TestPhase2MSFT:
    cfg = AnalysisConfig(symbol="MSFT")

    def test_returns(self):
        result = phase2_fundamentals(self.cfg)
        assert isinstance(result, Phase2Result)

    def test_kpi_df_non_empty(self):
        result = phase2_fundamentals(self.cfg)
        assert not result.kpi_df.empty
        assert "revenue_cagr_5y" in result.kpi_df.index

    def test_score_range(self):
        result = phase2_fundamentals(self.cfg)
        assert 1.0 <= result.score <= 5.0

    def test_provider_used(self):
        result = phase2_fundamentals(self.cfg)
        # MSFT is well-covered; income_df must have >=4 rows
        assert len(result.income_df) >= 4
```

### 4.3 Phase 7 unit test (no live API)

`TestPhase7Decision` uses `pytest-mock` (or `unittest.mock`) to construct synthetic Phase1–6 results with known scores and asserts that `phase7_decision` produces the correct composite score and action label:

```python
class TestPhase7Decision:
    def test_strong_buy(self):
        # Build mock results where all scores = 5.0
        # Expected composite: 5.0 → "Strong Buy"
        ...

    def test_avoid(self):
        # All scores = 1.0 → composite 1.0 → "Avoid/Sell"
        ...

    def test_boundary_buy(self):
        # Composite = 3.6 → "Buy"
        ...

    def test_execution_kpis_present(self):
        # atr_stop and target_2r are finite floats
        ...
```

### 4.4 Markers and configuration

```ini
# pytest.ini (or pyproject.toml)
[pytest]
markers =
    integration: requires live FMP API access and network
```

Run unit tests only (CI-safe):
```bash
pytest Analysis/tests/ -m "not integration" -v
```

Run full suite including live API:
```bash
pytest Analysis/tests/ -v
```

---

## 5. Notebook Architecture — `Analysis/01. phased_stock_analysis.ipynb`

### 5.1 Overview

The notebook imports all functions from `stock_analysis.py` and calls each phase in sequence. It contains no inline business logic — only calls, display, and commentary. This separation ensures the module can be tested independently of the notebook.

### 5.2 Cell-by-cell structure

| Cell(s) | Type | Content |
|---|---|---|
| 1 | Markdown | Title, purpose, version, date |
| 2 | Code | Imports: `stock_analysis.*`, pandas, matplotlib, seaborn, warnings |
| 3 | Code | Env setup: load `.env`, set OBB credentials, `obb.user.preferences.output_type = "dataframe"` |
| 4 | Code | Config instantiation: `cfg = AnalysisConfig(symbol="MSFT")` (or AAPL) |
| — | Markdown | **§1 Company Profile & Quality** |
| 5 | Code | `p1 = phase1_company_profile(cfg)` |
| 6 | Code | `display(p1.summary_df)` + `display(p1.revenue_geo_df)` + `display(p1.price_targets_df)` |
| 7 | Markdown | Phase 1 commentary: business summary, top 3 risks, gate decision |
| — | Markdown | **§2 Five-Year Fundamentals** |
| 8 | Code | `p2 = phase2_fundamentals(cfg)` |
| 9 | Code | `display(p2.kpi_df)` + trend bar charts for margins / CAGR |
| 10 | Markdown | Phase 2 commentary: score, scorecard category breakdown |
| — | Markdown | **§3 Technical Analysis & Timing** |
| 11 | Code | `p3 = phase3_technicals(cfg)` |
| 12 | Code | Price + indicator chart (SMA50/200, RSI, MACD, ADX panels) |
| 13 | Code | `display(pd.DataFrame(p3.signals, index=["Bullish?"]).T)` |
| 14 | Markdown | Phase 3 commentary: bullish count, trade setup checklist |
| — | Markdown | **§4 Valuation & Fair Value** |
| 15 | Code | `p4 = phase4_valuation(cfg)` |
| 16 | Code | `display(p4.multiples_df)` + DCF sensitivity heatmap |
| 17 | Code | `print(f"DCF Fair Value: {p4.dcf_estimate:.2f}  |  MOS: {p4.margin_of_safety:.1%}")` |
| 18 | Markdown | Phase 4 commentary: valuation verdict, MOS zone |
| — | Markdown | **§5 Risk & Portfolio Context** |
| 19 | Code | `p5 = phase5_risk(cfg)` |
| 20 | Code | `display(p5.risk_kpi_df)` + rolling drawdown chart |
| 21 | Markdown | Phase 5 commentary: position size, stress note |
| — | Markdown | **§6 Market Segment & Peer Relative Analysis** |
| 22 | Code | `p6 = phase6_peer_relative(cfg)` |
| 23 | Code | Correlation heatmap + risk-return scatter (Sharpe as bubble size) |
| 24 | Code | `display(p6.relative_table)` |
| 25 | Markdown | Phase 6 commentary: peer rank, ETF comparison |
| — | Markdown | **§7 Decision, Execution & Monitoring** |
| 26 | Code | `p7 = phase7_decision(cfg, p1, p2, p3, p4, p5, p6)` |
| 27 | Code | Score breakdown bar chart + action label badge |
| 28 | Code | `display(pd.DataFrame(p7.score_breakdown, index=["Score"]).T)` + monitoring triggers table |
| 29 | Markdown | Final memo: thesis, entry plan, stop, monitoring triggers |
| 30 | Code | Optional: export to Excel (reuse Cell 37 pattern from existing notebook) |

---

## 6. Gap Resolution Table

This table maps every "not implemented" item from the seven phase design documents to the specific module function and implementation approach.

| Gap (from Phase Docs) | Phase Doc | Module Function | Implementation Approach |
|---|---|---|---|
| Revenue by geography | Phase 1 | `phase1_company_profile` | `obb.equity.fundamental.revenue_per_geography(symbol, provider="fmp_cached")` → `revenue_geographic.py` model |
| Revenue by segment | Phase 1 | `phase1_company_profile` | `obb.equity.fundamental.revenue_per_segment(symbol, provider="fmp_cached")` → `revenue_business_line.py` model |
| Insider ownership | Phase 1 | `phase1_company_profile` | `obb.equity.ownership.insider_trading(symbol, provider="fmp_cached")` → `insider_trading.py` model |
| Institutional ownership | Phase 1 | `phase1_company_profile` | `obb.equity.ownership.institutional(symbol, provider="fmp_cached")` → `institutional_ownership.py` model |
| Analyst price targets | Phase 1 | `phase1_company_profile` | `obb.equity.estimates.price_target(symbol, provider="fmp_cached")` → `price_target.py` + `price_target_consensus.py` |
| Qualitative gate (5 questions) | Phase 1 | `phase1_company_profile` | `gate_passed` computed from quantitative proxies: market cap > $100M, peer_count > 0, data coverage >= 4yr |
| 5Y Revenue CAGR | Phase 2 | `phase2_fundamentals` | `_cagr(income_df["revenue"], years=5)` — uses last 5 annual rows |
| 5Y EPS CAGR | Phase 2 | `phase2_fundamentals` | `_cagr(income_df["eps_diluted"], years=5)` |
| 5Y FCF CAGR | Phase 2 | `phase2_fundamentals` | `_cagr(cash_df["free_cash_flow"], years=5)` |
| Interest Coverage | Phase 2 | `phase2_fundamentals` | `ebit / interest_expense` derived from income_df columns |
| Net Debt / EBITDA | Phase 2 | `phase2_fundamentals` | `(total_debt - cash) / ebitda` from balance_df + income_df |
| CFO / Net Income | Phase 2 | `phase2_fundamentals` | `operating_cash_flow / net_income` from cash_df + income_df |
| FCF Margin | Phase 2 | `phase2_fundamentals` | `free_cash_flow / revenue` from cash_df + income_df |
| Capex / Revenue | Phase 2 | `phase2_fundamentals` | `capital_expenditures / revenue` from cash_df + income_df |
| Per-phase fundamental scorecard | Phase 2 | `phase2_fundamentals` | Five weighted categories (Growth 25%, Profitability 25%, Capital Efficiency 20%, Balance Sheet 20%, Cash Quality 10%) |
| SMA50 / SMA200 | Phase 3 | `phase3_technicals` | `_compute_technicals()`: `close.rolling(50/200).mean()` |
| Stochastic (14,3,3) | Phase 3 | `phase3_technicals` | `_compute_technicals()`: rolling 14-period min/max on close |
| BB Width | Phase 3 | `phase3_technicals` | `_compute_technicals()`: `(upper - lower) / middle` |
| OBV slope (20D) | Phase 3 | `phase3_technicals` | `_compute_technicals()`: `obv.diff(20)` sign |
| Breakout Volume Ratio | Phase 3 | `phase3_technicals` | `_compute_technicals()`: `volume / volume.rolling(20).mean()` |
| MACD in scoring | Phase 3 | `phase3_technicals` | `signals["macd_bullish"] = macd_line > signal_line` |
| Full 6-condition technical gate | Phase 3 | `phase3_technicals` | `gate_passed = bullish_count >= 4` where 6 conditions are: SMA50>SMA200, ADX>=20, RSI in 40–55, MACD bullish, OBV rising, Vol ratio normal |
| DCF Fair Value | Phase 4 | `phase4_valuation` | See §2b: FCF-based simplified DCF, pure pandas arithmetic |
| Margin of Safety | Phase 4 | `phase4_valuation` | `(dcf - price) / dcf` |
| Sensitivity table | Phase 4 | `phase4_valuation` | `_dcf_sensitivity()`: 3×3 grid WACC ±1% × g_term ±0.5% |
| Correlation vs benchmark | Phase 5 | `phase5_risk` | `returns[symbol].corr(returns[benchmark])` |
| Position sizing | Phase 5 | `phase5_risk` | Conviction-to-size: base 1% + 1% per score above 2, capped at 5%, reduced if MaxDD > 40% |
| Stress scenario note | Phase 5 | `phase5_risk` | Compute estimated PnL for -20% market using beta: `stress_pnl = -0.20 * beta` |
| Sortino per peer | Phase 6 | `phase6_peer_relative` | Added to `universe_df` alongside existing metrics |
| Beta per peer | Phase 6 | `phase6_peer_relative` | `cov(asset, SPY) / var(SPY)` for each symbol |
| 4-block relative scorecard | Phase 6 | `phase6_peer_relative` | Return rank 25% + Sharpe/Sortino rank 25% + MDD/VaR rank 25% + rolling-30D consistency 25% |
| Relative gate (>=3.5) | Phase 6 | `phase6_peer_relative` | `gate_passed = score >= 3.5` |
| Execution KPIs (R-basis, stop) | Phase 7 | `phase7_decision` | `atr_stop = current_price - 2 * atr`; `target_2r = current_price + 2 * (current_price - atr_stop)` |
| Monitoring cadence table | Phase 7 | `phase7_decision` | `monitoring_triggers` dict with 5 trigger entries from Phase 7 doc |
| Handoff template | Phase 7 | `phase7_decision` | 6-item `handoff` dict populated from phase results |

---

## 7. File Layout

```
Analysis/
├── stock_analysis.py                    # NEW — single module, 7 phase functions + helpers
├── tests/
│   ├── __init__.py                      # NEW — empty, makes tests a package
│   └── test_stock_analysis.py           # NEW — pytest tests for MSFT + AAPL
├── 00. single_stock_analysis_playbook_template.ipynb   # EXISTING — partial notebook (patterns)
├── 01. phased_stock_analysis.ipynb      # NEW — clean notebook importing from module
└── docs/
    ├── PHASED_ANALYSIS_MASTER_PLAN.md   # THIS FILE — stitched overview plan
    ├── SINGLE_STOCK_ANALYSIS_STRATEGY.md  # EXISTING — master strategy v2.2
    └── phases/
        ├── PHASE_1_COMPANY_PROFILE_AND_QUALITY.md
        ├── PHASE_2_FIVE_YEAR_FUNDAMENTALS.md
        ├── PHASE_3_TECHNICAL_ANALYSIS_AND_TIMING.md
        ├── PHASE_4_VALUATION_AND_FAIR_VALUE.md
        ├── PHASE_5_RISK_AND_PORTFOLIO_CONTEXT.md
        ├── PHASE_6_MARKET_SEGMENT_ETF_PEER_RELATIVE_ANALYSIS.md
        └── PHASE_7_DECISION_EXECUTION_AND_MONITORING.md
```

Supporting directories (not modified by this plan):

```
openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/
├── equity_profile.py                    # obb.equity.profile
├── equity_quote.py                      # obb.equity.price.quote
├── equity_historical.py                 # obb.equity.price.historical
├── equity_peers.py                      # obb.equity.compare.peers
├── key_metrics.py                       # obb.equity.fundamental.metrics
├── income_statement.py                  # obb.equity.fundamental.income
├── balance_sheet.py                     # obb.equity.fundamental.balance
├── cash_flow.py                         # obb.equity.fundamental.cash
├── financial_ratios.py                  # obb.equity.fundamental.ratios
├── revenue_geographic.py                # obb.equity.fundamental.revenue_per_geography
├── revenue_business_line.py             # obb.equity.fundamental.revenue_per_segment
├── insider_trading.py                   # obb.equity.ownership.insider_trading
├── institutional_ownership.py           # obb.equity.ownership.institutional
├── price_target.py                      # obb.equity.estimates.price_target
└── price_target_consensus.py            # obb.equity.estimates.price_target_consensus
```

---

## 8. Phase-by-Phase Quick Reference

| # | Name | Module Function | fmp_cached Endpoints | Gate Condition |
|---|------|----------------|---------------------|------|
| 1 | Company Profile & Quality | `phase1_company_profile` | `equity.profile`, `equity.price.quote`, `equity.fundamental.metrics`, `equity.compare.peers`, `equity.fundamental.revenue_per_geography`, `equity.fundamental.revenue_per_segment`, `equity.ownership.insider_trading`, `equity.ownership.institutional`, `equity.estimates.price_target`, `equity.estimates.price_target_consensus` | Business understandable + no fatal unpriced risk (market cap > $100M, ≥4yr data, peer_count > 0) |
| 2 | 5-Year Fundamentals | `phase2_fundamentals` | `equity.fundamental.income`, `equity.fundamental.balance`, `equity.fundamental.cash`, `equity.fundamental.ratios` | Weighted score ≥ 3.5 / 5.0 across 5 KPI categories |
| 3 | Technical Analysis & Timing | `phase3_technicals` | `equity.price.historical` (1yr daily, provider="fmp_cached") | ≥ 4 of 6 technical conditions bullish |
| 4 | Valuation & Fair Value | `phase4_valuation` | `equity.fundamental.metrics`, `equity.fundamental.ratios`, `equity.fundamental.income`, `equity.fundamental.cash` | ≥ 2 valuation methods agree on direction AND MOS explicitly computed |
| 5 | Risk & Portfolio Context | `phase5_risk` | `equity.price.historical` (symbol + SPY, provider="fmp_cached") | Position size documented + stress scenario estimated |
| 6 | Market Segment & Peer Relative | `phase6_peer_relative` | `equity.price.historical` (universe), `equity.profile` (peers), all with provider="fmp_cached" | 4-block relative score ≥ 3.5 / 5.0 |
| 7 | Decision & Monitoring | `phase7_decision` | No direct data calls — synthesises Phase 1–6 results | Composite score and action label produced; execution KPIs and monitoring triggers documented |

---

## 9. Composite Score Weights (Phase 7)

| Block | Weight | Source Phase | Score Range |
|---|---:|---|---|
| Business Quality | 8% | Phase 1 | 1–5 |
| Fundamentals | 25% | Phase 2 | 1–5 (= `phase2_result.score`) |
| Technical Timing | 15% | Phase 3 | 1–5 (mapped from bullish_count/6 × 5) |
| Valuation | 20% | Phase 4 | 1–5 (based on MOS zone + multiples relative to history) |
| Risk Fit | 12% | Phase 5 | 1–5 (based on Sharpe, MaxDD, Beta vs portfolio target) |
| Peer Relative | 20% | Phase 6 | 1–5 (= `phase6_result.score`) |

**Total = weighted sum (0–5 scale)**

### Action bands

| Composite Score | Decision Label | Suggested Action |
|---:|---|---|
| ≥ 4.2 | **Strong Buy** | Full target size; staged entries over 2–3 sessions |
| ≥ 3.6 | **Buy** | Partial size (50–75%); add on confirmation |
| ≥ 2.8 | **Hold / Watch** | No fresh risk; reassess next earnings / technical trigger |
| < 2.8 | **Avoid / Sell** | Reduce or avoid exposure |

### Phase 7 composite computation (pseudocode)

```python
weights = {
    "business_quality": 0.08,
    "fundamentals":     0.25,
    "technicals":       0.15,
    "valuation":        0.20,
    "risk_fit":         0.12,
    "peer_relative":    0.20,
}

scores = {
    "business_quality": _score_phase1(p1),
    "fundamentals":     p2.score,
    "technicals":       p3.bullish_count / 6 * 5,
    "valuation":        _score_phase4(p4),
    "risk_fit":         _score_phase5(p5),
    "peer_relative":    p6.score,
}

composite = sum(scores[k] * weights[k] for k in weights)
label = _decision_label(composite)
```

Each `_score_phaseN()` helper maps the phase-specific outputs onto the 1–5 scale using the thresholds defined in the respective phase document.

---

## 10. Implementation Sequence

After this master plan document is approved, the following steps are executed in order:

### Step A — Write `Analysis/stock_analysis.py`

1. Define `AnalysisConfig` dataclass and all seven `PhaseNResult` dataclasses.
2. Implement `_to_df`, `_latest_col`, `_cagr`, `_compute_technicals`, `_decision_label`, `_clamp`, `_dcf_sensitivity` helpers.
3. Implement `phase1_company_profile` through `phase7_decision` in phase order.
4. Run a smoke test from a Python shell against `MSFT` to confirm no import or runtime errors.

**Acceptance criteria:** `from stock_analysis import AnalysisConfig, phase1_company_profile; p1 = phase1_company_profile(AnalysisConfig("MSFT"))` executes without error.

### Step B — Write and pass `Analysis/tests/test_stock_analysis.py`

1. Write one test class per phase per ticker (14 classes for MSFT + AAPL, plus `TestPhase7Decision`).
2. Mark all live-API tests with `@pytest.mark.integration`.
3. Run `pytest Analysis/tests/ -m "not integration"` — must show green (Phase 7 unit tests pass with no network).
4. Run `pytest Analysis/tests/ -v` — all integration tests must pass against live FMP cached API.
5. Fix any failures until all tests are green.

**Acceptance criteria:** `pytest Analysis/tests/ -v` exits with code 0 for both tickers.

### Step C — Write `Analysis/01. phased_stock_analysis.ipynb`

1. Create notebook with cells as specified in §5.
2. Run end-to-end for `MSFT` — all cells must execute cleanly.
3. Run end-to-end for `AAPL` by changing `cfg = AnalysisConfig(symbol="AAPL")` in Cell 4.
4. Verify all charts render, all tables display, and the Phase 7 action label is printed.

**Acceptance criteria:** Notebook runs without errors for both `MSFT` and `AAPL`; Phase 7 cell prints a valid action label.

---

## Appendix A — fmp_cached Models Directory (Verified 2026-03-22)

The following model files were confirmed present in
`openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/`:

```
analyst_estimates.py          balance_sheet.py              balance_sheet_growth.py
base_cached.py                calendar_dividend.py          calendar_earnings.py
calendar_events.py            calendar_ipo.py               calendar_splits.py
cash_flow.py                  cash_flow_growth.py           company_filings.py
company_news.py               crypto_historical.py          crypto_search.py
currency_historical.py        currency_pairs.py             currency_snapshots.py
discovery_filings.py          earnings_call_transcript.py   economic_calendar.py
equity_gainers.py             equity_historical.py          equity_losers.py
equity_most_active.py         equity_ownership.py           equity_peers.py
equity_profile.py             equity_quote.py               equity_screener.py
esg_score.py                  etf_countries.py              etf_equity_exposure.py
etf_holdings.py               etf_info.py                   etf_search.py
etf_sectors.py                executive_compensation.py     financial_ratios.py
forward_ebitda_estimates.py   forward_eps_estimates.py      government_trades.py
historical_dividends.py       historical_employees.py       historical_eps.py
historical_market_cap.py      historical_splits.py          income_statement.py
income_statement_growth.py    index_constituents.py         index_historical.py
insider_trading.py            institutional_ownership.py    key_executives.py
key_metrics.py                market_snapshots.py           nport_disclosure.py
price_performance.py          price_target.py               price_target_consensus.py
revenue_business_line.py      revenue_geographic.py         risk_premium.py
share_statistics.py           treasury_rates.py             world_news.py
yield_curve.py
```

All endpoints used in Phases 1–6 have a corresponding confirmed model file. ✓

---

## Appendix B — Sector ETF Map (from existing notebook Cell 23)

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

This map is the canonical reference for `phase6_peer_relative` sector ETF selection. It handles both FMP-style names (e.g., "Financial Services") and GICS-style names (e.g., "Financial") to avoid KeyError on sector string variations.

---

---

## Appendix C — Extended Fundamental KPI Pack: Phase 2 Additions

> **Analyst perspective:** The original Phase 2 set covers the most visible KPIs. The additions below address gaps that professional buy-side and sell-side analysts consistently use when assessing earnings quality, capital efficiency durability, and structural business health. Each metric is grounded in peer-reviewed academic research or widely-cited practitioner frameworks. All are computable from the four fmp_cached statement endpoints already called in `phase2_fundamentals`.

---

### C.1 DuPont Return on Equity (ROE) Decomposition

**What it is:**
ROE = Net Income / Shareholders' Equity. The 3-factor DuPont decomposition breaks this into:
```
ROE = Net Profit Margin × Asset Turnover × Equity Multiplier
    = (Net Income / Revenue) × (Revenue / Total Assets) × (Total Assets / Equity)
```

**Why it matters — analyst perspective:**
A high ROE that is driven by the equity multiplier (financial leverage) is categorically different — and much riskier — than one driven by margin expansion or asset efficiency. Two companies can both report 20% ROE: one is a high-margin, capital-light software business, the other is a debt-laden retailer. Without DuPont, you cannot distinguish them.

**Academic reference:**
Lev & Thiagarajan (1993) in *The Accounting Review* demonstrated that disaggregated financial fundamentals predict stock returns far better than summary figures. The DuPont framework is taught as the foundational framework in Penman's *Financial Statement Analysis and Security Valuation* (McGraw-Hill, 5th ed., 2013), Ch. 11 — the standard graduate-level text.

**Practical thresholds:**
- ROE > 15% sustained over 5 years: strong capital efficiency
- ROE rising but Equity Multiplier rising faster than margin/turnover: leverage-driven — score penalty
- ROE > 20% with Debt/Equity < 1: genuinely excellent business

**Implementation in `phase2_fundamentals`:**
```python
net_margin   = net_income / revenue                     # from income_df
asset_turn   = revenue / total_assets                   # income_df + balance_df
equity_mult  = total_assets / total_equity              # balance_df
roe_decomp   = net_margin * asset_turn * equity_mult    # should reconcile to net_income/equity
```

**Scoring rule:** Add 0.3 to Capital Efficiency score if ROE > 15% AND equity_multiplier < 2.5 for the latest year (quality ROE, not leverage-inflated).

---

### C.2 Asset Turnover Trend

**What it is:**
`Asset Turnover = Revenue / Average Total Assets`

**Why it matters — analyst perspective:**
Asset turnover measures how efficiently management deploys the asset base to generate revenue. A deteriorating trend — revenue growing slower than the asset base — signals either competitive moat erosion, failed capital allocation (acquisitions that don't earn their cost), or simply that the business is getting less capital-efficient over time.

**Academic reference:**
Fairfield, Whisenant & Yohn (2003) in *The Accounting Review* ("Accrued Earnings and Growth") showed that asset growth not matched by proportional revenue growth predicts future return-on-assets deterioration and lower stock returns. This is closely related to the asset turnover trend signal.

**Practical thresholds:**
- Stable or rising asset turnover over 5 years: positive signal
- Asset turnover declining by > 0.1 per year for 3+ years: investigate capital allocation quality
- Capital-intensive industries (utilities, manufacturing) have structurally lower asset turnover — always compare against sector median, not absolute value

**Implementation:**
```python
asset_turn_series = income_df["revenue"] / balance_df["total_assets"].rolling(2).mean()
asset_turn_5y_trend = asset_turn_series.diff().mean()   # positive = improving
```

---

### C.3 Earnings Quality: Accruals Ratio (Sloan Ratio)

**What it is:**
```
Accruals = Net Income - Operating Cash Flow
Accruals Ratio = Accruals / Average Net Operating Assets
```
where Net Operating Assets = (Total Assets − Cash) − (Total Liabilities − Total Debt)

**Why it matters — analyst perspective:**
This is one of the most powerful and well-validated anomalies in all of empirical finance. When a company's reported net income significantly exceeds its operating cash flow, the "gap" is made up of accounting accruals — entries that recognise revenue or defer costs without actual cash movement. High accruals are a leading indicator of earnings reversals, restatements, and underperformance.

**Academic reference:**
Sloan (1996), "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?" in *The Accounting Review*, Vol. 71, No. 3. This is one of the 20 most-cited papers in accounting research. Sloan demonstrated that portfolios of low-accrual firms consistently outperformed high-accrual firms by 10% per year over his study period. Richardson et al. (2005) in *Journal of Accounting Research* extended this with the Balance Sheet Accruals measure. Both papers are standard reading in CFA Level 2 Financial Statement Analysis.

**Practical thresholds:**
- Accruals Ratio < 0 (cash earnings exceed reported earnings): strong quality signal — "cash is the boss"
- Accruals Ratio 0%–5%: neutral
- Accruals Ratio > 10%: elevated concern; investigate further before proceeding
- Accruals Ratio > 20%: high risk of earnings restatement; automatic score penalty

**Implementation:**
```python
accruals          = income_df["net_income"] - cash_df["operating_cash_flow"]
net_op_assets     = (balance_df["total_assets"] - balance_df["cash_and_equivalents"]) \
                  - (balance_df["total_liabilities"] - balance_df["total_debt"])
avg_net_op_assets = net_op_assets.rolling(2).mean()
accruals_ratio    = accruals / avg_net_op_assets
```

**Scoring rule:** If accruals_ratio (latest year) > 0.10, reduce Phase 2 Cash Flow Quality score by 1 point. If > 0.20, flag as a gate warning — note in `kpi_df` commentary.

---

### C.4 Gross Profit as a Quality Anchor (Gross Profitability Ratio)

**What it is:**
```
Gross Profitability = Gross Profit / Total Assets
```

**Why it matters — analyst perspective:**
Gross profit is the "cleanest" profit measure — it is the hardest line item to manipulate because it is the most proximate to actual product economics. Operating income can be obscured by R&D capitalisation, D&A policy choices, and one-time items. Gross profit strips most of that noise away.

**Academic reference:**
Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium" in *Journal of Financial Economics*, Vol. 108(1). This paper showed that gross profitability scaled by assets is a powerful predictor of stock returns — "as powerful as book-to-market" — and is actually *negatively* correlated with value (P/B), meaning you can use it to screen for quality growth companies that are not necessarily cheap on traditional value metrics. The gross profitability factor is now incorporated into the Fama-French 5-factor model (2015) via the RMW [Robust Minus Weak profitability] factor.

**Practical thresholds:**
- Gross Profitability > 33%: strong quality signal (Novy-Marx threshold for long-side selection)
- Gross Profitability 20–33%: acceptable
- < 20%: low-quality business profile unless capital-intensive industry justifies it
- Trend: rising gross profitability over 5 years is often more important than the absolute level

**Implementation:**
```python
gross_profitability = income_df["gross_profit"] / balance_df["total_assets"]
```

---

### C.5 Share Dilution / Buyback Trend (Change in Shares Outstanding)

**What it is:**
```
Dilution Rate (YoY) = (shares_t - shares_{t-1}) / shares_{t-1}
5Y Net Dilution     = cumulative change over 5 years
```

**Why it matters — analyst perspective:**
EPS can grow even when the underlying business is shrinking if shares are being retired (buybacks). Conversely, EPS growth can be illusory if the share count is rising due to stock-based compensation, secondary offerings, or convertible debt issuance. Tracking the change in shares outstanding separates business growth from financial engineering in both directions.

**Academic reference:**
Loughran & Ritter (1995), "The New Issues Puzzle" in *Journal of Finance* established that companies issuing new equity (dilutors) dramatically underperform over the following 5 years. Ikenberry, Lakonishok & Vermaelen (1995), "Market Underreaction to Open Market Share Repurchases" in *Journal of Financial Economics* showed that buyback announcements predict positive long-term returns. Both findings are part of CFA Institute's *Equity Valuation* curriculum. More recently, Pontiff & Woodgate (2008) in *Journal of Finance* confirmed the share issuance anomaly persists after controlling for other factors.

**Practical thresholds:**
- 5Y shares reduced by > 5%: strong capital allocation signal (buybacks > dilution)
- Shares flat (±2%): neutral
- Shares grown by > 10% over 5 years: investigate — is this acquisition-driven (could be justified) or compensation dilution (generally negative)?
- Shares grown by > 20%: strong negative signal; score penalty on Capital Efficiency

**Implementation:**
```python
shares_series     = income_df["shares_outstanding"]    # or from metrics_df
dilution_5y       = (shares_series.iloc[-1] / shares_series.iloc[0]) - 1
annual_dilution   = shares_series.pct_change()
```

---

### C.6 Operating Leverage

**What it is:**
```
Operating Leverage = % Change in EBIT / % Change in Revenue
                   ≈ (Gross Profit - EBIT) / EBIT   [alternative proxy]
```
Computed as a 5-year average of the year-over-year ratio.

**Why it matters — analyst perspective:**
High operating leverage means a company has a large fixed-cost base. When revenue grows, profits grow much faster (earnings leverage). But when revenue falls, losses also amplify. This is critical context for the investment thesis: a high-operating-leverage company is a cyclical bet on revenue growth, not just a quality business hold. Understanding this prevents being caught in a margin collapse when the macro turns.

**Academic reference:**
Novy-Marx (2011), "Operating Leverage" in *Review of Finance* Vol. 15(1) showed that high-operating-leverage firms have systematically higher expected returns — but also higher systematic risk. The paper formalises the intuition that operating leverage creates "asset betas" even before financial leverage is added. Lev (1974), "On the Association Between Operating Leverage and Risk" in *Journal of Financial and Quantitative Analysis* is the foundational empirical paper on this topic.

**Practical thresholds:**
- Operating Leverage 1.0–1.5: moderate leverage — manageable
- 1.5–2.5: high leverage — strong upside in growth, meaningful downside in contraction
- > 2.5: very high — requires high conviction on revenue growth sustainability before entry
- Combine with revenue CAGR: high operating leverage + declining revenue CAGR = red flag

**Implementation:**
```python
ebit              = income_df["operating_income"]
revenue           = income_df["revenue"]
pct_ebit_chg      = ebit.pct_change()
pct_rev_chg       = revenue.pct_change()
op_leverage_5y    = (pct_ebit_chg / pct_rev_chg).replace([np.inf, -np.inf], np.nan).mean()
```

---

### C.7 Dividend Sustainability (Payout Ratio + FCF Payout)

**What it is:**
```
Earnings Payout Ratio  = Dividends Paid / Net Income
FCF Payout Ratio       = Dividends Paid / Free Cash Flow
```

**Why it matters — analyst perspective:**
For dividend-paying stocks, payout sustainability is a gate-level signal. A company paying out 90% of net income looks generous until FCF drops — then the dividend either gets cut (destroying income investor base and signalling distress) or gets funded by debt (unsustainable). Looking at FCF payout rather than earnings payout gives the real cash-based picture. Non-dividend payers: skip this metric; score as N/A.

**Academic reference:**
Lintner (1956), "Distribution of Incomes of Corporations Among Dividends, Retained Earnings, and Taxes" in *American Economic Review* established that managers smooth dividends and are reluctant to cut — making a payout ratio approaching 100% of earnings a leading indicator of future cut risk. DeAngelo, DeAngelo & Stulz (2006), "Dividend policy and the earned/contributed capital mix" in *Journal of Financial Economics* confirmed that companies with high retained earnings (i.e., established, profitable firms) are the most sustainable dividend payers.

**Practical thresholds:**
- FCF Payout < 50%: very sustainable; room to grow dividend
- FCF Payout 50–75%: sustainable but monitor FCF trend
- FCF Payout > 90%: under stress; any FCF decline threatens dividend
- FCF Payout > 100% (paying dividends from debt): flag as unsustainable; automatic score reduction

**Implementation:**
```python
dividends_paid     = cash_df["dividends_paid"].abs()       # usually reported as negative
fcf                = cash_df["free_cash_flow"]
fcf_payout         = dividends_paid / fcf
earnings_payout    = dividends_paid / income_df["net_income"]
```
If `dividends_paid == 0` for all years, set both to NaN and exclude from scorecard (N/A for non-payers).

---

### C.8 Revenue Quality: SG&A Efficiency Trend

**What it is:**
```
SG&A as % of Revenue = SG&A Expenses / Revenue
```
Tracked as a 5-year time series, not just a point estimate.

**Why it matters — analyst perspective:**
Rising SG&A as a percentage of revenue is one of the earliest warning signals of competitive pressure or management inefficiency. As a business matures and builds brand/distribution advantages, SG&A should fall as a percentage of revenue (operating leverage kicking in). If SG&A is rising, it typically means: (1) the company is spending aggressively to acquire customers (not always bad, but must be validated by rising revenue per customer); or (2) the moat is eroding and the company needs more sales effort to maintain the same revenue base. Warren Buffett's concept of "owner earnings" and his aversion to high-SGA businesses stems directly from this dynamic.

**Academic reference:**
Anderson, Banker & Janakiraman (2003), "Are Selling, General, and Administrative Costs 'Sticky'?" in *The Accounting Review* Vol. 78(1) documented the phenomenon of "cost stickiness" — that SG&A costs rise faster when revenue increases than they fall when revenue decreases. This asymmetry means SG&A ratio trends are informative: when revenue grows but SG&A ratio stays flat or rises, it signals difficulty in converting growth to margin leverage.

**Practical thresholds:**
- SG&A / Revenue declining over 5Y: operating leverage at work — positive signal
- SG&A / Revenue flat: neutral — stable model
- SG&A / Revenue rising > 2 percentage points over 5Y: investigate; validate against revenue per customer growth
- SG&A / Revenue > 35% in a non-growth mature business: structural inefficiency

**Implementation:**
```python
sga_ratio_series  = income_df["selling_general_administrative_expenses"] / income_df["revenue"]
sga_5y_trend      = sga_ratio_series.diff().mean()    # negative = improving (falling SGA%)
```

---

### C.9 Updated Phase 2 Scorecard with New Metrics

The original five-category scorecard is extended as follows. The weights are rebalanced to incorporate the new earnings-quality and capital-efficiency signals:

| Category | Weight | KPIs Included | Why This Weight |
|---|---:|---|---|
| Growth Quality | 20% | Revenue CAGR (5Y), EPS CAGR (5Y), FCF CAGR (5Y) | Reduced from 25% — growth alone is insufficient without quality context |
| Profitability Quality | 20% | Gross Margin trend, Operating Margin trend, Net Margin, Gross Profitability Ratio (Novy-Marx) | Unchanged; gross profitability now explicitly included |
| Capital Efficiency | 20% | ROIC, DuPont ROE decomposition, Asset Turnover trend, Share Dilution 5Y | Increased from 20%; DuPont + dilution now explicit inputs |
| Balance Sheet Safety | 15% | D/E, Interest Coverage, Current Ratio, Net Debt/EBITDA | Reduced slightly; this is a go/no-go check more than a score driver |
| Cash Flow & Earnings Quality | 15% | CFO/NI, FCF Margin, Capex/Revenue, **Accruals Ratio (Sloan)** | Increased from 10% — Sloan ratio is high-signal; earnings quality deserves more weight |
| Structural Efficiency | 10% | Operating Leverage, SG&A Efficiency Trend, Dividend FCF Payout (if applicable) | **New category** — captures business model durability and moat health |

**Revised gate:** Weighted score ≥ 3.5 / 5.0 still applies, but any category scoring ≤ 1.5 triggers a forced "hold/watch" cap on the Phase 7 composite, regardless of aggregate score.

---

### C.10 New `Phase2Result` fields

The following fields are added to the `Phase2Result` dataclass:

```python
@dataclass
class Phase2Result:
    # --- existing fields ---
    income_df: pd.DataFrame
    balance_df: pd.DataFrame
    cash_df: pd.DataFrame
    ratios_df: pd.DataFrame
    kpi_df: pd.DataFrame
    score: float
    gate_passed: bool
    # --- new fields (v1.1) ---
    roe_decomp_df: pd.DataFrame         # 5Y DuPont table: margin, asset_turn, equity_mult, roe
    asset_turn_trend: float             # 5Y average annual change in asset turnover
    accruals_ratio: float               # Sloan ratio for latest year (negative = high quality)
    gross_profitability: float          # Novy-Marx GP/Assets for latest year
    dilution_5y: float                  # cumulative share change over 5 years (negative = buybacks)
    op_leverage_5y: float               # average operating leverage over 5 years
    sga_ratio_trend: float              # 5Y average annual change in SG&A/Revenue (negative = improving)
    fcf_payout_ratio: float             # FCF payout ratio (NaN if non-dividend-payer)
    category_scores: dict[str, float]   # per-category scores for Phase 7 drill-down
```

---

## Appendix D — Extended Technical Timing Stack: Phase 3 Additions

> **Trader/analyst perspective:** The original Phase 3 indicator set (RSI, MACD, ADX, ATR, OBV, SMA50/200, Stochastic, BB Width, Volume Ratio) is a solid foundation. The additions below address timing gaps that consistently cause traders to enter setups that are technically valid but contextually wrong — e.g., entering just before a catalyst event, entering at a major structural resistance level, or misreading volume flow. Each addition is computationally derived from the OHLCV data already fetched, requires no new API call, and is grounded in peer-reviewed or widely-referenced practitioner literature.

---

### D.1 VWAP and Anchored VWAP (Volume-Weighted Average Price)

**What it is:**
```
VWAP_t = Σ(typical_price_i × volume_i) / Σ(volume_i)   for i = 1..t
typical_price = (high + low + close) / 3
```
Anchored VWAP: same formula but reset to a specific anchor date (earnings, breakout, 52-week low).

**Why it matters — trader perspective:**
VWAP is the single most-used institutional execution benchmark. Large funds and algorithms execute orders relative to VWAP to minimise market impact. This means price repeatedly gravitates toward VWAP as a mean-reversion anchor within any trading day or week. When a stock is trading above its cumulative VWAP since a major structural anchor point (e.g., post-earnings breakout), it signals that the average institutional buyer since that point is in profit — the "smart money" position is well. Below VWAP means the average buyer since the anchor is underwater — overhead supply increases.

**Practitioner reference:**
VWAP is covered in detail in *Trading and Exchanges* by Larry Harris (Oxford University Press, 2003), Ch. 19. Anchored VWAP as an entry tool was popularised and systematised by Brian Shannon in *Technical Analysis Using Multiple Timeframes* (2008) and is now standard on Bloomberg and TradingView. The institutional use of VWAP as a benchmark is documented in Almgren & Chriss (2001), "Optimal Execution of Portfolio Transactions" in *Journal of Risk*.

**Implementation for daily data:**
```python
# Rolling VWAP from the start of the technicals window (1-year lookback)
typical_price   = (price_df["high"] + price_df["low"] + price_df["close"]) / 3
cum_tp_vol      = (typical_price * price_df["volume"]).cumsum()
cum_vol         = price_df["volume"].cumsum()
vwap            = cum_tp_vol / cum_vol

# Anchored VWAP from 52-week low date
awk_date        = price_df["close"].idxmin()
mask            = price_df.index >= awk_date
anchored_vwap   = (cum_tp_vol - cum_tp_vol.loc[awk_date]) / \
                  (cum_vol - cum_vol.loc[awk_date])
```

**Timing signal added to `signals` dict:**
```python
signals["above_vwap"] = price_df["close"].iloc[-1] > vwap.iloc[-1]
```

---

### D.2 Ichimoku Cloud (Ichimoku Kinko Hyo)

**What it is:**
Five components, all derived from price alone:
```
Tenkan-sen (Conversion, 9)  = (max_high_9 + min_low_9) / 2
Kijun-sen  (Base, 26)       = (max_high_26 + min_low_26) / 2
Senkou Span A               = (Tenkan + Kijun) / 2   [plotted 26 periods forward]
Senkou Span B               = (max_high_52 + min_low_52) / 2   [plotted 26 periods forward]
Chikou Span                 = close   [plotted 26 periods back]
```
The "cloud" is the area between Senkou Span A and B.

**Why it matters — trader perspective:**
The Ichimoku system is widely used in Asian markets and increasingly by Western institutional desks because it simultaneously provides: trend direction (price vs cloud), momentum (Tenkan vs Kijun cross), support/resistance (cloud boundaries), and confirmation (Chikou vs historical price). A "three-confirmation" entry — price above cloud, Tenkan above Kijun, Chikou above price 26 bars ago — gives one of the lowest false-signal rates of any single indicator system.

**Academic/practitioner reference:**
Goichi Hosoda (pen name Ichimoku Sanjin) published the system in 1969 after 20 years of development. The seminal Western-language reference is Péloille (2017), *Trading with Ichimoku Clouds* (Wiley). An academic validation study is Murphy & Izzeldin (2017), "Forecasting Returns with Ichimoku Cloud Indicators" — presented at the European Financial Management Association conference — which found positive out-of-sample return predictability for Ichimoku trend signals on major indices.

**Implementation:**
```python
def _ichimoku(df):
    high, low, close = df["high"], df["low"], df["close"]
    tenkan  = (high.rolling(9).max()  + low.rolling(9).min())  / 2
    kijun   = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a  = ((tenkan + kijun) / 2).shift(26)
    span_b  = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    return tenkan, kijun, span_a, span_b
```

**Timing signals:**
```python
signals["above_cloud"]     = close.iloc[-1] > max(span_a.iloc[-1], span_b.iloc[-1])
signals["tenkan_kijun_bull"] = tenkan.iloc[-1] > kijun.iloc[-1]
signals["chikou_clear"]    = close.iloc[-26] < close.iloc[-1]  # Chikou above past price
```

---

### D.3 Rate of Change (ROC / Price Momentum)

**What it is:**
```
ROC(n) = (close_today - close_{today-n}) / close_{today-n} × 100
```
Standard periods: ROC(20) for 1-month momentum, ROC(60) for 3-month, ROC(120) for 6-month.

**Why it matters — trader perspective:**
ROC is the most direct measure of price momentum. While RSI measures the internal velocity of recent closes, ROC measures absolute performance over a defined lookback. This matters for two reasons: (1) academic momentum strategies — the most extensively documented return anomaly in finance — are based on 6–12 month price ROC, not oscillators; (2) combining short-term ROC (20D) with medium-term ROC (120D) helps distinguish: healthy pullbacks within a trend (ROC-120 positive but ROC-20 slightly negative) from genuine trend reversals (both negative). The former is an entry opportunity; the latter is a warning.

**Academic reference:**
Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency" in *Journal of Finance* Vol. 48(1) — the foundational momentum paper, showing 10% annualised return from a strategy of buying the top-decile 6-month winners and selling losers. Carhart (1997) added momentum as the 4th factor to the Fama-French model. Asness, Moskowitz & Pedersen (2013), "Value and Momentum Everywhere" in *Journal of Finance* showed the strategy works across 12 asset classes. ROC over 3–12 months is the standard momentum measure used in all these studies.

**Implementation:**
```python
roc_20  = (close / close.shift(20)  - 1) * 100
roc_60  = (close / close.shift(60)  - 1) * 100
roc_120 = (close / close.shift(120) - 1) * 100
```

**Timing signal:**
```python
signals["momentum_positive"] = (roc_60.iloc[-1] > 0) and (roc_120.iloc[-1] > 0)
```

---

### D.4 52-Week High Proximity

**What it is:**
```
Distance_from_52wk_high = (price_52wk_high - close_today) / price_52wk_high
52wk_high_ratio          = close_today / close.rolling(252).max()
```

**Why it matters — trader perspective:**
The 52-week high level acts as a psychological and mechanical resistance barrier for multiple reasons simultaneously: (1) investors who bought near the previous high are "at break-even" and often sell to recover losses; (2) short-sellers who shorted the previous high are forced to cover as price approaches, creating conflicting flows; (3) algorithmic momentum strategies typically trigger buy signals when a new 52-week high is broken with volume. A stock trading within 3–5% of its 52-week high that breaks through with strong volume (Volume Ratio > 1.5×) is in a high-probability continuation setup.

**Academic reference:**
George & Hwang (2004), "The 52-Week High and Momentum Investing" in *Journal of Finance* Vol. 59(5). This paper showed that proximity to the 52-week high is actually a stronger predictor of future returns than the traditional 6-month Jegadeesh-Titman momentum measure, because the 52-week high captures the anchoring and resistance-release dynamics that the raw momentum signal cannot. The paper found that stocks near their 52-week highs earned significantly positive abnormal returns in subsequent months, especially after breaking through the resistance level.

**Implementation:**
```python
high_252        = price_df["close"].rolling(252).max()
dist_from_high  = (high_252 - price_df["close"]) / high_252
near_high       = dist_from_high.iloc[-1] < 0.05    # within 5%
new_high_break  = price_df["close"].iloc[-1] >= high_252.iloc[-2]  # breaking out today
```

**Timing signals:**
```python
signals["near_52wk_high"]  = dist_from_high.iloc[-1] < 0.05
signals["52wk_breakout"]   = new_high_break and (signals.get("volume_ratio_high", False))
```

---

### D.5 Chaikin Money Flow (CMF)

**What it is:**
```
Money Flow Multiplier = ((close - low) - (high - close)) / (high - low)
Money Flow Volume     = Money Flow Multiplier × volume
CMF(21)              = sum(MFV, 21) / sum(volume, 21)
```

**Why it matters — trader perspective:**
CMF measures the degree to which volume is flowing into (positive CMF) versus out of (negative CMF) a stock over a rolling 21-day window. It is distinct from OBV in a critical way: OBV is a cumulative measure that tells you the net direction of volume over time; CMF is a normalised oscillator that tells you the current intensity of buying or selling pressure relative to the day's range. A stock can have rising OBV (technically positive accumulation trend) but negative CMF (selling pressure in the recent 21 days) — this divergence is a yellow flag for short-term entries even when the longer-term trend is bullish.

**Practitioner reference:**
Developed by Marc Chaikin in the 1980s. Covered comprehensively in Achelis (2001), *Technical Analysis from A to Z* (McGraw-Hill, 2nd ed.), and in Murphy (1999), *Technical Analysis of the Financial Markets* (New York Institute of Finance), which is the standard practitioner reference for technical analysis methodology. CMF has been validated in multiple quantitative studies as a useful volume-based confirmation tool, including Granville (1963) whose original volume flow work CMF extended.

**Implementation:**
```python
mf_mult  = ((close - low) - (high - close)) / (high - low + 1e-10)
mf_vol   = mf_mult * volume
cmf_21   = mf_vol.rolling(21).sum() / volume.rolling(21).sum()
```

**Timing signal:**
```python
signals["cmf_positive"] = cmf_21.iloc[-1] > 0
```

---

### D.6 Earnings Date Proximity (Event Risk Guard)

**What it is:**
Binary flag computed from the earnings calendar:
```
days_to_earnings = next_earnings_date - analysis_date
earnings_risk    = (days_to_earnings <= 5) or (days_to_earnings is unknown)
```

**Why it matters — trader perspective:**
This is not a return-predicting signal — it is a *stop signal* for entering new positions. Technical setups are invalidated by earnings because: (1) the stock can gap 10–20% either direction overnight regardless of technical structure; (2) all pre-earnings volume and price action is contaminated by options market activity (IV expansion, delta hedging), which makes MACD, RSI, and OBV signals statistically unreliable; (3) risk/reward calculations based on ATR stops become meaningless when a binary event can bypass any stop level. The professional rule is: if earnings are within 5 trading days, either (a) wait and assess the post-earnings setup, or (b) size down to 25% of normal and treat it as a speculative position.

**Reference:**
Ball & Brown (1968), "An Empirical Evaluation of Accounting Income Numbers" in *Journal of Accounting Research* — foundational paper documenting post-earnings-announcement drift (PEAD) and pre-earnings uncertainty. More practically, Natenberg (1994), *Option Volatility and Pricing* (McGraw-Hill), Ch. 16, covers how IV expansion into earnings distorts delta-based signals. Documented rule in O'Neil (2009), *How to Make Money in Stocks* (McGraw-Hill, 4th ed.): "Never buy a stock the week before it reports earnings unless you are willing to accept the full binary risk."

**Implementation:**
```python
# Requires earnings calendar from fmp_cached (calendar_earnings.py model is confirmed available)
earnings_df      = obb.equity.calendar.earnings(symbol=cfg.symbol, provider="fmp_cached")
next_earnings    = pd.Timestamp(earnings_df["date"].iloc[0]) if not earnings_df.empty else None
days_to_earnings = (next_earnings - pd.Timestamp.today()).days if next_earnings else 999
signals["earnings_safe_window"] = days_to_earnings > 5
```

**Scoring impact:** If `earnings_safe_window == False`, add a mandatory note to `Phase3Result.signals` commentary and reduce the Phase 7 technical timing score by 0.5 points.

---

### D.7 Price Gap Analysis (Unfilled Gaps as Support/Resistance)

**What it is:**
An upward price gap occurs when `open_t > close_{t-1}`. A downward gap when `open_t < close_{t-1}`.
```
gap_size_pct = (open_t - close_{t-1}) / close_{t-1}
significant_gap = abs(gap_size_pct) > 0.01   # 1% threshold
unfilled_up_gaps   = [gap for gap if open > prior_close and min(subsequent lows) > prior_close]
unfilled_down_gaps = [gap for gap if open < prior_close and max(subsequent highs) < prior_close]
```

**Why it matters — trader perspective:**
Unfilled gaps on a price chart act as mechanical support (unfilled upward gaps) or resistance (unfilled downward gaps) because: (1) a large portion of market participants did not get filled at the gap level; (2) algorithms explicitly target gap fill levels as mean-reversion trades; (3) institutional order flow that caused the gap often reinforces price at that level if the catalyst remains intact. As a timing tool: if a stock is consolidating above an unfilled upward gap from earnings or an analyst upgrade, that gap level is a high-quality stop anchor for a new entry.

**Reference:**
Bulkowski (2005), *Encyclopedia of Chart Patterns* (Wiley, 2nd ed.) — the most comprehensive empirical study of chart pattern success rates, including gap analysis. Bulkowski documented statistically that "runaway gaps" in trending stocks are filled less than 40% of the time within 3 months, validating their use as support levels. Also covered in Elder (1993), *Trading for a Living* (Wiley), which is a standard practitioner reference.

**Implementation:**
```python
gaps = pd.DataFrame({
    "gap_pct":  (price_df["open"] / price_df["close"].shift(1)) - 1,
    "date":     price_df.index
})
significant_gaps = gaps[gaps["gap_pct"].abs() > 0.01].copy()

# Find nearest unfilled upward gap below current price (potential support)
up_gaps   = significant_gaps[significant_gaps["gap_pct"] > 0.01]
# For each gap, check if the range was ever re-entered (filled)
# Simplified: check if any subsequent low < gap open level
```

**Timing signal:**
```python
# Presence of unfilled upward gap within 8% below current price = structural support
signals["gap_support_nearby"] = nearest_unfilled_up_gap_distance < 0.08
```

---

### D.8 Multi-Timeframe Trend Confluence (Weekly + Daily)

**What it is:**
Compute a subset of trend indicators on weekly data (derived by resampling the daily OHLCV already fetched) and require that the weekly trend agrees with the daily entry signal before a score is awarded.

```python
weekly_df   = price_df.resample("W").agg({"open":"first","high":"max","low":"min",
                                           "close":"last","volume":"sum"})
weekly_sma20  = weekly_df["close"].rolling(20).mean()   # ≈ 100D SMA
weekly_sma10  = weekly_df["close"].rolling(10).mean()   # ≈ 50D SMA
weekly_trend_bull = weekly_df["close"].iloc[-1] > weekly_sma20.iloc[-1]
```

**Why it matters — trader perspective:**
The single most common cause of failed technical setups is entering a daily chart pattern that is counter to the prevailing weekly trend. A daily chart can produce a bullish MACD cross, rising RSI, and strong volume — yet if the weekly chart shows a stock in a confirmed downtrend (price below 20-week SMA, declining ADX on the weekly), the daily setup will fail at the next level of weekly resistance. Multi-timeframe analysis is the difference between a 65% win-rate system and a 55% win-rate system on identical entry criteria.

**Reference:**
Murphy (1999), *Technical Analysis of the Financial Markets*, Ch. 8: "The case for multiple time-frame analysis." Elder (2002), *Come Into My Trading Room* (Wiley) systematised this as the "Triple Screen" method: filter by weekly trend, time by daily signal, trigger by hourly or shorter-term entry. Stan Weinstein (1988), *Secrets for Profiting in Bull and Bear Markets* (McGraw-Hill) built his entire Stage Analysis methodology around weekly chart primacy over daily entry signals. All three are standard practitioner references.

**Implementation:**
```python
# Resample daily data to weekly — no additional API call required
weekly_df           = price_df.resample("W").agg(...)
weekly_sma20        = weekly_df["close"].rolling(20).mean()
weekly_adx          = _compute_adx(weekly_df, period=14)          # reuse ADX helper
weekly_trend_bull   = (weekly_df["close"].iloc[-1] > weekly_sma20.iloc[-1]) \
                    and (weekly_adx.iloc[-1] > 20)
signals["weekly_trend_bullish"] = weekly_trend_bull
```

**Scoring impact:** If `weekly_trend_bullish == False`, a bullish daily setup scores a maximum of 2/5 on the technical block in Phase 7 — regardless of how many daily conditions are met.

---

### D.9 Fibonacci Retracement Levels as Entry Zones

**What it is:**
Identify the most recent significant swing low and swing high within the 1-year lookback window, then compute:
```
fib_levels = {
    "23.6%": high - 0.236 * (high - low),
    "38.2%": high - 0.382 * (high - low),
    "50.0%": high - 0.500 * (high - low),
    "61.8%": high - 0.618 * (high - low),
    "78.6%": high - 0.786 * (high - low),
}
```

**Why it matters — trader perspective:**
The Fibonacci ratios (derived from the Golden Ratio φ = 1.618) describe natural proportional retracements that recur across financial markets because they reflect the typical behaviour of trend participants partially reversing their gains before continuation. A 38.2% or 61.8% retracement on above-average volume is one of the highest-probability entry setups in technical analysis, used by traders from intraday scalpers to hedge fund managers. The value is not that markets follow Fibonacci because of mathematical necessity — the value is that enough market participants watch and act on these levels that they become self-fulfilling support zones.

**Academic/practitioner reference:**
Carney (2010), *Harmonic Trading, Volume 1* (FT Press) is the primary practitioner reference for Fibonacci-based entry frameworks. From an academic angle, Osler (2000), "Support for Resistance: Technical Analysis and Intraday Exchange Rates" in *Economic Policy Review* (Federal Reserve Bank of New York) provided empirical evidence that round-number and technical levels (including Fibonacci-derived levels) act as support and resistance in FX markets in a statistically significant way. Murphy (1999) Ch. 9 covers retracement levels as standard entry methodology.

**Implementation:**
```python
# Identify swing high and low within the 1-year window
swing_high   = price_df["close"].rolling(252).max().iloc[-1]
swing_low    = price_df["close"].rolling(252).min().iloc[-1]
range_size   = swing_high - swing_low
fib_38       = swing_high - 0.382 * range_size
fib_50       = swing_high - 0.500 * range_size
fib_62       = swing_high - 0.618 * range_size
current      = price_df["close"].iloc[-1]
fib_zone     = (fib_62 * 0.99) <= current <= (fib_38 * 1.01)  # ±1% tolerance
signals["at_fibonacci_support"] = fib_zone
```

---

### D.10 Revised Phase 3 Scoring: Full Condition Set

The original Phase 3 gate (≥ 4 of 6 bullish conditions) is expanded to a **≥ 6 of 11 bullish conditions** gate. The 11 conditions and their sources are:

| # | Signal Key | Indicator | Bullish Condition | Section |
|---|---|---|---|---|
| 1 | `sma_golden_cross` | SMA50 vs SMA200 | SMA50 > SMA200 | Original |
| 2 | `adx_trending` | ADX(14) | ADX ≥ 20 | Original |
| 3 | `rsi_pullback` | RSI(14) | RSI between 40–60 (pullback in uptrend) | Original |
| 4 | `macd_bullish` | MACD(12,26,9) | MACD line > signal line | Original |
| 5 | `obv_rising` | OBV slope (20D) | OBV slope positive | Original |
| 6 | `volume_ratio_normal` | Breakout Vol Ratio | Volume ratio ≤ 2.5 (not parabolic) | Original |
| 7 | `above_vwap` | VWAP (cumulative) | Close > VWAP | New (D.1) |
| 8 | `above_cloud` | Ichimoku | Close > cloud top | New (D.2) |
| 9 | `momentum_positive` | ROC(60), ROC(120) | Both ROC-60 and ROC-120 > 0 | New (D.3) |
| 10 | `cmf_positive` | CMF(21) | CMF > 0 | New (D.5) |
| 11 | `weekly_trend_bullish` | Weekly SMA20 + ADX | Weekly trend confirmed | New (D.8) |

**Hard overrides (any one of these caps the score regardless of bullish count):**
- `earnings_safe_window == False` → cap technical score at 2.5/5
- `weekly_trend_bullish == False` → cap technical score at 2.0/5

**Entry quality gate (conditions 7, 8, 9, and 11 must all be True for a "high-conviction entry" label)**

---

### D.11 New `Phase3Result` fields

```python
@dataclass
class Phase3Result:
    # --- existing fields ---
    price_df: pd.DataFrame          # OHLCV + all indicators
    signals: dict[str, bool]        # all 11 condition bools + new indicators
    bullish_count: int               # count of True signals out of 11
    gate_passed: bool               # bullish_count >= 6
    # --- new fields (v1.1) ---
    vwap: pd.Series                  # cumulative VWAP series
    ichimoku_df: pd.DataFrame        # Tenkan, Kijun, SpanA, SpanB columns
    roc_df: pd.DataFrame             # ROC_20, ROC_60, ROC_120 columns
    cmf: pd.Series                   # CMF(21) series
    weekly_df: pd.DataFrame          # weekly OHLCV resampled from daily
    fib_levels: dict[str, float]     # Fibonacci levels dict (swing high → low)
    nearest_gap_support: float       # price of nearest unfilled upward gap (NaN if none)
    days_to_earnings: int            # 999 if unknown/far out
    entry_quality: str               # "High Conviction" / "Standard" / "Cautious"
    hard_override: str | None        # reason string if a cap is applied, else None
```

---

*Last updated: 2026-03-22 | Owner: Research Engineering / Quantamental Team*
