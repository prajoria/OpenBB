"""Regression tests for the dual-MCP dependency lock workflow (#2245)."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "dual-mcp-lock.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_check_job_runs_lock_check():
    """Pull requests fail when a lock is stale."""
    assert "python scripts/lock_mcp_envs.py --check" in _workflow()


def test_replay_job_runs_on_windows_with_pinned_pester():
    """The launcher suite and replay run on Windows with Pester 4."""
    workflow = _workflow()
    for required in (
        "windows-latest",
        "RequiredVersion 4.10.1",
        "scripts/tests/Start-DualMcp.Tests.ps1",
        "scripts/test_mcp_lock_replay.ps1",
        "submodules:",
    ):
        assert required in workflow, required


def test_refresh_is_report_only():
    """The scheduled refresh reports upgrades without writing to the repository."""
    workflow = _workflow()
    for required in ("schedule:", "workflow_dispatch:", "--upgrade"):
        assert required in workflow, required
    for forbidden in ("git push", "gh pr create", "contents: write"):
        assert forbidden not in workflow, forbidden


def test_triggers_cover_lock_inputs():
    """Every file that can change the lock graph triggers the workflow."""
    workflow = _workflow()
    for path in (
        '"scripts/mcp_locks/**"',
        '"scripts/lock_mcp_envs.py"',
        '"scripts/start-dual-mcp.ps1"',
        '"scripts/mcp_stack_lifecycle.psm1"',
        '"openbb_platform/extensions/mcp_server/**"',
    ):
        assert path in workflow, path
