# load_espp_plan.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/load_espp_plan.py` (~540 lines) |
| **Writes** | `ESPP_Plan` |

> See also `../DESIGN.md` §6 and the standalone `../load_espp_plan.md`.

## Purpose

Parse ESPP (Employee Stock Purchase Plan) purchase history pasted/exported from
a brokerage statement (TSV/CSV) and upsert it into `ESPP_Plan`.

## Input format (TSV/CSV)

`Offering Period, Purchase Date, FMV at offering Start Date, FMV at Purchase
Date, Purchase Price, Purchase Quantity, Purchase Value, Qualified Disposition
Date, Purchase Deposit To`

## Data model — `@dataclass ESPPPurchase`

Computed properties:
- `discount_pct` = `(fmv_offering_start - purchase_price) / fmv_offering_start * 100`
- `bargain_element` = `(fmv_purchase_date - purchase_price) * purchase_quantity`

The "look-back" rule: purchase price is typically `85% * min(FMV_offering_start,
FMV_purchase_date)`.

## CLI

```
python Tools/load_espp_plan.py --file espp_data.tsv
python Tools/load_espp_plan.py --clipboard          # requires pyperclip
python Tools/load_espp_plan.py                       # embedded sample data
python Tools/load_espp_plan.py --database my_db
python Tools/load_espp_plan.py --dry-run
```

| Flag | Meaning |
|------|---------|
| `--file` / `-f` | path to TSV/CSV |
| `--clipboard` / `-c` | read from clipboard |
| `--database` | override target DB |
| `--dry-run` | parse + display only |

## Table: `ESPP_Plan`

Natural key `(offering_period_start, offering_period_end, purchase_date)`.
**Persistence:** `INSERT ... ON DUPLICATE KEY UPDATE` (upsert). Full DDL in
`../DESIGN.md` §4.3.

## Notes

- `symbol` defaults to `MSFT`.
- `discount_pct` / `bargain_element` are computed and stored for downstream
  tax-lot analysis.
