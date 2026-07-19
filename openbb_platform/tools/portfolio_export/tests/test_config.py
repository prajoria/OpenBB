"""Smoke test: config loads and rejects a repo-internal download dir."""

from __future__ import annotations

from pathlib import Path

import pytest
from portfolio_export.config import ConfigError, load_config

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_defaults_load_and_are_outside_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORTFOLIO_EXPORT_DIR", raising=False)
    monkeypatch.delenv("PORTFOLIO_EXPORT_PROFILE_DIR", raising=False)
    monkeypatch.delenv("PORTFOLIO_EXPORT_RECORDINGS_DIR", raising=False)
    cfg = load_config(PACKAGE_ROOT)
    assert cfg.repo_root.exists()
    # all three defaults resolve outside the repo
    assert not str(cfg.download_dir).startswith(str(cfg.repo_root))
    assert not str(cfg.profile_dir).startswith(str(cfg.repo_root))
    assert not str(cfg.user_recordings_dir).startswith(str(cfg.repo_root))
    # bundled examples still live in-repo (they're VCS-tracked template docs)
    assert str(cfg.bundled_recordings_dir).startswith(str(cfg.repo_root))


def test_rejects_download_dir_inside_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inside = PACKAGE_ROOT / "should_not_be_here"
    monkeypatch.setenv("PORTFOLIO_EXPORT_DIR", str(inside))
    monkeypatch.setenv("PORTFOLIO_EXPORT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("PORTFOLIO_EXPORT_RECORDINGS_DIR", str(tmp_path / "rec"))
    with pytest.raises(ConfigError, match="inside the repo"):
        load_config(PACKAGE_ROOT)


def test_rejects_profile_dir_inside_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inside = PACKAGE_ROOT / "should_not_be_here_profile"
    monkeypatch.setenv("PORTFOLIO_EXPORT_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("PORTFOLIO_EXPORT_PROFILE_DIR", str(inside))
    monkeypatch.setenv("PORTFOLIO_EXPORT_RECORDINGS_DIR", str(tmp_path / "rec"))
    with pytest.raises(ConfigError, match="inside the repo"):
        load_config(PACKAGE_ROOT)


def test_rejects_recordings_dir_inside_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    inside = PACKAGE_ROOT / "should_not_be_here_recordings"
    monkeypatch.setenv("PORTFOLIO_EXPORT_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("PORTFOLIO_EXPORT_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("PORTFOLIO_EXPORT_RECORDINGS_DIR", str(inside))
    with pytest.raises(ConfigError, match="inside the repo"):
        load_config(PACKAGE_ROOT)
