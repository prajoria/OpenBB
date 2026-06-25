# portfolio_stats.py — Spec

| | |
|---|---|
| **Category** | Read / reporting |
| **Path** | `Tools/portfolio_stats.py` |
| **Writes** | none (console output only) |

## Purpose

Query `Portfolio_Positions` + `Account_Owner` and print a summary grouped by
owner and account. A read-only reporting helper for sanity-checking what the
loaders ingested.

## Output

- Table-level stats: total rows, distinct snapshot count, snapshot date range,
  `Account_Owner` row count.
- Breakdowns grouped by owner and by account.

## CLI

```
python Tools/portfolio_stats.py
```

No flags — uses the default `DatabaseConfig` connection (autocommit,
`DictCursor`).

## Notes

- Read-only; safe to run anytime.
- Depends on `parse_fidelity_positions.py` having populated the tables.
