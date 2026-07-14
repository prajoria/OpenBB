"""AC-agent-12 (T2, P1): 09:25 ET pre-flight prune.

P3.1 shipping: verifies the seam is in place (``_preflight_prune`` is
called on non-fallback plans and returns unchanged for now). The full
implementation — drop halted / gapped / illiquid symbols using
``obb.fmp_trading.quote_batch`` + session-status filters — is a
follow-up bead. This test locks the current no-op contract so the
follow-up upgrade is an explicit test change, not a silent behavior
shift.
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


def _tool_call(watchlist=("MSFT", "AAPL")):
    from openbb_fmp_trading.agent.backend import ToolCall

    return ToolCall(
        name="submit_daily_plan",
        args={
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": list(watchlist),
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": {},
            "thesis": "t",
            "agent_backend": "claude",
        },
    )


class TestPreflightPruneSeam:
    def test_preflight_prune_called_on_non_fallback_plan(self, monkeypatch):
        """The seam runs — even in P3.1's no-op form we want a test that
        proves the method fires so the follow-up upgrade knows where to
        insert logic without introducing a NEW code path."""
        from openbb_fmp_trading.agent import pre_open as pre_open_mod
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call()

        calls: list = []
        original = PreOpenAgentTurn._preflight_prune

        def _spy(self, plan, as_of):
            calls.append((plan.watchlist, as_of))
            return original(self, plan, as_of)

        monkeypatch.setattr(PreOpenAgentTurn, "_preflight_prune", _spy)

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert len(calls) == 1
        assert calls[0][0] == ["MSFT", "AAPL"]

    def test_preflight_prune_skipped_on_fallback_plan(self, monkeypatch):
        """Fallback plans already ran through a conservative universe;
        double-pruning would be redundant and could empty an already-safe
        list."""
        from openbb_fmp_trading.agent import pre_open as pre_open_mod
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

        calls: list = []
        original = PreOpenAgentTurn._preflight_prune

        def _spy(self, plan, as_of):
            calls.append(plan)
            return original(self, plan, as_of)

        monkeypatch.setattr(PreOpenAgentTurn, "_preflight_prune", _spy)

        turn = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.is_deterministic_fallback is True
        assert calls == []  # skipped on fallback path

    def test_preflight_prune_returns_plan_unchanged_in_p31(self):
        """Contract lock: P3.1 ships a no-op _preflight_prune. The
        follow-up bead that adds real gap/halt/liquidity filters must
        also update this test."""
        from datetime import date
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.config import RiskConfig
        from openbb_fmp_trading.models.plan import DailyPlan

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=MagicMock(),
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = DailyPlan(
            as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
            trading_date=date(2026, 7, 13),
            watchlist=["MSFT", "AAPL"],
            preset="intraday_momentum",
            alerts=[],
            session_risk=RiskConfig(),
            thesis="t",
            agent_backend="claude",
        )
        result = turn._preflight_prune(
            plan, datetime(2026, 7, 13, 13, 25, tzinfo=timezone.utc)
        )
        assert result is plan  # no-op returns the same object
