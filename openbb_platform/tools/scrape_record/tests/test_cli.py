"""Tests for scrape_record.cli — build_parser + dry-run of subcommands.

Post-#1425 the CLI reads/writes a user-local SQLite DB. These tests
route ``SCRAPE_RECORD_DB_PATH`` at a temp file so they never touch
``~/.scrape_record/snapshots.db``.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

from scrape_record.cli import build_parser, main
from scrape_record.record import SnapshotEnvelope
from scrape_record.store import SnapshotStore

from ._fixtures import load_fixture


def _seed_db(db_path, name="yahoo_options_chain", symbol="AAPL"):
    env = SnapshotEnvelope(**load_fixture(name, symbol))
    with SnapshotStore(db_path) as store:
        store.upsert(env)


def test_parser_has_all_subcommands():
    """Every documented subcommand parses without error."""
    parser = build_parser()
    for cmd in ("config", "list", "record", "replay", "verify", "migrate"):
        if cmd in ("record", "replay", "verify"):
            args = parser.parse_args([cmd, "yahoo_options_chain", "--symbol", "AAPL"])
        elif cmd == "migrate":
            args = parser.parse_args([cmd, "--dry-run"])
        else:
            args = parser.parse_args([cmd])
        assert args.cmd == cmd


def test_cli_config_prints_summary(tmp_path, monkeypatch):
    """`scrape-record config` prints all path fields including db_path."""
    monkeypatch.setenv("SCRAPE_RECORD_DB_PATH", str(tmp_path / "snapshots.db"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["config"])
    out = buf.getvalue()
    assert rc == 0
    for token in (
        "repo_root",
        "snapshots_dir",
        "profile_dir",
        "db_path",
        "headless",
    ):
        assert token in out


def test_cli_verify_returns_ok_for_seeded_aapl(tmp_path, monkeypatch):
    """`scrape-record verify` exits 0 when the DB has the entry."""
    db = tmp_path / "snapshots.db"
    monkeypatch.setenv("SCRAPE_RECORD_DB_PATH", str(db))
    _seed_db(db)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["verify", "yahoo_options_chain", "--symbol", "AAPL"])
    assert rc == 0
    assert '"ok": true' in buf.getvalue()


def test_cli_verify_missing_snapshot_exits_nonzero(tmp_path, monkeypatch, capsys):
    """`scrape-record verify` for a missing symbol exits 2 (error path)."""
    monkeypatch.setenv("SCRAPE_RECORD_DB_PATH", str(tmp_path / "empty.db"))
    rc = main(["verify", "yahoo_options_chain", "--symbol", "NOT_A_REAL_SYMBOL"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "error" in err.lower()
