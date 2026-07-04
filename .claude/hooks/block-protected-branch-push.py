#!/usr/bin/env python3
"""PreToolUse:Bash hook that blocks git push to protected branches.

Policy (updated 2026-07-04)
---------------------------
* ``openbb_pine_support`` is the primary integration branch for Pine +
  TradingView work in this fork.
* ``develop`` is the downstream integration branch, bulk-merged from
  ``openbb_pine_support`` by a human.
* Neither branch may be pushed to directly by Claude. Feature branches
  from ``openbb_pine_support`` -> PR back is the required workflow.

Historical note: prior to 2026-07-04 this hook protected
``openbb_tradingview`` in place of ``openbb_pine_support``. The remote
``openbb_tradingview`` was deleted server-side, and ``openbb_pine_support``
inherits its role as the master/main branch for Pine work.

Hook contract
-------------
* stdin  = ``{"tool_name": "Bash", "tool_input": {"command": "..."}}``
* stdout = JSON with ``hookSpecificOutput.permissionDecision`` when blocking;
  empty (exit 0) when allowing.
* exit 0 on all paths -- decision is conveyed via the JSON, not exit code
  (per PreToolUse hook schema; using exit 1 would surface as a hook error
  rather than a permission denial).

Design notes
------------
Non-git-push commands pass through silently. This hook is a scalpel, not a
firewall -- ``eval "$(base64 -d ...)"`` bypasses it, and that's fine. We're
guarding against ACCIDENTAL pushes, not adversarial ones.

Written in Python (not bash + jq) because ``jq`` is not universally on team
members' Git Bash PATH, but Python is guaranteed by the OpenBB dev environment.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys


PROTECTED_BRANCHES = frozenset({"openbb_pine_support", "develop"})

# Match "git push" as a whole word so we don't false-positive on
# "git pushd" (doesn't exist) or a rare "grepush" (also doesn't).
# Handles leading env prefixes (GIT_TRACE=1 git push) and chained
# commands (git status && git push origin main).
_GIT_PUSH_RE = re.compile(r"(?:^|[\s;&|])git\s+push(?:\s|$)")


def _emit_deny(reason: str) -> None:
    """Print a deny decision and exit 0 (the schema, not exit code, denies)."""
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    sys.exit(0)


def _current_branch() -> str | None:
    """Return the current branch name, or None if detached / unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    name = result.stdout.strip()
    if not name or name == "HEAD":
        return None
    return name


def _extract_push_tail(command: str) -> str | None:
    """Return the substring after the LAST ``git push`` on the line, or None
    if the command doesn't contain a git push at all.
    """
    if not _GIT_PUSH_RE.search(command):
        return None
    # Split on the "git push" boundary. Keep the last chunk (in case there
    # are multiple, take the operative one).
    parts = re.split(r"(?:^|(?<=[\s;&|]))git\s+push(?:\s+|$)", command)
    tail = parts[-1] if parts else ""
    # If the original command was chained (`git push origin foo && echo`),
    # cut at the next shell separator so we don't include the following
    # command's args as if they were push args.
    tail = re.split(r"[;&|]", tail, maxsplit=1)[0]
    return tail.strip()


def _parse_refspec_destinations(tail: str) -> tuple[list[str], bool]:
    """Parse the arg tail of a git push and return (destinations, has_force).

    destinations: list of branch names being pushed TO. May be empty if the
                  push has no refspec (implicit-tracking case; caller handles
                  by falling back to current branch).
    has_force:    True if --force / --force-with-lease / -f / '+refspec' is
                  present.
    """
    try:
        tokens = shlex.split(tail)
    except ValueError:
        # Unbalanced quotes -- can't parse safely, so let it through. If the
        # user's command really is malformed, git will error naturally.
        return ([], False)

    has_force = False
    positional: list[str] = []

    for tok in tokens:
        if tok in {"--force", "-f", "--force-with-lease", "--force-if-includes"}:
            has_force = True
            continue
        if tok.startswith("--force-with-lease="):
            has_force = True
            continue
        if tok.startswith("-"):
            # Other flags (--tags, --set-upstream, --dry-run, -u, -n, -v ...)
            # don't affect branch targeting; ignore.
            continue
        positional.append(tok)

    # positional args are: [<repository> [<refspec>...]]
    if len(positional) <= 1:
        # No refspecs given (either just `git push`, or `git push origin`).
        return ([], has_force)

    refspecs = positional[1:]
    destinations: list[str] = []
    for refspec in refspecs:
        # '+refspec' is force-refspec syntax.
        if refspec.startswith("+"):
            has_force = True
            refspec = refspec[1:]
        # <local>:<remote> -> destination is <remote>. Bare -> destination is
        # the whole token. Delete syntax ':<branch>' also caught: <remote>
        # portion is the branch name to delete, which we still want to block.
        if ":" in refspec:
            dest = refspec.split(":", 1)[1]
        else:
            dest = refspec
        # Strip refs/heads/ prefix if the user was explicit.
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/") :]
        if dest:
            destinations.append(dest)

    return (destinations, has_force)


def _build_deny_reason(blocked: list[str], has_force: bool) -> str:
    """Return the user-facing reason string for a deny decision."""
    uniq = sorted(set(blocked))
    dests = ", ".join(uniq)
    force_note = " (force push detected)" if has_force else ""
    return (
        f"BLOCKED: direct push to protected branch(es): {dests}{force_note}.\n"
        "\n"
        "Policy: openbb_pine_support is the primary integration branch for Pine +\n"
        "TradingView work; develop is the downstream integration branch. Neither\n"
        "may be pushed to directly. Bulk merges from openbb_pine_support to\n"
        "develop are done manually by a human, never by Claude.\n"
        "\n"
        "Required workflow:\n"
        "  1. Create a feature branch off openbb_pine_support:\n"
        "       git switch -c <feature-name> openbb_pine_support\n"
        "  2. Commit your work on the feature branch.\n"
        "  3. Push the feature branch:\n"
        "       git push -u origin <feature-name>\n"
        "  4. Open a PR targeting openbb_pine_support:\n"
        "       gh pr create --base openbb_pine_support --head <feature-name>\n"
        "\n"
        "If you truly need to bypass this (e.g. amending a commit already on the\n"
        "protected branch during a manual maintenance session), disable the hook\n"
        "temporarily by editing .claude/settings.json or run the push from outside\n"
        "Claude."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Malformed input -- pass through. The tool call will still be
        # subject to normal permission checks.
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        sys.exit(0)

    tail = _extract_push_tail(command)
    if tail is None:
        # Not a git push at all -- allow silently.
        sys.exit(0)

    destinations, has_force = _parse_refspec_destinations(tail)

    if not destinations:
        # No explicit refspec -- git pushes the current branch to its upstream.
        # Destination is the current branch name (under push.default=simple,
        # which has been the git default since 2.0).
        current = _current_branch()
        if current is None:
            # Can't determine current branch -- allow to avoid false positive.
            sys.exit(0)
        destinations = [current]

    blocked = [d for d in destinations if d in PROTECTED_BRANCHES]
    if not blocked:
        sys.exit(0)

    _emit_deny(_build_deny_reason(blocked, has_force))


if __name__ == "__main__":
    main()
