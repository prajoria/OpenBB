"""Unit tests for local-ci CLI/config/report layers.

Runs without Docker — everything that would `subprocess.run(['docker', ...])`
is exercised via --dry-run or by pointing at fixture YAML.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import jsonschema
import pytest

# Make ci/ importable without installing.
CI_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(CI_DIR))

from local_ci import cli, config, exit_codes  # noqa: E402
from local_ci.report import JSON_DELIMITER, REPORT_SCHEMA_ID  # noqa: E402

FIXTURE_YAML = CI_DIR / "_fixture" / "local-ci.yml"
REPORT_SCHEMA = json.loads(
    (CI_DIR / "local_ci" / "schema" / "report.schema.json").read_text()
)


# ---------------------------------------------------------------------------
# config.py — YAML loading + schema validation
# ---------------------------------------------------------------------------


def test_load_fixture_yaml_parses_cleanly():
    cfg = config.load_project(FIXTURE_YAML)
    assert cfg.project == "fixture"
    assert set(cfg.tiers) == {"lint", "unit", "mysql"}
    assert cfg.default_tiers == ("lint", "unit")
    assert cfg.sidecars["mysql"].init["kind"] == "mysql_restore"
    assert cfg.tiers["mysql"].requires_services == ("mysql",)


def test_schema_rejects_unknown_top_level_key(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 1\nproject: bad\ncompose:\n  file: c.yml\n  runner_service: r\n"
        "tiers:\n  lint:\n    command: 'echo ok'\n"
        "surprise_field: yes\n"  # additionalProperties:false → reject
    )
    (tmp_path / "c.yml").write_text("services: {}\n")
    with pytest.raises(config.ConfigError) as ei:
        config.load_project(bad)
    assert "surprise_field" in str(ei.value) or "additional" in str(ei.value).lower()


def test_schema_rejects_wrong_version(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 2\nproject: x\ncompose:\n  file: c.yml\n  runner_service: r\n"
        "tiers:\n  lint:\n    command: 'echo'\n"
    )
    (tmp_path / "c.yml").write_text("services: {}\n")
    with pytest.raises(config.ConfigError):
        config.load_project(bad)


def test_yaml_syntax_error_raises_configerror(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text("version: 1\n  bad-indent: true\nproject: x\n")
    with pytest.raises(config.ConfigError):
        config.load_project(bad)


def test_default_tiers_must_be_subset(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 1\nproject: x\ncompose:\n  file: c.yml\n  runner_service: r\n"
        "tiers:\n  lint:\n    command: 'echo'\n"
        "default_tiers: [nope]\n"
    )
    (tmp_path / "c.yml").write_text("services: {}\n")
    with pytest.raises(config.ConfigError) as ei:
        config.load_project(bad)
    assert "nope" in str(ei.value)


def test_requires_services_must_reference_declared_sidecar(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 1\nproject: x\ncompose:\n  file: c.yml\n  runner_service: r\n"
        "tiers:\n  t:\n    command: 'echo'\n    requires_services: [ghost]\n"
    )
    (tmp_path / "c.yml").write_text("services: {}\n")
    with pytest.raises(config.ConfigError) as ei:
        config.load_project(bad)
    assert "ghost" in str(ei.value)


def test_missing_compose_file_raises(tmp_path: Path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 1\nproject: x\ncompose:\n  file: missing.yml\n  runner_service: r\n"
        "tiers:\n  t:\n    command: 'echo'\n"
    )
    with pytest.raises(config.ConfigError) as ei:
        config.load_project(bad)
    assert "compose file not found" in str(ei.value)


# ---------------------------------------------------------------------------
# discover_projects — real ci/*/local-ci.yml scan
# ---------------------------------------------------------------------------


def test_discover_projects_skips_underscore_dirs():
    """ci/_fixture/local-ci.yml exists but must NOT surface via --list."""
    configs = config.discover_projects(CI_DIR)
    names = [c.project for c in configs]
    assert "fixture" not in names  # underscore prefix hides it


# ---------------------------------------------------------------------------
# cli — top-level dispatch
# ---------------------------------------------------------------------------


def _run_cli(args, capsys) -> tuple[int, str, str]:
    rc = cli.main(args)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_list_returns_ok_and_prints_empty_message(capsys, tmp_path):
    # Empty ci-root → EXIT_OK + friendly message.
    rc, out, _ = _run_cli(["--list", "--ci-root", str(tmp_path)], capsys)
    assert rc == exit_codes.EXIT_OK
    assert "no projects discovered" in out


def test_list_json_with_fixture(capsys):
    rc, out, _ = _run_cli(
        ["--list", "--json", "--project-yaml", str(FIXTURE_YAML)], capsys
    )
    assert rc == exit_codes.EXIT_OK
    payload = json.loads(out)
    assert payload["schema"] == "local-ci/v1"
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["project"] == "fixture"


def test_unknown_project_returns_exit_2(capsys, tmp_path):
    rc, _, err = _run_cli(
        ["ghost", "--ci-root", str(tmp_path)], capsys
    )
    assert rc == exit_codes.EXIT_CLI_MISUSE
    assert "no project specified" in err or "unknown project" in err


def test_unknown_tier_returns_exit_2(capsys):
    rc, _, err = _run_cli(
        ["fixture", "nosuch", "--project-yaml", str(FIXTURE_YAML), "--dry-run"],
        capsys,
    )
    assert rc == exit_codes.EXIT_CLI_MISUSE
    assert "nosuch" in err


def test_schema_invalid_yaml_returns_exit_3(capsys, tmp_path):
    bad = tmp_path / "local-ci.yml"
    bad.write_text(
        "version: 1\nproject: x\ncompose:\n  file: c.yml\n  runner_service: r\n"
        "tiers:\n  t:\n    command: 'echo'\n"
        "surprise: true\n"
    )
    (tmp_path / "c.yml").write_text("services: {}\n")
    rc, _, err = _run_cli(["--project-yaml", str(bad), "--list"], capsys)
    assert rc == exit_codes.EXIT_CONFIG_ERROR
    assert "schema violation" in err or "config error" in err


# ---------------------------------------------------------------------------
# --dry-run: byte-identical argv contract (spec §15 acceptance #1)
# ---------------------------------------------------------------------------


def test_dry_run_prints_tier_command_and_no_side_effects(capsys, monkeypatch):
    """--dry-run must not shell out. We monkey-patch subprocess.run to
    detect any accidental process launch."""
    import local_ci.compose as compose_mod

    called = []

    def sentinel(*a, **kw):
        called.append(a)
        raise RuntimeError("--dry-run must not shell out")

    monkeypatch.setattr(compose_mod.subprocess, "run", sentinel)

    rc, out, _ = _run_cli(
        ["fixture", "lint", "unit", "--dry-run", "--project-yaml", str(FIXTURE_YAML)],
        capsys,
    )
    assert rc == exit_codes.EXIT_OK
    assert called == [], f"--dry-run must not shell out, got: {called}"
    assert "docker compose" in out
    assert "echo lint-ok" in out
    assert "echo unit-ok" in out


def test_dry_run_with_mysql_tier_lists_sidecar_bringup(capsys):
    rc, out, _ = _run_cli(
        ["fixture", "mysql", "--dry-run", "--project-yaml", str(FIXTURE_YAML)],
        capsys,
    )
    assert rc == exit_codes.EXIT_OK
    assert "mysql-svc" in out  # sidecar service name in `up -d`
    assert "echo mysql-ok" in out


def test_dry_run_with_fresh_shows_volume_rm(capsys):
    rc, out, _ = _run_cli(
        ["fixture", "mysql", "--fresh", "--dry-run",
         "--project-yaml", str(FIXTURE_YAML)],
        capsys,
    )
    assert rc == exit_codes.EXIT_OK
    assert "volume rm" in out
    assert "fixture-mysql-data" in out


# ---------------------------------------------------------------------------
# report.py — JSON output validates against report.schema.json
# ---------------------------------------------------------------------------


def test_report_json_validates_against_schema():
    from local_ci.compose import SidecarResult, TierResult
    from local_ci.report import RunReport

    r = RunReport(project="fixture")
    r.tiers.append(TierResult(name="lint", status="pass", duration_s=1.5, exit_code=0))
    r.tiers.append(
        TierResult(
            name="unit",
            status="fail",
            duration_s=42.1,
            exit_code=1,
            first_failure_excerpt="FAILED test_x.py::test_y - AssertionError",
        )
    )
    r.sidecars.append(SidecarResult(name="mysql", brought_up=True, healthy=True))
    payload = r.to_json_obj()

    # Must validate — this is the CLI/skill contract.
    jsonschema.validate(payload, REPORT_SCHEMA)
    assert payload["schema"] == REPORT_SCHEMA_ID == "local-ci/v1"
    assert payload["overall_status"] == "fail"
    assert payload["overall_exit_code"] == 1


def test_report_pass_only_yields_exit_0():
    from local_ci.compose import TierResult
    from local_ci.report import RunReport

    r = RunReport(project="fixture")
    r.tiers.append(TierResult(name="lint", status="pass", duration_s=0.1, exit_code=0))
    assert r.overall_status == "pass"
    assert r.overall_exit_code == 0
    jsonschema.validate(r.to_json_obj(), REPORT_SCHEMA)


def test_json_delimiter_present_in_stream(capsys):
    """The `---LOCAL-CI-JSON---` marker MUST land on its own line before the
    JSON body so agent skill wrappers can slice deterministically."""
    from local_ci.compose import TierResult
    from local_ci.report import RunReport, print_json_block, print_summary

    r = RunReport(project="fixture")
    r.tiers.append(TierResult(name="lint", status="pass", duration_s=0.1, exit_code=0))

    buf = io.StringIO()
    print_summary(r, out=buf)
    print_json_block(r, out=buf)
    text = buf.getvalue()

    lines = text.splitlines()
    assert JSON_DELIMITER in lines
    idx = lines.index(JSON_DELIMITER)
    # Everything after the delimiter must parse as JSON.
    body = "\n".join(lines[idx + 1 :])
    parsed = json.loads(body)
    assert parsed["schema"] == "local-ci/v1"


# ---------------------------------------------------------------------------
# InitError preflight — exit 5 on missing MySQL dump (spec §10.1)
# ---------------------------------------------------------------------------


def test_mysql_restore_preflight_raises_init_error_when_env_missing(monkeypatch):
    from local_ci.compose import InitError, _preflight_mysql_restore
    from local_ci.config import Sidecar

    sc = Sidecar(
        name="mysql",
        service="mysql-svc",
        init={
            "kind": "mysql_restore",
            "source_env": "TOTALLY_UNSET_VAR_XYZ",
            "source_file": "dump.sql",
            "volume": "v",
        },
    )
    monkeypatch.delenv("TOTALLY_UNSET_VAR_XYZ", raising=False)
    with pytest.raises(InitError) as ei:
        _preflight_mysql_restore(sc, dbbackup_dir=None)
    assert "TOTALLY_UNSET_VAR_XYZ" in str(ei.value)
    assert ei.value.exit_code == exit_codes.EXIT_INIT_ERROR


def test_mysql_restore_preflight_raises_when_dump_missing(monkeypatch, tmp_path):
    from local_ci.compose import InitError, _preflight_mysql_restore
    from local_ci.config import Sidecar

    sc = Sidecar(
        name="mysql",
        service="mysql-svc",
        init={
            "kind": "mysql_restore",
            "source_env": "FAKE_BACKUP_DIR",
            "source_file": "not-there.sql",
            "volume": "v",
        },
    )
    monkeypatch.setenv("FAKE_BACKUP_DIR", str(tmp_path))
    with pytest.raises(InitError) as ei:
        _preflight_mysql_restore(sc, dbbackup_dir=None)
    assert "not-there.sql" in str(ei.value)
    assert "not found" in str(ei.value)


def test_mysql_restore_preflight_passes_when_dump_present(monkeypatch, tmp_path):
    from local_ci.compose import _preflight_mysql_restore
    from local_ci.config import Sidecar

    dump = tmp_path / "dump.sql"
    dump.write_text("-- fake dump\n")
    sc = Sidecar(
        name="mysql",
        service="mysql-svc",
        init={
            "kind": "mysql_restore",
            "source_env": "FAKE_BACKUP_DIR",
            "source_file": "dump.sql",
            "volume": "v",
        },
    )
    monkeypatch.setenv("FAKE_BACKUP_DIR", str(tmp_path))
    _preflight_mysql_restore(sc, dbbackup_dir=None)  # no raise


# ---------------------------------------------------------------------------
# Regression tests for PR #1009 review findings.
# Each is written to fail on the pre-fix code and pass on the fix (CLAUDE.md
# rule R7: fixtures must discriminate between buggy and fixed).
# ---------------------------------------------------------------------------


def test_report_empty_tiers_is_fail_not_pass():
    """MED #4: `all([])` is True → old code emitted overall_status=pass
    with zero tiers actually run. The property MUST return 'fail' when
    the tier list is empty."""
    from local_ci.report import RunReport

    r = RunReport(project="fixture")
    assert r.tiers == []
    assert r.overall_status == "fail"
    assert r.overall_exit_code == 1
    # And the JSON payload must reflect it too.
    payload = r.to_json_obj()
    assert payload["overall_status"] == "fail"
    assert payload["overall_exit_code"] == 1


def test_sidecar_result_uses_init_triggered_not_init_ran():
    """LOW #7: field was overclaiming. Renamed for honesty; schema updated."""
    from local_ci.compose import SidecarResult
    from local_ci.report import RunReport

    r = RunReport(project="fixture")
    r.sidecars.append(
        SidecarResult(
            name="mysql", brought_up=True, healthy=True, init_triggered=True
        )
    )
    payload = r.to_json_obj()
    assert payload["sidecars"][0]["init_triggered"] is True
    assert "init_ran" not in payload["sidecars"][0]
    # And the schema must accept the new field (regression against a stale
    # schema that only knew about init_ran).
    jsonschema.validate(payload, REPORT_SCHEMA)


def test_print_summary_uses_init_triggered():
    """Regression: print_summary must use init_triggered, not init_ran.

    Before the fix, print_summary() raised AttributeError because it
    referenced s.init_ran on a SidecarResult that only has init_triggered.
    """
    from local_ci.compose import SidecarResult
    from local_ci.report import RunReport, print_summary

    r = RunReport(project="fixture")
    r.sidecars.append(
        SidecarResult(
            name="mysql", brought_up=True, healthy=True, init_triggered=True
        )
    )
    buf = io.StringIO()
    # Must not raise AttributeError
    print_summary(r, out=buf)
    output = buf.getvalue()
    assert "(init ran)" in output
    assert "mysql" in output


def test_print_summary_init_triggered_false_omits_label():
    """When init_triggered is False, the '(init ran)' label must be absent."""
    from local_ci.compose import SidecarResult
    from local_ci.report import RunReport, print_summary

    r = RunReport(project="fixture")
    r.sidecars.append(
        SidecarResult(
            name="mysql", brought_up=True, healthy=True, init_triggered=False
        )
    )
    buf = io.StringIO()
    print_summary(r, out=buf)
    assert "(init ran)" not in buf.getvalue()


def test_pull_uses_check_true(monkeypatch):
    """HIGH #1: `--pull` failing must NOT silently continue with stale
    images. runner.pull() must raise DockerError on non-zero exit."""
    from local_ci.compose import ComposeRunner, DockerError

    cfg = config.load_project(FIXTURE_YAML)
    runner = ComposeRunner(cfg)

    # Simulate `docker compose pull` failing with rc=1.
    class FakeCompleted:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = ""
            self.stderr = "manifest unknown"

    import local_ci.compose as compose_mod
    monkeypatch.setattr(
        compose_mod.subprocess,
        "run",
        lambda *a, **kw: FakeCompleted(1),
    )
    with pytest.raises(DockerError) as ei:
        runner.pull()
    assert "1" in str(ei.value) or "failed" in str(ei.value).lower()


def test_wait_healthy_rejects_empty_health_when_state_is_exited(monkeypatch):
    """HIGH #2: empty Health + State=exited must return False. Old code
    treated any empty Health as healthy → dead sidecar looked alive →
    false green on tests that tolerate empty DB rows."""
    from local_ci.compose import _wait_healthy

    import local_ci.compose as compose_mod

    class FakeCompleted:
        def __init__(self, out):
            self.returncode = 0
            self.stdout = out
            self.stderr = ""

    # Simulate: healthcheck not declared, container exited after boot failure.
    monkeypatch.setattr(
        compose_mod.subprocess,
        "run",
        lambda *a, **kw: FakeCompleted("|exited\n"),
    )
    # Zero timeout is fine — we just need one poll to make the call.
    assert _wait_healthy(["docker", "compose"], "svc", timeout_s=1) is False


def test_wait_healthy_accepts_empty_health_when_state_is_running(monkeypatch):
    """HIGH #2 counterpart: services with no healthcheck but State=running
    must still be treated as healthy (backward-compatible with the common
    case of unimportant sidecars without an explicit HEALTHCHECK)."""
    from local_ci.compose import _wait_healthy

    import local_ci.compose as compose_mod

    class FakeCompleted:
        def __init__(self, out):
            self.returncode = 0
            self.stdout = out
            self.stderr = ""

    monkeypatch.setattr(
        compose_mod.subprocess,
        "run",
        lambda *a, **kw: FakeCompleted("|running\n"),
    )
    assert _wait_healthy(["docker", "compose"], "svc", timeout_s=1) is True


def test_exec_tier_captures_failure_excerpt(monkeypatch):
    """MED #3: TierResult.first_failure_excerpt was always empty despite
    the schema field existing. On failure it must contain SOME signal."""
    import local_ci.compose as compose_mod
    from local_ci.compose import ComposeRunner

    cfg = config.load_project(FIXTURE_YAML)
    runner = ComposeRunner(cfg)

    class FakeProc:
        def __init__(self):
            self.returncode = 1
            self._lines = iter([
                "test_a.py::foo PASSED\n",
                "FAILED test_b.py::bar - AssertionError: expected 3 got 4\n",
                "1 failed, 1 passed\n",
            ])
            self.stdout = self  # so `for line in proc.stdout` works

        def __iter__(self):
            return self._lines

        def wait(self):
            pass

    monkeypatch.setattr(compose_mod.subprocess, "Popen", lambda *a, **kw: FakeProc())
    result = runner.exec_tier(cfg.tiers["lint"])
    assert result.status == "fail"
    assert result.first_failure_excerpt != ""
    assert "FAILED test_b.py::bar" in result.first_failure_excerpt


def test_exec_tier_no_excerpt_on_pass(monkeypatch):
    """Passing tier must NOT surface a failure excerpt (would confuse
    JSON consumers into thinking there was a problem)."""
    import local_ci.compose as compose_mod
    from local_ci.compose import ComposeRunner

    cfg = config.load_project(FIXTURE_YAML)
    runner = ComposeRunner(cfg)

    class FakeProc:
        def __init__(self):
            self.returncode = 0
            self._lines = iter(["all good\n"])
            self.stdout = self

        def __iter__(self):
            return self._lines

        def wait(self):
            pass

    monkeypatch.setattr(compose_mod.subprocess, "Popen", lambda *a, **kw: FakeProc())
    result = runner.exec_tier(cfg.tiers["lint"])
    assert result.status == "pass"
    assert result.first_failure_excerpt == ""
