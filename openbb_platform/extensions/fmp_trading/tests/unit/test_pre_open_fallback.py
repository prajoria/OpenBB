"""AC-agent-1: PreOpenAgentTurn produces valid DailyPlan OR falls back.

Covers the happy path + the two primary fallback triggers (AgentUnavailable,
missing state_store data). Full P0/P1 defense tests live in sibling files:

  - test_risk_clamp.py         AC-agent-7 (T1)
  - test_prompt_injection.py   AC-agent-8 (A1)
  - test_pre_open_validation_retry.py AC-agent-9 (A2)
  - test_bandwidth_reconciliation.py AC-agent-11 (A4)
  - test_preflight_prune.py    AC-agent-12 (T2)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


def _cfg():
    from openbb_fmp_trading.models.config import DailyConfig, RiskConfig

    return DailyConfig(
        default_watchlist=["SPY", "QQQ"],
        default_preset="trend_follow",
        default_risk=RiskConfig(),
        starting_equity=Decimal("100000"),
    )


class TestPreOpenSuccess:
    def test_valid_llm_output_produces_plan(self):
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = ToolCall(
            name="submit_daily_plan",
            args={
                "as_of": "2026-07-13T13:30:00+00:00",
                "date": "2026-07-13",
                "watchlist": ["MSFT", "AAPL"],  # both in tradable_universe
                "preset": "intraday_momentum",
                "alerts": [],
                "session_risk": {},  # defaults — T1-safe (no loosening)
                "thesis": "Momentum setup post-earnings.",
                "agent_backend": "claude",
            },
            model_id="claude-sonnet-4-5",
            input_tokens=1200,
            output_tokens=600,
        )
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=backend,
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.watchlist == ["MSFT", "AAPL"]
        assert plan.is_deterministic_fallback is False
        assert plan.agent_backend == "claude"
        assert plan.preset == "intraday_momentum"

    def test_success_journals_commit_with_a6_provenance(self):
        """A6: model_id + prompt_version land in the commit event."""
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.pre_open import (
            PRE_OPEN_PROMPT_VERSION,
            PreOpenAgentTurn,
        )
        from openbb_fmp_trading.models.journal_events import (
            DailyPlanCommittedEvent,
        )

        backend = MagicMock()
        backend.run_turn.return_value = ToolCall(
            name="submit_daily_plan",
            args={
                "as_of": "2026-07-13T13:30:00+00:00",
                "date": "2026-07-13",
                "watchlist": ["MSFT"],
                "preset": "intraday_momentum",
                "alerts": [], "session_risk": {},
                "thesis": "t", "agent_backend": "claude",
            },
            model_id="claude-sonnet-4-5",
        )
        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend, bandwidth=MagicMock(), journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        commits = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], DailyPlanCommittedEvent)
        ]
        assert len(commits) == 1
        assert commits[0].payload["model_id"] == "claude-sonnet-4-5"
        assert commits[0].payload["prompt_version"] == PRE_OPEN_PROMPT_VERSION
        assert commits[0].payload["is_deterministic_fallback"] is False


class TestPreOpenFallbackOnUnavailable:
    def test_agent_unavailable_falls_back_to_deterministic(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.is_deterministic_fallback is True
        assert plan.agent_backend == "none"
        # D4: same schema, different provenance
        assert isinstance(plan.watchlist, list)
        assert plan.preset  # non-empty
        # Fell back to default_watchlist since state_store is empty
        assert plan.watchlist == ["SPY", "QQQ"]

    def test_fallback_reads_last_watchlist_from_state_store(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": ["NVDA", "AMD"],
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.watchlist == ["NVDA", "AMD"]

    def test_fallback_halves_max_position_size_per_t3(self, monkeypatch):
        """T3: fallback plan halves max_position_size_pct_equity."""
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import (
            FALLBACK_RISK_HALVING_FACTOR,
            PreOpenAgentTurn,
        )

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )
        cfg = _cfg()
        default_size = cfg.default_risk.max_position_size_pct_equity

        turn = PreOpenAgentTurn(
            config=cfg,
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        expected = default_size * FALLBACK_RISK_HALVING_FACTOR
        assert plan.session_risk.max_position_size_pct_equity == pytest.approx(expected)


class TestT3LoudFallback:
    def test_fallback_emits_agent_fallback_event(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import AgentFallbackEvent

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )
        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        fallback_events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], AgentFallbackEvent)
        ]
        assert len(fallback_events) == 1
        payload = fallback_events[0].payload
        assert payload["turn"] == "pre_open"
        assert payload["source_error"] == "AgentUnavailable"
        assert payload["fallback_source"] == "default_config"
        assert payload["risk_halved"] is True

    def test_fallback_event_reports_state_store_source_when_watchlist_present(
        self, monkeypatch
    ):
        from openbb_fmp_trading.agent.backend import AlwaysUnavailableBackend
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import AgentFallbackEvent

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": ["NVDA"],
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )
        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        fallback_events = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], AgentFallbackEvent)
        ]
        assert fallback_events[0].payload["fallback_source"] == "state_store"
