"""Shared-.env smoke test — canonical loader pattern for every dev-agent.

Bead: OpenBBTechnical-qy83.1.9 — Shared .env smoke test green from every
worktree.

Every engineer + Claude subagent working on Portfolio Intelligence Engine
runs this script as the *first thing* after cloning + venv setup:

    .venv_win/Scripts/python.exe scripts/pi_env_smoke.py

Non-zero exit = something is wrong with .env / venv / imports. Zero exit +
'ALL SMOKE CHECKS PASSED' = ready to start Lane A/B/C/D work.

The script deliberately makes NO changes and prints NO secret values.
Only the *shape* of the environment is verified — that variables are
set, that key packages import, that the sibling shared .env is readable.

See docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md Appendix A
for the design rationale (shared file at parent dir + override=False +
per-worktree local .env override pattern).
"""

# ruff: noqa: T201
# This is a CLI script whose output IS its interface — print() calls are
# deliberate, not diagnostic leftovers. Never converted to logging.

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path

# ----------------------------------------------------------------------------
# Configuration — the ONLY hardcoded path in the whole program.
# ----------------------------------------------------------------------------
SHARED_ENV_PATH = Path("H:/masterswork/git/.env")

# Variables the shared .env must supply. Values are NEVER printed —
# only the presence + non-emptiness is asserted.
REQUIRED_VARS: tuple[str, ...] = (
    "FMP_API_KEY",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)

# Packages that must import cleanly for Lane A/B/C work to proceed.
# Note: openbb_fmp_cached is intentionally NOT in this set at M0 because
# it currently fails to import due to a fork-wide provider mismatch
# (references openbb_fmp.models.aftermarket_trade which does not exist in
# openbb-fmp 1.6.1) — tracked separately in bead OpenBBTechnical-qy83.1.14.
# The smoke test will re-include it once that bead is fixed.
REQUIRED_IMPORTS: tuple[str, ...] = (
    "openbb_core.app.router",
    "pandas",
    "numpy",
    "sqlalchemy",
    "pytest",
    "dotenv",
)


# ----------------------------------------------------------------------------
# Individual checks — each returns (ok: bool, detail: str). Additive; run
# all so the operator sees every failure in one pass, not one-at-a-time.
# ----------------------------------------------------------------------------
def check_shared_env_file_exists() -> tuple[bool, str]:
    """Shared .env must live one directory above every fork checkout."""
    if not SHARED_ENV_PATH.is_file():
        return (
            False,
            f"missing shared .env at {SHARED_ENV_PATH} — see Execution "
            "Plan Appendix A for setup",
        )
    return True, f"found at {SHARED_ENV_PATH}"


def check_env_loader_pattern() -> tuple[bool, str]:
    """Verify the canonical loader pattern actually loads the file.

    Uses ``override=False`` per Appendix A §A.3 — shared file supplies
    defaults, an optional local ./.env can override any single variable
    without editing the shared file.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False, "python-dotenv not installed in this venv"
    load_dotenv(SHARED_ENV_PATH, override=False)
    # Also load any per-worktree override (see Appendix A §A.4).
    local = Path.cwd() / ".env"
    if local.is_file():
        load_dotenv(local, override=True)
        return True, "loaded shared + local override"
    return True, "loaded shared (no local override present)"


def check_required_vars_set() -> tuple[bool, str]:
    """Every REQUIRED_VARS entry must be non-empty after load.

    Values are NEVER printed — only presence is reported. Missing keys
    are reported by NAME so the operator knows what to add.
    """
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        return False, f"missing/empty env vars: {missing}"
    return True, f"all {len(REQUIRED_VARS)} required vars present"


def check_imports() -> tuple[bool, str]:
    """Every REQUIRED_IMPORTS must succeed under this venv."""
    failed: list[str] = []
    for mod in REQUIRED_IMPORTS:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            failed.append(f"{mod} ({exc.msg})")
    if failed:
        return False, f"failed imports: {failed}"
    return True, f"all {len(REQUIRED_IMPORTS)} imports ok"


def check_running_under_venv() -> tuple[bool, str]:
    """Warn if system Python is invoked instead of .venv_win/python.

    CLAUDE.md is unambiguous: never use system Python. This is a
    frequent, silent, painful failure mode — global Python's packages
    are almost always the wrong version.
    """
    prefix = Path(sys.prefix)
    is_venv = prefix.name.startswith(".venv") or "venv" in prefix.parts
    if not is_venv:
        return (
            False,
            f"running under {prefix} — expected .venv_win/. "
            "Activate the venv or invoke .venv_win/Scripts/python.exe.",
        )
    return True, f"under venv at {prefix}"


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------
CHECKS: tuple[tuple[str, Callable[[], tuple[bool, str]]], ...] = (
    ("shared .env file exists", check_shared_env_file_exists),
    ("env loader pattern works", check_env_loader_pattern),
    ("required env vars set (values NOT printed)", check_required_vars_set),
    ("required packages import cleanly", check_imports),
    ("running under venv (not system python)", check_running_under_venv),
)


def main() -> int:
    """Run every check; return 0 on all-pass, 1 otherwise."""
    print("=" * 70)
    print("Portfolio Intelligence Engine — env smoke test (bd qy83.1.9)")
    print("=" * 70)
    failures = 0
    for label, fn in CHECKS:
        ok, detail = fn()
        marker = "OK  " if ok else "FAIL"
        print(f"  [{marker}] {label}: {detail}")
        if not ok:
            failures += 1
    print("-" * 70)
    if failures:
        print(f"FAILED {failures}/{len(CHECKS)} — see Execution Plan Appendix A")
        return 1
    print(f"ALL SMOKE CHECKS PASSED ({len(CHECKS)}/{len(CHECKS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
