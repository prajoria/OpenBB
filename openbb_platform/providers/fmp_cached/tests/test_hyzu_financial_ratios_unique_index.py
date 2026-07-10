"""Unit tests for bd-hyzu — financial_ratios UNIQUE(symbol, date, period).

Pre-fix the financial_ratios table had only a non-unique
``INDEX idx_composite (symbol, date, period)``. Two concurrent writers
racing on the same symbol could produce duplicate rows even with
per-symbol atomic replace_rows (bd-n3sf) if a caller bypassed
_store_financial_ratios or if external tools wrote to the table.

Post-fix:
- CREATE TABLE inline: UNIQUE KEY uk_symbol_date_period (symbol, date, period)
- ensure_financial_ratios_unique_index() migration for existing installs:
  dedupe by (symbol, date, period) keeping newest, then ALTER TABLE ADD UNIQUE
  (idempotent — repeat runs and fresh installs safely no-op).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


class TestCreateFinancialRatiosTableUniqueConstraint:
    """Fresh install: UNIQUE constraint is in the CREATE TABLE (bd-hyzu)."""

    def test_create_sql_contains_unique_symbol_date_period(self):
        """Source-level lint: the CREATE TABLE SQL MUST declare UNIQUE."""
        from openbb_fmp_cached.utils import cache_schema

        src = inspect.getsource(cache_schema.create_financial_ratios_table)
        # Exact substring — locks the current UNIQUE constraint against
        # accidental removal in a future refactor.
        assert "UNIQUE KEY uk_symbol_date_period (symbol, date, period)" in src, (
            "bd-hyzu: create_financial_ratios_table MUST declare "
            "UNIQUE(symbol, date, period). Without it, concurrent writers "
            "or external tools bypassing _store_financial_ratios can "
            "silently duplicate rows."
        )

    def test_non_unique_composite_index_removed(self):
        """The old non-unique ``idx_composite`` index MUST be removed.

        Keeping both idx_composite AND uk_symbol_date_period would double
        the index storage for identical column coverage. UNIQUE is a
        superset of idx_composite's query performance.
        """
        from openbb_fmp_cached.utils import cache_schema

        src = inspect.getsource(cache_schema.create_financial_ratios_table)
        assert "INDEX idx_composite (symbol, date, period)" not in src, (
            "Redundant with UNIQUE — remove idx_composite when adding "
            "the UNIQUE constraint."
        )


class TestEnsureFinancialRatiosUniqueIndex:
    """Migration helper: dedupe existing rows + ALTER TABLE ADD UNIQUE."""

    def test_migration_runs_dedupe_then_add_unique(self):
        """Happy path: both queries execute in order."""
        from openbb_fmp_cached.utils import cache_schema

        executed_sqls: list[str] = []

        def fake_execute(sql, params=()):
            executed_sqls.append(sql)
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            cache_schema.ensure_financial_ratios_unique_index()

        assert (
            len(executed_sqls) == 2
        ), f"Expected 2 queries (dedupe + ALTER TABLE). Got {len(executed_sqls)}."
        # Dedupe first — must not add UNIQUE before removing conflicts.
        assert "DELETE fr1" in executed_sqls[0]
        assert "financial_ratios fr1" in executed_sqls[0]
        assert (
            "cached_at < fr2.cached_at" in executed_sqls[0]
        ), "Dedupe MUST keep the newest by cached_at."
        # Then ADD UNIQUE.
        assert "ALTER TABLE financial_ratios" in executed_sqls[1]
        assert "ADD UNIQUE KEY uk_symbol_date_period" in executed_sqls[1]

    def test_dedupe_failure_still_attempts_add_unique(self):
        """Dedupe error MUST NOT prevent the ADD UNIQUE attempt.

        Failure scenarios: dedupe query timeout on huge table, permission
        error. The ADD UNIQUE should still run — worst case it fails too
        (because of remaining duplicates) and that failure is also caught.
        """
        from openbb_fmp_cached.utils import cache_schema

        call_count = {"n": 0}

        def fake_execute(sql, params=()):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("dedupe timeout")
            return None

        with patch.object(cache_schema, "execute_query", side_effect=fake_execute):
            # Must not raise — both errors are caught+logged.
            cache_schema.ensure_financial_ratios_unique_index()

        assert (
            call_count["n"] == 2
        ), "ADD UNIQUE MUST fire even if dedupe raised (best-effort migration)."

    def test_add_unique_already_present_is_silent(self, caplog):
        """Fresh install: constraint already exists → ALTER TABLE fails cleanly.

        MySQL raises "Duplicate key name" when adding a UNIQUE that
        already exists. This is the expected path for fresh installs
        (constraint inline in CREATE TABLE) and repeat migrations.
        Must NOT propagate, must NOT log at WARNING/ERROR (would be
        noise on every store call).
        """
        from openbb_fmp_cached.utils import cache_schema

        call_count = {"n": 0}

        def fake_execute(sql, params=()):
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Simulate MySQL 1061 duplicate key error.
                raise Exception(
                    "(1061, \"Duplicate key name 'uk_symbol_date_period'\")"
                )
            return None

        with patch.object(
            cache_schema, "execute_query", side_effect=fake_execute
        ), caplog.at_level("DEBUG", logger="openbb_fmp_cached.utils.cache_schema"):
            cache_schema.ensure_financial_ratios_unique_index()

        # No WARNING/ERROR records — this is expected behavior.
        loud_records = [r for r in caplog.records if r.levelno >= 30]  # WARNING+
        assert loud_records == [], (
            f"Duplicate-key on ADD UNIQUE is the expected path for "
            f"fresh/repeat runs — must NOT log at WARNING+. Got: {loud_records}"
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
