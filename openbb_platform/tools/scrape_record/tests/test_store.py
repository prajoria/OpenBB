"""Tests for scrape_record.store — user-local SQLite snapshot store.

Covers: round-trip, WAL/FK pragmas, upsert idempotence, load_snapshot
DB-preferred + JSON fallback, and the `scrape-record migrate` CLI
against a synthetic fixture tree.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from scrape_record.record import SnapshotEnvelope, load_snapshot
from scrape_record.store import SnapshotStore


def _make_env(name: str = "yahoo_equity_quote", symbol: str = "TEST") -> SnapshotEnvelope:
    return SnapshotEnvelope(
        name=name,
        symbol=symbol,
        captured_at="2026-07-25T00:00:00+00:00",
        source_url=f"synthetic://test/{name}/{symbol}",
        raw={"symbol": symbol, "price": 100.0, "nested": {"k": "v"}},
        extracted={"symbol": symbol, "price": 100.0},
        extractor_version="1",
    )


def test_store_roundtrip(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.db"
    with SnapshotStore(db) as store:
        assert store.get("yahoo_equity_quote", "TEST") is None
        env = _make_env()
        store.upsert(env)
        got = store.get("yahoo_equity_quote", "TEST")
        assert got is not None
        assert got.name == env.name
        assert got.symbol == env.symbol
        assert got.raw == env.raw
        assert got.extracted == env.extracted
        assert got.extractor_version == "1"
        listed = store.list_all()
        assert len(listed) == 1
        assert "raw" not in listed[0] and "raw_json" not in listed[0]
        assert listed[0]["symbol"] == "TEST"
        assert store.count() == 1
        # delete
        assert store.delete("yahoo_equity_quote", "TEST") == 1
        assert store.get("yahoo_equity_quote", "TEST") is None
        assert store.delete("yahoo_equity_quote", "TEST") == 0


def test_store_schema_wal_and_fk(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.db"
    with SnapshotStore(db):
        pass
    # Re-open with a raw sqlite3 handle to inspect pragmas that persist
    # (journal_mode is a per-database persistent setting).
    conn = sqlite3.connect(str(db))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        # foreign_keys is per-connection; the store sets it. We assert the
        # store applies it on a new connection.
    finally:
        conn.close()
    with SnapshotStore(db) as store:
        fk = store._conn.execute("PRAGMA foreign_keys").fetchone()[0]  # noqa: SLF001
        assert fk == 1


def test_store_upsert_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "snapshots.db"
    with SnapshotStore(db) as store:
        env = _make_env()
        store.upsert(env)
        store.upsert(env)  # no exception, no duplicate row
        assert store.count() == 1
        env2 = _make_env()
        env2.raw = {"symbol": "TEST", "price": 999.0}
        store.upsert(env2)
        got = store.get("yahoo_equity_quote", "TEST")
        assert got is not None
        assert got.raw["price"] == 999.0
        assert store.count() == 1


def test_load_snapshot_prefers_db_over_json(tmp_path: Path, monkeypatch) -> None:
    """When both DB and legacy JSON exist for a key, DB wins."""
    # Build a config pointing at a temp legacy dir + temp DB.
    from scrape_record.config import Config

    pkg_root = tmp_path / "pkg"
    snap_dir = pkg_root / "snapshots" / "yahoo_equity_quote"
    snap_dir.mkdir(parents=True)
    db_path = tmp_path / "snapshots.db"
    cfg = Config(
        repo_root=tmp_path,
        package_root=pkg_root,
        snapshots_dir=pkg_root / "snapshots",
        recordings_dir=pkg_root / "recordings",
        profile_dir=tmp_path / "prof",
        db_path=db_path,
        headless=False,
    )
    # Legacy JSON with distinguishable payload
    legacy = _make_env()
    legacy.raw = {"which": "legacy_json"}
    (snap_dir / "TEST.json").write_text(
        json.dumps(
            {
                "name": legacy.name,
                "symbol": legacy.symbol,
                "captured_at": legacy.captured_at,
                "source_url": legacy.source_url,
                "raw": legacy.raw,
                "extracted": legacy.extracted,
                "extractor_version": legacy.extractor_version,
            }
        ),
        encoding="utf-8",
    )
    # DB entry with different payload
    db_env = _make_env()
    db_env.raw = {"which": "db"}
    with SnapshotStore(db_path) as store:
        store.upsert(db_env)

    got = load_snapshot(cfg, "yahoo_equity_quote", "TEST")
    assert got.raw == {"which": "db"}


def test_load_snapshot_falls_back_to_json_when_db_absent(tmp_path: Path) -> None:
    from scrape_record.config import Config

    pkg_root = tmp_path / "pkg"
    snap_dir = pkg_root / "snapshots" / "yahoo_equity_quote"
    snap_dir.mkdir(parents=True)
    cfg = Config(
        repo_root=tmp_path,
        package_root=pkg_root,
        snapshots_dir=pkg_root / "snapshots",
        recordings_dir=pkg_root / "recordings",
        profile_dir=tmp_path / "prof",
        db_path=tmp_path / "does_not_exist.db",
        headless=False,
    )
    env = _make_env()
    env.raw = {"which": "legacy_json"}
    (snap_dir / "TEST.json").write_text(
        json.dumps(
            {
                "name": env.name,
                "symbol": env.symbol,
                "captured_at": env.captured_at,
                "source_url": env.source_url,
                "raw": env.raw,
                "extracted": env.extracted,
                "extractor_version": env.extractor_version,
            }
        ),
        encoding="utf-8",
    )
    got = load_snapshot(cfg, "yahoo_equity_quote", "TEST")
    assert got.raw == {"which": "legacy_json"}


def test_load_snapshot_raises_with_record_hint(tmp_path: Path) -> None:
    from scrape_record.config import Config

    pkg_root = tmp_path / "pkg"
    (pkg_root / "snapshots").mkdir(parents=True)
    cfg = Config(
        repo_root=tmp_path,
        package_root=pkg_root,
        snapshots_dir=pkg_root / "snapshots",
        recordings_dir=pkg_root / "recordings",
        profile_dir=tmp_path / "prof",
        db_path=tmp_path / "missing.db",
        headless=False,
    )
    with pytest.raises(FileNotFoundError, match="scrape-record record"):
        load_snapshot(cfg, "yahoo_equity_quote", "NOPE")


def test_migrate_walks_fixture_dir_and_reports(tmp_path: Path, capsys) -> None:
    """The `scrape-record migrate` CLI upserts every legacy JSON exactly once."""
    from scrape_record.cli import main
    from scrape_record.config import load_config

    # Build a fake package tree with 2 snapshots, monkey-patched via env vars.
    pkg_root = tmp_path / "scrape_record_pkg"
    snap_dir = pkg_root / "snapshots" / "yahoo_equity_quote"
    snap_dir.mkdir(parents=True)
    (pkg_root / "recordings").mkdir()
    for sym in ("AAA", "BBB"):
        env = _make_env(symbol=sym)
        (snap_dir / f"{sym}.json").write_text(
            json.dumps(
                {
                    "name": env.name,
                    "symbol": env.symbol,
                    "captured_at": env.captured_at,
                    "source_url": env.source_url,
                    "raw": env.raw,
                    "extracted": env.extracted,
                    "extractor_version": env.extractor_version,
                }
            ),
            encoding="utf-8",
        )
    # A malformed file to exercise the needs-review path.
    (snap_dir / "OOPS.json").write_text("{ not json", encoding="utf-8")

    db_path = tmp_path / "snapshots.db"

    # Patch load_config to return a Config anchored on our fake pkg_root.
    import scrape_record.cli as cli_mod
    from scrape_record.config import Config

    fake_cfg = Config(
        repo_root=tmp_path,
        package_root=pkg_root,
        snapshots_dir=pkg_root / "snapshots",
        recordings_dir=pkg_root / "recordings",
        profile_dir=tmp_path / "prof",
        db_path=db_path,
        headless=False,
    )
    orig = cli_mod.load_config
    cli_mod.load_config = lambda: fake_cfg  # type: ignore[assignment]
    try:
        rc = main(["migrate", "--dry-run"])
    finally:
        cli_mod.load_config = orig  # type: ignore[assignment]
    # dry-run: no DB written, but reports 2 ok + 1 bad -> nonzero exit
    assert not db_path.exists()
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "2 / 3" in out
    assert rc == 1  # 1 malformed file

    # Real run — DB should end up with exactly 2 rows.
    cli_mod.load_config = lambda: fake_cfg  # type: ignore[assignment]
    try:
        main(["migrate"])
    finally:
        cli_mod.load_config = orig  # type: ignore[assignment]
    with SnapshotStore(db_path) as store:
        assert store.count() == 2
        # Idempotent second run
    cli_mod.load_config = lambda: fake_cfg  # type: ignore[assignment]
    try:
        main(["migrate"])
    finally:
        cli_mod.load_config = orig  # type: ignore[assignment]
    with SnapshotStore(db_path) as store:
        assert store.count() == 2
