"""Tests for the centralized Portfolio Intelligence environment contract."""

# ruff: noqa: D103

import os
from pathlib import Path

import pytest
from openbb_techtrade import config as config_module
from openbb_techtrade.config import (
    ConfigError,
    _validate_outside_repo,
    order_sink,
    order_sink_paper_dir,
    paper_db_path,
    paper_engine,
    snapshot_db_path,
    snapshot_engine,
)


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_engine, "PI_PAPER_ENGINE"),
        (snapshot_engine, "PI_SNAPSHOT_ENGINE"),
    ],
)
def test_engine_getter_defaults_to_mysql(monkeypatch, getter, env_name):
    monkeypatch.delenv(env_name, raising=False)

    assert getter() == "mysql"


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_engine, "PI_PAPER_ENGINE"),
        (snapshot_engine, "PI_SNAPSHOT_ENGINE"),
    ],
)
def test_engine_getter_normalizes_environment_override(monkeypatch, getter, env_name):
    monkeypatch.setenv(env_name, " SQLite ")

    assert getter() == "sqlite"


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_engine, "PI_PAPER_ENGINE"),
        (snapshot_engine, "PI_SNAPSHOT_ENGINE"),
    ],
)
def test_engine_getter_accepts_caller_default(monkeypatch, getter, env_name):
    monkeypatch.delenv(env_name, raising=False)

    assert getter("sqlite") == "sqlite"


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_engine, "PI_PAPER_ENGINE"),
        (snapshot_engine, "PI_SNAPSHOT_ENGINE"),
    ],
)
def test_engine_getter_rejects_unsupported_value(monkeypatch, getter, env_name):
    monkeypatch.setenv(env_name, "oracle")

    with pytest.raises(ValueError, match=rf"^{env_name} must be one of .*oracle"):
        getter()


def test_order_sink_defaults_to_paper(monkeypatch):
    monkeypatch.delenv("PI_ORDER_SINK", raising=False)

    assert order_sink() == "paper"


def test_order_sink_normalizes_supported_override(monkeypatch):
    monkeypatch.setenv("PI_ORDER_SINK", " Fidelity_CSV ")

    assert order_sink() == "fidelity_csv"


def test_order_sink_accepts_caller_default(monkeypatch):
    monkeypatch.delenv("PI_ORDER_SINK", raising=False)

    assert order_sink("fidelity_csv") == "fidelity_csv"


def test_order_sink_rejects_unsupported_value(monkeypatch):
    monkeypatch.setenv("PI_ORDER_SINK", "alpaca")

    with pytest.raises(ValueError, match=r"^PI_ORDER_SINK must be one of .*alpaca"):
        order_sink()


@pytest.mark.parametrize(
    ("getter", "env_name", "filename"),
    [
        (paper_db_path, "PI_PAPER_DB", "paper.db"),
        (snapshot_db_path, "PI_SNAPSHOT_DB", "snapshot.db"),
        (
            order_sink_paper_dir,
            "PI_ORDER_SINK_PAPER_DIR",
            "order_batches",
        ),
    ],
)
def test_path_getter_uses_per_user_default(monkeypatch, getter, env_name, filename):
    monkeypatch.delenv(env_name, raising=False)

    assert getter() == Path.home() / ".portfolio_intel" / filename


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_db_path, "PI_PAPER_DB"),
        (snapshot_db_path, "PI_SNAPSHOT_DB"),
        (order_sink_paper_dir, "PI_ORDER_SINK_PAPER_DIR"),
    ],
)
def test_path_getter_preserves_environment_override(monkeypatch, getter, env_name):
    monkeypatch.setenv(env_name, "~/custom/relative.db")

    assert getter() == Path("~/custom/relative.db")


@pytest.mark.parametrize(
    ("getter", "env_name"),
    [
        (paper_db_path, "PI_PAPER_DB"),
        (order_sink_paper_dir, "PI_ORDER_SINK_PAPER_DIR"),
    ],
)
def test_path_getter_treats_empty_environment_as_unset(monkeypatch, getter, env_name):
    monkeypatch.setenv(env_name, "")

    assert getter("relative/custom") == Path("relative/custom")


def test_snapshot_path_rejects_relative_default_inside_repo(monkeypatch):
    monkeypatch.setenv("PI_SNAPSHOT_DB", "")

    with pytest.raises(ConfigError, match="outside"):
        snapshot_db_path("relative/custom")


def test_snapshot_guard_rejects_repository_path(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(ConfigError, match="outside"):
        _validate_outside_repo(
            "PI_SNAPSHOT_DB", repo_root / "data" / "snapshot.db", repo_root
        )


def test_snapshot_guard_accepts_sibling_path(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "user-data" / "snapshot.db"

    assert (
        _validate_outside_repo("PI_SNAPSHOT_DB", outside, repo_root)
        == outside.resolve()
    )


def test_snapshot_guard_rejects_hard_link_to_repository_file(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    inside = repo_root / "snapshot.db"
    inside.touch()
    outside = tmp_path / "user-data" / "snapshot.db"
    outside.parent.mkdir()
    try:
        os.link(inside, outside)
    except OSError as exc:
        pytest.skip(f"hard links unavailable: {type(exc).__name__}")

    with pytest.raises(ConfigError, match="hard link"):
        _validate_outside_repo("PI_SNAPSHOT_DB", outside, repo_root)


def test_installed_package_without_checkout_marker_does_not_invent_repo_root(
    tmp_path, monkeypatch
):
    installed = (
        tmp_path / "Python" / "Lib" / "site-packages" / "openbb_techtrade" / "config.py"
    )
    monkeypatch.setattr(config_module, "__file__", str(installed))
    destination = tmp_path / "user-data" / "snapshot.db"

    assert config_module._repository_root() is None
    assert (
        _validate_outside_repo("PI_SNAPSHOT_DB", destination) == destination.resolve()
    )
