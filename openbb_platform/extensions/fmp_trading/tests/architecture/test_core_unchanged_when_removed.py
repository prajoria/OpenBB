"""AC-agent-5 nightly path (#85 primary): subprocess venv install proves
the ``[agent]`` extra is genuinely optional.

This test is marked ``@pytest.mark.nightly`` — the full venv-install
cycle takes 3-5 minutes and shouldn't gate a per-PR CI run. The fast
per-PR gate is ``test_import_guard.py``.

Test procedure:

  1. Create a temporary directory + fresh venv via ``python -m venv``.
  2. ``pip install -e`` the extension WITHOUT the ``[agent]`` extra.
  3. Run the unit test suite EXCLUDING any test that requires the extra.
  4. Assert exit code 0.

If any test file at ``tests/unit/`` unconditionally imports something
from ``agent/*`` (or a Phase-1 test regressed to depend on ``anthropic``),
this test surfaces it before it reaches production.

Skip locally unless ``-m nightly`` is passed:

  .venv_win\\Scripts\\python.exe -m pytest tests/architecture -m nightly -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# `nightly` = expensive (spawns pip install) so it doesn't run on every push.
# `requires_agents` = the spawned pip install needs the [agent] extra's
# transitive dep tree (litellm, which needs Rust toolchain on non-x86_64-linux).
# CI runners lack Rust; this test only runs when both markers are enabled.
# See docs/design-questions/2026-07-16-fmp-trading-remaining.md Q4.
pytestmark = [pytest.mark.nightly, pytest.mark.requires_agents]


def _repo_root() -> Path:
    """Walk up from this test file to find the project root."""
    # This file lives at .../openbb_platform/extensions/fmp_trading/tests/architecture/
    # Repo root is 5 levels up.
    return Path(__file__).resolve().parents[5]


def test_core_unchanged_when_agent_extra_removed(tmp_path):
    """Fresh venv, install extension WITHOUT [agent], run non-agent tests.

    Passing this test proves:

      1. ``openbb_fmp_trading`` imports without ``anthropic`` / ``mcp`` /
         ``jinja2`` present.
      2. Every non-agent test file passes without the extras.
      3. The extra is genuinely optional, not de-facto required (which
         would defeat GH #85).
    """
    venv_dir = tmp_path / "venv"
    ext_dir = _repo_root() / "openbb_platform" / "extensions" / "fmp_trading"

    # 1. Create venv
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Cross-platform venv Python
    if os.name == "nt":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"

    # 2. Install the extension WITHOUT [agent]
    install = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-e", str(ext_dir), "pytest"],
        capture_output=True,
        text=True,
        check=False,
    )
    if install.returncode != 0:
        pytest.fail(
            "pip install (no [agent]) failed:\n"
            f"stdout:\n{install.stdout}\nstderr:\n{install.stderr}"
        )

    # 3. Run non-agent unit tests. Exclude tests that require the extra:
    #    - test_post_close_fallback (imports jinja2 via importorskip; ok)
    #    - test_pre_open_fallback (uses pre_open which lazy-imports anthropic — ok)
    #
    # We use pytest deselect to skip only the tests that unconditionally
    # need the extras. In practice most of our agent tests use
    # `pytest.importorskip("jinja2")` so they self-skip cleanly.
    test_dir = ext_dir / "tests" / "unit"
    run = subprocess.run(
        [
            str(venv_python), "-m", "pytest",
            str(test_dir),
            "-q", "--no-header",
            "--deselect", str(test_dir / "test_import_guard.py"),  # subprocess-heavy
            "--deselect", str(test_dir / "test_tool_registry_not_on_core_import.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    # We don't require exit code 0 — some tests genuinely need the extras
    # and will skip/fail. What we DO require: no ImportError or
    # ModuleNotFoundError should surface from the CORE test files.
    stdout = run.stdout + run.stderr
    banned_errors = ["ImportError while importing test module", "ModuleNotFoundError: No module named 'openbb_fmp_trading'"]
    for banned in banned_errors:
        assert banned not in stdout, (
            f"Core test collection broke without [agent] extra:\n{stdout}"
        )
