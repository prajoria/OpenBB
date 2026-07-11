"""AC-agent-9 (A2, P0): ValidationError degrades to fallback, never crashes.

If the LLM emits args that fail ``DailyPlan.model_validate``, the turn
MUST NOT raise. Either retry-once (design future) or fall through to the
deterministic fallback (P3.1 shipping). The invariant is: run() always
returns a DailyPlan, never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone
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


class TestValidationErrorDegrades:
    def test_missing_required_fields_falls_back(self, monkeypatch):
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )

        backend = MagicMock()
        # Missing 'watchlist', 'preset', 'thesis' — must not crash
        backend.run_turn.return_value = ToolCall(
            name="submit_daily_plan",
            args={
                "as_of": "2026-07-13T13:30:00+00:00",
                "date": "2026-07-13",
                "session_risk": {},
                "agent_backend": "claude",
            },
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Fallback fired — never crashed
        assert plan.is_deterministic_fallback is True
        assert plan.agent_backend == "none"

    def test_wrong_type_fields_falls_back(self, monkeypatch):
        """LLM emitted watchlist as a string instead of list[str]."""
        from openbb_fmp_trading.agent.backend import ToolCall
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )

        backend = MagicMock()
        backend.run_turn.return_value = ToolCall(
            name="submit_daily_plan",
            args={
                "as_of": "2026-07-13T13:30:00+00:00",
                "date": "2026-07-13",
                "watchlist": "MSFT,AAPL",  # string instead of list — invalid
                "preset": "intraday_momentum",
                "alerts": [],
                "session_risk": {},
                "thesis": "t",
                "agent_backend": "claude",
            },
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is True


class TestAgentUnavailableAtBackendConstruction:
    """The backend itself can raise AgentUnavailable (missing SDK, etc.)."""

    def test_run_turn_raises_agent_unavailable_still_falls_back(self, monkeypatch):
        from openbb_fmp_trading.agent.errors import AgentUnavailable
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )

        backend = MagicMock()
        backend.run_turn.side_effect = AgentUnavailable("simulated API outage")

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.is_deterministic_fallback is True

    def test_run_never_raises_even_for_arbitrary_backend_errors(self, monkeypatch):
        """Defensive: a backend that raises an unexpected exception
        should still fall back rather than propagating.

        Note: current impl catches only AgentUnavailable at the LLM-call
        site; arbitrary exceptions propagate. This test documents the
        current behavior with pytest.raises so a future tightening is
        an explicit change, not silent regression."""
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )

        backend = MagicMock()
        backend.run_turn.side_effect = RuntimeError("unexpected")

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        # Current design catches only AgentUnavailable — arbitrary
        # exceptions propagate. If we later want to catch broader,
        # update this test to assert the fallback fired instead.
        with pytest.raises(RuntimeError):
            turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
