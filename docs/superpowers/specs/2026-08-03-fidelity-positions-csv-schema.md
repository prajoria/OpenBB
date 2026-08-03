# Fidelity Positions Download — CSV schema reference

**Source of truth for the "positions download" CSV that the Fidelity
website emits when the operator hits the "Download" button on the
Positions page.** Read-only from our side — nothing we write goes to
Fidelity as a structured import (Fidelity has no basket-upload / API
surface; every real order gets filed manually).

Referenced by:

- `openbb_platform/tools/portfolio_utils/portfolio_utils/parse_fidelity_positions.py`
  — the parser that ingests these files into MySQL
  (`Portfolio_Positions`) and SQLite (`~/.portfolio_importer/positions.db`).
- Future paper-fill reconciliation (T5 P5 on #1719) — after the
  operator files orders manually and Fidelity's next positions snapshot
  arrives, we diff pre-execution vs. post-execution positions to
  confirm fills.
- The XLSX "Manual Order Placement Cheat Sheet" (T5 P4 on #1719) is
  formatted so its rows are the *inverse* of this table — the operator
  reads our cheat sheet, types it into Fidelity's order UI, and the
  next positions download reflects the change.

Because the CSV is public-facing (from the operator's browser export),
we treat this as a stable schema. Any change Fidelity makes to the
column list is caught by `parse_fidelity_positions.py`'s header-check
+ the row-count sanity guard.

## Column reference

| Field Name | Header Label | Data Type | Requirement | Description / Format |
|---|---|---|---|---|
| `account_id` | Account Name / Number | String | Required | Account descriptor and masked number (e.g., `Individual - X12345678`). |
| `ticker_symbol` | Symbol | String | Required | Ticker symbol or core position identifier (e.g., `AAPL`, `SPAXX`). |
| `description` | Description | String | Required | Full security or asset class description. |
| `quantity` | Quantity | Numeric (Decimal) | Required | Total units/shares held (formatted to up to 3 decimal places). |
| `last_price` | Last Price | Numeric (Currency) | Required | Most recent market or closing price per unit. |
| `price_change_dollar` | Last Price Change ($) | Numeric (Signed) | Optional | Day's price movement in dollars per unit (+ or −). |
| `price_change_percent` | Last Price Change (%) | Numeric (Percent) | Optional | Day's price movement as a percentage. |
| `market_value` | Current Value | Numeric (Currency) | Required | Total market position value (Quantity × Last Price). |
| `todays_gain_loss_dollar` | Today's Gain/Loss ($) | Numeric (Signed) | Optional | Dollar change in total value during the current trading session. |
| `todays_gain_loss_percent` | Today's Gain/Loss (%) | Numeric (Percent) | Optional | Percentage change in total value during the current trading session. |
| `cost_basis_per_share` | Cost Basis Per Share | Numeric (Currency) | Optional | Average acquisition cost per share. May return string `Pending Update` for unsettled trades. |
| `total_cost_basis` | Total Cost Basis | Numeric (Currency) | Optional | Aggregate cost basis (Quantity × Cost Basis Per Share). |
| `total_gain_loss_dollar` | Total Gain/Loss ($) | Numeric (Signed) | Optional | Cumulative unrealized gain or loss in dollars since acquisition. |
| `total_gain_loss_percent` | Total Gain/Loss (%) | Numeric (Percent) | Optional | Cumulative unrealized return percentage. |
| `portfolio_weight` | Percent of Portfolio | Numeric (Percent) | Optional | Holding value divided by total portfolio account value. |

## Format quirks worth remembering

- **Currency columns include a leading `$`** (e.g., `$1,234.56`) — the
  parser strips it. `Pending Update` in `cost_basis_per_share` is a
  string, not a numeric; the parser sets it to `None` and logs a
  WARNING.
- **Percentage columns include a trailing `%`** (e.g., `12.34%`) — the
  parser strips it and divides by 100 so downstream code sees a fraction.
- **Signed columns can use `+` prefix** (e.g., `+3.45`) — the parser
  tolerates both `+3.45` and `3.45`.
- **`quantity` up to 3 decimal places** — enough for fractional shares
  (mutual funds, some ETFs), inadequate for options contract counts
  (which Fidelity emits as integers anyway).
- **`account_id` is not a bare number** — it's `<Descriptor> - X<last-4>`.
  Our importer's `mask_account_number()` normalizes to the last-4
  form before persisting.
- **The header row appears in every file** — unlike some brokers'
  headerless exports, Fidelity always includes it, which is why our
  parser can safely refuse a file whose header doesn't match this
  schema.
- **The file is emitted in the operator's current sort order** —
  whatever they had toggled on the Positions page. Don't rely on any
  particular row order.

## Non-goals

- **We do NOT emit this format.** Nothing in this repo generates a
  positions-style CSV to send back to Fidelity — Fidelity has no
  such upload surface.
- **We do NOT treat this as the paper-trading engine's positions
  store schema.** The engine has its own richer schema (tax lots,
  order-timestamped fills, realized P&L, etc.). This CSV is the
  *reconciliation source*, not the storage model.
- **We do NOT extend this schema.** Fidelity owns the format; adding
  columns here doesn't make Fidelity emit them. Enrichment happens
  downstream in `Portfolio_Positions` (sector, industry, etc.).

## Related files

- `openbb_platform/tools/portfolio_snapshot_importer/portfolio_snapshot_importer/ingest.py`
  — the CSV ingest path. **Currently reads an older Fidelity header
  set** (see "Schema drift" below); needs an update PR to align with
  the schema documented here.
- `openbb_platform/tools/portfolio_utils/portfolio_utils/parse_fidelity_positions.py`
  — an older HTML-scraping parser (Playwright DOM). Unaffected by CSV
  schema changes.
- `openbb_platform/tools/portfolio_snapshot_importer/` — the SQLite
  positions store (`~/.portfolio_importer/positions.db`)
- `openbb_platform/tools/portfolio_snapshot_importer/portfolio_snapshot_importer/mysql_store.py`
  — the canonical MySQL store added in #1744 / PR #1747

## Schema drift — the parser is on an older format

`ingest.py:27-44` (`_EXPECTED_COLS`) reads a different, older header
set than the one documented above. Discrepancies:

| This doc | `ingest.py` | Note |
|---|---|---|
| `Account Name / Number` (one column) | `Account number` + `Account name` (two) | Old format split them |
| `Last Price Change ($)` + `Last Price Change (%)` (two) | `Last price change` (one) | Old format had a single combined column |
| `Today's Gain/Loss ($)` / `(%)` | `Today's gain/loss dollar` / `Today's gain/loss percent` | Same fields, different capitalization + word for symbol |
| `Total Cost Basis` | `Cost basis total` | Word order flip |
| `Cost Basis Per Share` | `Average cost basis` | Different name for the same field |
| `Percent of Portfolio` | `Percent of account` | Different name |
| (not in this doc) | `Type` | Old format had a Type column |

**Neither format is "wrong"** — Fidelity's Download button emits
whatever the current UI version produces. Both live formats exist in
the wild (a saved 2024 export uses the old headers; a fresh 2026
export uses the new ones).

**Follow-up action** (not blocking on T5 #1719): update `ingest.py`
to accept **both** header sets via an alias map, so either export
imports cleanly. Track under a new "portfolio-intel/ingest schema
alignment" issue.

