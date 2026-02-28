"""Populate the market_holidays table with all US stock market holidays.

Covers 2016-2026 (11 years).  Uses INSERT ... ON DUPLICATE KEY UPDATE
so it is safe to re-run (idempotent).

NYSE/NASDAQ observed holidays:
    - New Year's Day (Jan 1, observed)
    - Martin Luther King Jr. Day (3rd Monday Jan)
    - Presidents' Day (3rd Monday Feb)
    - Good Friday (Friday before Easter)
    - Memorial Day (last Monday May)
    - Juneteenth (Jun 19, observed) -- starting 2022
    - Independence Day (Jul 4, observed)
    - Labor Day (1st Monday Sep)
    - Thanksgiving (4th Thursday Nov)
    - Christmas (Dec 25, observed)
    - Special closures (state funerals, etc.)
"""

import os
import sys
import argparse
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Path setup (same as other Tools scripts)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("FMP_CACHE_AUTO_CREATE_DB", "false")


# ---------------------------------------------------------------------------
# Holiday computation helpers (same logic as _get_basic_market_holidays)
# ---------------------------------------------------------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th occurrence of weekday (0=Mon) in month/year."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the last occurrence of weekday in month/year."""
    d = _nth_weekday(year, month, weekday, 4)
    nxt = d + timedelta(weeks=1)
    return nxt if nxt.month == month else d


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm for Easter Sunday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    """NYSE observed-date rule: Saturday->Friday, Sunday->Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def compute_us_holidays(start_year: int, end_year: int) -> list[tuple]:
    """Return list of (holiday_date, market, holiday_name) tuples."""
    rows = []
    for year in range(start_year, end_year + 1):
        rows.append((_observed(date(year, 1, 1)), "US", "New Year's Day"))
        rows.append((_nth_weekday(year, 1, 0, 3), "US", "Martin Luther King Jr. Day"))
        rows.append((_nth_weekday(year, 2, 0, 3), "US", "Presidents' Day"))
        rows.append((_easter(year) - timedelta(days=2), "US", "Good Friday"))
        rows.append((_last_weekday(year, 5, 0), "US", "Memorial Day"))
        if year >= 2022:
            rows.append((_observed(date(year, 6, 19)), "US", "Juneteenth"))
        rows.append((_observed(date(year, 7, 4)), "US", "Independence Day"))
        rows.append((_nth_weekday(year, 9, 0, 1), "US", "Labor Day"))
        rows.append((_nth_weekday(year, 11, 3, 4), "US", "Thanksgiving"))
        rows.append((_observed(date(year, 12, 25)), "US", "Christmas"))

    # Special closures
    specials = [
        (date(2018, 12, 5), "US", "George H.W. Bush Funeral"),
        (date(2025, 1, 9), "US", "Jimmy Carter Funeral"),
    ]
    for s in specials:
        if start_year <= s[0].year <= end_year:
            rows.append(s)

    return sorted(rows, key=lambda r: r[0])


def main():
    import pymysql
    from openbb_fmp_cached.utils.database import DatabaseConfig

    parser = argparse.ArgumentParser(
        description="Populate US market_holidays table (idempotent upsert with optional range rebuild)."
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2016,
        help="Start year to populate (default: 2016)",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2026,
        help="End year to populate (default: 2026)",
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target MySQL database (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--no-rebuild-range",
        action="store_true",
        help="Do not clear existing rows in range before upsert",
    )
    args = parser.parse_args()

    start_year = args.start_year
    end_year = args.end_year

    if start_year > end_year:
        raise ValueError("start-year must be <= end-year")

    rebuild_range = not args.no_rebuild_range

    print("=" * 60)
    print("  POPULATE market_holidays TABLE")
    print("=" * 60)
    print(f"\n  Range: {start_year} - {end_year}")

    rows = compute_us_holidays(start_year, end_year)
    print(f"  Computed {len(rows)} US market holidays\n")

    # Print them
    print(f"  {'Date':<14s} {'Holiday'}")
    print(f"  {'----':<14s} {'-------'}")
    for hdate, _, hname in rows:
        dow = hdate.strftime("%a")
        print(f"  {str(hdate):<14s} {dow}  {hname}")

    # Connect to database
    config = DatabaseConfig()
    params = config.connection_params
    if args.database:
        params["database"] = args.database

    print(f"\n  Target DB: {params.get('database')}")
    print(f"  Rebuild range: {'YES' if rebuild_range else 'NO'}")
    conn = pymysql.connect(**params)
    try:
        with conn.cursor() as cur:
            if rebuild_range:
                delete_sql = """
                    DELETE FROM market_holidays
                    WHERE market = 'US'
                      AND YEAR(holiday_date) BETWEEN %s AND %s
                """
                cur.execute(delete_sql, (start_year, end_year))
                print(f"\n  Deleted {cur.rowcount} existing US rows in {start_year}-{end_year}")

            # Upsert (idempotent)
            sql = """
                INSERT INTO market_holidays (holiday_date, market, holiday_name)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE holiday_name = VALUES(holiday_name)
            """
            cur.executemany(sql, rows)
            conn.commit()
            affected = cur.rowcount
            print(f"\n  Upserted {affected} rows into market_holidays")

            # Verify
            cur.execute(
                "SELECT YEAR(holiday_date) AS year, COUNT(*) as cnt "
                "FROM market_holidays WHERE market='US' "
                "GROUP BY YEAR(holiday_date) ORDER BY YEAR(holiday_date)"
            )
            print(f"\n  {'Year':<6s} {'Holidays':>8s}")
            print(f"  {'----':<6s} {'--------':>8s}")
            total = 0
            for r in cur.fetchall():
                print(f"  {r[0]:<6d} {r[1]:>8d}")
                total += r[1]
            print(f"\n  Total: {total} rows in market_holidays")

    finally:
        conn.close()

    print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
