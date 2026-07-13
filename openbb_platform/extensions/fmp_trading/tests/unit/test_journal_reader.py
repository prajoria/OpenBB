"""Unit tests for reporting/journal_reader.py (P5.0 / D6).

Verifies:
  * session_journal_path resolves session_id -> DEFAULT_JOURNAL_ROOT / <id>.ndjson
  * session_id sanitization rejects path-traversal attempts (incl. Windows S4)
  * Post-resolution is_relative_to check
  * read_journal_file yields JournalEvent objects
  * compute_metrics_from_events produces expected aggregates
  * pnl_source provenance (finding #4): authoritative_session_end
    vs summed_from_fills vs empty
  * total_commissions + total_slippage aggregation (finding #6)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest


class TestSessionJournalPath:
    def test_default_root_used_when_none(self):
        from openbb_fmp_trading.reporting.journal_reader import (
            DEFAULT_JOURNAL_ROOT,
            session_journal_path,
        )

        result = session_journal_path("s20260713")
        assert result == DEFAULT_JOURNAL_ROOT / "s20260713.ndjson"

    def test_explicit_root_respected(self, tmp_path):
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path

        result = session_journal_path("s20260713", root=tmp_path)
        assert result == tmp_path / "s20260713.ndjson"

    @pytest.mark.parametrize("bad_id", [
        "../etc/passwd",
        "..\\..\\Windows\\System32\\config",
        "a/b",
        "a\\b",
        ".hidden",
        "",
        "C:foo",       # review S4: Windows drive-relative
        "sess:id",     # embedded colon
    ])
    def test_bad_session_id_rejected(self, bad_id, tmp_path):
        """Security: session_id sanitization prevents path-traversal writes."""
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path

        with pytest.raises(ValueError):
            session_journal_path(bad_id, root=tmp_path)

    def test_normal_session_id_accepted(self, tmp_path):
        """Sanity: a well-formed session_id doesn't get rejected."""
        from openbb_fmp_trading.reporting.journal_reader import session_journal_path

        result = session_journal_path("s20260713143025", root=tmp_path)
        assert result == tmp_path / "s20260713143025.ndjson"


class TestReadJournalFile:
    def test_reads_ndjson_and_yields_events(self, tmp_path):
        """Round-trip: write a tiny NDJSON, read it back, count events.

        Uses openbb_core_journal.JournalEvent format (schema_version=1)."""
        from openbb_fmp_trading.reporting.journal_reader import read_journal_file

        path = tmp_path / "s.ndjson"
        path.write_text(
            '{"schema_version":1,"event_type":"session_start",'
            '"ts":"2026-07-13T13:30:00+00:00","session_id":"s20260713",'
            '"payload":{}}\n'
            '{"schema_version":1,"event_type":"session_end",'
            '"ts":"2026-07-13T20:15:00+00:00","session_id":"s20260713",'
            '"payload":{"flat_at_close":true}}\n',
            encoding="utf-8",
        )
        events = list(read_journal_file(path))
        assert len(events) == 2
        # Order-preserving
        assert events[0].event_type == "session_start"
        assert events[1].event_type == "session_end"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        from openbb_fmp_trading.reporting.journal_reader import read_journal_file

        with pytest.raises(FileNotFoundError):
            list(read_journal_file(tmp_path / "does-not-exist.ndjson"))

    def test_malformed_line_skipped_not_raised(self, tmp_path):
        """JournalReader.stream() silently skips malformed lines (+ WARN log).
        This test locks that contract so we don't accidentally change it."""
        from openbb_fmp_trading.reporting.journal_reader import read_journal_file

        path = tmp_path / "s.ndjson"
        path.write_text(
            '{"schema_version":1,"event_type":"session_start",'
            '"ts":"2026-07-13T13:30:00+00:00","session_id":"s","payload":{}}\n'
            'this is not valid JSON {[\n'
            '{"schema_version":1,"event_type":"session_end",'
            '"ts":"2026-07-13T20:15:00+00:00","session_id":"s","payload":{}}\n',
            encoding="utf-8",
        )
        events = list(read_journal_file(path))
        # Malformed line silently skipped; the two valid ones survive
        assert len(events) == 2
        assert [e.event_type for e in events] == ["session_start", "session_end"]


class TestComputeMetricsFromEvents:
    """Refactor contract + review finding #4 (pnl_source) + #6 (cost drag)."""

    def test_empty_journal_produces_zero_metrics(self):
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        metrics = compute_metrics_from_events([])
        assert metrics.realized_pnl == Decimal("0")
        assert metrics.pnl_source == "empty"
        assert metrics.fill_count == 0
        assert metrics.order_count == 0
        assert metrics.veto_counts_by_gate == {}
        assert metrics.total_commissions == Decimal("0")
        assert metrics.total_slippage == Decimal("0")

    def test_session_end_authoritative_overrides_fill_sum(self):
        """Finding #4: session_end.realized_pnl wins; pnl_source flags it."""
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            SessionEndEvent,
        )
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "150.00"},
            ),
            SessionEndEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "175.00", "flat_at_close": True},
            ),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.realized_pnl == Decimal("175.00")
        assert metrics.pnl_source == "authoritative_session_end"
        assert metrics.fill_count == 1

    def test_summed_from_fills_when_no_session_end(self):
        """Finding #4: without session_end, fall back to summing fills
        and flag the provenance so the operator knows it's reconstructed."""
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "50.00"},
            ),
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 5, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "100.00"},
            ),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.realized_pnl == Decimal("150.00")
        assert metrics.pnl_source == "summed_from_fills"
        assert metrics.fill_count == 2

    def test_counts_orders_and_vetoes_by_gate(self):
        from datetime import datetime, timezone
        from openbb_fmp_trading.models.journal_events import (
            OrderEvent,
            VetoEvent,
        )
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            OrderEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={},
            ),
            OrderEvent(
                ts=datetime(2026, 7, 13, 14, 5, tzinfo=timezone.utc),
                session_id="s",
                payload={},
            ),
            VetoEvent(
                ts=datetime(2026, 7, 13, 14, 10, tzinfo=timezone.utc),
                session_id="s",
                payload={"gate": "G1"},
            ),
            VetoEvent(
                ts=datetime(2026, 7, 13, 14, 15, tzinfo=timezone.utc),
                session_id="s",
                payload={"gate": "G1"},
            ),
            VetoEvent(
                ts=datetime(2026, 7, 13, 14, 20, tzinfo=timezone.utc),
                session_id="s",
                payload={"reason_code": "R42"},  # fallback to reason_code
            ),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.order_count == 2
        assert metrics.veto_counts_by_gate == {"G1": 2, "R42": 1}

    def test_cost_drag_aggregated_across_fills(self):
        """Finding #6: total_commissions + total_slippage surface headline
        cost drag."""
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"commission": "1.00", "slippage": "0.10"},
            ),
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 5, tzinfo=timezone.utc),
                session_id="s",
                payload={"commission": "1.00", "slippage": "0.20"},
            ),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.total_commissions == Decimal("2.00")
        assert metrics.total_slippage == Decimal("0.30")

    def test_decimal_precision_preserved_through_summing(self):
        """P2 + review #3: Decimal summation preserves precision."""
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        # These values, summed as float, would produce a 17-decimal
        # IEEE754 artifact. As Decimal they stay exact.
        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "0.10"},
            ),
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 5, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "0.20"},
            ),
        ]
        metrics = compute_metrics_from_events(events)
        assert metrics.realized_pnl == Decimal("0.30")
        # Sanity: NOT the float artifact "0.30000000000000004"
        assert str(metrics.realized_pnl) == "0.30"
