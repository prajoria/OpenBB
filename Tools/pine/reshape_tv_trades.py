"""Reshape a TradingView 'List of Trades' CSV into our trades.csv schema.

TV emits TWO rows per closed round-trip (exit row FIRST, then entry row,
paired by shared 'Trade number'). Both rows carry the same round-trip P&L
numbers denormalized onto each leg.

Our conformance schema expects ONE row per closed round-trip with
`date_entry / date_exit / price_entry / price_exit / contracts_entry /
contracts_exit` all on the SAME row (see the guide's Part 3.6 and the
discovery walker at `conftest.py:_discover_strategy_triples`).

Usage:
    python reshape_tv_trades.py <input.csv> <output.csv>

Example:
    python reshape_tv_trades.py \\
        "C:/Users/daaji/Downloads/RSI_Reversal_NASDAQ_AAPL_2026-07-20.csv" \\
        "openbb_platform/extensions/pine/openbb_pine/tests/conformance_strategy/fixtures/rsi_reversal/rsi_reversal.trades.csv"

The script is deterministic + idempotent — running it twice on the same
input produces byte-identical output.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


# Map TV column names → our column names for the fields shared between
# entry and exit rows (round-trip totals, denormalized on both TV rows).
_SHARED_COLUMN_MAP = {
    "Trade number": "trade_num",
    "Signal": "signal",  # entry/exit signals differ, handled separately below
    "Net PnL USD": "profit",
    "Return %": "profit_percent",
    "Cumulative PnL USD": "cumulative_profit",
    "Cumulative PnL %": "cumulative_profit_percent",
    "Favorable excursion USD": "runup",
    "Adverse excursion USD": "drawdown",
    "Duration (bars)": "bars_in_trade",
    "Commission USD": "commission",
}

# Output column order (deterministic — matches the guide's Part 3.6 spec
# plus the extra excursion/commission columns we get for free from TV).
_OUTPUT_COLUMNS = [
    "trade_num",
    "type",              # "long" or "short" (from the entry-row Type field)
    "signal_entry",
    "date_entry",
    "price_entry",
    "contracts_entry",
    "signal_exit",
    "date_exit",
    "price_exit",
    "contracts_exit",
    "profit",
    "profit_percent",
    "cumulative_profit",
    "cumulative_profit_percent",
    "runup",
    "drawdown",
    "bars_in_trade",
    "commission",
]


def _classify_leg(type_value: str) -> str:
    """Return 'entry' or 'exit' from TV's Type value ('Entry long' / 'Exit long' / etc)."""
    lower = type_value.strip().lower()
    if lower.startswith("entry"):
        return "entry"
    if lower.startswith("exit"):
        return "exit"
    raise ValueError(f"Unrecognized Type value: {type_value!r} (expected 'Entry …' / 'Exit …')")


def _direction_from_type(type_value: str) -> str:
    """Return 'long' or 'short' from TV's Type ('Entry long' / 'Exit short' / etc)."""
    tokens = type_value.strip().lower().split()
    if len(tokens) < 2 or tokens[1] not in ("long", "short"):
        raise ValueError(f"Unrecognized Type value: {type_value!r} (expected direction as 2nd word)")
    return tokens[1]


def reshape(input_path: Path, output_path: Path) -> int:
    """Reshape input → output. Returns number of round-trips written."""
    with input_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    if not rows:
        raise ValueError(f"Input file is empty: {input_path}")

    # Group by Trade number. Each group should have exactly 2 rows
    # (entry + exit). Preserve original order within a group so we
    # can distinguish entry vs exit unambiguously via the Type field.
    groups: dict[str, list[dict]] = {}
    for row in rows:
        trade_num = row.get("Trade number", "").strip()
        if not trade_num:
            continue  # skip any blank/footer rows TV sometimes emits
        groups.setdefault(trade_num, []).append(row)

    output_rows: list[dict[str, str]] = []

    # Sort by Trade number as integer so trade #10 comes after #9, not
    # after #1 (which is what a string-sort would do).
    for trade_num in sorted(groups.keys(), key=lambda x: int(x)):
        legs = groups[trade_num]
        if len(legs) != 2:
            raise ValueError(
                f"Trade number {trade_num} has {len(legs)} rows; expected exactly 2 "
                f"(entry + exit). Check the source CSV for TV output shape drift."
            )

        # Split legs by type
        entry_row = None
        exit_row = None
        for leg in legs:
            leg_type = _classify_leg(leg["Type"])
            if leg_type == "entry":
                entry_row = leg
            else:
                exit_row = leg

        if entry_row is None or exit_row is None:
            raise ValueError(
                f"Trade number {trade_num} missing entry or exit row. "
                f"Got legs: {[l['Type'] for l in legs]}"
            )

        # Sanity check: entry and exit must be same direction
        entry_dir = _direction_from_type(entry_row["Type"])
        exit_dir = _direction_from_type(exit_row["Type"])
        if entry_dir != exit_dir:
            raise ValueError(
                f"Trade number {trade_num}: direction mismatch entry={entry_dir} exit={exit_dir}"
            )

        # Build the collapsed row. Round-trip totals come from either
        # leg (they're identical); take from the entry row by convention.
        collapsed = {
            "trade_num": trade_num,
            "type": entry_dir,  # "long" or "short"
            "signal_entry": entry_row.get("Signal", ""),
            "date_entry": entry_row.get("Date and time", ""),
            "price_entry": entry_row.get("Price USD", ""),
            "contracts_entry": entry_row.get("Size (qty)", ""),
            "signal_exit": exit_row.get("Signal", ""),
            "date_exit": exit_row.get("Date and time", ""),
            "price_exit": exit_row.get("Price USD", ""),
            "contracts_exit": exit_row.get("Size (qty)", ""),
            "profit": entry_row.get("Net PnL USD", ""),
            "profit_percent": entry_row.get("Return %", ""),
            "cumulative_profit": entry_row.get("Cumulative PnL USD", ""),
            "cumulative_profit_percent": entry_row.get("Cumulative PnL %", ""),
            "runup": entry_row.get("Favorable excursion USD", ""),
            "drawdown": entry_row.get("Adverse excursion USD", ""),
            "bars_in_trade": entry_row.get("Duration (bars)", ""),
            "commission": entry_row.get("Commission USD", ""),
        }
        output_rows.append(collapsed)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)

    return len(output_rows)


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <input.csv> <output.csv>", file=sys.stderr)
        return 1
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 1
    n = reshape(input_path, output_path)
    print(f"Wrote {n} round-trips to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
