r"""Reshape a TradingView 'List of Trades' CSV into our trades.csv schema.

TV emits TWO rows per closed round-trip (exit row FIRST, then entry row,
paired by shared 'Trade number'). Both rows carry the same round-trip P&L
numbers denormalized onto each leg.

Our conformance schema expects ONE row per closed round-trip with
`date_entry / date_exit / price_entry / price_exit / contracts_entry /
contracts_exit` all on the SAME row (see the guide's Part 3.6 and the
discovery walker at `conftest.py:_discover_strategy_triples`).

Usage:
    python reshape_tv_trades.py <input.csv> <output.csv>
    python reshape_tv_trades.py <input.csv> <output.csv> \
        --symbol NASDAQ:AAPL --timeframe 1D \
        --start 2025-01-01 --end 2025-06-30 \
        [--tv-strategy-settings-json path/to/settings.json]

Positional-args form is the pre-D2.2 CLI and still works (back-compat).
The optional metadata flags emit a companion `<output-stem>.meta.json`
alongside the CSV; this metadata feeds the `provenance.json.trades_source`
block in the hybrid-fixture-suite design (see
docs/superpowers/brainstorms/2026-07-20-pine-hybrid-fixture-suite.md §D1.4).

Structural validation (D2.1) applied to every input:
  - Every Trade number has exactly 2 legs (entry + exit)
  - Directions match within a pair (both `long` or both `short`)
  - exit_time > entry_time on every round-trip
  - qty is non-negative

Failures raise ValueError with the offending trade_num in the message.

The script is deterministic + idempotent — running it twice on the same
input produces byte-identical output.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

# Bump when the .meta.json schema changes (D2.2). Consumers (provenance.json
# writer, harness bars loader) can gate on major-version bumps.
RESHAPE_TOOL_VERSION = "1.1.0"


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
    "type",  # "long" or "short" (from the entry-row Type field)
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
    raise ValueError(
        f"Unrecognized Type value: {type_value!r} (expected 'Entry …' / 'Exit …')"
    )


def _direction_from_type(type_value: str) -> str:
    """Return 'long' or 'short' from TV's Type ('Entry long' / 'Exit short' / etc)."""
    tokens = type_value.strip().lower().split()
    if len(tokens) < 2 or tokens[1] not in ("long", "short"):
        raise ValueError(
            f"Unrecognized Type value: {type_value!r} (expected direction as 2nd word)"
        )
    return tokens[1]


def _parse_qty(qty_str: str, trade_num: str) -> float:
    """Parse TV's `Size (qty)` cell to float; raise on non-numeric or negative.

    D2.1: qty must be non-negative — direction lives in Type, not in a
    signed qty. TV never emits negative qty in normal exports, but a
    hand-edit or CSV corruption might; catch it loudly.
    """
    try:
        val = float(qty_str)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"Trade {trade_num}: could not parse qty {qty_str!r} as float ({e})"
        ) from e
    if val < 0:
        raise ValueError(
            f"Trade {trade_num}: qty must be non-negative (got {val}). Direction "
            "lives in Type, not signed qty."
        )
    return val


def _validate_chronology(entry_date: str, exit_date: str, trade_num: str) -> None:
    """D2.1: assert exit_time > entry_time (strict inequality).

    Same-timestamp entry+exit is rejected too — either two fills on the
    same bar (rare but real; requires case-by-case audit) or a data bug.
    """
    if exit_date <= entry_date:
        raise ValueError(
            f"Trade {trade_num}: exit time ({exit_date}) must be strictly "
            f"after entry time ({entry_date}). Same-timestamp or "
            f"exit-before-entry is structurally invalid — check for a "
            f"chronological data corruption."
        )


def reshape(
    input_path: Path,
    output_path: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Reshape input → output. Returns number of round-trips written.

    If ``metadata`` is provided (any subset of ``symbol``, ``timeframe``,
    ``start``, ``end``, ``strategy_settings_path``), emits a companion
    ``<output-stem>.meta.json`` alongside the CSV. The metadata schema
    matches the ``trades_source`` block of provenance.json per the
    hybrid-fixture-suite brainstorm (§D1.4).
    """
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
    for trade_num in sorted(groups.keys(), key=int):
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
                f"Got legs: {[leg['Type'] for leg in legs]}"
            )

        # Sanity check: entry and exit must be same direction
        entry_dir = _direction_from_type(entry_row["Type"])
        exit_dir = _direction_from_type(exit_row["Type"])
        if entry_dir != exit_dir:
            raise ValueError(
                f"Trade number {trade_num}: direction mismatch entry={entry_dir} exit={exit_dir}"
            )

        # D2.1: chronological + qty validation
        entry_date = entry_row.get("Date and time", "").strip()
        exit_date = exit_row.get("Date and time", "").strip()
        _validate_chronology(entry_date, exit_date, trade_num)
        # qty is on both rows and denormalized (same value); validate once.
        _parse_qty(entry_row.get("Size (qty)", ""), trade_num)

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

    # D2.2: metadata capture. If any metadata was passed, emit
    # <output-stem>.meta.json alongside the CSV. The stem strategy
    # handles both `foo.trades.csv` → `foo.trades.meta.json` and
    # `foo.csv` → `foo.meta.json` (Path.with_suffix replaces only the
    # last extension).
    if metadata is not None:
        _write_metadata(output_path, metadata, row_count=len(output_rows))

    return len(output_rows)


def _write_metadata(
    output_path: Path,
    metadata: dict[str, Any],
    *,
    row_count: int,
) -> None:
    """Write ``<output-stem>.meta.json`` next to the reshaped CSV.

    Metadata keys accepted: ``symbol``, ``timeframe``, ``start``, ``end``,
    ``strategy_settings_path``. Unknown keys are dropped silently to keep
    the schema tight.

    Deterministic: fields written in fixed order; ``captured_at`` uses
    UTC date (not datetime) so re-running the same day is idempotent.
    """
    settings_path = metadata.get("strategy_settings_path")
    strategy_settings: dict[str, Any] | None = None
    if settings_path is not None:
        settings_file = Path(settings_path)
        if not settings_file.exists():
            raise FileNotFoundError(
                f"strategy_settings_path does not exist: {settings_file}"
            )
        strategy_settings = json.loads(settings_file.read_text(encoding="utf-8"))

    meta: dict[str, Any] = {
        "schema_version": 1,
        "reshape_tool_version": RESHAPE_TOOL_VERSION,
        "captured_at": _dt.datetime.now(_dt.timezone.utc).date().isoformat(),
        "row_count": row_count,
        "symbol": metadata.get("symbol"),
        "timeframe": metadata.get("timeframe"),
        "start": metadata.get("start"),
        "end": metadata.get("end"),
    }
    if strategy_settings is not None:
        meta["strategy_settings"] = strategy_settings

    meta_path = output_path.with_suffix(".meta.json")
    # If output_path is `foo.trades.csv`, `.with_suffix('.meta.json')` gives
    # `foo.trades.meta.json` — correct. For `foo.csv` it gives
    # `foo.meta.json` — also correct.
    meta_path.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_argparser() -> argparse.ArgumentParser:
    """CLI parser separated for testability."""
    p = argparse.ArgumentParser(
        description=(
            "Reshape TradingView 'List of Trades' CSV into our conformance "
            "fixture trades.csv schema. Optionally emits metadata JSON."
        ),
    )
    p.add_argument("input", type=Path, help="TV List-of-Trades CSV")
    p.add_argument("output", type=Path, help="Reshaped output CSV")
    p.add_argument(
        "--symbol",
        help="Symbol the trades were captured against (e.g. NASDAQ:AAPL)",
    )
    p.add_argument(
        "--timeframe",
        help="Chart timeframe (e.g. 1D, 4H, 15)",
    )
    p.add_argument(
        "--start",
        help="Bar window start (ISO date, e.g. 2025-01-01)",
    )
    p.add_argument(
        "--end",
        help="Bar window end (ISO date, e.g. 2025-06-30)",
    )
    p.add_argument(
        "--tv-strategy-settings-json",
        type=Path,
        help=(
            "Path to a JSON file containing TV Strategy Tester Properties "
            "(commission, slippage, pyramiding, etc). Embedded verbatim "
            "under 'strategy_settings' in the emitted meta.json."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parse argv, invoke :func:`reshape`, echo status.

    Returns ``0`` on success, ``1`` on input-file-not-found.
    Ruff T201 (print-found) is suppressed intentionally — this is CLI
    output, not incidental debug logging.
    """
    # Back-compat: the pre-D2.2 CLI used raw sys.argv positional parsing.
    # argparse understands the same positional shape, so we route through
    # it uniformly. Two-positional-arg invocations continue to work.
    parser = _build_argparser()
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)  # noqa: T201
        return 1

    metadata: dict[str, Any] | None = None
    metadata_flags = (
        args.symbol,
        args.timeframe,
        args.start,
        args.end,
        args.tv_strategy_settings_json,
    )
    if any(v is not None for v in metadata_flags):
        metadata = {
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "start": args.start,
            "end": args.end,
        }
        if args.tv_strategy_settings_json is not None:
            metadata["strategy_settings_path"] = args.tv_strategy_settings_json

    n = reshape(args.input, args.output, metadata=metadata)
    print(f"Wrote {n} round-trips to {args.output}")  # noqa: T201
    if metadata is not None:
        print(f"Wrote metadata to {args.output.with_suffix('.meta.json')}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
