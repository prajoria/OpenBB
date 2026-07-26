"""Round-trip tests: filename parser + fixture ingest + idempotence + reads.

Uses a hand-crafted synthetic CSV so no real brokerage data touches the repo.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from portfolio_snapshot_importer import (
    FilenameParseError,
    IngestReport,
    PortfolioStore,
    import_file,
    import_files,
    import_folder,
    parse_fidelity_filename,
)


# ---------------------------------------------------------------------------
# filename parser
# ---------------------------------------------------------------------------
class TestFilenameParser:
    def test_parses_full_form(self):
        d, u = parse_fidelity_filename("Portfolio_Positions_Jul-18-2026_alice.csv")
        assert d == date(2026, 7, 18)
        assert u == "alice"

    def test_parses_without_user_suffix(self):
        d, u = parse_fidelity_filename("Portfolio_Positions_Jan-05-2024.csv")
        assert d == date(2024, 1, 5)
        assert u is None

    def test_accepts_dots_and_dashes_in_user(self):
        d, u = parse_fidelity_filename("Portfolio_Positions_Dec-31-2025_a.b-c_1.csv")
        assert u == "a.b-c_1"

    def test_rejects_wrong_prefix(self):
        with pytest.raises(FilenameParseError):
            parse_fidelity_filename("Fidelity_Positions_Jul-18-2026.csv")

    def test_rejects_bogus_month(self):
        with pytest.raises(FilenameParseError):
            parse_fidelity_filename("Portfolio_Positions_XYZ-18-2026.csv")

    def test_rejects_impossible_date(self):
        with pytest.raises(FilenameParseError):
            parse_fidelity_filename("Portfolio_Positions_Feb-30-2026.csv")


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------
SYNTHETIC_CSV = (
    "﻿Account number,Account name,Symbol,Description,Quantity,Last price,"
    "Last price change,Current value,Today's gain/loss dollar,"
    "Today's gain/loss percent,Total gain/loss dollar,Total gain/loss percent,"
    "Percent of account,Cost basis total,Average cost basis,Type,user_id\n"
    "Z1234567,Brokerage,XYZ,SYNTHETIC INC,10,$100.50,+$1.00,\"$1,005.00\","
    "+$10.00,+1.00%,+$100.00,+11.05%,25.00%,\"$905.00\",$90.50,Cash,alice\n"
    "Z1234567,Brokerage,ABC,SYNTHETIC ETF,20,$50.00,-$0.50,\"$1,000.00\","
    "-$10.00,-0.99%,-$50.00,-4.76%,24.90%,\"$1,050.00\",$52.50,Cash,alice\n"
    "Z1234567,Brokerage,SPAXX**,MONEY MARKET,2000.5,$1.00,--,\"$2,000.50\","
    "--,--,--,--,49.80%,--,--,Cash,alice\n"
    "Brokerage services provided by ... (footer)\n"
)


@pytest.fixture
def synthetic_csv(tmp_path: Path) -> Path:
    p = tmp_path / "Portfolio_Positions_Jul-18-2026_alice.csv"
    p.write_text(SYNTHETIC_CSV, encoding="utf-8")
    return p


@pytest.fixture
def store(tmp_path: Path) -> PortfolioStore:
    return PortfolioStore(tmp_path / "positions.db")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
class TestIngest:
    def test_imports_synthetic(self, synthetic_csv, store):
        r = import_file(synthetic_csv, store=store)
        assert r.status == "imported"
        assert r.snapshot_date == "2026-07-18"
        assert r.user_id == "alice"
        assert r.row_count_kept == 3  # footer + no-symbol rows dropped upstream
        assert r.row_count_raw == 3  # the 4th line is a footer, excluded by _read_csv

    def test_second_import_is_duplicate(self, synthetic_csv, store):
        r1 = import_file(synthetic_csv, store=store)
        r2 = import_file(synthetic_csv, store=store)
        assert r1.status == "imported"
        assert r2.status == "duplicate"
        assert r2.snapshot_id == r1.snapshot_id

    def test_list_and_show_roundtrip(self, synthetic_csv, store):
        r = import_file(synthetic_csv, store=store)
        snaps = store.list_snapshots()
        assert len(snaps) == 1
        assert snaps[0]["user_id"] == "alice"

        positions = store.positions_for(r.snapshot_id)
        symbols = sorted(p["symbol"] for p in positions)
        assert symbols == ["ABC", "SPAXX**", "XYZ"]

        xyz = next(p for p in positions if p["symbol"] == "XYZ")
        assert xyz["quantity"] == 10.0
        assert xyz["last_price"] == 100.50
        assert xyz["current_value"] == 1005.00
        # Percent stored as fraction of one: 25.00% → 0.25
        assert xyz["percent_of_account"] == pytest.approx(0.25)
        assert xyz["today_gain_loss_percent"] == pytest.approx(0.01)

    def test_unrecognized_filename_skipped(self, tmp_path, store):
        bad = tmp_path / "random.csv"
        bad.write_text("garbage")
        r = import_file(bad, store=store)
        assert r.status == "skipped_unrecognized"

    def test_missing_columns_error(self, tmp_path, store):
        thin = tmp_path / "Portfolio_Positions_Jul-18-2026_bob.csv"
        thin.write_text("Account number,Symbol\nX,Y\n")
        r = import_file(thin, store=store)
        assert r.status == "error"
        assert "missing required columns" in r.message

    def test_folder_import_multi_user(self, tmp_path, store):
        a = tmp_path / "Portfolio_Positions_Jul-18-2026_alice.csv"
        b = tmp_path / "Portfolio_Positions_Jul-18-2026_bob.csv"
        a.write_text(SYNTHETIC_CSV, encoding="utf-8")
        b.write_text(SYNTHETIC_CSV.replace("alice", "bob"), encoding="utf-8")
        report: IngestReport = import_folder(tmp_path, store=store)
        assert report.imported == 2
        assert report.duplicates == 0
        # Same content, different user_id → distinct snapshots
        assert len({r.snapshot_id for r in report.results}) == 2


# ---------------------------------------------------------------------------
# store isolation
# ---------------------------------------------------------------------------
class TestStore:
    def test_wal_journal(self, tmp_path):
        with PortfolioStore(tmp_path / "s.db") as s:
            mode = s._conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"

    def test_foreign_keys_enabled(self, tmp_path):
        with PortfolioStore(tmp_path / "s.db") as s:
            fk = s._conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1
