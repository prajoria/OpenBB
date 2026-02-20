"""
ESPP Plan Data Loader

Reads ESPP (Employee Stock Purchase Plan) data from a file or clipboard
and populates the ESPP_Plan table in MySQL.

Input format (TSV/CSV – copy-paste from brokerage statement):
    Offering Period, Purchase Date, FMV at offering Start Date,
    FMV at Purchase Date, Purchase Price, Purchase Quantity,
    Purchase Value, Qualified Disposition Date†††, Purchase Deposit To

Usage:
    python Tools/load_espp_plan.py --file espp_data.tsv
    python Tools/load_espp_plan.py --clipboard
    python Tools/load_espp_plan.py                   # uses embedded sample data
    python Tools/load_espp_plan.py --database my_db   # target a specific database
"""

import argparse
import csv
import io
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure the fmp_cached provider package is importable from source checkout
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIRS = [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]
# Also add extensions
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

# Load .env so DB credentials are available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ESPPPurchase:
    """Represents a single ESPP (Employee Stock Purchase Plan) purchase record.

    An ESPP allows employees to buy company stock at a discount (typically 15%)
    through after-tax payroll deductions during fixed "offering periods" (usually
    3–6 months).  At the end of each period the accumulated contributions are used
    to purchase shares at the discounted price.

    Column definitions
    ------------------
    offering_period_start : date
        First day of the ESPP offering/enrollment window.  The FMV on this date
        is one of the two prices used to calculate the purchase price (the
        "look-back" provision).
    offering_period_end : date
        Last day of the offering window (often coincides with purchase_date).
    purchase_date : date
        The date on which shares were actually purchased with the employee's
        accumulated payroll deductions.
    fmv_offering_start : float
        Fair Market Value (closing price) of the stock on offering_period_start.
        Used by the look-back rule: purchase price = 85% × min(FMV_start, FMV_purchase).
    fmv_purchase_date : float
        Fair Market Value (closing price) on the purchase_date.  Together with
        fmv_offering_start it determines the actual purchase price.
    purchase_price : float
        The per-share price the employee paid, usually 85% of the lower of
        fmv_offering_start and fmv_purchase_date (the "look-back" discount).
    purchase_quantity : float
        Number of shares purchased in this period (may be fractional).
    purchase_value : float
        Total dollar value of the purchase = purchase_price × purchase_quantity.
    qualified_disposition_date : date
        Earliest date the shares can be sold and qualify for favorable
        long-term capital-gains tax treatment.  This is the later of:
          • 2 years after offering_period_start, or
          • 1 year after purchase_date.
        Selling before this date triggers a "disqualifying disposition" and
        the bargain element is taxed as ordinary income instead.
    purchase_deposit_to : str
        Account the purchased shares were deposited into (e.g. "Brokerage
        Account").
    symbol : str
        Ticker symbol of the stock purchased (default: MSFT).

    Computed properties
    -------------------
    discount_pct : float
        Effective discount percentage = (FMV_start − purchase_price) / FMV_start × 100.
        Shows how much below the offering-start price the employee actually paid.
    bargain_element : float
        (FMV_purchase − purchase_price) × quantity.  This is the "compensation"
        component — the amount that may be taxed as ordinary income on a
        disqualifying disposition or reported on Form 3922.
    """

    offering_period_start: Optional[date] = None      # Start of ESPP enrollment window
    offering_period_end: Optional[date] = None        # End of ESPP enrollment window
    purchase_date: Optional[date] = None              # Date shares were bought
    fmv_offering_start: float = 0.0                   # Stock closing price on offering start
    fmv_purchase_date: float = 0.0                    # Stock closing price on purchase date
    purchase_price: float = 0.0                       # Discounted per-share price paid
    purchase_quantity: float = 0.0                    # Number of shares acquired
    purchase_value: float = 0.0                       # Total cost = price × quantity
    qualified_disposition_date: Optional[date] = None # Earliest date for LTCG treatment
    purchase_deposit_to: str = ""                     # Destination brokerage account
    symbol: str = "MSFT"                              # Ticker symbol (default MSFT)

    @property
    def discount_pct(self) -> float:
        """Effective ESPP discount percentage.

        Calculated as (FMV_offering_start − purchase_price) / FMV_offering_start × 100.
        A typical ESPP offers a 15% discount via a look-back provision.
        """
        if self.fmv_offering_start == 0:
            return 0.0
        return ((self.fmv_offering_start - self.purchase_price)
                / self.fmv_offering_start * 100)

    @property
    def bargain_element(self) -> float:
        """Bargain element (compensation income) per IRS rules.

        = (FMV on purchase date − purchase price) × quantity.
        This amount is reported on Form 3922 and may be taxed as ordinary
        income on a disqualifying disposition.  On a qualifying disposition
        the taxable compensation is capped at (FMV_offering_start − purchase_price) × qty.
        """
        return (self.fmv_purchase_date - self.purchase_price) * self.purchase_quantity


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_currency(val: str) -> float:
    """Parse currency string like '$492.05 USD' or '$2,571.85 USD' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = val.strip()
    negative = "(" in cleaned
    # Remove $, USD, commas, parentheses, spaces
    cleaned = re.sub(r"[$,()A-Za-z\s]", "", cleaned)
    try:
        result = float(cleaned)
        return -result if negative else result
    except ValueError:
        return 0.0


def parse_quantity(val: str) -> float:
    """Parse quantity string like '5.517 shares' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = re.sub(r"[A-Za-z,\s]", "", val.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date_str(val: str) -> Optional[date]:
    """Parse date strings like '09/30/2025' or '2025-09-30'."""
    if not val or val.strip() in ("--", "N/A", ""):
        return None
    val = val.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%b-%d-%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def parse_offering_period(val: str):
    """Parse offering period like '07/01/2025 - 09/30/2025' into (start, end)."""
    if not val or val.strip() in ("--", "N/A", ""):
        return None, None
    parts = re.split(r"\s*[-–—]+\s*", val.strip())
    start = parse_date_str(parts[0]) if len(parts) >= 1 else None
    end = parse_date_str(parts[1]) if len(parts) >= 2 else None
    return start, end


def normalize_key(k: str) -> str:
    """Normalize column header to a canonical key."""
    key = k.strip().lower()
    # Remove unicode daggers / special chars
    key = re.sub(r"[†‡*]+", "", key)
    key = key.replace(" ", "_").replace(".", "")
    return key


def parse_row(row: dict) -> ESPPPurchase:
    """Parse a single row dict into an ESPPPurchase."""
    norm = {normalize_key(k): v.strip() if isinstance(v, str) else v
            for k, v in row.items()}

    def get(keys, default=""):
        for k in keys:
            if k in norm:
                return norm[k]
        return default

    offering_start, offering_end = parse_offering_period(
        get(["offering_period"])
    )

    return ESPPPurchase(
        offering_period_start=offering_start,
        offering_period_end=offering_end,
        purchase_date=parse_date_str(
            get(["purchase_date"])
        ),
        fmv_offering_start=parse_currency(
            get(["fmv_at_offering_start_date", "fmv_at_offering_start"])
        ),
        fmv_purchase_date=parse_currency(
            get(["fmv_at_purchase_date"])
        ),
        purchase_price=parse_currency(
            get(["purchase_price"])
        ),
        purchase_quantity=parse_quantity(
            get(["purchase_quantity"])
        ),
        purchase_value=parse_currency(
            get(["purchase_value"])
        ),
        qualified_disposition_date=parse_date_str(
            get(["qualified_disposition_date"])
        ),
        purchase_deposit_to=get(
            ["purchase_deposit_to"], ""
        ),
    )


def parse_data(text: str) -> list:
    """Parse TSV/CSV text into a list of ESPPPurchase records."""
    first_line = text.strip().split("\n")[0]
    delimiter = "\t" if "\t" in first_line else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    records = []
    for row in reader:
        rec = parse_row(row)
        if rec.purchase_quantity > 0:
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# MySQL operations
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ESPP_Plan (
    -- Surrogate primary key
    id                        INT AUTO_INCREMENT PRIMARY KEY,

    -- Offering period: the enrollment window during which payroll deductions accumulate
    offering_period_start     DATE          NULL,   -- First day of the offering window
    offering_period_end       DATE          NULL,   -- Last day of the offering window

    -- Purchase transaction
    purchase_date             DATE          NULL,   -- Date shares were actually purchased

    -- Fair Market Values (closing prices) used by the look-back rule
    fmv_offering_start        DECIMAL(12,4) NOT NULL DEFAULT 0, -- FMV on offering start date
    fmv_purchase_date         DECIMAL(12,4) NOT NULL DEFAULT 0, -- FMV on purchase date

    -- Price & quantity
    purchase_price            DECIMAL(12,4) NOT NULL DEFAULT 0, -- Discounted per-share price (usually 85% of lower FMV)
    purchase_quantity         DECIMAL(12,4) NOT NULL DEFAULT 0, -- Shares acquired (may be fractional)
    purchase_value            DECIMAL(14,4) NOT NULL DEFAULT 0, -- Total cost = price × quantity

    -- Tax disposition
    qualified_disposition_date DATE         NULL,   -- Earliest sell date for LTCG treatment

    -- Account info
    purchase_deposit_to       VARCHAR(100)  NOT NULL DEFAULT '', -- Brokerage account where shares land
    symbol                    VARCHAR(20)   NOT NULL DEFAULT 'MSFT', -- Ticker symbol of purchased stock

    -- Computed fields (populated at insert time for easy querying)
    discount_pct              DECIMAL(6,2)  NOT NULL DEFAULT 0, -- Effective discount % = (FMV_start - price) / FMV_start × 100
    bargain_element           DECIMAL(14,4) NOT NULL DEFAULT 0, -- Compensation element = (FMV_purchase - price) × qty

    -- Audit
    created_at                TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Prevent duplicate inserts for the same offering + purchase
    UNIQUE KEY uq_espp_purchase (offering_period_start, offering_period_end, purchase_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_SQL = """
INSERT INTO ESPP_Plan
    (offering_period_start, offering_period_end, purchase_date,
     fmv_offering_start, fmv_purchase_date, purchase_price,
     purchase_quantity, purchase_value,
     qualified_disposition_date, purchase_deposit_to, symbol,
     discount_pct, bargain_element)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    fmv_offering_start   = VALUES(fmv_offering_start),
    fmv_purchase_date    = VALUES(fmv_purchase_date),
    purchase_price       = VALUES(purchase_price),
    purchase_quantity    = VALUES(purchase_quantity),
    purchase_value       = VALUES(purchase_value),
    qualified_disposition_date = VALUES(qualified_disposition_date),
    purchase_deposit_to  = VALUES(purchase_deposit_to),
    symbol               = VALUES(symbol),
    discount_pct         = VALUES(discount_pct),
    bargain_element      = VALUES(bargain_element)
"""


def get_connection(database: Optional[str] = None):
    """Get a pymysql connection, optionally overriding the database name."""
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    config = DatabaseConfig()
    params = config.connection_params
    if database:
        params["database"] = database

    # Ensure the database exists
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


def populate_table(records: list, database: Optional[str] = None) -> dict:
    """Create table (if needed) and upsert ESPP purchase records.

    Returns summary dict with counts.
    """
    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)

            rows_affected = 0
            for rec in records:
                cur.execute(INSERT_SQL, (
                    rec.offering_period_start,
                    rec.offering_period_end,
                    rec.purchase_date,
                    rec.fmv_offering_start,
                    rec.fmv_purchase_date,
                    rec.purchase_price,
                    rec.purchase_quantity,
                    rec.purchase_value,
                    rec.qualified_disposition_date,
                    rec.purchase_deposit_to,
                    rec.symbol,
                    round(rec.discount_pct, 2),
                    round(rec.bargain_element, 4),
                ))
                rows_affected += cur.rowcount

            # Read back for summary
            cur.execute("SELECT COUNT(*) AS cnt FROM ESPP_Plan")
            total = cur.fetchone()["cnt"]

        return {
            "database": conn.db.decode() if isinstance(conn.db, bytes) else conn.db,
            "upserted": rows_affected,
            "total_rows": total,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_records(records: list) -> None:
    """Print parsed ESPP records to console."""
    sep = "=" * 90
    print(f"\n{sep}")
    print("  ESPP PLAN PURCHASES")
    print(sep)

    print(f"  {'Offering Period':<27} {'Purchase':>10} {'FMV Start':>10} "
          f"{'FMV Purch':>10} {'Price':>10} {'Qty':>8} {'Value':>12} {'Qual Disp':>12}")
    print(f"  {'-'*27} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*12} {'-'*12}")

    for r in sorted(records, key=lambda x: x.purchase_date or date.min):
        period = ""
        if r.offering_period_start and r.offering_period_end:
            period = (f"{r.offering_period_start.strftime('%m/%d/%Y')}"
                      f" - {r.offering_period_end.strftime('%m/%d/%Y')}")
        pd = r.purchase_date.strftime("%m/%d/%Y") if r.purchase_date else "N/A"
        qd = r.qualified_disposition_date.strftime("%m/%d/%Y") if r.qualified_disposition_date else "N/A"
        print(
            f"  {period:<27} {pd:>10} ${r.fmv_offering_start:>8,.2f} "
            f"${r.fmv_purchase_date:>8,.2f} ${r.purchase_price:>8,.2f} "
            f"{r.purchase_quantity:>8.3f} ${r.purchase_value:>10,.2f} {qd:>12}"
        )

    total_value = sum(r.purchase_value for r in records)
    total_qty = sum(r.purchase_quantity for r in records)
    total_bargain = sum(r.bargain_element for r in records)
    print(f"\n  Total purchases:   {len(records)}")
    print(f"  Total shares:      {total_qty:,.3f}")
    print(f"  Total value:       ${total_value:>12,.2f}")
    print(f"  Total bargain:     ${total_bargain:>12,.2f}  (taxable compensation)")
    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# Embedded sample data
# ---------------------------------------------------------------------------

SAMPLE_DATA = (
    "Offering Period\tPurchase Date\tFMV at offering Start Date\t"
    "FMV at Purchase Date\tPurchase Price\tPurchase Quantity\t"
    "Purchase Value\tQualified Disposition Date†††\tPurchase Deposit To\n"
    "07/01/2025 - 09/30/2025\t09/30/2025\t$492.05 USD\t$517.95 USD\t"
    "$466.16 USD\t5.517 shares\t$2,571.85 USD\t07/01/2027\tBrokerage Account\n"
    "04/01/2025 - 06/30/2025\t06/30/2025\t$382.19 USD\t$497.41 USD\t"
    "$447.67 USD\t23.788 shares\t$10,649.17 USD\t04/01/2027\tBrokerage Account"
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ESPP Plan Data Loader — parse & populate ESPP_Plan table"
    )
    parser.add_argument(
        "--file", "-f",
        help="Path to TSV/CSV file with ESPP data",
    )
    parser.add_argument(
        "--clipboard", "-c",
        action="store_true",
        help="Read data from clipboard",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database name (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and display only — do not write to database",
    )
    args = parser.parse_args()

    # ---- Read input ----
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    elif args.clipboard:
        try:
            import pyperclip
            text = pyperclip.paste()
        except ImportError:
            print("Install pyperclip for clipboard support: pip install pyperclip")
            sys.exit(1)
    else:
        print("Using embedded sample data (use --file or --clipboard for real data)")
        text = SAMPLE_DATA

    # ---- Parse ----
    records = parse_data(text)
    if not records:
        print("No valid ESPP purchase records found in input data.")
        sys.exit(1)

    print_records(records)

    # ---- Persist ----
    if args.dry_run:
        print("Dry-run mode — skipping database write.")
        return

    print(f"Writing {len(records)} record(s) to ESPP_Plan table …")
    stats = populate_table(records, database=args.database)

    print(f"\n{'='*50}")
    print(f"  Done — database: {stats['database']}")
    print(f"  Rows upserted:   {stats['upserted']}")
    print(f"  Total rows:      {stats['total_rows']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
