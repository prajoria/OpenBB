"""AC-P5-3: json_builder produces valid, stable JSON with Decimal-as-string."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest


class TestJsonBuilder:
    def test_output_is_valid_json(self):
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("100"))
        text = build_json_manifest(
            events=[],
            metrics=metrics,
            plan=None,
            report=None,
            session_id="s20260713",
        )
        parsed = json.loads(text)
        assert parsed["session_id"] == "s20260713"
        assert parsed["metrics"]["realized_pnl"] == "100"

    def test_decimal_serialized_as_string(self):
        """Review finding #3: precision preserved via string serialization."""
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("1234.56789012"))
        parsed = json.loads(
            build_json_manifest(
                events=[],
                metrics=metrics,
                plan=None,
                report=None,
                session_id="s",
            )
        )
        assert parsed["metrics"]["realized_pnl"] == "1234.56789012"

    def test_stable_output_across_calls(self):
        """Review S1 fix: sorted keys = stable JSON bytes for same input.

        Note: event `ts` values ARE in the output — they come from the
        recorded journal. Stability is guaranteed only because those
        timestamps are inputs (not generated at render time); do NOT
        call datetime.now() anywhere in json_builder.
        """
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(realized_pnl=Decimal("0"))
        a = build_json_manifest(
            events=[], metrics=metrics, plan=None, report=None, session_id="s"
        )
        b = build_json_manifest(
            events=[], metrics=metrics, plan=None, report=None, session_id="s"
        )
        assert a == b

    def test_cost_drag_fields_serialized(self):
        """Review #6: total_commissions + total_slippage in the manifest."""
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(
            realized_pnl=Decimal("100"),
            total_commissions=Decimal("2.50"),
            total_slippage=Decimal("0.75"),
        )
        parsed = json.loads(
            build_json_manifest(
                events=[], metrics=metrics, plan=None, report=None, session_id="s"
            )
        )
        assert parsed["metrics"]["total_commissions"] == "2.50"
        assert parsed["metrics"]["total_slippage"] == "0.75"

    def test_pnl_source_field_serialized(self):
        """Review #4: pnl_source provenance visible in the manifest."""
        from openbb_fmp_trading.models.report import SessionMetrics
        from openbb_fmp_trading.reporting.json_builder import build_json_manifest

        metrics = SessionMetrics(
            realized_pnl=Decimal("100"),
            pnl_source="authoritative_session_end",
        )
        parsed = json.loads(
            build_json_manifest(
                events=[], metrics=metrics, plan=None, report=None, session_id="s"
            )
        )
        assert parsed["metrics"]["pnl_source"] == "authoritative_session_end"
