"""Tests for the guarded Portfolio Intelligence editable installer."""

# ruff: noqa: D103

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from scripts import pi_install


class _Distribution:
    def __init__(self, direct_url: str | None) -> None:
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        return self._direct_url


def test_install_runs_portfolio_before_techtrade(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    verified: list[tuple[str, ...]] = []

    def capture(command, *, check):
        assert check is True
        calls.append(command)

    monkeypatch.setattr(subprocess, "run", capture)
    monkeypatch.setattr(
        pi_install,
        "require_editable",
        lambda names=pi_install.DISTRIBUTIONS: verified.append(names),
    )

    pi_install.install(tmp_path)

    extensions = tmp_path / "openbb_platform" / "extensions"
    assert calls == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            str(extensions / "portfolio_intel"),
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            str(extensions / "techtrade"),
        ],
    ]
    assert verified == [pi_install.DISTRIBUTIONS]


def test_install_dry_run_has_no_side_effects(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("dry-run must not invoke pip"),
    )
    monkeypatch.setattr(
        pi_install,
        "require_editable",
        lambda *args, **kwargs: pytest.fail("dry-run must not inspect metadata"),
    )

    pi_install.install(tmp_path, dry_run=True)


@pytest.mark.parametrize(
    ("direct_url", "expected"),
    [
        (json.dumps({"dir_info": {"editable": True}}), True),
        (json.dumps({"dir_info": {}}), False),
        (json.dumps({"dir_info": {"editable": False}}), False),
        (None, False),
        ("not-json", False),
    ],
)
def test_is_editable_reads_pep_610_metadata(monkeypatch, direct_url, expected):
    monkeypatch.setattr(
        importlib.metadata,
        "distribution",
        lambda _name: _Distribution(direct_url),
    )

    assert pi_install.is_editable("example") is expected


def test_is_editable_returns_false_for_missing_distribution(monkeypatch):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "distribution", missing)

    assert pi_install.is_editable("missing") is False


def test_require_editable_names_every_failed_distribution(monkeypatch):
    monkeypatch.setattr(
        pi_install,
        "is_editable",
        lambda name: name == "openbb-portfolio-intel",
    )

    with pytest.raises(
        RuntimeError,
        match=r"openbb-techtrade.*not installed as editable",
    ):
        pi_install.require_editable()


def test_repository_root_is_derived_from_script_location():
    expected = Path(pi_install.__file__).resolve().parents[1]

    assert expected == pi_install.REPO_ROOT


@pytest.mark.skipif(
    os.environ.get("PI_RUN_EDITABLE_INSTALL_TEST") != "1",
    reason="set PI_RUN_EDITABLE_INSTALL_TEST=1 to exercise pip in an isolated venv",
)
def test_installer_restores_editability_after_raw_pip_clobber():
    repo_root = pi_install.REPO_ROOT
    venv_dir = repo_root / ".dev-cycle" / "pi-install-integration-venv"
    python = venv_dir / "Scripts" / "python.exe"
    extensions = repo_root / "openbb_platform" / "extensions"

    probe = (
        "import importlib.metadata,json,sys;"
        "d=importlib.metadata.distribution(sys.argv[1]);"
        "m=json.loads(d.read_text('direct_url.json'));"
        "print(str(m.get('dir_info',{}).get('editable') is True).lower())"
    )

    def pip_install(path: Path) -> None:
        subprocess.run(  # noqa: S603
            [str(python), "-m", "pip", "install", "-e", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )

    def editable(name: str) -> bool:
        completed = subprocess.run(  # noqa: S603
            [str(python), "-c", probe, name],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() == "true"

    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        pip_install(extensions / "backtest")
        pip_install(extensions / "techtrade")
        assert editable("openbb-techtrade")

        pip_install(extensions / "portfolio_intel")
        assert not editable("openbb-techtrade")

        subprocess.run(  # noqa: S603
            [str(python), str(repo_root / "scripts" / "pi_install.py")],
            check=True,
            capture_output=True,
            text=True,
        )
        assert editable("openbb-portfolio-intel")
        assert editable("openbb-techtrade")
    finally:
        shutil.rmtree(venv_dir, ignore_errors=True)
