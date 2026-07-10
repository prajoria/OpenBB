"""Module-global telemetry counter tests (openbb-fork side).

Extracted from ``test_error_model.py`` during E0.6 so the parent file's
non-stdlib imports become pynecore-side only (compiler + errors + IR)
and it can migrate to ``pyne_compiler`` at E2.

These tests exercise the OpenBB-fork-specific module-global recorder
functions in ``openbb_pine.telemetry`` (``record_unsupported_builtin``,
``record_unsupported_feature``, ``reset_metrics``, and the ``get_*``
snapshot helpers). Post-E2 the ``TelemetrySink`` Protocol moves to
``pyne_compiler.telemetry`` but the module-global counter shims stay
here alongside ``OpenBBTelemetrySink`` — hence STAY.

Clean-room: I have not viewed TradingView or PyneComp source code.
"""

from __future__ import annotations


class TestTelemetryCounters:
    def setup_method(self) -> None:
        """Isolate every test case from residual counter state."""
        from openbb_pine.telemetry import reset_metrics

        reset_metrics()

    def test_record_unsupported_builtin_increments(self) -> None:
        from openbb_pine.telemetry import (
            get_unsupported_builtin_counts,
            record_unsupported_builtin,
        )

        record_unsupported_builtin("ta.ichimoku")
        record_unsupported_builtin("ta.ichimoku")
        record_unsupported_builtin("ta.tsi")
        counts = get_unsupported_builtin_counts()
        assert counts["ta.ichimoku"] == 2
        assert counts["ta.tsi"] == 1

    def test_record_unsupported_feature_increments(self) -> None:
        from openbb_pine.telemetry import (
            get_unsupported_feature_counts,
            record_unsupported_feature,
        )

        record_unsupported_feature("PF010")
        counts = get_unsupported_feature_counts()
        assert counts["PF010"] == 1

    def test_reset_metrics_clears_both(self) -> None:
        from openbb_pine.telemetry import (
            get_unsupported_builtin_counts,
            get_unsupported_feature_counts,
            record_unsupported_builtin,
            record_unsupported_feature,
            reset_metrics,
        )

        record_unsupported_builtin("ta.foo")
        record_unsupported_feature("PF999")
        reset_metrics()
        assert get_unsupported_builtin_counts() == {}
        assert get_unsupported_feature_counts() == {}

    def test_get_returns_copy_not_live_reference(self) -> None:
        """Mutating the returned dict must NOT bleed into the counter state."""
        from openbb_pine.telemetry import (
            get_unsupported_builtin_counts,
            record_unsupported_builtin,
        )

        record_unsupported_builtin("ta.x")
        snapshot = get_unsupported_builtin_counts()
        snapshot["ta.injected"] = 999
        assert "ta.injected" not in get_unsupported_builtin_counts()
