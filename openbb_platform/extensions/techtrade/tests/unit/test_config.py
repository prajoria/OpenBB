"""Tests for the centralized Portfolio Intelligence environment contract."""

# ruff: noqa: D103

from pathlib import Path

import pytest
from openbb_techtrade.config import (
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
        (snapshot_db_path, "PI_SNAPSHOT_DB"),
        (order_sink_paper_dir, "PI_ORDER_SINK_PAPER_DIR"),
    ],
)
def test_path_getter_treats_empty_environment_as_unset(monkeypatch, getter, env_name):
    monkeypatch.setenv(env_name, "")

    assert getter("relative/custom") == Path("relative/custom")
