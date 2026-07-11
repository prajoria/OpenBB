"""openbb-daytrade — CLI entry point.

Phase 1 shipped `doctor`. Phase 3 P3.3 adds `mcp-serve` (stdio MCP
server; `[agent]` extra required). Phase 2 adds `run`, `plan`,
`snapshot`; Phase 4 adds `alert`; Phase 5 adds `replay`, `report`.
Each subcommand shares the same argparse structure.
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


def _cmd_mcp_serve(_args: argparse.Namespace) -> int:
    """openbb-daytrade mcp-serve — start the stdio MCP server (P3.3 / #85).

    Requires the ``[agent]`` extra. Emits a friendly install-hint on
    missing extra rather than an ImportError stack trace. This is the
    entry point external MCP clients (Claude Desktop, VS Code MCP)
    connect to.
    """
    # Extra check happens BEFORE importing agent.* to keep the "missing
    # extra" error message clean.
    try:
        from openbb_fmp_trading.agent import is_agent_available
    except ImportError:
        print(
            "ERROR: openbb-fmp-trading[agent] extra not installed.\n"
            "       pip install 'openbb-fmp-trading[agent]'",
            file=sys.stderr,
        )
        return 1

    if not is_agent_available():
        print(
            "ERROR: [agent] extra dependencies missing (anthropic + mcp + jinja2).\n"
            "       pip install 'openbb-fmp-trading[agent]'",
            file=sys.stderr,
        )
        return 1

    # Lazy import — agent.mcp_server pulls in the mcp SDK
    from openbb_fmp_trading.agent.mcp_server import run_stdio_server

    print("openbb-daytrade mcp-serve — starting stdio MCP server", file=sys.stderr)
    return run_stdio_server()


def main(argv: list[str] | None = None) -> int:
    """Top-level CLI dispatch."""
    parser = argparse.ArgumentParser(prog="openbb-daytrade")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor_p = sub.add_parser(
        "doctor",
        help="Health-check the environment (FMP creds, cache, extras, bandwidth)",
    )
    doctor_p.set_defaults(func=_cmd_doctor)

    mcp_p = sub.add_parser(
        "mcp-serve",
        help="Start the stdio MCP server (requires [agent] extra; PRD §7.3)",
    )
    mcp_p.set_defaults(func=_cmd_mcp_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

