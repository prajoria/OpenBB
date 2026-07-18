"""AC-P5-4: report() orchestrator writes files + returns ReportManifest.

Covers:
  * format='all' writes MD + JSON (xlsx gracefully skipped in P5.1 with
    a warning; P5.2 wires it)
  * format='md' writes only MD
  * format='json' writes only JSON
  * idempotent overwrite requires explicit overwrite=True flag
    (review S5 + security-review round 1)
  * full-path Decimal precision (review #3): 12-digit Decimal survives
    the FULL report(format='json') pipeline
  * output_dir jail (security-review round 1 finding #1)
  * symlink write refusal (security-review round 1 finding #3)

All tests set FMP_TRADING_REPORTS_ROOT to tmp_path via monkeypatch so
they can write inside the jail without polluting the real Analysis/exports/.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest


@pytest.fixture(autouse=True)
def _jail_to_tmp(tmp_path, monkeypatch):
    """Set the reports jail to tmp_path for every test in this file.

    Also unlocks the techtrade excel_export absolute-path guard — pytest's
    ``tmp_path`` is always absolute, and the format="all" pipeline routes
    xlsx generation through techtrade's export which rejects absolute
    paths by default (security guard, documented escape hatch).
    """
    monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("TECHTRADE_EXPORT_ALLOW_ABSOLUTE", "1")
    return tmp_path


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
    """Review S5 + security-review round 1: idempotent overwrite requires
    the explicit ``overwrite=True`` flag (default is refuse-with-error)."""

    def test_second_call_without_overwrite_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        # Set the jail to tmp_path so output_dir under it validates
        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
        from openbb_fmp_trading.reporting.report import OutputExists, report

        output = tmp_path / "day1"
        report(session_id="s20260713", format="md", output_dir=output)
        # Second call without overwrite -> OutputExists
        with pytest.raises(OutputExists):
            report(session_id="s20260713", format="md", output_dir=output)

    def test_second_call_with_overwrite_true_warns(
        self, tmp_path, monkeypatch, caplog
    ):
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
        from openbb_fmp_trading.reporting.report import report

        output = tmp_path / "day1"
        caplog.set_level(logging.WARNING)
        report(
            session_id="s20260713", format="md", output_dir=output, overwrite=False
        )
        first_mtime = (output / "end_of_day.md").stat().st_mtime
        time.sleep(0.01)
        report(
            session_id="s20260713", format="md", output_dir=output, overwrite=True
        )
        second_mtime = (output / "end_of_day.md").stat().st_mtime
        assert second_mtime > first_mtime
        assert any("overwrit" in r.message.lower() for r in caplog.records)


class TestOutputDirJail:
    """Security-review round 1 finding #1: output_dir is jailed."""

    def test_output_dir_outside_jail_raises(self, tmp_path, monkeypatch):
        """A path outside FMP_TRADING_REPORTS_ROOT is rejected."""
        import sys

        # Cross-platform "outside jail" path
        outside = tmp_path / "outside"
        outside.mkdir()
        jail = tmp_path / "jail"
        jail.mkdir()
        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(jail))

        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import (
            OutputPathEscapesJail,
            report,
        )

        with pytest.raises(OutputPathEscapesJail):
            report(session_id="s20260713", format="md", output_dir=outside)

    def test_output_dir_inside_jail_accepted(self, tmp_path, monkeypatch):
        """Sanity: an in-jail path is accepted."""
        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import report

        in_jail = tmp_path / "day1"
        manifest = report(
            session_id="s20260713", format="md", output_dir=in_jail
        )
        assert manifest.md_path is not None
        assert manifest.md_path.exists()

    def test_symlink_writes_refused(self, tmp_path, monkeypatch):
        """Security-review finding #3: refuse to write through symlinks."""
        import os
        import sys

        if sys.platform == "win32":
            pytest.skip("Symlink creation on Windows requires admin/dev mode")

        monkeypatch.setenv("FMP_TRADING_REPORTS_ROOT", str(tmp_path))
        monkeypatch.setattr(
            "openbb_fmp_trading.reporting.journal_reader.read_session_events",
            lambda session_id, root=None: iter([]),
        )
        from openbb_fmp_trading.reporting.report import (
            OutputPathEscapesJail,
            report,
        )

        # Plant a symlink at the target file path
        output_dir = tmp_path / "day1"
        output_dir.mkdir()
        target_outside = tmp_path / "attacker_target"
        target_outside.write_text("original content", encoding="utf-8")
        (output_dir / "end_of_day.md").symlink_to(target_outside)

        with pytest.raises(OutputPathEscapesJail, match="symlink"):
            report(
                session_id="s20260713",
                format="md",
                output_dir=output_dir,
                overwrite=True,
            )
        # Target unchanged — the write was refused
        assert target_outside.read_text() == "original content"


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
