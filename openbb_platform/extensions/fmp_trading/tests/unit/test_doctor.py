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
