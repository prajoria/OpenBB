"""Regression tests for the ScanSnapshotStore issue planner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "scan_snapshot_plan.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("scan_snapshot_plan", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["scan_snapshot_plan"] = module
    spec.loader.exec_module(module)
    return module


def test_main_uses_created_issue_numbers_for_dependencies(monkeypatch):
    """Dependency links must use server-returned numbers, not assumptions."""
    module = _load_module()
    assigned_numbers = iter(
        [3101, 4117, 5229, 6331, 7447, 8551, 9661, 10771, 11887, 12997, 13103, 14221]
    )
    created_bodies: dict[str, str] = {}

    def fake_create_issue(title: str, body: str, dry: bool) -> int:
        assert dry is False
        created_bodies[title] = body
        return next(assigned_numbers)

    def fake_gh(*args: str) -> str:
        if args[:2] == ("issue", "view"):
            return "Existing parent body."
        if args[:2] == ("issue", "edit"):
            return ""
        raise AssertionError(f"Unexpected gh call: {args}")

    monkeypatch.setattr(module, "create_issue", fake_create_issue)
    monkeypatch.setattr(module, "add_to_project", lambda *_args: None)
    monkeypatch.setattr(module, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", ["scan_snapshot_plan.py"])

    assert module.main() == 0

    def body_for(title_fragment: str) -> str:
        return next(
            body for title, body in created_bodies.items() if title_fragment in title
        )

    assert "Blocked-by #3101 (A1 schema)." in body_for("Phase A2")
    assert "Blocked-by #3101 (A1), #4117 (A2)." in body_for("Phase A3")
    assert "Blocked-by #4117 (A2)." in body_for("Phase B1")
    assert "Blocked-by #6331 (B1)." in body_for("Phase B2")
    assert "Blocked-by #6331 (B1 runner) + #5229 (A3 fixtures" in body_for(
        "wire tt_movers"
    )
    for title_fragment in (
        "wire tt_signals",
        "wire tt_validate",
        "wire tt_tune",
        "wire tt_audit",
    ):
        body = body_for(title_fragment)
        assert "#6331" in body
        assert "#5229" in body
    assert "Blocked-by #4117 (A2)." in body_for("retention worker")
    assert "Blocked-by #6331 (B1)." in body_for("cadence docs")


def test_gh_decodes_cli_output_as_utf8(monkeypatch):
    """Unicode issue titles must survive Windows' non-UTF-8 locale."""
    module = _load_module()
    monkeypatch.setattr(module.shutil, "which", lambda _name: sys.executable)
    command = (
        "import sys; " "sys.stdout.buffer.write('Phase A1 — DDL\\n'.encode('utf-8'))"
    )

    assert module.gh("-c", command) == "Phase A1 — DDL"


def test_gh_requests_utf8_decoding_on_every_platform(monkeypatch):
    """The Windows fix must remain guarded even when CI's locale is UTF-8."""
    module = _load_module()
    run_kwargs: dict[str, object] = {}
    monkeypatch.setattr(module.shutil, "which", lambda _name: "gh.exe")

    def fake_run(*_args, **kwargs):
        run_kwargs.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.gh("issue", "list")
    assert run_kwargs["encoding"] == "utf-8"


def test_create_issue_updates_existing_issue_body(monkeypatch):
    """Reruns must repair existing plan issues instead of discarding the body."""
    module = _load_module()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "find_open_by_title", lambda _title: 1937)
    monkeypatch.setattr(module, "gh", lambda *args: calls.append(args) or "")

    assert module.create_issue("Phase A2", "corrected body", False) == 1937
    assert calls == [
        (
            "issue",
            "edit",
            "1937",
            "--repo",
            module.REPO,
            "--body",
            "corrected body",
        )
    ]


def test_resolve_dependencies_formats_dry_run_placeholders():
    """Dry-run output must remain readable before GitHub assigns numbers."""
    module = _load_module()

    assert (
        module.resolve_dependencies("Blocked-by [[A1]].", {}, dry_run=True)
        == "Blocked-by #<A1>."
    )


def test_resolve_dependencies_rejects_unknown_unresolved_markers():
    """New dependency keys must not leak into real issue bodies."""
    module = _load_module()

    with pytest.raises(ValueError, match="Dependency C1 has not been created yet"):
        module.resolve_dependencies("Blocked-by [[C1]].", {}, dry_run=False)


def test_render_parent_body_replaces_prior_breakdowns():
    """Planner reruns must leave exactly one breakdown and preserve later text."""
    module = _load_module()
    plan = [module.Node(key="A1", title="First task", body="", number=3101)]
    existing = (
        "Parent intro.\n\n"
        "## Plan breakdown (filed 2026-08-05)\n\n"
        "- #1936 — stale task\n\n"
        "## Operator notes\n\n"
        "Keep this text.\n\n"
        "## Plan breakdown (filed 2026-08-05)\n\n"
        "- #1936 — duplicated task"
    )

    rendered = module.render_parent_body(existing, plan)

    assert rendered.count("## Plan breakdown (filed 2026-08-05)") == 1
    assert "- #3101 — First task" in rendered
    assert "## Operator notes\n\nKeep this text." in rendered
