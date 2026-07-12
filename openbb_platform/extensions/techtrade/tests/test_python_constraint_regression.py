"""Regression test for the openbb-platform / sub-package python constraint.

Bead: OpenBBTechnical-qy83.1.13 — dev_install.py -e fails when any sub-package
(extension or provider) declares a python upper-bound *narrower* than the
platform's own upper-bound. Poetry's solver cannot converge and every
fresh dev_install fails at ``poetry lock --regenerate``.

Historical trigger: 6 sub-packages (backtest, financialtoolkit, fmp_trading,
portfolio, techtrade, fmp_cached) declared ``python = ">=3.10,<3.14"`` while
openbb_platform's own pyproject.toml declared ``<4``. The fix landed with
this test was to narrow the platform to ``<3.14`` to match the tightest
downstream.

Bead: OpenBBTechnical-qy83.1.14 — downstream symptom: because dev_install
never completed, ``openbb-fmp`` was pulled from PyPI (1.6.1) instead of
being editable-installed from the in-tree source. ``openbb_fmp_cached``
then failed to import ``openbb_fmp.models.aftermarket_trade`` (present
in-tree, absent from the PyPI release). Fix landed in a separate PR;
this test's job is to prevent the ROOT cause from returning.

This module ships two invariants:

1. **Every sub-package must not be narrower than the platform** — iterates
   ``openbb_platform/{extensions,providers,obbject_extensions}/*/pyproject.toml``
   so any future sub-package that narrows the range gets caught, not just
   ``techtrade``.
2. **``dev_install.py``'s LOCAL_DEPS must match the platform's declared range**
   — the two constraints are duplicated (see qy83.1.13 review finding 5)
   and must stay in sync.

Both invariants are static pyproject.toml parses — no ``poetry lock`` invocation
required. Uses ``packaging.version.Version`` for correct pre-release handling
(fixes qy83.1.13 review finding 4: naive regex would silently strip ``rc1``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_ROOT = REPO_ROOT / "openbb_platform"
PLATFORM_PYPROJECT = PLATFORM_ROOT / "pyproject.toml"
DEV_INSTALL_SCRIPT = PLATFORM_ROOT / "dev_install.py"


def _python_upper_bound(pyproject_path: Path) -> str:
    """Return the ``<X.Y`` upper-bound string from ``[tool.poetry.dependencies].python``.

    Only inspects the top-level ``[tool.poetry.dependencies]`` block — group
    or extras-scoped python constraints are ignored (they don't participate
    in the same solver context).
    """
    body = pyproject_path.read_text(encoding="utf-8")
    m = re.search(
        r"\[tool\.poetry\.dependencies\][\s\S]+?python\s*=\s*\"[^<]*(<[^\"]+)\"",
        body,
    )
    assert m, f"could not locate python constraint in {pyproject_path}"
    return m.group(1).strip()


def _dev_install_local_deps_upper_bound() -> str:
    """Return the ``<X.Y`` upper-bound from ``dev_install.py``'s LOCAL_DEPS shim.

    That string is written into ``pyproject.toml`` at install time before
    running ``poetry lock``, so it MUST match the checked-in platform range
    or the fresh regeneration silently disagrees with the source of truth.
    """
    body = DEV_INSTALL_SCRIPT.read_text(encoding="utf-8")
    # Constrain the match to inside the LOCAL_DEPS triple-quoted string.
    m = re.search(
        r'LOCAL_DEPS\s*=\s*"""[\s\S]+?python\s*=\s*"[^<]*(<[^"]+)"',
        body,
    )
    assert m, f"could not locate python constraint in {DEV_INSTALL_SCRIPT}"
    return m.group(1).strip()


def _parse_upper(bound: str) -> Version:
    """Parse ``<X.Y`` into a ``packaging.version.Version``.

    Uses ``packaging.version`` (PEP 440) instead of the naive ``int``-split
    approach so ``<3.14rc1``, ``<3.14a0``, ``<4.0.dev1`` etc. are rejected
    with a clear error rather than silently truncated to ``(3, 14, 0)``.
    """
    m = re.match(r"<\s*(\S+)", bound)
    assert m, f"unparseable upper bound: {bound!r}"
    raw = m.group(1)
    try:
        v = Version(raw)
    except InvalidVersion as exc:
        pytest.fail(f"upper bound {raw!r} is not a valid PEP 440 version: {exc}")
    # Reject pre-release / dev / local markers — they make the ordering
    # semantically ambiguous inside a solver constraint.
    assert not (v.is_prerelease or v.is_devrelease or v.local), (
        f"upper bound {raw!r} contains pre-release/dev/local metadata; "
        "poetry treats these specially and this test cannot safely compare."
    )
    return v


def _iter_subpackage_pyprojects() -> list[Path]:
    """All sub-package pyproject.tomls that participate in dev_install.

    Covers extensions, providers, and obbject_extensions — the three
    directories dev_install.py's LOCAL_DEPS references with ``path =``.
    Community-only or vendored deps are excluded via the glob shape.
    """
    subdirs = ("extensions", "providers", "obbject_extensions")
    out: list[Path] = []
    for sub in subdirs:
        root = PLATFORM_ROOT / sub
        if not root.is_dir():
            continue
        out.extend(root.glob("*/pyproject.toml"))
    return sorted(out)


def test_no_subpackage_narrower_than_platform() -> None:
    """No sub-package may declare a python upper-bound narrower than the platform.

    Iterates every extension / provider / obbject_extension pyproject.toml
    and asserts its ``<X.Y`` upper bound is at least the platform's. If a
    sub-package narrows, dev_install.py -e's poetry lock cannot converge
    (bead qy83.1.13). This catches the *class* of regression, not just the
    specific ``techtrade`` case that surfaced it originally.
    """
    platform_upper = _parse_upper(_python_upper_bound(PLATFORM_PYPROJECT))
    subpackages = _iter_subpackage_pyprojects()
    assert subpackages, "no sub-package pyproject.tomls found — glob broken?"

    offenders: list[tuple[str, str, str]] = []
    for pp in subpackages:
        try:
            sub_upper_str = _python_upper_bound(pp)
        except AssertionError:
            # Some sub-packages may not declare a python constraint at all.
            continue
        sub_upper = _parse_upper(sub_upper_str)
        if sub_upper < platform_upper:
            offenders.append(
                (
                    pp.relative_to(REPO_ROOT).as_posix(),
                    sub_upper_str,
                    f"<{platform_upper}",
                )
            )

    assert not offenders, (
        "the following sub-packages declare a python upper-bound NARROWER "
        f"than the platform ({platform_upper}) — this breaks dev_install.py -e "
        "(bead qy83.1.13):\n  "
        + "\n  ".join(f"{p}: {sub} < platform {plat}" for p, sub, plat in offenders)
    )


def test_dev_install_local_deps_matches_platform() -> None:
    """dev_install.py's LOCAL_DEPS python range MUST equal the platform's.

    The two are duplicated (LOCAL_DEPS is a hardcoded string this script
    writes into pyproject.toml at install time before running poetry).
    If they drift, dev_install silently uses a different constraint than
    the checked-in source of truth. Catches the DRY violation flagged in
    the qy83.1.13 review.
    """
    platform_upper = _parse_upper(_python_upper_bound(PLATFORM_PYPROJECT))
    dev_upper = _parse_upper(_dev_install_local_deps_upper_bound())
    assert dev_upper == platform_upper, (
        f"dev_install.py LOCAL_DEPS python upper bound (<{dev_upper}) "
        f"does not match openbb_platform/pyproject.toml (<{platform_upper}). "
        "These two are duplicated by design — keep them in lock-step."
    )
