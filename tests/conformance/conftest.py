"""Conformance harness pytest fixtures (PRD section 7).

Auto-discovers ``(name.pine, name.csv)`` pairs under ``tests/conformance/``
and yields one parametrized test per pair. The discovery rules:

* For every ``*.pine`` file at any depth, look for a sibling ``*.csv``
  with the same stem.
* Filenames starting with ``_`` are reserved for harness self-tests
  (``_smoke.pine`` / ``_smoke.csv``) and are still included so the
  harness itself is exercised on every CI run. Per-builtin scripts
  should NOT start with ``_``.
* A ``*.pine`` with no sibling ``*.csv`` is a configuration error: we
  emit a pytest WARNING via :func:`pytest_collection_modifyitems` but
  do not fail collection (the missing-reference case is often a
  work-in-progress).

The test in :mod:`test_conformance_corpus` consumes the
``conformance_pair`` fixture: each test invocation receives a
``(pine_path, csv_path)`` tuple and runs the compiler-then-diff cycle
described in PRD section 7. When the compiler does not yet exist
(``openbb_pine.compiler`` not importable, Phase 1 in flight), the test
SKIPs cleanly; once the compiler lands the same fixtures start
asserting numerical equality at ``atol=1e-9, rtol=0`` per PRD section 7.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Iterable

import pytest

# The conformance dir is THIS file's parent. We resolve once so the
# pytest collection step has a stable, absolute root regardless of
# where pytest is invoked from.
CONFORMANCE_ROOT = Path(__file__).resolve().parent


def _discover_pairs(root: Path | None = None) -> list[tuple[Path, Path]]:
    """Walk ``root`` and return every ``(*.pine, *.csv)`` pair found.

    Pairs are sorted by ``.pine`` path so test ordering is stable across
    runs (important for ``pytest-xdist`` reproducibility and for human
    eyeballing of failure rosters).

    A ``.pine`` with no sibling ``.csv`` of the same stem is OMITTED from
    the returned list and surfaced via :func:`_warn_orphan_pines`.

    Parameters
    ----------
    root:
        The directory to walk. Defaults to :data:`CONFORMANCE_ROOT`.
        Exposed as a parameter so tests of the harness itself can point
        it at a temp dir.
    """
    base = root if root is not None else CONFORMANCE_ROOT
    pairs: list[tuple[Path, Path]] = []
    for pine_path in sorted(base.rglob("*.pine")):
        csv_path = pine_path.with_suffix(".csv")
        if csv_path.is_file():
            pairs.append((pine_path, csv_path))
    return pairs


def _orphan_pines(root: Path | None = None) -> list[Path]:
    """List ``.pine`` files with no matching ``.csv`` -- diagnostic only."""
    base = root if root is not None else CONFORMANCE_ROOT
    return [
        p for p in sorted(base.rglob("*.pine"))
        if not p.with_suffix(".csv").is_file()
    ]


def _warn_orphan_pines() -> None:
    """Emit a pytest WARNING per orphan ``.pine`` (no fail).

    A missing reference CSV is usually a work-in-progress -- failing
    collection would block unrelated work. The warning surfaces the
    backlog so it doesn't rot silently.
    """
    for orphan in _orphan_pines():
        warnings.warn(
            f"conformance: {orphan.relative_to(CONFORMANCE_ROOT)!s} has no "
            f"sibling .csv reference -- pair will be skipped from auto-discovery",
            UserWarning,
            stacklevel=2,
        )


def pytest_collection_modifyitems(config, items):
    """Emit orphan-pine warnings during collection (one-shot per session)."""
    _warn_orphan_pines()


def _pair_id(pair: tuple[Path, Path]) -> str:
    """Pytest parametrize id: the stem relative to CONFORMANCE_ROOT.

    ``tests/conformance/ta/sma.pine`` -> ``ta/sma``
    ``tests/conformance/_smoke.pine``  -> ``_smoke``
    """
    pine_path, _ = pair
    rel = pine_path.relative_to(CONFORMANCE_ROOT).with_suffix("")
    return rel.as_posix()


# Compute pairs ONCE at module import. Using a module-level constant
# rather than a fixture factory means pytest's parametrize id list is
# stable for an entire collection cycle (matters for ``--lf`` /
# ``--cache-show`` to point at the right failed pair across runs).
_DISCOVERED_PAIRS: list[tuple[Path, Path]] = _discover_pairs()


@pytest.fixture(
    params=_DISCOVERED_PAIRS,
    ids=[_pair_id(p) for p in _DISCOVERED_PAIRS],
)
def conformance_pair(request) -> tuple[Path, Path]:
    """Yield one ``(pine_path, csv_path)`` pair per discovered fixture.

    Skipped gracefully if no pairs exist at all (the very-first commit
    of the harness, before any builtin has its first fixture).
    """
    if not _DISCOVERED_PAIRS:
        pytest.skip(
            f"no (.pine, .csv) pairs under {CONFORMANCE_ROOT} -- "
            "add fixtures alongside builtin implementations"
        )
    return request.param


# Re-export the discovery helpers so test_conformance_corpus can import
# them and so external tooling (e.g. CI reporters) can list pairs
# without re-walking the tree.
__all__ = [
    "CONFORMANCE_ROOT",
    "_discover_pairs",
    "_orphan_pines",
    "_pair_id",
    "conformance_pair",
]
