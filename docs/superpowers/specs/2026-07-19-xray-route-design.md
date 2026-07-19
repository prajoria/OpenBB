# Design — /portfolio/intel/xray route (`openbb_portfolio_intel.routers.xray_router`)

- **Date:** 2026-07-19
- **Issue:** [#541 `[portfolio] [P1][App] /portfolio/intel/xray route + portfolio_basket join`](https://github.com/prajoria/OpenBB/issues/541)
- **Parent epic:** #491 Portfolio Intelligence Engine
- **Branch:** `feat/pi-app/xray-route-gh-541`
- **Base:** `portfolio` @ f08436c25 (post-#512)
- **Status:** Draft

---

## 1. Purpose

Expose the shipped X-Ray substrate (`analytics/xray.py`: `look_through` + `rollup_by` + `herfindahl_hirschman` + `effective_n`) as an OpenBB Platform route under `obb.portfolio.intel.xray.*`. This is the first user-visible surface of the Portfolio Intelligence Engine and unblocks Lane D (X-Ray widgets #529 #530).

## 2. Scope

**In scope:**

- Sub-router at the pre-reserved path `openbb_portfolio_intel.routers.xray_router` (already listed in `portfolio_intel_router._PLANNED_SUBROUTERS`).
- One command: `obb.portfolio.intel.xray.look_through(basket=..., provider="fmp_cached")` — takes an **inline basket** (list of `{symbol, weight}` positions), fetches ETF holdings for any ETF via `obb.etf.holdings`, recursively unwraps, returns per-underlying effective weights + sector/country/HHI rollups.
- Response wrapped in `OBBject[XRayLookThroughResult]` — a Pydantic model with `effective`, `sector_rollup`, `country_rollup`, `concentration` (hhi + effective_n + top-K), `unresolved`, `warnings`.
- Provider-agnostic at the route surface (accepts `provider=`), but only `fmp_cached` is a first-class citizen for the fork.
- Fully unit-tested with mocked `obb.etf.holdings` + one live `@pytest.mark.integration` smoke.

**Out of scope (scope-cuts, filed as follow-ups):**

- **Saved `portfolio_basket` DB table join.** The PRD §11 mention of a saved-basket lookup requires a SQL layer (basket-CRUD endpoints, auth model) that doesn't exist yet on `portfolio`. The route accepts an **inline** basket only for this cut; a follow-up will add `basket_id: str | None = None` when the table lands.
- **Risk metrics on the unwrapped basket** — belongs in `/portfolio/intel/risk` (#528), separate route, same lane. This route ships exposure/concentration only.
- **Widget wire-up** — Lane D consumes this route; widget PRs are #529 #530.
- **`obb.portfolio.intel.risk` / `.concentration` / `.events` / `.smart_money`** — separate reserved subrouter modules per `_PLANNED_SUBROUTERS`. Cadence: one route per PR (mirrors #558 What-If shipping cadence).

## 3. Public API

Landing spot: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/routers/xray_router.py` (new file), plus new `openbb_portfolio_intel/routers/__init__.py` (empty package init).

```python
from decimal import Decimal
from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router
from pydantic import BaseModel, Field

router = Router(
    prefix="/xray",
    description="Recursively unwrap an ETF-containing portfolio to underlying holdings.",
)


class BasketPosition(BaseModel):
    """One row of an input portfolio basket.

    Weight is a fraction of 1.0 (not a percentage). Callers with quantity
    * price data must normalize before passing in — the router does not
    infer market values. Follow-up #NNN will accept a `qty + price` shape
    once the `portfolio_basket` SQL table lands.
    """

    symbol: str = Field(description="Ticker (equity or ETF).")
    weight: Decimal = Field(description="Fraction of total portfolio (0 < w <= 1).")


class ConcentrationSummary(BaseModel):
    hhi: float = Field(description="Herfindahl-Hirschman index on effective weights [0, 1].")
    effective_n: float = Field(description="Reciprocal HHI — effective number of holdings.")
    top1: float = Field(description="Largest single effective exposure.")
    top5: float = Field(description="Sum of top-5 effective exposures.")
    top10: float = Field(description="Sum of top-10 effective exposures.")


class XRayLookThroughResult(BaseModel):
    """Nested response shape for the /xray/look_through route."""

    effective: dict[str, float] = Field(description="symbol -> effective weight")
    sector_rollup: dict[str, float] = Field(description="sector -> summed weight")
    country_rollup: dict[str, float] = Field(description="country -> summed weight")
    concentration: ConcentrationSummary
    unresolved: list[str] = Field(description="ETFs whose holdings were not resolvable.")
    depth_reached: int = Field(description="Deepest recursion level hit.")
    warnings: list[str] = Field(default_factory=list)


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Unwrap a 60/40 SPY-plus-AAPL basket to underlyings.",
            code=[
                "from decimal import Decimal",
                "positions = [",
                '    {"symbol": "SPY", "weight": Decimal("0.6")},',
                '    {"symbol": "AAPL", "weight": Decimal("0.4")},',
                "]",
                'result = obb.portfolio.intel.xray.look_through(basket=positions, provider="fmp_cached").results',
                "print(sorted(result.effective.items(), key=lambda kv: -kv[1])[:5])",
            ],
        ),
    ],
)
def look_through(
    basket: list[BasketPosition],
    provider: str | None = None,
) -> OBBject[XRayLookThroughResult]:
    """Recursively unwrap ETFs in `basket` to underlying single-security exposures.

    Fetches ETF holdings via ``obb.etf.holdings(symbol, provider=<provider>)``
    for every symbol in the basket whose holdings are queryable, then calls
    :func:`openbb_portfolio_intel.analytics.xray.look_through` to unwrap.
    Non-ETFs (single securities) pass through unchanged.

    Returns the full ``XRayLookThroughResult`` — effective per-symbol
    weights after unwrap, sector + country rollups, concentration
    (HHI + effective-N + top-K), plus depth/unresolved/warnings.
    """
    ...
```

## 4. Design decisions (with rationale)

### 4.1 Why an inline basket, not a saved-basket lookup

The PRD envisions a `portfolio_basket` SQL table so widgets can render "my portfolio's X-Ray" without re-uploading positions. That table doesn't exist yet. Two ways to unblock:

- **A — Ship inline-only now.** Users pass `basket=[...]` explicitly. Simple, no auth model, no SQL migration. Downstream widgets pass a session-stored basket into the route until the table lands.
- **B — Wait for the basket table.** Blocks #529 #530 widgets on unknown-timeline design work.

**Chosen: A.** Widget cost of accepting an inline basket is a session-store call, ~5 minutes. Basket-table cost is a multi-issue design (CRUD, auth, migration, tests). The `basket_id: str | None = None` parameter is reserved for a future PR to add without breaking the current shape.

### 4.2 Why per-position `weight: Decimal`, not `qty + price`

`analytics/xray.look_through` accepts `list[Holding]` where each has `Decimal` weight summing to ~1.0 (validated by `_validate_weights`). Route surface mirrors that contract 1:1. A `qty + price` surface would push value → weight conversion into the route, duplicating what the (future) basket-table lookup will do. Ship the minimum-viable shape; add `qty` support once the paper-trading account model lands.

### 4.3 Why the response wraps a Pydantic model, not raw dicts

- `OBBject[dict]` works but loses schema in `/docs`.
- A typed `XRayLookThroughResult` gives the widget layer autocomplete + OpenAPI schema.
- Nested `ConcentrationSummary` (rather than flat) matches PRD §11's "Concentration ribbon widget" grouping.

### 4.4 Fetcher seam: `obb.etf.holdings` at the route layer, not xray substrate

`analytics/xray.look_through(portfolio, holdings_provider)` accepts `holdings_provider: dict[str, list[Holding]]` — an already-populated map. The route is responsible for **building that map** by calling `obb.etf.holdings(symbol, provider=provider)` for every basket symbol that returns non-empty. This keeps `xray.py` pure (no I/O) and puts provider-orchestration in the route (where credentials, rate limits, and provider selection belong).

Concrete flow:
1. Basket in.
2. For each unique symbol, call `obb.etf.holdings(symbol=s, provider=provider)`. If it returns ≥1 row, that symbol is an ETF and its holdings become the `holdings_provider[s]` entry. Empty result → treat as terminal single-security.
3. Convert basket → `list[Holding]` (Decimal weights).
4. Call `xray.look_through(portfolio=..., holdings_provider=map)` → `LookThroughResult`.
5. Roll up via `xray.rollup_by(effective, attribute_provider, "sector")` and `"country"`. Attribute provider is built by looking up each underlying's holdings row (`sector` and `country` come from the ETF holdings — for non-ETF singletons the caller can extend later via a symbol-lookup endpoint; for this cut, singletons roll up as `"(unknown)"`).
6. Compute `hhi`, `effective_n`, and top-K sums locally (same logic as the What-If engine's `_fill_concentration_diffs`).
7. Assemble the `XRayLookThroughResult`.

### 4.5 Errors and invariants

- **Empty basket:** `raise ValueError("basket must contain at least one position")`.
- **Weights don't sum to ~1.0** (within `xray.DEFAULT_WEIGHT_TOLERANCE = 0.0001`): raise; do not silently renormalize (matches What-If's fail-loud philosophy).
- **Any weight < 0:** raise (shorts deferred to same follow-up as #904).
- **Any symbol missing from basket that also can't resolve via `obb.etf.holdings`:** treated as terminal single-security (no error). Emit warning if the symbol was intended as an ETF but returned 0 rows.
- **Provider failure** (`obb.etf.holdings` raises for one symbol): log warning, treat that symbol as unresolved (kept at face value in effective weights, tagged in `unresolved`). Do not fail the whole request — matches the multi-tier philosophy of the ETF holdings fetcher.
- **Depth cap:** pass `max_depth=xray.DEFAULT_MAX_DEPTH` (5) through — a fund-of-fund-of-fund pathology is a warning not an error.

### 4.6 Sector/country provenance

The `holdings_provider` sub-rows carry `sector` + `country` per underlying via `EtfHoldingsData` fields. Build `attribute_provider: dict[symbol -> Holding]` from **all resolved sub-rows across all fetched ETFs** — first-write-wins if a symbol appears in multiple ETFs (they should agree). For terminal single-securities (non-ETF basket entries), no provider row exists; roll up as `"(unknown)"`. Log a warning listing how many symbols fell into `"(unknown)"` so the caller knows.

## 5. Testing plan

Landing spot: `openbb_platform/extensions/portfolio_intel/tests/unit/test_xray_router.py`.

~10-12 tests, all offline (mocked `obb.etf.holdings`), plus 1 `@pytest.mark.integration` smoke.

Categories:

1. **Happy path — single ETF basket.** 100% SPY basket → mocked SPY holdings (3 dummy underlyings summing to 1.0) → effective weights match; sector rollup non-empty; hhi + effective_n sensible.
2. **Mixed basket (ETF + single stock).** 60% SPY + 40% AAPL → AAPL passes through terminal; SPY unwraps; effective sums to ~1.0.
3. **Nested ETF (ETF holding another ETF).** 100% "FOF" → FOF holds 100% SPY → SPY holds 3 stocks → depth_reached = 2; effective is the 3 stocks.
4. **Unknown symbol** (obb.etf.holdings returns []): treated as terminal, no error, no warning (that's the normal case for equity singletons).
5. **Explicit-ETF fetch fails** (obb.etf.holdings raises): symbol enters `unresolved`, effective retains face weight, warning emitted.
6. **Empty basket** → ValueError.
7. **Weights don't sum to 1.0** → ValueError (propagated from `xray.look_through`).
8. **Negative weight** → ValueError.
9. **Sector rollup captures unknowns.** Single-stock basket with no attribute provider → `"(unknown)"` bucket carries the weight.
10. **Concentration invariants.** 100% one-stock basket → hhi = 1.0, effective_n = 1.0, top1 = 1.0.
11. **Response envelope shape.** `OBBject[XRayLookThroughResult]` has `.results.effective` populated (not `.results.results`).
12. **Determinism.** Same input twice → equal outputs (tolerance-based).
13. **Integration smoke** (`@pytest.mark.integration`): `obb.portfolio.intel.xray.look_through(basket=[{"symbol":"SPY","weight":1.0}], provider="fmp_cached")` returns >100 underlyings.

R7.11: for the reject-negative-weight and reject-empty-basket tests, revert the guard temporarily and confirm the test fails.

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/
│   └── routers/
│       ├── __init__.py                # NEW — empty package init
│       └── xray_router.py             # NEW — this issue (~200 lines)
└── tests/
    └── unit/
        └── test_xray_router.py        # NEW — ~200 lines

# The scaffold parent router already lists this subrouter in
# _PLANNED_SUBROUTERS, so no edit to portfolio_intel_router.py needed.
```

No changes to `pyproject.toml`. No new deps.

## 7. Follow-up work (out of scope, filed separately later)

- **#NNN** — `portfolio_basket` SQL table + CRUD endpoints (unblocks `basket_id` param + widget session storage)
- **#NNN** — Attribute provider extension for non-ETF single securities (currently roll up as `(unknown)`)
- **#528** — `/risk` + `/concentration` routes (siblings)
- **#529 #530** — X-Ray widgets consuming this route

## 8. Provenance

- Design spec: this file.
- Substrate: xray.py + risk.py shipped via #526 #535 #536 #539 #540.
- Runtime unblock: `obb.etf.holdings` shipped via #512 (PR #908).
- Sub-issue link: #541 already listed in _PLANNED_SUBROUTERS, so no parent-router edit needed.

## 9. Verdict

Ship §3 (single `look_through` command) + §5 (12 unit + 1 integration test). Cadence matches #558 (single-PR, single-command, small scope, follow-ups tracked). Every downstream widget in Lane D depends on this route existing; it should ship next.
