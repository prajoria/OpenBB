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
    orig = compose_mod.subprocess.run

    def sentinel(*a, **kw):
        called.append(a)
        return orig(*a, **kw)

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
