"""CI guardrail: no application/extension code may call `provider="fmp"` directly.

The fmp_trading extension and all downstream consumers must always route
through fmp_cached to preserve the caching invariants and bandwidth budget
(PRD §5.4). Only the provider packages themselves, provider tests, and this
architecture test may reference the bare "fmp" provider string.

**Exemptions the regex handles automatically:**
- Lines that are string literals inside `PythonEx(code=[...])` doc blocks —
  those are OpenAPI example strings, not runtime code. Detected by the leading
  whitespace-then-double-quote pattern common to all such lines in the codebase.
- Lines carrying the marker comment `# provider-purity-exempt: <reason>` — used
  by tests that deliberately pass `provider="fmp"` to verify the "warn on wrong
  provider" branch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]  # openbb_platform/tests/architecture -> repo

# Directories that MAY reference provider="fmp" (provider impls + their own tests):
ALLOWED_SUBTREES: tuple[str, ...] = (
    "openbb_platform/providers/fmp/",
    "openbb_platform/providers/fmp_cached/",
    "openbb_platform/tests/architecture/",  # this test file itself
)

# Directories that must be scanned (extension code + shared app code):
SCAN_SUBTREES: tuple[str, ...] = (
    "openbb_platform/extensions/",
    "Analysis/",
    "cli/",
)

# Matches:  provider="fmp"   provider='fmp'   provider = "fmp"
PATTERN = re.compile(r"""provider\s*=\s*["']fmp["']""")

# A line is a docstring/PythonEx example if it starts (after whitespace) with `"`
# or `'` — the PythonEx `code=[...]` pattern wraps each line as a quoted string:
#   "stock_data = obb.equity.price.historical(..., provider='fmp')",
#   'stock_data = obb.equity.price.historical(..., provider="fmp")',
DOCSTRING_LINE = re.compile(r"""^\s*["']""")

# Explicit opt-out marker for tests that deliberately pass provider="fmp":
EXEMPT_MARKER = "provider-purity-exempt"


def _iter_py_files(subtree: str) -> list[Path]:
    root = REPO_ROOT / subtree
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if p.is_file()]


def _is_offender(line: str) -> bool:
    """A line is a real offender only if it (a) matches PATTERN, (b) is not a
    PythonEx docstring example, and (c) does not carry the exemption marker."""
    if not PATTERN.search(line):
        return False
    if DOCSTRING_LINE.match(line):
        return False
    if EXEMPT_MARKER in line:
        return False
    return True


@pytest.mark.parametrize("subtree", SCAN_SUBTREES)
def test_no_bare_fmp_provider_in_app_code(subtree: str) -> None:
    """Assert `provider="fmp"` never appears in extension/app code."""
    offenders: list[tuple[Path, int, str]] = []
    for path in _iter_py_files(subtree):
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if any(rel.startswith(a) for a in ALLOWED_SUBTREES):
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            if _is_offender(line):
                offenders.append((path, lineno, line.strip()))

    assert not offenders, (
        "Found `provider=\"fmp\"` in application/extension code; must use "
        '`provider="fmp_cached"` per PRD §5.4.\n'
        "If a specific line is a deliberate test of the wrong-provider branch, "
        f"add the comment `# {EXEMPT_MARKER}: <reason>` to that line.\n\n"
        "Offenders:\n"
        + "\n".join(f"  {p}:{ln}: {src}" for p, ln, src in offenders)
    )
