# Design — /portfolio_intel/smart_money route

- **Date:** 2026-07-20
- **Issue:** [#527](https://github.com/prajoria/OpenBB/issues/527)
- **Parent epic:** #491
- **Branch:** `feat/pi-app/smart-money-route-gh-527`
- **Base:** `portfolio` @ 37c6dced8 (post-#542)
- **Status:** Draft (pattern-mirror of #541/#528/#542)

---

## 1. Purpose

Expose the smart-money aggregation substrate (`analytics.events_smartmoney.aggregate_smart_money` + `top_conviction`) as `obb.portfolio_intel.smart_money.rollup(basket, window_days, provider)`. Unblocks Lane D's Smart-Money ribbon widget (#532).

## 2. Scope

**In scope:**

- Sub-router at pre-reserved `openbb_portfolio_intel.routers.smart_money_router`.
- One command: `obb.portfolio_intel.smart_money.rollup(basket, window_days=90, top_n=10, provider=None)` → per-symbol scores + top-conviction list.
- Fetches 3 signal sources for basket symbols in the last `window_days`:
  - Insider transactions (`obb.equity.ownership.insider_trading`)
  - 13F institutional holdings changes (`obb.equity.ownership.institutional`)
  - Senate disclosures (`obb.regulators.sec.form_13f` or equivalent — check what exists)
- Response model `SmartMoneyRollupResult` (in `openbb_portfolio_intel.models`).
- Per-source fetch failure = warning + partial result (same posture as #542).

**Out of scope:**

- **Weighting normalization** — accept substrate default (per-source magnitude passthrough); custom per-source weights are P3.
- **Historical time-series** — this is a point-in-time rollup for a lookback window.
- **Non-US sources** — SEC-only for now.

## 3. Public API

New models in `models.py`:

```python
class SmartMoneyScoreItem(BaseModel):
    symbol: str
    composite: float  # signed conviction (Decimal → float at boundary)
    by_source: dict[str, float]  # e.g. {"insider": 0.4, "form_13f": -0.2}
    signal_count: int


class SmartMoneyRollupResult(BaseModel):
    by_symbol: dict[str, SmartMoneyScoreItem]  # every scored symbol
    top_conviction: list[SmartMoneyScoreItem]  # top-N by |composite|
    warnings: list[str]
```

Command:

```python
def rollup(
    basket: list[dict],
    window_days: int = 90,
    top_n: int = 10,
    provider: str | None = None,
) -> OBBject:
```

## 4. Testing

`test_smart_money_router.py` — 8 tests + 1 integration:
- Happy path (mocked signals across 3 sources)
- Portfolio-scoped filter
- Empty basket / negative window / negative top_n → ValueError
- Per-source fetch failure → warning + partial
- Deterministic
- Envelope shape

## 5. Provider fetch — TBD detail

Actual OpenBB endpoints for insider/13F/senate vary; the router will try what's available on `obb.equity.ownership.*` at runtime and fall through gracefully on `AttributeError`. Follow-up P2 issue can pin the exact endpoints once the widget layer's needs are clearer.
