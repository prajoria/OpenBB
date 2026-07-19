"""Test-portfolio data generator — Fidelity-shaped CSV with randomized inputs.

Produces a Fidelity-shaped ``Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user_id>.csv``
suitable for driving the snapshot importer designed in
``docs/superpowers/specs/2026-07-18-portfolio-snapshot-importer-design.md``
and the ``portfolio_export.loaders.fidelity`` loader.

Design rules
------------
Fields kept **as-is** from the template (never randomized):

    Symbol, Description, Quantity, Last price

Free inputs (randomized within realistic bounds):

    Last price change, Average cost basis (as ratio of Last price),
    Account number selection (round-robin from --accounts), user_id
    selection (round-robin from --user-ids).

Derived fields (**computed to satisfy Fidelity's definitional invariants**):

    Current value        = Quantity × Last price
    Cost basis total     = Quantity × Average cost basis
    Total gain/loss $    = Current value − Cost basis total
    Total gain/loss %    = Total gain/loss $ / Cost basis total × 100
    Today's gain/loss $  = Quantity × Last price change
    Today's gain/loss %  = Last price change / (Last price − Last price change) × 100
    Percent of account   = row Current value / SUM(Current value in same account) × 100

This is a physics-consistent generator (not just shape-consistent), so
tests can assert exact equality on the invariants. A "shape only" random
generator would let importer bugs like "swapped Current value with Cost
basis total" pass silently; consistent data surfaces them.

Multi-user support
------------------
Fidelity's export CSV includes a ``user_id`` column, so a single file
can hold positions belonging to multiple users (household exports).
Use ``--user-ids alice,bob`` to round-robin rows across multiple users
so a single generated CSV represents such a household export. Filename
uses the first user_id from the list (matches the file-naming
convention when the export is scoped to one primary user).

Non-goals (call these out explicitly)
-------------------------------------
- No 52-week range column — the design spec's ``position`` table doesn't
  store it and the loader doesn't consume it. Add later if analytics
  needs it.
- No "Not Priced Today" weekend placeholder — the loader coerces
  non-numeric ``Last price`` to NaN, which would break the invariants
  every downstream test depends on. Simulate weekend imports by
  passing a specific ``--date`` (Saturday/Sunday) instead.
- No corporate-action reconciliation, no intraday-fill skew — the
  invariants hold exactly by construction.

Usage
-----
    # Single-user, default 10-row preset
    python scripts/test_portfolio_data_generator.py

    # Multi-user household file
    python scripts/test_portfolio_data_generator.py \\
        --user-ids alice,bob \\
        --accounts X78542853,Z12345678 \\
        --date 2026-07-18

    # Custom template (CSV or JSON with Symbol/Description/Quantity/Last price)
    python scripts/test_portfolio_data_generator.py \\
        --template scripts/fixtures/test_holdings.csv \\
        --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Column contract — matches portfolio_export.loaders.fidelity constants +
# adds Fidelity's per-row user_id column (present in real exports; supports
# multi-user household files).
# ---------------------------------------------------------------------------
FIDELITY_HEADER: tuple[str, ...] = (
    "Account number",
    "Account name",
    "Symbol",
    "Description",
    "Quantity",
    "Last price",
    "Last price change",
    "Current value",
    "Today's gain/loss dollar",
    "Today's gain/loss percent",
    "Total gain/loss dollar",
    "Total gain/loss percent",
    "Percent of account",
    "Cost basis total",
    "Average cost basis",
    "Type",
    "user_id",
)

KEEP_AS_IS: frozenset[str] = frozenset(
    {"Symbol", "Description", "Quantity", "Last price"}
)


# ---------------------------------------------------------------------------
# Built-in preset — small, realistic US-equity + one ETF + one money-market
# fund. Only Symbol / Description / Quantity / Last price flow to output
# verbatim; everything else is randomized or computed per-row.
# ---------------------------------------------------------------------------
DEFAULT_HOLDINGS: tuple[dict[str, object], ...] = (
    {
        "Symbol": "AAPL",
        "Description": "APPLE INC",
        "Quantity": 42.0,
        "Last price": 187.50,
    },
    {
        "Symbol": "MSFT",
        "Description": "MICROSOFT CORP",
        "Quantity": 25.0,
        "Last price": 412.30,
    },
    {
        "Symbol": "GOOGL",
        "Description": "ALPHABET INC CL A",
        "Quantity": 60.0,
        "Last price": 178.90,
    },
    {
        "Symbol": "AMZN",
        "Description": "AMAZON.COM INC",
        "Quantity": 15.0,
        "Last price": 195.20,
    },
    {
        "Symbol": "NVDA",
        "Description": "NVIDIA CORP",
        "Quantity": 30.0,
        "Last price": 122.10,
    },
    {
        "Symbol": "SPY",
        "Description": "SPDR S&P 500 ETF TR",
        "Quantity": 100.0,
        "Last price": 555.75,
    },
    {
        "Symbol": "VTI",
        "Description": "VANGUARD TOTAL STOCK MKT ETF",
        "Quantity": 80.0,
        "Last price": 268.40,
    },
    {
        "Symbol": "TLT",
        "Description": "ISHARES 20+ YEAR TREAS BD ETF",
        "Quantity": 50.0,
        "Last price": 95.60,
    },
    {
        "Symbol": "SPAXX",
        "Description": "FIDELITY GOVERNMENT MMKT",
        "Quantity": 5000.0,
        "Last price": 1.00,
    },
    {
        "Symbol": "BRK.B",
        "Description": "BERKSHIRE HATHAWAY INC CL B",
        "Quantity": 12.0,
        "Last price": 468.20,
    },
)


# ---------------------------------------------------------------------------
# Randomization bounds — only on the two free inputs.
# ---------------------------------------------------------------------------
@dataclass
class _RandomBounds:
    """Bounds for the free-input fields.

    Everything else in the generated row is a deterministic function of
    (Quantity, Last price, Last price change ratio, Cost basis ratio).
    """

    last_price_change_pct_of_price: tuple[float, float] = (-3.0, 3.0)
    cost_basis_ratio: tuple[float, float] = (0.55, 1.35)


BOUNDS = _RandomBounds()

# Money-market fund heuristics — Fidelity leaves gain/loss cells blank
# for MMKT rows.
_MMKT_HINTS = ("MMKT", "MONEY MARKET", "TREASURY MMKT", "GOVERNMENT MMKT")
_MMKT_SYMBOLS = ("SPAXX", "FDRXX", "FZFXX", "SPRXX", "VMFXX", "VMRXX")


def _looks_like_money_market(symbol: str, description: str) -> bool:
    upper_desc = description.upper()
    return symbol.upper() in _MMKT_SYMBOLS or any(h in upper_desc for h in _MMKT_HINTS)


# ---------------------------------------------------------------------------
# Fidelity formatting helpers.
# ---------------------------------------------------------------------------


def _fmt_money(x: float) -> str:
    """'$X,XXX.XX' with 2-decimal precision, thousands sep, sign as '-'."""
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _fmt_percent(x: float) -> str:
    """'+X.XX%' / '-X.XX%'."""
    return f"{x:+.2f}%"


def _fmt_quantity(q: float) -> str:
    """Fractional shares: drop trailing zeros; integers stay integer."""
    return f"{q:.4f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Per-row generation. Returns a dict keyed by FIDELITY_HEADER columns,
# with money/percent fields already formatted. `Percent of account`
# is left as None here — filled in by a second pass that has visibility
# into all rows per account.
# ---------------------------------------------------------------------------


def _generate_row(
    tmpl: dict[str, object],
    *,
    account_number: str,
    account_name: str,
    user_id: str,
    account_type: str,
    rng: random.Random,
) -> dict[str, str | None]:
    """Generate one Fidelity-shaped position row from a template + inputs.

    Template must supply Symbol, Description, Quantity, Last price.
    All other fields are derived from randomized free inputs so that
    Fidelity's definitional invariants hold exactly.
    """
    symbol = str(tmpl["Symbol"])
    description = str(tmpl["Description"])
    quantity = float(tmpl["Quantity"])
    last_price = float(tmpl["Last price"])

    is_mmkt = _looks_like_money_market(symbol, description)

    # --- Free inputs ---
    # Last price change: fraction of Last price, e.g. -3% .. +3%.
    lpc_pct = rng.uniform(*BOUNDS.last_price_change_pct_of_price)
    last_price_change = last_price * lpc_pct / 100.0
    # Average cost basis: ratio of current Last price, e.g. 0.55 .. 1.35
    # (bought below or above current price).
    cb_ratio = rng.uniform(*BOUNDS.cost_basis_ratio)
    average_cost_basis = last_price * cb_ratio

    # --- Derived (definitional invariants — DO NOT randomize) ---
    current_value = quantity * last_price
    cost_basis_total = quantity * average_cost_basis
    total_gl_dollar = current_value - cost_basis_total
    total_gl_pct = (
        (total_gl_dollar / cost_basis_total * 100.0) if cost_basis_total else 0.0
    )
    today_gl_dollar = quantity * last_price_change
    prev_close = last_price - last_price_change
    today_gl_pct = (last_price_change / prev_close * 100.0) if prev_close else 0.0

    row: dict[str, str | None] = {
        "Account number": account_number,
        "Account name": account_name,
        "Symbol": symbol,
        "Description": description,
        "Quantity": _fmt_quantity(quantity),
        "Last price": _fmt_money(last_price),
        "Last price change": _fmt_money(last_price_change),
        "Current value": _fmt_money(current_value),
        "Today's gain/loss dollar": "" if is_mmkt else _fmt_money(today_gl_dollar),
        "Today's gain/loss percent": "" if is_mmkt else _fmt_percent(today_gl_pct),
        "Total gain/loss dollar": "" if is_mmkt else _fmt_money(total_gl_dollar),
        "Total gain/loss percent": "" if is_mmkt else _fmt_percent(total_gl_pct),
        "Percent of account": None,  # filled in by _fill_percent_of_account
        "Cost basis total": "" if is_mmkt else _fmt_money(cost_basis_total),
        "Average cost basis": "" if is_mmkt else _fmt_money(average_cost_basis),
        "Type": account_type,
        "user_id": user_id,
    }
    # Stash the raw Current value for the account-total pass.
    row["_current_value_raw"] = current_value  # type: ignore[assignment]
    return row


def _fill_percent_of_account(rows: list[dict[str, str | None]]) -> None:
    """Second pass: compute % of account across all rows sharing an account.

    Per Fidelity: (row current value) / (sum of current values within the
    same Account number) × 100. Modifies rows in place; strips the
    ``_current_value_raw`` helper key.
    """
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        acct = str(r["Account number"])
        totals[acct] += float(r["_current_value_raw"])  # type: ignore[arg-type]

    for r in rows:
        acct = str(r["Account number"])
        cv = float(r["_current_value_raw"])  # type: ignore[arg-type]
        pct = (cv / totals[acct] * 100.0) if totals[acct] else 0.0
        r["Percent of account"] = _fmt_percent(pct)
        del r["_current_value_raw"]


# ---------------------------------------------------------------------------
# Template loading (CSV or JSON with Symbol/Description/Quantity/Last price).
# ---------------------------------------------------------------------------


def _load_template(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return [dict(r) for r in DEFAULT_HOLDINGS]
    if not path.exists():
        raise FileNotFoundError(f"template not found: {path}")

    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as f:
            rows = list(json.load(f))
    else:
        with path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))

    out: list[dict[str, object]] = []
    required = ("Symbol", "Description", "Quantity", "Last price")
    for i, r in enumerate(rows, start=1):
        missing = [k for k in required if k not in r]
        if missing:
            raise ValueError(f"template row {i} missing columns: {missing}")
        out.append(
            {
                "Symbol": str(r["Symbol"]).strip(),
                "Description": str(r["Description"]).strip(),
                "Quantity": float(str(r["Quantity"]).replace(",", "")),
                "Last price": float(
                    str(r["Last price"]).replace("$", "").replace(",", "")
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Filename convention.
# ---------------------------------------------------------------------------


def _default_filename(user_id: str, snapshot_date: date) -> str:
    """Fidelity: Portfolio_Positions_<Mon>-<DD>-<YYYY>_<user>.csv."""
    mon = snapshot_date.strftime("%b")
    return f"Portfolio_Positions_{mon}-{snapshot_date.day:02d}-{snapshot_date.year}_{user_id}.csv"


# ---------------------------------------------------------------------------
# Writer (Fidelity's trailing-comma quirk is off by default now — the loader
# tolerates both; keep clean unless explicitly asked to exercise the quirk).
# ---------------------------------------------------------------------------


def _write_csv(
    out_path: Path,
    rows: list[dict[str, str | None]],
    *,
    trailing_comma_quirk: bool,
) -> None:
    header = list(FIDELITY_HEADER)
    if trailing_comma_quirk:
        header.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        for r in rows:
            values = [r.get(col) or "" for col in FIDELITY_HEADER]
            if trailing_comma_quirk:
                values.append("")
            w.writerow(values)


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a Fidelity-shaped test portfolio CSV with "
        "physics-consistent randomized inputs.",
    )
    p.add_argument(
        "--user-ids",
        default="testuser",
        help="Comma-separated user_ids. Rows round-robin across them; "
        "filename uses the first one. Default: testuser",
    )
    p.add_argument(
        "--accounts",
        default="X78542853",
        help="Comma-separated account numbers. Rows round-robin across them. "
        "Default: X78542853",
    )
    p.add_argument(
        "--account-type",
        default="Cash",
        help="Value for the Type column (Cash / Margin / IRA / etc.). Default: Cash",
    )
    p.add_argument(
        "--date", default=None, help="Snapshot date YYYY-MM-DD (default: today)"
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path (default: ./test_portfolio_output/<fidelity-name>)",
    )
    p.add_argument(
        "--template",
        default=None,
        help="CSV or JSON template with Symbol/Description/Quantity/Last price "
        "(default: 10-row built-in preset)",
    )
    p.add_argument(
        "--seed", type=int, default=None, help="RNG seed for reproducibility"
    )
    p.add_argument(
        "--trailing-comma",
        action="store_true",
        help="Emit Fidelity's trailing-comma quirk (default: off; loader tolerates both)",
    )
    args = p.parse_args(argv)

    snapshot_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    )
    user_ids = [u.strip() for u in args.user_ids.split(",") if u.strip()]
    accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    if not user_ids or not accounts:
        p.error("--user-ids and --accounts must each have at least one value")

    template = _load_template(Path(args.template) if args.template else None)
    out_path = (
        Path(args.out)
        if args.out
        else Path("test_portfolio_output")
        / _default_filename(user_ids[0], snapshot_date)
    )

    rng = random.Random(args.seed)
    rows: list[dict[str, str | None]] = []
    for i, tmpl in enumerate(template):
        acct = accounts[i % len(accounts)]
        uid = user_ids[i % len(user_ids)]
        acct_name = f"Test Individual - {uid}"
        rows.append(
            _generate_row(
                tmpl,
                account_number=acct,
                account_name=acct_name,
                user_id=uid,
                account_type=args.account_type,
                rng=rng,
            )
        )
    _fill_percent_of_account(rows)

    _write_csv(out_path, rows, trailing_comma_quirk=args.trailing_comma)

    print(  # noqa: T201
        f"Wrote {len(rows)} row(s) to {out_path}\n"
        f"  users={user_ids}  accounts={accounts}  date={snapshot_date}  seed={args.seed}\n"
        f"  Header: {len(FIDELITY_HEADER)} named cols"
        + (" + 1 trailing (quirk)" if args.trailing_comma else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
