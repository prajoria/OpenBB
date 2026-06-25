# parse_fidelity_positions.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/parse_fidelity_positions.py` (~870 lines) |
| **Writes** | `Portfolio_Positions`, `Account_Owner` |

> Full deep-dive (DOM structure, table layouts, account resolution, design
> rationale) lives in `../DESIGN.md` §5 and §8. This spec is the quick
> reference.

## Purpose

Parse a saved Fidelity "Portfolio Positions" HTML export (virtualized ag-grid)
into a tidy `DataFrame` and persist it to MySQL — one row per cost-basis lot
(expanded positions) or one row per collapsed position summary.

## Inputs

- A Fidelity Portfolio Positions HTML file (`--file`, or `DEFAULT_HTML_PATH`).
- The pinned-left ag-grid container is the **authority** for tickers and detail
  drawer tables; the center container only has summary col-id values
  (`curVal`, `qty`, `cstBasShr`, `cstBasTot`, `totGL`, `totGLPct`).

## CLI

```
--file / -f     Path to HTML file (default: DEFAULT_HTML_PATH)
--database      Override MySQL database
--owner         Owner name for Account_Owner (interactive prompt if omitted)
--dry-run       Parse + display only, no DB write
--csv           Also save the DataFrame to this CSV path
```

## Key functions

| Function | Purpose |
|----------|---------|
| `_extract_snapshot_timestamp(soup)` | parse "As of ..." sidebar timestamp |
| `_build_account_map(soup)` | row-index -> account_name boundary map |
| `_extract_identifier(pinned_row)` | ticker/CUSIP from pinned-left row |
| `_center_cell_values(center_row)` | col-id -> text dict (collapsed rows) |
| `_resolve_account(idx, ...)` | binary-search account boundaries |
| `extract_positions(html_path)` | main parser -> `DataFrame` |
| `persist_to_mysql(df, owner, ...)` | DELETE+INSERT + Account_Owner upsert |
| `print_summary(df)` | by-stock / by-term / by-account console output |

## Tables

- `Portfolio_Positions` — one row per lot/position; `snapshot_date` DATETIME.
  **Persistence:** `DELETE WHERE snapshot_date = X` then `INSERT` (full-snapshot
  replacement; no UNIQUE KEY because RSU vest lots can be truly identical).
- `Account_Owner` — `(account_name, owner)` map; **`INSERT IGNORE`**.

Full DDL in `../DESIGN.md` §4.1 / §4.2.

## Gotchas

- Currency parsing must accept `$10,423.20`, `+$5,104.47`, `-$183.70`,
  `($605.38)` (parens = negative), `--` (no value).
- col-id attributes are brittle — they can change if Fidelity reorders columns.
- Detail tables come in 8-col (regular) and 11-col (ESPP/RSU) layouts.
- `--owner` is required for DB writes but not `--dry-run`.

## Tests

`Tools/tests/test_parse_fidelity_positions.py`.
