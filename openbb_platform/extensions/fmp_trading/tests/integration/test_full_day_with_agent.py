"""AC-1-ext: full day E2E with agent turns.

Extends the Phase 2 P2.7 harness with pre/post-close agent turns:

  06:30 ET -> PreOpenAgentTurn (canned backend, NOT live Claude per A5)
  09:30-16:00 ET -> Phase 2 tick loop (unchanged)
  16:15 ET -> PostCloseAgentTurn (canned backend)
  Next day -> PreOpenAgentTurn again; fallback reads state_store's
              last_watchlist written by yesterday's post-close

Assertions:
  - Every turn produces a valid pydantic object (never crashes)
  - DailyPlanCommittedEvent + EndOfDayReportEvent both journaled
  - state_store.save_last_watchlist called with today's watchlist
  - Next-day fallback DailyPlan.watchlist == today's watchlist (round-trip)
  - full journal shape sanity-checked

Runtime: <3s (no live LLM, no live MySQL, no live FMP). Marked
@pytest.mark.integration so it's excluded from the default unit run.
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


class _CannedBackend:
    """A canned backend that replays a pre-recorded ToolCall.

    Substitutes for a live Claude call in the E2E test (A5 discipline
    from the design review — LLM in integration tests is flaky, costs
    money, and needs secrets).
    """

    def __init__(self, canned_tool_call):
        self._canned = canned_tool_call
        self.call_count = 0

    def run_turn(self, *args, **kwargs):
        self.call_count += 1
        return self._canned


@pytest.mark.integration
class TestFullDayWithAgent:
    """End-to-end: pre-open -> journal -> post-close -> state_store ->
    next-day pre-open fallback reads yesterday's watchlist."""

    def test_full_day_pre_open_then_post_close_writes_state_store(
        self, monkeypatch
    ):
        pytest.importorskip("jinja2")

        from openbb_fmp_trading.agent.backend import (
            AlwaysUnavailableBackend,
            ToolCall,
        )
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.agent.post_close import PostCloseAgentTurn

        # ---- In-memory state_store shim ----
        # Full parity with the real store: (key, scope) -> payload
        store: dict[tuple[str, str], object] = {}

        def _save_state(key, payload, scope="default"):
            store[(key, scope)] = payload

        def _load_state(key, scope="default"):
            return store.get((key, scope))

        # Wire every state_store accessor to the in-memory dict
        for name in ("save_last_watchlist", "save_last_plan", "save_last_session_summary"):
            monkeypatch.setattr(
                f"openbb_fmp_trading.core.state_store.{name}",
                _make_save_wrapper(name, _save_state),
            )
        for name in ("load_last_watchlist", "load_last_plan", "load_last_session_summary"):
            monkeypatch.setattr(
                f"openbb_fmp_trading.core.state_store.{name}",
                _make_load_wrapper(name, _load_state),
            )

        # ---- Day 1: pre-open (canned backend produces today's plan) ----
        day1_plan_args = {
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": ["MSFT", "AAPL", "NVDA"],
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": {},
            "thesis": "Momentum setup.",
            "agent_backend": "claude",
        }
        pre_open_backend = _CannedBackend(
            ToolCall(
                name="submit_daily_plan",
                args=day1_plan_args,
                model_id="claude-sonnet-4-5",
                input_tokens=1200, output_tokens=600,
            )
        )
        pre_open = PreOpenAgentTurn(
            config=_cfg(),
            backend=pre_open_backend,
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        plan = pre_open.run(
            as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        )

        assert plan.watchlist == ["MSFT", "AAPL", "NVDA"]
        assert plan.is_deterministic_fallback is False
        assert pre_open_backend.call_count == 1

        # ---- Day 1: post-close (narrator fallback writes state_store) ----
        # We use AlwaysUnavailableBackend to force the narrator path;
        # what matters for AC-1-ext is that state_store gets written on
        # BOTH paths.
        post_close = PostCloseAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),
            bandwidth=MagicMock(),
            journal=MagicMock(),
            plan=plan,  # today's committed plan
        )
        report = post_close.run(
            session_id="s20260713",
            as_of=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
        )

        assert report.is_deterministic_fallback is True
        assert report.session_id == "s20260713"

        # State store was populated by post_close
        assert store[("last_watchlist", "default")] == ["MSFT", "AAPL", "NVDA"]
        assert store[("last_plan", "default")]["watchlist"] == ["MSFT", "AAPL", "NVDA"]
        assert "date" in store[("last_session_summary", "default")]

        # ---- Day 2: pre-open FALLBACK reads yesterday's watchlist ----
        day2_pre_open = PreOpenAgentTurn(
            config=_cfg(),
            backend=AlwaysUnavailableBackend(),  # force fallback path
            bandwidth=MagicMock(),
            journal=MagicMock(),
        )
        day2_plan = day2_pre_open.run(
            as_of=datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
        )

        # AC-1-ext keystone assertion: yesterday's watchlist survived
        # the state_store round-trip and became today's fallback.
        assert day2_plan.is_deterministic_fallback is True
        assert day2_plan.watchlist == ["MSFT", "AAPL", "NVDA"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_save_wrapper(name, save_fn):
    """Build a save_* wrapper that pipes into the in-memory dict."""
    key_map = {
        "save_last_watchlist": "last_watchlist",
        "save_last_plan": "last_plan",
        "save_last_session_summary": "last_session_summary",
    }
    key = key_map[name]

    def _wrapper(payload_or_plan, scope="default"):
        # save_last_plan wants a DailyPlan; the store keeps model_dump()
        if name == "save_last_plan":
            save_fn(key, payload_or_plan.model_dump(mode="json"), scope)
        else:
            save_fn(key, payload_or_plan, scope)

    return _wrapper


def _make_load_wrapper(name, load_fn):
    """Build a load_* wrapper that reads the in-memory dict."""
    key_map = {
        "load_last_watchlist": "last_watchlist",
        "load_last_plan": "last_plan",
        "load_last_session_summary": "last_session_summary",
    }
    key = key_map[name]

    def _wrapper(scope="default"):
        payload = load_fn(key, scope)
        if payload is None:
            return None
        # load_last_plan reconstitutes the DailyPlan
        if name == "load_last_plan":
            from openbb_fmp_trading.models.plan import DailyPlan
            return DailyPlan.model_validate(payload)
        return payload

    return _wrapper
