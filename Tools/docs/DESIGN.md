# Tools — Design & Context Document

> **Purpose:** Living reference for AI-assisted development sessions.
> Captures architecture, design decisions, table schemas, changelog, and
> known issues so future context windows can resume work efficiently.

---

## 1. Overview

The `Tools/` directory contains standalone CLI scripts that parse brokerage
data (HTML exports, TSV/CSV) and persist it to a local MySQL database for
analysis.  All scripts share a common infrastructure pattern.

### Repository & Branch

| Key               | Value                                                |
|--------------------|------------------------------------------------------|
| Repo               | Fork of OpenBB-finance/OpenBB                        |
| Branch             | `openbb_learning`                                    |
| Python venv        | `.venv_win` (project-local)                          |
| MySQL database     | Configured via `DatabaseConfig`                      |
| MySQL credentials  | Stored in `~/.openbb_platform/user_settings.json`   |
| Data directory     | External (see `CONTEXT_LOCAL.md`)                    |

> **Note:** Real paths, credentials, and account details are in
> `Tools/docs/CONTEXT_LOCAL.md` (git-ignored).  See `rules/COLLABORATION_RULES.md`
> for PII hygiene guidelines.

---

## 2. Script Inventory

| Script                          | Purpose                                                       | Lines | Tables Created              |
|---------------------------------|---------------------------------------------------------------|-------|-----------------------------|
| `parse_fidelity_positions.py`   | Parse Fidelity "Portfolio Positions" HTML → MySQL             | ~870  | `Portfolio_Positions`, `Account_Owner` |
| `load_espp_plan.py`             | Parse ESPP purchase history (TSV/CSV) → MySQL                | ~540  | `ESPP_Plan`                 |
| `share_cost_basis.py`           | Standalone cost-basis / gain-loss analyzer (TSV/CSV, no DB)  | ~310  | —                           |
| `build_sp500_constituents.py`   | Populate `sp500_constituents` via `fmp_cached` provider      | ~100  | (uses provider module)      |

---

## 3. Shared Infrastructure

All DB-connected scripts follow the same pattern:

```
PROJECT_ROOT discovery → sys.path injection → DatabaseConfig import
→ get_connection(database=) → CREATE TABLE IF NOT EXISTS → INSERT
```

### `get_connection(database=None)`
- Reads `DatabaseConfig` from `openbb_fmp_cached.utils.database`.
- Creates the database if it does not exist.
- Returns a `pymysql` connection with `DictCursor` and `autocommit=True`.
- The `--database` CLI arg overrides the config-derived database name.

### Common Parsers
- `parse_currency(val)` — Handles `$10,423.20`, `+$5,104.47`, `-$183.70`, `($605.38)`, `--`.
- `parse_percent(val)` — Handles `+23.45%`, `-18.91%`, `(5.22%)`, `--`.
- `parse_quantity(val)` — Handles comma-formatted floats.
- `parse_date_str(val)` — Parses `"Jun-13-2022"`, `"06/13/2022"`, etc. to `datetime.date`.

### sys.path Bootstrap
Every script adds these to `sys.path` for source-tree imports:
- `openbb_platform/providers/fmp_cached`
- `openbb_platform/providers/fmp`
- `openbb_platform/core`
- `openbb_platform/platform`
- All `openbb_platform/extensions/*/`
- All `openbb_platform/obbject_extensions/*/`

---

## 4. Table Schemas

### 4.1 `Portfolio_Positions`

Created by `parse_fidelity_positions.py`.  One row per cost-basis lot (expanded)
or one row per collapsed position summary.

```sql
CREATE TABLE IF NOT EXISTS Portfolio_Positions (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_date       DATETIME      NULL,
    account_name        VARCHAR(100)  NOT NULL DEFAULT '',
    symbol              VARCHAR(20)   NOT NULL,
    description         VARCHAR(200)  NOT NULL DEFAULT '',
    acquired            DATE          NULL,
    term                VARCHAR(10)   NOT NULL DEFAULT '',
    total_gain_loss     DECIMAL(14,4) NOT NULL DEFAULT 0,
    pct_gain_loss       DECIMAL(8,2)  NOT NULL DEFAULT 0,
    current_value       DECIMAL(14,4) NOT NULL DEFAULT 0,
    quantity            DECIMAL(14,4) NOT NULL DEFAULT 0,
    avg_cost_basis      DECIMAL(12,4) NOT NULL DEFAULT 0,
    cost_basis_total    DECIMAL(14,4) NOT NULL DEFAULT 0,
    transfer_avail_date DATE          NULL,
    share_source        VARCHAR(50)   NOT NULL DEFAULT '',
    grant_date          DATE          NULL,
    created_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_snapshot (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Persistence strategy:** DELETE all rows with the same `snapshot_date`,
then INSERT.  Makes re-imports idempotent.  No UNIQUE KEY constraint — the
delete-before-insert pattern prevents duplicates.

### 4.2 `Account_Owner`

Created by `parse_fidelity_positions.py`.  Maps Fidelity account names to
human owners, enabling multi-owner households (e.g., spouse accounts).

```sql
CREATE TABLE IF NOT EXISTS Account_Owner (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_name    VARCHAR(100)  NOT NULL,
    owner           VARCHAR(100)  NOT NULL,
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_account_owner (account_name, owner)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Persistence strategy:** `INSERT IGNORE` — silently skips if (account_name,
owner) already exists.

### 4.3 `ESPP_Plan`

Created by `load_espp_plan.py`.

```sql
CREATE TABLE IF NOT EXISTS ESPP_Plan (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    offering_period_start       DATE          NULL,
    offering_period_end         DATE          NULL,
    purchase_date               DATE          NULL,
    fmv_offering_start          DECIMAL(12,4) NOT NULL DEFAULT 0,
    fmv_purchase_date           DECIMAL(12,4) NOT NULL DEFAULT 0,
    purchase_price              DECIMAL(12,4) NOT NULL DEFAULT 0,
    purchase_quantity           DECIMAL(12,4) NOT NULL DEFAULT 0,
    purchase_value              DECIMAL(14,4) NOT NULL DEFAULT 0,
    qualified_disposition_date  DATE          NULL,
    purchase_deposit_to         VARCHAR(100)  NOT NULL DEFAULT '',
    symbol                      VARCHAR(20)   NOT NULL DEFAULT 'MSFT',
    discount_pct                DECIMAL(6,2)  NOT NULL DEFAULT 0,
    bargain_element             DECIMAL(14,4) NOT NULL DEFAULT 0,
    created_at                  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_espp_purchase (offering_period_start, offering_period_end, purchase_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**Persistence strategy:** `INSERT ... ON DUPLICATE KEY UPDATE` — upserts
based on the (offering_start, offering_end, purchase_date) natural key.

---

## 5. `parse_fidelity_positions.py` — Deep Dive

### 5.1 HTML DOM Structure (Fidelity ag-grid)

Fidelity's Portfolio Positions page uses a virtualized ag-grid with two
column containers that share `row-index` attributes:

```
div.ag-pinned-left-cols-container          div.ag-center-cols-container
  ├── ag-row[row-index=0] account hdr        ├── ag-row[row-index=0] (empty)
  ├── ag-row[row-index=1] position           ├── ag-row[row-index=1] col values
  ├── ag-row[row-index=2] detail drawer      ├── ag-row[row-index=2] drawer table
  ├── ag-row[row-index=3] position           ├── ag-row[row-index=3] col values
  └── ...                                    └── ...
```

- **Account rows** (`posweb-row-account`): Contain `h3.posweb-cell-account`
  with `span.posweb-cell-account_primary` (name) and
  `span.posweb-cell-account_secondary` (number).

- **Position rows** (`posweb-row-position`): Contain ticker in a bare
  `<span>` (no class) inside the pinned-left cell; description in
  `<p class="posweb-cell-symbol-description">`.

- **Expanded positions** (`aria-expanded="true"`): Have a companion detail
  row containing `div.posweb-drawer-container` with a `<table>` of cost-basis lots.

- **Collapsed positions** (no aria-expanded, or `"false"`): Only have summary
  values readable from center-container col-ids (`curVal`, `qty`, `cstBasShr`,
  `cstBasTot`, `totGL`, `totGLPct`).

### 5.2 Table Column Layouts

Detail tables come in two formats:

| Cols | Layout                                                              | Source            |
|------|---------------------------------------------------------------------|-------------------|
| 8    | Acquired, Term, $ G/L, % G/L, Cur Value, Qty, Avg Cost, Cost Total | Regular purchases |
| 11   | Same 8 + Transfer Avail. Dates, Share Source, Grant Date            | ESPP / RSU lots   |

### 5.3 Snapshot Timestamp

Extracted from `div.acct-selector__time--expand-collapse`:
```
"As of Feb-20-2026 1:39 a.m. ET"  →  datetime(2026, 2, 20, 1, 39, 0)
```

### 5.4 Account Resolution

Binary search over sorted account boundary row-indices to assign each
position row to the correct account.

### 5.5 Key Functions

| Function                           | Purpose                                                    |
|------------------------------------|------------------------------------------------------------|
| `_extract_snapshot_timestamp(soup)` | Parse "As of ..." sidebar timestamp                       |
| `_build_account_map(soup)`          | Build row-index → account_name boundary map               |
| `_extract_identifier(pinned_row)`   | Get ticker/CUSIP from pinned-left position row            |
| `_center_cell_values(center_row)`   | Read col-id → text dict from center container             |
| `_resolve_account(idx, ...)`        | Binary-search account boundaries for a row-index          |
| `extract_positions(html_path)`      | Main parser: returns `pd.DataFrame`                       |
| `persist_to_mysql(df, owner, ...)`  | DELETE+INSERT by snapshot_date + Account_Owner upsert     |
| `print_summary(df)`                 | Console output: by-stock, by-term, by-account breakdowns  |

### 5.6 CLI Arguments

```
--file / -f       Path to HTML file  (default: see DEFAULT_HTML_PATH in script)
--database        Override MySQL database name
--owner           Owner name for Account_Owner mapping  (prompted interactively if omitted)
--dry-run         Parse and display only — skip DB write
--csv             Also save DataFrame to this CSV path
```

---

## 6. `load_espp_plan.py` — Deep Dive

### 6.1 Data Model

`@dataclass ESPPPurchase` with computed properties:
- `discount_pct` — `(fmv_offering_start - purchase_price) / fmv_offering_start × 100`
- `bargain_element` — `(fmv_purchase_date - purchase_price) × purchase_quantity`

### 6.2 CLI Arguments

```
--file / -f       Path to TSV/CSV file
--clipboard / -c  Read from clipboard (requires pyperclip)
--database        Override MySQL database name
--dry-run         Parse and display only
```

---

## 7. `share_cost_basis.py` — Deep Dive

Standalone analyzer (no database).  Uses `@dataclass ShareLot` and
`@dataclass Portfolio` with computed properties for:
- `total_quantity`, `total_cost_basis`, `total_current_value`
- `total_gain_loss`, `total_pct_gain_loss`, `weighted_avg_cost`
- `short_term_lots`, `long_term_lots`

CLI: `--file`, `--clipboard`, or embedded sample data.

---

## 8. Design Decisions & Rationale

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | DELETE + INSERT (not UPSERT) for Portfolio_Positions | Each HTML snapshot is a complete point-in-time.  No natural unique key across lots (RSU vests can have identical symbol, date, qty, cost).  Deleting by snapshot_date then inserting guarantees idempotent full-snapshot replacement. |
| 2 | Separate `Account_Owner` table | Decouples account metadata from position data.  Allows multiple owners in a household.  INSERT IGNORE means accounts accumulate across import runs. |
| 3 | Collapsed position handling via center-container col-ids | Not all accounts have expanded positions in the HTML.  Collapsed rows only have summary values in `col-id` attributes (no detail table).  Parser reads these for at least summary-level coverage, creating 1 row per collapsed position. |
| 4 | `snapshot_date` as DATETIME (not DATE) | Fidelity timestamps include time ("1:39 a.m. ET").  Using DATETIME preserves intra-day snapshots if the user saves multiple HTML exports in one day. |
| 5 | No UNIQUE KEY on Portfolio_Positions | Intentional.  RSU vest lots can be truly identical in all data columns except the HTML row order.  The DELETE-by-snapshot pattern handles dedup. |
| 6 | `--owner` interactive prompt fallback | Owner is required for DB writes but not for `--dry-run`.  Interactive prompt avoids forcing CLI arg in exploratory usage. |
| 7 | ESPP uses ON DUPLICATE KEY UPDATE | ESPP purchases have a clear natural key (offering_start + offering_end + purchase_date).  Upsert is safe and simpler than delete+insert. |
| 8 | Pinned-left container is authority for tickers and detail drawers | Center container does NOT contain drawer tables — they are nested inside the pinned-left container's position rows.  This was discovered empirically. |

---

## 9. Data Flow Diagram

```
 ┌──────────────────────────┐
 │  Fidelity HTML export    │
 │  "Portfolio Positions"   │
 └──────────┬───────────────┘
            │  parse_fidelity_positions.py
            ▼
 ┌──────────────────────────┐     ┌──────────────────────┐
 │  extract_positions()     │────▶│  pd.DataFrame        │
 │  - snapshot timestamp    │     │  185 rows (example)   │
 │  - account mapping       │     │  36 symbols           │
 │  - expanded lot parsing  │     │  6 accounts           │
 │  - collapsed summary     │     └──────────┬────────────┘
 └──────────────────────────┘                │
                                             ├──▶ --csv → CSV file
                                             ├──▶ --dry-run → print_summary()
                                             │
                                             ▼
                              ┌───────────────────────────────────┐
                              │  persist_to_mysql(df, owner)      │
                              │  1. CREATE TABLE IF NOT EXISTS    │
                              │  2. DELETE WHERE snapshot_date=X  │
                              │  3. INSERT all rows               │
                              │  4. INSERT IGNORE Account_Owner   │
                              └───────────────────────────────────┘
```

```
 ┌──────────────────────────┐
 │  ESPP TSV/CSV export     │
 └──────────┬───────────────┘
            │  load_espp_plan.py
            ▼
 ┌──────────────────────────┐     ┌──────────────────────┐
 │  parse_data(text)        │────▶│  list[ESPPPurchase]  │
 └──────────────────────────┘     └──────────┬───────────┘
                                             │
                                             ▼
                              ┌───────────────────────────────────┐
                              │  populate_table(records)          │
                              │  INSERT ... ON DUPLICATE KEY UPD  │
                              └───────────────────────────────────┘
```

---

## 10. Changelog

### 2026-06-24

- **ingest_sec_13f.py** — SEC bulk Form 13F → CUSIP reverse-holdings index (#89)
  - Downloads the quarterly Form 13F bulk data set (zip), parses `SUBMISSION`,
    `COVERPAGE`, and `INFOTABLE` TSVs, and loads `sec_13f_holdings` +
    `sec_13f_cusip_map` in `openbb_fmp_cache_test` via the existing
    `openbb_fmp_cached` DB helpers. DDL lives in
    `providers/sec/openbb_sec/utils/thirteen_f_index.py` (single source of
    truth); the ingest imports it — no `CREATE TABLE` in `Tools/`.
  - VALUE unit normalized per-period at parse (whole-USD from 2023-Q2,
    thousands before); option rows (`PUTCALL`) segregated, not summed into long
    shares. FIGI captured per-CUSIP into `sec_13f_cusip_map.figi`. Manifest row
    written to `sec_13f_ingest_runs` (period, sha256, counts, value_unit).
  - CLI: `--period`, `--user-agent` (SEC requires it), `--no-seed`, `--limit`,
    `--dry-run`. `requests` only (no `aiohttp`); idempotent ON DUPLICATE KEY.
  - Read helpers `resolve_cusip` / `holders_for_cusip` power the
    `fmp_cached` institutional-ownership SEC tier (`_try_sec_13f`), which now
    aggregates real per-manager holdings into the FMP summary schema instead of
    the old always-empty filer-indexed fetcher.
  - Verified e2e: 2023q2 ingest (59,718 holdings / 4,523 CUSIPs);
    `resolve_cusip('MSFT')`/`('AAPL')` + ranked holders confirmed.

### 2026-02-19

- **parse_fidelity_positions.py** — Created
  - Initial parser for Fidelity ag-grid HTML (pinned-left + center containers).
  - Extracted tickers from bare `<span>` tags, parsed 8-col and 11-col table layouts.
  - First successful parse: 26 stocks, 173 lots.

- **RSU duplicate lot fix** — Added `lot_sequence` column (groupby cumcount)
  to distinguish identical RSU vest lots. Later removed in favor of
  DELETE+INSERT strategy.

- **Snapshot timestamp** — Extracted `snapshot_date` from sidebar
  `div.acct-selector__time--expand-collapse` ("As of Feb-20-2026 1:39 a.m. ET").

- **Account tracking** — Rewrote parser to build account boundary map from
  pinned-left container's `row-index`.  Maps each position to its enclosing
  `posweb-row-account` header.

- **Collapsed row handling** — Positions in non-expanded accounts (401K, 529,
  ROTH IRA, HSA) had no detail drawer.  Added center-container col-id
  extraction (`curVal`, `qty`, `cstBasShr`, etc.) for summary-level coverage.
  Result: 6 accounts, 36 stocks, 185 rows.

- **Idempotent re-import** — Removed UNIQUE KEY and `lot_sequence`.  Switched
  to DELETE WHERE `snapshot_date=X` then INSERT.  Verified: re-run produces
  DELETE 185 + INSERT 185 = 185 total.

- **Account_Owner table** — Added `Account_Owner` with `--owner` CLI arg and
  interactive fallback.  INSERT IGNORE on (account_name, owner).

- **CSV export** — Added `--csv` flag.  Tested with 185 rows.

- **load_espp_plan.py** — Created (earlier in session)
  - Parses ESPP purchase history from TSV/CSV.
  - `ESPP_Plan` table with offering period, FMV, purchase price, discount %, bargain element.
  - Upsert via ON DUPLICATE KEY UPDATE.

- **share_cost_basis.py** — Created (earlier in session)
  - Standalone cost-basis analyzer.
  - Reads TSV/CSV or clipboard.  No database persistence.

- **Documentation** — Created `Tools/docs/load_espp_plan.md`.

- **Git** — Committed and pushed to branch `openbb_learning`.
  Updated `.gitignore` with `.venv_win/` and `*.sql`.

---

## 11. Known Issues & Future Work

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Default HTML path is generic | Open | `DEFAULT_HTML_PATH` uses a generic name but real files may use owner-specific names.  Consider removing the default or using glob patterns. |
| 2 | Center-container col-ids are brittle | Watch | Fidelity may change col-id values (`curVal`, `qty`, etc.) across DOM updates. |
| 3 | Collapsed positions lack lot-level detail | By design | Collapsed rows only produce 1 summary row per position.  To get lot detail, user must expand positions in the browser before saving HTML. |
| 4 | No automated tests | Open | Parser relies on real HTML fixtures.  Consider saving a sanitized HTML fragment for regression tests. |
| 5 | `share_cost_basis.py` overlaps with `parse_fidelity_positions.py` | Low | The standalone analyzer predates the HTML parser.  Could be retired or refactored as a shared analysis module. |
| 6 | Multi-snapshot time-series analysis | Future | With multiple HTML snapshots imported, build queries/views for tracking position changes over time. |
| 7 | Documentation for `parse_fidelity_positions.py` | Open | Separate user-facing doc (like `load_espp_plan.md`) not yet created. |
| 8 | Tax-lot optimization | Future | Use cost-basis data to suggest tax-optimal sell orders (specific lot ID, HIFO, FIFO). |

---

## 12. Environment Quick Reference

See `Tools/docs/CONTEXT_LOCAL.md` (git-ignored) for real paths, credentials,
and copy-pasteable commands.

Generic usage patterns:

```bash
# Fidelity parser (dry-run)
python Tools/parse_fidelity_positions.py --file <HTML_PATH> --dry-run

# Fidelity parser (DB write)
python Tools/parse_fidelity_positions.py --file <HTML_PATH> --owner <OWNER>

# ESPP loader
python Tools/load_espp_plan.py --file <TSV_PATH>

# Cost basis analyzer
python Tools/share_cost_basis.py --file <TSV_PATH>
```

---

*Last updated: 2026-02-20*
