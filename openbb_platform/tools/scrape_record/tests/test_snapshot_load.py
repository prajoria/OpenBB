"""Tests for scrape_record.record — snapshot envelope load path.

Post-#1425, the primary snapshot store is a user-local SQLite DB. These
tests seed a temp DB from a synthetic fixture so they never depend on
the operator's ``~/.scrape_record/snapshots.db``.
"""

from __future__ import annotations

import pytest
from scrape_record.config import Config
from scrape_record.record import SnapshotEnvelope, load_snapshot
from scrape_record.store import SnapshotStore

from ._fixtures import fixture_path, load_fixture


def _cfg_for(tmp_path, seed_db: bool) -> Config:
    pkg_root = tmp_path / "pkg"
    (pkg_root / "snapshots").mkdir(parents=True)
    (pkg_root / "recordings").mkdir()
    cfg = Config(
        repo_root=tmp_path,
        package_root=pkg_root,
        snapshots_dir=pkg_root / "snapshots",
        recordings_dir=pkg_root / "recordings",
        profile_dir=tmp_path / "prof",
        db_path=tmp_path / "snapshots.db",
        headless=False,
    )
    if seed_db:
        data = load_fixture("yahoo_options_chain", "AAPL")
        env = SnapshotEnvelope(**data)
        with SnapshotStore(cfg.db_path) as store:
            store.upsert(env)
    return cfg


def test_load_synthetic_aapl_snapshot_via_db(tmp_path):
    """The synthetic AAPL fixture round-trips through the DB into an envelope."""
    cfg = _cfg_for(tmp_path, seed_db=True)
    env = load_snapshot(cfg, "yahoo_options_chain", "AAPL")
    assert isinstance(env, SnapshotEnvelope)
    assert env.name == "yahoo_options_chain"
    assert env.symbol == "AAPL"
    assert env.source_url and env.source_url.startswith("https://finance.yahoo.com")
    assert isinstance(env.raw, dict)
    assert isinstance(env.extracted, dict)
    assert env.extractor_version == "1"


def test_load_snapshot_raises_for_missing_symbol(tmp_path):
    """Missing (name, symbol) raises FileNotFoundError with the record hint."""
    cfg = _cfg_for(tmp_path, seed_db=False)
    with pytest.raises(FileNotFoundError, match="record"):
        load_snapshot(cfg, "yahoo_options_chain", "NONEXISTENT_XYZ_SYMBOL_")


def test_synthetic_fixture_envelope_shape_stable_on_disk():
    """The AAPL fixture's on-disk keys still match the envelope dataclass fields."""
    p = fixture_path("yahoo_options_chain", "AAPL")
    data = load_fixture("yahoo_options_chain", "AAPL")
    expected_keys = {
        "name",
        "symbol",
        "captured_at",
        "source_url",
        "raw",
        "extracted",
        "extractor_version",
    }
    assert set(data.keys()) == expected_keys, f"drift in {p}"
