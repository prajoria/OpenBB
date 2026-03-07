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
DEFAULT_FORTRESS_CSV_PATH = r"I:\masterswork\git\OpenBB\Analysis\FortressFinal.csv"

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
    basket_name        VARCHAR(200)  NOT NULL DEFAULT '',-- Basket name for basket-derived rows

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
    INDEX idx_snapshot (snapshot_date),
    INDEX idx_account_basket (account_name, basket_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_SQL = """
INSERT INTO Portfolio_Positions
    (snapshot_date, account_name, basket_name, symbol, description, acquired, term,
     total_gain_loss, pct_gain_loss, current_value, quantity,
     avg_cost_basis, cost_basis_total,
     transfer_avail_date, share_source, grant_date)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

CREATE_PORTFOLIO_BASKET_SQL = """
CREATE TABLE IF NOT EXISTS portfolio_basket (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_date        DATETIME       NOT NULL,
    symbol               VARCHAR(20)    NOT NULL,
    description          VARCHAR(200)   NOT NULL DEFAULT '',
    total_quantity       DECIMAL(14,4)  NOT NULL DEFAULT 0,
    total_cost_basis     DECIMAL(14,4)  NOT NULL DEFAULT 0,
    total_current_value  DECIMAL(14,4)  NOT NULL DEFAULT 0,
    total_gain_loss      DECIMAL(14,4)  NOT NULL DEFAULT 0,
    pct_return           DECIMAL(8,2)   NOT NULL DEFAULT 0,
    portfolio_weight_pct DECIMAL(8,4)   NOT NULL DEFAULT 0,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_snapshot_symbol (snapshot_date, symbol),
    INDEX idx_basket_snapshot (snapshot_date),
    INDEX idx_basket_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_PORTFOLIO_BASKET_SQL = """
INSERT INTO portfolio_basket
    (snapshot_date, symbol, description, total_quantity, total_cost_basis,
     total_current_value, total_gain_loss, pct_return, portfolio_weight_pct)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

CREATE_BASKET_INTENDED_WEIGHT_SQL = """
CREATE TABLE IF NOT EXISTS basket_intended_weight (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    import_date          DATETIME       NOT NULL,
    basket_name          VARCHAR(200)   NOT NULL,
    symbol               VARCHAR(20)    NOT NULL,
    description          VARCHAR(255)   NOT NULL DEFAULT '',
    target_weight_pct    DECIMAL(8,4)   NOT NULL DEFAULT 0,
    proposal             VARCHAR(120)   NOT NULL DEFAULT '',
    pillar               VARCHAR(120)   NOT NULL DEFAULT '',
    asset_type           VARCHAR(120)   NOT NULL DEFAULT '',
    sector               VARCHAR(120)   NOT NULL DEFAULT '',
    style                VARCHAR(120)   NOT NULL DEFAULT '',
    region               VARCHAR(120)   NOT NULL DEFAULT '',
    strategy_bucket      VARCHAR(120)   NOT NULL DEFAULT '',
    role                 VARCHAR(255)   NOT NULL DEFAULT '',
    owner                VARCHAR(100)   NOT NULL DEFAULT '',
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_biw_basket_date (basket_name, import_date),
    INDEX idx_biw_symbol (symbol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_BASKET_INTENDED_WEIGHT_SQL = """
INSERT INTO basket_intended_weight
    (import_date, basket_name, symbol, description, target_weight_pct,
     proposal, pillar, asset_type, sector, style, region, strategy_bucket, role, owner)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def persist_basket_intended_weight_csv(
    csv_path: str,
    basket_name: str,
    database: Optional[str] = None,
    owner: str = "",
) -> dict:
    """Import intended basket weights from a preprocessed CSV file."""
    source_df = pd.read_csv(csv_path)
    if source_df.empty:
        raise ValueError(f"CSV has no rows: {csv_path}")

    required_cols = {"ticker", "target_weight_pct"}
    missing = [c for c in required_cols if c not in source_df.columns]
    if missing:
        raise ValueError(
            f"CSV missing required columns: {missing}. Found: {list(source_df.columns)}"
        )

    import_dt = datetime.now().replace(microsecond=0)
    basket_label = _clean_text(basket_name) or "Fortress"

    df = source_df.copy()
    df["symbol"] = df["ticker"].astype(str).str.strip().str.upper()
    if "name" in df.columns:
        df["description"] = df["name"].astype(str).fillna("").str.strip()
    else:
        df["description"] = ""
    df["target_weight_pct"] = pd.to_numeric(df["target_weight_pct"], errors="coerce").fillna(0.0)

    string_cols = [
        "proposal",
        "pillar",
        "asset_type",
        "sector",
        "style",
        "region",
        "strategy_bucket",
        "role",
    ]
    for col in string_cols:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("").astype(str).str.strip()

    df = df[df["symbol"].ne("")].copy()
    if df.empty:
        raise ValueError("CSV has no valid symbol rows after normalization")

    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_BASKET_INTENDED_WEIGHT_SQL)

            inserted = 0
            for _, row in df.iterrows():
                cur.execute(
                    INSERT_BASKET_INTENDED_WEIGHT_SQL,
                    (
                        import_dt,
                        basket_label,
                        row["symbol"],
                        row["description"],
                        float(row["target_weight_pct"]),
                        row["proposal"],
                        row["pillar"],
                        row["asset_type"],
                        row["sector"],
                        row["style"],
                        row["region"],
                        row["strategy_bucket"],
                        row["role"],
                        owner or "",
                    ),
                )
                inserted += cur.rowcount

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM basket_intended_weight WHERE basket_name = %s",
                (basket_label,),
            )
            basket_total_rows = int(cur.fetchone()["cnt"])

        db_name = conn.db.decode() if isinstance(conn.db, bytes) else conn.db
        return {
            "database": db_name,
            "basket_name": basket_label,
            "import_date": import_dt,
            "inserted": inserted,
            "csv_rows": int(len(df)),
            "unique_symbols": int(df["symbol"].nunique()),
            "target_weight_sum_pct": float(df["target_weight_pct"].sum()),
            "basket_total_rows": basket_total_rows,
        }
    finally:
        conn.close()


def build_basket_drift_report(
    basket_name: str,
    database: Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:
    """Build intended-vs-actual drift report for a basket.

    Uses the latest import_date for basket_intended_weight and the latest
    snapshot_date for the same basket in Portfolio_Positions.

    Actual weights are computed *within the basket only*:
        symbol_current_value / basket_total_current_value * 100
    """
    basket_label = _clean_text(basket_name) or "Fortress"

    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_BASKET_INTENDED_WEIGHT_SQL)
            cur.execute(CREATE_PORTFOLIO_BASKET_SQL)

            cur.execute(
                """
                SELECT MAX(import_date) AS latest_import_date
                FROM basket_intended_weight
                WHERE basket_name = %s
                """,
                (basket_label,),
            )
            latest_import = cur.fetchone()["latest_import_date"]
            if latest_import is None:
                raise ValueError(
                    f"No intended-weight data found for basket '{basket_label}'"
                )

            cur.execute(
                """
                SELECT MAX(snapshot_date) AS latest_snapshot_date
                FROM Portfolio_Positions
                WHERE basket_name = %s
                """,
                (basket_label,),
            )
            latest_snapshot = cur.fetchone()["latest_snapshot_date"]
            if latest_snapshot is None:
                raise ValueError(
                    f"No Portfolio_Positions rows found for basket '{basket_label}'"
                )

            cur.execute(
                """
                WITH basket_actual AS (
                    SELECT
                        p.snapshot_date,
                        p.symbol,
                        MAX(p.description) AS actual_description,
                        ROUND(SUM(p.current_value), 4) AS actual_total_current_value,
                        ROUND(SUM(p.cost_basis_total), 4) AS actual_total_cost_basis,
                        ROUND(SUM(p.total_gain_loss), 4) AS actual_total_gain_loss,
                        CASE
                            WHEN SUM(p.cost_basis_total) > 0
                            THEN ROUND(SUM(p.total_gain_loss) / SUM(p.cost_basis_total) * 100, 2)
                            ELSE 0
                        END AS actual_pct_return
                    FROM Portfolio_Positions p
                    WHERE p.snapshot_date = %s
                      AND p.basket_name = %s
                    GROUP BY p.snapshot_date, p.symbol
                ),
                basket_totals AS (
                    SELECT
                        snapshot_date,
                        SUM(actual_total_current_value) AS basket_total_value
                    FROM basket_actual
                    GROUP BY snapshot_date
                )
                SELECT
                    iw.symbol AS symbol,
                    iw.description AS intended_description,
                    iw.target_weight_pct AS intended_weight_pct,
                    CASE
                        WHEN COALESCE(bt.basket_total_value, 0) > 0
                        THEN ROUND(COALESCE(ba.actual_total_current_value, 0) / bt.basket_total_value * 100, 4)
                        ELSE 0
                    END AS actual_weight_pct,
                    COALESCE(ba.actual_description, '') AS actual_description,
                    COALESCE(ba.actual_total_current_value, 0) AS actual_total_current_value,
                    COALESCE(ba.actual_total_cost_basis, 0) AS actual_total_cost_basis,
                    COALESCE(ba.actual_total_gain_loss, 0) AS actual_total_gain_loss,
                    COALESCE(ba.actual_pct_return, 0) AS actual_pct_return
                FROM basket_intended_weight iw
                LEFT JOIN basket_actual ba
                  ON ba.symbol = iw.symbol
                LEFT JOIN basket_totals bt
                  ON bt.snapshot_date = ba.snapshot_date
                WHERE iw.basket_name = %s
                  AND iw.import_date = %s
                ORDER BY ABS(
                    (
                        CASE
                            WHEN COALESCE(bt.basket_total_value, 0) > 0
                            THEN ROUND(COALESCE(ba.actual_total_current_value, 0) / bt.basket_total_value * 100, 4)
                            ELSE 0
                        END
                    ) - iw.target_weight_pct
                ) DESC,
                         iw.symbol ASC
                """,
                (latest_snapshot, basket_label, basket_label, latest_import),
            )
            rows = cur.fetchall()

        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError(
                f"No comparable rows for basket '{basket_label}' at import {latest_import}"
            )

        df["description"] = df["actual_description"].where(
            df["actual_description"].astype(str).str.strip().ne(""),
            df["intended_description"],
        )
        df["drift_pct"] = (df["actual_weight_pct"] - df["intended_weight_pct"]).round(4)
        df["abs_drift_pct"] = df["drift_pct"].abs().round(4)
        df["missing_in_actual"] = (df["actual_total_current_value"].astype(float) <= 0).astype(int)

        summary = {
            "basket_name": basket_label,
            "latest_import_date": latest_import,
            "latest_snapshot_date": latest_snapshot,
            "rows": int(len(df)),
            "symbols_missing_in_actual": int(df["missing_in_actual"].sum()),
            "intended_weight_sum_pct": float(df["intended_weight_pct"].sum()),
            "actual_weight_sum_pct": float(df["actual_weight_pct"].sum()),
            "max_abs_drift_pct": float(df["abs_drift_pct"].max()),
            "avg_abs_drift_pct": float(df["abs_drift_pct"].mean()),
        }

        display_cols = [
            "symbol",
            "description",
            "intended_weight_pct",
            "actual_weight_pct",
            "drift_pct",
            "abs_drift_pct",
            "missing_in_actual",
            "actual_pct_return",
        ]
        return df[display_cols].copy(), summary
    finally:
        conn.close()


def _build_portfolio_basket_rows(df: pd.DataFrame) -> list[dict]:
    """Build symbol-level aggregated basket rows with portfolio weights."""
    if df.empty:
        return []

    grouped = (
        df.groupby("symbol", as_index=False)
        .agg(
            description=("description", "first"),
            total_quantity=("quantity", "sum"),
            total_cost_basis=("cost_basis_total", "sum"),
            total_current_value=("current_value", "sum"),
            total_gain_loss=("total_gain_loss", "sum"),
        )
    )

    total_portfolio_value = float(grouped["total_current_value"].sum())
    if total_portfolio_value > 0:
        grouped["portfolio_weight_pct"] = (
            grouped["total_current_value"] / total_portfolio_value * 100
        )
    else:
        grouped["portfolio_weight_pct"] = 0.0

    cost = grouped["total_cost_basis"].replace(0, float("nan"))
    grouped["pct_return"] = ((grouped["total_gain_loss"] / cost) * 100).round(2).fillna(0)

    for col in (
        "total_quantity",
        "total_cost_basis",
        "total_current_value",
        "total_gain_loss",
        "portfolio_weight_pct",
    ):
        grouped[col] = grouped[col].astype(float)

    return grouped.to_dict(orient="records")


def _ensure_portfolio_positions_schema(cur) -> None:
    """Apply additive schema migrations for Portfolio_Positions."""
    cur.execute("SHOW COLUMNS FROM Portfolio_Positions LIKE 'basket_name'")
    if cur.fetchone() is None:
        cur.execute(
            "ALTER TABLE Portfolio_Positions "
            "ADD COLUMN basket_name VARCHAR(200) NOT NULL DEFAULT '' AFTER account_name"
        )
        cur.execute(
            "ALTER TABLE Portfolio_Positions "
            "ADD INDEX idx_account_basket (account_name, basket_name)"
        )


def _rebuild_portfolio_basket_for_snapshot(cur, snapshot_value) -> tuple[int, int]:
    """Rebuild portfolio_basket rows for one snapshot from Portfolio_Positions."""
    cur.execute(
        "DELETE FROM portfolio_basket WHERE snapshot_date = %s",
        (snapshot_value,),
    )
    deleted_basket = cur.rowcount

    cur.execute(
        """
        INSERT INTO portfolio_basket
            (snapshot_date, symbol, description, total_quantity, total_cost_basis,
             total_current_value, total_gain_loss, pct_return, portfolio_weight_pct)
        SELECT
            pp.snapshot_date,
            pp.symbol,
            MAX(pp.description) AS description,
            ROUND(SUM(pp.quantity), 4) AS total_quantity,
            ROUND(SUM(pp.cost_basis_total), 4) AS total_cost_basis,
            ROUND(SUM(pp.current_value), 4) AS total_current_value,
            ROUND(SUM(pp.total_gain_loss), 4) AS total_gain_loss,
            CASE
                WHEN SUM(pp.cost_basis_total) > 0
                THEN ROUND(SUM(pp.total_gain_loss) / SUM(pp.cost_basis_total) * 100, 2)
                ELSE 0
            END AS pct_return,
            CASE
                WHEN totals.total_value > 0
                THEN ROUND(SUM(pp.current_value) / totals.total_value * 100, 4)
                ELSE 0
            END AS portfolio_weight_pct
        FROM Portfolio_Positions pp
        JOIN (
            SELECT snapshot_date, SUM(current_value) AS total_value
            FROM Portfolio_Positions
            WHERE snapshot_date = %s
            GROUP BY snapshot_date
        ) totals
          ON totals.snapshot_date = pp.snapshot_date
        WHERE pp.snapshot_date = %s
        GROUP BY pp.snapshot_date, pp.symbol, totals.total_value
        """,
        (snapshot_value, snapshot_value),
    )
    inserted_basket = cur.rowcount
    return deleted_basket, inserted_basket


def persist_basket_positions_to_mysql(
    basket_positions_df: pd.DataFrame,
    owner: str,
    database: Optional[str] = None,
) -> dict:
    """Persist basket-derived rows into Portfolio_Positions."""
    if basket_positions_df.empty:
        return {
            "database": database or "",
            "deleted": 0,
            "inserted": 0,
            "total_rows": 0,
            "stocks": 0,
            "deleted_basket": 0,
            "inserted_basket": 0,
            "total_basket_rows": 0,
        }

    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            _ensure_portfolio_positions_schema(cur)
            cur.execute(CREATE_ACCOUNT_OWNER_SQL)
            cur.execute(CREATE_PORTFOLIO_BASKET_SQL)

            basket_accounts = [
                str(a)
                for a in basket_positions_df["account_name"].dropna().astype(str).unique().tolist()
            ]

            for account_name in basket_accounts:
                cur.execute(INSERT_ACCOUNT_OWNER_SQL, (account_name, owner))

            deleted = 0
            deleted_basket = 0
            inserted_basket = 0

            snapshot_values = [
                s for s in basket_positions_df["snapshot_date"].dropna().unique().tolist() if s is not None
            ]

            if basket_accounts and snapshot_values:
                placeholders_accounts = ", ".join(["%s"] * len(basket_accounts))
                placeholders_snapshots = ", ".join(["%s"] * len(snapshot_values))
                delete_sql = (
                    "DELETE FROM Portfolio_Positions "
                    f"WHERE snapshot_date IN ({placeholders_snapshots}) "
                    f"AND account_name IN ({placeholders_accounts})"
                )
                cur.execute(delete_sql, (*snapshot_values, *basket_accounts))
                deleted = cur.rowcount

            inserted = 0
            for _, row in basket_positions_df.iterrows():
                snapshot_val = row.get("snapshot_date")
                cur.execute(
                    INSERT_SQL,
                    (
                        snapshot_val,
                        row["account_name"],
                        row.get("basket_name", "") or "",
                        row["symbol"],
                        row.get("description", "") or "",
                        None,
                        "",
                        float(row.get("total_gain_loss", 0.0) or 0.0),
                        float(row.get("pct_gain_loss", 0.0) or 0.0),
                        float(row.get("current_value", 0.0) or 0.0),
                        float(row.get("quantity", 0.0) or 0.0),
                        float(row.get("avg_cost_basis", 0.0) or 0.0),
                        float(row.get("cost_basis_total", 0.0) or 0.0),
                        None,
                        "Basket Group",
                        None,
                    ),
                )
                inserted += cur.rowcount

            for snapshot_val in snapshot_values:
                d_count, i_count = _rebuild_portfolio_basket_for_snapshot(cur, snapshot_val)
                deleted_basket += d_count
                inserted_basket += i_count

            cur.execute("SELECT COUNT(*) AS cnt FROM Portfolio_Positions")
            total_rows = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM portfolio_basket")
            total_basket_rows = cur.fetchone()["cnt"]

        db_name = conn.db.decode() if isinstance(conn.db, bytes) else conn.db
        return {
            "database": db_name,
            "deleted": deleted,
            "inserted": inserted,
            "total_rows": total_rows,
            "stocks": int(basket_positions_df["symbol"].nunique()),
            "deleted_basket": deleted_basket,
            "inserted_basket": inserted_basket,
            "total_basket_rows": total_basket_rows,
        }
    finally:
        conn.close()


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


def persist_to_mysql(
    df: pd.DataFrame,
    owner: str = "",
    database: Optional[str] = None,
    *,
    merge_snapshot: bool = False,
) -> dict:
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
            _ensure_portfolio_positions_schema(cur)
            cur.execute(CREATE_ACCOUNT_OWNER_SQL)
            cur.execute(CREATE_PORTFOLIO_BASKET_SQL)

            # Populate Account_Owner
            if owner and "account_name" in df.columns:
                for acct in df["account_name"].dropna().unique():
                    cur.execute(INSERT_ACCOUNT_OWNER_SQL, (acct, owner))

            # Determine snapshot datetime for the delete sweep
            snap_val = None
            if "snapshot_date" in df.columns and df["snapshot_date"].notna().any():
                snap_val = df["snapshot_date"].dropna().iloc[0]

            # Delete previous import of this snapshot.
            # Default behavior assumes one HTML file is a complete snapshot.
            if snap_val is not None:
                imported_accounts = []
                if "account_name" in df.columns:
                    imported_accounts = [
                        str(a) for a in df["account_name"].dropna().astype(str).unique().tolist()
                    ]

                if merge_snapshot and imported_accounts:
                    placeholders = ", ".join(["%s"] * len(imported_accounts))
                    delete_sql = (
                        "DELETE FROM Portfolio_Positions "
                        "WHERE snapshot_date = %s "
                        f"AND account_name IN ({placeholders})"
                    )
                    cur.execute(delete_sql, (snap_val, *imported_accounts))
                    deleted = cur.rowcount
                else:
                    cur.execute(
                        "DELETE FROM Portfolio_Positions WHERE snapshot_date = %s",
                        (snap_val,),
                    )
                    deleted = cur.rowcount
            else:
                deleted = 0
                imported_accounts = []

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
                    row.get("basket_name", "") or "",
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

            if snap_val is not None:
                # Rebuild basket for the full snapshot across all accounts currently in DB.
                deleted_basket, inserted_basket = _rebuild_portfolio_basket_for_snapshot(cur, snap_val)
            else:
                deleted_basket = 0
                inserted_basket = 0

            cur.execute("SELECT COUNT(*) AS cnt FROM Portfolio_Positions")
            total = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM portfolio_basket")
            total_basket = cur.fetchone()["cnt"]

        db_name = conn.db.decode() if isinstance(conn.db, bytes) else conn.db
        return {
            "database": db_name,
            "deleted": deleted,
            "inserted": inserted,
            "total_rows": total,
            "stocks": df["symbol"].nunique(),
            "deleted_basket": deleted_basket,
            "inserted_basket": inserted_basket,
            "total_basket_rows": total_basket,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Basket portfolio parser (summary export)
# ---------------------------------------------------------------------------

def _clean_text(value: Optional[str]) -> str:
    """Normalize whitespace for extracted HTML text."""
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _extract_center_cell_text(center_row: Optional[Tag], col_id: str) -> str:
    """Extract cell text from a center-grid row by AG Grid col-id."""
    if center_row is None:
        return ""
    node = center_row.select_one(f"div[col-id='{col_id}']")
    if node is None:
        return ""
    return _clean_text(node.get_text(" ", strip=True))


def extract_basket_groups(html_path: str, owner: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract basket groups from Fidelity Basket Portfolios HTML."""
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f, "html.parser")

    snapshot_ts = _extract_snapshot_timestamp(soup)

    pinned_container = soup.select_one("div.ag-pinned-left-cols-container")
    if pinned_container is None:
        raise ValueError("Could not find pinned-left grid container in HTML")

    center_container = soup.select_one("div.ag-center-cols-container")
    center_rows_by_index: dict[str, Tag] = {}
    if center_container is not None:
        for center_row in center_container.select("div[role='row'][row-index]"):
            row_index = center_row.get("row-index")
            if row_index is not None:
                center_rows_by_index[str(row_index)] = center_row

    rows = pinned_container.select("div[role='row']")

    current_source_account = ""
    current_source_account_number = ""
    current_basket: Optional[dict] = None
    basket_rows: list[dict] = []
    basket_positions_rows: list[dict] = []

    for row in rows:
        classes = set(row.get("class", []))

        if "posweb-row-account" in classes:
            primary = row.select_one(".posweb-cell-account_primary")
            secondary = row.select_one(".posweb-cell-account_secondary")
            current_source_account = _clean_text(primary.get_text(" ", strip=True) if primary else "")
            current_source_account_number = _clean_text(secondary.get_text(" ", strip=True) if secondary else "")
            continue

        if "posweb-row-basket_group" in classes:
            if current_basket is not None:
                current_basket["basket_complete"] = False
                current_basket["basket_end_marker"] = "not_found"
                current_basket["positions_parsed"] = len(current_basket["symbols"])
                basket_rows.append(current_basket)

            basket_name_node = row.select_one(".posweb-cell-group-info_primary_name span")
            if basket_name_node is None:
                basket_name_node = row.select_one(".posweb-cell-group-info_primary_name")
            basket_name = _clean_text(basket_name_node.get_text(" ", strip=True) if basket_name_node else "")

            positions_text_node = row.select_one(".posweb-cell-group-text_curval")
            positions_text = _clean_text(
                positions_text_node.get_text(" ", strip=True) if positions_text_node else ""
            )
            match = re.search(r"(\d+)\s+positions", positions_text, flags=re.IGNORECASE)
            declared_positions = int(match.group(1)) if match else None

            current_basket = {
                "owner": owner,
                "source_account": current_source_account,
                "source_account_number": current_source_account_number,
                "account_name": f"{owner}:{basket_name}" if basket_name else f"{owner}:UNKNOWN",
                "basket_name": basket_name,
                "positions_declared": declared_positions,
                "positions_declared_text": positions_text,
                "positions_parsed": 0,
                "basket_complete": False,
                "basket_end_marker": "",
                "symbols": [],
            }
            continue

        if "posweb-row-basket" in classes and current_basket is not None:
            row_index = str(row.get("row-index", ""))
            center_row = center_rows_by_index.get(row_index)

            symbol_node = row.select_one(".posweb-cell-symbol-name_container .posweb-cell-symbol-name")
            if symbol_node is None:
                symbol_node = row.select_one(".posweb-cell-symbol-name_container span")
            symbol_text = _clean_text(symbol_node.get_text(" ", strip=True) if symbol_node else "")
            if not symbol_text:
                continue

            description_node = row.select_one("p.posweb-cell-symbol-description")
            description_text = _clean_text(
                description_node.get_text(" ", strip=True) if description_node else ""
            )

            if symbol_text.lower() == "basket total":
                current_basket["basket_complete"] = True
                current_basket["basket_end_marker"] = "Basket Total"
                current_basket["positions_parsed"] = len(current_basket["symbols"])
                basket_rows.append(current_basket)
                current_basket = None
            else:
                quantity_text = _extract_center_cell_text(center_row, "qty")
                current_value_text = _extract_center_cell_text(center_row, "curVal")
                avg_cost_text = _extract_center_cell_text(center_row, "cstBasShr")
                cost_basis_total_text = _extract_center_cell_text(center_row, "cstBasTot")
                total_gl_text = _extract_center_cell_text(center_row, "totGL")
                total_gl_pct_text = _extract_center_cell_text(center_row, "totGLPct")

                quantity = parse_quantity(quantity_text) if quantity_text else 0.0
                current_value = parse_currency(current_value_text) if current_value_text else 0.0
                avg_cost_basis = parse_currency(avg_cost_text) if avg_cost_text else 0.0
                cost_basis_total = parse_currency(cost_basis_total_text) if cost_basis_total_text else 0.0
                total_gain_loss = parse_currency(total_gl_text) if total_gl_text else 0.0
                pct_gain_loss = parse_percent(total_gl_pct_text) if total_gl_pct_text else 0.0

                current_basket["symbols"].append(
                    {
                        "symbol": symbol_text,
                        "description": description_text,
                        "quantity": quantity,
                        "current_value": current_value,
                        "avg_cost_basis": avg_cost_basis,
                        "cost_basis_total": cost_basis_total,
                        "total_gain_loss": total_gain_loss,
                        "pct_gain_loss": pct_gain_loss,
                        "snapshot_date": snapshot_ts,
                    }
                )

    if current_basket is not None:
        current_basket["basket_complete"] = False
        current_basket["basket_end_marker"] = "not_found"
        current_basket["positions_parsed"] = len(current_basket["symbols"])
        basket_rows.append(current_basket)

    for basket in basket_rows:
        for idx, position in enumerate(basket.get("symbols", []), start=1):
            basket_positions_rows.append(
                {
                    "owner": basket["owner"],
                    "source_account": basket["source_account"],
                    "source_account_number": basket["source_account_number"],
                    "account_name": basket["account_name"],
                    "basket_name": basket["basket_name"],
                    "symbol": position["symbol"],
                    "description": position.get("description", ""),
                    "quantity": position.get("quantity", 0.0),
                    "current_value": position.get("current_value", 0.0),
                    "avg_cost_basis": position.get("avg_cost_basis", 0.0),
                    "cost_basis_total": position.get("cost_basis_total", 0.0),
                    "total_gain_loss": position.get("total_gain_loss", 0.0),
                    "pct_gain_loss": position.get("pct_gain_loss", 0.0),
                    "snapshot_date": position.get("snapshot_date"),
                    "position_index": idx,
                }
            )

    summary_records = [
        {
            "owner": b["owner"],
            "source_account": b["source_account"],
            "source_account_number": b["source_account_number"],
            "account_name": b["account_name"],
            "basket_name": b["basket_name"],
            "positions_declared": b["positions_declared"],
            "positions_parsed": b["positions_parsed"],
            "basket_complete": b["basket_complete"],
            "basket_end_marker": b["basket_end_marker"],
            "snapshot_date": snapshot_ts,
        }
        for b in basket_rows
    ]

    summary_df = pd.DataFrame(summary_records)
    positions_df = pd.DataFrame(basket_positions_rows)
    return summary_df, positions_df


def export_basket_groups_to_excel(
    summary_df: pd.DataFrame,
    positions_df: pd.DataFrame,
    output_path: str,
) -> None:
    """Export basket summary and positions into an XLSX workbook."""
    with pd.ExcelWriter(output_path) as writer:
        summary_df.to_excel(writer, sheet_name="basket_summary", index=False)
        positions_df.to_excel(writer, sheet_name="basket_positions", index=False)

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
    parser.add_argument(
        "--merge-snapshot",
        action="store_true",
        default=False,
        help=(
            "Merge into existing snapshot by deleting only matching accounts. "
            "Default is full snapshot replace by as-of date."
        ),
    )
    parser.add_argument(
        "--parse-baskets",
        action="store_true",
        default=False,
        help="Parse Fidelity Basket Portfolios HTML and export basket summary XLSX",
    )
    parser.add_argument(
        "--basket-owner",
        default="Ras",
        help="Owner label for basket parsing mode (default: Ras)",
    )
    parser.add_argument(
        "--basket-output",
        default=None,
        help="Output XLSX path for basket parsing mode",
    )
    parser.add_argument(
        "--import-baskets",
        action="store_true",
        default=False,
        help="When used with --parse-baskets, also import parsed baskets into Portfolio_Positions",
    )
    parser.add_argument(
        "--import-basket-csv",
        default=None,
        help=(
            "Import preprocessed intended-weight CSV directly into basket_intended_weight "
            "(skips HTML parsing)"
        ),
    )
    parser.add_argument(
        "--basket-name",
        default="Fortress",
        help="Basket name label for --import-basket-csv (default: Fortress)",
    )
    parser.add_argument(
        "--csv-owner",
        default="",
        help="Optional owner label for --import-basket-csv",
    )
    parser.add_argument(
        "--drift-report",
        action="store_true",
        default=False,
        help="Compare latest intended weights vs latest portfolio_basket actual weights",
    )
    parser.add_argument(
        "--drift-output",
        default=None,
        help="Optional CSV output path for --drift-report",
    )
    args = parser.parse_args()

    if args.import_basket_csv:
        csv_path = args.import_basket_csv
        if csv_path.strip().lower() in {"default", "fortress"}:
            csv_path = DEFAULT_FORTRESS_CSV_PATH

        if not os.path.exists(csv_path):
            print(f"CSV file not found: {csv_path}")
            sys.exit(1)

        print(f"Importing intended-weight CSV: {csv_path}")
        stats = persist_basket_intended_weight_csv(
            csv_path=csv_path,
            basket_name=args.basket_name,
            database=args.database,
            owner=args.csv_owner,
        )

        print(f"Imported intended weights into database: {stats['database']}")
        print(f"  Basket:            {stats['basket_name']}")
        print(f"  Import date:       {stats['import_date']}")
        print(f"  CSV rows:          {stats['csv_rows']}")
        print(f"  Inserted:          {stats['inserted']}")
        print(f"  Unique symbols:    {stats['unique_symbols']}")
        print(f"  Weight sum (%):    {stats['target_weight_sum_pct']:.4f}")
        print(f"  Basket total rows: {stats['basket_total_rows']}")
        return

    if args.drift_report:
        report_df, summary = build_basket_drift_report(
            basket_name=args.basket_name,
            database=args.database,
        )
        print("Basket drift report")
        print(f"  Basket:              {summary['basket_name']}")
        print(f"  Intended import:     {summary['latest_import_date']}")
        print(f"  Actual snapshot:     {summary['latest_snapshot_date']}")
        print(f"  Symbols:             {summary['rows']}")
        print(f"  Missing in actual:   {summary['symbols_missing_in_actual']}")
        print(f"  Intended sum (%):    {summary['intended_weight_sum_pct']:.4f}")
        print(f"  Actual sum (%):      {summary['actual_weight_sum_pct']:.4f}")
        print(f"  Max abs drift (%):   {summary['max_abs_drift_pct']:.4f}")
        print(f"  Avg abs drift (%):   {summary['avg_abs_drift_pct']:.4f}")

        top = report_df.sort_values("abs_drift_pct", ascending=False).head(15)
        print("\nTop drift symbols")
        print(top.to_string(index=False))

        if args.drift_output:
            report_df.to_csv(args.drift_output, index=False)
            print(f"\nSaved drift CSV: {args.drift_output}")
        return

    if not os.path.exists(args.file):
        print(f"File not found: {args.file}")
        sys.exit(1)

    if args.parse_baskets:
        owner = _clean_text(args.basket_owner) or "Ras"
        output_path = args.basket_output
        if not output_path:
            base_dir = os.path.dirname(args.file)
            output_path = os.path.join(base_dir, f"basket_parse_review_{owner}.xlsx")

        summary_df, positions_df = extract_basket_groups(args.file, owner=owner)
        export_basket_groups_to_excel(summary_df, positions_df, output_path)

        print(f"Basket parse complete for owner: {owner}")
        print(f"Baskets found: {len(summary_df)}")
        print(f"Output XLSX: {output_path}")
        if not summary_df.empty:
            cols = ["account_name", "basket_name", "positions_declared", "positions_parsed"]
            print(summary_df[cols].to_string(index=False))

        if args.import_baskets:
            print("\nImporting parsed baskets into Portfolio_Positions ...")
            stats = persist_basket_positions_to_mysql(
                basket_positions_df=positions_df,
                owner=owner,
                database=args.database,
            )
            print(f"Imported baskets into database: {stats['database']}")
            print(f"  Deleted (prior): {stats['deleted']}")
            print(f"  Inserted:        {stats['inserted']}")
            print(f"  Total rows:      {stats['total_rows']}")
            print(f"  Basket rows:     {stats['total_basket_rows']}")
        return

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
    stats = persist_to_mysql(
        df,
        owner=owner,
        database=args.database,
        merge_snapshot=args.merge_snapshot,
    )

    print(f"\n{'='*50}")
    print(f"  Done — database: {stats['database']}")
    print(f"  Stocks:          {stats['stocks']}")
    print(f"  Deleted (prior): {stats['deleted']}")
    print(f"  Inserted:        {stats['inserted']}")
    print(f"  Total rows:      {stats['total_rows']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
