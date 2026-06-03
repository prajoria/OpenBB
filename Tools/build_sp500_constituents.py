"""
Populate the sp500_constituents cache via the fmp_cached provider module.

Thin CLI wrapper around openbb_fmp_cached.models.index_constituents.populate_cache().

Usage:
    python Tools/build_sp500_constituents.py
    python Tools/build_sp500_constituents.py --source api
    python Tools/build_sp500_constituents.py --source copy --source-database fmp_cache
    python Tools/build_sp500_constituents.py --database openbb_fmp_cache_test --source copy
"""

import os
import sys
import argparse

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
# Also add any openbb_platform/extensions/*/
_ext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "extensions")
if os.path.isdir(_ext_root):
    for _d in os.listdir(_ext_root):
        _dp = os.path.join(_ext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)
# And openbb_platform/obbject_extensions/*/
_obbext_root = os.path.join(PROJECT_ROOT, "openbb_platform", "obbject_extensions")
if os.path.isdir(_obbext_root):
    for _d in os.listdir(_obbext_root):
        _dp = os.path.join(_obbext_root, _d)
        if os.path.isdir(_dp):
            _SRC_DIRS.append(_dp)

for _p in _SRC_DIRS:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env so FMP_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser(
        description="Populate sp500_constituents table via fmp_cached module"
    )
    parser.add_argument(
        "--database",
        default=None,
        help="Target database name (default: from DatabaseConfig / FMP_CACHE_TEST_MODE)",
    )
    parser.add_argument(
        "--source",
        choices=["api", "copy"],
        default="copy",
        help="Data source: 'api' to fetch from FMP, 'copy' to copy from --source-database (default: copy)",
    )
    parser.add_argument(
        "--source-database",
        default="fmp_cache",
        help="Database to copy from when --source=copy (default: fmp_cache)",
    )
    args = parser.parse_args()

    # Import the module's public API
    from openbb_fmp_cached.models.index_constituents import populate_cache

    print(f"🔧 Populating sp500_constituents (source: {args.source})")

    stats = populate_cache(
        source=args.source,
        source_database=args.source_database,
        target_database=args.database,
    )

    print(f"\n{'='*50}")
    print(f"✅ Done — {stats['database']}")
    print(f"   Total rows: {stats['total_rows']}")
    print(f"   Sectors:    {stats['sectors']}")
    print(f"   Top sectors:")
    for s in stats["top_sectors"]:
        print(f"     {s['gics_sector']:30s} {s['cnt']:>4} companies")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
