"""Contract tests for the portfolio-intel PR ops files.

Bead: OpenBBTechnical-qy83.1.2 — PR template + CI rule: feat/pi-* must
target portfolio.

Two artefacts land on the portfolio branch:

1. A GitHub Actions workflow that fails any PR whose head branch starts
   with ``feat/pi-`` (portfolio-intel work) and whose base is anything
   other than ``portfolio``. This is the CI backstop for the Execution
   Plan §2A branching contract.

2. A short section appended to ``.github/pull_request_template.md`` that
   points portfolio-intel contributors at the correct base branch, so
   the *human* default matches what CI will enforce.

These tests guard the *shape* of both artefacts so nobody accidentally
weakens the guard by deleting the branch pattern or removing the base
restriction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "portfolio-intel-base-guard.yml"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


@pytest.fixture(scope="module")
def workflow_body() -> str:
    """Return the raw workflow YAML."""
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pr_template_body() -> str:
    """Return the raw PR template text (post-append)."""
    assert PR_TEMPLATE.is_file(), f"missing PR template: {PR_TEMPLATE}"
    return PR_TEMPLATE.read_text(encoding="utf-8")


def test_workflow_file_exists() -> None:
    """The base-branch guard workflow must be on disk."""
    assert WORKFLOW.is_file()


def test_workflow_triggers_on_pull_request(workflow_body: str) -> None:
    """Workflow must fire on ``pull_request`` events to gate merges.

    Without a ``pull_request`` trigger the guard is inert — PRs merge
    without the check ever running.
    """
    assert re.search(
        r"^\s*pull_request:", workflow_body, flags=re.MULTILINE
    ), "workflow must trigger on pull_request events"


def test_workflow_targets_develop_and_main(workflow_body: str) -> None:
    """Guard only fires when the PR targets develop or main.

    Explicit allow-list — if someone opens a `feat/pi-*` PR against
    `portfolio` (the correct target), the guard should not fire at all.
    """
    for base in ("develop", "main"):
        assert re.search(
            rf"^\s*-\s*{base}\s*$", workflow_body, flags=re.MULTILINE
        ), f"workflow must gate PRs to `{base}`"


def test_workflow_matches_pi_head_pattern(workflow_body: str) -> None:
    """Guard must recognise the ``feat/pi-*`` head-branch prefix.

    The Execution Plan §2A convention names portfolio-intel branches
    ``feat/pi-<lane>/<slug>`` — if the regex drifts, the guard silently
    lets PI branches through into develop.
    """
    assert (
        "feat/pi-" in workflow_body
    ), "workflow must match the feat/pi- head-branch prefix"


def test_workflow_fails_the_job_not_just_warns(workflow_body: str) -> None:
    """Guard must call ``exit 1`` — a warn-only guard is not a guard.

    Grep for ``exit 1`` in the run block. If the check only comments on
    the PR without failing the job, branch protection cannot block the
    merge.
    """
    assert (
        "exit 1" in workflow_body
    ), "workflow must exit non-zero to block the merge (not warn-only)"


def test_pr_template_documents_portfolio_intel_base(pr_template_body: str) -> None:
    """PR template must mention the ``portfolio`` base for PI branches.

    The template is where human contributors first learn the convention;
    CI is the backstop. Both must agree.
    """
    lowered = pr_template_body.lower()
    assert (
        "portfolio-intel" in lowered or "feat/pi-" in lowered
    ), "PR template must reference portfolio-intel work"
    assert (
        "portfolio" in lowered
    ), "PR template must name `portfolio` as the base branch for PI PRs"
