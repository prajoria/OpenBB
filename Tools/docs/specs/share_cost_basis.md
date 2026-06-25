# share_cost_basis.py — Spec

| | |
|---|---|
| **Category** | Analysis (no DB) |
| **Path** | `Tools/share_cost_basis.py` (~310 lines) |
| **Writes** | none |

> See also `../DESIGN.md` §7.

## Purpose

Standalone cost-basis / gain-loss analyzer for a set of share lots. No database
— reads TSV/CSV (or embedded sample data) and prints a portfolio summary.

## Data model

- `@dataclass ShareLot` — a single tax lot.
- `@dataclass Portfolio` — collection of lots with computed properties:
  `total_quantity`, `total_cost_basis`, `total_current_value`,
  `total_gain_loss`, `total_pct_gain_loss`, `weighted_avg_cost`,
  `short_term_lots`, `long_term_lots`.

## CLI

```
python Tools/share_cost_basis.py --file lots.tsv
python Tools/share_cost_basis.py --clipboard
python Tools/share_cost_basis.py                 # embedded sample data
```

| Flag | Meaning |
|------|---------|
| `--file` | path to TSV/CSV of lots |
| `--clipboard` | read from clipboard |

## Notes

- Pure in-memory analysis — good for quick what-if cost-basis math without
  touching MySQL.
- Shares the currency/quantity parsing conventions with the Fidelity parser.
