"""doctor() — fields populated, missing extras degrade gracefully, exit-code discipline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openbb_fmp_trading.core.doctor import run_doctor
from openbb_fmp_trading.models import HealthReport


def test_doctor_returns_populated_healthreport(tmp_path: Path):
    """Every boolean field must be True or False — None is a bug (missing check)."""
    report = run_doctor(
        bandwidth_state_path=tmp_path / "bw.json",
        bandwidth_budget_bytes=1_000,
        today=date(2026, 7, 6),
    )
    assert isinstance(report, HealthReport)
    for field in (
        "fmp_credentials_ok",
        "mysql_cache_ok",
        "exchange_calendars_ok",
        "techtrade_ok",
        "agent_extra_installed",
        "xlsxwriter_extra_installed",
        "validation_extra_installed",
    ):
        assert getattr(report, field) in (True, False), field
    assert 0.0 <= report.bandwidth_remaining_pct <= 100.0


def test_doctor_bandwidth_conservation_promoted_to_warning(tmp_path: Path):
    """When BandwidthMeter is in conservation mode, doctor surfaces it as a warning."""
    # Seed a bandwidth state at ~85% so BandwidthMeter loads as conservation.
    state = tmp_path / "bw.json"
    state.write_text('{"month": "2026-07", "used_bytes": 850}', encoding="utf-8")
    report = run_doctor(
        bandwidth_state_path=state,
        bandwidth_budget_bytes=1_000,
        today=date(2026, 7, 6),
    )
    assert any("conservation" in w for w in report.warnings)


def test_doctor_bandwidth_halted_promoted_to_error(tmp_path: Path):
    """When BandwidthMeter is halted, doctor surfaces it as an error (exit non-zero)."""
    state = tmp_path / "bw.json"
    state.write_text('{"month": "2026-07", "used_bytes": 980}', encoding="utf-8")
    report = run_doctor(
        bandwidth_state_path=state,
        bandwidth_budget_bytes=1_000,
        today=date(2026, 7, 6),
    )
    assert any("halted" in e.lower() for e in report.errors)


def test_doctor_router_command_returns_obbject_results():
    """The router command is invocable and returns an OBBject with populated results."""
    from openbb import obb

    result = obb.fmp_trading.doctor()
    assert result.results is not None
    # results is model_dump()'d — a dict, not a HealthReport instance.
    assert "fmp_credentials_ok" in result.results
    assert "bandwidth_remaining_pct" in result.results


def test_cli_doctor_exit_code_matches_errors(tmp_path: Path, capsys, monkeypatch):
    """openbb-daytrade doctor exits 1 iff report.errors is non-empty."""
    from openbb_fmp_trading.cli.main import _cmd_doctor

    # Force an error condition via a halted bandwidth state.
    state = tmp_path / "bw.json"
    state.write_text('{"month": "2026-07", "used_bytes": 980}', encoding="utf-8")

    # Patch _cmd_doctor's state_path resolution by monkey-patching Path.home().
    monkeypatch.setattr(
        "openbb_fmp_trading.cli.main.Path.home", lambda: tmp_path.parent
    )
    # Ensure the fake home resolves to our fixture location:
    fake_state_dir = tmp_path.parent / ".openbb_platform" / "fmp_trading"
    fake_state_dir.mkdir(parents=True, exist_ok=True)
    (fake_state_dir / "bandwidth.json").write_text(
        '{"month": "2026-07", "used_bytes": 999999999999}', encoding="utf-8"
    )

    import argparse

    exit_code = _cmd_doctor(argparse.Namespace())
    captured = capsys.readouterr()
    assert "openbb-daytrade doctor" in captured.out
    # With a halted-bandwidth state, errors should be present -> exit 1.
    assert exit_code == 1


def test_check_mysql_cache_uses_surviving_symbol():
    """Regression #861: _check_mysql_cache must NOT import a non-existent
    ``ping_cache`` from a phantom ``openbb_fmp_cached.utils.helpers``.

    The prior implementation had `from openbb_fmp_cached.utils.helpers
    import ping_cache` — neither module nor symbol exists — swallowed by
    a bare `except Exception: return False`. Doctor always reported
    ``mysql_cache_ok: false`` regardless of real DB state.

    This test asserts on the SOURCE (AST-walked) rather than behaviour,
    because behavioural verification requires a live MySQL container.
    AST inspection catches the specific class of "import a symbol that
    doesn't exist" bug without needing infra.
    """
    import ast
    import inspect

    from openbb_fmp_trading.core import doctor as doctor_mod

    tree = ast.parse(inspect.getsource(doctor_mod._check_mysql_cache))

    imported_symbols: list[tuple[str, str]] = []  # (module, name)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_symbols.append((node.module, alias.name))

    # The bug: `openbb_fmp_cached.utils.helpers.ping_cache` is imported.
    # The fix: import surviving symbols from `openbb_fmp_cached.utils.database`.
    assert ("openbb_fmp_cached.utils.helpers", "ping_cache") not in imported_symbols, (
        "Regression: _check_mysql_cache still imports the non-existent "
        "`ping_cache` from `openbb_fmp_cached.utils.helpers`. See #861."
    )

    # Also verify the current symbols DO resolve at import time — this
    # catches "someone renamed get_connection_pool" future-drift.
    for module, name in imported_symbols:
        if module.startswith("openbb_fmp_cached"):
            imported_mod = __import__(module, fromlist=[name])
            assert hasattr(imported_mod, name), (
                f"_check_mysql_cache imports {module}.{name} which does not "
                f"exist. Silent-swallow bug pattern from #861 will re-trigger."
            )

