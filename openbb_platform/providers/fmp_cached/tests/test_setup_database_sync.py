"""Regression test for #775 — setup_database.create_cache_tables must be sync.

Before the fix, create_cache_tables was declared `async def` and used
`await` on `init_database()` and `create_all_tables()` — but both of
those are synchronous functions returning bool / dict. Calling
create_cache_tables therefore raised:

    TypeError: object bool can't be used in 'await' expression

This test imports setup_database, invokes create_cache_tables with the
underlying init_database / create_all_tables mocked (so no live MySQL
is needed), and asserts the call completes without raising.

Mutation-verified per CLAUDE.md R7.11: reverting the fix (restoring
`async def` + `await`) makes this test fail with the exact TypeError.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SETUP_SCRIPT = (
    Path(__file__).resolve().parent.parent / "setup_database.py"
)


def _load_setup_database_module():
    """Load setup_database.py by absolute path.

    It's a script (not part of the openbb_fmp_cached package), so we
    have to load it via importlib rather than a normal `import`.
    load_db_config() runs at module scope and reads user_settings.json,
    so this test implicitly requires that file to be present with valid
    MySQL credentials (same as every other fmp_cached test).
    """
    spec = importlib.util.spec_from_file_location(
        "fmp_cached_setup_database", str(SETUP_SCRIPT)
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_create_cache_tables_is_synchronous():
    """create_cache_tables must be a regular def, not async def.

    The bug that #775 fixed was `async def create_cache_tables` calling
    `await init_database()` on a sync function. Making the function
    sync is the fix; asserting `not iscoroutinefunction` is the
    R7.11-discriminating check that would fail on the reverted code.
    """
    mod = _load_setup_database_module()
    assert not inspect.iscoroutinefunction(mod.create_cache_tables), (
        "create_cache_tables must be a regular sync def, not async — "
        "init_database and create_all_tables are both sync. "
        "See #775."
    )


def test_create_cache_tables_returns_true_when_underlying_calls_succeed():
    """End-to-end sanity: with the DB layer mocked to succeed,
    create_cache_tables returns True (and does NOT raise TypeError).

    This is the load-bearing scenario: pre-fix, the function raised
    `TypeError: object bool can't be used in 'await' expression`
    before ever reaching a return. Post-fix, it returns True.
    """
    mod = _load_setup_database_module()

    # Mock the two symbols that create_cache_tables imports at call time.
    # setup_database appends the fmp_cached provider dir to sys.path
    # inside the function, so we patch at the source-module level.
    with patch(
        "openbb_fmp_cached.utils.database.init_database", return_value=True
    ), patch(
        "openbb_fmp_cached.utils.cache_schema.create_all_tables",
        return_value={"table_a": True, "table_b": True},
        create=True,
    ):
        result = mod.create_cache_tables()

    assert result is True, (
        "create_cache_tables should return True when init_database and "
        "create_all_tables succeed. See #775."
    )


def test_create_cache_tables_reraises_underlying_failure_as_false():
    """Failure path: underlying exception is caught and returns False,
    NOT propagated as an unhandled TypeError.
    """
    mod = _load_setup_database_module()

    with patch(
        "openbb_fmp_cached.utils.database.init_database",
        side_effect=RuntimeError("simulated init failure"),
    ):
        result = mod.create_cache_tables()

    assert result is False, (
        "create_cache_tables should catch underlying exceptions and "
        "return False, not propagate them."
    )


# Cleanup: unload the setup_database module to avoid polluting sys.modules
# for subsequent tests that might load it fresh.
@pytest.fixture(autouse=True)
def _cleanup_module():
    yield
    sys.modules.pop("fmp_cached_setup_database", None)
