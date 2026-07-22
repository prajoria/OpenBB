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


def test_snapshot_path_sanitizes_slash_in_symbol():
    """Symbols with '/' or '\\' should not create nested dirs."""
    cfg = load_config()
    p = snapshot_path(cfg, "yahoo_options_chain", "BRK/A")
    assert p.name == "BRK_A.json"


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
