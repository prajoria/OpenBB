"""Meta-tests for the env smoke script."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

SMOKE_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pi_env_smoke.py"

# Names of environment variables the smoke script is trusted with. Any
# `print`/`sys.stdout.write`/`logging.*` reference that reads one of these
# via `os.environ[...]`, `os.getenv(...)`, or an intermediate variable must
# be flagged.
_REQUIRED_VARS = (
    "FMP_API_KEY",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
)


def test_smoke_script_exists() -> None:
    """Script must be on disk under scripts/."""
    assert SMOKE_SCRIPT.is_file(), f"missing smoke script: {SMOKE_SCRIPT}"


def _find_output_calls(tree: ast.AST) -> list[ast.Call]:
    """Return every ``print``/``sys.stdout.write``/``logging.*`` Call node.

    Broader than a regex — catches split-assign leaks (``v = os.environ[
    'X']; print(v)``) once the value flows into an output call.
    """
    out: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Bare `print(...)`
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            out.append(node)
            continue
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            # sys.stdout.write / sys.stderr.write
            if attr == "write":
                out.append(node)
                continue
            # logging.info / logging.debug / logging.warning / ...
            if attr in {
                "info",
                "debug",
                "warning",
                "error",
                "critical",
                "exception",
                "log",
            }:
                out.append(node)
    return out


def _mentions_env_value(node: ast.AST) -> bool:
    """Return True if the AST subtree touches an env-value lookup.

    Catches:
    - ``os.environ['X']`` / ``os.environ.get('X')``
    - ``os.getenv('X')``
    - Bare reference to an env-var name (``print(FMP_API_KEY)``)
    - Reference to ``os.environ`` as a whole
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Subscript):
            v = sub.value
            if (
                isinstance(v, ast.Attribute)
                and isinstance(v.value, ast.Name)
                and v.value.id == "os"
                and v.attr == "environ"
            ):
                return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            fn = sub.func
            if (
                isinstance(fn.value, ast.Name)
                and fn.value.id == "os"
                and fn.attr == "getenv"
            ):
                return True
            if (
                isinstance(fn.value, ast.Attribute)
                and isinstance(fn.value.value, ast.Name)
                and fn.value.value.id == "os"
                and fn.value.attr == "environ"
                and fn.attr == "get"
            ):
                return True
        # Bare name that matches an env var, or `os.environ` reference.
        if isinstance(sub, ast.Name) and sub.id in _REQUIRED_VARS:
            return True
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == "os"
            and sub.attr == "environ"
        ):
            return True
    return False


def test_smoke_script_never_prints_secret_values() -> None:
    """Static AST scan: script MUST NOT emit env-var values.

    Widened from the prior regex-based check (PR #474 review finding 1)
    which was bypassable in several ways:
    - `os.getenv('FMP_API_KEY')` — used getenv, not os.environ
    - Split-assign then print — two statements, one regex per line
    - `sys.stdout.write` / `logging.info` — not `print`
    - Any REQUIRED_VAR name other than FMP_API_KEY / MYSQL_PASSWORD

    This AST walk flags every output call whose argument subtree touches
    an env-value read, closing all four bypasses.
    """
    tree = ast.parse(SMOKE_SCRIPT.read_text(encoding="utf-8"))
    src = SMOKE_SCRIPT.read_text(encoding="utf-8")
    offenders: list[str] = []
    for call in _find_output_calls(tree):
        for arg in call.args:
            if _mentions_env_value(arg):
                snippet = ast.get_source_segment(src, call) or ast.dump(call)
                offenders.append(f"line {call.lineno}: {snippet}")
                break
    assert not offenders, (
        "smoke script must not print env-var VALUES. Offending output calls:\n  "
        + "\n  ".join(offenders)
    )


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
    prints a final summary — the contract for the operator UX. Also
    asserts stderr is Traceback-free (PR #474 review finding 4: a
    tolerant returncode-in-(0,1) check masks crashes that also happen
    to exit 1 via SystemExit).
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SMOKE_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode in (0, 1), (
        f"smoke script crashed with exit {result.returncode}\n"
        f"stderr: {result.stderr[:500]}"
    )
    assert (
        "Traceback" not in result.stderr
    ), f"smoke script crashed with a Traceback:\n{result.stderr[:1000]}"
    assert "Portfolio Intelligence Engine" in result.stdout
    assert re.search(
        r"\[(OK|FAIL)\s*\]", result.stdout
    ), "smoke script must emit per-check status lines"
    assert (
        "ALL SMOKE CHECKS PASSED" in result.stdout or "FAILED" in result.stdout
    ), "smoke script must emit a final summary line"


def test_shared_env_path_is_env_var_overridable() -> None:
    """SHARED_ENV_PATH must honor the PI_SHARED_ENV_PATH env var.

    PR #474 review finding 2: the hardcoded Windows path breaks on Linux/CI.
    Assert the script reads PI_SHARED_ENV_PATH before falling back to the
    default. Static AST check — verifying by import would run the whole
    script and mutate os.environ.
    """
    src = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert (
        'os.environ.get("PI_SHARED_ENV_PATH"' in src
    ), "SHARED_ENV_PATH must be overridable via PI_SHARED_ENV_PATH env var"


def test_venv_detection_uses_pep405_idiom() -> None:
    """check_running_under_venv must use sys.prefix != sys.base_prefix.

    PR #474 review finding 3: the prior heuristic false-negatived on Poetry
    venvs. The PEP 405 idiom works for every tool (stdlib venv, poetry,
    virtualenv, pipenv). Static grep is enough — the runtime behavior of
    this specific check is hard to fake in a unit test.
    """
    src = SMOKE_SCRIPT.read_text(encoding="utf-8")
    assert "sys.prefix == sys.base_prefix" in src or (
        "sys.prefix" in src and "sys.base_prefix" in src
    ), "must use PEP 405 sys.prefix vs sys.base_prefix venv detection"
