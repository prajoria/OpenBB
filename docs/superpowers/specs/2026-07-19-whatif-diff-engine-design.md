# Design — What-If Diff Engine (`openbb_portfolio_intel.analytics.whatif`)

- **Date:** 2026-07-19
- **Issue:** [#558 `[portfolio] [P2][Analytics] What-If diff engine (stateless)`](https://github.com/prajoria/OpenBBTechnical/issues/558)
- **Parent epic:** #491 (Portfolio Intelligence Engine)
- **PRD reference:** `docs/Specs/Portfolio-Intelligence-Engine-PRD.md` §15 (Rebalancing & What-If Simulator), §14 (Risk & Attribution Analytics)
- **Branch:** `portfolio`
- **Author:** Claude (openbb-dev-cycle v3, Phase 1)
- **Status:** Draft — awaiting review comments

---

## 1. Purpose

Ship a **stateless pure function** that answers: *"If I apply these candidate trades to my portfolio, what happens to my exposure, concentration, and risk metrics — right now, in memory, without touching any table?"*

This is the analytical counterpart to Paper Trading (§16). Where paper trading persists a shadow book and simulates forward-time fills, What-If is a synchronous, one-shot re-computation of the §14 analytics against a hypothetically-modified position vector.

## 2. Scope

**In scope:**

- One public entry point (`run_whatif`) that accepts current positions + candidate deltas + a bundle of read-only market data, and returns a categorized diff of six analytic surfaces.
- Composition of the existing pure-math substrate (`analytics/xray.py`, `analytics/risk.py`). No new math is introduced by this issue.
- Deterministic behavior — same inputs, same outputs, always. No I/O, no globals, no time.

**Out of scope (deferred to separate issues):**

- Router / REST wiring (`/portfolio/intel/whatif`). Lives in the router-scaffold cluster (#527/#528/#541/#542/#572 shape).
- Cache / provider integration. The router builds `MarketData` from `fmp_cached`; What-If never touches the cache.
- The What-If **widget** (#552) — this issue produces the engine that widget will consume.
- Backtest hand-off (PRD §15 "optional: delegate to openbb-backtest") — that's #573.
- Rebalance *suggestion* engine ("what deltas should I apply to hit target weights?"). Out. §15 is diff-only for this cut.
- Options / futures / multi-leg. Equity + ETF only, matching §16.2 scope.

## 3. Public API

Landing spot: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/analytics/whatif.py`.

```python
from dataclasses import dataclass
from decimal import Decimal
import numpy as np

from openbb_portfolio_intel.analytics.xray import Holding


@dataclass(frozen=True)
class PositionQty:
    """One row of the current book, in signed shares.

    A negative `qty` represents an existing short.
    """
    symbol: str
    qty: Decimal


@dataclass(frozen=True)
class Delta:
    """A candidate trade against the current book.

    `delta_qty` is signed and additive. Buy = positive, sell = negative.
    Close-a-position = ``-current_qty``. Flip-to-short = past zero into
    negative territory.
    """
    symbol: str
    delta_qty: Decimal


@dataclass(frozen=True)
class MarketData:
    """Read-only bundle of everything the analytics need.

    The router (a separate issue) builds this from fmp_cached; What-If
    is agnostic to the source and never fetches.

    Attributes
    ----------
    prices : dict[str, Decimal]
        Last price per symbol (Decimal, currency = book currency).
        Every symbol appearing in `positions` or `deltas` MUST have a
        price or ``run_whatif`` raises ``ValueError``.
    holdings_provider : dict[str, list[Holding]]
        ETF/fund → underlying holdings map for `xray.look_through`.
        Symbols missing here are treated as terminal (single-security).
    attribute_provider : dict[str, Holding]
        Symbol → Holding carrying sector/country attributes for
        `xray.rollup_by`. Missing symbols roll up as "(unknown)".
    returns : np.ndarray of shape (T, N)
        Per-asset return time-series, column-aligned with `returns_symbols`.
    returns_symbols : list[str]
        Column order for `returns` and `cov`. Symbols in the book but
        absent from this list degrade risk/contribution rows to `None`
        with a warning; xray rows are unaffected.
    cov : np.ndarray of shape (N, N)
        Asset covariance matrix, aligned with `returns_symbols`.
    benchmark_returns : np.ndarray of shape (T,)
        Benchmark return series aligned in time with `returns`.
    """
    prices: dict[str, Decimal]
    holdings_provider: dict[str, list[Holding]]
    attribute_provider: dict[str, Holding]
    returns: np.ndarray
    returns_symbols: list[str]
    cov: np.ndarray
    benchmark_returns: np.ndarray


@dataclass(frozen=True)
class MetricDiff:
    """One row in the diff view.

    Shape matches PRD §15: `{metric, current, projected, delta}`. When
    a side is unavailable (e.g. new symbol, symbol missing from returns
    matrix) the missing side is `None` and `delta` is `None`.
    """
    metric: str
    current: float | Decimal | None
    projected: float | Decimal | None
    delta: float | Decimal | None


@dataclass(frozen=True)
class WhatIfDiff:
    """Categorized diff, one flat list per category.

    Each category maps to a widget section. Flat inside categories so
    downstream rendering is a for-loop; categorized across categories so
    the widget doesn't have to parse metric-name prefixes.
    """
    exposure_diffs: list[MetricDiff]        # per-symbol effective weight
    sector_diffs: list[MetricDiff]          # rollup_by("sector")
    country_diffs: list[MetricDiff]         # rollup_by("country")
    concentration_diffs: list[MetricDiff]   # hhi, effective_n, top1/top5/top10
    risk_diffs: list[MetricDiff]            # vol, var_95, cvar_95, beta
    contribution_diffs: list[MetricDiff]    # per-symbol component_var
    warnings: list[str]


def run_whatif(
    positions: list[PositionQty],
    deltas: list[Delta],
    market_data: MarketData,
) -> WhatIfDiff:
    """Compute the What-If diff for `deltas` applied to `positions`.

    Pure function. No I/O. Deterministic.

    Raises
    ------
    ValueError
        If any symbol in `positions` or `deltas` is missing from
        `market_data.prices`. Fail loud — the router should have caught this.
    """
    ...
```

## 4. Design decisions (with rationale)

### 4.1 Qty-in, prices-as-arg (vs. weights-in)

**Chosen: qty-in.** The public shape mirrors the PRD example verbatim (`{symbol: "NVDA", delta_qty: +10}`) and is symmetric with Paper Trading (§16), which also speaks qty. Prices arrive as an explicit `MarketData.prices` dict so the function stays pure and the router controls provenance (matches G9 "reproducible via `fmp_cached`").

Rejected: weights-in (compositional but loses PRD vocabulary, forces every caller to re-implement qty→weight); dual-mode (YAGNI — no caller asks for both).

### 4.2 Close-position and short semantics

`delta_qty` is signed and additive. Resulting position quantities:

| projected_qty | Behavior | Warning emitted? |
|---|---|---|
| `> 0` | Long weight, passes through unchanged | no |
| `== 0` | Symbol **removed** from projected weights (no ghost row) | yes — "`<sym>` delta closes position (qty → 0)" |
| `< 0` | **Short** — negative weight, passed to analytics as-is | yes — "`<sym>` projected qty is negative (short position)" |

Rationale: zero-weight rows would pollute exposure_diffs with a false "unchanged" appearance; explicit removal + warning is more honest. Shorts pass through unchanged because the risk math handles signed weights natively and xray rollups sum abs-weights sanely; there is no reason for What-If to gate short arithmetic.

### 4.3 Metric coverage

| Category | Metrics | Source |
|---|---|---|
| Exposure | per-symbol effective weight (post-look-through) | `xray.look_through` |
| Sector rollup | per-sector effective weight | `xray.rollup_by(attribute="sector")` |
| Country rollup | per-country effective weight | `xray.rollup_by(attribute="country")` |
| Concentration | `hhi`, `effective_n`, `top1`, `top5`, `top10` | `xray.herfindahl_hirschman`, `xray.effective_n`, +local top-K sums |
| Risk | `volatility`, `var_95`, `cvar_95`, `beta` | `risk.portfolio_volatility`, `risk.value_at_risk`, `risk.conditional_var`, `risk.portfolio_beta` |
| Contribution | per-symbol `component_var` | `risk.component_var` |

Dropped for this cut:

- **`marginal_var`** — derivable from `component_var / weight`; a widget can compute it if needed. Adding it here would double the contribution row count for no new information.
- **`mcap_bucket` rollup** — no `attribute_provider` we currently ship carries the field. Synthesizing buckets here would be a new inference; that belongs in a data-layer issue.

### 4.4 Diff output shape (categorized flat)

Categorized (nested-but-shallow), with one flat list of `MetricDiff` per category. Widget-friendly (each category maps to a section); linear inside a category so rendering is a for-loop. Flat-only would force downstream to group by metric-name prefix (fragile). Deeply-nested would over-schema six categories.

### 4.5 Errors and invariants

- **Missing price:** `ValueError` naming the symbol. Router should have caught this; failing loud prevents silent-wrong numbers.
- **Weight normalization:** projected `qty × price` vector is normalized to sum-to-1 within `xray.DEFAULT_WEIGHT_TOLERANCE` before calling look_through. If the projected book is all-zeros (fully liquidated), raise `ValueError` — the analytics have no meaning on an empty portfolio and the widget should catch this upstream anyway.
- **Symbols missing from `returns_symbols`:** risk + contribution rows for those symbols emit `current=None, projected=None, delta=None` with a `warnings` entry naming the symbol. Xray rows are unaffected — an unwrap can still tell you the exposure moved even if we can't price the risk.
- **Empty deltas:** returns a diff where every `delta == 0` (or `None` where sides are `None`). Not an error — a widget may call this to render the "current state" view.
- **Purity:** no I/O, no logging, no `datetime.now()`, no random, no global mutation. Deterministic bytes across runs.

## 5. Testing plan

Landing spot: `openbb_platform/extensions/portfolio_intel/tests/unit/test_whatif.py`.

All pure-function tests, hand-built inputs, no fixtures beyond in-line dicts / numpy arrays. Target ~15–20 tests grouped:

1. **Happy path:** 3-position book + one buy delta → projected weights re-normalize, hhi drops, one sector row shifts by the expected delta.
2. **Empty deltas:** every `delta == 0`; row counts equal to the current-only diff; no warnings.
3. **Close position:** `delta_qty = -current_qty` → symbol absent from `projected` weight rows, `warnings` contains the "closes position" line.
4. **Flip to short:** `delta_qty` past zero → negative projected weight; xray + risk still compute; short warning emitted.
5. **New symbol via delta:** symbol not in `positions` → present only in projected side; `current=None`, `delta=None`-on-current-only rows handled correctly.
6. **Symbol missing from returns matrix:** risk + contribution rows for that symbol are `None`; warning emitted; xray unaffected.
7. **Missing price:** `run_whatif(..., market_data with prices missing "NVDA")` → `ValueError` naming NVDA.
8. **Fully-liquidated projected book:** every symbol closed → `ValueError`.
9. **Weight normalization invariant:** projected weights sum to `Decimal("1")` within tolerance.
10. **HHI monotonicity sanity:** concentrating all weight into one name raises HHI (→ 1.0) and lowers `effective_n` (→ 1.0).
11. **Component-VaR sums-to-VaR sanity:** `sum(contribution_diffs.projected)` equals the projected parametric VaR within float tolerance.
12. **ETF unwrap through look_through:** delta on an ETF affects underlying single-security exposures, not just the ETF row.
13. **Determinism:** two invocations on identical input produce byte-identical `WhatIfDiff` (compared field-by-field on frozen dataclasses).
14. **Missing sector/country attribute:** symbol without `attribute_provider` entry rolls up into `"(unknown)"` bucket in both current and projected — no crash.
15. **Beta with different-length series:** propagates the underlying `ValueError` from `risk.portfolio_beta` — not swallowed.

Runs under `.venv_portfolio` (this session's fork venv with linters preinstalled) and `.venv_win` (the CLAUDE.md-mandated default). All tests deterministic; no `@pytest.mark.integration`.

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/
│   └── analytics/
│       ├── whatif.py              # NEW — this issue
│       ├── xray.py                # existing, unchanged
│       └── risk.py                # existing, unchanged
└── tests/
    └── unit/
        └── test_whatif.py         # NEW — this issue
```

No changes to `pyproject.toml`, no new deps (numpy + scipy already pulled in transitively via `risk.py`).

## 7. Follow-up work (out of scope for #558, filed as separate issues later)

- **#552 What-If diff card widget** — consumes `WhatIfDiff` and renders per-category panels.
- **Router endpoint** — `/portfolio/intel/whatif` in the router-scaffold cluster; builds `MarketData` from `fmp_cached`.
- **#573 backtest hand-off** — the "what would this portfolio have done over the last N years" delegate.
- Suggestion engine — target-weight rebalance solver. Would be its own P3-shaped issue.

## 8. Provenance

- Plan step: 1 of 1 (single-file pure analytics — no decomposition warranted).
- Parent epic: #491 Portfolio Intelligence Engine.
- Sub-issue link: #558 (to be attached to epic #491 via `gh api sub_issues` in Phase 2).
- Design spec: this file.

---

## 9. Review — Analyst & Engineering hats

> Reviewer: added 2026-07-19. Two hats: (A) trading/portfolio-analyst — is the
> math the *right* math for a trader deciding "should I place this trade?"; (B)
> senior software engineer — is the design buildable, correct, and honest about
> its dependencies. Findings are ordered blocking → high → medium → nits.
> Verdict at the bottom.

### 9.0 BLOCKING — the "existing substrate" does not exist

§2 says *"Composition of the existing pure-math substrate (`analytics/xray.py`,
`analytics/risk.py`). **No new math is introduced by this issue.**"* and §6 lists
both files as *"existing, unchanged."* **Neither file exists in the tree.** The
only Python under `openbb_platform/extensions/portfolio_intel/` is
`__init__.py`, `portfolio_intel_router.py`, and the test scaffold —
`analytics/` is not present, and `xray.py` / `risk.py` exist nowhere in the
repo (verified by file search across the whole workspace).

Every function this spec composes (`look_through`, `rollup_by`,
`herfindahl_hirschman`, `effective_n`, `portfolio_volatility`,
`value_at_risk`, `conditional_var`, `portfolio_beta`, `component_var`, plus the
`Holding` dataclass and `DEFAULT_WEIGHT_TOLERANCE` constant) is therefore
**unbuilt**. As written, #558 is not startable — it is blocked on the issues
that ship xray + risk.

**Recommendation:**
1. Downgrade the "no new math / existing, unchanged" language to
   "**depends on** the xray + risk substrate delivered by #\<xray-issue\> and
   #\<risk-issue\>", and wire those as `--blocked-by` edges so `bd ready` /
   the issue tracker reflect reality (per the repo coordination rules).
2. If those substrate issues are **not** yet filed, they must be filed and
   land first — otherwise this design is validating an API contract against a
   module that no one has committed to.
3. Pin the exact function **signatures and return types** of the six imported
   functions in this spec (or link the substrate design), because the whole
   `MetricDiff` shape depends on whether, e.g., `component_var` returns a
   `dict[str, float]` keyed by symbol or a numpy array in `returns_symbols`
   order. Right now that contract is assumed, not stated.

### 9.1 BLOCKING (analyst) — no cash / funding leg makes projected weights misleading

The design applies deltas, recomputes `qty × price`, then **normalizes the
projected vector to sum-to-1** (§4.5). That silently bakes in a *self-financing*
assumption: every buy is implicitly funded by proportionally shrinking every
other weight. That is **not** how a trader reasons about "if I add 10 NVDA."
Three funding models give three *different* projected weight vectors and three
different risk numbers:

| Funding model | What actually happens to weights | Who asks for it |
|---|---|---|
| **Cash-funded** (deploy idle cash) | Book grows; NVDA weight rises, others *dilute* proportionally | "I have cash to put to work" |
| **Funded by a named sell** | NVDA up, the sold name down, rest unchanged | "rotate MSFT → NVDA" |
| **Proportional trim** (the current implicit behavior) | Everything else shaved pro-rata to fund NVDA | rebalancing to a target |

By renormalizing, the engine **hard-codes model #3** and hides it. A trader
staring at "sector tech +4%, cash unchanged" when they intended a *cash-funded*
buy is getting a wrong answer. This is the single biggest analyst gap.

**Recommendation:** add cash to the model. Minimum viable:
- Add `cash: Decimal` to `PositionQty`/book input (or a `MarketData.cash`), and
  treat cash as a real, zero-vol position line.
- A buy debits cash; a sell credits it. Do **not** renormalize away the cash
  line — let the gross book value float. Then weights are `value_i / (Σvalue +
  cash)` and the three funding models fall out naturally from what the caller
  puts in the delta list.
- Emit a warning when a delta would drive cash negative (implicit margin/
  leverage) rather than silently normalizing it away.

If cash is truly deferred, the spec must **state the self-financing assumption
loudly** as a named limitation, because it changes every number in the diff.

### 9.2 HIGH (analyst + correctness) — abs-weight rollups are wrong when shorts are present

§4.2 says shorts "pass through unchanged" and "xray rollups sum abs-weights
sanely." **Abs-weight is analytically wrong for a signed book.** A short SPY
position *reduces* net tech/financials exposure; rolled up as an absolute
weight it *adds* to it. Same defect hits concentration: HHI and `effective_n`
assume weights in `[0,1]` summing to 1. With a short, a weight is negative and
gross exposure can exceed 1 — HHI on signed-normalized weights is undefined and
`effective_n` becomes meaningless.

Since §4.2 explicitly claims to *support* shorts (flip-to-short is a first-class
delta with its own test, #4), this is a correctness bug in the stated design,
not just a scope cut.

**Recommendation:** pick one and write it down:
- **Concentration** (`hhi`, `effective_n`, top-K): compute on **gross weights**
  = `|value_i| / Σ|value|`. Say so explicitly.
- **Sector/country rollups**: sum **signed** net weights so a short correctly
  offsets. Then the "sector tech" row means net exposure, which is what a risk
  manager wants.
- If you don't want to solve signed rollups this cut, then **drop shorts from
  scope** (reject `projected_qty < 0` with a `ValueError`) rather than shipping
  a rollup that's silently wrong. You can't both "support shorts" and "sum
  abs-weights."

### 9.3 HIGH (analyst) — the stated user story asks for metrics the diff omits

PRD §14/§15 and the headline user question (PRD line 65) are explicit:
*"If I add / drop / resize position X, what happens to my **sector weight,
tracking error, and dividend yield** — before I trade?"* The six surfaces here
cover sector weight but **omit tracking error and dividend yield**, and the
risk row drops **Sharpe / Sortino / Max Drawdown / Ulcer** that PRD §14.1 lists.

- **Tracking error / active risk** is the notable miss: `benchmark_returns` is
  *already* in `MarketData`, so the ingredient is on the table and unused. A
  position resize's effect on active risk is exactly the "before I trade"
  question. Recommend adding `tracking_error` (and optionally active weight vs
  benchmark) to `risk_diffs`.
- **Sharpe / Sortino / MaxDD / Ulcer** genuinely can't be projected from a
  qty-delta against a *static covariance* — they need a full projected return
  *series*, which reweighting a fixed cov matrix cannot produce. That's a
  legitimate reason to defer them, **but the spec should say that** rather than
  silently dropping them, so a reviewer doesn't think they were forgotten.
- **Dividend yield** is a simple weighted sum if a per-symbol yield is
  available; if no provider carries it, note that (same pattern as the
  `mcap_bucket` drop in §4.3).

### 9.4 HIGH (methodology) — static covariance is a first-order approximation; label it

Projecting VaR/vol/beta by reweighting a **fixed historical covariance** is
standard and fine as a *first-order* preview, but it systematically
**understates** the risk of adding a concentrated or regime-sensitive position
(historical cov doesn't know the correlation you're about to create, and
mean-reverts through crises). A trader who over-trusts a `var_95 delta = -1.2%`
on a big concentrating buy is being misled.

**Recommendation:** one sentence in §4.3 / §4.5 stating the projection is a
static-cov first-order estimate and does not re-estimate forward covariance.
Cheap to write, saves a user from a false-precision mistake.

### 9.5 HIGH (engineering) — Decimal/float mixing makes `delta` ill-defined

`MetricDiff` fields are `float | Decimal | None`. Prices/weights are `Decimal`;
risk/xray outputs from numpy are `float`. The diff computes
`delta = projected - current`. `Decimal("0.4") - 0.4` raises `TypeError`, and
even where it doesn't, mixing the two per-row is a landmine.

**Recommendation:** state a single coercion rule — e.g. **all diff arithmetic
is done in `float`**, `Decimal` inputs are coerced at the boundary, and
`MetricDiff` carries `float | None` only (keep `Decimal` for the *input* money
types, not the output diff). Or, if you want exactness on weights, keep the
whole diff in `Decimal` and coerce numpy floats once. Either is fine; the
current union type with no rule is not.

### 9.6 MEDIUM (correctness) — component-VaR "sums to VaR" only holds for parametric

Test 11 asserts `sum(component_var) == projected VaR`. That Euler/homogeneity
identity holds for **parametric (Gaussian) VaR**, *not* for **historical VaR**
(non-differentiable at the quantile — components don't sum to total). PRD §14.1
says VaR is "historical + parametric." If `risk.value_at_risk` /
`risk.component_var` default to historical, test 11 will fail or force a wrong
implementation.

**Recommendation:** state explicitly that the What-If risk row uses **parametric**
VaR/CVaR (the only variant with a clean contribution decomposition), and make
test 11 assert the identity only for that variant.

### 9.7 MEDIUM (engineering) — "byte-identical determinism" is too strong

Test 13 asserts two runs produce **byte-identical** `WhatIfDiff`. Floating-point
results from numpy/BLAS are **not** guaranteed byte-identical across thread
counts, CPU, or BLAS backend (reduction order varies). "Same inputs → same
outputs" is true up to fp tolerance, not to the bit.

**Recommendation:** change the determinism guarantee (and test 13) to
tolerance-based equality (`math.isclose` / `np.allclose` field-by-field). Keep
the *purity* guarantee (no I/O, no globals, no clock) as-is — that part is
correct and worth keeping.

### 9.8 MEDIUM (engineering) — validate covariance/returns alignment and shape

`MarketData` carries `returns (T,N)`, `cov (N,N)`, `returns_symbols (len N)`,
`benchmark_returns (T,)` — but nothing in the contract asserts `N` and `T`
actually agree across all four, or that `cov` is symmetric PSD. A mis-aligned
or non-PSD cov yields **negative variance / negative component-VaR** silently.

**Recommendation:** add cheap boundary asserts in `run_whatif` — `cov.shape ==
(len(returns_symbols),)*2`, `returns.shape[1] == len(returns_symbols)`,
`benchmark_returns.shape[0] == returns.shape[0]`, and either assert PSD or
document that the caller guarantees it. Fail loud, consistent with the
missing-price philosophy in §4.5.

### 9.9 MEDIUM — module taxonomy drifts from the PRD

The PRD's proposed layout (Specs PRD §"file layout") names
`analytics/decomposition.py` (VaR/CVaR/beta), `whatif/simulator.py`, and
`drawdown.py`. This spec uses `analytics/risk.py`, `analytics/xray.py`, and
`analytics/whatif.py`. Divergent module paths will bite the router-scaffold
cluster (#527/#528/#541/#542/#572), which imports by path.

**Recommendation:** reconcile the taxonomy once, in one place, before code
lands — either update the PRD or add a note here explaining the deliberate
rename, so downstream issues import from a single agreed tree.

### 9.10 LOW / nits

- **Transaction cost / slippage**: even a stateless preview benefits from an
  optional "estimated cost = bps × traded notional" line so the trader sees
  *net* benefit of the rebalance. Fine to defer, but call it out as an explicit
  future line item (it's the difference between "should I trade" and "what's my
  new exposure").
- **Currency**: `prices` are "book currency" — multi-currency books (foreign
  ADRs, FX hedges) are silently assumed single-currency. State it as a scope
  limitation.
- **New-symbol `delta = None`** (§ MetricDiff): for a brand-new position,
  `current=None` so `delta=None`. Arguably the trader wants `delta = projected`
  ("this is entirely new exposure"). Minor product call — just confirm it's
  intentional.
- **Empty-portfolio `ValueError`**: reasonable, but a fully-liquidated *what-if*
  ("what if I sell everything to cash?") is a legitimate question a trader asks.
  Consider returning an all-cash diff instead of raising, once cash exists
  (ties to 9.1).

### 9.11 Verdict

The **software shape is clean** — stateless pure function, frozen dataclasses,
categorized-flat output, honest error philosophy, and a genuinely good test
list. The engineering nits (9.5–9.8) are all small and mechanical.

But two things must change before this is buildable and trustworthy:

1. **9.0 — fix the dependency lie.** The substrate doesn't exist; sequence and
   link the xray/risk issues first. This is a hard blocker, not a wording nit.
2. **9.1 + 9.2 — fix the analyst model.** Renormalize-to-1 with no cash line
   silently picks one funding model and mislabels the others, and abs-weight
   rollups are wrong for the shorts the spec claims to support. Either model
   cash + signed rollups properly, or explicitly narrow scope (no shorts,
   self-financing-only, stated loudly). As written, the projected weights — the
   headline output — can be quietly wrong for the most common trader intent
   ("deploy cash into NVDA").

Everything else (9.3–9.10) is "state the assumption and move on." Recommend a
**revise-and-re-review** rather than approve-as-is, with 9.0/9.1/9.2 as the
gating items.
