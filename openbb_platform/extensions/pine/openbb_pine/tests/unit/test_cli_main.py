"""CLI tests for ``openbb-pine`` (bead 0e9.5.55 — P4).

Per D3 §10 + PRD §16.4: ``doctor`` subcommand exits 0 / 1 / 2 with [OK]/
[WARN]/[FAIL] lines, ``--version`` banner first line is the
``POWERED_BY_FULL`` literal. All diagnostic checks are mocked so the CLI
tests are deterministic and offline.
"""

from __future__ import annotations

from click.testing import CliRunner


# ----------------------------------------------------------------------
# --version banner
# ----------------------------------------------------------------------


def test_version_banner_first_line_is_powered_by():
    """§2.6 surface #4: ``Powered by PyneSys (https://pynesys.io)`` first line."""
    from openbb_pine.attribution import POWERED_BY_FULL
    from openbb_pine.cli.main import cli

    runner = CliRunner()
    out = runner.invoke(cli, ["--version"])
    assert out.exit_code == 0
    lines = out.output.splitlines()
    assert lines[0] == POWERED_BY_FULL


def test_version_banner_mentions_package_and_version():
    """Second line follows click's ``%(prog)s %(version)s`` format."""
    from openbb_pine.cli.main import cli

    runner = CliRunner()
    out = runner.invoke(cli, ["--version"])
    # Click prints "<prog> <version>" on the line after the message template.
    assert "0.1.0" in out.output or "cli" in out.output.lower()


# ----------------------------------------------------------------------
# doctor — exit codes
# ----------------------------------------------------------------------


def _stub_results(monkeypatch, results):
    """Replace the CLI's diagnostic backend with a fixed result list."""
    import openbb_pine.cli.main as cli_mod

    monkeypatch.setattr(
        cli_mod, "run_all_checks", lambda allow_byo_only=False: list(results)
    )


def test_doctor_exit_0_when_all_ok(monkeypatch):
    from openbb_pine.cli.main import cli
    from pyne_compiler.errors.diagnostics import CheckResult

    _stub_results(
        monkeypatch,
        [
            CheckResult(name="A", status="ok", message="a"),
            CheckResult(name="B", status="ok", message="b"),
        ],
    )
    out = CliRunner().invoke(cli, ["doctor"])
    assert out.exit_code == 0
    assert "[OK] A" in out.output
    assert "[OK] B" in out.output
    assert "All checks passed" in out.output


def test_doctor_exit_1_when_any_fail(monkeypatch):
    from openbb_pine.cli.main import cli
    from pyne_compiler.errors.diagnostics import CheckResult

    _stub_results(
        monkeypatch,
        [
            CheckResult(name="A", status="ok", message="ok"),
            CheckResult(
                name="FMP key present",
                status="fail",
                message="NOT found",
                fix_hint="run obb.account.save_credentials(...)",
            ),
        ],
    )
    out = CliRunner().invoke(cli, ["doctor"])
    assert out.exit_code == 1
    assert "[FAIL] FMP key present" in out.output
    assert "NOT found" in out.output
    assert "run obb.account.save_credentials" in out.output
    assert "1 check(s) failed" in out.output


def test_doctor_exit_2_on_preflight_exception(monkeypatch):
    """Any unhandled exception inside ``run_all_checks`` → exit 2 (harness died)."""
    import openbb_pine.cli.main as cli_mod
    from openbb_pine.cli.main import cli

    def boom(allow_byo_only: bool = False):
        raise RuntimeError("openbb-core not installed")

    monkeypatch.setattr(cli_mod, "run_all_checks", boom)
    out = CliRunner().invoke(cli, ["doctor"])
    assert out.exit_code == 2
    assert "PRE-FLIGHT ERROR" in out.output or "openbb-core not installed" in out.output


def test_doctor_warn_lines_use_warn_tag(monkeypatch):
    from openbb_pine.cli.main import cli
    from pyne_compiler.errors.diagnostics import CheckResult

    _stub_results(
        monkeypatch,
        [
            CheckResult(
                name="openbb-fmp-cached installed (recommended)",
                status="warn",
                message="missing",
            ),
        ],
    )
    out = CliRunner().invoke(cli, ["doctor"])
    assert out.exit_code == 0  # WARN ≠ FAIL
    assert "[WARN] openbb-fmp-cached" in out.output


def test_doctor_allow_byo_only_flag_threads_through(monkeypatch):
    """The ``--allow-byo-only`` flag must reach ``run_all_checks(allow_byo_only=True)``."""
    import openbb_pine.cli.main as cli_mod
    from openbb_pine.cli.main import cli
    from pyne_compiler.errors.diagnostics import CheckResult

    captured = {}

    def spy(allow_byo_only: bool = False):
        captured["flag"] = allow_byo_only
        return [CheckResult(name="x", status="ok", message=".")]

    monkeypatch.setattr(cli_mod, "run_all_checks", spy)

    out_default = CliRunner().invoke(cli, ["doctor"])
    assert out_default.exit_code == 0
    assert captured["flag"] is False

    out_byo = CliRunner().invoke(cli, ["doctor", "--allow-byo-only"])
    assert out_byo.exit_code == 0
    assert captured["flag"] is True


def test_doctor_fix_hint_rendered_with_arrow(monkeypatch):
    """A check with a ``fix_hint`` produces an arrow-prefixed indent line."""
    from openbb_pine.cli.main import cli
    from pyne_compiler.errors.diagnostics import CheckResult

    _stub_results(
        monkeypatch,
        [
            CheckResult(
                name="FMP API key present",
                status="fail",
                message="NOT found",
                fix_hint="Set ~/.openbb_platform/user_settings.json",
            ),
        ],
    )
    out = CliRunner().invoke(cli, ["doctor"])
    assert "→ Set ~/.openbb_platform" in out.output
