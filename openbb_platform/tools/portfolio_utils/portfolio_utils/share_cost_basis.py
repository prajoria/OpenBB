"""
Share Acquisition & Cost Basis Analyzer

Reads share acquisition data (e.g., from brokerage exports) and processes
cost basis, gains/losses, and holding period analysis.

Input format (TSV/CSV):
    Acquired, Term, $ Total gain/loss, % Total gain/loss, Current value,
    Quantity, Average cost basis, Cost basis total, Transfer Avail. Dates,
    Share Source, Grant Date

Usage:
    python Tools/share_cost_basis.py --file data.tsv
    python Tools/share_cost_basis.py --clipboard
    python Tools/share_cost_basis.py  # uses embedded sample data

Output:
    - Summary statistics
    - Per-lot breakdown
    - Aggregated cost basis and unrealized P&L
"""

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional


@dataclass
class ShareLot:
    """Represents a single acquisition lot of shares."""
    acquired: Optional[date] = None
    term: str = ""  # Short or Long
    total_gain_loss: float = 0.0
    pct_gain_loss: float = 0.0
    current_value: float = 0.0
    quantity: float = 0.0
    avg_cost_basis: float = 0.0
    cost_basis_total: float = 0.0
    transfer_avail_date: Optional[date] = None
    share_source: str = ""
    grant_date: Optional[date] = None

    @property
    def current_price(self) -> float:
        return self.current_value / self.quantity if self.quantity else 0.0

    @property
    def is_short_term(self) -> bool:
        return self.term.lower().startswith("short")


@dataclass
class Portfolio:
    """Aggregated portfolio of share lots."""
    lots: list = field(default_factory=list)

    @property
    def total_quantity(self) -> float:
        return sum(lot.quantity for lot in self.lots)

    @property
    def total_cost_basis(self) -> float:
        return sum(lot.cost_basis_total for lot in self.lots)

    @property
    def total_current_value(self) -> float:
        return sum(lot.current_value for lot in self.lots)

    @property
    def total_gain_loss(self) -> float:
        return sum(lot.total_gain_loss for lot in self.lots)

    @property
    def total_pct_gain_loss(self) -> float:
        if self.total_cost_basis == 0:
            return 0.0
        return (self.total_gain_loss / self.total_cost_basis) * 100

    @property
    def weighted_avg_cost(self) -> float:
        if self.total_quantity == 0:
            return 0.0
        return self.total_cost_basis / self.total_quantity

    @property
    def short_term_lots(self) -> list:
        return [lot for lot in self.lots if lot.is_short_term]

    @property
    def long_term_lots(self) -> list:
        return [lot for lot in self.lots if not lot.is_short_term]


def parse_currency(val: str) -> float:
    """Parse currency string like '($605.38)' or '$2,595.63' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = val.strip()
    negative = "(" in cleaned
    cleaned = re.sub(r"[$(,)\s]", "", cleaned)
    try:
        result = float(cleaned)
        return -result if negative else result
    except ValueError:
        return 0.0


def parse_percent(val: str) -> float:
    """Parse percentage string like '-18.91%' to float."""
    if not val or val.strip() in ("--", "N/A", ""):
        return 0.0
    cleaned = re.sub(r"[%\s]", "", val.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(val: str) -> Optional[date]:
    """Parse date strings like 'Dec-01-2025' or '2025-12-01'."""
    if not val or val.strip() in ("--", "N/A", ""):
        return None
    val = val.strip()
    for fmt in ("%b-%d-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def parse_row(row: dict) -> ShareLot:
    """Parse a single row dict into a ShareLot."""
    # Normalize column names (handle variations in header naming)
    normalized = {}
    for k, v in row.items():
        key = k.strip().lower().replace(" ", "_").replace("$_", "").replace("%_", "pct_")
        normalized[key] = v.strip() if isinstance(v, str) else v

    def get(keys, default=""):
        for k in keys:
            if k in normalized:
                return normalized[k]
        return default

    return ShareLot(
        acquired=parse_date(get(["acquired"])),
        term=get(["term"], ""),
        total_gain_loss=parse_currency(get(["total_gain/loss", "total_gain_loss", "$_total_gain/loss"])),
        pct_gain_loss=parse_percent(get(["pct_total_gain/loss", "pct_total_gain_loss", "%_total_gain/loss"])),
        current_value=parse_currency(get(["current_value"])),
        quantity=float(get(["quantity"], "0") or "0"),
        avg_cost_basis=parse_currency(get(["average_cost_basis", "avg_cost_basis"])),
        cost_basis_total=parse_currency(get(["cost_basis_total"])),
        transfer_avail_date=parse_date(get(["transfer_avail._dates", "transfer_avail_dates"])),
        share_source=get(["share_source"], ""),
        grant_date=parse_date(get(["grant_date"])),
    )


def parse_data(text: str) -> Portfolio:
    """Parse TSV/CSV text into a Portfolio."""
    # Detect delimiter
    first_line = text.strip().split("\n")[0]
    delimiter = "\t" if "\t" in first_line else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    portfolio = Portfolio()

    for row in reader:
        lot = parse_row(row)
        if lot.quantity > 0:
            portfolio.lots.append(lot)

    return portfolio


def print_summary(portfolio: Portfolio) -> None:
    """Print formatted portfolio summary."""
    sep = "=" * 70
    print(f"\n{sep}")
    print("  SHARE ACQUISITION & COST BASIS SUMMARY")
    print(sep)

    print(f"\n  Total Lots:           {len(portfolio.lots)}")
    print(f"  Total Shares:         {portfolio.total_quantity:,.3f}")
    print(f"  Total Cost Basis:     ${portfolio.total_cost_basis:>12,.2f}")
    print(f"  Total Current Value:  ${portfolio.total_current_value:>12,.2f}")
    print(f"  Total Gain/Loss:      ${portfolio.total_gain_loss:>12,.2f}")
    print(f"  Overall Return:       {portfolio.total_pct_gain_loss:>11.2f}%")
    print(f"  Weighted Avg Cost:    ${portfolio.weighted_avg_cost:>12,.2f}")

    if portfolio.lots:
        print(f"  Current Price (est):  ${portfolio.lots[0].current_price:>12,.2f}")

    # Term breakdown
    short = portfolio.short_term_lots
    long = portfolio.long_term_lots

    if short:
        short_total = sum(l.total_gain_loss for l in short)
        short_cost = sum(l.cost_basis_total for l in short)
        print(f"\n  Short-Term ({len(short)} lots):")
        print(f"    Cost Basis:         ${short_cost:>12,.2f}")
        print(f"    Gain/Loss:          ${short_total:>12,.2f}")

    if long:
        long_total = sum(l.total_gain_loss for l in long)
        long_cost = sum(l.cost_basis_total for l in long)
        print(f"\n  Long-Term ({len(long)} lots):")
        print(f"    Cost Basis:         ${long_cost:>12,.2f}")
        print(f"    Gain/Loss:          ${long_total:>12,.2f}")

    # Per-lot detail
    print(f"\n{sep}")
    print("  LOT DETAILS")
    print(sep)
    print(f"  {'Acquired':<14} {'Term':<7} {'Qty':>8} {'Avg Cost':>10} "
          f"{'Cost Total':>12} {'Cur Value':>12} {'Gain/Loss':>12} {'Return':>8} {'Source'}")
    print(f"  {'-'*14} {'-'*7} {'-'*8} {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*8} {'-'*12}")

    for lot in sorted(portfolio.lots, key=lambda l: l.acquired or date.min):
        acq = lot.acquired.strftime("%Y-%m-%d") if lot.acquired else "N/A"
        print(
            f"  {acq:<14} {lot.term:<7} {lot.quantity:>8.3f} "
            f"${lot.avg_cost_basis:>9,.2f} ${lot.cost_basis_total:>11,.2f} "
            f"${lot.current_value:>11,.2f} ${lot.total_gain_loss:>11,.2f} "
            f"{lot.pct_gain_loss:>7.2f}% {lot.share_source}"
        )

    # By acquisition date
    dates = {}
    for lot in portfolio.lots:
        key = lot.acquired or date.min
        if key not in dates:
            dates[key] = {"qty": 0, "cost": 0, "value": 0, "gl": 0}
        dates[key]["qty"] += lot.quantity
        dates[key]["cost"] += lot.cost_basis_total
        dates[key]["value"] += lot.current_value
        dates[key]["gl"] += lot.total_gain_loss

    if len(dates) > 1:
        print(f"\n{sep}")
        print("  BY ACQUISITION DATE")
        print(sep)
        print(f"  {'Date':<14} {'Shares':>10} {'Cost Basis':>12} {'Cur Value':>12} {'Gain/Loss':>12} {'Return':>8}")
        print(f"  {'-'*14} {'-'*10} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")
        for d in sorted(dates.keys()):
            info = dates[d]
            pct = (info["gl"] / info["cost"] * 100) if info["cost"] else 0
            ds = d.strftime("%Y-%m-%d") if d != date.min else "N/A"
            print(
                f"  {ds:<14} {info['qty']:>10.3f} ${info['cost']:>11,.2f} "
                f"${info['value']:>11,.2f} ${info['gl']:>11,.2f} {pct:>7.2f}%"
            )

    print(f"\n{sep}\n")


# Embedded sample data for testing
SAMPLE_DATA = """Acquired\tTerm\t$ Total gain/loss\t% Total gain/loss\tCurrent value\tQuantity\tAverage cost basis\tCost basis total\tTransfer Avail. Dates\tShare Source\tGrant Date
Dec-01-2025\tShort\t($605.38)\t-18.91%\t$2,595.63\t6.506\t$492.01\t$3,201.01\t--\tDeposit only\t--
Dec-01-2025\tShort\t($958.50)\t-18.91%\t$4,109.69\t10.301\t$492.01\t$5,068.19\t--\tDeposit only\t--"""


def main():
    parser = argparse.ArgumentParser(
        description="Share Acquisition & Cost Basis Analyzer"
    )
    parser.add_argument(
        "--file", "-f",
        help="Path to TSV/CSV file with share data",
    )
    parser.add_argument(
        "--clipboard", "-c",
        action="store_true",
        help="Read data from clipboard",
    )
    args = parser.parse_args()

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

    portfolio = parse_data(text)

    if not portfolio.lots:
        print("No valid share lots found in input data.")
        sys.exit(1)

    print_summary(portfolio)


if __name__ == "__main__":
    main()
