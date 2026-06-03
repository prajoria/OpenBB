---
applyTo: "Tools/**"
---

# Tools/ Script Rules

## Script Inventory

| Script | Purpose | DB Tables |
|--------|---------|-----------|
| `parse_fidelity_positions.py` | Parse Fidelity HTML (ag-grid) → structured rows | `Portfolio_Positions`, `Account_Owner` |
| `load_espp_plan.py` | Parse ESPP purchase history (TSV/CSV) → MySQL | `ESPP_Plan` |
| `fetch_position_history.py` | Fetch daily equity prices for all portfolio symbols | `equity_historical` |
| `populate_market_holidays.py` | Compute US stock market holidays | `market_holidays` |
| `share_cost_basis.py` | Standalone cost-basis / gain-loss analyzer | — (no DB) |

## Fidelity HTML Parsing

- Fidelity uses ag-grid with **pinned-left** and **center** containers
- Pinned-left is the authority for tickers and detail drawers
- Center container does NOT contain drawer tables
- Col-id attributes (`curVal`, `qty`, `cstBasShr`, etc.) may change — treat as brittle

## Currency Value Parsing

Handle all Fidelity formats:
- `$10,423.20` — standard positive
- `+$5,104.47` — explicit positive
- `-$183.70` — negative
- `($605.38)` — parentheses mean negative
- `--` — no value (return `0.0` or `None`)

## Key Dependencies

```
Tools/parse_fidelity_positions.py → openbb_fmp_cached.utils.database
Tools/load_espp_plan.py → openbb_fmp_cached.utils.database
Tools/fetch_position_history.py → openbb_fmp_cached.utils.database
                                 → openbb_fmp_cached.models.equity_historical
                                 → openbb_core.app.service.user_service
Tools/populate_market_holidays.py → openbb_fmp_cached.utils.database
```

## Documentation

- `Tools/docs/DESIGN.md` — Living architecture doc (committed)
- `Tools/docs/CONTEXT_LOCAL.md` — Sensitive local context (git-ignored, never commit)
