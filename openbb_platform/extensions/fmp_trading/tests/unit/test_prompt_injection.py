"""AC-agent-8 (A1, P0): prompt-injection defense stack.

Covers the two deterministic post-LLM defenses:

  L1  tradable-universe allowlist  (agent.tradable_universe)
  L2  watchlist size cap           (MAX_WATCHLIST_SIZE)

The other three layers from design-spec §6.6:

  L3  clamp-only risk overrides    -> test_risk_clamp.py
  L4  prompt-level delimiting      -> asserted in the prompt file's own tests
  L5  red-team live-input tests    -> deferred to a live-recording fixture

Every rejection lands in the journal as PromptInjectionRejectedEvent for
audit — this file asserts both the rejection AND the audit trail.
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


def _tool_call_with_watchlist(watchlist: list[str]):
    from openbb_fmp_trading.agent.backend import ToolCall

    return ToolCall(
        name="submit_daily_plan",
        args={
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": watchlist,
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": {},
            "thesis": "t",
            "agent_backend": "claude",
        },
    )


class TestTradableUniverseAllowlist:
    """L1: symbols outside the universe are dropped."""

    def test_out_of_universe_symbol_dropped(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        # MSFT + AAPL are in the starter universe; ATTACKER_TICKER is not.
        backend.run_turn.return_value = _tool_call_with_watchlist(
            ["MSFT", "ATTACKER_TICKER_XYZ", "AAPL"]
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert plan.watchlist == ["MSFT", "AAPL"]
        assert "ATTACKER_TICKER_XYZ" not in plan.watchlist

    def test_empty_after_drop_triggers_fallback(self, monkeypatch):
        """L1 escalation: if every symbol was out-of-universe, fall back."""
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
        backend.run_turn.return_value = _tool_call_with_watchlist(
            ["ATTACKER_1", "ATTACKER_2", "ATTACKER_3"]
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Empty watchlist -> fallback path
        assert plan.is_deterministic_fallback is True

    def test_drop_journals_prompt_injection_rejected(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import (
            PromptInjectionRejectedEvent,
        )

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call_with_watchlist(
            ["MSFT", "ATTACKER_TICKER_XYZ"]
        )
        journal = MagicMock()

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        rejections = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], PromptInjectionRejectedEvent)
        ]
        universe_rejections = [
            r for r in rejections
            if r.payload["defense_layer"] == "tradable_universe"
        ]
        assert len(universe_rejections) == 1
        assert "ATTACKER_TICKER_XYZ" in universe_rejections[0].payload["offending_value"]


class TestWatchlistSizeCap:
    """L2: watchlist truncated to MAX_WATCHLIST_SIZE=30."""

    def test_oversized_watchlist_truncated(self):
        from openbb_fmp_trading.agent.pre_open import (
            MAX_WATCHLIST_SIZE,
            PreOpenAgentTurn,
        )

        backend = MagicMock()
        # 40 valid symbols — first 30 kept, last 10 dropped.
        # Use symbols known to be in the starter universe.
        symbols = [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "AVGO", "ORCL", "ADBE", "CRM", "AMD", "NFLX", "INTC", "CSCO",
            "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT", "MU", "PANW",
            "JPM", "BAC", "WFC", "GS", "MS", "C",
            # 30 above; 10 below get truncated
            "USB", "PNC", "AXP", "SCHW", "BLK", "SPGI", "MMC", "CB", "PGR", "ICE",
        ]
        assert len(symbols) == 40

        backend.run_turn.return_value = _tool_call_with_watchlist(symbols)

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        assert len(plan.watchlist) == MAX_WATCHLIST_SIZE
        assert plan.watchlist == symbols[:MAX_WATCHLIST_SIZE]

    def test_truncation_journals_prompt_injection_rejected(self):
        from openbb_fmp_trading.agent.pre_open import (
            MAX_WATCHLIST_SIZE,
            PreOpenAgentTurn,
        )
        from openbb_fmp_trading.models.journal_events import (
            PromptInjectionRejectedEvent,
        )

        backend = MagicMock()
        symbols = [
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA",
            "AVGO", "ORCL", "ADBE", "CRM", "AMD", "NFLX", "INTC", "CSCO",
            "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT", "MU", "PANW",
            "JPM", "BAC", "WFC", "GS", "MS", "C",
            "USB", "PNC", "AXP",
        ]
        backend.run_turn.return_value = _tool_call_with_watchlist(symbols)
        journal = MagicMock()

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=journal,
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        rejections = [
            c.args[0]
            for c in journal.write.call_args_list
            if isinstance(c.args[0], PromptInjectionRejectedEvent)
        ]
        size_rejections = [
            r for r in rejections
            if r.payload["defense_layer"] == "watchlist_size_cap"
        ]
        assert len(size_rejections) == 1
        # 33 - 30 = 3 dropped
        assert size_rejections[0].payload["offending_value"] == ["USB", "PNC", "AXP"]


class TestRedTeamPoisonedInputs:
    """L5 (partial): the classic 'ignore-instructions' string doesn't
    survive the defense stack.

    The LLM output IS the attack simulation here — we bypass the model
    entirely and directly hand the turn wrapper a poisoned tool-call
    args dict. The defenses run regardless of upstream provenance.
    """

    def test_poisoned_watchlist_containing_penny_stock(self, monkeypatch):
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
        # Simulate a poisoned news headline that talked the model into
        # emitting a penny-stock ticker + a legit large-cap.
        backend.run_turn.return_value = _tool_call_with_watchlist(
            ["PENNY1", "PENNY2", "MSFT"]
        )
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Penny stocks dropped by tradable_universe; MSFT survives.
        assert plan.watchlist == ["MSFT"]
        assert plan.is_deterministic_fallback is False
