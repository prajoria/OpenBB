#!/usr/bin/env python3
"""Record fmp_cached HTTP fixtures for the ``@pytest.mark.record_http`` suite.

Wrapper around ``pytest -m record_http --record=http --record-no-overwrite``
that adds three things pytest-recorder doesn't do on its own:

1. **Fails loud** when no FMP API key is present — otherwise the "recorded"
   cassette is empty from a 401 and the green "PASS" lies about coverage.
2. **Clears matching L2 cache rows** BEFORE recording so cache-hits don't
   short-circuit the HTTP call (verified failure for
   ``FMPCachedEquityProfileFetcher`` — cached rows in the ``equity_profile``
   table meant pytest-recorder saw zero traffic and wrote no cassette,
   silently).
3. **--endpoint filtering** so contributors can re-record just one endpoint
   after an FMP API change instead of the whole set.

Usage:

  # Record every ``@pytest.mark.record_http`` test that lacks a cassette
  python scripts/pi_fmp_record.py

  # Record just one endpoint (matches test function name substring)
  python scripts/pi_fmp_record.py --endpoint etf_holdings

  # Force re-record even if cassette exists (default is no-overwrite)
  python scripts/pi_fmp_record.py --endpoint etf_holdings --overwrite

Runs against ``.venv_win`` python; assumes ``fmp_cached_api_key`` is in
``~/.openbb_platform/user_settings.json``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FMP_CACHED = REPO_ROOT / "openbb_platform" / "providers" / "fmp_cached"
TEST_FILE = FMP_CACHED / "tests" / "test_fmp_cached_fetchers.py"
CASSETTE_DIR = FMP_CACHED / "tests" / "record" / "http" / "test_fmp_cached_fetchers"

# Cache tables that may short-circuit HTTP when populated. Contributors
# discovered via the equity_profile / etf_holdings recording failure —
# `Fetcher.test(params)` returns success from L2 cache without emitting
# an HTTP call, and pytest-recorder writes no cassette. Cleared before
# each record run so the fetcher goes over the wire.
#
# Format: (test_function_substring, DELETE-SQL, tuple-of-args). Add rows
# when you add a new @record_http test whose fetcher uses L2 cache.
_CACHE_CLEAR_ROWS: list[tuple[str, str, tuple]] = [
    ("equity_profile", "DELETE FROM equity_profile WHERE symbol = %s", ("AAPL",)),
    ("etf_holdings", "DELETE FROM etf_holdings WHERE symbol = %s", ("SPY",)),
    # Other tests don't hit dedicated cache tables — they route through
    # the generic HTTP path.
]


def _check_api_key() -> None:
    """Fail loud if no fmp_cached_api_key is configured."""
    try:
        from openbb_core.app.service.user_service import UserService  # noqa: PLC0415
    except ImportError:
        sys.exit(
            "error: openbb_core not importable — run .venv_win\\Scripts\\python.exe not system python"
        )
    creds = UserService().default_user_settings.credentials.model_dump(mode="json")
    key = creds.get("fmp_cached_api_key") or creds.get("fmp_api_key")
    if not key:
        sys.exit(
            "error: fmp_cached_api_key (or fmp_api_key) not set in "
            "~/.openbb_platform/user_settings.json — "
            "recording without a key produces empty cassettes from 401 responses."
        )
    if len(key) < 20:
        sys.exit(
            f"error: fmp_cached_api_key looks too short ({len(key)} chars); "
            "recording would likely 401. Fix credentials first."
        )


def _clear_cache_for(endpoint_filter: str | None) -> None:
    """Delete cache rows for the endpoints about to be recorded.

    ``endpoint_filter`` is None (clear all in the table) or a substring
    (clear only matching rows). Fails soft — a missing table is expected
    on first run.
    """
    try:
        from openbb_fmp_cached.utils.database import execute_query  # noqa: PLC0415
    except ImportError:
        # Provider not installed in this env — nothing to clear.
        return

    for match, sql, args in _CACHE_CLEAR_ROWS:
        if endpoint_filter and match not in endpoint_filter:
            continue
        try:
            execute_query(sql, args)
        except Exception as exc:  # noqa: BLE001
            # Table might not exist yet; log and continue. The pytest run
            # will fail loud if there's a real problem.
            print(f"note: cache-clear for {match} skipped ({exc})", file=sys.stderr)


def _existing_cassettes() -> set[str]:
    return {p.stem for p in CASSETTE_DIR.glob("*.yaml")}


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--endpoint",
        default=None,
        help="Record only tests whose name contains this substring "
        "(e.g. 'etf_holdings' matches test_fmp_cached_etf_holdings_fetcher).",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Force re-record even if cassette exists (default preserves existing).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would run, don't execute.",
    )
    args = p.parse_args()

    _check_api_key()
    _clear_cache_for(args.endpoint)

    # Build pytest command
    pytest_args = [
        sys.executable,
        "-m",
        "pytest",
        str(TEST_FILE),
        "-m",
        "record_http",
        "--record=http",
    ]
    if not args.overwrite:
        pytest_args.append("--record-no-overwrite")
    if args.endpoint:
        pytest_args += ["-k", args.endpoint]

    if args.dry_run:
        print("would run:", " ".join(pytest_args))
        return 0

    print("recording fixtures →", CASSETTE_DIR)
    result = subprocess.run(pytest_args, cwd=REPO_ROOT)
    if result.returncode != 0:
        print(f"error: pytest returned {result.returncode}", file=sys.stderr)
        return result.returncode

    # Summary of what landed
    print()
    print("cassettes on disk:")
    for c in sorted(_existing_cassettes()):
        size = (CASSETTE_DIR / f"{c}.yaml").stat().st_size
        print(f"  {c}  ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
