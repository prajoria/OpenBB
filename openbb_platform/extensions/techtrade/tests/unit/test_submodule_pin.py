"""Submodule-pin drift guard for the vendored pandas-ta-classic fork (#71, PRD §19).

Fails CI if the ``external/pandas-ta-classic`` pin drifts from the reviewed,
recorded commit. The recorded pin is asserted against (a) the techtrade README,
(b) the superproject gitlink (``git ls-tree HEAD`` -- needs no submodule fetch),
and (c) the live submodule HEAD when its working tree is populated. Git-based
checks skip cleanly when git / the work tree is unavailable (e.g. installed sdist),
so the suite stays runnable everywhere while still failing CI on real drift.

Bumping the submodule must update ``EXPECTED_PIN`` here and the README in the same
reviewed PR -- that is the §19 pin discipline, enforced by this test.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

EXPECTED_PIN = "cfda99036ba64a4983e5871d42d1865743b7c6a9"
_SUBMODULE_REL = "openbb_platform/extensions/techtrade/external/pandas-ta-classic"
_EXT_ROOT = Path(__file__).resolve().parents[2]  # .../extensions/techtrade
_README = _EXT_ROOT / "README.md"


def _repo_root() -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=_EXT_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return Path(out.stdout.strip())


def test_readme_documents_expected_pin():
    text = _README.read_text(encoding="utf-8")
    shas = set(re.findall(r"\b[0-9a-f]{40}\b", text))
    assert EXPECTED_PIN in shas, f"README must document submodule pin {EXPECTED_PIN}"


def test_superproject_gitlink_matches_expected_pin():
    root = _repo_root()
    if root is None:
        pytest.skip("git unavailable / not a work tree")
    out = subprocess.run(
        ["git", "ls-tree", "HEAD", _SUBMODULE_REL],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    line = out.stdout.strip()
    if not line:
        pytest.skip("submodule gitlink not present in this tree")
    # Format: "160000 commit <sha>\t<path>"
    recorded = line.split()[2]
    assert recorded == EXPECTED_PIN


def test_live_submodule_head_matches_expected_pin():
    sub = _EXT_ROOT / "external" / "pandas-ta-classic"
    if not (sub / ".git").exists():
        pytest.skip("submodule working tree not populated")
    out = subprocess.run(
        ["git", "-C", str(sub), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert out.stdout.strip() == EXPECTED_PIN
