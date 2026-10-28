"""Shared fixtures for the Portfolio Intelligence unit tests."""

import itertools

import pytest


@pytest.fixture(params=["memory", "sqlite"])
def paper_store_backend(request, monkeypatch, tmp_path):
    """Run a paper-store test module against both store implementations.

    The store contract tests build stores through the module-level names
    ``InMemoryAccountStore``, ``InMemoryPositionStore`` and
    ``InMemoryLedgerStore``. With the
    ``sqlite`` parameter those names build the durable SQLite stores (#2333)
    instead, each in its own file, so the same assertions prove both.
    """
    if request.param == "sqlite":
        # pylint: disable=import-outside-toplevel
        from openbb_portfolio_intel.paper.sqlite_stores import (
            SqliteAccountStore,
            SqliteLedgerStore,
            SqlitePositionStore,
        )

        counter = itertools.count()
        module = request.module
        for name, factory in (
            ("InMemoryAccountStore", SqliteAccountStore),
            ("InMemoryPositionStore", SqlitePositionStore),
            ("InMemoryLedgerStore", SqliteLedgerStore),
        ):
            if hasattr(module, name):
                monkeypatch.setattr(
                    module,
                    name,
                    lambda factory=factory: factory(
                        tmp_path / f"store-{next(counter)}.sqlite"
                    ),
                )
    return request.param
