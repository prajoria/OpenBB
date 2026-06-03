"""
Portfolio Positions — Stats by Owner & Account

Queries the Portfolio_Positions and Account_Owner tables and prints
a summary grouped by owner and account.

Usage
-----
    python Tools/portfolio_stats.py
"""

import os
import sys

# ---------------------------------------------------------------------------
# Path setup (reuse DatabaseConfig from fmp_cached)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]:
    if sub not in sys.path:
        sys.path.insert(0, sub)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass

import pymysql
from openbb_fmp_cached.utils.database import DatabaseConfig


def get_connection():
    config = DatabaseConfig()
    params = config.connection_params
    return pymysql.connect(
        **params,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def main():
    conn = get_connection()
    sep = "=" * 100
    try:
        with conn.cursor() as cur:
            # ---- Table-level stats ----
            cur.execute("SELECT COUNT(*) AS cnt FROM Portfolio_Positions")
            total_rows = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(DISTINCT snapshot_date) AS cnt FROM Portfolio_Positions"
            )
            total_snapshots = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT MIN(snapshot_date) AS mn, MAX(snapshot_date) AS mx "
                "FROM Portfolio_Positions"
            )
            snap_range = cur.fetchone()

            cur.execute("SELECT COUNT(*) AS cnt FROM Account_Owner")
            owner_rows = cur.fetchone()["cnt"]

            print(f"\n{sep}")
            print("  PORTFOLIO POSITIONS — TABLE STATS")
            print(sep)
            print(f"  Total rows:       {total_rows:,}")
            print(f"  Snapshots:        {total_snapshots}")
            print(f"  Earliest:         {snap_range['mn']}")
            print(f"  Latest:           {snap_range['mx']}")
            print(f"  Account_Owner:    {owner_rows} mapping(s)")

            # ---- Account_Owner mappings ----
            cur.execute(
                "SELECT owner, account_name FROM Account_Owner ORDER BY owner, account_name"
            )
            ao_rows = cur.fetchall()

            print(f"\n{sep}")
            print("  ACCOUNT → OWNER MAPPINGS")
            print(sep)
            print(f"  {'Owner':<20} {'Account':<60}")
            print(f"  {'-'*20} {'-'*60}")
            for r in ao_rows:
                print(f"  {r['owner']:<20} {r['account_name']:<60}")

            # ---- Stats by owner ----
            cur.execute("""
                SELECT
                    ao.owner,
                    COUNT(*)                       AS lots,
                    COUNT(DISTINCT pp.symbol)       AS stocks,
                    SUM(pp.quantity)                AS total_qty,
                    SUM(pp.cost_basis_total)        AS total_cost,
                    SUM(pp.current_value)           AS total_value,
                    SUM(pp.total_gain_loss)         AS total_gl,
                    MAX(pp.snapshot_date)            AS latest_snapshot
                FROM Portfolio_Positions pp
                JOIN Account_Owner ao ON pp.account_name = ao.account_name
                GROUP BY ao.owner
                ORDER BY total_value DESC
            """)
            owner_stats = cur.fetchall()

            print(f"\n{sep}")
            print("  BY OWNER (latest snapshot per account)")
            print(sep)
            print(
                f"  {'Owner':<20} {'Lots':>5} {'Stocks':>7} "
                f"{'Cost Basis':>15} {'Cur Value':>15} "
                f"{'Gain/Loss':>15} {'Return':>8}  {'Snapshot'}"
            )
            print(
                f"  {'-'*20} {'-'*5} {'-'*7} "
                f"{'-'*15} {'-'*15} {'-'*15} {'-'*8}  {'-'*19}"
            )
            for r in owner_stats:
                ret = (
                    float(r["total_gl"]) / float(r["total_cost"]) * 100
                    if r["total_cost"]
                    else 0
                )
                print(
                    f"  {r['owner']:<20} {r['lots']:>5} {r['stocks']:>7} "
                    f"${float(r['total_cost']):>14,.2f} "
                    f"${float(r['total_value']):>14,.2f} "
                    f"${float(r['total_gl']):>14,.2f} "
                    f"{ret:>7.1f}%  {r['latest_snapshot']}"
                )

            # ---- Stats by account ----
            cur.execute("""
                SELECT
                    COALESCE(ao.owner, '(unassigned)') AS owner,
                    pp.account_name,
                    COUNT(*)                        AS lots,
                    COUNT(DISTINCT pp.symbol)        AS stocks,
                    SUM(pp.quantity)                 AS total_qty,
                    SUM(pp.cost_basis_total)         AS total_cost,
                    SUM(pp.current_value)            AS total_value,
                    SUM(pp.total_gain_loss)          AS total_gl,
                    MAX(pp.snapshot_date)             AS latest_snapshot
                FROM Portfolio_Positions pp
                LEFT JOIN Account_Owner ao ON pp.account_name = ao.account_name
                GROUP BY ao.owner, pp.account_name
                ORDER BY ao.owner, total_value DESC
            """)
            acct_stats = cur.fetchall()

            print(f"\n{sep}")
            print("  BY ACCOUNT")
            print(sep)
            print(
                f"  {'Owner':<16} {'Account':<42} {'Lots':>5} {'Stk':>4} "
                f"{'Cost Basis':>15} {'Cur Value':>15} "
                f"{'Gain/Loss':>15} {'Ret':>7}"
            )
            print(
                f"  {'-'*16} {'-'*42} {'-'*5} {'-'*4} "
                f"{'-'*15} {'-'*15} {'-'*15} {'-'*7}"
            )
            for r in acct_stats:
                ret = (
                    float(r["total_gl"]) / float(r["total_cost"]) * 100
                    if r["total_cost"]
                    else 0
                )
                print(
                    f"  {r['owner']:<16} {str(r['account_name'])[:42]:<42} "
                    f"{r['lots']:>5} {r['stocks']:>4} "
                    f"${float(r['total_cost']):>14,.2f} "
                    f"${float(r['total_value']):>14,.2f} "
                    f"${float(r['total_gl']):>14,.2f} "
                    f"{ret:>6.1f}%"
                )

            # ---- Snapshot history ----
            cur.execute("""
                SELECT
                    snapshot_date,
                    COUNT(*)                   AS lots,
                    COUNT(DISTINCT symbol)      AS stocks,
                    COUNT(DISTINCT account_name) AS accounts,
                    SUM(cost_basis_total)       AS total_cost,
                    SUM(current_value)          AS total_value,
                    SUM(total_gain_loss)        AS total_gl
                FROM Portfolio_Positions
                GROUP BY snapshot_date
                ORDER BY snapshot_date
            """)
            snap_stats = cur.fetchall()

            print(f"\n{sep}")
            print("  SNAPSHOT HISTORY")
            print(sep)
            print(
                f"  {'Snapshot':<21} {'Lots':>5} {'Stk':>4} {'Accts':>5} "
                f"{'Cost Basis':>15} {'Cur Value':>15} {'Gain/Loss':>15}"
            )
            print(
                f"  {'-'*21} {'-'*5} {'-'*4} {'-'*5} "
                f"{'-'*15} {'-'*15} {'-'*15}"
            )
            for r in snap_stats:
                print(
                    f"  {str(r['snapshot_date']):<21} {r['lots']:>5} "
                    f"{r['stocks']:>4} {r['accounts']:>5} "
                    f"${float(r['total_cost']):>14,.2f} "
                    f"${float(r['total_value']):>14,.2f} "
                    f"${float(r['total_gl']):>14,.2f}"
                )

            print(f"\n{sep}\n")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
