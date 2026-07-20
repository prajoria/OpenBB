# Design — What-If short-position support with signed rollups (#904)

- **Date:** 2026-07-20
- **Issue:** [#904](https://github.com/prajoria/OpenBB/issues/904)
- **Parent:** #558 (initial What-If diff engine, PR #905) + #903 (cash line, PR #926)
- **Branch:** `feat/pi-analytics/whatif-shorts-gh-904`
- **Base:** `portfolio` (post-#903 merge)
- **Status:** Draft

---

## 1. Purpose

The initial ship (#558) rejects any delta that drives a projected qty
negative — it raises `ValueError` with a pointer to this issue. That
was the correct scope cut: sector/country rollups on unsigned weights
would silently mis-report a short SPY as "adds to tech exposure" when
it should *reduce* tech; concentration on signed weights is
analytically undefined.

This PR extends the engine with proper signed-book support.

## 2. Scope

**In scope:**
- Allow projected qty < 0 (a short position).
- Rollups (sector, country, exposure) go on **signed net weights** —
  a short SPY *reduces* the projected tech exposure.
- Concentration (HHI, effective-N) goes on **gross weights**
  (`|value_i| / Σ|value|`) — a $1M short and a $1M long each carry
  $1M of directional risk, so the concentration reflects that.
- Extend `xray.herfindahl_hirschman` + `effective_n` with a
  `gross: bool = False` toggle — additive, backward-compat.
- Route What-If concentration diffs through the gross path when any
  projected qty is negative; keep the net path otherwise (avoids
  gratuitous churn in the shipped calculations for long-only books).
- Component-VaR: the parametric identity holds on signed weights out
  of the box — need only a test-level verification that no branch
  applies `abs()` en route.
- New warnings: any short position on the projected side attaches a
  `_SHORTS_ENABLED_WARNING` so downstream consumers know the diff was
  computed on a signed book.

**Out of scope (documented, deferred):**
- **Short-borrow cost.** A real short costs a per-annum borrow fee
  (~0.3% for large caps, up to 100%+ for hard-to-borrow). Not modeled;
  What-If diff is exposure/concentration, not P&L. Filed as future
  follow-up when Paper Trading tackles fill/carry (#546-#548 already
  cover the paper-side accounting).
- **Margin requirement checks.** A short position needs collateral
  (Reg-T 150%, plus haircut per broker). Modeled downstream by Paper
  Trading; What-If treats projected cash independent of margin.
- **Options / derivatives.** Delta from a synthetic (e.g. long put +
  short call = synthetic short) is out of scope; deltas are on
  underlying equities only. If a widget consumer needs synthetic
  shorts, they compute delta and pass it as a Delta row.
- **Locate / hard-to-borrow warnings.** No provider surface for
  locate availability; upstream data doesn't exist.

## 3. Public API changes

### `xray.herfindahl_hirschman(exposures, gross=False)`

```python
def herfindahl_hirschman(
    exposures: dict[str, Decimal],
    gross: bool = False,
) -> Decimal:
    """Compute HHI on net-signed weights (default) or gross-abs weights.

    gross=False (default, backward-compat):
        HHI = Σ w_i²  where w_i is the signed weight.
        Undefined for signed books — offsetting long+short can produce
        HHI > 1.0 (a long and short of equal magnitude but opposite
        sign each contribute w² and there's no cancellation).
    gross=True:
        HHI = Σ (|value_i| / Σ|value_j|)²
        Correct on signed books — a $1M long + $1M short = HHI 0.5
        (two equal-magnitude positions), matching intuition.
    """
```

### `xray.effective_n(hhi)` — no change

`effective_n` is just `1/HHI`; the caller decides which HHI to feed
it. No signature change.

### `analytics.whatif` — new warning + branch dispatch

```python
_SHORTS_ENABLED_WARNING = (
    "signed-book diff: at least one projected qty is short (< 0). "
    "Concentration reported on GROSS weights; sector/country rollups "
    "reported on SIGNED weights (see #904)"
)
```

`run_whatif`:
- Remove the "projected qty < 0 → ValueError" branch.
- After computing `projected_qty`, if any value is negative:
  - Attach `_SHORTS_ENABLED_WARNING` to `diff.warnings`.
  - Concentration path uses `gross=True`.
  - Rollups keep signed weights (they naturally handle sign — a
    negative weight in a sector rollup subtracts from that sector's
    total, which is the correct reading).
- Cash-line arithmetic (#903) unchanged — a short still generates
  proceeds (credits cash under `cash_funded`) and requires borrow
  costs downstream that are out of scope here.

**Backward-compat:** long-only books hit the exact same code paths as
the initial ship. The `_SHORTS_ENABLED_WARNING` and `gross=True`
branches fire only when at least one projected qty is negative.

## 4. Design decisions

### 4.1 Concentration on gross, rollups on signed — why the split?

- **Concentration** answers "how directionally exposed am I to a
  single name?" A $1M short and a $1M long both expose me to $1M of
  price movement on that name. Gross-weight HHI captures this. Net
  would let a fully-hedged book (long+short of equal size on the same
  name) appear as HHI=0, which is misleading — the book carries $2M
  of gross exposure with $0 net.
- **Sector rollups** answer "is my book long or short tech, net?" A
  short SPY *does* reduce net tech exposure, and the widget should
  show that. Signed weights are what a portfolio manager reads to
  understand net directional tilt.

### 4.2 `_look_through_or_empty` on signed weights

`xray.look_through` currently asserts weights sum to 1.0. With
shorts, they still can (the signed sum of long weights + negative
weights of shorts, all normalized by the risky-total-value, still
sums to 1.0 by construction — because
`risky_total = Σ q_i × p_i` where q_i is signed). So `look_through`
works unmodified.

But: `look_through` filters to `if v > 0` when building the input
dict — that would drop shorts silently. Need to widen the filter to
`if v != 0`.

**Impact assessment for #558 shipped code**: this branch changes the
`if v > 0` filter in `run_whatif` for building `projected_weights` /
`current_weights`. Because the initial ship rejects shorts, no
existing test exercises the `if v > 0` filter on a negative-value
case — behavior is preserved for long-only tests.

### 4.3 What about the risky-book denominator?

Under #903, `risky_total = Σ v_i` (unsigned sum of shares × price).
With shorts, `v_i` can be negative, so `Σ v_i` can shrink or even go
negative. That's wrong — a $1M long AAPL + $1M short SPY should have
$2M of gross book, not $0.

Fix: define `risky_total = Σ |v_i|` (gross book value) instead of
the signed sum, ONLY when computing the weight-vector normalization.
The signed sum retains its meaning for the `projected_total` cash
denominator.

**Two distinct totals from here on:**
- `gross_book = Σ |v_i|` — for weight vectors, HHI-gross, and
  interpretation "what's the total capital deployed"
- `net_book = Σ v_i` — for cash arithmetic (a short generates cash)
  and the WhatIfDiff.cash_diff line

For long-only books, `gross_book == net_book`, so the initial-ship
math is unchanged.

### 4.4 Rollup weight math with signed weights

`xray.rollup_by(current_effective, attribute_provider, "sector")` sums
weights per sector. With signed weights, a short in a sector
subtracts from the sector's total. That's the correct behavior — no
code change needed on the rollup side.

### 4.5 Component-VaR sanity

`risk.component_var` uses `w.T @ cov` where `w` is the weight vector.
Signed weights are handled correctly by matrix algebra — a short
position contributes negatively to portfolio variance in the sense
that it can offset a long position's covariance contribution (through
the covariance-matrix cross-term).

**Explicit test**: add one that shows a short of a highly-correlated
name (e.g. -1 unit of SPY when long SPY-tracker) *reduces* projected
volatility vs the pre-short book. Load-bearing on the "matrix
algebra respects sign" invariant.

## 5. Testing plan

Extend `tests/unit/test_whatif.py` with a `#904` section. New tests:

**A. Backward-compat (regression guard).**
- All 31 existing (19 original + 12 from #903) tests pass unmodified.
  Primary R7.11 check.

**B. Simple short position.**
- Flip a full position short (delta_qty = -2 × current_qty) →
  projected_qty < 0, diff computes, `_SHORTS_ENABLED_WARNING` fires.

**C. Signed rollup correctness.**
- Long AAPL (Tech) + short SPY (Tech via ETF look-through) →
  projected Tech sector rollup is LESS than current (the short
  reduces net tech).
- Test uses a small holdings_provider with SPY that has a Tech
  weight so the look-through actually engages.

**D. Gross-weight concentration.**
- Long $1M AAPL + short $1M MSFT → gross HHI on projected = 0.5
  (two equal-magnitude positions). Net-HHI would be
  0.25 + 0.25 = 0.5 too (both squared), but that's a coincidence —
  use asymmetric weights ($1M long + $2M short) to distinguish:
  gross_HHI = (1/3)² + (2/3)² ≈ 0.556; net_HHI = (1/3)² + (-2/3)² = 0.556 too?
  Actually squaring cancels sign so net_HHI equals gross_HHI when
  computed via w².
  → **The design difference is only in the DENOMINATOR**: gross
  normalizes by Σ|v|, net normalizes by Σv (signed). Use net_book <
  gross_book to distinguish.
  → Test: long $1M A + short $500k B → gross_book=$1.5M, net_book=$500k.
  net-HHI would use $500k denominator: (1M/500k)² + (500k/500k)² = 4+1 = 5 (nonsense, >1).
  gross-HHI: (1M/1.5M)² + (500k/1.5M)² = 0.444 + 0.111 = 0.556 (sane).
- Assert projected HHI ∈ (0, 1] when shorts present (the "gross
  keeps it bounded" invariant).

**E. Reverse-verify HHI-gross.**
- Temporarily flip `gross=True` back to `gross=False` in the shorts
  path → the same test above returns HHI > 1 (or NaN under some
  arithmetic). Confirms the test discriminates.

**F. Component-VaR on signed weights.**
- Long SPY 100% + delta short SPY 50% → projected weights = long 50%
  (net) → volatility LOWER than current (half the exposure). Load-
  bearing on the "signed weights flow through risk correctly"
  invariant.

**G. Guard rails.**
- All-short book: raises ValueError (or warns? — pick a rule). Pick
  **raise**: a book with 0 gross long capital is a degenerate case
  that shouldn't produce a diff.
- Mixed long+short + cash under `cash_funded`: cash still debited on
  buys, credited on sells (sell = negative delta_qty, whether the
  starting position is long or short). Verify.

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/analytics/
│   ├── xray.py       # EDIT — herfindahl_hirschman(gross=False) toggle
│   └── whatif.py     # EDIT — drop short-reject, add signed weight branch
└── tests/unit/
    ├── test_xray.py     # EXTEND — gross=True path tests
    └── test_whatif.py   # EXTEND — #904 section: shorts + signed diffs
```

No new files.

## 7. Verdict

Ship §3-§5 as one PR. This is a scope extension of a shipped API with
strict backward compat. Expect 1-2 review iterations on the
gross-vs-net documentation. Multi-currency stays deferred; short-borrow
cost stays deferred (belongs on Paper Trading side).

The load-bearing R7.11 check is the **19+12+13 = 44/44 pass** target
after the new tests land, with mutation-verify on the sign-handling
branches.
