# export_basket_weight_comparison.py — Spec

| | |
|---|---|
| **Category** | Read / export |
| **Path** | `Tools/export_basket_weight_comparison.py` |
| **Writes** | Excel file (`.xlsx`) |

## Purpose

For a given basket, build a symbol-level comparison of three weight views and
export to Excel:

1. **Intended** weights from `basket_intended_weight` (latest import by default).
2. **Current basket-scoped** weights from `Portfolio_Positions`.
3. **Current global snapshot** weights from `portfolio_basket`.

## CLI

```
python Tools/export_basket_weight_comparison.py --basket Fortress
python Tools/export_basket_weight_comparison.py --basket Fortress --output Analysis/Fortress_weight_comparison.xlsx
python Tools/export_basket_weight_comparison.py --basket Fortress --database openbb_fmp_cache_test
```

| Flag | Meaning |
|------|---------|
| `--basket` | basket name (required) |
| `--output` | output `.xlsx` path |
| `--database` | override source DB |
| `--import-date` | pin a specific `basket_intended_weight` import (default latest) |
| `--snapshot-date` | pin a specific positions snapshot (default latest) |
| `--universe` | which symbols to include (`all` default) |

## Key function

`build_comparison_table(basket_name, database, import_date, snapshot_date,
universe) -> (DataFrame, dict)` — resolves the latest import/snapshot dates if
not pinned and joins the three weight sources.

## Reads

- `basket_intended_weight`
- `Portfolio_Positions`
- `portfolio_basket`

## Notes

- Read-only against MySQL; the only write is the Excel file.
- Uses `pandas` + `pymysql` with the shared `get_connection(database)` helper.
