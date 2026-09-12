# SPY Concentration Invariants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace market-data-sensitive SPY HHI bounds with durable assertions that reject malformed concentration output.

**Architecture:** Keep the live route invocation unchanged and validate mathematical invariants of `ConcentrationSummary`. Modify tests only; production modules and dependencies remain untouched.

**Tech Stack:** Python, pytest, OpenBB `OBBject`, `math.isfinite`.

## Global Constraints

- Production code must remain unchanged.
- The test must continue to exercise live `fmp_cached` SPY holdings.
- Assertions must reject non-finite, out-of-domain, internally inconsistent, empty, or misordered concentration metrics.

---

### Task 1: Replace the brittle live assertion

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_risk_router.py:1-10,280-294`
- Test: `openbb_platform/extensions/portfolio_intel/tests/unit/test_risk_router.py`

**Interfaces:**
- Consumes: `ConcentrationSummary` fields `hhi`, `effective_n`, `top1`, `top5`, and `top10`.
- Produces: A live integration assertion contract independent of SPY's current constituent weights.

- [x] **Step 1: Write the durable assertions**

```python
from math import isfinite, sqrt

values = (res.hhi, res.effective_n, res.top1, res.top5, res.top10)
assert all(isfinite(value) for value in values)
assert 0.0 < res.hhi <= 1.0
assert res.effective_n == pytest.approx(1.0 / res.hhi)
assert res.effective_n > 3.0
assert 0.0 < res.top1 <= res.top5 <= res.top10 <= 1.0
assert res.hhi <= res.top1 <= sqrt(res.hhi) + 1e-12
assert res.top1 < res.top5
```

- [x] **Step 2: Verify RED against malformed concentration output**

Run a focused Python/pytest harness that substitutes malformed metrics such as `hhi=float("nan")`
and confirms the new invariant block raises `AssertionError`.

Expected: malformed metrics are rejected.

- [x] **Step 3: Run the live integration test**

Run:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\portfolio_intel\tests\unit\test_risk_router.py::test_live_concentration_spy_via_obb -v
```

Expected: `1 passed`.

- [x] **Step 4: Run targeted risk tests**

Run:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\portfolio_intel\tests\unit\test_risk.py openbb_platform\extensions\portfolio_intel\tests\unit\test_risk_router.py -m "not integration" -v
```

Expected: all selected tests pass.

- [x] **Step 5: Run diagnostics and real-path harness**

Run Ruff on the modified test and call the live route from a Python harness. Capture the route
metrics and invariant results in `.dev-cycle/verify-phase6.log`.

- [x] **Step 6: Commit**

```text
test(portfolio): make SPY concentration check resilient

Closes #2027

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```
