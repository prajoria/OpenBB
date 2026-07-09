"""openbb-daytrade — CLI entry point (Phase 1: doctor only).

Phase 2 adds `run`, `plan`, `snapshot`; Phase 4 adds `alert`; Phase 5 adds
`replay`, `report`. Each subcommand shares the same argparse structure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openbb_fmp_trading.core.doctor import run_doctor


def _cmd_doctor(_args: argparse.Namespace) -> int:
    """openbb-daytrade doctor — print health report and exit 0/1 on errors."""
    state_path = Path.home() / ".openbb_platform" / "fmp_trading" / "bandwidth.json"
    report = run_doctor(
        bandwidth_state_path=state_path,
        bandwidth_budget_bytes=50 * 1024**3,
    )
    print("openbb-daytrade doctor")
    print("=" * 40)
    print(f"  FMP credentials       : {'OK' if report.fmp_credentials_ok else 'MISSING'}")
    print(f"  fmp_cached MySQL      : {'OK' if report.mysql_cache_ok else 'unreachable'}")
    print(f"  exchange_calendars    : {'OK' if report.exchange_calendars_ok else 'MISSING'}")
    print(f"  openbb-techtrade      : {report.techtrade_version} "
          f"({'OK' if report.techtrade_ok else 'MISSING'})")
    print(f"  [agent] extra         : {'installed' if report.agent_extra_installed else 'absent'}")
    print(f"  [xlsxwriter] extra    : {'installed' if report.xlsxwriter_extra_installed else 'absent'}")
    print(f"  [validation] extra    : {'installed' if report.validation_extra_installed else 'absent'}")
    print(f"  Bandwidth remaining   : {report.bandwidth_remaining_pct:.1f}%")
    for w in report.warnings:
        print(f"  WARN: {w}")
    for e in report.errors:
        print(f"  ERROR: {e}")
    return 1 if report.errors else 0


def main(argv: list[str] | None = None) -> int:
    """Top-level CLI dispatch."""
    parser = argparse.ArgumentParser(prog="openbb-daytrade")
    sub = parser.add_subparsers(dest="cmd", required=True)
    doctor_p = sub.add_parser(
        "doctor",
        help="Health-check the environment (FMP creds, cache, extras, bandwidth)",
    )
    doctor_p.set_defaults(func=_cmd_doctor)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
