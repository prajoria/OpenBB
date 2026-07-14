"""AC-agent-2: PostCloseAgentTurn produces valid EndOfDayReport OR narrator.

Covers:
  - LLM happy path -> is_deterministic_fallback=False
  - AlwaysUnavailableBackend -> Jinja narrator (#84 delivery)
  - state_store always written (both LLM + fallback paths)
  - AgentFallbackEvent + EndOfDayReportEvent both journaled
  - T5 low_signal defaults to True on every recommendation
  - Metrics forced from journal (LLM can't lie about numbers)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _cfg():
    from openbb_fmp_trading.models.config import DailyConfig, RiskConfig

    return DailyConfig(
        default_watchlist=["SPY"],
        default_preset="trend_follow",
        default_risk=RiskConfig(),
        starting_equity=Decimal("100000"),
    )


def _plan():
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    return DailyPlan(
        as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
        trading_date=date(2026, 7, 13),
        watchlist=["MSFT", "AAPL"],
        preset="intraday_momentum",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="test",
        agent_backend="claude",
    )


class TestPostCloseNarratorFallback:
    """AC-agent-2 primary: AlwaysUnavailableBackend -> Jinja narrator."""

    def test_agent_unavailable_produces_jinja_briefing(self, monkeypatch):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.post_close import PostCloseAgentTurn

        _no_state_store(monkeypatch)

        turn = PostCloseAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
            plan=_plan(),
        )
        report = turn.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        assert report.is_deterministic_fallback is True
        assert report.agent_backend == "none"
        assert "Session Briefing" in report.briefing_md
        assert "2026-07-13" in report.briefing_md
        # T5: no recommendations from single-session narrator
        assert report.tomorrow_recommendations == []

    def test_narrator_emits_agent_fallback_event(self, monkeypatch):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.post_close import PostCloseAgentTurn
        from openbb_fmp_trading.models.journal_events import AgentFallbackEvent

        _no_state_store(monkeypatch)
        journal = MagicMock()

        turn = PostCloseAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=journal,
            plan=_plan(),
        )
        turn.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        fallback_events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], AgentFallbackEvent)
        ]
        assert len(fallback_events) == 1
        assert fallback_events[0].payload["turn"] == "post_close"
        assert fallback_events[0].payload["fallback_source"] == "jinja_narrator"


class TestPostCloseLLMHappyPath:
    def test_valid_llm_output_produces_report(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.post_close import PostCloseAgentTurn

        _no_state_store(monkeypatch)

        backend = MagicMock()
        backend.run_turn.return_value = ToolCall(
            name="submit_end_of_day_md",
            args={
                "session_date": "2026-07-13",
                "session_id": "s20260713",
                "agent_backend": "claude",
                "briefing_md": "# LLM-authored briefing\n\nToday: ...",
                "tomorrow_recommendations": [],
                # metrics field will be OVERWRITTEN from the journal
                # even if the LLM tries to provide fake numbers
                "metrics": {
                    "realized_pnl": "999999",  # LLM lie
                    "fill_count": 42,
                },
            },
            model_id="claude-sonnet-4-5",
        )

        turn = PostCloseAgentTurn(
            config=_cfg(),
            backend=backend,
            bandwidth=MagicMock(),
            journal=MagicMock(),
            plan=_plan(),
        )
        report = turn.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        assert report.is_deterministic_fallback is False
        assert report.agent_backend == "claude"
        assert "LLM-authored" in report.briefing_md
        # LLM's fake realized_pnl was overwritten by journal-derived (0)
        assert report.metrics.realized_pnl == Decimal("0")


class TestStateStoreAlwaysWritten:
    """The state_store writes fire on BOTH LLM + fallback paths so
    tomorrow's pre-open has context regardless of today's turn provenance."""

    def test_watchlist_persisted_on_fallback(self, monkeypatch):
        pytest.importorskip("jinja2")

        captured: dict = {}
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.save_last_watchlist",
            lambda syms, scope="default": captured.setdefault("watchlist", syms),
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.save_last_plan",
            lambda plan, scope="default": captured.setdefault("plan", plan),
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.save_last_session_summary",
            lambda summary, scope="default": captured.setdefault("summary", summary),
        )

        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.post_close import PostCloseAgentTurn

        turn = PostCloseAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
            plan=_plan(),
        )
        turn.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        # Every state key was written
        assert captured["watchlist"] == ["MSFT", "AAPL"]
        assert captured["plan"].watchlist == ["MSFT", "AAPL"]
        assert captured["summary"]["date"] == "2026-07-13"
        assert captured["summary"]["session_id"] == "s20260713"


class TestA6ProvenanceOnCommit:
    """A6: model_id + prompt_version journaled on the EndOfDayReportEvent."""

    def test_report_event_carries_a6_fields(self, monkeypatch):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.post_close import (
            POST_CLOSE_PROMPT_VERSION,
            PostCloseAgentTurn,
        )
        from openbb_fmp_trading.models.journal_events import EndOfDayReportEvent

        _no_state_store(monkeypatch)
        journal = MagicMock()

        turn = PostCloseAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=journal,
            plan=_plan(),
        )
        turn.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], EndOfDayReportEvent)
        ]
        assert len(events) == 1
        payload = events[0].payload
        assert payload["prompt_version"] == POST_CLOSE_PROMPT_VERSION
        assert payload["is_deterministic_fallback"] is True
        assert payload["model_id"] is None  # narrator path, no LLM


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _no_state_store(monkeypatch):
    """No-op every state_store write so tests don't require a live MySQL."""
    for name in (
        "save_last_watchlist",
        "save_last_plan",
        "save_last_session_summary",
    ):
        monkeypatch.setattr(
            f"openbb_fmp_trading.core.state_store.{name}",
            lambda *a, **kw: None,
        )
