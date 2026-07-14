"""E0 grep-gate regression tests (bd-dt1, task E0.7).

These tests permanently codify the Phase 2A completion criteria from
`docs/superpowers/specs/2026-07-06-pine-extraction-to-pynecore-design.md`
§6.E0 verification:

1. **Zero cross-boundary imports.** Pynecore-side surfaces (the
   compiler and the runtime-core primitives listed in the spec) MUST
   NOT import from fork-side surfaces (attribution, telemetry,
   routers, mcp_tools, _coverage_manifest, cli, or the runtime
   provider glue: fmp_provider, byo_provider, fmp_retry,
   provider_selection). A hit here means E0.1-E0.5 have regressed and
   Phase 2B's `git filter-repo` would drag fork-only code into
   pynecore.

2. **E0.6 test-split manifest still reflects reality.** The MOVE/STAY
   classification in `docs/superpowers/plans/e06-test-split-manifest.md`
   is the ground truth for the E2 filter-repo path list. If a new
   test file was added without updating the manifest, or if a test
   changed its import surface, this test fails so the drift gets
   fixed before Phase 2B runs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Repository root: this file is at
# openbb_platform/extensions/pine/openbb_pine/tests/unit/test_e0_grep_gate.py
_REPO_ROOT = Path(__file__).resolve().parents[6]

# The pynecore-side surfaces (compiler + runtime-core primitives) that
# MUST stay free of fork-side imports. Kept in sync with spec §6.E0.
_PYNECORE_SIDE_PATHS = [
    "openbb_platform/extensions/pine/openbb_pine/compiler/",
    "openbb_platform/extensions/pine/openbb_pine/runtime/executor_core.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/security_dispatcher.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/secondary_cache.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/security_hook.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/strategy_types.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/restricted.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/limits.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/_pynecore_glue.py",
    "openbb_platform/extensions/pine/openbb_pine/runtime/pynecore_bridge.py",
    "openbb_platform/extensions/pine/openbb_pine/compiler_errors.py",
]

# Forbidden import pattern. Must match the pre-merge grep-gate in
# spec §6.E0 verification exactly.
_FORBIDDEN_IMPORT_RE = (
    r"from openbb_pine\.(attribution|telemetry|routers|mcp_tools|"
    r"_coverage_manifest|cli)\.|"
    r"from openbb_pine\.runtime\.(fmp_provider|byo_provider|fmp_retry|"
    r"provider_selection)"
)


def test_e0_grep_gate_no_cross_boundary_imports() -> None:
    """Pynecore-side surfaces MUST NOT import from fork-side surfaces.

    This is the pre-merge gate from spec §6.E0 verification. A hit
    here means one of the E0.1-E0.5 refactors has regressed and would
    contaminate pyne_compiler after Phase 2B's filter-repo.
    """
    pattern = re.compile(_FORBIDDEN_IMPORT_RE)
    hits: list[str] = []

    for rel in _PYNECORE_SIDE_PATHS:
        target = _REPO_ROOT / rel
        if not target.exists():
            # A missing target is itself a regression — E0 named it.
            hits.append(f"MISSING: {rel}")
            continue
        files = (
            list(target.rglob("*.py")) if target.is_dir() else [target]
        )
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError as exc:  # pragma: no cover
                hits.append(f"UNREADABLE: {f}: {exc}")
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(
                        f"{f.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}"
                    )

    assert not hits, (
        "E0 grep-gate FAILED: pynecore-side code imports fork-side "
        "surfaces. Phase 2B filter-repo would contaminate pyne_compiler. "
        "Fix by moving the dependency behind an injection seam "
        "(see spec §6.E0.1-E0.5). Violations:\n  - "
        + "\n  - ".join(hits)
    )


# ---- Manifest MOVE/STAY validation ---------------------------------------

_MANIFEST_PATH = (
    _REPO_ROOT / "docs" / "superpowers" / "plans" / "e06-test-split-manifest.md"
)
_UNIT_TESTS_DIR = (
    _REPO_ROOT
    / "openbb_platform"
    / "extensions"
    / "pine"
    / "openbb_pine"
    / "tests"
    / "unit"
)

# Ground-truth counts from the manifest header.
_EXPECTED_MOVE = 24
_EXPECTED_STAY = 64
_EXPECTED_TOTAL = 88  # 88 test_*.py files (excludes E0.7 infra); +1 vs
# post-E3.5 baseline for test_executor_strategy_branch.py (bd-liz —
# executor_shell strategy branch; STAYS with the shell)

# Fork-side surfaces: any test importing these STAYS. Mirrors the
# classification grep documented in the manifest, but restricted to
# real ``import`` / ``from ... import`` statements so string literals
# and comments (which the E0.6 refactor left in refactored files as
# banned-token assertions or docstrings) don't false-positive.
_FORK_SIDE_MODULE_RE = (
    r"openbb_pine\.(?:attribution|telemetry|routers|mcp_tools|"
    r"_coverage_manifest|cli|_load_bundled_widgets|about|diagnostics|"
    r"stdlib)|"
    r"openbb_pine\.runtime\.(?:fmp_provider|byo_provider|fmp_retry|"
    r"provider_selection)|"
    r"openbb_core"
)
_FORK_SIDE_IMPORT_RE = re.compile(
    rf"^\s*(?:from\s+(?:{_FORK_SIDE_MODULE_RE})"
    rf"|import\s+(?:{_FORK_SIDE_MODULE_RE}))",
    re.MULTILINE,
)

# Files not covered by the manifest that are E0.7 infrastructure and
# do not participate in the E2 MOVE/STAY partition.
_MANIFEST_EXEMPT = frozenset({"test_e0_grep_gate.py"})

# STAYs whose fork-side coupling is not visible via ``from`` imports:
# they AST-walk fork sources or assert on banned string literals. The
# manifest classifies them STAY by fiat; the import-based classifier
# below would call them MOVE, so we override.
_MANIFEST_STAY_BY_FIAT = frozenset({
    "test_prefetch_security.py",         # asserts banned FMP-provider strings
    "test_router_command_bare_obbject.py",  # AST-walks fork routers
    # E3.4: after import rewrite these still-STAY tests exercise the openbb_pine
    # deprecation shims (diagnostics/telemetry live in openbb_pine as re-exports
    # from pyne_compiler.*, so the import-based classifier now sees them as MOVE).
    "test_diagnostics.py",
    "test_telemetry_injection.py",
    "test_telemetry_module_globals.py",
    # E3.5: this file explicitly imports the fork-side deprecation shims
    # (openbb_pine.compiler.*, openbb_pine.compiler_errors, etc.) to
    # verify they emit DeprecationWarning + preserve identity. Import
    # classifier calls it MOVE (shim targets are pyne_compiler.*); by
    # intent it STAYS with the shims until v0.next+1.
    "test_deprecation_shims.py",
    # bd-liz: the strategy branch lives in executor_shell (fork-side —
    # OBBject wrapper, POWERED_BY_FULL attribution), but the test
    # imports only ``openbb_pine.runtime.executor_shell`` +
    # ``openbb_pine.errors``, neither of which is in the FORK_SIDE
    # regex (executor_shell is fork-side by module location, not by
    # import surface). Classifier calls it MOVE; by intent it STAYS
    # with the shell.
    "test_executor_strategy_branch.py",
})


def _extract_e2_move_list() -> list[str]:
    """Parse the E2 filter-repo MOVE list at the tail of the manifest."""
    text = _MANIFEST_PATH.read_text(encoding="utf-8")
    # Grab lines that look like the E2 path list.
    prefix = "openbb_platform/extensions/pine/openbb_pine/tests/unit/"
    return sorted(
        {
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith(prefix)
            and line.strip().endswith(".py")
        }
    )


def _classify_test_file(path: Path) -> str:
    """Return 'STAY' if file imports a fork-side surface, else 'MOVE'."""
    text = path.read_text(encoding="utf-8")
    return "STAY" if _FORK_SIDE_IMPORT_RE.search(text) else "MOVE"


def test_e06_manifest_counts_match_disk() -> None:
    """Manifest header counts must match the actual test files on disk."""
    all_tests = sorted(
        p.name
        for p in _UNIT_TESTS_DIR.glob("test_*.py")
        if p.name not in _MANIFEST_EXEMPT
    )
    assert len(all_tests) == _EXPECTED_TOTAL, (
        f"E0.6 manifest drift: disk has {len(all_tests)} test files "
        f"(excluding E0.7 infra), manifest says {_EXPECTED_TOTAL}. "
        "Update docs/superpowers/plans/e06-test-split-manifest.md."
    )

    move_list = _extract_e2_move_list()
    assert len(move_list) == _EXPECTED_MOVE, (
        f"E0.6 manifest drift: E2 filter-repo list has {len(move_list)} "
        f"entries, manifest header says MOVE={_EXPECTED_MOVE}."
    )

    stay_count = _EXPECTED_TOTAL - len(move_list)
    assert stay_count == _EXPECTED_STAY, (
        f"E0.6 manifest drift: STAY = TOTAL - MOVE = "
        f"{_EXPECTED_TOTAL} - {len(move_list)} = {stay_count}, "
        f"manifest header says STAY={_EXPECTED_STAY}."
    )


def test_e06_manifest_classification_matches_imports() -> None:
    """Every MOVE file must actually be pynecore-side-only per its imports.

    Every STAY file must actually import a fork-side surface. If a
    test file was added or its imports changed such that the
    classification no longer holds, the manifest (and E2's filter-repo
    path list) must be updated before Phase 2B runs.
    """
    move_list = _extract_e2_move_list()
    move_names = {p.rsplit("/", 1)[-1] for p in move_list}

    disk_tests = sorted(
        p
        for p in _UNIT_TESTS_DIR.glob("test_*.py")
        if p.name not in _MANIFEST_EXEMPT
    )
    misclassified: list[str] = []

    for path in disk_tests:
        actual = _classify_test_file(path)
        if path.name in _MANIFEST_STAY_BY_FIAT:
            actual = "STAY"
        expected = "MOVE" if path.name in move_names else "STAY"
        if actual != expected:
            misclassified.append(
                f"{path.name}: manifest says {expected}, "
                f"imports say {actual}"
            )

    assert not misclassified, (
        "E0.6 manifest classification does not match test imports. "
        "Update docs/superpowers/plans/e06-test-split-manifest.md and "
        "the E2 filter-repo list before Phase 2B. Drift:\n  - "
        + "\n  - ".join(misclassified)
    )


def test_e0_grep_gate_matches_spec_command() -> None:
    """The regex in this test file matches the spec §6.E0 shell grep.

    Guards against silent drift between the shell gate (used
    pre-merge and in CI) and this Python regression test.
    """
    # This is the exact ERE from spec §6.E0 verification. If the spec
    # changes, update both places.
    spec_ere = (
        r"from openbb_pine\.(attribution|telemetry|routers|mcp_tools|"
        r"_coverage_manifest|cli)\.|from openbb_pine\.runtime\."
        r"(fmp_provider|byo_provider|fmp_retry|provider_selection)"
    )
    # Normalize whitespace/newlines in the test's copy for comparison.
    ours = _FORBIDDEN_IMPORT_RE.replace("\n", "").replace(" ", "")
    theirs = spec_ere.replace(" ", "")
    assert ours == theirs, (
        "E0 grep-gate regex drift: this test's regex no longer matches "
        f"the spec §6.E0 shell grep.\n  test: {ours}\n  spec: {theirs}"
    )


def test_e0_grep_gate_shell_command_available() -> None:
    """Smoke-test: `grep -rE ...` runs and returns zero hits.

    Runs the actual shell command from spec §6.E0 verification so the
    Python and shell paths can't diverge. Skips if grep isn't on PATH
    (e.g. minimal Windows environments), because the Python test above
    already covers the semantics.
    """
    import shutil

    if shutil.which("grep") is None:
        import pytest

        pytest.skip("grep not available on PATH")

    cmd = ["grep", "-rE", _FORBIDDEN_IMPORT_RE, *_PYNECORE_SIDE_PATHS]
    result = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # grep exits 0 on match (bad), 1 on no match (good), 2 on error.
    assert result.returncode == 1, (
        f"E0 grep-gate shell command failed unexpectedly "
        f"(exit={result.returncode}).\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stdout == "", (
        "E0 grep-gate shell command returned hits:\n" + result.stdout
    )
