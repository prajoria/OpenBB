"""openbb-daytrade — CLI entry point.

Phase 1 shipped `doctor`. Phase 3 P3.3 added `mcp-serve` (stdio MCP
server; `[agent]` extra required). Phase 5 P5.4 adds `report` +
`replay` — the two post-session tools operators run manually.
Phase 2 adds `run`, `plan`, `snapshot`; Phase 4 adds `alert`. Each
subcommand shares the same argparse structure.
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

    from openbb_fmp_trading.agent.mcp_server import run_stdio_server

    print("openbb-daytrade mcp-serve — starting stdio MCP server", file=sys.stderr)
    return run_stdio_server()


def _cmd_report(args: argparse.Namespace) -> int:
    """openbb-daytrade report — render session artifacts.

    Delegates to ``obb.fmp_trading.report()`` (P5.1). Output paths are
    printed as a manifest. Any warnings (e.g. xlsx skipped because
    openbb-techtrade unavailable) print to stderr.
    """
    from openbb_fmp_trading.reporting.report import (
        OutputExists,
        OutputPathEscapesJail,
        report,
    )

    try:
        manifest = report(
            session_id=args.session,
            format=args.format,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            include_agent_narrative=not args.no_agent_narrative,
            overwrite=args.overwrite,
        )
    except OutputExists as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "       Pass --overwrite to regenerate the existing report.",
            file=sys.stderr,
        )
        return 2
    except OutputPathEscapesJail as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "       Set FMP_TRADING_REPORTS_ROOT env var to widen the "
            "reports jail if needed.",
            file=sys.stderr,
        )
        return 3
    except FileNotFoundError as exc:
        print(f"ERROR: journal not found for session {args.session!r}: {exc}",
              file=sys.stderr)
        return 4

    print("openbb-daytrade report")
    print("=" * 40)
    print(f"  Session       : {manifest.session_id}")
    print(f"  Session date  : {manifest.session_date}")
    print(f"  Events read   : {manifest.session_events_count}")
    print(f"  Agent backend : {manifest.agent_backend or '(none / narrator)'}")
    if manifest.md_path:
        print(f"  MD            : {manifest.md_path}")
    if manifest.json_path:
        print(f"  JSON          : {manifest.json_path}")
    if manifest.xlsx_path:
        print(f"  XLSX          : {manifest.xlsx_path}")
    for w in manifest.warnings:
        print(f"  WARN: {w}", file=sys.stderr)
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    """openbb-daytrade replay — deterministic journal reconstruction.

    Takes a session_id (path-jailed via session_journal_path). Reports
    ``diverged_at_tick`` on divergence unless ``--raise-on-divergence``
    is passed, in which case it raises ReplayDivergenceError (default:
    True, matching the router).
    """
    from openbb_fmp_trading.reporting.errors import ReplayDivergenceError
    from openbb_fmp_trading.reporting.journal_reader import (
        session_journal_path,
    )
    from openbb_fmp_trading.reporting.replay import replay

    try:
        journal_path = session_journal_path(args.session)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 5

    try:
        result = replay(
            journal_path,
            from_tick=args.from_tick,
            to_tick=args.to_tick,
            raise_on_divergence=not args.no_raise,
        )
    except ReplayDivergenceError as exc:
        print(f"DIVERGENCE at tick {exc.tick_index}", file=sys.stderr)
        print(f"  event_type: {exc.event_type}", file=sys.stderr)
        print(f"  field     : {exc.field}", file=sys.stderr)
        print(f"  expected  : {exc.expected!r}", file=sys.stderr)
        print(f"  actual    : {exc.actual!r}", file=sys.stderr)
        return 6
    except FileNotFoundError as exc:
        print(f"ERROR: journal not found: {exc}", file=sys.stderr)
        return 4

    print("openbb-daytrade replay")
    print("=" * 40)
    print(f"  Session          : {result.session_id}")
    print(f"  Session date     : {result.session_date}")
    print(f"  Events replayed  : {result.events_replayed}")
    if result.daily_plan:
        print(f"  Plan watchlist   : {result.daily_plan.watchlist}")
        print(f"  Plan preset      : {result.daily_plan.preset}")
    if result.diverged_at_tick is not None:
        print(f"  Diverged at tick : {result.diverged_at_tick}")
        return 6
    print(f"  Diverged at tick : (no divergence)")
    return 0


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

    report_p = sub.add_parser(
        "report",
        help="Render session artifacts as MD + XLSX + JSON (P5.1 / PRD §4.6)",
    )
    report_p.add_argument("--session", required=True,
                          help="Session id (e.g. s20260713143025)")
    report_p.add_argument(
        "--format",
        default="all",
        choices=["md", "xlsx", "json", "all"],
        help="Which formats to emit (default: all)",
    )
    report_p.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Target directory (must be inside FMP_TRADING_REPORTS_ROOT jail). "
            "Default: <jail>/daytrade_<date>/"
        ),
    )
    report_p.add_argument(
        "--no-agent-narrative",
        action="store_true",
        help=(
            "Force the deterministic Jinja narrator even if the journal "
            "has an LLM briefing_md_content"
        ),
    )
    report_p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing report files (default: refuse with error)",
    )
    report_p.set_defaults(func=_cmd_report)

    replay_p = sub.add_parser(
        "replay",
        help="Deterministic journal reconstruction (P5.3 / PRD §4.1)",
    )
    replay_p.add_argument("--session", required=True,
                          help="Session id (path resolved via traversal-safe helper)")
    replay_p.add_argument("--from-tick", type=int, default=0,
                          help="0-based tick index to start from (default: 0)")
    replay_p.add_argument("--to-tick", type=int, default=None,
                          help="0-based tick index to stop before (default: all)")
    replay_p.add_argument(
        "--no-raise",
        action="store_true",
        help=(
            "Report divergences via diverged_at_tick instead of raising "
            "(useful for divergence-diff tooling)"
        ),
    )
    replay_p.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())


