"""Unit tests for the SEC bulk 13F CUSIP index (issue #89).

Covers the pure helpers in ``openbb_sec.utils.thirteen_f_index`` (period/value-
unit normalization, mocked read helpers) and the pure parse/aggregate functions
in ``Tools/ingest_sec_13f.py``. No network, no database — DB access is mocked.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from openbb_sec.utils import thirteen_f_index as tfi

# Make Tools/ingest_sec_13f.py importable (it has no import-time side effects
# beyond sys.path bootstrap + env setdefault).
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
)
_TOOLS_DIR = os.path.join(_PROJECT_ROOT, "Tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import ingest_sec_13f as ingest  # noqa: E402


# ---------------------------------------------------------------------------
# Period + value-unit helpers
# ---------------------------------------------------------------------------


class TestPeriodHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2025q4", "2025-Q4"),
            ("2025Q4", "2025-Q4"),
            ("2025-Q4", "2025-Q4"),
            ("2023-q2", "2023-Q2"),
        ],
    )
    def test_normalize_dataset_period(self, raw, expected):
        assert tfi.normalize_dataset_period(raw) == expected

    def test_normalize_dataset_period_invalid(self):
        with pytest.raises(ValueError):
            tfi.normalize_dataset_period("2025-13")

    @pytest.mark.parametrize(
        "report_date,expected",
        [
            ("31-MAR-2023", "2023-Q1"),
            ("30-JUN-2023", "2023-Q2"),
            ("30-SEP-2024", "2024-Q3"),
            ("31-DEC-2025", "2025-Q4"),
        ],
    )
    def test_period_from_report_date(self, report_date, expected):
        assert tfi.period_from_report_date(report_date) == expected

    def test_period_from_report_date_bad(self):
        assert tfi.period_from_report_date("") is None
        assert tfi.period_from_report_date("garbage") is None

    def test_period_to_quarter_end(self):
        assert tfi.period_to_quarter_end("2023-Q1") == "2023-03-31"
        assert tfi.period_to_quarter_end("2024-Q4") == "2024-12-31"


class TestValueUnit:
    """The x1000 guard — unit varies by period (Q-D)."""

    @pytest.mark.parametrize(
        "period,expected",
        [
            ("2023q1", "thousands"),
            ("2023q2", "usd"),
            ("2022q4", "thousands"),
            ("2026q1", "usd"),
        ],
    )
    def test_value_unit_for_dataset(self, period, expected):
        assert tfi.value_unit_for_dataset(period) == expected

    def test_normalize_value_thousands_scales(self):
        # Pre-2023-Q2: VALUE is in thousands → multiply by 1000.
        assert tfi.normalize_value_to_usd(479354, "thousands") == 479_354_000

    def test_normalize_value_usd_passthrough(self):
        # 2023-Q2+: VALUE already whole dollars → no scaling.
        assert tfi.normalize_value_to_usd(4360, "usd") == 4360

    def test_normalize_value_none(self):
        assert tfi.normalize_value_to_usd(None, "usd") is None


# ---------------------------------------------------------------------------
# Read helpers (mocked DB)
# ---------------------------------------------------------------------------


class TestReadHelpers:
    def test_resolve_cusip_returns_list(self):
        fake_db = MagicMock()
        fake_db.execute_query.return_value = [
            {"cusip": "02079K305"},
            {"cusip": "02079K107"},
        ]
        with patch.object(tfi, "_db", return_value=fake_db):
            assert tfi.resolve_cusip("GOOGL") == ["02079K305", "02079K107"]

    def test_resolve_cusip_empty_symbol(self):
        assert tfi.resolve_cusip("") == []

    def test_resolve_cusip_graceful_on_error(self):
        fake_db = MagicMock()
        fake_db.execute_query.side_effect = Exception("db down")
        with patch.object(tfi, "_db", return_value=fake_db):
            assert tfi.resolve_cusip("MSFT") == []

    def test_holders_for_cusip_ranked(self):
        fake_db = MagicMock()
        # First call resolves latest period; second returns the holder rows.
        fake_db.execute_query.side_effect = [
            [{"p": "2026-Q1"}],
            [
                {"cusip": "67066G104", "filer_cik": "1", "filer_name": "Big",
                 "period": "2026-Q1", "shares": 9, "value_usd": 900, "put_call": None},
                {"cusip": "67066G104", "filer_cik": "2", "filer_name": "Small",
                 "period": "2026-Q1", "shares": 1, "value_usd": 100, "put_call": None},
            ],
        ]
        with patch.object(tfi, "_db", return_value=fake_db):
            rows = tfi.holders_for_cusip("67066G104")
        assert [r["filer_name"] for r in rows] == ["Big", "Small"]

    def test_holders_for_cusip_no_period(self):
        fake_db = MagicMock()
        fake_db.execute_query.return_value = [{"p": None}]
        with patch.object(tfi, "_db", return_value=fake_db):
            assert tfi.holders_for_cusip("67066G104") == []

    def test_holders_for_cusip_empty_input(self):
        assert tfi.holders_for_cusip([]) == []


# ---------------------------------------------------------------------------
# Ingest parser / aggregator (pure)
# ---------------------------------------------------------------------------


class TestIngestParsers:
    def test_parse_submission(self):
        rows = [
            {"ACCESSION_NUMBER": "acc-1", "CIK": "0001324279", "PERIODOFREPORT": "31-MAR-2023"},
            {"ACCESSION_NUMBER": "", "CIK": "x", "PERIODOFREPORT": "31-MAR-2023"},
        ]
        out = ingest.parse_submission(rows)
        assert out == {"acc-1": ("0001324279", "2023-Q1")}

    def test_parse_coverpage(self):
        rows = [{"ACCESSION_NUMBER": "acc-1", "FILINGMANAGER_NAME": "Bank of Israel"}]
        assert ingest.parse_coverpage(rows) == {"acc-1": "Bank of Israel"}

    def test_aggregate_excludes_options_and_sums(self):
        submission = {"acc-1": ("000111", "2023-Q1")}
        coverpage = {"acc-1": "Manager A"}
        info = [
            # two long rows, same (cusip, cik, period) → summed
            {"ACCESSION_NUMBER": "acc-1", "CUSIP": "594918104", "NAMEOFISSUER": "MICROSOFT",
             "FIGI": "", "VALUE": "100", "SSHPRNAMT": "10", "PUTCALL": ""},
            {"ACCESSION_NUMBER": "acc-1", "CUSIP": "594918104", "NAMEOFISSUER": "MICROSOFT",
             "FIGI": "", "VALUE": "50", "SSHPRNAMT": "5", "PUTCALL": ""},
            # an option row → excluded
            {"ACCESSION_NUMBER": "acc-1", "CUSIP": "594918104", "NAMEOFISSUER": "MICROSOFT",
             "FIGI": "", "VALUE": "999", "SSHPRNAMT": "99", "PUTCALL": "Call"},
        ]
        # value_unit thousands → x1000
        holdings, cusip_map, stats = ingest.aggregate_infotable(
            info, submission, coverpage, "thousands"
        )
        assert stats["read"] == 3
        assert stats["options_skipped"] == 1
        assert len(holdings) == 1
        cusip, cik, filer_name, period, shares, value_usd, put_call, source, _ = holdings[0]
        assert (cusip, cik, period) == ("594918104", "000111", "2023-Q1")
        assert shares == 15
        assert value_usd == 150_000  # (100+50) * 1000
        assert put_call is None
        assert source == tfi.SOURCE_BULK
        assert len(cusip_map) == 1
        assert cusip_map[0][0] == "594918104"

    def test_aggregate_skips_rows_without_submission(self):
        info = [
            {"ACCESSION_NUMBER": "missing", "CUSIP": "594918104", "NAMEOFISSUER": "X",
             "FIGI": "", "VALUE": "100", "SSHPRNAMT": "10", "PUTCALL": ""},
        ]
        holdings, cusip_map, stats = ingest.aggregate_infotable(info, {}, {}, "usd")
        assert holdings == []
        assert stats["no_submission"] == 1

    def test_aggregate_value_usd_passthrough(self):
        submission = {"a": ("c", "2023-Q2")}
        info = [
            {"ACCESSION_NUMBER": "a", "CUSIP": "037833100", "NAMEOFISSUER": "APPLE",
             "FIGI": "", "VALUE": "4360", "SSHPRNAMT": "8", "PUTCALL": ""},
        ]
        holdings, _, _ = ingest.aggregate_infotable(info, submission, {"a": "Mgr"}, "usd")
        # whole-USD dataset → no x1000
        assert holdings[0][5] == 4360


class TestRecentQuarters:
    def test_recent_quarters_descending(self):
        from datetime import date

        qs = ingest.recent_quarters(date(2026, 5, 15), count=3)
        assert qs == ["2026q2", "2026q1", "2025q4"]

    def test_dataset_url(self):
        url = ingest.dataset_url("2025q4")
        assert url.endswith("/2025q4_form13f.zip")
