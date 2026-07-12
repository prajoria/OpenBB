"""Regression test: openbb_fmp_cached must be importable in a clean venv.

Bead: OpenBBTechnical-qy83.1.15 (originally filed as "cache_schema.py used-
before-defined NameError").

Investigation revealed the actual root cause was NOT a code bug in the current
source — the source has ``create_aftermarket_quote_table`` defined at line
5463 and ``FLATTENED_TABLES`` (which references it) at line 5555, so the
order is correct.

The observed ``NameError`` was from a **stale wheel** in site-packages,
installed by an earlier ``dev_install.py -e`` run that captured an older
snapshot of the source (where the dict came BEFORE the function). Force-
reinstall from repo source (``pip install -e ... --force-reinstall --no-deps``)
resolves the import cleanly.

This test asserts the current source is import-clean so that if anyone
DOES rearrange the file such that ``FLATTENED_TABLES`` moves above a
``create_*_table`` function it references, CI catches it here at commit
time rather than at first import in some future venv.
"""

from __future__ import annotations

import importlib

import pytest


def test_openbb_fmp_cached_imports_cleanly() -> None:
    """`import openbb_fmp_cached` must succeed under a clean venv.

    Historically failed with:
        NameError: name 'create_aftermarket_quote_table' is not defined
    when ``FLATTENED_TABLES`` was declared above the functions it referenced.
    Guards against any reintroduction of that ordering.
    """
    # Force a fresh import to catch any module-level regressions.
    for mod in list(importlib.sys.modules):
        if mod.startswith("openbb_fmp_cached"):
            del importlib.sys.modules[mod]

    try:
        importlib.import_module("openbb_fmp_cached")
    except NameError as exc:
        pytest.fail(
            f"openbb_fmp_cached failed to import (used-before-defined "
            f"in cache_schema.py?): {exc}"
        )


def test_flattened_tables_registry_is_populated() -> None:
    """FLATTENED_TABLES must be a non-empty dict of callables.

    Direct assertion on the target of the qy83.1.15 investigation: the
    dict must exist, every value must have a callable ``schema`` (the
    used-before-defined bug would either raise NameError at import OR
    silently install a `None` reference — this catches both).
    """
    from openbb_fmp_cached.utils.cache_schema import FLATTENED_TABLES

    assert isinstance(FLATTENED_TABLES, dict), "FLATTENED_TABLES must be a dict"
    assert FLATTENED_TABLES, "FLATTENED_TABLES must not be empty"
    for name, entry in FLATTENED_TABLES.items():
        assert isinstance(entry, dict), f"{name}: entry must be dict"
        assert "schema" in entry, f"{name}: entry missing 'schema' key"
        assert callable(entry["schema"]), (
            f"{name}: schema must be callable, got {type(entry['schema']).__name__} "
            "(if None, a create_*_table function is being used before defined)"
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
