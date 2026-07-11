"""AC-agent-11 (A4, P1): bandwidth reconciled against actual usage.

The pre-charge is an estimate (8000 tokens). If the actual usage from
``response.usage`` differs, the meter is reconciled so it doesn't drift.
Without reconciliation, a run of high-cost turns silently
under-accounts and blows past conservation/halted thresholds.
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


def _tool_call(input_tokens=None, output_tokens=None):
    from openbb_fmp_trading.agent.backend import ToolCall

    return ToolCall(
        name="submit_daily_plan",
        args={
            "as_of": "2026-07-13T13:30:00+00:00",
            "date": "2026-07-13",
            "watchlist": ["MSFT"],
            "preset": "intraday_momentum",
            "alerts": [],
            "session_risk": {},
            "thesis": "t",
            "agent_backend": "claude",
        },
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class TestBandwidthPreCharge:
    def test_pre_charge_called_before_backend(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call(input_tokens=1500, output_tokens=500)
        bandwidth = MagicMock()

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=bandwidth, journal=MagicMock(),
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Pre-charge was called with the estimated_tokens for pre-open (8000)
        bandwidth.charge_agent_turn_budget.assert_called_once_with(
            estimated_tokens=8000
        )


class TestBandwidthReconciliation:
    def test_reconcile_called_with_actual_usage(self):
        """A4: after the call, meter.reconcile(estimated, actual) fires
        with real numbers from response.usage."""
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call(
            input_tokens=1500, output_tokens=500
        )
        bandwidth = MagicMock()

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=bandwidth, journal=MagicMock(),
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # Reconciliation happened
        bandwidth.reconcile.assert_called_once_with(estimated=8000, actual=2000)

    def test_reconcile_skipped_when_usage_missing(self):
        """If response.usage is None (test backends, older SDKs), skip
        reconciliation gracefully rather than crashing."""
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call(
            input_tokens=None, output_tokens=None
        )
        bandwidth = MagicMock()

        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=bandwidth, journal=MagicMock(),
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        # No reconciliation call because we couldn't measure
        bandwidth.reconcile.assert_not_called()


class TestBackendCalledWithA6Constraints:
    """A6: temperature=0 + max_iterations pinned for reproducibility."""

    def test_backend_called_with_temperature_zero(self):
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn

        backend = MagicMock()
        backend.run_turn.return_value = _tool_call()
        turn = PreOpenAgentTurn(
            config=_cfg(), backend=backend,
            bandwidth=MagicMock(), journal=MagicMock(),
        )
        turn.run(as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc))

        kwargs = backend.run_turn.call_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert kwargs["max_iterations"] == 8
        assert kwargs["required_final_tool"] == "submit_daily_plan"
