"""Meta-tests for the env smoke script."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SMOKE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pi_env_smoke.py"


def test_smoke_script_exists() -> None:
    """Script must be on disk under scripts/."""
    assert SMOKE_SCRIPT.is_file(), f"missing smoke script: {SMOKE_SCRIPT}"


def test_smoke_script_never_prints_secret_values() -> None:
    """Static scan: script MUST NOT print env var VALUES.

    Grep for banned patterns like `print(os.environ[...` or
    `print(FMP_API_KEY)`. Presence-only reporting is fine.
    """
    body = SMOKE_SCRIPT.read_text(encoding="utf-8")
    banned = [
        r"print\([^)]*os\.environ\[",
        r"print\([^)]*os\.environ\.get\([^)]*\)\s*\)",  # bare value print
        r"print\([^)]*FMP_API_KEY[^)]*\)",  # explicit key print
        r"print\([^)]*MYSQL_PASSWORD[^)]*\)",
    ]
    for pat in banned:
        assert not re.search(
            pat, body
        ), f"smoke script must not print env values (matched pattern: {pat})"


def test_smoke_script_documents_bead_and_appendix() -> None:
    """Docstring must cite the bead + Execution Plan Appendix A."""
    body = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "qy83.1.9" in body, "smoke script must cite bead qy83.1.9"
    assert "Appendix A" in body, "smoke script must reference Exec Plan Appendix A"


def test_smoke_script_runs_and_reports_status() -> None:
    """End-to-end: run the script and confirm it emits status lines.

    We do NOT assert exit code = 0 because the CI env may not have the
    shared .env file (that is expected). We DO assert the script runs
    without raising a Python exception, emits per-check status lines,
    and prints a final summary — the contract for the operator UX.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SMOKE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    # Script must exit cleanly (0 or 1) — never crash with a traceback.
    assert result.returncode in (0, 1), (
        f"smoke script crashed with exit {result.returncode}\n"
        f"stderr: {result.stderr[:500]}"
    )
    assert "Portfolio Intelligence Engine" in result.stdout
    assert re.search(
        r"\[(OK|FAIL)\s*\]", result.stdout
    ), "smoke script must emit per-check status lines"
    assert (
        "ALL SMOKE CHECKS PASSED" in result.stdout or "FAILED" in result.stdout
    ), "smoke script must emit a final summary line"
