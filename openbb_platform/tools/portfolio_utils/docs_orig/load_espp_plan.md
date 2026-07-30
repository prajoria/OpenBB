# ESPP Plan Data Loader

> **Script:** `Tools/load_espp_plan.py`

Parses Employee Stock Purchase Plan (ESPP) purchase records from a brokerage
export and populates the `ESPP_Plan` table in MySQL.

---

## What Is an ESPP?

An ESPP (IRC §423) lets employees buy company stock at a discount — typically
**15 %** off the lower of two Fair Market Values (the **look-back** provision):

1. FMV on the **offering start date**, and
2. FMV on the **purchase date**.

Payroll deductions accumulate during a fixed **offering period** (usually 3–6
months) and shares are purchased automatically at the end of each period.

---

## Usage

```bash
# Use embedded sample data (quick test)
python Tools/load_espp_plan.py

# Parse only — no database write
python Tools/load_espp_plan.py --dry-run

# Load from a TSV / CSV file
python Tools/load_espp_plan.py --file espp_data.tsv

# Read from clipboard (requires pyperclip)
python Tools/load_espp_plan.py --clipboard

# Target a specific MySQL database
python Tools/load_espp_plan.py --database my_db
```

---

## Input Format

Tab-separated (TSV) or comma-separated (CSV) with the following columns.
You can copy-paste directly from a brokerage ESPP statement page.

| # | Column Header                     | Example Value       |
|---|-----------------------------------|---------------------|
| 1 | Offering Period                   | 07/01/2025 - 09/30/2025 |
| 2 | Purchase Date                     | 09/30/2025          |
| 3 | FMV at offering Start Date        | $492.05 USD         |
| 4 | FMV at Purchase Date              | $517.95 USD         |
| 5 | Purchase Price                    | $466.16 USD         |
| 6 | Purchase Quantity                 | 5.517 shares        |
| 7 | Purchase Value                    | $2,571.85 USD       |
| 8 | Qualified Disposition Date†††     | 07/01/2027          |
| 9 | Purchase Deposit To               | Brokerage Account   |

> **Note:** Currency values may include `$`, `,`, `USD`, and parentheses for
> negatives.  Quantity may include the word `shares`.  All are parsed
> automatically.

---

## Database Table: `ESPP_Plan`

The script creates the table automatically if it doesn't exist and performs an
**upsert** (INSERT … ON DUPLICATE KEY UPDATE) keyed on
`(offering_period_start, offering_period_end, purchase_date)`, so re-runs are
safe.

### Column Reference

| Column                      | Type            | Description |
|-----------------------------|-----------------|-------------|
| `id`                        | INT AUTO_INCREMENT | Surrogate primary key |
| `offering_period_start`     | DATE            | First day of the ESPP enrollment window. The FMV on this date is one of the two prices used in the look-back calculation. |
| `offering_period_end`       | DATE            | Last day of the offering window (often coincides with the purchase date). |
| `purchase_date`             | DATE            | Date shares were actually purchased with accumulated payroll deductions. |
| `fmv_offering_start`        | DECIMAL(12,4)   | Fair Market Value (closing price) on the offering start date. Used in: `purchase_price = 85% × min(FMV_start, FMV_purchase)`. |
| `fmv_purchase_date`         | DECIMAL(12,4)   | Fair Market Value (closing price) on the purchase date. |
| `purchase_price`            | DECIMAL(12,4)   | Discounted per-share price the employee paid — usually 85 % of the lower of the two FMVs. |
| `purchase_quantity`         | DECIMAL(12,4)   | Number of shares acquired (may be fractional). |
| `purchase_value`            | DECIMAL(14,4)   | Total cost of the purchase = `purchase_price × purchase_quantity`. |
| `qualified_disposition_date`| DATE            | Earliest date the shares can be sold for long-term capital-gains treatment. This is the **later** of: 2 years after `offering_period_start` **or** 1 year after `purchase_date`. Selling before this date is a *disqualifying disposition*. |
| `purchase_deposit_to`       | VARCHAR(100)    | Brokerage account where purchased shares were deposited (e.g. "Brokerage Account"). |
| `symbol`                    | VARCHAR(20)     | Ticker symbol of the stock purchased. Defaults to **MSFT**. |
| `discount_pct`              | DECIMAL(6,2)    | **Computed at insert time.** Effective discount % = `(FMV_start − price) / FMV_start × 100`. |
| `bargain_element`           | DECIMAL(14,4)   | **Computed at insert time.** Compensation element = `(FMV_purchase − price) × quantity`. This is the amount reported on IRS Form 3922 and potentially taxed as ordinary income. |
| `created_at`                | TIMESTAMP       | Row creation timestamp (auto-populated). |

### Tax Implications

| Disposition Type     | When                                     | Tax Treatment |
|----------------------|------------------------------------------|---------------|
| **Qualifying**       | Sold after `qualified_disposition_date`  | Bargain element (capped at offering-start discount) taxed as ordinary income; remainder as LTCG. |
| **Disqualifying**    | Sold before `qualified_disposition_date` | Full bargain element (`FMV_purchase − price`) × qty taxed as ordinary income; any additional gain as STCG/LTCG depending on holding period. |

---

## Database Configuration

The script reuses `DatabaseConfig` from the `openbb_fmp_cached` provider,
which reads MySQL credentials from (in priority order):

1. `~/.openbb_platform/user_settings.json` → `credentials` section
2. Environment variables: `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
3. Defaults: `fmp_user@localhost:3306/openbb_fmp_cache`

Override the target database with `--database <name>`.

---

## Example

```
$ python Tools/load_espp_plan.py --file espp_q3.tsv

==========================================================================================
  ESPP PLAN PURCHASES
==========================================================================================
  Offering Period               Purchase  FMV Start  FMV Purch      Price      Qty        Value    Qual Disp
  --------------------------- ---------- ---------- ---------- ---------- -------- ------------ ------------
  04/01/2025 - 06/30/2025     06/30/2025 $  382.19 $  497.41 $  447.67   23.788 $ 10,649.17   04/01/2027
  07/01/2025 - 09/30/2025     09/30/2025 $  492.05 $  517.95 $  466.16    5.517 $  2,571.85   07/01/2027

  Total purchases:   2
  Total shares:      29.305
  Total value:       $   13,221.02
  Total bargain:     $    1,468.94  (taxable compensation)
==========================================================================================

Writing 2 record(s) to ESPP_Plan table …

==================================================
  Done — database: openbb_fmp_cache_test
  Rows upserted:   2
  Total rows:      2
==================================================
```
