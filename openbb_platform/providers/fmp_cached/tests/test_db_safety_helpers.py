"""Unit tests for Tier-0 DB safety helpers — bd-kh08.

Two helpers added to ``openbb_fmp_cached.utils.database``:

1. ``safe_identifier(name)`` — regex-allowlist SQL identifier sanitizer.
   Fixes the CREATE-DATABASE SQL-injection cluster (bd-y5fn / v9ri /
   20zx / o1oy).
2. ``replace_rows(table, where_col, where_val, rows, *, columns=None)``
   — transactional DELETE + INSERT that either commits everything or
   rolls back on any failure. Fixes the autocommit + DELETE-then-INSERT
   data-loss cluster (bd-ihdn / n3sf / 2650 / gykp / hyzu).

Design spec: docs/superpowers/specs/2026-07-08-bd-kh08-tier0-db-helpers-design.md
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# safe_identifier
# ---------------------------------------------------------------------------


class TestSafeIdentifier:
    """Regex-allowlist SQL identifier sanitizer (bd-kh08 helper #1)."""

    def test_valid_simple_name(self):
        """Standard snake_case name passes through unchanged."""
        from openbb_fmp_cached.utils.database import safe_identifier

        assert safe_identifier("my_table") == "my_table"

    def test_valid_max_length_64(self):
        """64-char identifier accepted (MySQL boundary)."""
        from openbb_fmp_cached.utils.database import safe_identifier

        name = "a" + "b" * 63  # 64 chars total
        assert len(name) == 64
        assert safe_identifier(name) == name

    def test_valid_with_digits_and_underscores(self):
        """Digits after first char + underscores throughout."""
        from openbb_fmp_cached.utils.database import safe_identifier

        assert safe_identifier("tbl_2026_q1") == "tbl_2026_q1"

    def test_valid_leading_underscore(self):
        """Leading underscore is allowed by MySQL grammar."""
        from openbb_fmp_cached.utils.database import safe_identifier

        assert safe_identifier("_hidden") == "_hidden"

    def test_rejects_length_65(self):
        """65-char identifier exceeds MySQL 64-char cap → ValueError."""
        from openbb_fmp_cached.utils.database import safe_identifier

        bad = "a" + "b" * 64  # 65 chars
        with pytest.raises(ValueError) as exc:
            safe_identifier(bad)
        # Message must include repr of the input so operator can trace
        # what was rejected (bd-kh08 error-message contract).
        assert repr(bad) in str(exc.value) or bad in str(exc.value)

    def test_rejects_leading_digit(self):
        """Identifier starting with digit is invalid MySQL grammar."""
        from openbb_fmp_cached.utils.database import safe_identifier

        with pytest.raises(ValueError):
            safe_identifier("9table")

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # empty
            "a b",  # whitespace
            "a;b",  # statement terminator
            "a'b",  # single quote
            "a`b",  # backtick — MySQL-specific escape
            'a"b',  # double quote
            "a\x00b",  # null byte
            "a-b",  # hyphen (invalid in unquoted identifier)
            "a.b",  # dot (schema-qualified names not allowed here)
            "'; DROP TABLE users; --",  # classic injection payload
        ],
    )
    def test_rejects_malicious_inputs(self, bad):
        """Every classic injection shape is rejected by the allowlist."""
        from openbb_fmp_cached.utils.database import safe_identifier

        with pytest.raises(ValueError):
            safe_identifier(bad)


# ---------------------------------------------------------------------------
# replace_rows
# ---------------------------------------------------------------------------


class _FakeConn:
    """Minimal pymysql-connection stand-in for replace_rows tests.

    Records: DELETE calls, INSERT/executemany calls, commit/rollback,
    close. Callers can toggle whether executemany raises.
    """

    def __init__(self, executemany_raises: Exception | None = None):
        self._executemany_raises = executemany_raises
        self.delete_calls: list[tuple] = []
        self.executemany_calls: list[tuple] = []
        self.commit_called = 0
        self.rollback_called = 0
        self.close_called = 0
        self._cursor = MagicMock()
        self._cursor.execute.side_effect = self._on_execute
        self._cursor.executemany.side_effect = self._on_executemany
        self._cursor.rowcount = 0

    def _on_execute(self, sql: str, params: tuple = ()):
        self.delete_calls.append((sql, params))

    def _on_executemany(self, sql: str, params_list: list):
        if self._executemany_raises is not None:
            raise self._executemany_raises
        self.executemany_calls.append((sql, params_list))
        self._cursor.rowcount = len(params_list)

    def cursor(self):
        cm = MagicMock()
        cm.__enter__ = lambda _self: self._cursor
        cm.__exit__ = lambda _self, *a: False
        return cm

    def commit(self):
        self.commit_called += 1

    def rollback(self):
        self.rollback_called += 1

    def close(self):
        self.close_called += 1


class TestReplaceRows:
    """Transactional DELETE + INSERT (bd-kh08 helper #2)."""

    def _patch_connect(self, fake: _FakeConn):
        """Patch pymysql.connect at the module level."""
        return patch(
            "openbb_fmp_cached.utils.database.pymysql.connect",
            return_value=fake,
        )

    def test_happy_path_inserts_rows(self):
        """3 rows → DELETE executed once, executemany INSERT once, commit."""
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        rows = [
            {"symbol": "AAPL", "value": 1},
            {"symbol": "AAPL", "value": 2},
            {"symbol": "AAPL", "value": 3},
        ]
        with self._patch_connect(fake):
            n = replace_rows("my_table", "symbol", "AAPL", rows)

        assert n == 3
        # DELETE fired first.
        assert len(fake.delete_calls) == 1
        delete_sql, delete_params = fake.delete_calls[0]
        assert "DELETE" in delete_sql.upper()
        assert "my_table" in delete_sql
        assert "symbol" in delete_sql
        assert delete_params == ("AAPL",)
        # Then INSERT via executemany with the 3 rows.
        assert len(fake.executemany_calls) == 1
        insert_sql, insert_params = fake.executemany_calls[0]
        assert "INSERT" in insert_sql.upper()
        assert len(insert_params) == 3
        # Commit called; rollback NOT called.
        assert fake.commit_called == 1
        assert fake.rollback_called == 0
        assert fake.close_called == 1

    def test_empty_rows_deletes_only(self):
        """Empty rows list → DELETE + commit, no INSERT."""
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        with self._patch_connect(fake):
            n = replace_rows("my_table", "symbol", "AAPL", [])

        assert n == 0
        assert len(fake.delete_calls) == 1
        assert len(fake.executemany_calls) == 0
        assert fake.commit_called == 1
        assert fake.rollback_called == 0

    def test_rejects_invalid_table(self):
        """Invalid table name → ValueError from safe_identifier."""
        from openbb_fmp_cached.utils.database import replace_rows

        with pytest.raises(ValueError):
            replace_rows("my; DROP", "symbol", "AAPL", [{"a": 1}])

    def test_rejects_invalid_where_col(self):
        """Invalid where_col name → ValueError from safe_identifier."""
        from openbb_fmp_cached.utils.database import replace_rows

        with pytest.raises(ValueError):
            replace_rows("my_table", "col; DROP", "AAPL", [{"a": 1}])

    def test_insert_failure_rolls_back(self):
        """Mid-INSERT failure → rollback (pre-existing data survives)."""
        from openbb_fmp_cached.utils.database import replace_rows

        boom = RuntimeError("simulated INSERT failure mid-batch")
        fake = _FakeConn(executemany_raises=boom)
        rows = [{"a": 1}, {"a": 2}]

        with self._patch_connect(fake):
            with pytest.raises(RuntimeError, match="simulated INSERT"):
                replace_rows("my_table", "symbol", "AAPL", rows)

        # DELETE fired, INSERT raised, rollback called, commit NOT called.
        assert len(fake.delete_calls) == 1
        assert fake.rollback_called == 1
        assert fake.commit_called == 0
        # Connection still closed even on failure.
        assert fake.close_called == 1

    def test_columns_inferred_from_row_keys_sorted(self):
        """No explicit columns → INSERT SQL uses sorted key order (deterministic)."""
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        rows = [{"zebra": 1, "apple": 2, "mango": 3}]
        with self._patch_connect(fake):
            replace_rows("my_table", "symbol", "AAPL", rows)

        insert_sql, insert_params = fake.executemany_calls[0]
        # Column order in the SQL must be alphabetically sorted.
        # (Robust check — split on comma inside parens.)
        cols_section = insert_sql.split("(", 1)[1].split(")", 1)[0]
        cols = [c.strip() for c in cols_section.split(",")]
        assert cols == sorted(cols) == ["apple", "mango", "zebra"]

    def test_columns_explicit_used_verbatim(self):
        """Explicit columns list → INSERT SQL uses that exact order."""
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        rows = [{"zebra": 1, "apple": 2, "mango": 3}]
        with self._patch_connect(fake):
            replace_rows(
                "my_table",
                "symbol",
                "AAPL",
                rows,
                columns=["zebra", "apple", "mango"],
            )

        insert_sql, insert_params = fake.executemany_calls[0]
        cols_section = insert_sql.split("(", 1)[1].split(")", 1)[0]
        cols = [c.strip() for c in cols_section.split(",")]
        assert cols == ["zebra", "apple", "mango"]

    def test_autocommit_false_on_connection(self):
        """Fresh connection MUST be opened with autocommit=False.

        Design decision D3: fresh connection + explicit transaction,
        NOT the shared pool (whose connections have autocommit=True
        baked at get-time). If someone refactors this to use the pool,
        the transaction semantics silently break.
        """
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        with patch(
            "openbb_fmp_cached.utils.database.pymysql.connect",
            return_value=fake,
        ) as mock_connect:
            replace_rows("my_table", "symbol", "AAPL", [{"a": 1}])

        # The single connect call must have received autocommit=False.
        assert mock_connect.call_count == 1
        _, kwargs = mock_connect.call_args
        assert kwargs.get("autocommit") is False, (
            "replace_rows opened a connection with autocommit != False — "
            "transaction semantics require autocommit=False so the "
            "DELETE + INSERT commit/rollback atomically (bd-kh08 D3)."
        )

    # ---- PR #414 review-fix regression tests ------------------------------

    def test_rejects_non_empty_rows_with_empty_columns(self):
        """PR #414 hunter P1: rows + columns=[] MUST raise, not silently DELETE-only.

        Pre-review-fix ``if rows and columns:`` gated the INSERT on both
        being truthy — a caller passing non-empty rows + explicit
        ``columns=[]`` would DELETE then silently skip INSERT and commit,
        producing the exact "cache empty after replace_rows" failure the
        helper exists to prevent.
        """
        from openbb_fmp_cached.utils.database import replace_rows

        with pytest.raises(ValueError, match="non-empty rows but no columns"):
            replace_rows(
                "my_table",
                "symbol",
                "AAPL",
                [{"a": 1}, {"b": 2}],
                columns=[],
            )

    def test_rejects_non_empty_rows_of_empty_dicts_inferred(self):
        """PR #414 hunter P1: rows=[{},{}] with inferred columns also rejected.

        Inferred columns come from the union of row keys. If every row
        is an empty dict, the inferred columns list is empty → same
        DELETE-then-silent-skip failure mode. Reject loudly.
        """
        from openbb_fmp_cached.utils.database import replace_rows

        with pytest.raises(ValueError, match="non-empty rows but no columns"):
            replace_rows("my_table", "symbol", "AAPL", [{}, {}])

    def test_explicit_columns_missing_key_raises_keyerror(self):
        """PR #414 code-reviewer P2: explicit columns are a caller contract.

        Pre-review-fix ``row.get(col)`` silently substituted None (SQL
        NULL) when a row was missing an explicit column — inconsistent
        with safe_identifier's loud-rejection philosophy. A typo in the
        explicit columns list became a silent SQL NULL. Post-fix, missing
        keys under EXPLICIT columns raise KeyError with the row index
        and the missing key.
        """
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        rows = [
            {"symbol": "AAPL", "value": 1},
            {"symbol": "AAPL"},  # missing 'value'
        ]
        with self._patch_connect(fake):
            with pytest.raises(KeyError, match="value"):
                replace_rows(
                    "my_table",
                    "symbol",
                    "AAPL",
                    rows,
                    columns=["symbol", "value"],
                )

    def test_inferred_columns_missing_key_becomes_null(self):
        """PR #414 code-reviewer P2: inferred columns keep None-fill (regression lock).

        Inferred columns come from the union of keys across rows. Some
        rows genuinely have fewer keys — None-fill is the correct
        default there. Only EXPLICIT columns raise on missing keys.
        """
        from openbb_fmp_cached.utils.database import replace_rows

        fake = _FakeConn()
        rows = [
            {"symbol": "AAPL", "value": 1},
            {"symbol": "AAPL"},  # missing 'value' — becomes None
        ]
        with self._patch_connect(fake):
            n = replace_rows("my_table", "symbol", "AAPL", rows)

        assert n == 2
        # Second row's tuple should have None for the missing 'value' column.
        _, params = fake.executemany_calls[0]
        # Columns inferred + sorted: ['symbol', 'value']
        assert params[1] == ("AAPL", None)

    def test_rollback_failure_log_includes_original_exception(self, caplog):
        """PR #414 code-reviewer P2: rollback-failure log must name the ORIGINAL exception.

        Pre-review-fix the log only showed why rollback broke, not why
        rollback was needed. Post-fix the log includes both — operators
        debugging cache corruption see the full causal chain.
        """
        import logging

        from openbb_fmp_cached.utils.database import replace_rows

        original_exc = RuntimeError("original failure from INSERT")
        fake = _FakeConn(executemany_raises=original_exc)
        # Force rollback itself to fail so we hit the log branch.
        fake.rollback = MagicMock(side_effect=RuntimeError("rollback failure"))

        with caplog.at_level(logging.ERROR, logger="openbb_fmp_cached.utils.database"):
            with self._patch_connect(fake):
                with pytest.raises(RuntimeError, match="original failure"):
                    replace_rows("my_table", "symbol", "AAPL", [{"a": 1}])

        # The error log MUST mention the original exception, not just
        # the rollback failure. Otherwise operators lose the causal
        # chain in monitoring systems.
        error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert error_records, "no ERROR-level log captured on rollback failure"
        msg = error_records[0].getMessage()
        assert "original failure" in msg, (
            f"rollback-failure log doesn't name the original exception. "
            f"Log message: {msg!r}"
        )


class TestSafeIdentifierNonStr:
    """PR #414 code-reviewer P2: cover the isinstance guard."""

    @pytest.mark.parametrize(
        "bad",
        [
            123,  # int
            b"my_table",  # bytes
            None,
            ["my_table"],  # list
            object(),  # arbitrary object
            12.5,  # float
        ],
    )
    def test_rejects_non_str_inputs(self, bad):
        """isinstance guard rejects non-str inputs.

        Pre-review-fix this branch had zero test coverage — if someone
        refactored the isinstance check away, the tests stayed GREEN
        and the regression surfaced as TypeError at runtime (regex
        won't accept non-str).
        """
        from openbb_fmp_cached.utils.database import safe_identifier

        with pytest.raises(ValueError):
            safe_identifier(bad)
