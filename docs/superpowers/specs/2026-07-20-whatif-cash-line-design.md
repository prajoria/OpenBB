# Design — What-If cash line + funding modes (#903)

- **Date:** 2026-07-20
- **Issue:** [#903](https://github.com/prajoria/OpenBB/issues/903)
- **Parent:** #558 (initial What-If diff engine, shipped as PR #905)
- **Branch:** `feat/pi-analytics/whatif-cash-line-gh-903`
- **Base:** `portfolio` (post-#558)
- **Status:** Draft

---

## 1. Purpose

The initial What-If engine (`analytics/whatif.py`) ships **self-financing
only** — every buy is implicitly funded by pro-rata trimming every other
holding. That covers rebalancing to a target weight, but doesn't model
either of the other two things users ask about:

| Funding model | Meaning | Example prompt |
|---|---|---|
| **cash_funded** | Deploy idle cash; book grows | "I have $50k cash — buy NVDA" |
| **named_sell_funded** | Sell A, buy B, rest unchanged | "Rotate MSFT → NVDA" |
| **self_financing** (shipped) | Pro-rata trim | "Get me to 5% AAPL" |

## 2. Scope

**In scope:**
- Add `cash: Decimal = Decimal("0")` to `MarketData` (additive, default-preserving).
- Add `funding_mode: Literal["self_financing","cash_funded","named_sell_funded"] = "self_financing"` to `run_whatif`.
- Under `cash_funded`: cash contributes to `current_total`/`projected_total` as a zero-weight zero-vol line; deltas debit/credit cash rather than renormalizing away.
- Warn (non-fatal) when projected cash goes negative (implicit margin).
- Under `named_sell_funded`: skip the self-financing renormalization branch of the projected-weights math; caller is responsible for netting the deltas to zero (verifier warns if not).
- New warning strings, all grep-able.
- Backward-compatible: existing callers with no `cash` field and no `funding_mode` get exactly the same self-financing behavior.

**Out of scope (documented, deferred):**
- **Multi-currency.** `cash: Decimal` remains scalar in the base currency of the book. Cross-currency positions still get the single-currency-silently-assumed treatment. Filed as follow-up (#903-currency, to be created).
- **Withdrawal / deposit intents.** Cash CAN be set explicitly by the caller but there is no "add $10k" delta type. Funding is derived from deltas, not from a separate cash-flow input.
- **Cost basis / P&L on the sell side.** What-If reports current vs projected exposure and risk; realized-P&L on the funded-by-sell side belongs to Paper Trading (#544-548).

## 3. Public API changes

### `MarketData`

```python
@dataclass
class MarketData:
    prices: dict[str, Decimal]
    holdings_provider: dict[str, list[Holding]]
    attribute_provider: dict[str, Holding]
    returns: np.ndarray
    returns_symbols: list[str]
    cov: np.ndarray
    benchmark_returns: np.ndarray
    cash: Decimal = Decimal("0")  # NEW — book's idle cash in base currency
```

### `run_whatif` signature

```python
def run_whatif(
    positions: list[PositionQty],
    deltas: list[Delta],
    market_data: MarketData,
    funding_mode: Literal["self_financing","cash_funded","named_sell_funded"] = "self_financing",
) -> WhatIfDiff:
```

### `WhatIfDiff` — new field

```python
@dataclass(frozen=True)
class WhatIfDiff:
    ...  # existing
    cash_diff: MetricDiff | None = None  # NEW — current vs projected cash line
```

`cash_diff` is populated when `market_data.cash > 0` OR `funding_mode == "cash_funded"`. Under `self_financing` with no cash on the book, `cash_diff` is `None` (preserves current output shape for existing callers).

## 4. Design decisions

### 4.1 Cash as a zero-vol book line, not a "special" number

Cash contributes to total-market-value denominators (`current_total`,
`projected_total`) but does NOT appear in `current_weights` /
`projected_weights` — the weight dicts feed into risk (covariance) and
concentration (HHI), and cash is neither risky (vol = 0) nor
concentrating (weight of cash-in-cash HHI = irrelevant).

Consequences:

- HHI and effective-N shift **downward** for cash-heavy books because the
  denominator grows but the security weights don't. That is the correct
  reading — a portfolio with 20% cash IS less concentrated.
- Volatility, VaR, CVaR, beta shift **downward** because the total book
  grows while risky contribution stays the same. Also correct.
- Component-VaR contributions stay in `risky-book-only` frame and their
  sum still equals total risky VaR. A separate `cash_diff` row exposes
  the cash line separately.

Alternative: model cash as a synthetic symbol `__CASH__` inside the
weight vectors, add a zero-vol row/column to cov, add a zero-return
column to returns. Rejected — the covariance-matrix shape mutation
would break every downstream numpy assumption, and NaN guards would
need a special case. Zero-vol synthetic returns also invite div-by-zero
in Sharpe-like ratios that we might add later.

### 4.2 Funding-mode dispatch

Three modes, dispatched at the top of `run_whatif`:

```python
if funding_mode == "self_financing":
    # Current behavior — no cash math. cash_diff = None unless cash > 0 on the book.
elif funding_mode == "cash_funded":
    # Debit/credit market_data.cash per delta; warn if projected cash < 0.
    # No renormalization — projected_total grows/shrinks with the delta value.
elif funding_mode == "named_sell_funded":
    # Sum of delta_qty * price must be ≈ 0 (caller nets). Warn otherwise.
    # Cash unchanged.
else:
    raise ValueError(...)
```

The `self_financing` path is untouched — this is a strict additive
change to the public surface, gated on the new param.

### 4.3 Backward compatibility — the load-bearing rule

- `MarketData` gets a defaulted field. All existing test fixtures pass through.
- `run_whatif` gets a defaulted param. All existing call sites keep working.
- `WhatIfDiff` gets a new field with default `None`. `dataclass(frozen=True)` still admits the new field because it has a default.

**Test load-bearing**: the pre-existing 80/80 `test_whatif.py` suite runs
green *without modification* against this branch. That's the load-bearing
regression check — if any of those 80 tests fail after the diff, I broke
the shipped contract.

### 4.4 Warning strings

New grep-able sentinels (same pattern as `_SELF_FINANCING_WARNING`):

```python
_CASH_FUNDED_WARNING = (
    "cash-funded diff: buys debit market_data.cash; verify cash line "
    "reflects actual idle cash (see #903)"
)
_NAMED_SELL_FUNDED_WARNING = (
    "named-sell-funded diff: caller-supplied deltas net through — cash "
    "line unchanged (see #903)"
)
_NEGATIVE_CASH_WARNING = (
    "cash-funded diff drives projected cash negative — implicit margin "
    "assumption, results still computed"
)
_UNBALANCED_NAMED_SELL_WARNING = (
    "named-sell-funded diff: sum(delta_qty * price) = {net} ≠ 0 — book "
    "value shifts by {net}; consider explicit funding_mode"
)
_CURRENCY_ASSUMPTION_WARNING = (
    "cash line is scalar in the book's base currency; multi-currency "
    "positions are silently single-currency (see #903 follow-up)"
)
```

## 5. Testing plan

Extend `tests/unit/test_whatif.py`. New tests cover:

**A. Backward compatibility (regression guard).**
- All 80 existing tests pass unmodified. This is the primary R7.11 check.

**B. `cash_funded` mode.**
- Happy path: buy $10k of NVDA with $50k cash on the book → NVDA weight rises, all other weights fall (denominator grew), projected cash = $40k, `cash_diff.delta = -10_000`.
- Full deploy: buy = current cash exactly → projected cash = 0, no warning.
- Over-deploy: buy > current cash → projected cash < 0, `_NEGATIVE_CASH_WARNING` fires, diff still computed.
- Zero cash on book + `cash_funded`: warn about zero starting cash + implicit margin.
- Sell under `cash_funded`: cash increases (credit), no warning.
- **R7.11 reverse-verify**: temporarily revert the debit-arithmetic and confirm at least one of these tests fails. Applied per-test at author-time.

**C. `named_sell_funded` mode.**
- Happy path: sell $10k MSFT, buy $10k NVDA, deltas net to 0 → cash unchanged, weights shift 1-for-1, no `_UNBALANCED_...` warning.
- Unbalanced: net > 0 (sold more than bought) → warn, book value shrinks.
- **Reverse-verify** with mutation on the netting-tolerance check.

**D. `cash_diff` shape.**
- `self_financing` + zero cash → `cash_diff is None` (backward-compat).
- `self_financing` + positive cash on book → `cash_diff` populated with `delta = 0` (book unchanged).
- `cash_funded` → `cash_diff` populated with `delta = -sum(buy_value)`.
- `named_sell_funded` → `cash_diff` populated with `delta = 0` if balanced.

**E. Guard rails.**
- Invalid `funding_mode` string → `ValueError`.
- `cash < 0` in `MarketData` → `ValueError` (a negative cash line means the book is already in margin — outside this cut's scope).

## 6. File layout

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/analytics/whatif.py       # EDIT — add fields + branch
└── tests/unit/test_whatif.py                        # EXTEND — new tests only
```

No new files. No new modules. Additive change.

## 7. Verdict

Ship §3+§4 as one PR. This is a targeted extension of a proven substrate,
not a redesign. Expect one review iteration on warning-text wording and
possibly on whether `cash_diff` should always be populated (nullable-vs-
optional debate). Reverse-verified per test.

Multi-currency is filed as a separate follow-up so this PR stays small
and focused.
