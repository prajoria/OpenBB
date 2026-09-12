# TechTrade Indicator Regressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore extended-selector fallback behavior and Ichimoku panel/vote output while preserving classic/extended parity contracts.

**Architecture:** Normalize the two supported `pandas-ta-classic` Ichimoku result shapes at the indicator boundary and keep the existing calculation logic unchanged. Preserve `PanelConfig` through every technical adapter fallback so caller intent survives dependency absence and runtime failures.

**Tech Stack:** Python 3.12, pandas, pandas-ta-classic, Pydantic models, pytest, Ruff.

## Global Constraints

- Classic requests remain byte-compatible with the existing classic panel.
- Extended requests retain every classic key/value and may add extended keys.
- Every technical fallback preserves the caller's requested `panel_config`.
- The default ship allowlist continues to exclude `ichimoku_cloud`.
- No dependency version pin or new dependency is introduced.

---

### Task 1: Preserve Extended Selection Through Technical Fallbacks

**Files:**
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_extended_pass_through.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_technical.py`

**Interfaces:**
- Consumes: `technical_panel(..., panel_config: PanelConfig | None, obb_loader: Callable[[], object] | None) -> IndicatorPanel`
- Produces: fallback behavior equivalent to `build_indicator_panel(..., panel_config=panel_config)`

- [ ] **Step 1: Strengthen the unavailable-extension fallback assertion**

Replace obsolete full equality with classic-subset/value parity and require an
extended-only Aroon key:

```python
assert set(classic.trend).issubset(extended.trend)
for key, value in classic.trend.items():
    assert extended.trend[key] == value
assert "aroon_osc" in extended.trend
assert classic.momentum == extended.momentum
assert classic.volatility == extended.volatility
assert classic.volume == extended.volume
```

- [ ] **Step 2: Add a failing technical-exception fallback test**

Inject an `obb_loader` whose `technical.macd` raises `RuntimeError`, request
`PANEL_EXTENDED`, and compare the result to direct
`build_indicator_panel(..., panel_config=PANEL_EXTENDED)`. Require
`"aroon_osc" in actual.trend` so dropping the selector cannot pass.

- [ ] **Step 3: Run the focused fallback tests and confirm RED**

Run:

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest openbb_platform\extensions\techtrade\tests\unit\test_extended_pass_through.py -q
```

Expected: the new exception-path assertion fails because `technical_panel` calls
`build_indicator_panel` without `panel_config` in its exception handler.

- [ ] **Step 4: Forward the selector in the exception fallback**

Change the final fallback to:

```python
return build_indicator_panel(
    symbol,
    as_of,
    ohlcv_rows,
    config=config,
    panel_config=panel_config,
)
```

- [ ] **Step 5: Re-run the fallback module**

Run the Step 3 command. Expected: all tests pass.

### Task 2: Normalize Ichimoku Dependency Results

**Files:**
- Modify: `openbb_platform/extensions/techtrade/tests/unit/test_extended_trend_family.py`
- Modify: `openbb_platform/extensions/techtrade/openbb_techtrade/engine/indicators_ext.py`

**Interfaces:**
- Consumes: `df.ta.ichimoku(...)` returning a current-value frame or `(current, projection)`
- Produces: `_ichimoku_current_frame(result: object) -> object | None`

- [ ] **Step 1: Add result-shape contract tests**

Use a small fake frame-like object to assert:

```python
assert _ichimoku_current_frame(frame) is frame
assert _ichimoku_current_frame((frame, projection)) is frame
assert _ichimoku_current_frame(None) is None
assert _ichimoku_current_frame(("invalid", projection)) is None
```

- [ ] **Step 2: Run the shape tests and confirm RED**

Run:

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest openbb_platform\extensions\techtrade\tests\unit\test_extended_trend_family.py -q
```

Expected: failure because `_ichimoku_current_frame` is not defined, alongside the
existing missing-key regressions.

- [ ] **Step 3: Implement minimal result normalization**

Add:

```python
def _ichimoku_current_frame(result: object) -> object | None:
    candidate = result[0] if isinstance(result, tuple) and result else result
    if candidate is None or not hasattr(candidate, "columns") or not hasattr(candidate, "iloc"):
        return None
    return candidate
```

Use this helper instead of accepting tuples only.

- [ ] **Step 4: Re-run the trend-family module**

Run the Step 2 command. Expected: all tests pass, including raw keys, confirmed
keys, whipsaw neutralization, default exclusion, and explicit vote opt-in.

### Task 3: Regression, Diagnostics, and Real-Path Verification

**Files:**
- Create (ignored evidence): `.dev-cycle/verify-phase6.log`

**Interfaces:**
- Consumes: public `build_indicator_panel` and `technical_panel`
- Produces: evidence that classic parity, extended additions, Ichimoku keys, and exception fallback work together

- [ ] **Step 1: Run targeted tests**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest openbb_platform\extensions\techtrade\tests\unit\test_extended_pass_through.py openbb_platform\extensions\techtrade\tests\unit\test_extended_trend_family.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run broader non-integration TechTrade tests**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m pytest openbb_platform\extensions\techtrade\tests -m "not integration" -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run changed-file diagnostics**

```powershell
& '..\..\OpenBB\.venv_portfolio\Scripts\python.exe' -m ruff check openbb_platform\extensions\techtrade\openbb_techtrade\engine\indicators_ext.py openbb_platform\extensions\techtrade\openbb_techtrade\engine\indicators_technical.py openbb_platform\extensions\techtrade\tests\unit\test_extended_pass_through.py openbb_platform\extensions\techtrade\tests\unit\test_extended_trend_family.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Drive the real path and capture evidence**

Build a 200-bar deterministic OHLCV series, call classic and extended builders,
force the technical adapter's exception path with a failing loader, assert shared
key/value parity and extended-only keys, and write concise results to
`.dev-cycle/verify-phase6.log`.

- [ ] **Step 5: Review, commit, push, and open the PR**

Run simplification, code, and security reviews; resolve all findings; commit with
the required co-author trailer; push `fix/pi-techtrade-indicators-gh-2078`; and
open a PR to `portfolio` with:

```text
Closes #2078
```

