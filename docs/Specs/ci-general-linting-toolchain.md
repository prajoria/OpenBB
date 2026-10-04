# General Code Linting toolchain specification

Status: implementation specification for
[#2095 (General Code Linting job lacks installed linters)](https://github.com/prajoria/OpenBB/issues/2095).
Integration target: `portfolio`.

## Problem

The workflow installs the unpinned PyPI package `openbb-devtools`. The currently
published package no longer declares every executable that the workflow invokes.
The job therefore exits 127 at `black` before checking changed Python code.

The repository already owns the expected lint dependency contract in
`openbb_platform/extensions/devtools/pyproject.toml`. It declares Black, mypy,
Pylint, Ruff and Codespell with Python 3.10-compatible ranges and maintains the
corresponding lock file.

## Decision

Install the checked-out local DevTools package with the selected workflow
interpreter:

```text
python -m pip install ./openbb_platform/extensions/devtools
```

Do not duplicate linter versions in the workflow or continue resolving an
unrelated latest PyPI aggregate. The package manifest remains the single source
of dependency policy. Keep third-party type stubs in the same installation step.

The workflow must verify the five required commands before running Codespell or
the changed-file lint suite. A missing executable then fails at setup with a
specific diagnostic rather than an opaque command-not-found failure.

## Acceptance

1. A regression test verifies that the workflow installs the local DevTools
   package through `python -m pip`.
2. The same test verifies that each invoked lint command is declared by the
   local package and that the workflow checks command availability.
3. The prior unpinned `pip install openbb-devtools` command is absent.
4. YAML/JSON validation and repository formatting checks pass.
5. The real GitHub `General Code Linting` job reaches and successfully runs its
   lint commands on a Python-changing PR.

This change repairs CI setup only. It does not weaken, skip or conditionally
ignore any linter.
