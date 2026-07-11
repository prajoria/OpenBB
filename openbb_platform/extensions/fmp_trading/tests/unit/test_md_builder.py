"""AC-P5-1: md_builder produces valid Markdown from events.

Two code paths — BOTH must have real assertions per review finding #1
(TDD honesty). No greening against stubs.

  1. include_agent_narrative=True AND EndOfDayReportEvent in events
     -> extract briefing_md verbatim from the event's
        payload["briefing_md_content"] (added in P5.0 Step 4)
  2. Otherwise -> render deterministic Jinja template using SessionMetrics
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest


class TestAgentNarrativePath:
    """Review finding #2: include_agent_narrative=True must produce the
    LLM's actual prose verbatim, NOT silently fall through."""

    def test_extracts_briefing_md_verbatim_when_present(self):
        """P5.0 Step 4 widened EndOfDayReportEvent to journal
        briefing_md_content. This test proves the extractor uses it."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        # Distinctive LLM prose we expect back verbatim
        llm_briefing = (
            "# Session Briefing — Q3 2026\n\n"
            "Today's rotation into semis was catalyzed by NVDA earnings; "
            "MSFT lagged into close due to CFO exit rumor.\n\n"
            "**Process observation:** G6 fired twice on out-sized entry "
            "attempts — sizing rules working as intended."
        )
        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={
                    "briefing_md_length": len(llm_briefing),
                    "briefing_md_content": llm_briefing,
                    "agent_backend": "claude",
                    "is_deterministic_fallback": False,
                },
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=True)

        # AC-P5-1 (real): LLM's distinctive prose survives byte-for-byte
        assert md == llm_briefing, (
            "include_agent_narrative=True must return the journaled "
            "briefing_md verbatim, not fall through to the template"
        )
        # Distinctive LLM sentence survives round-trip
        assert "rotation into semis" in md

    def test_falls_back_to_template_when_no_briefing_content(self):
        """Legacy events (pre-P5.0-Step-4) have no briefing_md_content —
        extractor returns None, template fallback fires."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={"briefing_md_length": 42, "agent_backend": "claude"},
                # NOTE: no briefing_md_content — legacy/corrupt event
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=True)
        # Template header appears (deterministic fallback fired)
        assert "Session Briefing" in md

    def test_include_agent_narrative_false_forces_template(self):
        """Even when briefing_md_content is present, False forces template."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        events = [
            EndOfDayReportEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s20260713",
                payload={
                    "briefing_md_length": 20,
                    "briefing_md_content": "# LLM prose — do NOT use",
                    "agent_backend": "claude",
                },
            ),
        ]
        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        md = build_md(events, metrics, include_agent_narrative=False)
        assert "LLM prose" not in md  # LLM content ignored
        assert "Session Briefing" in md  # template header present


class TestDeterministicTemplatePath:
    def test_renders_template_when_no_end_of_day_event(self):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        metrics = SessionMetrics(
            realized_pnl=Decimal("175.00"),
            fill_count=2,
            order_count=2,
            veto_counts_by_gate={"G1": 1},
        )
        md = build_md([], metrics, include_agent_narrative=False)
        assert "Session Briefing" in md
        assert "175.00" in md  # realized_pnl rendered
        assert "G1" in md      # veto gate name rendered

    def test_deterministic_output_stable_across_calls(self):
        """AC-P5-1: same input -> same output (no dict-order noise)."""
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.md_builder import build_md

        metrics = SessionMetrics(realized_pnl=Decimal("0"))
        a = build_md([], metrics)
        b = build_md([], metrics)
        assert a == b
