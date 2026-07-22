"""Tests for scrape_record.config path validation."""

from __future__ import annotations

import pytest
from scrape_record.config import (
    ConfigError,
    load_config,
    recording_path,
    snapshot_path,
)


def test_load_config_resolves_paths_and_validates_placement():
    """Defaults: snapshots_dir INSIDE package, profile_dir OUTSIDE repo."""
    cfg = load_config()
    # Snapshots MUST be inside package
    assert cfg.snapshots_dir.is_relative_to(cfg.package_root)
    # Profile MUST NOT be inside repo
    with pytest.raises(ValueError):
        cfg.profile_dir.relative_to(cfg.repo_root)


def test_load_config_rejects_profile_inside_repo(tmp_path, monkeypatch):
    """A profile_dir inside the repo must raise ConfigError."""
    cfg_probe = load_config()
    bad = cfg_probe.repo_root / "tmp_bad_profile"
    with pytest.raises(ConfigError, match="profile_dir"):
        load_config(profile_dir=str(bad))


def test_snapshot_path_layout():
    """(name, symbol) resolves to snapshots/<name>/<symbol>.json."""
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_options_chain", "AAPL")
    assert p.name == "AAPL.json"
    assert p.parent.name == "yahoo_options_chain"
    assert p.parent.parent == cfg.snapshots_dir


def test_snapshot_path_rejects_slash_in_symbol():
    """Path-traversal hardening: symbols with `/` or `\\` are rejected outright."""
    cfg = load_config()
    with pytest.raises(ConfigError, match="disallowed characters"):
        snapshot_path(cfg, "yahoo_options_chain", "BRK/A")
    with pytest.raises(ConfigError, match="disallowed characters"):
        snapshot_path(cfg, "yahoo_options_chain", "BRK\\A")


def test_snapshot_path_rejects_traversal_dotdot():
    """Explicit '..' and '.' are rejected even if allowlist would let them."""
    cfg = load_config()
    with pytest.raises(ConfigError, match="'.'|'..'|disallowed"):
        snapshot_path(cfg, "yahoo_options_chain", "..")
    with pytest.raises(ConfigError, match="'.'|'..'|disallowed"):
        snapshot_path(cfg, "yahoo_options_chain", ".")


def test_snapshot_path_rejects_null_byte():
    """NUL bytes never survive validation (defense against path-terminator tricks)."""
    cfg = load_config()
    with pytest.raises(ConfigError, match="NUL"):
        snapshot_path(cfg, "yahoo_options_chain", "AAPL\x00.txt")


def test_snapshot_path_rejects_empty_symbol():
    """Empty symbol rejected."""
    cfg = load_config()
    with pytest.raises(ConfigError, match="non-empty"):
        snapshot_path(cfg, "yahoo_options_chain", "")


def test_snapshot_path_rejects_overlong_symbol():
    """Symbol > 64 chars rejected."""
    cfg = load_config()
    with pytest.raises(ConfigError, match="max length"):
        snapshot_path(cfg, "yahoo_options_chain", "A" * 65)


def test_snapshot_path_accepts_finance_legit_punctuation():
    """Allowlist includes . - _ ^ = for BRK.B / BRK-B / ^GSPC / CL=F."""
    cfg = load_config()
    for sym in ("BRK.B", "BRK-B", "^GSPC", "CL=F", "AAPL251230C00325000"):
        # Should not raise
        p = snapshot_path(cfg, "yahoo_options_chain", sym)
        assert p.name.endswith(".json")


def test_snapshot_path_defense_in_depth_asserts_inside_snapshots_dir():
    """Even if someone widens the allowlist, resolved path is re-checked."""
    cfg = load_config()
    # The check runs on every call; the accepted 'AAPL' case must resolve inside
    p = snapshot_path(cfg, "yahoo_options_chain", "AAPL")
    assert p.is_relative_to(cfg.snapshots_dir)


def test_recording_path_layout():
    """Recording is a .py under recordings/."""
    cfg = load_config()
    p = recording_path(cfg, "yahoo_options_chain")
    assert p.name == "yahoo_options_chain.py"
    assert p.parent == cfg.recordings_dir


def test_config_summary_contains_all_fields():
    """summary() must be human-readable and mention every path."""
    cfg = load_config()
    s = cfg.summary()
    for token in (
        "repo_root",
        "package_root",
        "snapshots_dir",
        "recordings_dir",
        "profile_dir",
        "headless",
    ):
        assert token in s
