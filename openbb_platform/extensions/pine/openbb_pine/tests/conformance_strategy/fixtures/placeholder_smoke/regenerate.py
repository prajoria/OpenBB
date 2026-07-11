"""Regenerate placeholder_smoke expected-value CSVs from a real run_byo call.

Usage (from repo root):

    .venv_win\\Scripts\\python.exe openbb_platform/extensions/pine/openbb_pine/\
tests/conformance_strategy/fixtures/placeholder_smoke/regenerate.py

Records baseline equity/trades/stats output for the never-trading
placeholder strategy. The recorded values are the source of truth for
the three parity assertions — regenerate ONLY when a legitimate change
(e.g. bumped initial_capital default) shifts the baseline, and note
the reason in the commit.
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

HERE = Path(__file__).parent
HARNESS = HERE.parent.parent  # tests/conformance_strategy/
sys.path.insert(0, str(HARNESS))
from conftest import _deterministic_500_bars  # noqa: E402

from openbb_pine.routers.strategies_router import run_byo  # noqa: E402


def main() -> None:
    source = (HERE / "placeholder_smoke.pine").read_text(encoding="utf-8")
    records = _deterministic_500_bars()
    result = asyncio.run(run_byo(source=source, records=records, symbol="TEST"))

    curve = result.extra["equity_curve"]
    with (HERE / "placeholder_smoke.equity.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=["bar_index", "equity", "drawdown"])
        w.writeheader()
        for row in curve:
            w.writerow(row)

    orders = result.extra.get("orders") or []
    # Header always written; body may be empty (never-trades strategy).
    trade_fields = ["id", "direction", "qty", "pnl", "pnl_pct", "bars_held", "comment"]
    if orders and hasattr(orders[0], "__dict__"):
        trade_fields = list(vars(orders[0]).keys())
    elif orders and isinstance(orders[0], dict):
        trade_fields = list(orders[0].keys())
    with (HERE / "placeholder_smoke.trades.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=trade_fields)
        w.writeheader()
        for o in orders:
            row = vars(o) if hasattr(o, "__dict__") else o
            w.writerow({k: row.get(k, "") for k in trade_fields})

    stats = result.extra.get("stats") or {}
    with (HERE / "placeholder_smoke.stats.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.DictWriter(f, fieldnames=list(stats.keys()))
        w.writeheader()
        w.writerow({k: ("" if v is None else v) for k, v in stats.items()})

    print(f"Wrote {len(curve)} equity rows, {len(orders)} trades, "
          f"{len(stats)} stats keys.")
    print(f"trades.csv columns: {trade_fields}")
    print(f"stats keys: {sorted(stats.keys())}")


if __name__ == "__main__":
    main()
