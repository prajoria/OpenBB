# Design — /portfolio_intel/risk + /concentration routes

- **Date:** 2026-07-19
- **Issue:** [#528](https://github.com/prajoria/OpenBB/issues/528)
- **Parent epic:** #491
- **Branch:** `feat/pi-app/risk-concentration-routes-gh-528`
- **Base:** `portfolio` @ 6f3a0c553 (post-#541)
- **Status:** Draft (pattern-mirror of #541 xray-route design)

---

## 1. Purpose

Expose portfolio-level risk metrics (volatility, parametric VaR/CVaR, beta) and concentration (HHI + effective-N + top-K) as OpenBB Platform routes under `obb.portfolio_intel.risk.*`. Unblocks Lane D's Risk Dashboard widget (#533) and Concentration ribbon (part of #530).

## 2. Scope

**In scope:**

- Sub-router at pre-reserved `openbb_portfolio_intel.routers.risk_router`.
- **Two commands** under one file:
  - `obb.portfolio_intel.risk.metrics(basket, returns_source, benchmark_returns, provider=None)` → vol / var_95 / cvar_95 / beta.
  - `obb.portfolio_intel.risk.concentration(basket, provider=None)` → hhi / effective_n / top1/5/10 (post-unwrap effective weights).
- Response models in `openbb_portfolio_intel.models` (top-level file, per #541-established quirk). Reuses `ConcentrationSummary`; adds `RiskMetricsResult`.
- Route surface: `basket: list[dict]`, returns bare `OBBject` (unparameterized). Runtime shape typed inside.

**Out of scope (scope-cuts, filed as follow-ups):**

- **Historical returns fetching from `obb.equity.price.historical`.** For this cut, `/risk/metrics` accepts a **pre-computed** `returns_source` dict (`{symbol: list[float]}`) plus `benchmark_returns: list[float]`. Follow-up will add an auto-fetch mode that pulls historical price series from `fmp_cached`. Reason: the widget layer will pre-compute + cache returns; auto-fetch inside a route would trigger heavy I/O per request.
- **No shorts** — negative basket weights raise ValueError (mirrors #904).
- **Confidence level fixed at 0.95.** Follow-up will parameterize once the widget has a UI for it.
- **No historical VaR/CVaR variant.** The route uses parametric only — matches the What-If engine's rationale (§9.6 in #558 design): parametric admits the Euler component-sum identity, historical does not. Callers who need historical can call `analytics.risk.value_at_risk` directly with a return series.
- **No dividend adjustment.** Weights are treated as pre-adjusted.
- **No saved portfolio_basket table lookup** — inline basket only (same as #541).

## 3. Public API

Landing spot: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/routers/risk_router.py`.

New models added to `openbb_portfolio_intel/models.py`:

```python
class RiskMetricsResult(BaseModel):
    """/risk/metrics response — parametric portfolio-level risk metrics."""

    volatility: float | None = Field(description="Portfolio std-dev (per-period, same time-scale as input returns).")
    var_95: float | None = Field(description="Parametric VaR at 95% (loss magnitude, positive).")
    cvar_95: float | None = Field(description="Parametric CVaR at 95% (expected shortfall, positive).")
    beta: float | None = Field(description="Portfolio beta vs benchmark_returns.")
    warnings: list[str] = Field(default_factory=list)
```

`ConcentrationSummary` reused from #541 (already in `models.py`).

```python
@router.command(methods=["POST"], examples=[...])
def metrics(
    basket: list[dict],
    returns_source: dict,          # {symbol: list[float]}
    benchmark_returns: list[float],
    provider: str | None = None,
) -> OBBject:
    """Portfolio-level parametric risk metrics."""
    ...


@router.command(methods=["POST"], examples=[...])
def concentration(
    basket: list[dict],
    provider: str | None = None,
) -> OBBject:
    """Post-unwrap concentration metrics (HHI + effective-N + top-K)."""
    ...
```

## 4. Design decisions

### 4.1 Two commands, one router file

Same pattern as backtest's `run_router.py` shipping `run` + `sweep` + `tear_sheet` in one file. Groups related surface (both operate on the same basket input); keeps `_PLANNED_SUBROUTERS` from expanding to a route-per-file explosion.

### 4.2 `returns_source` as a pre-computed dict (not fetched inline)

The whatif engine's `MarketData` pattern (§4.1 of #558) already established this: analytics substrate takes an already-populated `returns` matrix, the caller builds it. Same posture here: the route doesn't fetch historical prices — the widget (with cache) or a downstream router does. Follow-up #NNN will add an auto-fetch overload.

### 4.3 Parametric VaR/CVaR (not historical)

Same rationale as #558's What-If engine — the Euler decomposition + downstream contribution split only works for parametric. Historical variant belongs at `obb.portfolio_intel.risk.metrics_historical(returns_source=...)` as a separate follow-up if a caller needs it.

### 4.4 Response envelope

`OBBject` (unparameterized) per #541-quirk. Runtime `.results` is `RiskMetricsResult` or `ConcentrationSummary` depending on the command.

### 4.5 `concentration` command reuses xray infrastructure

`/concentration` is essentially the "just the concentration part" of `/xray/look_through`. Rather than duplicate the ETF-unwrap machinery, the command calls the same `_fetch_holdings` + `_build_holdings_provider` helpers exposed from `xray_router` (public alias: extract them into a shared `_shared.py` helper, or expose via a `xray_router._fetch_holdings` module attr).

**Chosen:** import `_fetch_holdings` + `_build_holdings_provider` from `openbb_portfolio_intel.routers.xray_router` as module-level references (Python module reuse; not "exported API"). Alternative is a `routers/_shared.py` helper — cleaner but adds a file just for two functions.

### 4.6 Weight validation

Same `_validate_basket` from xray_router (rejects empty + negative). Also imports.

## 5. Testing plan

Landing spot: `openbb_platform/extensions/portfolio_intel/tests/unit/test_risk_router.py`.

~12-14 tests, all offline. Categories:

**`/risk/metrics`:**
1. Happy path — 3-asset basket, hand-built returns dict + benchmark → assert vol > 0, var_95 > 0, cvar_95 > var_95, beta close to 1 when portfolio ≈ benchmark.
2. Basket symbol missing from returns_source → warning + None on affected fields.
3. Empty basket → ValueError.
4. Negative weight → ValueError.
5. Weights don't sum to 1 → ValueError (validated at boundary, not silently normalized).
6. Length mismatch (benchmark_returns shorter than returns_source values) → propagated ValueError.
7. Single-asset basket → vol matches the asset's own stddev.
8. Determinism — same inputs → same outputs.

**`/risk/concentration`:**
9. Single ETF unwrap → concentration reflects post-unwrap effective weights.
10. Mixed basket → HHI + effective-N sensible.
11. Empty basket → ValueError.
12. Single-holding basket → hhi = 1.0, effective_n = 1.0.
13. Determinism.

**Integration smoke:**
14. `@pytest.mark.integration` — live `obb.portfolio_intel.risk.concentration(basket=[SPY 100%], provider="fmp_cached")` — assert HHI in [0.1, 0.5].

R7.11: empty-basket + negative-weight guards get reverse-verified.

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/
│   ├── models.py                        # EXTEND — add RiskMetricsResult
│   └── routers/
│       └── risk_router.py               # NEW — this issue (~200 lines)
└── tests/
    └── unit/
        └── test_risk_router.py          # NEW — ~250 lines
```

## 7. Follow-up work

- **#NNN** — Auto-fetch `returns_source` from `obb.equity.price.historical(symbol, ...)` inside the route (cache-first).
- **#NNN** — Historical VaR variant as a separate command.
- **#NNN** — Parameterize `confidence` (currently 0.95).

## 8. Verdict

Ship §3 as one PR mirroring #541's cadence. Well-established pattern; expected 1-2 CI iterations (codespell/pylint pragmas discovered by #541 already applied).
