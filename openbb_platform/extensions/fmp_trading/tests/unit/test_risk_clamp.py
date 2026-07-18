"""AC-agent-7 (T1, P0): clamp-only risk overrides.

The LLM must NEVER be able to loosen risk beyond ``DailyConfig.default_risk``.
Every loosening attempt is either clipped (single-field) or triggers a
retry-once + fallback (any loosening at all).

Why so strict: the LLM's context includes attacker-influenceable news
strings. A poisoned headline could talk the model into
``max_position_size_pct_equity=99``. The clamp validator + fallback
funnel is the load-bearing defense against that class of attack.
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
        default_risk=RiskConfig(),  # standard defaults
        starting_equity=Decimal("100000"),
    )


def _tool_call_with_risk(risk_updates: dict, watchlist=("MSFT",)):
    """Build a submit_daily_plan tool-call arg dict with LLM-emitted
    session_risk overrides."""
    from openbb_fmp_trading.agent.backend import ToolCall
    from openbb_fmp_trading.models.config import RiskConfig

    base_risk = RiskConfig().model_dump()
    base_risk.update(risk_updates)
    return ToolCall(
        name="submit_daily_plan",
        args={
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": list(watchlist),
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": base_risk,
            "thesis": "t",
            "agent_backend": "claude",
        },
        model_id="claude-sonnet-4-5",
    )


class TestClampSizeFields:
    """Fields where LARGER = LOOSER: max_position_size, max_notional, etc."""

    @pytest.mark.parametrize("field,loosened_value", [
        ("max_position_size_pct_equity", 50.0),   # default 10.0
        ("max_notional_pct_equity", 90.0),        # default 30.0
        ("max_open_positions", 100),              # default 5
        ("max_positions_per_sector", 20),         # default 2
        ("cooldown_after_stopout_min", 0),        # default 30 (0 = no wait = looser)
    ])
    def test_loosened_field_triggers_fallback(self, field, loosened_value, monkeypatch):
        """Any loosening of these fields must trigger the fallback path.

        Security-review #1 fix: ``cooldown_after_stopout_min`` is
        smaller-is-looser (a 0-minute cooldown means no wait between
        re-entries after a stopout, which is less restrictive than a
        30-minute default). The impl now handles this in the same
        negative-direction branch as ``day_dd_pct``.
        """
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
        backend.run_turn.return_value = _tool_call_with_risk({field: loosened_value})

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Loosening triggers the fallback path (RiskOverrideLoosening -> fallback)
        assert plan.is_deterministic_fallback is True


class TestClampNegativeField:
    """day_dd_pct is negative; MORE NEGATIVE = looser (bigger allowed loss)."""

    def test_more_negative_day_dd_triggers_fallback(self, monkeypatch):
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
        # Default day_dd_pct = -2.0. LLM tries -10.0 (allows 10% loss = looser).
        backend.run_turn.return_value = _tool_call_with_risk({"day_dd_pct": -10.0})

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is True


class TestClampTimeField:
    """flat_by_close_time_et: LATER (bigger string) = looser."""

    def test_later_flat_by_close_time_triggers_fallback(self, monkeypatch):
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
        # Default 15:50. LLM tries 15:58 (looser = later cutoff).
        backend.run_turn.return_value = _tool_call_with_risk(
            {"flat_by_close_time_et": "15:58"}
        )

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is True


class TestTighteningAllowed:
    """Tightening (smaller position size, more-negative day_dd_pct threshold,
    tighter flat-by-close) MUST pass through."""

    def test_tighter_max_position_size_passes_through(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        # Default 10.0; LLM tightens to 5.0 (smaller position)
        backend.run_turn.return_value = _tool_call_with_risk(
            {"max_position_size_pct_equity": 5.0}
        )

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is False
        assert plan.session_risk.max_position_size_pct_equity == 5.0

    def test_earlier_flat_by_close_passes_through(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        # Default 15:50; LLM tightens to 15:30
        backend.run_turn.return_value = _tool_call_with_risk(
            {"flat_by_close_time_et": "15:30"}
        )

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        plan = turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))
        assert plan.is_deterministic_fallback is False
        assert plan.session_risk.flat_by_close_time_et == "15:30"


class TestClampJournalsRejection:
    """Every clamp event journals a PromptInjectionRejectedEvent for audit."""

    def test_loosening_journals_prompt_injection_rejected(self, monkeypatch):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import (
            PromptInjectionRejectedEvent,
        )

        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_watchlist",
            lambda scope="default": None,
        )
        monkeypatch.setattr(
            "openbb_fmp_trading.core.state_store.load_last_session_summary",
            lambda scope="default": None,
        )

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call_with_risk(
            {"max_position_size_pct_equity": 99.0}
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
        # The risk-clamp defense emits an AGGREGATE rejection with a
        # `fields` list-of-dicts (not a single-field `field`) so downstream
        # JSON consumers see a stable shape. See pre_open._journal_clamp_aggregate.
        assert any(
            r.payload["defense_layer"] == "risk_clamp"
            and any(
                v.get("field") == "max_position_size_pct_equity"
                and v.get("offending_value") == 99.0
                for v in r.payload.get("fields", [])
            )
            for r in rejections
        )
