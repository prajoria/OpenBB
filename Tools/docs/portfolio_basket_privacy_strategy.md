# Portfolio Basket Privacy Strategy

## Goal
Create and serve a `portfolio_basket` dataset that is useful for analytics (weights, relative performance, allocations) while preventing leakage of real holdings information (true share counts and absolute dollar values) to APIs and LLM-accessible surfaces.

## Privacy Requirements
- Never expose raw `Portfolio_Positions` through API/LLM endpoints.
- Keep `Portfolio_Positions` access local-script only.
- Publish only transformed basket-level data.
- Preserve internal consistency for:
  - weight math,
  - cost/current relationship,
  - gain/loss and pct gain/loss derivation.
- Intentionally break reversibility to true shares and true dollars.

---

## Recommended Strategy (Preferred)
Use a **normalized notional model** in `portfolio_basket`.

### Core idea
For each basket snapshot, map holdings to a synthetic portfolio NAV (for example, `100.0` or `10,000.0`) and store only normalized values.

- `total_current_value` = **weight representation** (not real currency)
- `total_cost_basis` = derived to preserve return math
- `total_gain_loss` = `total_current_value - total_cost_basis`
- `pct_gain_loss` = computed from synthetic values
- `quantity` = synthetic units (optional) and explicitly non-share

This keeps ranking, allocation, and return behavior intact while removing true scale.

---

## Suggested Transform Rules
Assume per basket/snapshot we have symbol-level aggregates from raw positions (local only):
- true `current_value_i`
- true `cost_basis_i`

Let:
- `W_i = current_value_i / sum(current_value)` (weight in 0..1)
- `NAV_SYN = 100.0` (or 10,000.0)

Then publish:
- `total_current_value_i = round(W_i * NAV_SYN, 4)`
- `pct_gain_loss_i = round(((current_value_i - cost_basis_i) / cost_basis_i) * 100, 2)` (if cost_basis_i > 0)
- `total_cost_basis_i = round(total_current_value_i / (1 + pct_gain_loss_i/100), 4)` when pct is finite
- `total_gain_loss_i = round(total_current_value_i - total_cost_basis_i, 4)`
- `portfolio_weight_pct_i = round(W_i * 100, 4)`

### Quantity handling (important)
Best privacy: do **not** expose quantity.

If schema compatibility requires it:
- store `quantity` as synthetic units only, e.g. `round(W_i * 1000, 4)`
- label/document it as `synthetic_units` behavior
- never derive from true shares

---

## Why this is safer
This removes direct disclosure of:
- true shares,
- true notional dollars,
- account/basket monetary scale.

And still enables:
- composition analysis,
- relative performance,
- basket optimization experiments,
- gain/loss and return comparisons.

---

## Hardening Add-ons (Recommended)
1. **Weight bucketing for API mode**
   - Optionally round/bucket `portfolio_weight_pct` (e.g., to 0.25% bins).
2. **Top-N + Others**
   - Collapse smallest positions into `OTHER` bucket to reduce fingerprinting.
3. **Minimum threshold suppression**
   - Hide positions below threshold (e.g., `<0.35%`).
4. **Time smoothing**
   - If needed, publish delayed snapshots (e.g., T-1/T-2) for external endpoints.

---

## API/LLM Data Contract
Allowed from `portfolio_basket`:
- symbol
- basket_name / account_name (synthetic basket account style)
- portfolio_weight_pct
- total_current_value (synthetic)
- total_cost_basis (synthetic)
- total_gain_loss (synthetic)
- pct_gain_loss

Not allowed:
- raw `Portfolio_Positions`
- true lot data
- true share quantity
- true dollar notional

---

## Operational Separation
- Raw ingest + true calculations: local scripts only.
- Transformation pipeline: local trusted process writes `portfolio_basket`.
- APIs query only `portfolio_basket`.
- Access control policy: block `Portfolio_Positions` from service endpoints.

---

## Validation Checks
For each basket snapshot in transformed table, enforce:
- `abs(sum(portfolio_weight_pct) - 100) <= tolerance`
- `total_gain_loss == total_current_value - total_cost_basis` (within rounding)
- `pct_gain_loss == (total_gain_loss/total_cost_basis)*100` when cost basis > 0
- No symbol row contains raw-share semantics.

---

## Migration Plan (High-level)
1. Add/confirm `portfolio_basket` schema fields for synthetic metrics.
2. Build symbol-level aggregates from raw positions locally.
3. Apply normalized transform rules.
4. Write transformed rows to `portfolio_basket`.
5. Point all API endpoints to `portfolio_basket` only.
6. Keep `Portfolio_Positions` script-only.

---

## Recommendation Summary
Use **normalized synthetic notional + weight-preserving returns** as the default.  
It gives the best utility/privacy tradeoff and is straightforward to validate.
