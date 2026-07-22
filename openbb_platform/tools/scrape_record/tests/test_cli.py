"""Tests for scrape_record.cli — build_parser + dry-run of subcommands.

The `record` and `replay` subcommands hit Playwright + live Yahoo, so
they're not exercised end-to-end here. We test the parser wiring, the
`config`, `list`, and `verify` subcommands which are fully offline.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from scrape_record.cli import build_parser, main


def test_parser_has_all_subcommands():
    """Every documented subcommand parses without error."""
    parser = build_parser()
    for cmd in ("config", "list", "record", "replay", "verify"):
        # A --help attempt would sys.exit(0); we just check the subparser exists
        # by parsing an args tuple that satisfies its required args.
        if cmd in ("record", "replay", "verify"):
            args = parser.parse_args([cmd, "yahoo_options_chain", "--symbol", "AAPL"])
        else:
            args = parser.parse_args([cmd])
        assert args.cmd == cmd


def test_cli_config_prints_summary():
    """`scrape-record config` prints all path fields."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["config"])
    out = buf.getvalue()
    assert rc == 0
    for token in ("repo_root", "snapshots_dir", "profile_dir", "headless"):
        assert token in out


def test_cli_list_lists_at_least_the_aapl_snapshot():
    """`scrape-record list` includes the AAPL fixture we commit."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["list"])
    out = buf.getvalue()
    assert rc == 0
    assert "yahoo_options_chain" in out
    assert "AAPL" in out


def test_cli_verify_returns_ok_for_aapl():
    """`scrape-record verify yahoo_options_chain --symbol AAPL` exits 0 + prints ok=true."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["verify", "yahoo_options_chain", "--symbol", "AAPL"])
    assert rc == 0
    assert '"ok": true' in buf.getvalue()


def test_cli_verify_missing_snapshot_exits_nonzero(capsys):
    """`scrape-record verify` for a missing symbol exits 2 (error path)."""
    rc = main(["verify", "yahoo_options_chain", "--symbol", "NOT_A_REAL_SYMBOL"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error" in err.lower()
