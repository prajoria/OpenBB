"""Tests for #1753 — Fidelity Positions CSV header alignment.

Verifies that both OLD-format and CURRENT-format Fidelity Positions
downloads import cleanly via the alias-map + column-split/merge in
``_normalize_current_headers``.
"""

# ruff: noqa: D101, D102, D103, D105, E501

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from portfolio_snapshot_importer.ingest import (
    _HEADER_ALIASES,
    _normalize_current_headers,
    import_file,
)
from portfolio_snapshot_importer.store import SqlitePortfolioStore

# ---------------------------------------------------------------------------
# Sample CSV bodies
# ---------------------------------------------------------------------------


# OLD format — 16 columns as the pre-2025 Fidelity Positions download
# emitted them.
_OLD_FORMAT_CSV = dedent("""\
    Account number,Account name,Symbol,Description,Quantity,Last price,Last price change,Current value,Today's gain/loss dollar,Today's gain/loss percent,Total gain/loss dollar,Total gain/loss percent,Percent of account,Cost basis total,Average cost basis,Type
    X12345678,Individual,MSFT,MICROSOFT CORP,50,400.00,+1.50,20000.00,+75.00,+0.38%,+2500.00,+14.29%,20.00%,17500.00,350.00,Cash
    X12345678,Individual,AAPL,APPLE INC,100,180.00,-0.50,18000.00,-50.00,-0.28%,+1000.00,+5.88%,18.00%,17000.00,170.00,Cash
    """)


# CURRENT format — the schema landed at
# docs/superpowers/specs/2026-08-03-fidelity-positions-csv-schema.md.
# Same data as OLD_FORMAT but with different headers / column layout.
_CURRENT_FORMAT_CSV = dedent("""\
    Account Name / Number,Symbol,Description,Quantity,Last Price,Last Price Change ($),Last Price Change (%),Current Value,Today's Gain/Loss ($),Today's Gain/Loss (%),Cost Basis Per Share,Total Cost Basis,Total Gain/Loss ($),Total Gain/Loss (%),Percent of Portfolio
    Individual - X12345678,MSFT,MICROSOFT CORP,50,400.00,+1.50,+0.38%,20000.00,+75.00,+0.38%,350.00,17500.00,+2500.00,+14.29%,20.00%
    Individual - X12345678,AAPL,APPLE INC,100,180.00,-0.50,-0.28%,18000.00,-50.00,-0.28%,170.00,17000.00,+1000.00,+5.88%,18.00%
    """)


@pytest.fixture
def store(tmp_path: Path) -> SqlitePortfolioStore:
    return SqlitePortfolioStore(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# _normalize_current_headers
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_old_format_is_noop(self) -> None:
        """R7.11 twin: if the fast-path check missed old-format files,
        we'd double-process them and corrupt the row dicts. Verified.
        """
        header = ["Account number", "Account name", "Symbol", "Quantity"]
        rows = [
            {
                "Account number": "X1",
                "Account name": "Ind",
                "Symbol": "MSFT",
                "Quantity": "50",
            }
        ]
        out_header, out_rows = _normalize_current_headers(header, rows)
        assert out_header == header
        assert out_rows == rows

    def test_current_format_alias_renames_apply(self) -> None:
        """R7.11 twin: without _HEADER_ALIASES, `Percent of Portfolio`
        would fail the _EXPECTED_COLS presence check. Verified.
        """
        header = [
            "Account Name / Number",
            "Symbol",
            "Percent of Portfolio",
            "Cost Basis Per Share",
        ]
        rows = [
            {
                "Account Name / Number": "Individual - X123",
                "Symbol": "MSFT",
                "Percent of Portfolio": "20.00%",
                "Cost Basis Per Share": "350.00",
            }
        ]
        out_header, out_rows = _normalize_current_headers(header, rows)
        assert "Percent of account" in out_header
        assert "Average cost basis" in out_header
        assert out_rows[0]["Percent of account"] == "20.00%"
        assert out_rows[0]["Average cost basis"] == "350.00"

    def test_account_column_splits(self) -> None:
        """R7.11 twin: without the rsplit, `Individual - X123` would
        become the entire account name and account number would be
        empty — breaking the last-4 mask downstream.
        """
        header = ["Account Name / Number", "Symbol"]
        rows = [{"Account Name / Number": "Roth IRA - X87654321", "Symbol": "MSFT"}]
        _, out_rows = _normalize_current_headers(header, rows)
        assert out_rows[0]["Account name"] == "Roth IRA"
        assert out_rows[0]["Account number"] == "X87654321"

    def test_account_column_unsplittable_falls_back(self) -> None:
        """A descriptor without ' - ' falls back to account_name=whole, number=empty."""
        header = ["Account Name / Number", "Symbol"]
        rows = [{"Account Name / Number": "Just A Name", "Symbol": "MSFT"}]
        _, out_rows = _normalize_current_headers(header, rows)
        assert out_rows[0]["Account name"] == "Just A Name"
        assert out_rows[0]["Account number"] == ""

    def test_last_price_change_columns_collapse(self) -> None:
        """R7.11 twin: without the split-column collapse, the parser
        would fail the _EXPECTED_COLS check (no `Last price change`).
        """
        header = [
            "Account Name / Number",
            "Symbol",
            "Last Price Change ($)",
            "Last Price Change (%)",
        ]
        rows = [
            {
                "Account Name / Number": "Individual - X1",
                "Symbol": "MSFT",
                "Last Price Change ($)": "+1.50",
                "Last Price Change (%)": "+0.38%",
            }
        ]
        out_header, out_rows = _normalize_current_headers(header, rows)
        assert "Last price change" in out_header
        assert "Last Price Change ($)" not in out_header
        assert "Last Price Change (%)" not in out_header
        assert out_rows[0]["Last price change"] == "+1.50"

    def test_header_alias_map_is_self_consistent(self) -> None:
        """Every alias value must be a valid old-format column name."""
        from portfolio_snapshot_importer.ingest import _EXPECTED_COLS

        for old_canonical in _HEADER_ALIASES.values():
            assert old_canonical in _EXPECTED_COLS, (
                f"Alias target {old_canonical!r} isn't in _EXPECTED_COLS. "
                "Either fix the alias, or add the column to _EXPECTED_COLS."
            )


# ---------------------------------------------------------------------------
# End-to-end import_file — both formats produce the same snapshot rows
# ---------------------------------------------------------------------------


class TestImportEndToEnd:
    def test_old_format_imports_cleanly(
        self, tmp_path: Path, store: SqlitePortfolioStore
    ) -> None:
        p = tmp_path / "Portfolio_Positions_Jan-15-2026.csv"
        p.write_text(_OLD_FORMAT_CSV, encoding="utf-8")
        result = import_file(p, store=store, user_id_fallback="daaji")
        assert result.status == "imported", result.message
        assert result.row_count_kept == 2

    def test_current_format_imports_cleanly(
        self, tmp_path: Path, store: SqlitePortfolioStore
    ) -> None:
        """R7.11 twin: without _normalize_current_headers, this test
        fails at the _EXPECTED_COLS presence check.
        """
        p = tmp_path / "Portfolio_Positions_Jan-15-2026.csv"
        p.write_text(_CURRENT_FORMAT_CSV, encoding="utf-8")
        result = import_file(p, store=store, user_id_fallback="daaji")
        assert result.status == "imported", result.message
        assert result.row_count_kept == 2

    def test_current_format_split_account(
        self, tmp_path: Path, store: SqlitePortfolioStore
    ) -> None:
        """Verify the account_name / account_number split survives
        into the persisted snapshot rows.
        """
        p = tmp_path / "Portfolio_Positions_Jan-15-2026.csv"
        p.write_text(_CURRENT_FORMAT_CSV, encoding="utf-8")
        result = import_file(p, store=store, user_id_fallback="daaji")
        assert result.status == "imported"
        # Fetch the persisted positions.
        positions = store.positions_for(result.snapshot_id)
        # Every row should have account_name=Individual and a
        # last-4-masked account_number derived from X12345678.
        for row in positions:
            assert row["account_name"] == "Individual"
            # The importer's last-4 masking normalizes account_number.
            assert row["account_number"] and "5678" in row["account_number"]
