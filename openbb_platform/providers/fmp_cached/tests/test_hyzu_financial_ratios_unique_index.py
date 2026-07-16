"""Unit tests for bd-hyzu — financial_ratios UNIQUE(symbol, date, period, currency).

Pre-fix the financial_ratios table had only a non-unique
``INDEX idx_composite (symbol, date, period)``. Two concurrent writers
racing on the same symbol could produce duplicate rows even with
per-symbol atomic replace_rows (bd-n3sf) if a caller bypassed
_store_financial_ratios or if external tools wrote to the table.

Post-fix:
- CREATE TABLE inline: UNIQUE KEY uk_symbol_date_period_currency
  (symbol, date, period, currency) — includes currency to prevent
  dedupe from collapsing multi-currency reporters (PR #427 hunter P0).
- ensure_financial_ratios_unique_index() migration for existing installs:
  NULL-cleanup, dedupe, ALTER TABLE ADD UNIQUE. Idempotent + errno-aware
  (1061 silent, 1062 loud) + guarded by module-level ran-once flag
  (PR #427 code-reviewer P1 + hunter P1).
"""

from __future__ import annotations

import inspect
from unittest.mock import patch


class TestCreateFinancialRatiosTableUniqueConstraint:
    """Fresh install: UNIQUE constraint is in the CREATE TABLE (bd-hyzu)."""

    def test_create_sql_contains_unique_with_currency(self):
        """Source-level lint: the CREATE TABLE SQL MUST declare UNIQUE with currency."""
        from openbb_fmp_cached.utils import cache_schema

        src = inspect.getsource(cache_schema.create_financial_ratios_table)
        # Locks the current UNIQUE constraint (includes currency per
        # PR #427 hunter P0 — prevents multi-currency-per-key data loss).
        assert "UNIQUE KEY uk_symbol_date_period_currency" in src, (
            "bd-hyzu: create_financial_ratios_table MUST declare "
            "UNIQUE(symbol, date, period, currency). Without it, "
            "concurrent writers or external tools bypassing "
            "_store_financial_ratios can silently duplicate rows."
        )
        assert "(symbol, date, period, currency)" in src, (
            "UNIQUE key columns MUST include currency (PR #427 hunter P0) "
            "to prevent dedupe from collapsing multi-currency reporters."
        )

    def test_non_unique_composite_index_removed(self):
        """The old non-unique ``idx_composite`` index MUST be removed."""
        from openbb_fmp_cached.utils import cache_schema

        src = inspect.getsource(cache_schema.create_financial_ratios_table)
        assert "INDEX idx_composite (symbol, date, period)" not in src, (
            "Redundant with UNIQUE — remove idx_composite when adding "
            "the UNIQUE constraint."
        )


class TestEnsureFinancialRatiosUniqueIndex:
    """Migration helper: NULL-cleanup + dedupe + ALTER TABLE ADD UNIQUE."""

    def setup_method(self):
        """Reset the ran-once flag between tests."""
        from openbb_fmp_cached.utils import cache_schema

        cache_schema._reset_fr_migration_flag_for_tests()

    def test_migration_runs_null_cleanup_dedupe_add_unique(self):
        """Happy path (fresh install, index missing): 4 queries in order —
        NULL cleanup, dedupe, SHOW INDEX pre-check, ADD UNIQUE.

        The SHOW INDEX pre-check was added for #776: it lets us skip the
        ALTER entirely on repeat runs so we never hit the 1061 error
        path (which execute_query logs at ERROR before our try/except
        can suppress it).
        """
        from openbb_fmp_cached.utils import cache_schema

        executed_sqls: list[str] = []

        def fake_execute(sql, params=()):
            executed_sqls.append(sql)
            # Return [] for SHOW INDEX → index missing → ADD UNIQUE proceeds
            if "SHOW INDEX" in sql:
                return []
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()

        assert (
            len(executed_sqls) == 4
        ), f"Expected 4 queries (NULL, dedupe, SHOW INDEX, ALTER). Got {len(executed_sqls)}."
        # Step 1: NULL cleanup — MUST include all 4 key columns.
        assert "DELETE FROM financial_ratios" in executed_sqls[0]
        assert "symbol IS NULL" in executed_sqls[0]
        assert (
            "currency IS NULL" in executed_sqls[0]
        ), "NULL cleanup MUST include currency (part of UNIQUE key)."
        # Step 2: dedupe self-join includes currency.
        assert "DELETE fr1" in executed_sqls[1]
        assert "fr1.currency = fr2.currency" in executed_sqls[1], (
            "Dedupe self-join MUST include currency (PR #427 hunter P0). "
            "Without it, multi-currency rows for the same "
            "(symbol, date, period) silently collapse."
        )
        assert (
            "cached_at < fr2.cached_at" in executed_sqls[1]
        ), "Dedupe MUST keep the newest by cached_at."
        # Step 3: SHOW INDEX pre-check (#776).
        assert "SHOW INDEX FROM financial_ratios" in executed_sqls[2]
        # Step 4: ADD UNIQUE with currency.
        assert "ALTER TABLE financial_ratios" in executed_sqls[3]
        assert "ADD UNIQUE KEY uk_symbol_date_period_currency" in executed_sqls[3]

    def test_migration_skips_alter_when_index_already_exists(self):
        """Repeat-run path (#776): SHOW INDEX returns a row → no ALTER,
        no 1061 error, no ERROR log noise."""
        from openbb_fmp_cached.utils import cache_schema

        executed_sqls: list[str] = []

        def fake_execute(sql, params=()):
            executed_sqls.append(sql)
            # SHOW INDEX returns a row → index already present
            if "SHOW INDEX" in sql:
                return [{"Key_name": "uk_symbol_date_period_currency"}]
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()

        # NULL cleanup, dedupe, SHOW INDEX — no ALTER.
        assert len(executed_sqls) == 3, (
            f"Expected 3 queries (NULL, dedupe, SHOW INDEX) when index "
            f"already exists — no ALTER should fire. Got {len(executed_sqls)}."
        )
        assert not any("ALTER TABLE" in s for s in executed_sqls), (
            "ALTER TABLE MUST NOT fire when the index already exists — "
            "otherwise execute_query logs the 1061 error at ERROR level "
            "before our try/except catches it. See #776."
        )

    def test_migration_ran_only_once_per_process(self):
        """PR #427 code-reviewer P1: ran-once flag skips subsequent calls."""
        from openbb_fmp_cached.utils import cache_schema

        call_count = {"n": 0}

        def fake_execute(sql, params=()):
            call_count["n"] += 1
            if "SHOW INDEX" in sql:
                return []
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()
            first_run_calls = call_count["n"]
            # 2nd call: MUST be a no-op (flag is set).
            cache_schema.ensure_financial_ratios_unique_index()
            second_run_calls = call_count["n"]

        assert (
            first_run_calls == 4
        ), f"First run should do 4 queries, got {first_run_calls}"
        assert second_run_calls == first_run_calls, (
            f"2nd call MUST skip (flag set). Got {second_run_calls - first_run_calls} "
            f"extra queries — pre-fix migration ran on EVERY aextract_data call, "
            f"burning ~2 MySQL round-trips per fetch forever."
        )

    def test_dedupe_failure_still_attempts_add_unique(self):
        """Dedupe error MUST NOT prevent the ADD UNIQUE attempt."""
        from openbb_fmp_cached.utils import cache_schema

        call_count = {"n": 0}
        sqls_seen: list[str] = []

        def fake_execute(sql, params=()):
            call_count["n"] += 1
            sqls_seen.append(sql)
            if "DELETE fr1" in sql:
                raise RuntimeError("dedupe timeout")
            if "SHOW INDEX" in sql:
                return []
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()

        # NULL cleanup, dedupe (raises), SHOW INDEX, ADD UNIQUE — 4 attempts.
        assert (
            call_count["n"] == 4
        ), "ADD UNIQUE MUST fire even if dedupe raised (best-effort migration)."
        assert any("ALTER TABLE" in s for s in sqls_seen)

    def test_add_unique_errno_1061_already_present_is_silent(self, caplog):
        """1061 Duplicate key name = race condition (index appeared between
        SHOW INDEX pre-check and ALTER). Silent at DEBUG."""
        from openbb_fmp_cached.utils import cache_schema

        def fake_execute(sql, params=()):
            if "SHOW INDEX" in sql:
                return []  # Pre-check says missing → proceed to ALTER
            if "ALTER TABLE" in sql:
                raise Exception(
                    "(1061, \"Duplicate key name 'uk_symbol_date_period_currency'\")"
                )
            return None

        with patch.object(
            cache_schema, "execute_query", side_effect=fake_execute
        ), caplog.at_level("DEBUG", logger="openbb_fmp_cached.utils.cache_schema"):
            cache_schema.ensure_financial_ratios_unique_index()

        loud_records = [r for r in caplog.records if r.levelno >= 30]
        assert loud_records == [], (
            f"1061 on ADD UNIQUE (race) — must NOT log at WARNING+. "
            f"Got: {loud_records}"
        )

    def test_add_unique_errno_1062_unexpected_logs_warning(self, caplog):
        """PR #427 code-reviewer P2 + hunter P2: 1062 = dedupe missed a dup.

        MySQL 1062 "Duplicate entry for key ..." fires if ADD UNIQUE
        finds a duplicate the dedupe missed (NULL rows, race, edge case).
        MUST log at WARNING so operators can investigate. Pre-review-fix
        this was swallowed at DEBUG same as 1061 — silent failure.
        """
        from openbb_fmp_cached.utils import cache_schema

        def fake_execute(sql, params=()):
            if "SHOW INDEX" in sql:
                return []  # Pre-check says missing → proceed to ALTER
            if "ALTER TABLE" in sql:
                raise Exception(
                    "(1062, \"Duplicate entry 'AAPL-2024-01-01-annual-USD' "
                    "for key 'uk_symbol_date_period_currency'\")"
                )
            return None

        with patch.object(
            cache_schema, "execute_query", side_effect=fake_execute
        ), caplog.at_level("WARNING", logger="openbb_fmp_cached.utils.cache_schema"):
            cache_schema.ensure_financial_ratios_unique_index()

        warning_records = [
            r
            for r in caplog.records
            if r.levelno == 30 and "duplicate" in r.message.lower()
        ]
        assert warning_records, (
            "1062 (Duplicate entry) MUST log at WARNING — signals that "
            "dedupe missed a duplicate and the UNIQUE constraint was NOT "
            "added. Pre-review-fix this was swallowed at DEBUG same as 1061."
        )

    def test_1062_failure_keeps_flag_false_for_retry(self):
        """If 1062 fires (dedupe missed), flag stays False so next call retries."""
        from openbb_fmp_cached.utils import cache_schema

        call_count = {"n": 0}

        def fake_execute(sql, params=()):
            call_count["n"] += 1
            if "SHOW INDEX" in sql:
                return []  # Pre-check says missing → proceed to ALTER
            if "ALTER TABLE" in sql:
                raise Exception('(1062, "Duplicate entry ...")')
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()
            first_calls = call_count["n"]
            # Second call: SHOULD retry (flag NOT set on 1062).
            cache_schema.ensure_financial_ratios_unique_index()
            second_calls = call_count["n"]

        assert second_calls > first_calls, (
            "1062 failure means migration didn't complete — flag MUST stay "
            "False so the next store call can retry. Got no retry (flag set)."
        )


class TestFinancialRatiosMigrationWiredIntoExtract:
    """aextract_data calls the migration helper (bd-hyzu)."""

    def test_aextract_data_calls_ensure_unique_index(self):
        """Source-level lint: aextract_data path MUST call ensure_financial_ratios_unique_index."""
        from openbb_fmp_cached.models import financial_ratios

        src = inspect.getsource(financial_ratios)
        assert "ensure_financial_ratios_unique_index" in src, (
            "The migration helper MUST be wired into the aextract_data "
            "init flow, else existing installs never get the UNIQUE "
            "constraint added."
        )
        assert (
            "from openbb_fmp_cached.utils.cache_schema import" in src
        ), "Import MUST come from cache_schema (not defined locally)."
