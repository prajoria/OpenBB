"""Unit tests for the Fidelity persist autocommit fix — bd-2650/gykp.

``Tools/parse_fidelity_positions.py`` had two persist functions —
``persist_to_mysql`` and ``persist_basket_positions_to_mysql`` — that
ran DELETE + per-row INSERT on an ``autocommit=True`` connection. A
mid-loop INSERT failure would leave the DB with the prior snapshot's
rows GONE (from the committed DELETE) and only part of the new snapshot
loaded (some INSERTs committed row-by-row, then the failing INSERT).

Post-fix ``get_connection`` defaults to ``autocommit=False`` and both
persist functions wrap the DDL + DELETE + INSERT + basket-rebuild in
an explicit try/commit/except/rollback/finally block, so a mid-batch
failure rolls back cleanly to the pre-import state.

Tests focus on the transaction contract — they mock pymysql entirely
so no MySQL server is needed.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# Ensure the repo's Tools/ directory is importable.
_REPO_ROOT = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..",
        "..",
        "..",
    )
)
_TOOLS_DIR = os.path.join(_REPO_ROOT, "Tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _sample_positions_df() -> pd.DataFrame:
    """3 rows for 2 accounts, one snapshot."""
    return pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-30"),
                "account_name": "ACCT-1",
                "basket_name": "",
                "symbol": "MSFT",
                "description": "Microsoft Corp",
                "acquired": pd.Timestamp("2020-01-15"),
                "term": "Long",
                "total_gain_loss": 100.0,
                "pct_gain_loss": 10.0,
                "current_value": 1000.0,
                "quantity": 5.0,
                "avg_cost_basis": 180.0,
                "cost_basis_total": 900.0,
                "transfer_avail_date": pd.NaT,
                "share_source": "",
                "grant_date": pd.NaT,
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-30"),
                "account_name": "ACCT-1",
                "basket_name": "",
                "symbol": "AAPL",
                "description": "Apple Inc",
                "acquired": pd.Timestamp("2021-03-10"),
                "term": "Long",
                "total_gain_loss": 50.0,
                "pct_gain_loss": 5.0,
                "current_value": 1050.0,
                "quantity": 7.0,
                "avg_cost_basis": 143.0,
                "cost_basis_total": 1000.0,
                "transfer_avail_date": pd.NaT,
                "share_source": "",
                "grant_date": pd.NaT,
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-30"),
                "account_name": "ACCT-2",
                "basket_name": "",
                "symbol": "GOOGL",
                "description": "Alphabet Inc",
                "acquired": pd.Timestamp("2022-06-01"),
                "term": "Long",
                "total_gain_loss": 25.0,
                "pct_gain_loss": 2.5,
                "current_value": 1025.0,
                "quantity": 8.0,
                "avg_cost_basis": 125.0,
                "cost_basis_total": 1000.0,
                "transfer_avail_date": pd.NaT,
                "share_source": "",
                "grant_date": pd.NaT,
            },
        ]
    )


def _sample_basket_df() -> pd.DataFrame:
    """Two-account basket positions."""
    return pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-30"),
                "account_name": "BASKET-1",
                "basket_name": "TECH",
                "symbol": "MSFT",
                "description": "Microsoft Corp",
                "total_gain_loss": 100.0,
                "pct_gain_loss": 10.0,
                "current_value": 1000.0,
                "quantity": 5.0,
                "avg_cost_basis": 180.0,
                "cost_basis_total": 900.0,
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-30"),
                "account_name": "BASKET-2",
                "basket_name": "TECH",
                "symbol": "AAPL",
                "description": "Apple Inc",
                "total_gain_loss": 50.0,
                "pct_gain_loss": 5.0,
                "current_value": 1050.0,
                "quantity": 7.0,
                "avg_cost_basis": 143.0,
                "cost_basis_total": 1000.0,
            },
        ]
    )


class _FakeCursor:
    """Minimal cursor stand-in that returns a scalar 'cnt' on fetchone.

    All ``execute`` calls succeed unless a ``failure_predicate`` is set;
    tests set the predicate to trigger a RuntimeError at a specific point
    (mid-loop, on DELETE, etc.).
    """

    def __init__(self, failure_predicate=None):
        self.executed: list[tuple] = []
        self.rowcount = 1
        self.failure_predicate = failure_predicate  # callable(sql, params) -> bool

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if self.failure_predicate and self.failure_predicate(sql, params):
            raise RuntimeError(f"Injected failure at exec #{len(self.executed)}")

    def fetchone(self):
        return {"cnt": 42}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    """Minimal pymysql conn stand-in that records commit/rollback/close."""

    def __init__(self, failure_predicate=None):
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0
        self.db = "openbb_test"
        self._cursor = _FakeCursor(failure_predicate)

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


# ---------------------------------------------------------------------------
# Site 1: get_connection default
# ---------------------------------------------------------------------------


class TestGetConnectionDefault:
    """get_connection defaults to autocommit=False (bd-2650)."""

    def test_default_is_autocommit_false(self):
        """Pre-fix default was autocommit=True — the exact data-loss cause.
        Post-fix default is autocommit=False so caller must explicitly
        commit or rollback.
        """
        import parse_fidelity_positions as tool

        captured = {}

        def fake_connect(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("pymysql.connect", side_effect=fake_connect):
            tool.get_connection(database="openbb_test")

        # Last call to pymysql.connect is the returned connection.
        assert captured.get("autocommit") is False, (
            f"Default autocommit MUST be False post-bd-2650. Got: "
            f"{captured.get('autocommit')} — reverting to True would "
            f"re-introduce the P0 data-loss window."
        )

    def test_explicit_autocommit_true_still_supported(self):
        """Callers can opt in to autocommit=True for backward compat."""
        import parse_fidelity_positions as tool

        captured = {}

        def fake_connect(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        with patch("pymysql.connect", side_effect=fake_connect):
            tool.get_connection(database="openbb_test", autocommit=True)

        assert captured.get("autocommit") is True


# ---------------------------------------------------------------------------
# Site 2: persist_to_mysql transaction contract
# ---------------------------------------------------------------------------


class TestPersistToMysqlTransaction:
    """persist_to_mysql commits on success, rolls back on failure (bd-gykp)."""

    def test_happy_path_commits_and_closes(self):
        """Successful persist MUST call commit() exactly once and close()."""
        import parse_fidelity_positions as tool

        fake_conn = _FakeConn()
        with patch.object(tool, "get_connection", return_value=fake_conn):
            tool.persist_to_mysql(
                _sample_positions_df(), owner="test", database="openbb_test"
            )

        assert (
            fake_conn.commits == 1
        ), f"Success path MUST commit exactly once. Got {fake_conn.commits}."
        assert (
            fake_conn.rollbacks == 0
        ), f"Success path MUST NOT rollback. Got {fake_conn.rollbacks}."
        assert fake_conn.closes == 1, "conn.close() MUST be called in finally."

    def test_insert_failure_rolls_back_and_closes(self):
        """Mid-loop INSERT failure MUST trigger rollback + close, NOT commit."""
        import parse_fidelity_positions as tool

        # Fail on the 5th SQL execution (past DDL, past DELETE, into the
        # INSERT loop).
        def fail_at_5th(sql, params):
            return fail_at_5th.call_count >= 5  # noqa: PLR2004

        fail_at_5th.call_count = 0

        fake_conn = _FakeConn(
            failure_predicate=lambda s, p: len(fake_conn._cursor.executed) >= 5
        )
        with patch.object(tool, "get_connection", return_value=fake_conn):
            with pytest.raises(RuntimeError, match="Injected failure"):
                tool.persist_to_mysql(
                    _sample_positions_df(), owner="test", database="openbb_test"
                )

        assert fake_conn.rollbacks == 1, (
            f"INSERT failure MUST rollback exactly once. Got {fake_conn.rollbacks}. "
            f"If 0 → the except: rollback; raise block is missing or unreachable, "
            f"meaning the DELETE has committed and the partial INSERTs are visible "
            f"— the exact bd-gykp P0 data-loss scenario."
        )
        assert (
            fake_conn.commits == 0
        ), f"On failure, commit MUST NOT be called. Got {fake_conn.commits}."
        assert fake_conn.closes == 1, "conn.close() MUST fire in finally even on error."

    def test_delete_failure_rolls_back_and_closes(self):
        """DELETE failure MUST rollback + close."""
        import parse_fidelity_positions as tool

        # Trigger on any DELETE
        fake_conn = _FakeConn(
            failure_predicate=lambda s, p: "DELETE FROM Portfolio_Positions" in s
        )
        with patch.object(tool, "get_connection", return_value=fake_conn):
            with pytest.raises(RuntimeError, match="Injected failure"):
                tool.persist_to_mysql(
                    _sample_positions_df(), owner="test", database="openbb_test"
                )

        assert fake_conn.rollbacks == 1
        assert fake_conn.commits == 0
        assert fake_conn.closes == 1


# ---------------------------------------------------------------------------
# Site 3: persist_basket_positions_to_mysql transaction contract
# ---------------------------------------------------------------------------


class TestPersistBasketPositionsTransaction:
    """persist_basket_positions_to_mysql same transaction contract."""

    def test_happy_path_commits_and_closes(self):
        import parse_fidelity_positions as tool

        fake_conn = _FakeConn()
        with patch.object(tool, "get_connection", return_value=fake_conn):
            tool.persist_basket_positions_to_mysql(
                _sample_basket_df(), owner="test", database="openbb_test"
            )

        assert fake_conn.commits == 1
        assert fake_conn.rollbacks == 0
        assert fake_conn.closes == 1

    def test_insert_failure_rolls_back_and_closes(self):
        import parse_fidelity_positions as tool

        fake_conn = _FakeConn(
            failure_predicate=lambda s, p: len(fake_conn._cursor.executed) >= 6
        )
        with patch.object(tool, "get_connection", return_value=fake_conn):
            with pytest.raises(RuntimeError, match="Injected failure"):
                tool.persist_basket_positions_to_mysql(
                    _sample_basket_df(), owner="test", database="openbb_test"
                )

        assert fake_conn.rollbacks == 1
        assert fake_conn.commits == 0
        assert fake_conn.closes == 1

    def test_empty_df_early_return_no_connection(self):
        """Empty DF short-circuits BEFORE opening a connection (pre-fix behavior preserved)."""
        import parse_fidelity_positions as tool

        with patch.object(tool, "get_connection") as mock_get:
            result = tool.persist_basket_positions_to_mysql(
                pd.DataFrame(), owner="test", database="openbb_test"
            )

        assert mock_get.call_count == 0, "Empty DF must not open a connection."
        assert result["inserted"] == 0
