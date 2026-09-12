# Look-Through Normalization Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce normalized recursive ETF holdings so concentration output cannot be silently under-scaled.

**Architecture:** Validate and normalize each non-empty child holdings vector lazily when the shared analytics look-through reaches it. Preserve top-level validation and empty-provider fallback behavior.

**Tech Stack:** Python 3.12, `Decimal`, dataclasses, pytest, OpenBB portfolio-intel extension.

## Global Constraints

- Preserve public response schemas and valid single-security behavior.
- Accept underlying provider rounding drift up to exactly `0.01`.
- Reject non-finite, negative, zero-total, and materially under/over-normalized child vectors.
- Normalize accepted child vectors before recursive multiplication.

---

### Task 1: Enforce the recursive normalization contract

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/analytics/xray.py`
- Test: `openbb_platform/extensions/portfolio_intel/tests/unit/test_xray.py`

**Interfaces:**
- Consumes: `look_through(portfolio, holdings_provider, max_depth, weight_tolerance)`.
- Produces: normalized effective weights or a parent-specific `ValueError`.

- [x] **Step 1: Add failing malformed-vector tests**

```python
def test_look_through_rejects_materially_unnormalized_underlyings() -> None:
    provider = {
        "SPY": [
            Holding("AAPL", Decimal("0.006")),
            Holding("MSFT", Decimal("0.004")),
        ]
    }
    with pytest.raises(ValueError, match="SPY.*sum to 1.0"):
        look_through([Holding("SPY", Decimal("1"))], provider)
```

Also parameterize negative, `NaN`, and infinite child weights.

- [x] **Step 2: Run focused tests and observe RED**

Run:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\portfolio_intel\tests\unit\test_xray.py -k "underlying" -v
```

Expected: new cases fail because child vectors are not validated.

- [x] **Step 3: Add minimal validation and normalization**

Add a `0.01` child-vector tolerance and a private helper that returns immutable replacement
`Holding` rows with `weight / total`. Call it lazily from recursive look-through and cache the
normalized vector by parent symbol.

- [x] **Step 4: Verify GREEN and preserved semantics**

Run:

```powershell
.venv_portfolio\Scripts\python.exe -m pytest openbb_platform\extensions\portfolio_intel\tests\unit\test_xray.py openbb_platform\extensions\portfolio_intel\tests\unit\test_xray_router.py openbb_platform\extensions\portfolio_intel\tests\unit\test_risk.py openbb_platform\extensions\portfolio_intel\tests\unit\test_risk_router.py openbb_platform\extensions\portfolio_intel\tests\unit\test_whatif.py -m "not integration" -q
```

Expected: all selected tests pass.

- [x] **Step 5: Run diagnostics and real-path verification**

Run Ruff on both modified Python files. Then call the live SPY X-Ray and concentration routes;
record that effective weights sum to one and all concentration invariants pass in
`.dev-cycle/verify-phase6.log`.

- [x] **Step 6: Commit and update PR #2074**

Commit with `Refs #2077`, push the existing branch, and add a standalone `Closes #2077` line
to the PR body.
