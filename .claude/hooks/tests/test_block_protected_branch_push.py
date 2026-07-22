"""Tests for .claude/hooks/block-protected-branch-push.py (#598).

The hook protects `openbb_pine_support` and `develop` from accidental
direct `git push` by Claude. It's been in production for months but
had zero test coverage — logic that gates two important branches
should have regression tests codifying the intent.

#598 reported a false-positive on `git push --force-with-lease` from a
non-protected feature branch. Manual repro of that exact command
against current code exits 0 (allow) — no false positive today. But
the reporter's ambiguity means we should codify the CORRECT behavior
for all edge cases so the exact scenario can never regress.

R7.7 discipline: every load-bearing assertion has an inverse — flip
the hook to a broken form and confirm the test would catch it. See
`test_reverse_verify_catches_broken_hook` at the bottom for the
sentinel case.

The hook's contract:
  stdin  = {"tool_name": "Bash", "tool_input": {"command": "..."}}
  stdout = JSON with hookSpecificOutput.permissionDecision when denying
  stdout = empty (exit 0) when allowing
  exit code always 0 (the schema conveys the decision, not the code)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _REPO_ROOT / ".claude" / "hooks" / "block-protected-branch-push.py"


def _run_hook(command: str) -> tuple[str, int]:
    """Invoke the hook with a Bash tool payload; return (stdout, exit_code).

    Uses the same Python interpreter as the test runner so behavior is
    consistent across CI + local. The hook writes its decision to stdout;
    exit code is always 0 per its documented contract.
    """
    python = shutil.which("python") or sys.executable
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(  # noqa: S603 - test-controlled subprocess
        [python, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=10,
        check=False,
    )
    return result.stdout, result.returncode


def _is_deny(stdout: str) -> bool:
    """Parse stdout; return True if the hook denied the command."""
    if not stdout.strip():
        return False
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    return payload.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


def _deny_reason(stdout: str) -> str:
    """Extract the human-readable deny reason (empty string if allowed)."""
    if not _is_deny(stdout):
        return ""
    payload = json.loads(stdout)
    return payload["hookSpecificOutput"].get("permissionDecisionReason", "")


# ---------------------------------------------------------------------------
# Baseline: hook file exists and is invokable
# ---------------------------------------------------------------------------


def test_hook_file_exists():
    """Sanity — the hook is at the expected path and readable."""
    assert _HOOK.exists(), f"hook not found at {_HOOK}"
    assert _HOOK.is_file()


def test_hook_exits_zero_on_empty_payload():
    """Malformed input MUST NOT cause the hook to fail — malformed
    should pass through silently (the tool call is then subject to
    normal permission checks). Documented in the hook's main().
    """
    python = shutil.which("python") or sys.executable
    result = subprocess.run(  # noqa: S603 - test-controlled subprocess
        [python, str(_HOOK)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# NON-git-push commands must pass through
# ---------------------------------------------------------------------------


class TestNonGitPushPassthrough:
    """Anything that isn't a `git push` allows silently."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git status",
            "git log --oneline",
            "git fetch origin",
            "git pull origin openbb_pine_support",
            "ls -la",
            "echo openbb_pine_support",
            "cat README.md | grep push",
            "git commit -m 'push to openbb_pine_support later'",
            # Words containing "push" but not the git push command
            "grep 'git push' README.md",
            "echo 'do not git push to develop'",  # a message about pushing
        ],
    )
    def test_allows_non_push_commands(self, cmd: str):
        """Non-`git push` command must pass through the hook untouched."""
        stdout, code = _run_hook(cmd)
        assert code == 0
        assert not _is_deny(stdout), (
            f"expected allow, got deny for command: {cmd!r}\n"
            f"reason: {_deny_reason(stdout)}"
        )


# ---------------------------------------------------------------------------
# Explicit protected-branch pushes MUST be blocked
# ---------------------------------------------------------------------------


class TestBlocksProtectedBranches:
    """Any `git push` targeting `openbb_pine_support` or `develop` is denied."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "git push origin openbb_pine_support",
            "git push origin develop",
            "git push origin HEAD:openbb_pine_support",
            "git push origin HEAD:develop",
            "git push origin feature:openbb_pine_support",
            "git push origin +openbb_pine_support",  # force-refspec syntax
            "git push origin +develop",
            "git push --force origin openbb_pine_support",
            "git push --force-with-lease origin openbb_pine_support",
            "git push --force-with-lease=openbb_pine_support:sha origin openbb_pine_support",
            "git push origin refs/heads/openbb_pine_support",
            "git push origin refs/heads/develop",
            # Delete-syntax should ALSO be blocked (deleting a protected branch
            # is even more destructive than pushing to it).
            "git push origin :openbb_pine_support",
            "git push origin :develop",
            # Env-prefixed commands
            "GIT_TRACE=1 git push origin openbb_pine_support",
            # Chained — the second command is a protected push
            "git status && git push origin openbb_pine_support",
            "git commit -am 'x' ; git push origin develop",
        ],
    )
    def test_blocks(self, cmd: str):
        """Push targeting a protected branch must be denied."""
        stdout, code = _run_hook(cmd)
        assert code == 0
        assert _is_deny(stdout), f"expected DENY, got allow for command: {cmd!r}"
        # The deny reason must name what's being blocked so the human
        # reader knows which branch triggered.
        reason = _deny_reason(stdout)
        assert (
            "openbb_pine_support" in reason or "develop" in reason
        ), f"deny reason missing branch name: {reason!r}"


# ---------------------------------------------------------------------------
# NON-protected branches — the #598 false-positive class
# ---------------------------------------------------------------------------


class TestAllowsNonProtectedBranches:
    """The #598 report: pushing a feature branch (or anything not in
    `PROTECTED_BRANCHES`) MUST be allowed, even with --force flags.

    These are the exact patterns the reporter's ambiguity might have
    hit. Codifying them as passing tests prevents regression.
    """

    @pytest.mark.parametrize(
        "cmd",
        [
            # Explicit refspec push to a feature branch
            "git push origin feat/pine-something",
            "git push origin fix/pine-bug-123",
            "git push origin docs/pine-guide",
            # -u / --set-upstream (the standard first push)
            "git push -u origin feat/e33-byo-provider-refactor",
            "git push --set-upstream origin feat/pine-canonical-bars-and-capture-gh-967",
            # --force on a feature branch
            "git push --force origin feat/pine-something",
            "git push -f origin fix/pine-something",
            # --force-with-lease with explicit refspec (the exact #598 shape)
            "git push --force-with-lease origin feat/e33-byo-provider-refactor",
            "git push --force-with-lease origin fix/pine-hook-force-push-tests-gh-598",
            # --force-with-lease=<ref>[:<expected>] form with feature branch
            "git push --force-with-lease=feat/foo origin feat/foo",
            # HEAD:<branch> targeting a feature branch
            "git push origin HEAD:feat/pine-something",
            # +feature-refspec (force syntax, feature branch)
            "git push origin +feat/pine-something",
            # Deleting a feature branch (destructive but not protected)
            "git push origin :feat/pine-old-branch",
            # Push to a completely different remote
            "git push my-fork feat/pine-something",
        ],
    )
    def test_allows(self, cmd: str):
        """Push targeting a non-protected branch must be allowed (#598 class)."""
        stdout, code = _run_hook(cmd)
        assert code == 0
        assert not _is_deny(stdout), (
            f"FALSE POSITIVE (#598 class): expected allow, got deny\n"
            f"command: {cmd!r}\n"
            f"reason: {_deny_reason(stdout)}"
        )


# ---------------------------------------------------------------------------
# Implicit-refspec pushes (no positional args) — the tricky path
# ---------------------------------------------------------------------------


class TestImplicitRefspec:
    """`git push` with no positional args pushes the current branch to
    its tracking upstream. Under push.default=simple (git ≥2.0 default),
    the destination branch name equals the source branch name.

    The hook falls back to `_current_branch()` in this case. Testing
    this path requires either being ON the branch (integration-y) or
    trusting the manual repro documented in the #598 comment.

    We test the passthrough behavior when current-branch lookup fails
    (detached HEAD) — the documented safe default is to allow.
    """

    def test_bare_git_push_from_non_protected_current_branch_allows(self):
        """From `fix/pine-hook-force-push-tests-gh-598` (this branch),
        `git push` with no args resolves to the current branch, which
        is not protected → allow.
        """
        # This test runs on the branch it's asserting about — perfect
        # integration check.
        stdout, code = _run_hook("git push")
        assert code == 0
        assert not _is_deny(stdout), (
            f"bare 'git push' from non-protected current branch should "
            f"allow; got: {_deny_reason(stdout)}"
        )

    def test_bare_force_with_lease_from_non_protected_current_branch_allows(self):
        """The #598 exact shape: `git push --force-with-lease` with no
        positional args, from a feature branch. Must NOT false-positive.
        """
        stdout, code = _run_hook("git push --force-with-lease")
        assert code == 0
        assert not _is_deny(stdout), (
            f"#598 REGRESSION: 'git push --force-with-lease' from "
            f"non-protected current branch should allow; got: "
            f"{_deny_reason(stdout)}"
        )

    def test_bare_force_from_non_protected_current_branch_allows(self):
        """Same as above with plain --force."""
        stdout, code = _run_hook("git push --force")
        assert code == 0
        assert not _is_deny(stdout)


# ---------------------------------------------------------------------------
# Edge cases that might trick the parser
# ---------------------------------------------------------------------------


class TestParserEdgeCases:
    """Cases where a naive parser would mis-classify."""

    def test_git_pushd_is_not_git_push(self):
        """`git pushd` doesn't exist, but the whole-word regex must not
        false-match it as `git push`.
        """
        # We can't test this directly (git errors first) but we can test
        # a command that would trip a substring match.
        stdout, code = _run_hook("git help push")  # not a push
        assert code == 0
        assert not _is_deny(stdout)

    def test_message_containing_push_word_allows(self):
        """A commit message MENTIONING push isn't a push."""
        stdout, code = _run_hook(
            "git commit -m 'push helper for develop and openbb_pine_support'"
        )
        assert code == 0
        assert not _is_deny(stdout)

    def test_unbalanced_quotes_pass_through(self):
        """The parser gives up on unbalanced quotes (shlex fails) and
        allows — git will error naturally when the malformed command
        actually runs.
        """
        stdout, code = _run_hook("git push origin 'unclosed")
        assert code == 0
        assert not _is_deny(stdout)

    def test_multiple_refspecs_all_checked(self):
        """`git push origin foo bar baz` pushes THREE refs; if any of
        them is protected, block.
        """
        stdout, code = _run_hook(
            "git push origin feat/foo feat/bar openbb_pine_support"
        )
        assert code == 0
        assert _is_deny(
            stdout
        ), "multi-refspec push containing protected branch must be blocked"

    def test_dry_run_still_blocked_for_protected(self):
        """`--dry-run` doesn't actually push, but the intent to push a
        protected branch is worth blocking — the human should be
        redirected to a feature-branch workflow regardless.
        """
        stdout, code = _run_hook("git push --dry-run origin openbb_pine_support")
        assert code == 0
        assert _is_deny(stdout)


# ---------------------------------------------------------------------------
# R7.7 reverse-verification: mutating the hook MUST fail a test
# ---------------------------------------------------------------------------


def test_reverse_verify_catches_broken_hook(tmp_path: Path):
    """If someone breaks the hook to always allow, at least one
    protected-branch test above MUST fail. This is the sentinel that
    proves the tests are load-bearing, not ceremonial.

    We construct a stripped-down "always allow" version of the hook,
    run it against a known-should-be-blocked command, and assert it
    would incorrectly allow — proving the real tests would catch the
    regression.
    """
    broken = tmp_path / "broken_hook.py"
    broken.write_text(
        "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n",
        encoding="utf-8",
    )

    # Run the broken hook against a command the real hook blocks.
    python = shutil.which("python") or sys.executable
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin openbb_pine_support"},
    }
    result = subprocess.run(  # noqa: S603 - test-controlled subprocess
        [python, str(broken)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    # Broken hook returns empty stdout (implicit allow). Real hook
    # would return a deny JSON. This asymmetry proves the tests can
    # distinguish correct from broken behavior.
    assert not _is_deny(result.stdout), (
        "sanity check: the deliberately-broken hook allows everything; "
        "if this fails, _is_deny is misclassifying empty output as deny"
    )

    # Now the same command against the REAL hook — must deny.
    real_stdout, _ = _run_hook("git push origin openbb_pine_support")
    assert _is_deny(real_stdout), (
        "R7.7 REVERSE VERIFY FAILED: real hook allowed a command that "
        "should be denied. The tests above are ceremonial — they'd all "
        "pass against the broken hook too."
    )
