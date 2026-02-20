"""
Fidelity Portfolio Positions HTML Parser

Parses a saved Fidelity "Portfolio Positions" web page (HTML) and extracts
every cost-basis lot into a clean pandas DataFrame, then persists it to a
MySQL table (Portfolio_Positions).

Background
----------
Fidelity's Positions page uses an ag-grid layout with two column containers:

* **Pinned-left container** (`ag-pinned-left-cols-container`) — holds
  account header rows (`posweb-row-account` with `h3.posweb-cell-account`)
  and ticker summary rows (`posweb-row-position` with `aria-expanded`).
  Account names live in `span.posweb-cell-account_primary` (e.g.
  "Individual - TOD", "MICROSOFT 401K PLAN") and account numbers in
  `span.posweb-cell-account_secondary`.

* **Center container** (`ag-center-cols-container`) — holds the matching
  account rows (empty placeholders) and position detail rows containing
  the cost-basis lot tables (`div.posweb-drawer-container`).

Both containers share the same `row-index` attribute per row, which allows
correlating account headers from the pinned-left side with position data
from the center side.

Each stock occupies two DOM rows inside `div.posweb-row-position`:

1. **Summary row** (`aria-expanded="true"`)
   Contains the ticker symbol (in a bare `<span>` without a CSS class) and
   the company description (in `<p class="posweb-cell-symbol-description">`).

2. **Detail row** (contains `div.posweb-drawer-container`)
   Contains a `<table>` with one header row and N data rows — one per cost-
   basis lot.  The header columns are either:

   * **8-column layout** (regular brokerage purchases):
     Acquired | Term | $ Total gain/loss | % Total gain/loss |
     Current value | Quantity | Average cost basis | Cost basis total

   * **11-column layout** (employer stock-plan shares — ESPP / RSU):
     Same 8 columns + Transfer Avail. Dates | Share Source | Grant Date

Snapshot Timestamp
------------------
The sidebar contains a timestamp like "As of Feb-20-2026 1:39 a.m. ET" in
`div.acct-selector__time--expand-collapse`.  This is parsed as the
`snapshot_date` (DATETIME) and stored with every row, allowing multiple
HTML snapshots to coexist in the same table.

Account Tracking
----------------
Account rows (`div.posweb-row-account`) appear in document order before
their child positions.  The parser builds an account boundary map from
`row-index` attributes in the pinned-left container, then assigns each
position row to its enclosing account section.

The script normalises both column layouts into a single DataFrame with all
data columns plus ticker, description, account_name, and snapshot_date.

Parsing Strategy
----------------
1. Load the HTML with BeautifulSoup.
2. Extract the snapshot timestamp from the sidebar.
3. Build an account-boundary map from `ag-row` elements in the pinned-left
   container: each account's `row-index` marks the start of its section.
4. Walk `ag-row` elements in the **pinned-left** container in `row-index`
   order, correlating with the **center** container by `row-index`.
5. Use the account boundary map to assign `account_name` to each position.
6. **Expanded positions** (`aria-expanded="true"` + detail drawer row):
   Extract the ticker from the pinned-left row and parse lot-level detail
   from the `<table>` inside the drawer.
7. **Collapsed positions** (no expansion): extract the ticker or identifier
   (CUSIP) from the pinned-left row and read summary values (`curVal`,
   `qty`, `cstBasShr`, `cstBasTot`, `totGL`, `totGLPct`) from the matching
   center-container row.  These become a single-lot record.
8. Currency/percentage strings are cleaned to numeric floats.
9. Date strings (e.g. "Jun-13-2022") are parsed to `datetime.date`.
10. The result is a pandas DataFrame ready for analysis or DB persistence.

Persistence Strategy
--------------------
Each HTML file is a complete snapshot identified by its ``snapshot_date``.
On import, all existing rows with the same ``snapshot_date`` are deleted
before inserting, making re-imports idempotent.

Usage
-----
    python Tools/parse_fidelity_positions.py
    python Tools/parse_fidelity_positions.py --file "path/to/Portfolio Positions.html"
    python Tools/parse_fidelity_positions.py --dry-run          # parse only, no DB write
    python Tools/parse_fidelity_positions.py --database my_db   # target specific database

Table: Portfolio_Positions
--------------------------
See CREATE_TABLE_SQL below for the full schema.
"""

import argparse
import os
import re
import sys
from datetime import date, datetime
from typing import List, Optional, Tuple

import pandas as pd
from bs4 import BeautifulSoup, Tag

# ---------------------------------------------------------------------------
# Ensure fmp_cached provider is importable (for DatabaseConfig)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIRS = [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]
_ext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "extensions")
if os.path.isdir(_ext_root):
    for _d in os.listdir(_ext_root):
        _dp = os.path.join(_ext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)
_obbext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "obbject_extensions")
if os.path.isdir(_obbext_root):
    for _d in os.listdir(_obbext_root):
        _dp = os.path.join(_obbext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)
for _p in _SRC_DIRS:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Default HTML path
# ---------------------------------------------------------------------------
DEFAULT_HTML_PATH = r"I:\masterswork\FinanceData\Portfolio Positions.html"

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_currency(val: str) -> float:
    """Parse a Fidelity currency string to float.

    Examples:
        '$10,423.20'  -> 10423.20
        '+$5,104.47'  -> 5104.47
        '-$183.70'    -> -183.70
        '($605.38)'   -> -605.38
        '--'          -> 0.0
    """
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = val.strip()
    negative = cleaned.startswith("-") or "(" in cleaned
    cleaned = re.sub(r"[+$,()A-Za-z\s]", "", cleaned)
    try:
        result = float(cleaned)
        return -result if negative else result
    except ValueError:
        return 0.0


def parse_percent(val: str) -> float:
    """Parse a percentage string like '+95.97%' or '-100%' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = re.sub(r"[%+\s]", "", val.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_quantity(val: str) -> float:
    """Parse a quantity string like '40' or '6.506' or '10,000' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = re.sub(r"[,\s]", "", val.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date_str(val: str) -> Optional[date]:
    """Parse Fidelity date strings like 'Jun-13-2022' or '--' to date.

    Supports:  'Jun-13-2022', '06/13/2022', '2022-06-13'
    """
    if not val or val.strip() in ("--", "N/A", ""):
        return None
    val = val.strip()
    for fmt in ("%b-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Core HTML parser
# ---------------------------------------------------------------------------

def _extract_snapshot_timestamp(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract the 'As of ...' timestamp from the Fidelity sidebar.

    Looks for text like 'As of Feb-20-2026 1:39 a.m. ET' inside
    ``div.acct-selector__time--expand-collapse`` or, as fallback, any
    element matching the pattern.

    Returns a timezone-naive datetime or None.
    """
    # Primary location
    ts_div = soup.find("div", class_="acct-selector__time--expand-collapse")
    if ts_div:
        txt = ts_div.get_text(strip=True)
    else:
        # Fallback: search broadly
        hit = soup.find(string=re.compile(r"As of \w{3}-\d{2}-\d{4}"))
        txt = hit.strip() if hit else ""

    if not txt:
        return None

    # "As of Feb-20-2026 1:39 a.m. ET"
    m = re.search(
        r"As of\s+([A-Za-z]{3}-\d{2}-\d{4})\s+(\d{1,2}:\d{2})\s*(a\.m\.|p\.m\.)",
        txt,
    )
    if not m:
        return None

    date_part = m.group(1)             # "Feb-20-2026"
    time_part = m.group(2)             # "1:39"
    ampm = m.group(3).replace(".", "")  # "am" / "pm"
    combined = f"{date_part} {time_part} {ampm}"
    for fmt in ("%b-%d-%Y %I:%M %p", "%b-%d-%Y %I:%M%p"):
        try:
            return datetime.strptime(combined, fmt)
        except ValueError:
            continue
    return None


def _build_account_map(soup: BeautifulSoup) -> dict:
    """Build a row-index → account-name mapping from the pinned-left container.

    Returns
    -------
    dict
        ``{row_index_int: "Account Name (Number)", ...}``
        e.g. ``{0: "Individual - TOD (X65957336)", 57: "Traditional IRA (261802512)"}``
    """
    pinned = soup.find("div", class_="ag-pinned-left-cols-container")
    if not pinned:
        return {}

    acct_map: dict = {}  # row_index -> account label
    for ag_row in pinned.find_all("div", class_="ag-row", recursive=False):
        if "posweb-row-account" not in ag_row.get("class", []):
            continue
        row_idx_str = ag_row.get("row-index", "")
        if not row_idx_str.isdigit():
            continue
        h3 = ag_row.find("h3", class_="posweb-cell-account")
        if not h3:
            continue
        name_el = h3.find("span", class_="posweb-cell-account_primary")
        num_el = h3.find("span", class_="posweb-cell-account_secondary")
        name = name_el.get_text(strip=True) if name_el else "Unknown"
        num = num_el.get_text(strip=True) if num_el else ""
        label = f"{name} ({num})" if num else name
        acct_map[int(row_idx_str)] = label

    return acct_map


def _resolve_account(row_index: int, account_boundaries: List[int],
                     account_map: dict) -> str:
    """Return the account name for a given row-index.

    Uses the sorted account boundary list to find the account whose
    start-index is <= row_index.
    """
    acct_idx = 0
    for boundary in account_boundaries:
        if boundary <= row_index:
            acct_idx = boundary
        else:
            break
    return account_map.get(acct_idx, "Unknown")


def _extract_identifier(pinned_row: Tag) -> Tuple[str, str]:
    """Extract a (symbol_or_id, description) from a pinned-left position row.

    For expanded rows the ticker is in a bare ``<span>`` (e.g. "MSFT").
    For collapsed rows the text may be a ticker ("MTUM"), a CUSIP
    ("09261F614"), a fund code ("NHX202764"), or "Cash".

    Returns
    -------
    (identifier, description)
        *identifier* is the best available symbol/CUSIP/label.
        *description* is the company/fund name.
    """
    identifier = ""
    for sp in pinned_row.find_all("span"):
        if sp.get("class"):
            continue
        t = sp.get_text(strip=True)
        if not t:
            continue
        # Skip filler labels
        if t in ("Not Priced Today", "Margin position"):
            continue
        # Short text without spaces is likely a ticker, CUSIP, or code
        if len(t) <= 12 and " " not in t:
            identifier = t
            break

    desc_el = pinned_row.find("p", class_="posweb-cell-symbol-description")
    desc = desc_el.get_text(strip=True) if desc_el else ""

    # If identifier looks like a real ticker keep it uppercase;
    # CUSIPs/codes are kept as-is.
    return identifier, desc


def _center_cell_values(center_row: Optional[Tag]) -> dict:
    """Read col-id → text from a center-container position row."""
    if not center_row:
        return {}
    result = {}
    for cell in center_row.find_all("div", class_="ag-cell"):
        col_id = cell.get("col-id", "")
        txt = cell.get_text(strip=True)
        if col_id and txt and txt != "--":
            result[col_id] = txt
    return result


def extract_positions(html_path: str) -> pd.DataFrame:
    """Parse the Fidelity Portfolio Positions HTML into a DataFrame.

    Handles both **expanded** positions (with per-lot detail tables) and
    **collapsed** positions (summary-only rows).  Collapsed rows are
    converted to a single-lot record using the summary values available
    in the center container (``curVal``, ``qty``, ``cstBasShr``,
    ``cstBasTot``, ``totGL``, ``totGLPct``).

    Returns a DataFrame with one row per cost-basis lot, columns:
        account_name, snapshot_date, symbol, description, acquired, term,
        total_gain_loss, pct_gain_loss, current_value, quantity,
        avg_cost_basis, cost_basis_total, transfer_avail_date,
        share_source, grant_date

    Parameters
    ----------
    html_path : str
        Path to the saved HTML file.
    """
    with open(html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # --- Snapshot timestamp ---
    snapshot_dt = _extract_snapshot_timestamp(soup)

    # --- Account boundary map (from pinned-left container) ---
    account_map = _build_account_map(soup)
    account_boundaries = sorted(account_map.keys())

    # --- Build center-container row-index lookup ---
    center_cont = soup.find("div", class_="ag-center-cols-container")
    center_by_idx: dict = {}  # row-index int -> center Tag
    if center_cont:
        for cr in center_cont.find_all("div", class_="ag-row", recursive=False):
            ri = cr.get("row-index", "")
            if ri.isdigit():
                center_by_idx[int(ri)] = cr

    # --- Walk pinned-left container rows in row-index order ---
    pinned = soup.find("div", class_="ag-pinned-left-cols-container")
    if not pinned:
        return pd.DataFrame()

    ag_rows = pinned.find_all("div", class_="ag-row", recursive=False)
    ag_rows.sort(key=lambda r: int(r.get("row-index", "9999")))

    records: List[dict] = []
    current_ticker: str = ""
    current_desc: str = ""
    # Track which row-indices have been consumed by expanded detail rows
    # so we don't double-count them as collapsed.
    consumed_indices: set = set()

    for row in ag_rows:
        row_classes = row.get("class", [])
        row_idx = int(row.get("row-index", "-1"))

        # Skip account rows
        if "posweb-row-account" in row_classes:
            continue

        if "posweb-row-position" not in row_classes:
            continue

        # Resolve account for this position
        current_account = _resolve_account(
            row_idx, account_boundaries, account_map
        )

        expanded = row.get("aria-expanded", "")
        has_drawer = row.find(class_="posweb-drawer-container") is not None

        # ---- EXPANDED: summary row (ticker + description) ----
        if expanded == "true":
            current_ticker, current_desc = _extract_identifier(row)
            consumed_indices.add(row_idx)
            continue  # the detail row follows

        # ---- EXPANDED: detail row with lot-level table ----
        if has_drawer and current_ticker:
            consumed_indices.add(row_idx)
            table = row.find("table")
            if not table:
                continue

            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            is_employer_plan = len(headers) >= 11

            data_trs = table.find_all("tr")[1:]  # skip header
            for tr in data_trs:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) < 8:
                    continue

                rec = {
                    "account_name": current_account,
                    "snapshot_date": snapshot_dt,
                    "symbol": current_ticker,
                    "description": current_desc,
                    "acquired": parse_date_str(cells[0]),
                    "term": cells[1],
                    "total_gain_loss": parse_currency(cells[2]),
                    "pct_gain_loss": parse_percent(cells[3]),
                    "current_value": parse_currency(cells[4]),
                    "quantity": parse_quantity(cells[5]),
                    "avg_cost_basis": parse_currency(cells[6]),
                    "cost_basis_total": parse_currency(cells[7]),
                    "transfer_avail_date": parse_date_str(cells[8]) if is_employer_plan and len(cells) > 8 else None,
                    "share_source": cells[9] if is_employer_plan and len(cells) > 9 else "",
                    "grant_date": parse_date_str(cells[10]) if is_employer_plan and len(cells) > 10 else None,
                }
                records.append(rec)
            continue

        # ---- COLLAPSED: single summary row (no lot detail) ----
        if row_idx not in consumed_indices:
            identifier, desc = _extract_identifier(row)
            if not identifier:
                continue  # skip rows with no identifier at all

            # Read summary values from center container
            cv = _center_cell_values(center_by_idx.get(row_idx))

            rec = {
                "account_name": current_account,
                "snapshot_date": snapshot_dt,
                "symbol": identifier,
                "description": desc,
                "acquired": None,       # not available in collapsed view
                "term": "",
                "total_gain_loss": parse_currency(cv.get("totGL", "")),
                "pct_gain_loss": parse_percent(cv.get("totGLPct", "")),
                "current_value": parse_currency(cv.get("curVal", "")),
                "quantity": parse_quantity(cv.get("qty", "")),
                "avg_cost_basis": parse_currency(cv.get("cstBasShr", "")),
                "cost_basis_total": parse_currency(cv.get("cstBasTot", "")),
                "transfer_avail_date": None,
                "share_source": "",
                "grant_date": None,
            }
            records.append(rec)

    df = pd.DataFrame(records)

    # Ensure proper dtypes
    if not df.empty:
        df["acquired"] = pd.to_datetime(df["acquired"])
        df["transfer_avail_date"] = pd.to_datetime(df["transfer_avail_date"])
        df["grant_date"] = pd.to_datetime(df["grant_date"])
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])

    return df


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame) -> None:
    """Print a human-readable summary of the parsed positions."""
    sep = "=" * 90

    print(f"\n{sep}")
    print("  FIDELITY PORTFOLIO POSITIONS — COST BASIS LOTS")
    print(sep)

    # Snapshot timestamp
    if "snapshot_date" in df.columns and df["snapshot_date"].notna().any():
        snap = df["snapshot_date"].dropna().iloc[0]
        print(f"\n  Snapshot:             {snap}")

    # Account count
    if "account_name" in df.columns:
        print(f"  Accounts:             {df['account_name'].nunique()}")

    print(f"  Total stocks:         {df['symbol'].nunique()}")
    print(f"  Total lots:           {len(df)}")
    print(f"  Total quantity:       {df['quantity'].sum():,.3f} shares")
    print(f"  Total cost basis:     ${df['cost_basis_total'].sum():>14,.2f}")
    print(f"  Total current value:  ${df['current_value'].sum():>14,.2f}")
    print(f"  Total gain/loss:      ${df['total_gain_loss'].sum():>14,.2f}")

    total_cost = df["cost_basis_total"].sum()
    total_gl = df["total_gain_loss"].sum()
    pct = (total_gl / total_cost * 100) if total_cost else 0
    print(f"  Overall return:       {pct:>13.2f}%")

    # By-stock summary
    print(f"\n{sep}")
    print("  BY STOCK")
    print(sep)
    print(f"  {'Symbol':<8} {'Lots':>5} {'Qty':>12} {'Cost Basis':>14} "
          f"{'Cur Value':>14} {'Gain/Loss':>14} {'Return':>8}")
    print(f"  {'-'*8} {'-'*5} {'-'*12} {'-'*14} {'-'*14} {'-'*14} {'-'*8}")

    grp = df.groupby("symbol").agg(
        lots=("symbol", "count"),
        quantity=("quantity", "sum"),
        cost_basis=("cost_basis_total", "sum"),
        current_value=("current_value", "sum"),
        gain_loss=("total_gain_loss", "sum"),
    ).sort_values("gain_loss", ascending=False)

    for sym, row in grp.iterrows():
        ret = (row.gain_loss / row.cost_basis * 100) if row.cost_basis else 0
        print(
            f"  {sym:<8} {row.lots:>5} {row.quantity:>12,.3f} "
            f"${row.cost_basis:>13,.2f} ${row.current_value:>13,.2f} "
            f"${row.gain_loss:>13,.2f} {ret:>7.1f}%"
        )

    # Term breakdown
    print(f"\n{sep}")
    print("  BY HOLDING PERIOD")
    print(sep)
    for term in ["Long", "Short"]:
        subset = df[df["term"] == term]
        if subset.empty:
            continue
        tc = subset["cost_basis_total"].sum()
        tv = subset["current_value"].sum()
        tg = subset["total_gain_loss"].sum()
        ret = (tg / tc * 100) if tc else 0
        print(f"  {term}-term:  {len(subset):>4} lots | "
              f"Cost ${tc:>12,.2f} | Value ${tv:>12,.2f} | "
              f"G/L ${tg:>12,.2f} ({ret:+.1f}%)")

    # Employer plan lots
    plan_lots = df[df["share_source"].str.strip().ne("") & df["share_source"].notna()]
    if not plan_lots.empty:
        print(f"\n{sep}")
        print(f"  EMPLOYER PLAN LOTS (ESPP/RSU): {len(plan_lots)} lots")
        print(sep)
        sources = plan_lots["share_source"].value_counts()
        for src, cnt in sources.items():
            print(f"    {src}: {cnt} lots")

    # By-account summary
    if "account_name" in df.columns:
        print(f"\n{sep}")
        print("  BY ACCOUNT")
        print(sep)
        print(f"  {'Account':<40} {'Lots':>5} {'Cost Basis':>14} "
              f"{'Cur Value':>14} {'Gain/Loss':>14}")
        print(f"  {'-'*40} {'-'*5} {'-'*14} {'-'*14} {'-'*14}")

        agrp = df.groupby("account_name").agg(
            lots=("symbol", "count"),
            cost_basis=("cost_basis_total", "sum"),
            current_value=("current_value", "sum"),
            gain_loss=("total_gain_loss", "sum"),
        ).sort_values("current_value", ascending=False)

        for acct, row in agrp.iterrows():
            print(
                f"  {str(acct)[:40]:<40} {row.lots:>5} "
                f"${row.cost_basis:>13,.2f} ${row.current_value:>13,.2f} "
                f"${row.gain_loss:>13,.2f}"
            )

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# MySQL persistence
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Portfolio_Positions (
    id                 INT AUTO_INCREMENT PRIMARY KEY,

    -- Snapshot identification
    snapshot_date      DATETIME      NULL,              -- "As of" timestamp from the HTML page
    account_name       VARCHAR(100)  NOT NULL DEFAULT '',-- Account: "Individual - TOD (X65957336)"

    -- Stock identification
    symbol             VARCHAR(20)   NOT NULL,          -- Ticker symbol, CUSIP, or fund code
    description        VARCHAR(200)  NOT NULL DEFAULT '',-- Company/fund name from Fidelity

    -- Cost-basis lot details (lot-level for expanded, summary for collapsed)
    acquired           DATE          NULL,              -- Date shares were acquired (NULL if collapsed)
    term               VARCHAR(10)   NOT NULL DEFAULT '',-- Holding period: "Short" or "Long"
    total_gain_loss    DECIMAL(14,4) NOT NULL DEFAULT 0,-- Unrealized $ gain/loss for this lot
    pct_gain_loss      DECIMAL(8,2)  NOT NULL DEFAULT 0,-- Unrealized % gain/loss
    current_value      DECIMAL(14,4) NOT NULL DEFAULT 0,-- Current market value of this lot
    quantity           DECIMAL(14,4) NOT NULL DEFAULT 0,-- Number of shares in this lot
    avg_cost_basis     DECIMAL(12,4) NOT NULL DEFAULT 0,-- Per-share cost basis
    cost_basis_total   DECIMAL(14,4) NOT NULL DEFAULT 0,-- Total cost basis = qty × avg cost

    -- Employer stock-plan fields (ESPP / RSU) — NULL for regular purchases
    transfer_avail_date DATE        NULL,              -- Date shares become transferable
    share_source       VARCHAR(50)  NOT NULL DEFAULT '',-- Source: "Deposit only", "ESPP", etc.
    grant_date         DATE         NULL,              -- Original grant/vest date

    -- Audit
    created_at         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Index on snapshot for fast delete-before-reimport
    INDEX idx_snapshot (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_SQL = """
INSERT INTO Portfolio_Positions
    (snapshot_date, account_name, symbol, description, acquired, term,
     total_gain_loss, pct_gain_loss, current_value, quantity,
     avg_cost_basis, cost_basis_total,
     transfer_avail_date, share_source, grant_date)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

CREATE_ACCOUNT_OWNER_SQL = """
CREATE TABLE IF NOT EXISTS Account_Owner (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    account_name    VARCHAR(100)  NOT NULL,          -- e.g. "Individual - TOD (X65957336)"
    owner           VARCHAR(100)  NOT NULL,          -- e.g. "Pranav"
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_account_owner (account_name, owner)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_ACCOUNT_OWNER_SQL = """
INSERT IGNORE INTO Account_Owner (account_name, owner)
VALUES (%s, %s)
"""


def get_connection(database: Optional[str] = None):
    """Get a pymysql connection, optionally overriding the database name."""
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    config = DatabaseConfig()
    params = config.connection_params
    if database:
        params["database"] = database

    db_name = params.pop("database")
    conn = pymysql.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
    finally:
        conn.close()

    params["database"] = db_name
    return pymysql.connect(
        **params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def persist_to_mysql(df: pd.DataFrame, owner: str = "",
                     database: Optional[str] = None) -> dict:
    """Persist a snapshot to MySQL.

    Strategy: DELETE all rows with the same ``snapshot_date``, then INSERT
    all rows from the DataFrame.  This makes re-imports of the same HTML
    file fully idempotent.

    Also populates the ``Account_Owner`` table with distinct account names
    mapped to the given *owner*.

    Returns a summary dict.
    """
    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(CREATE_ACCOUNT_OWNER_SQL)

            # Populate Account_Owner
            if owner and "account_name" in df.columns:
                for acct in df["account_name"].dropna().unique():
                    cur.execute(INSERT_ACCOUNT_OWNER_SQL, (acct, owner))

            # Determine snapshot datetime for the delete sweep
            snap_val = None
            if "snapshot_date" in df.columns and df["snapshot_date"].notna().any():
                snap_val = df["snapshot_date"].dropna().iloc[0]

            # Delete previous import of this snapshot (idempotent re-import)
            if snap_val is not None:
                cur.execute(
                    "DELETE FROM Portfolio_Positions WHERE snapshot_date = %s",
                    (snap_val,),
                )
                deleted = cur.rowcount
            else:
                deleted = 0

            # Insert all rows
            inserted = 0
            for _, row in df.iterrows():
                snapshot = row["snapshot_date"] if pd.notna(row["snapshot_date"]) else None
                acquired = row["acquired"].date() if pd.notna(row["acquired"]) else None
                transfer = row["transfer_avail_date"].date() if pd.notna(row["transfer_avail_date"]) else None
                grant = row["grant_date"].date() if pd.notna(row["grant_date"]) else None

                cur.execute(INSERT_SQL, (
                    snapshot,
                    row["account_name"],
                    row["symbol"],
                    row["description"],
                    acquired,
                    row["term"],
                    float(row["total_gain_loss"]),
                    float(row["pct_gain_loss"]),
                    float(row["current_value"]),
                    float(row["quantity"]),
                    float(row["avg_cost_basis"]),
                    float(row["cost_basis_total"]),
                    transfer,
                    row["share_source"] or "",
                    grant,
                ))
                inserted += cur.rowcount

            cur.execute("SELECT COUNT(*) AS cnt FROM Portfolio_Positions")
            total = cur.fetchone()["cnt"]

        db_name = conn.db.decode() if isinstance(conn.db, bytes) else conn.db
        return {
            "database": db_name,
            "deleted": deleted,
            "inserted": inserted,
            "total_rows": total,
            "stocks": df["symbol"].nunique(),
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse Fidelity Portfolio Positions HTML and load into MySQL"
    )
    parser.add_argument(
        "--file", "-f",
        default=DEFAULT_HTML_PATH,
        help=f"Path to saved HTML file (default: {DEFAULT_HTML_PATH})",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database name (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--owner",
        default=None,
        help="Owner name for this snapshot (e.g. 'Pranav'). "
             "Prompted interactively if omitted and not --dry-run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display only — do not write to database",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Also save DataFrame to this CSV path",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        sys.exit(1)

    print(f"Parsing: {args.file}")
    df = extract_positions(args.file)

    if df.empty:
        print("No portfolio positions found.")
        sys.exit(1)

    print_summary(df)

    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Saved CSV: {args.csv}")

    if args.dry_run:
        print("Dry-run mode — skipping database write.")
        return

    # Resolve owner name
    owner = args.owner
    if not owner:
        owner = input("Enter owner name for this snapshot: ").strip()
    if not owner:
        print("Owner name is required for database import.")
        sys.exit(1)
    print(f"Owner: {owner}")

    print(f"Writing {len(df)} row(s) to Portfolio_Positions table ...")
    stats = persist_to_mysql(df, owner=owner, database=args.database)

    print(f"\n{'='*50}")
    print(f"  Done — database: {stats['database']}")
    print(f"  Stocks:          {stats['stocks']}")
    print(f"  Deleted (prior): {stats['deleted']}")
    print(f"  Inserted:        {stats['inserted']}")
    print(f"  Total rows:      {stats['total_rows']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
