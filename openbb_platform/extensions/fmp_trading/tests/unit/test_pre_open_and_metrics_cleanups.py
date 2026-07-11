"""Regression tests for bd-9nd.10 + bd-9nd.11.

bd-9nd.10: aggregate PromptInjectionRejectedEvent per turn — clamp
violations from a single _clamp_risk_overrides pass produce ONE event
with fields=[...], not N per-field events.

bd-9nd.11: WARN log on unparseable Decimal values in
compute_metrics_from_events — silent swallow was hard to trace during
P&L reconciliation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# bd-9nd.10 — aggregate PromptInjectionRejectedEvent
# ---------------------------------------------------------------------------


class TestAggregateClampEvents:
    """One clamp pass = one aggregate event, not N per-field events."""

    def _cfg(self):
        from openbb_fmp_trading.models.config import DailyConfig, RiskConfig

        return DailyConfig(
            default_watchlist=["MSFT"],
            default_preset="intraday_momentum",
            default_risk=RiskConfig(),
        )

    def _plan_with_loosened_risk(self, **overrides):
        """Build a DailyPlan whose session_risk loosens N fields."""
        from datetime import date as _date

        from openbb_fmp_trading.models.config import RiskConfig
        from openbb_fmp_trading.models.plan import DailyPlan

        base_risk = RiskConfig().model_dump()
        base_risk.update(overrides)
        return DailyPlan(
            as_of=datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
            date=_date(2026, 7, 13),
            watchlist=["MSFT"],
            preset="intraday_momentum",
            alerts=[],
            session_risk=RiskConfig(**base_risk),
            thesis="test",
            agent_backend="claude",
        )

    def test_single_field_violation_emits_one_aggregate_event(self):
        """Legacy shim: single-field _journal_clamp still produces one
        aggregate event (with fields=[one-entry-list])."""
        from openbb_fmp_trading.agent.errors import RiskOverrideLoosening
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import (
            PromptInjectionRejectedEvent,
        )

        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=self._cfg(),
            backend=MagicMock(),
            bandwidth=MagicMock(),
            journal=journal,
        )
        plan = self._plan_with_loosened_risk(
            max_position_size_pct_equity=99.0  # WAY over default
        )

        with pytest.raises(RiskOverrideLoosening):
            turn._clamp_risk_overrides(plan)

        # bd-9nd.10 contract: ONE event, not one-per-field
        writes = [
            call.args[0] for call in journal.write.call_args_list
            if isinstance(call.args[0], PromptInjectionRejectedEvent)
        ]
        assert len(writes) == 1
        # Aggregate shape: payload["fields"] is a list
        payload = writes[0].payload
        assert payload["defense_layer"] == "risk_clamp"
        assert isinstance(payload.get("fields"), list)
        assert payload["field_count"] == 1
        assert payload["fields"][0]["field"] == "max_position_size_pct_equity"

    def test_multi_field_violation_still_one_event_with_all_fields(self):
        """The whole point of bd-9nd.10: N loosened fields = ONE event
        with N entries in payload['fields'], NOT N events."""
        from openbb_fmp_trading.agent.errors import RiskOverrideLoosening
        from openbb_fmp_trading.agent.pre_open import PreOpenAgentTurn
        from openbb_fmp_trading.models.journal_events import (
            PromptInjectionRejectedEvent,
        )

        journal = MagicMock()
        turn = PreOpenAgentTurn(
            config=self._cfg(),
            backend=MagicMock(),
            bandwidth=MagicMock(),
            journal=journal,
        )
        # Loosen 3 different fields simultaneously
        plan = self._plan_with_loosened_risk(
            max_position_size_pct_equity=50.0,   # default 10.0
            max_notional_pct_equity=90.0,        # default 30.0
            day_dd_pct=-10.0,                    # more negative = looser
        )

        with pytest.raises(RiskOverrideLoosening):
            turn._clamp_risk_overrides(plan)

        writes = [
            call.args[0] for call in journal.write.call_args_list
            if isinstance(call.args[0], PromptInjectionRejectedEvent)
        ]
        # bd-9nd.10: exactly ONE event for the whole pass
        assert len(writes) == 1, (
            f"Expected 1 aggregate event, got {len(writes)} — "
            "per-field emission regressed"
        )
        payload = writes[0].payload
        assert payload["field_count"] == 3
        # All three fields represented in one payload
        field_names = {entry["field"] for entry in payload["fields"]}
        assert field_names == {
            "max_position_size_pct_equity",
            "max_notional_pct_equity",
            "day_dd_pct",
        }


# ---------------------------------------------------------------------------
# bd-9nd.11 — WARN on unparseable Decimal values
# ---------------------------------------------------------------------------


class TestDecimalParseErrorsLogged:
    """Silent swallow of unparseable realized_pnl / commission / slippage
    was hard to trace during P&L reconciliation. bd-9nd.11: WARN log
    surfaces the offending value + event ts for traceability."""

    def test_bad_realized_pnl_on_fill_logs_warning(self, caplog):
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "not-a-number"},
            ),
        ]
        caplog.set_level(logging.WARNING, logger="openbb_fmp_trading.reporting.journal_reader")

        metrics = compute_metrics_from_events(events)

        # The bad value was skipped, not crashed
        assert metrics.fill_count == 1
        assert metrics.realized_pnl == Decimal("0")

        # ... AND a WARN was logged with the offending value + ts
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("realized_pnl" in r.message for r in warnings), (
            f"Expected a WARN mentioning realized_pnl; got: "
            f"{[r.message for r in warnings]}"
        )
        assert any("not-a-number" in r.message for r in warnings)

    def test_bad_commission_and_slippage_both_log(self, caplog):
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={
                    "realized_pnl": "150.00",  # valid — ignored by this test
                    "commission": "garbage-commission",
                    "slippage": "also-bad",
                },
            ),
        ]
        caplog.set_level(logging.WARNING, logger="openbb_fmp_trading.reporting.journal_reader")

        metrics = compute_metrics_from_events(events)

        # Metrics still compute; bad cost values just weren't summed in
        assert metrics.realized_pnl == Decimal("150.00")
        assert metrics.total_commissions == Decimal("0")
        assert metrics.total_slippage == Decimal("0")

        messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any("commission" in m and "garbage-commission" in m for m in messages)
        assert any("slippage" in m and "also-bad" in m for m in messages)

    def test_bad_session_end_pnl_logs_and_falls_back_to_summed(self, caplog):
        """The most critical case: session_end is authoritative, so
        losing it silently would misreport as summed_from_fills without
        the operator knowing why."""
        from openbb_fmp_trading.models.journal_events import (
            FillEvent,
            SessionEndEvent,
        )
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "150.00"},
            ),
            SessionEndEvent(
                ts=datetime(2026, 7, 13, 20, 15, tzinfo=timezone.utc),
                session_id="s",
                payload={"realized_pnl": "definitely-wrong", "flat_at_close": True},
            ),
        ]
        caplog.set_level(logging.WARNING, logger="openbb_fmp_trading.reporting.journal_reader")

        metrics = compute_metrics_from_events(events)

        # Fell back to summed_from_fills — the operator MUST see the
        # WARN, otherwise they think the summed value is authoritative
        assert metrics.pnl_source == "summed_from_fills"
        assert metrics.realized_pnl == Decimal("150.00")

        messages = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "session_end" in m and "definitely-wrong" in m for m in messages
        ), f"Expected session_end WARN; got: {messages}"

    def test_valid_decimals_produce_no_warnings(self, caplog):
        """Sanity: valid values don't spam WARN logs."""
        from openbb_fmp_trading.models.journal_events import FillEvent
        from openbb_fmp_trading.reporting.journal_reader import (
            compute_metrics_from_events,
        )

        events = [
            FillEvent(
                ts=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
                session_id="s",
                payload={
                    "realized_pnl": "150.00",
                    "commission": "1.00",
                    "slippage": "0.10",
                },
            ),
        ]
        caplog.set_level(logging.WARNING, logger="openbb_fmp_trading.reporting.journal_reader")

        metrics = compute_metrics_from_events(events)

        # No warnings for valid input
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warnings == []
        # Sanity: values were summed correctly
        assert metrics.realized_pnl == Decimal("150.00")
        assert metrics.total_commissions == Decimal("1.00")
        assert metrics.total_slippage == Decimal("0.10")
