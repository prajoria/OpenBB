# Key-Stats Provider Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add only provider-backed Shares Float and Forward P/E rows to the live key-stats tier and explicitly disposition unsupported fields.

**Architecture:** Reuse the existing key-stats best-effort enrichment seam. Fetch `fmp_cached` share statistics and annual forward EPS, pass their first rows to the pure shaper, and omit values whenever source data is absent or invalid.

**Tech Stack:** Python 3.10+, OpenBB provider commands, FastAPI test client, pytest.

## Global Constraints

- Never fabricate a key-stat value.
- Short Interest and Insider Ownership remain omitted because current `fmp_cached` capabilities do not supply them.
- Forward P/E is current live price divided by a positive annual consensus EPS `mean`.
- Do not modify execution, configuration, snapshot, viewer frontend, or risk files.

---

### Task 1: Source-backed key-stat shaping

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/tier_calls.py`
- Test: `openbb_platform/extensions/portfolio_intel/tests/unit/test_tier_calls.py`

**Interfaces:**
- Produces: `_fetch_share_statistics(symbol: str) -> dict`
- Produces: `_fetch_forward_eps(symbol: str) -> dict`
- Extends: `_shape_key_stats(..., share_statistics: dict | None = None, forward_eps: dict | None = None)`

- [ ] **Step 1: Write failing tests**

Test that real source-shaped inputs emit `Shares Float` and `Forward P/E`, that
missing or non-positive EPS omits Forward P/E, and that Short Interest and
Insider Ownership remain absent.

- [ ] **Step 2: Verify RED**

Run the focused key-stats tests and expect failure because the shaper does not
accept or emit the new sourced fields.

- [ ] **Step 3: Implement minimal shaping and fetch helpers**

Use `equity.ownership.share_statistics(..., provider="fmp_cached")` and
`equity.estimates.forward_eps(..., provider="fmp_cached",
fiscal_period="annual", limit=1)`. Route both through `_safe_first_row`.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and expect all key-stats unit tests to pass.

### Task 2: Real capability verification and disposition

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_pi_terminal_f1_batch_a.py`
- GitHub: issue #1959

**Interfaces:**
- Consumes: the extended live key-stats tier
- Produces: issue comment recording supported and unsupported provider fields

- [ ] **Step 1: Update regression expectations**

Keep endpoint-stub guards against fabricated Short Interest and Insider
Ownership. Replace stale no-source assumptions for Shares Float and Forward P/E
with live-tier tests backed by explicit provider-shaped fixtures.

- [ ] **Step 2: Run targeted tests and diagnostics**

Run both key-stats test modules plus targeted Ruff checks.

- [ ] **Step 3: Drive the real provider path**

Fetch AAPL share statistics, annual forward EPS, and quote from `fmp_cached`;
assert the live key-stats tier includes Shares Float and mathematically derived
Forward P/E. Save sanitized output to `.dev-cycle/verify-phase6-1959.log`.

- [ ] **Step 4: Record unsupported-field evidence**

Comment on #1959 that `EquityShortInterest` is absent from the provider registry
and share statistics returns no insider-ownership field. State explicitly that
both remain omitted.

- [ ] **Step 5: Review and ship**

Run code/security review, commit with `Refs #1959`, push, open a PR to
`portfolio` with a standalone `Closes #1959.` line, converge, merge, verify the
issue is closed, and clean the branch/worktree.
