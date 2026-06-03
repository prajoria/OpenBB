# Detailed Implementation Spec — Sprint 1 (Days 1–2)

> **Date:** 2026-05-31
> **Scope:** Highest-impact items that can be completed in 1–2 working days
> **Branch:** `openbb_learning`

---

## Preamble: Revised Gap Assessment

After reading `stock_analysis.py` in full (~2,100 lines), the **module** is substantially more complete than the notebook-focused strategy doc indicates. Here is the corrected status:

| Phase | Module Status | Real Remaining Gaps |
|---|---|---|
| P1 | ✅ ~95% | Gate is basic (just checks sector exists); no summary card DF |
| P2 | ✅ ~95% | 5Y CAGR ✓, Sloan ✓, DuPont ✓, interest coverage ✓, scoring ✓, gate ✓ |
| P3 | ✅ ~90% | 11-condition setup ✓, VWAP ✓, Ichimoku ✓, ROC ✓, CMF ✓, Fib ✓, weekly ✓, earnings guard ✓. Missing: **Stochastic oscillator**, **Bollinger Band width** in signals |
| P4 | ✅ ~95% | DCF ✓, MOS ✓, sensitivity ✓, reverse-DCF ✓, ROIC-WACC ✓, EV/EBIT ✓, P/GP ✓, valuation-technical gate ✓. Missing: **5Y historical multiple trends** |
| P5 | ✅ ~95% | Sharpe/Sortino/Calmar/GtP/Kelly/regime beta/position sizing/stress/portfolio fit — all done |
| P6 | ✅ ~90% | Sortino/Beta per peer ✓, IR ✓, 5-block scoring ✓, fundamental overlay ✓. Missing: **rolling 3M relative strength** |
| P7 | ✅ ~85% | Composite ✓, action label ✓, staged entry ✓, ATR stop ✓, time stop ✓, monitoring triggers ✓, handoff ✓. Missing: **monitoring cadence template**, **report export** |
| Cross-cutting | ⚠️ | No gate enforcement in `run_full_analysis`; no E2E notebook; no report generation |

**Conclusion:** The module is 85–95% complete per phase. The highest-value remaining work is:
1. Gate enforcement in `run_full_analysis()`
2. E2E analysis notebook
3. Missing indicators (Stochastic, BB width, historical multiples, rolling RS)
4. Report generation (Jinja2 → HTML/PDF)

---

## Issue 1: Add `enforce_gates` to `run_full_analysis()`

**Type:** Feature | **Priority:** P1 | **Estimate:** 2 hours

### Problem
`run_full_analysis()` runs all 7 phases unconditionally. Per the master plan, each phase has a `gate_passed` boolean, but failures don't stop the pipeline. Users get misleading composite scores for stocks that should have been rejected at Phase 2 or Phase 4.

### Spec

1. Add `enforce_gates: bool = False` field to `AnalysisConfig`
2. In `run_full_analysis()`, after each phase call, check `result.gate_passed`
3. If `enforce_gates=True` and gate fails:
   - Log a warning with the phase name and `gate_notes`
   - Set all subsequent phase results to `None`
   - Return the partial dict with a `"stopped_at"` key indicating which phase failed
   - Set `p7` to a synthetic `Phase7Result` with `action_label="Gate Failed"` and `composite_score=0.0`
4. If `enforce_gates=False` (default): current behavior — run everything, log warnings only

### Files
- `Analysis/stock_analysis.py`: Modify `AnalysisConfig`, modify `run_full_analysis()`

### Tests
- Unit test: mock phase functions, verify pipeline stops at correct phase
- Unit test: verify `enforce_gates=False` runs all phases regardless
- Unit test: verify partial result dict has correct keys and `stopped_at`

### Acceptance Criteria
- `run_full_analysis(AnalysisConfig(symbol="X", enforce_gates=True))` stops after a failing gate
- `run_full_analysis(AnalysisConfig(symbol="X"))` continues to work as before (backward compatible)
- All existing 56 unit tests pass unchanged

---

## Issue 2: Add Stochastic Oscillator and BB Width to Phase 3 signals

**Type:** Feature | **Priority:** P2 | **Estimate:** 1.5 hours

### Problem
`_compute_technicals()` calculates RSI, MACD, ADX, ATR, OBV, SMA 50/200, VWAP, Ichimoku, ROC, CMF, and volume ratio — but **Stochastic %K/%D** and **Bollinger Band width** are not computed or included in the 11-condition signal dict. The Phase 3 spec (v1.1) lists them.

### Spec

1. In `_compute_technicals()`, add:
   - **Stochastic(14,3,3):** `%K = 100 * (close - low_14) / (high_14 - low_14)`, smoothed 3-period; `%D = SMA(%K, 3)`
   - **Bollinger Band Width:** `bb_width = (upper - lower) / middle` where bands are SMA(20) ± 2σ. Already partially computed (BB columns may exist); ensure `bb_width` column is added.

2. In `phase3_technicals()`, add two more entries to the `signals` dict (total becomes 13):
   - `"stochastic_bullish"`: `%K > %D and %K < 80` (not overbought, trending up)
   - `"bb_squeeze_breakout"`: `bb_width < bb_width.rolling(120).quantile(0.20)` AND `close > upper_band` (squeeze then breakout)

3. Update gate threshold: keep at ≥6 but now out of 13 conditions (more lenient than 6/11)

### Files
- `Analysis/stock_analysis.py`: `_compute_technicals()`, `phase3_technicals()`

### Tests
- Unit test: verify Stochastic columns exist in output `price_df`
- Unit test: verify BB width column exists
- Unit test: verify `signals` dict has 13 keys
- Integration test: run on MSFT, verify no crash

### Acceptance Criteria
- `price_df` has `stoch_k`, `stoch_d`, `bb_width` columns
- `signals` dict has 13 boolean entries
- All existing Phase 3 tests pass

---

## Issue 3: Add 5-Year Historical Multiple Trends to Phase 4

**Type:** Feature | **Priority:** P2 | **Estimate:** 1.5 hours

### Problem
Phase 4 computes current multiples (P/E, EV/EBITDA, etc.) but has no historical context. A P/E of 25 is meaningless without knowing the company's 5Y median P/E. The spec calls for a historical multiples trend DataFrame.

### Spec

1. In `phase4_valuation()`, after computing current multiples:
   - Build `historical_multiples_df` from `ratios_df` (which already has 5 years of annual data from Phase 2)
   - Extract per-year: P/E, EV/EBITDA, P/S, P/FCF (from existing `ratios_df` columns)
   - Compute 5Y median for each multiple
   - Add `vs_5y_median` column: `current / median - 1` (positive = above median = relatively expensive)

2. Add `historical_multiples_df` and `multiples_vs_median` dict to `Phase4Result`

3. The valuation verdict can optionally incorporate: "3+ multiples below 5Y median" as additional undervaluation signal

### Files
- `Analysis/stock_analysis.py`: `Phase4Result` dataclass, `phase4_valuation()`

### Tests
- Unit test: verify `historical_multiples_df` has expected columns and 5 rows
- Unit test: verify `vs_5y_median` dict has correct keys
- Integration test: run on MSFT, verify reasonable medians

### Acceptance Criteria
- `p4.historical_multiples_df` is a non-empty DataFrame with year-indexed multiples
- `p4.multiples_vs_median` is a dict like `{"pe": -0.12, "ev_ebitda": 0.05, ...}`
- All existing Phase 4 tests pass

---

## Issue 4: Create End-to-End Analysis Notebook

**Type:** Feature | **Priority:** P1 | **Estimate:** 3 hours

### Problem
There is no notebook that calls the `stock_analysis.py` module functions. The existing notebook (`00. single_stock_analysis_playbook_template.ipynb`) duplicates logic inline rather than importing from the module. Users cannot run a clean E2E analysis.

### Spec

Create `Analysis/01. phased_stock_analysis.ipynb` with these cells:

1. **Config cell:** `symbol = "MSFT"` (change this one cell to analyze any stock)
2. **Imports + setup:** `from stock_analysis import AnalysisConfig, run_full_analysis, ...`
3. **Per-phase cells (7 groups, one per phase):**
   - Call `phase_N(cfg, ...)`
   - Print gate result: ✅ PASS or ❌ FAIL with `gate_notes`
   - Display key DataFrames with `display(df.style...)`
   - Phase-specific visualizations:
     - P2: Revenue/EPS/FCF bar chart (5Y)
     - P3: Price chart with SMA 50/200 + Bollinger Bands overlay
     - P4: Sensitivity heatmap (3×3 DCF grid)
     - P5: Risk metrics radar chart
     - P6: Peer comparison bar chart (Sharpe)
     - P7: Score breakdown horizontal bar chart
4. **Summary cell:** Print final action label, composite score, and entry plan
5. **All charts use matplotlib** (already available in .venv_win)

### Files
- `Analysis/01. phased_stock_analysis.ipynb` (new)

### Tests
- Manual: run the notebook with `symbol = "MSFT"` and verify no errors
- Verify all 7 phases produce output cells

### Acceptance Criteria
- Notebook runs top-to-bottom for MSFT without errors
- Each phase shows gate status and key outputs
- At least 5 matplotlib charts are rendered
- Changing `symbol` to "AAPL" and re-running works

---

## Issue 5: Add Rolling 3-Month Relative Strength to Phase 6

**Type:** Feature | **Priority:** P3 | **Estimate:** 1 hour

### Problem
Phase 6 computes point-in-time annualized metrics but lacks **rolling relative strength** to show how the stock's performance vs peers has trended over the past 3 months. This is a key momentum signal for relative analysis.

### Spec

1. In `phase6_peer_relative()`, after building `relative_table`:
   - Compute rolling 63-day (3-month) cumulative return for each symbol in `returns_df`
   - Rank the target symbol within the universe at the latest date
   - Add `rolling_3m_return` column to `relative_table`
   - Add `rolling_3m_rank` (percentile, 0-100) to `Phase6Result`

2. Incorporate into `_score_relative()` block 1 (return rank): blend annualized and rolling 3M equally

### Files
- `Analysis/stock_analysis.py`: `phase6_peer_relative()`, `_score_relative()`, `Phase6Result`

### Tests
- Unit test: verify `rolling_3m_return` column in `relative_table`
- Unit test: verify `rolling_3m_rank` is a float 0-100

### Acceptance Criteria
- `p6.relative_table` has `rolling_3m_return` column
- `p6.rolling_3m_rank` is populated
- Existing Phase 6 tests pass

---

## Issue 6: Run existing test suite — baseline validation

**Type:** Chore | **Priority:** P0 | **Estimate:** 30 min

### Problem
The repo has been idle for 2+ months. Before making any changes, we need to confirm the existing 118 tests (56 unit + 62 integration) still pass in `.venv_win`.

### Spec

1. Run unit tests: `.venv_win\Scripts\python.exe -m pytest Analysis/tests/test_stock_analysis.py -m "not integration" -v`
2. Record pass/fail count
3. If any failures, document them as blockers for other issues

### Acceptance Criteria
- All 56 unit tests pass (or failures are documented as separate bugs)
- Test output saved/reported

---

## Execution Plan

| Order | Issue | Est. | Dependency |
|---|---|---|---|
| 1 | #6 Baseline test validation | 30 min | None |
| 2 | #1 Gate enforcement | 2 hr | #6 passing |
| 3 | #2 Stochastic + BB width | 1.5 hr | #6 passing |
| 4 | #3 Historical multiples | 1.5 hr | #6 passing |
| 5 | #5 Rolling relative strength | 1 hr | #6 passing |
| 6 | #4 E2E notebook | 3 hr | #1–#5 merged |

**Total:** ~9.5 hours across 2 days
