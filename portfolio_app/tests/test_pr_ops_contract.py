"""Contract tests for the portfolio-intel PR ops files.

Bead: OpenBBTechnical-qy83.1.2 — PR template + CI rule: feat/pi-* must
target portfolio.

Two artefacts land on the portfolio branch:

1. A GitHub Actions workflow that fails any PR whose head branch matches
   the portfolio-intel patterns (feat/pi-*, feature/pi-*, pi/*, case-
   insensitive) and whose base is anything other than ``portfolio``.
   This is the CI backstop for the Execution Plan §2A branching contract.

2. A short section appended to ``.github/pull_request_template.md`` that
   points portfolio-intel contributors at the correct base branch, so
   the *human* default matches what CI will enforce.

These tests guard the *shape* of both artefacts so nobody accidentally
weakens the guard by deleting the branch pattern or removing the base
restriction.

Hardening (PR #471 R2):
- YAML-parse the workflow file instead of grepping substrings so
  ``exit 1`` in a comment or ``exit 1`` in an unrelated step doesn't
  spuriously satisfy the assertion.
- Assert the exit-1 statement lives inside the conditional-branch of
  the guard step's shell script, not anywhere else.
- Also assert the ``pull_request.branches`` allow-list is exactly
  ``[develop, main]`` under the correct key, not just present anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "portfolio-intel-base-guard.yml"
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


@pytest.fixture(scope="module")
def workflow_body() -> str:
    """Return the raw workflow YAML."""
    assert WORKFLOW.is_file(), f"missing workflow: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow_yaml(workflow_body: str) -> dict:
    """Return the parsed workflow YAML.

    Parsing rather than grepping means a comment containing ``exit 1``
    or ``pull_request:`` cannot spuriously satisfy an assertion.
    """
    parsed = yaml.safe_load(workflow_body)
    assert isinstance(parsed, dict), "workflow YAML must be a mapping"
    return parsed


@pytest.fixture(scope="module")
def pr_template_body() -> str:
    """Return the raw PR template text (post-append)."""
    assert PR_TEMPLATE.is_file(), f"missing PR template: {PR_TEMPLATE}"
    return PR_TEMPLATE.read_text(encoding="utf-8")


def _guard_run_script(workflow_yaml: dict) -> str:
    """Return the shell script text of the guard step (the ``run:`` block).

    Located by walking jobs -> steps and finding the step whose ``run``
    field contains ``exit 1`` — the only step in this workflow that has
    a non-trivial script. Raises ``AssertionError`` if not found.
    """
    for job in (workflow_yaml.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run")
            if isinstance(run, str) and "exit 1" in run:
                return run
    raise AssertionError(
        "no step with `exit 1` in its `run` block — guard step missing?"
    )


def test_workflow_file_exists() -> None:
    """The base-branch guard workflow must be on disk."""
    assert WORKFLOW.is_file()


def test_workflow_triggers_on_pull_request(workflow_yaml: dict) -> None:
    """Workflow must fire on ``pull_request`` events to gate merges.

    Without a ``pull_request`` trigger the guard is inert.
    PyYAML parses ``on:`` as Python's boolean ``True`` key — accept
    either form so YAML quoting variants both work.
    """
    on_key = workflow_yaml.get("on") or workflow_yaml.get(True)
    assert (
        isinstance(on_key, dict) and "pull_request" in on_key
    ), "workflow must have `on.pull_request:` mapping"


def test_workflow_targets_exactly_develop_and_main(workflow_yaml: dict) -> None:
    """Guard's ``on.pull_request.branches`` must be exactly [develop, main].

    Explicit allow-list — if someone opens a ``feat/pi-*`` PR against
    ``portfolio`` (the correct target), the guard should NOT fire.
    YAML-parsed so a comment mentioning ``develop`` or ``main`` elsewhere
    can't spuriously satisfy the check (PR #471 R2 finding: prior test
    only grepped for lines).
    """
    on_key = workflow_yaml.get("on") or workflow_yaml.get(True)
    branches = on_key["pull_request"].get("branches")
    assert branches is not None, "on.pull_request.branches must be set"
    assert set(branches) == {
        "develop",
        "main",
    }, f"expected exactly [develop, main], got {branches}"


def test_workflow_matches_pi_head_patterns(workflow_yaml: dict) -> None:
    """Guard must recognise the portfolio-intel head-branch prefixes.

    Post-R2, the guard accepts ``feat/pi-*``, ``feature/pi-*``, and
    ``pi/*`` under ``shopt -s nocasematch`` so casing variants are
    caught too. Assert on the run script content of the guard step.
    """
    script = _guard_run_script(workflow_yaml)
    assert "nocasematch" in script, (
        "guard must enable case-insensitive matching so Feat/pi-* / "
        "FEAT/PI-* variants don't bypass"
    )
    for pat in ("feat/pi-*", "feature/pi-*", "pi/*"):
        assert pat in script, f"guard script must match portfolio-intel prefix {pat!r}"


def test_workflow_exits_inside_the_guard_conditional(workflow_yaml: dict) -> None:
    """`exit 1` must live INSIDE the `if` that matched the PI prefix.

    PR #471 R2 finding (medium): the prior test only checked ``"exit 1"
    in body``, which passes if the token appears in a comment or in an
    unrelated step. This test parses the guard step's shell script and
    verifies the exit occurs inside a conditional block whose test
    references the head-ref check.
    """
    script = _guard_run_script(workflow_yaml)
    # Structural check: script must contain both `if [[ "$HEAD_REF" ==`
    # (the conditional) AND `exit 1` inside a `fi`-terminated block.
    # A simple line-based scan is enough for this specific script shape.
    lines = script.splitlines()
    in_pi_if = False
    saw_exit_inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("if ") and "HEAD_REF" in stripped:
            in_pi_if = True
        elif stripped == "fi":
            in_pi_if = False
        elif in_pi_if and stripped == "exit 1":
            saw_exit_inside = True
            break
    assert saw_exit_inside, (
        '`exit 1` must appear inside the `if [[ "$HEAD_REF" == ... ]]` '
        "conditional block, not outside it or in a comment"
    )


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
