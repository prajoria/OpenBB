"""Regression tests for ``openbb_fmp_cached`` module import ordering.

Bead: OpenBBTechnical-qy83.1.15.

Update from the initial framing: the bug IS real on some branches of this
fork (portfolio had ``FLATTENED_TABLES`` at line 5428 while 4 referenced
functions were defined at lines 5606-5695 — used-before-defined). ``develop``
had the correct ordering; PR #487 mirrors the develop version onto portfolio.

These tests guard the invariant so any future re-reorder that puts
``FLATTENED_TABLES`` above a ``create_*_table`` function it references is
caught at commit time, not at first import in some downstream venv.

Four complementary layers:

1. In-process import (fast, catches most cases)
2. Registry-populated invariant (guards against silent None-installation)
3. Specific-function invariant (regression for the exact original symptom)
4. Subprocess clean-venv simulation (bulletproof — matches the failure
   mode as an operator actually observes it: fresh venv, first import)
5. AST line-order invariant (matches the PR's stated intent: catches the
   *shape* of the bug — dict-referencing-later-function — even if
   subsequent imports somehow succeed)
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

# Path to the module under regression watch.
_CACHE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "openbb_fmp_cached"
    / "utils"
    / "cache_schema.py"
)


def test_openbb_fmp_cached_imports_cleanly_in_process() -> None:
    """``import openbb_fmp_cached`` must succeed in this process.

    Note: this test intentionally does NOT purge ``sys.modules`` first.
    An earlier version did (to guarantee "fresh import" semantics), but
    that mutation leaked into sibling test files whose fetcher class
    definitions had already captured references to
    ``openbb_fmp_cached.models.<X>.execute_query``. After the purge, those
    production references still pointed at the pre-purge module while
    ``patch("openbb_fmp_cached.models.<X>.execute_query")`` in later tests
    targeted the newly-imported module attribute — silently-non-triggered
    mocks and ~28 downstream test failures.

    The fresh-import guarantee is provided by
    :func:`test_openbb_fmp_cached_imports_cleanly_in_subprocess` below,
    which is bulletproof (a real fresh interpreter) and cannot pollute
    the parent test session.
    """
    try:
        importlib.import_module("openbb_fmp_cached")
    except NameError as exc:
        pytest.fail(
            f"openbb_fmp_cached failed to import (used-before-defined "
            f"in cache_schema.py?): {exc}"
        )


def test_openbb_fmp_cached_imports_cleanly_in_subprocess() -> None:
    """``import openbb_fmp_cached`` must succeed in a fresh Python subprocess.

    PR #484 review finding 1: even purging ``sys.modules`` in-process can
    leave transitive dependencies cached (e.g. an ``openbb_core.provider``
    entry that eagerly touched fmp_cached and shadows the used-before-
    defined error). A subprocess is the only way to genuinely simulate
    the "fresh venv, first import" state that an operator hits after
    ``pip install``. Runs the interpreter with ``-c "import
    openbb_fmp_cached"`` and asserts exit 0 + no NameError in stderr.
    """
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import openbb_fmp_cached"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "fresh-subprocess import of openbb_fmp_cached failed "
        f"(exit {result.returncode}):\n{result.stderr[:2000]}"
    )
    assert (
        "NameError" not in result.stderr
    ), f"fresh-subprocess import surfaced a NameError:\n{result.stderr[:2000]}"


def test_flattened_tables_registry_is_populated() -> None:
    """``FLATTENED_TABLES`` must be a non-empty dict of callables.

    Guards against silent ``None``-installation (which a partial
    module-init pattern could produce) even though the current bug shape
    raises ``NameError`` outright.
    """
    from openbb_fmp_cached.utils.cache_schema import FLATTENED_TABLES

    assert isinstance(FLATTENED_TABLES, dict), "FLATTENED_TABLES must be a dict"
    assert FLATTENED_TABLES, "FLATTENED_TABLES must not be empty"
    for name, entry in FLATTENED_TABLES.items():
        assert isinstance(entry, dict), f"{name}: entry must be dict"
        assert "schema" in entry, f"{name}: entry missing 'schema' key"
        assert callable(entry["schema"]), (
            f"{name}: schema must be callable, got "
            f"{type(entry['schema']).__name__} (if None, a create_*_table "
            "function is being used before defined)"
        )


def test_aftermarket_quote_table_specifically() -> None:
    """The specific function that was reported broken in qy83.1.15."""
    from openbb_fmp_cached.utils.cache_schema import (
        FLATTENED_TABLES,
        create_aftermarket_quote_table,
    )

    assert callable(create_aftermarket_quote_table)
    assert "aftermarket_quote" in FLATTENED_TABLES
    assert (
        FLATTENED_TABLES["aftermarket_quote"]["schema"]
        is create_aftermarket_quote_table
    )


def test_flattened_tables_declared_after_all_referenced_functions() -> None:
    """AST line-order invariant matching the PR's stated intent.

    PR #484 review finding 4: the previous tests catch the bug's runtime
    *effect* (import failure) but not its structural *cause* (a
    module-level dict referencing a function whose ``def`` line-number
    is greater than the dict's assignment line-number). This test parses
    ``cache_schema.py`` and asserts every ``create_*_table`` name used
    as a value inside ``FLATTENED_TABLES`` is defined *earlier* in the
    file than the dict itself.

    Rejects the exact shape of the bug even if the module happens to
    import successfully by some transitive-order coincidence.
    """
    tree = ast.parse(_CACHE_SCHEMA_PATH.read_text(encoding="utf-8"))

    # Find the FLATTENED_TABLES = {...} assignment and every name it
    # references as a schema= value.
    dict_lineno: int | None = None
    referenced: dict[str, int] = {}  # name -> lineno-of-reference
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "FLATTENED_TABLES"
            and isinstance(node.value, ast.Dict)
        ):
            dict_lineno = node.lineno
            for val in node.value.values:
                # Value is a dict {"schema": create_..._table}. Walk it
                # for every Name reference (the create_*_table symbol).
                if isinstance(val, ast.Dict):
                    for v in val.values:
                        if isinstance(v, ast.Name) and v.id.startswith("create_"):
                            referenced.setdefault(v.id, v.lineno)
            break

    assert dict_lineno is not None, (
        "could not locate `FLATTENED_TABLES = {...}` assignment in "
        f"{_CACHE_SCHEMA_PATH}"
    )
    assert referenced, "FLATTENED_TABLES appears empty — nothing to check?"

    # Build a map of every top-level `def create_*_table` -> lineno.
    def_linenos: dict[str, int] = {
        node.name: node.lineno
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("create_")
    }

    offenders: list[str] = []
    for name in referenced:
        def_line = def_linenos.get(name)
        if def_line is None:
            offenders.append(f"{name}: no top-level `def` found")
        elif def_line > dict_lineno:
            offenders.append(
                f"{name}: def at line {def_line} but referenced by "
                f"FLATTENED_TABLES at line {dict_lineno} — "
                "used-before-defined"
            )

    assert not offenders, (
        "cache_schema.py has function/dict order violations (bd qy83.1.15):\n  "
        + "\n  ".join(offenders)
    )
