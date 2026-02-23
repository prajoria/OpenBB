"""
Mock Data Generator — creates realistic but fully anonymized test fixtures.

All account numbers, owner names, symbols, and financial values are synthetic.
The data mimics the shape and distributions of real Portfolio_Positions,
Account_Owner, ESPP_Plan, and equity_historical tables.

Usage (regenerate fixtures):
    python -m portfolio_app.tests.mock_data_generator
    # or from tests/ folder:
    python mock_data_generator.py

The generated JSON files are saved to tests/fixtures/ and are gitignored.
They are also importable directly via ``load_*()`` helpers.
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SEED = 42  # deterministic by default

# --------------------------------------------------------------------------- #
#  Synthetic vocabulary
# --------------------------------------------------------------------------- #

FAKE_SYMBOLS = [
    ("ACME", "Acme Corp"),
    ("BOLT", "Bolt Industries Inc"),
    ("CRYS", "Crystal Dynamics Ltd"),
    ("DUNE", "Dune Energy Holdings"),
    ("ECHO", "Echo Communications Inc"),
    ("FLUX", "Flux Semiconductor Corp"),
    ("GRID", "Grid Power Solutions"),
    ("HALO", "Halo Biotech Inc"),
    ("IRIS", "Iris Pharmaceuticals"),
    ("JADE", "Jade Mining Corp"),
    ("KITE", "Kite Aerospace Inc"),
    ("LUNA", "Luna Financial Group"),
    ("MESA", "Mesa Materials Inc"),
    ("NOVA", "Nova Cybersecurity Corp"),
    ("OPAL", "Opal Data Systems"),
    ("PINE", "Pine Healthcare Inc"),
    ("QUIK", "QuikServe Technologies"),
    ("REEF", "Reef Ocean Sciences"),
    ("STAR", "StarLink Logistics"),
    ("TIER", "Tier One Software Inc"),
    ("UPEX", "UpEx Global Trading"),
    ("VIBE", "Vibe Media Corp"),
    ("WAVE", "Wave Robotics Inc"),
    ("XCEL", "Xcel Clean Energy"),
    ("YARN", "Yarn Textiles Ltd"),
    ("ZERO", "Zero Gravity Labs"),
    # Mutual-fund-like identifiers (alphanumeric)
    ("FND01A", "Alpha Growth Fund Cl A"),
    ("FND02B", "Beta Bond Index Cl B"),
    ("FND03C", "Gamma Balanced Fund Cl C"),
    ("FND04D", "Delta SmallCap Value Cl D"),
]

FAKE_OWNERS = ["Jordan", "Morgan", "Taylor"]

FAKE_ACCOUNTS = [
    ("Individual Brokerage (A10001)", "Jordan"),
    ("Roth IRA (A20002)", "Jordan"),
    ("Company 401K Plan (A30003)", "Jordan"),
    ("529 College Fund Alpha (A40004)", "Jordan"),
    ("529 College Fund Beta (A50005)", "Jordan"),
    ("Health Savings Account (A60006)", "Jordan"),
    ("Individual Brokerage (A70007)", "Morgan"),
    ("Roth IRA (A80008)", "Morgan"),
    ("Company 401K Plan (A30003)", "Morgan"),  # shared 401K
    ("Individual Brokerage (A90009)", "Taylor"),
]

TERMS = ["", "Long", "Short", "Unknown"]
SHARE_SOURCES = ["", "Deposit only", "Stock purchase plan"]

SNAPSHOT_DATES = [
    datetime(2025, 12, 15, 10, 30, 0),
    datetime(2026, 1, 15, 10, 30, 0),
]

# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _rand_price(low: float = 5.0, high: float = 600.0) -> float:
    return round(random.uniform(low, high), 4)


def _rand_quantity(low: float = 0.5, high: float = 500.0) -> float:
    return round(random.uniform(low, high), 4)


def _rand_date(start: date = date(2018, 1, 1), end: date = date(2025, 12, 1)) -> str:
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def _json_serial(obj: Any) -> Any:
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# --------------------------------------------------------------------------- #
#  Generators
# --------------------------------------------------------------------------- #

def generate_account_owner(rng: random.Random | None = None) -> list[dict]:
    """Generate Account_Owner mapping rows."""
    rows = []
    for i, (acct, owner) in enumerate(FAKE_ACCOUNTS, start=1):
        rows.append({
            "id": i,
            "account_name": acct,
            "owner": owner,
            "created_at": datetime(2026, 1, 1, 12, 0, 0).isoformat(),
        })
    return rows


def generate_positions(
    num_lots_per_snapshot: int = 80,
    rng: random.Random | None = None,
) -> list[dict]:
    """
    Generate Portfolio_Positions rows.

    Creates ``num_lots_per_snapshot`` lots for each snapshot date, spread across
    accounts and symbols with realistic value ranges.
    """
    r = rng or random.Random(SEED)
    rows = []
    row_id = 0

    for snap_dt in SNAPSHOT_DATES:
        # Price drift multiplier per snapshot
        drift = 1.0 + r.uniform(-0.05, 0.08)

        for _ in range(num_lots_per_snapshot):
            row_id += 1
            sym, desc = r.choice(FAKE_SYMBOLS)
            acct, owner = r.choice(FAKE_ACCOUNTS)
            qty = _rand_quantity(0.5, 800.0)
            avg_cost = _rand_price(2.0, 500.0)
            cost_total = round(qty * avg_cost, 4)
            # Apply drift + some noise for current value
            current_value = round(cost_total * drift * r.uniform(0.7, 1.5), 4)
            gain_loss = round(current_value - cost_total, 4)
            pct_gl = round((gain_loss / cost_total * 100), 2) if cost_total > 0 else 0.0

            term = r.choice(TERMS)
            acquired = _rand_date()
            source = r.choice(SHARE_SOURCES)
            grant_date = _rand_date() if source == "Stock purchase plan" else None
            transfer_date = (
                (date.fromisoformat(grant_date) + timedelta(days=r.randint(365, 730))).isoformat()
                if grant_date
                else None
            )

            rows.append({
                "id": row_id,
                "snapshot_date": snap_dt.isoformat(),
                "account_name": acct,
                "symbol": sym,
                "description": desc,
                "acquired": acquired,
                "term": term,
                "total_gain_loss": gain_loss,
                "pct_gain_loss": pct_gl,
                "current_value": current_value,
                "quantity": qty,
                "avg_cost_basis": avg_cost,
                "cost_basis_total": cost_total,
                "transfer_avail_date": transfer_date,
                "share_source": source,
                "grant_date": grant_date,
                "owner": owner,  # denormalized for convenience
            })
    return rows


def generate_espp(num_purchases: int = 6, rng: random.Random | None = None) -> list[dict]:
    """Generate synthetic ESPP_Plan purchase records."""
    r = rng or random.Random(SEED + 1)
    rows = []
    base_date = date(2024, 1, 1)

    for i in range(num_purchases):
        offering_start = base_date + timedelta(days=i * 90)
        offering_end = offering_start + timedelta(days=89)
        purchase_date = offering_end
        fmv_start = _rand_price(300.0, 550.0)
        fmv_purchase = fmv_start * r.uniform(0.9, 1.2)
        discount_pct = round(r.uniform(3.0, 15.0), 2)
        purchase_price = round(min(fmv_start, fmv_purchase) * (1 - discount_pct / 100), 4)
        qty = round(r.uniform(3.0, 20.0), 4)
        value = round(purchase_price * qty, 4)
        bargain = round((fmv_purchase - purchase_price) * qty, 4)
        qual_date = offering_start + timedelta(days=r.randint(540, 730))

        rows.append({
            "id": i + 1,
            "offering_period_start": offering_start.isoformat(),
            "offering_period_end": offering_end.isoformat(),
            "purchase_date": purchase_date.isoformat(),
            "fmv_offering_start": round(fmv_start, 4),
            "fmv_purchase_date": round(fmv_purchase, 4),
            "purchase_price": purchase_price,
            "purchase_quantity": qty,
            "purchase_value": value,
            "qualified_disposition_date": qual_date.isoformat(),
            "purchase_deposit_to": r.choice(["Brokerage Account", "ESPP Deposit"]),
            "symbol": "TIER",  # Company stock
            "discount_pct": discount_pct,
            "bargain_element": bargain,
        })
    return rows


def generate_equity_historical(
    symbols: list[str] | None = None,
    days: int = 60,
    rng: random.Random | None = None,
) -> list[dict]:
    """Generate synthetic daily OHLCV data for a few symbols."""
    r = rng or random.Random(SEED + 2)
    symbols = symbols or ["ACME", "BOLT", "FLUX", "TIER", "NOVA"]
    rows = []
    end = date(2026, 1, 20)

    for sym in symbols:
        price = _rand_price(50.0, 400.0)
        for d in range(days):
            dt = end - timedelta(days=days - d - 1)
            if dt.weekday() >= 5:  # skip weekends
                continue
            change_pct = r.uniform(-0.04, 0.04)
            open_ = round(price, 4)
            close = round(price * (1 + change_pct), 4)
            high = round(max(open_, close) * r.uniform(1.0, 1.02), 4)
            low = round(min(open_, close) * r.uniform(0.98, 1.0), 4)
            volume = r.randint(500_000, 80_000_000)
            rows.append({
                "symbol": sym,
                "date": dt.isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "change_percent": round(change_pct * 100, 4),
            })
            price = close  # random walk
    return rows


# --------------------------------------------------------------------------- #
#  Write / Load utilities
# --------------------------------------------------------------------------- #

def write_fixtures(seed: int = SEED) -> Path:
    """Generate all fixtures and write to tests/fixtures/*.json.

    Returns the fixtures directory path.
    """
    random.seed(seed)
    rng = random.Random(seed)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "positions.json": generate_positions(rng=rng),
        "account_owner.json": generate_account_owner(rng=rng),
        "espp.json": generate_espp(rng=rng),
        "equity_historical.json": generate_equity_historical(rng=rng),
    }
    for filename, rows in data.items():
        path = FIXTURES_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=_json_serial)
        print(f"  Wrote {path} ({len(rows)} rows)")

    # Also write a manifest for easy inspection
    manifest = {
        "seed": seed,
        "generated_at": datetime.now().isoformat(),
        "files": {k: len(v) for k, v in data.items()},
    }
    with open(FIXTURES_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"  Wrote manifest.json")
    return FIXTURES_DIR


def load_positions() -> list[dict]:
    """Load positions fixture from disk (or generate on-the-fly)."""
    return _load_or_generate("positions.json", generate_positions)


def load_account_owner() -> list[dict]:
    return _load_or_generate("account_owner.json", generate_account_owner)


def load_espp() -> list[dict]:
    return _load_or_generate("espp.json", generate_espp)


def load_equity_historical() -> list[dict]:
    return _load_or_generate("equity_historical.json", generate_equity_historical)


def _load_or_generate(filename: str, generator_fn) -> list[dict]:
    """Load from disk if exists, otherwise generate with default seed."""
    path = FIXTURES_DIR / filename
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    # First time — generate and cache
    write_fixtures()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
#  CLI entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate mock test fixtures")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--lots", type=int, default=80, help="Lots per snapshot")
    args = parser.parse_args()

    print(f"Generating fixtures (seed={args.seed}, lots_per_snapshot={args.lots})...")
    random.seed(args.seed)
    rng = random.Random(args.seed)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "positions.json": generate_positions(num_lots_per_snapshot=args.lots, rng=rng),
        "account_owner.json": generate_account_owner(rng=rng),
        "espp.json": generate_espp(rng=rng),
        "equity_historical.json": generate_equity_historical(rng=rng),
    }
    for filename, rows in data.items():
        path = FIXTURES_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=_json_serial)
        print(f"  {filename}: {len(rows)} rows")

    manifest = {
        "seed": args.seed,
        "generated_at": datetime.now().isoformat(),
        "files": {k: len(v) for k, v in data.items()},
    }
    with open(FIXTURES_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("Done.")
