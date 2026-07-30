"""Export symbol-level basket weight comparison to Excel.

Compares, for a given basket name:
1) Intended weights from ``basket_intended_weight`` (latest import by default)
2) Current basket-scoped weights from ``Portfolio_Positions``
3) Current global snapshot weights from ``portfolio_basket``

Usage
-----
python Tools/export_basket_weight_comparison.py --basket Fortress
python Tools/export_basket_weight_comparison.py --basket Fortress --output Analysis/Fortress_weight_comparison.xlsx
python Tools/export_basket_weight_comparison.py --basket Fortress --database openbb_fmp_cache_test
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "openbb_platform" / "providers" / "fmp_cached"))

from openbb_fmp_cached.utils.database import DatabaseConfig  # noqa: E402


def get_connection(database: Optional[str] = None):
    """Get a pymysql connection with project DB config."""
    params = DatabaseConfig().connection_params
    db_name = database or params.pop("database")
    return pymysql.connect(
        **params,
        database=db_name,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def build_comparison_table(
    basket_name: str,
    database: Optional[str] = None,
    import_date: Optional[str] = None,
    snapshot_date: Optional[str] = None,
    universe: str = "all",
) -> tuple[pd.DataFrame, dict]:
    """Build full symbol-level comparison table for one basket."""
    basket_label = basket_name.strip()
    if not basket_label:
        raise ValueError("basket_name must be non-empty")

    conn = get_connection(database)
    try:
        with conn.cursor() as cur:
            if import_date is None:
                cur.execute(
                    """
                    SELECT MAX(import_date) AS v
                    FROM basket_intended_weight
                    WHERE basket_name = %s
                    """,
                    (basket_label,),
                )
                row = cur.fetchone()
                import_date = row["v"] if row else None
            if import_date is None:
                raise ValueError(
                    f"No rows in basket_intended_weight for basket '{basket_label}'"
                )

            if snapshot_date is None:
                cur.execute(
                    """
                    SELECT MAX(snapshot_date) AS v
                    FROM Portfolio_Positions
                    WHERE basket_name = %s
                    """,
                    (basket_label,),
                )
                row = cur.fetchone()
                snapshot_date = row["v"] if row else None
            if snapshot_date is None:
                raise ValueError(
                    f"No rows in Portfolio_Positions for basket '{basket_label}'"
                )

            query = """
            WITH intended AS (
                SELECT
                    symbol,
                    MAX(description) AS intended_description,
                    MAX(target_weight_pct) AS intended_weight_pct
                FROM basket_intended_weight
                WHERE basket_name = %s
                  AND import_date = %s
                GROUP BY symbol
            ),
            basket_actual AS (
                SELECT
                    symbol,
                    MAX(description) AS positions_description,
                    SUM(current_value) AS positions_current_value,
                    SUM(cost_basis_total) AS positions_cost_basis,
                    SUM(total_gain_loss) AS positions_gain_loss
                FROM Portfolio_Positions
                WHERE basket_name = %s
                  AND snapshot_date = %s
                GROUP BY symbol
            ),
            basket_total AS (
                SELECT SUM(positions_current_value) AS total_value
                FROM basket_actual
            ),
            basket_actual_w AS (
                SELECT
                    b.symbol,
                    b.positions_description,
                    b.positions_current_value,
                    b.positions_cost_basis,
                    b.positions_gain_loss,
                    CASE
                        WHEN t.total_value > 0
                        THEN ROUND(b.positions_current_value / t.total_value * 100, 4)
                        ELSE 0
                    END AS positions_weight_pct
                FROM basket_actual b
                CROSS JOIN basket_total t
            ),
            global_actual AS (
                SELECT
                    symbol,
                    MAX(description) AS global_description,
                    MAX(total_current_value) AS global_current_value,
                    MAX(portfolio_weight_pct) AS global_weight_pct,
                    MAX(total_cost_basis) AS global_cost_basis,
                    MAX(total_gain_loss) AS global_gain_loss,
                    MAX(pct_return) AS global_pct_return
                FROM portfolio_basket
                WHERE snapshot_date = %s
                GROUP BY symbol
            ),
            all_symbols AS (
                SELECT symbol FROM intended
                UNION
                SELECT symbol FROM basket_actual_w
                UNION
                SELECT symbol FROM global_actual
            )
            SELECT
                %s AS basket_name,
                a.symbol,
                COALESCE(i.intended_description, b.positions_description, g.global_description, '') AS description,
                COALESCE(i.intended_weight_pct, 0) AS intended_weight_pct,
                COALESCE(b.positions_weight_pct, 0) AS current_weight_positions_pct,
                COALESCE(g.global_weight_pct, 0) AS current_weight_portfolio_basket_pct,
                COALESCE(b.positions_current_value, 0) AS positions_current_value,
                COALESCE(g.global_current_value, 0) AS global_current_value,
                COALESCE(b.positions_cost_basis, 0) AS positions_cost_basis,
                COALESCE(b.positions_gain_loss, 0) AS positions_gain_loss,
                CASE WHEN i.symbol IS NULL THEN 0 ELSE 1 END AS in_intended,
                CASE WHEN b.symbol IS NULL THEN 0 ELSE 1 END AS in_positions,
                CASE WHEN g.symbol IS NULL THEN 0 ELSE 1 END AS in_portfolio_basket
            FROM all_symbols a
            LEFT JOIN intended i ON i.symbol = a.symbol
            LEFT JOIN basket_actual_w b ON b.symbol = a.symbol
            LEFT JOIN global_actual g ON g.symbol = a.symbol
            ORDER BY a.symbol
            """

            cur.execute(
                query,
                (
                    basket_label,
                    import_date,
                    basket_label,
                    snapshot_date,
                    snapshot_date,
                    basket_label,
                ),
            )
            rows = cur.fetchall()

        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("Comparison query returned no rows")

        df["drift_positions_pct"] = (
            df["current_weight_positions_pct"].astype(float)
            - df["intended_weight_pct"].astype(float)
        ).round(4)
        df["drift_portfolio_basket_pct"] = (
            df["current_weight_portfolio_basket_pct"].astype(float)
            - df["intended_weight_pct"].astype(float)
        ).round(4)

        if universe == "intended":
            df = df[df["in_intended"] == 1].copy()
        elif universe == "positions":
            df = df[df["in_positions"] == 1].copy()
        elif universe == "intersection":
            df = df[(df["in_intended"] == 1) & (df["in_positions"] == 1)].copy()
        elif universe != "all":
            raise ValueError(
                "universe must be one of: all, intended, positions, intersection"
            )

        summary = {
            "basket_name": basket_label,
            "import_date": import_date,
            "snapshot_date": snapshot_date,
            "universe": universe,
            "rows": int(len(df)),
            "intended_sum_pct": float(df["intended_weight_pct"].sum()),
            "positions_sum_pct": float(df["current_weight_positions_pct"].sum()),
            "portfolio_basket_sum_pct": float(df["current_weight_portfolio_basket_pct"].sum()),
            "intended_symbols": int(df["in_intended"].sum()),
            "positions_symbols": int(df["in_positions"].sum()),
            "portfolio_basket_symbols": int(df["in_portfolio_basket"].sum()),
        }

        return df, summary
    finally:
        conn.close()


def export_to_excel(df: pd.DataFrame, summary: dict, output_path: str) -> None:
    """Export summary + symbol-level comparison table to xlsx."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    summary_df = pd.DataFrame([summary])
    with pd.ExcelWriter(output_path) as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        df.to_excel(writer, sheet_name="symbol_comparison", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export basket intended/current weights comparison to Excel"
    )
    parser.add_argument("--basket", required=True, help="Basket name, e.g. Fortress")
    parser.add_argument("--database", default=None, help="Optional DB override")
    parser.add_argument(
        "--import-date",
        default=None,
        help="Optional intended import timestamp (default: latest for basket)",
    )
    parser.add_argument(
        "--snapshot-date",
        default=None,
        help="Optional Portfolio_Positions snapshot datetime (default: latest for basket)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output xlsx path (default: Analysis/<basket>_weight_comparison.xlsx)",
    )
    parser.add_argument(
        "--universe",
        default="all",
        choices=["all", "intended", "positions", "intersection"],
        help=(
            "Symbol universe to export: all (default), intended, positions, or intersection"
        ),
    )
    args = parser.parse_args()

    output = args.output
    if not output:
        output = str(PROJECT_ROOT / "Analysis" / f"{args.basket}_weight_comparison.xlsx")

    df, summary = build_comparison_table(
        basket_name=args.basket,
        database=args.database,
        import_date=args.import_date,
        snapshot_date=args.snapshot_date,
        universe=args.universe,
    )
    export_to_excel(df=df, summary=summary, output_path=output)

    print("Basket comparison exported")
    print(f"  Basket:                     {summary['basket_name']}")
    print(f"  Import date:                {summary['import_date']}")
    print(f"  Snapshot date:              {summary['snapshot_date']}")
    print(f"  Universe:                   {summary['universe']}")
    print(f"  Symbol rows:                {summary['rows']}")
    print(f"  Intended weight sum (%):    {summary['intended_sum_pct']:.4f}")
    print(f"  Positions weight sum (%):   {summary['positions_sum_pct']:.4f}")
    print(
        f"  portfolio_basket sum (%):   {summary['portfolio_basket_sum_pct']:.4f}"
    )
    print(f"  Output:                     {output}")


if __name__ == "__main__":
    main()
