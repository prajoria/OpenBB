"""AC-P5-4: report() orchestrator writes files + returns ReportManifest.

Covers:
  * format='all' writes MD + JSON (xlsx gracefully skipped in P5.1 with
    a warning; P5.2 wires it)
  * format='md' writes only MD
  * format='json' writes only JSON
  * idempotent overwrite emits WARN (review S5)
  * full-path Decimal precision (review #3): 12-digit Decimal survives
    the FULL report(format='json') pipeline
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest


class TestReportManifest:
    def test_format_all_writes_md_and_json(self, tmp_path, monkeypatch):
        # Stub the journal read so no live disk / MySQL involvement
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713",
            format="all",
            output_dir=tmp_path,
        )
        assert manifest.md_path is not None
        assert manifest.json_path is not None
        assert manifest.md_path.exists()
        assert manifest.json_path.exists()
        # P5.1 shipping: xlsx skipped with a warning; xlsx_path stays None.
        # (P5.2 wires the real builder; when that lands the warning
        # disappears + xlsx_path becomes a real Path.)
        if manifest.xlsx_path is None:
            assert any("xlsx" in w.lower() for w in manifest.warnings)

    def test_format_md_writes_only_md(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713",
            format="md",
            output_dir=tmp_path,
        )
        assert manifest.md_path is not None
        assert manifest.json_path is None
        assert manifest.xlsx_path is None

    def test_format_json_writes_only_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713",
            format="json",
            output_dir=tmp_path,
        )
        assert manifest.md_path is None
        assert manifest.json_path is not None
        assert manifest.xlsx_path is None

    def test_manifest_session_events_count_reflects_input(self, tmp_path, monkeypatch):
        from openbb_fmp_trading.models.journal_events import (
            OrderEvent,
            SessionStartEvent,
        )

        events = [
            SessionStartEvent(
                ts=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={},
            ),
            OrderEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={},
            ),
        ]
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter(events),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(session_id="s20260713", format="md", output_dir=tmp_path)
        assert manifest.session_events_count == 2


class TestIdempotentOverwrite:
    """Review S5: design §6.2 documents idempotent-overwrite behavior."""

    def test_second_call_overwrites_and_warns(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        caplog.set_level(logging.WARNING)
        report(session_id="s20260713", format="md", output_dir=tmp_path)
        first_mtime = (tmp_path / "end_of_day.md").stat().st_mtime
        time.sleep(0.01)  # ensure mtime tick
        report(session_id="s20260713", format="md", output_dir=tmp_path)
        second_mtime = (tmp_path / "end_of_day.md").stat().st_mtime
        assert second_mtime > first_mtime  # file was rewritten
        # WARN emitted at least once about the overwrite
        assert any("overwrit" in r.message.lower() for r in caplog.records)


class TestFullPathDecimalPrecision:
    """Review finding #3: prove Decimal survives the FULL
    report(format='json') path — not just build_json_manifest in isolation.
    Regression against pydantic v2 coercing Decimal->float silently
    somewhere upstream of json.dumps."""

    def test_decimal_precision_survives_report_json_path(
        self, tmp_path, monkeypatch
    ):
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            SessionEndEvent,
        )

        # Decimal that CANNOT be exactly represented as float
        precise_pnl = Decimal("1234.56789012345")
        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"symbol": "MSFT", "realized_pnl": str(precise_pnl)},
            ),
            SessionEndEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s",
                payload={"flat_at_close": True, "realized_pnl": str(precise_pnl)},
            ),
        ]

        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter(events),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713", format="json", output_dir=tmp_path
        )
        raw = json.loads(manifest.json_path.read_text(encoding="utf-8"))

        # Precision preserved end-to-end: raw JSON has full digits
        assert raw["metrics"]["realized_pnl"] == "1234.56789012345", (
            f"Decimal precision lost: got {raw['metrics']['realized_pnl']!r}. "
            f"Check model_config.json_encoders on SessionMetrics AND "
            f"json_builder's default=str fallback path (review finding #3)."
        )


class TestSessionDateResolution:
    """Review S3: _parse_session_date raises on failure — never defaults."""

    def test_prefers_session_start_event_date(self, tmp_path, monkeypatch):
        """Explicit session_start event date wins over session_id parse."""
        from openbb_fmp_trading.models.journal_events import SessionStartEvent

        events = [
            SessionStartEvent(
                ts=datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc),
                session_id="s99999999999999",  # nonsense; the ts wins
                payload={},
            ),
        ]
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter(events),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s99999999999999", format="md", output_dir=tmp_path
        )
        # Date extracted from the event, not the malformed session_id
        assert manifest.session_date.isoformat() == "2026-07-06"

    def test_falls_back_to_session_id_parse(self, tmp_path, monkeypatch):
        """No session_start event — parse from session_id."""
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        manifest = report(
            session_id="s20260713143025", format="md", output_dir=tmp_path
        )
        assert manifest.session_date.isoformat() == "2026-07-13"

    def test_raises_on_unparseable_session_id(self, tmp_path, monkeypatch):
        """S3 fix: no silent default to today() when session_id is malformed."""
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        with pytest.raises(ValueError, match="Cannot determine session_date"):
            report(
                session_id="not-a-valid-id", format="md", output_dir=tmp_path
            )
