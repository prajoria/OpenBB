"""Regression tests for the General Code Linting workflow toolchain."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "general-linting.yml"


def test_workflow_installs_checked_out_devtools_contract():
    """Workflow dependencies come from the repository package, not latest PyPI."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pip install ./openbb_platform/extensions/devtools" in workflow
    assert "pip install openbb-devtools" not in workflow


def test_workflow_verifies_every_invoked_lint_command_is_available():
    """The preflight loop covers every command invoked by lint steps."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    loop_line = next(
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("for command in ")
    )
    verified = set(
        loop_line.removeprefix("for command in ").removesuffix("; do").split()
    )
    lint_block = workflow.split(
        "# Run linters for openbb_platform | cli", maxsplit=1
    )[1].split("else", maxsplit=1)[0]
    invoked = {
        line.strip().split(maxsplit=1)[0]
        for line in lint_block.splitlines()
        if line.startswith("            ") and line.strip()
    }
    invoked.add("codespell")
    assert invoked == verified
