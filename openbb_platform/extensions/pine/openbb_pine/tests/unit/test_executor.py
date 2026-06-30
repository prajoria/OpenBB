"""Tests for ``openbb_pine.runtime.executor`` -- D2 section 6 (R7).

End-to-end tests for ``run_compiled``: the OBBject.results + .extra contract
that downstream surfaces (REST, MCP, Workspace widget) consume.

Strategy: the compiler (D1 / C5) is not yet online, so we hand-build
``CompiledModule`` instances directly. The provider layer (R1/R2) is exercised
both for real (BYO with a synthesized DataFrame) and mocked (FMP via the
``_import_obb`` patch point that ``test_fmp_provider`` already established).

PyneCore's runtime is real -- it's vendored, fast, and the only reliable way
to verify the plot/alert collection plumbing actually works.
"""

from __future__ import annotations

import signal
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from openbb_pine.attribution import POWERED_BY_FULL
from openbb_pine.compiler.types import CompiledModule
from openbb_pine.errors import (
    PineDataValidationError,
    PineExecTimeoutError,
    PineProviderError,
    PineSecurityError,
)
from openbb_pine.runtime.executor import _resolve_data_source, run_compiled

_HAS_SIGALRM = hasattr(signal, "SIGALRM")


# --- Helpers -----------------------------------------------------------------


def _trivial_plot_close_module(*, cache_status: str = "miss", title: str = "basis") -> CompiledModule:
    """The minimum-viable @pyne module: plot close, indicator decorator."""
    source = f'''"""
@pyne
"""
from pynecore.lib import script, plot, close

@script.indicator(title="Smoke")
def main():
    plot(close, "{title}")
'''
    return CompiledModule(
        source=source,
        sha=f"smoke-{title}",
        pine_version=6,
        compiler_version="0.1.0",
        builtins_used=frozenset({"plot", "close"}),
        security_contexts=None,
        cache_status=cache_status,  # type: ignore[arg-type]
    )


def _alert_module() -> CompiledModule:
    """A module that calls ``alert()`` on every bar."""
    source = '''"""
@pyne
"""
from pynecore.lib import script, plot, alert, close

@script.indicator(title="Alerter")
def main():
    plot(close, "close")
    alert("ping")
'''
    return CompiledModule(
        source=source, sha="alert-smoke", pine_version=6,
        compiler_version="0.1.0",
        builtins_used=frozenset({"plot", "alert", "close"}),
        security_contexts=None, cache_status="miss",
    )


def _two_plot_module() -> CompiledModule:
    """A module that emits two named plot columns per bar."""
    source = '''"""
@pyne
"""
from pynecore.lib import script, plot, close, open

@script.indicator(title="Two")
def main():
    plot(close, "close")
    plot(open, "open")
'''
    return CompiledModule(
        source=source, sha="two-plot", pine_version=6,
        compiler_version="0.1.0",
        builtins_used=frozenset({"plot", "close", "open"}),
        security_contexts=None, cache_status="miss",
    )


def _byo_frame(rows: int = 5, *, tz_aware: bool = True) -> pd.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc if tz_aware else None)
    idx = pd.DatetimeIndex(
        [base + pd.Timedelta(days=i) for i in range(rows)], name="date"
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1000.0 + i for i in range(rows)],
        },
        index=idx,
    )


def _mock_obb_with_frame(df: pd.DataFrame) -> Any:
    """Return a MagicMock that mimics ``from openbb import obb`` enough to
    satisfy ``FMPOHLCVProvider._fetch``."""
    fake_obbj = MagicMock()
    fake_obbj.to_df.return_value = df
    obb = MagicMock()
    obb.equity.price.historical.return_value = fake_obbj
    obb.crypto.price.historical.return_value = fake_obbj
    obb.currency.price.historical.return_value = fake_obbj
    obb.commodity.price.historical.return_value = fake_obbj
    return obb


# ============================================================================
# .results DataFrame shape
# ============================================================================


class TestResultsDataFrame:
    """D2 §6.2 -- one column per plot, indexed by tz-aware DatetimeIndex."""

    def test_single_plot_yields_single_column(self):
        cm = _trivial_plot_close_module(title="basis")
        df = _byo_frame(rows=5)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert list(obj.results.columns) == ["basis"]
        assert obj.results.shape == (5, 1)

    def test_two_plots_yield_two_columns(self):
        cm = _two_plot_module()
        df = _byo_frame(rows=3)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert set(obj.results.columns) == {"close", "open"}
        assert obj.results.shape == (3, 2)

    def test_results_index_is_tz_aware_datetimeindex(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame(rows=3)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert isinstance(obj.results.index, pd.DatetimeIndex)
        assert obj.results.index.tz is not None

    def test_results_values_match_input_close(self):
        cm = _trivial_plot_close_module(title="close")
        df = _byo_frame(rows=4)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        # close column in the BYO frame == 100.5, 101.5, 102.5, 103.5.
        assert list(obj.results["close"]) == [100.5, 101.5, 102.5, 103.5]


# ============================================================================
# .extra contract -- D2 §6.1
# ============================================================================


class TestExtraContract:
    """Every D2 §6.1 key present with the right type."""

    def test_all_seven_keys_present(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        expected_keys = {
            "alerts", "orders", "attribution", "compile_cache_hit",
            "exec_ms", "provider_used", "bars_consumed",
        }
        assert set(obj.extra.keys()) == expected_keys

    def test_attribution_is_literal_powered_by_full(self):
        """Per D2 §6.4 -- attribution is the literal constant from
        openbb_pine.attribution (single source of truth)."""
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.extra["attribution"] == POWERED_BY_FULL
        assert obj.extra["attribution"] == "Powered by PyneSys (https://pynesys.io)"

    def test_orders_is_empty_list_for_indicators(self):
        """D2 §6.1 row 2 -- orders is ALWAYS present, [] for indicators."""
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.extra["orders"] == []
        assert isinstance(obj.extra["orders"], list)

    def test_alerts_is_list_of_dicts(self):
        cm = _trivial_plot_close_module()  # no alert calls -> empty list
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.extra["alerts"] == []
        assert isinstance(obj.extra["alerts"], list)

    def test_compile_cache_hit_reflects_compiled_cache_status(self):
        cm_hit = _trivial_plot_close_module(cache_status="hit")
        cm_miss = _trivial_plot_close_module(cache_status="miss")
        df = _byo_frame(rows=2)
        obj_hit = run_compiled(cm_hit, provider_or_data=df, symbol="X", interval="1d")
        obj_miss = run_compiled(cm_miss, provider_or_data=df, symbol="X", interval="1d")
        assert obj_hit.extra["compile_cache_hit"] is True
        assert obj_miss.extra["compile_cache_hit"] is False

    def test_compile_cache_hit_handles_bypass(self):
        cm = _trivial_plot_close_module(cache_status="bypass")
        df = _byo_frame(rows=2)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        # "bypass" is not "hit" -> False.
        assert obj.extra["compile_cache_hit"] is False

    def test_exec_ms_is_int_and_nonnegative(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert isinstance(obj.extra["exec_ms"], int)
        assert obj.extra["exec_ms"] >= 0

    def test_exec_ms_within_reasonable_envelope(self):
        """5 bars should execute in well under 5s; without a wall-clock signal
        the test would be a flaky tautology. Use a small timeout (5s) to make
        the upper bound concrete."""
        cm = _trivial_plot_close_module()
        df = _byo_frame(rows=5)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d", timeout_s=5)
        assert obj.extra["exec_ms"] < 5000

    def test_bars_consumed_matches_input_rows(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame(rows=7)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.extra["bars_consumed"] == 7

    def test_provider_used_byo_for_dataframe_input(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.extra["provider_used"] == "byo"


# ============================================================================
# Alerts captured during run
# ============================================================================


class TestAlertCapture:
    """``alert(message)`` calls land in ``extra["alerts"]`` per D2 §6.1."""

    def test_one_alert_per_bar(self):
        cm = _alert_module()
        df = _byo_frame(rows=4)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        alerts = obj.extra["alerts"]
        assert len(alerts) == 4
        for entry in alerts:
            assert entry["message"] == "ping"

    def test_alert_entries_have_required_shape(self):
        cm = _alert_module()
        df = _byo_frame(rows=2)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        for entry in obj.extra["alerts"]:
            assert set(entry.keys()) >= {"bar_index", "ts", "message"}
            assert isinstance(entry["bar_index"], int)
            assert isinstance(entry["ts"], str)
            assert isinstance(entry["message"], str)

    def test_alert_ts_is_iso8601_utc(self):
        cm = _alert_module()
        df = _byo_frame(rows=1)
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        (entry,) = obj.extra["alerts"]
        # ISO-8601 with explicit +00:00 or Z suffix.
        ts = entry["ts"]
        assert "+00:00" in ts or ts.endswith("Z"), f"non-UTC ts: {ts!r}"
        # Parseable as datetime.
        datetime.fromisoformat(ts)

    def test_alert_monkey_patch_is_torn_down(self):
        """After ``run_compiled`` returns, ``pynecore.lib.alert.alert`` is
        the original function again. A second run must not see a stale shim
        appending to the previous list."""
        cm = _alert_module()
        df = _byo_frame(rows=2)
        obj_a = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        obj_b = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        # Both calls capture exactly their own bars worth of alerts.
        assert len(obj_a.extra["alerts"]) == 2
        assert len(obj_b.extra["alerts"]) == 2
        # And the per-call lists are distinct objects.
        assert obj_a.extra["alerts"] is not obj_b.extra["alerts"]


# ============================================================================
# Timeout integration -- R5
# ============================================================================


class TestTimeoutIntegration:
    """T2 enforcement wraps run_iter; long script -> PineExecTimeoutError."""

    @pytest.mark.skipif(not _HAS_SIGALRM, reason="POSIX-only SIGALRM timeout test")
    def test_sleeping_script_raises_pine_exec_timeout(self):
        """A script that sleeps inside main() must trip the wall-clock cap."""
        # Even though `time` is in our forbidden set, an indirect sleep via
        # math.cos with a huge range is too dependent on CPU. We import time
        # explicitly here -- the SECURITY scan blocks it. So we test the
        # timeout with a busy loop using PyneCore's own constructs.
        source = '''"""
@pyne
"""
from pynecore.lib import script, plot, close

@script.indicator(title="Slow")
def main():
    # Busy loop -- not allowed to import time, but range() and a noop
    # arithmetic keeps the GIL held briefly.
    x = 0.0
    for _ in range(10_000_000):
        x += 1.0
    plot(close, "close")
'''
        cm = CompiledModule(
            source=source, sha="slow", pine_version=6,
            compiler_version="0.1.0", builtins_used=frozenset(),
            security_contexts=None, cache_status="miss",
        )
        # Big enough frame that the per-bar 10M loop blows the budget.
        df = _byo_frame(rows=200)
        with pytest.raises(PineExecTimeoutError):
            run_compiled(cm, provider_or_data=df, symbol="X", interval="1d", timeout_s=1)


# ============================================================================
# T3 sandbox -- forbidden imports rejected
# ============================================================================


class TestSandboxRejectsForbiddenImports:
    """The AST scan in _pynecore_glue catches os/subprocess/etc."""

    @pytest.mark.parametrize("mod", ["os", "subprocess", "socket", "ctypes", "shutil"])
    def test_forbidden_import_raises_pine_security_error(self, mod):
        source = f'''"""
@pyne
"""
import {mod}
from pynecore.lib import script, plot, close

@script.indicator(title="Bad")
def main():
    plot(close, "close")
'''
        cm = CompiledModule(
            source=source, sha=f"bad-{mod}", pine_version=6,
            compiler_version="0.1.0", builtins_used=frozenset(),
            security_contexts=None, cache_status="miss",
        )
        df = _byo_frame()
        with pytest.raises(PineSecurityError) as excinfo:
            run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert mod in str(excinfo.value)

    def test_from_import_of_forbidden_module_caught(self):
        source = '''"""
@pyne
"""
from os import environ
from pynecore.lib import script, plot, close

@script.indicator(title="Bad")
def main():
    plot(close, "close")
'''
        cm = CompiledModule(
            source=source, sha="bad-from", pine_version=6,
            compiler_version="0.1.0", builtins_used=frozenset(),
            security_contexts=None, cache_status="miss",
        )
        df = _byo_frame()
        with pytest.raises(PineSecurityError):
            run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")

    def test_pynecore_import_is_allowed(self):
        """A clean module that imports ONLY from pynecore must NOT trip the
        scan. Defense-in-depth, not a foot-gun."""
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        # Should not raise PineSecurityError.
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert obj.results.shape[0] == len(df)


# ============================================================================
# BYO provider integration
# ============================================================================


class TestBYOIntegration:
    def test_dataframe_input_drives_byo_provider(self):
        cm = _trivial_plot_close_module(title="close")
        df = _byo_frame(rows=4)
        obj = run_compiled(cm, provider_or_data=df, symbol="AAPL", interval="1d")
        assert obj.extra["provider_used"] == "byo"
        assert obj.extra["bars_consumed"] == 4

    def test_byo_validation_errors_propagate(self):
        cm = _trivial_plot_close_module()
        bad_df = pd.DataFrame({"open": [1.0]}, index=pd.DatetimeIndex([datetime(2024, 1, 1, tzinfo=timezone.utc)]))
        with pytest.raises(PineDataValidationError):
            run_compiled(cm, provider_or_data=bad_df, symbol="X", interval="1d")

    def test_byo_with_default_symbol_works(self):
        """``symbol=None`` falls back to ``"BYO"`` for the syminfo prefix."""
        cm = _trivial_plot_close_module(title="close")
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, interval="1d")
        assert obj.extra["bars_consumed"] == 5


# ============================================================================
# FMP provider integration (mocked obb)
# ============================================================================


class TestFMPIntegration:
    """The "fmp" / "fmp_cached" provider names route through FMPOHLCVProvider."""

    def test_fmp_routing_with_mocked_obb(self):
        cm = _trivial_plot_close_module(title="close")
        fake_df = pd.DataFrame(
            {
                "open": [200.0, 201.0, 202.0],
                "high": [201.0, 202.0, 203.0],
                "low": [199.0, 200.0, 201.0],
                "close": [200.5, 201.5, 202.5],
                "volume": [5000.0] * 3,
            },
            index=pd.DatetimeIndex(
                [datetime(2024, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=i) for i in range(3)],
                name="date",
            ),
        )
        obb = _mock_obb_with_frame(fake_df)
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            obj = run_compiled(
                cm, provider_or_data="fmp", symbol="AAPL", interval="1d"
            )
        assert obj.extra["provider_used"] == "fmp"
        assert obj.results.shape == (3, 1)
        assert obb.equity.price.historical.called

    def test_fmp_cached_routing_when_explicitly_requested(self):
        cm = _trivial_plot_close_module(title="close")
        fake_df = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.DatetimeIndex([datetime(2024, 1, 1, tzinfo=timezone.utc)], name="date"),
        )
        obb = _mock_obb_with_frame(fake_df)
        with patch("openbb_pine.runtime.fmp_provider._import_obb", return_value=obb):
            obj = run_compiled(
                cm, provider_or_data="fmp_cached", symbol="AAPL", interval="1d"
            )
        assert obj.extra["provider_used"] == "fmp_cached"
        # Mocked OBBject does not specify the provider name; provider kwarg
        # should still be passed through.
        _, call_kwargs = obb.equity.price.historical.call_args
        assert call_kwargs.get("provider") == "fmp_cached"


# ============================================================================
# Non-FMP provider fast-fail (PRD §13.8)
# ============================================================================


class TestNonFMPRejection:
    """Per PRD §13.8 -- only fmp / fmp_cached supported, others raise."""

    @pytest.mark.parametrize("bad", ["yfinance", "polygon", "alpha_vantage", "intrinio"])
    def test_non_fmp_string_raises_provider_error(self, bad):
        cm = _trivial_plot_close_module()
        with pytest.raises(PineProviderError) as excinfo:
            run_compiled(cm, provider_or_data=bad, symbol="X", interval="1d")
        assert bad in str(excinfo.value)


# ============================================================================
# _resolve_data_source -- internal branching tested directly
# ============================================================================


class TestResolveDataSource:
    """Direct unit tests for the provider-construction branches."""

    def test_string_provider_returns_fmp_provider(self):
        prov = _resolve_data_source(
            "fmp", symbol="AAPL", interval="1d",
            start=None, end=None, user_settings=None,
        )
        # Concrete class check; FMPOHLCVProvider has provider_used attr.
        assert prov.provider_used == "fmp"

    def test_dataframe_returns_byo_provider(self):
        df = _byo_frame()
        prov = _resolve_data_source(
            df, symbol="X", interval="1d",
            start=None, end=None, user_settings=None,
        )
        assert prov.provider_used == "byo"

    def test_unsupported_type_raises_typeerror(self):
        with pytest.raises(TypeError):
            _resolve_data_source(
                12345, symbol="X", interval="1d",  # type: ignore[arg-type]
                start=None, end=None, user_settings=None,
            )

    def test_missing_symbol_with_fmp_raises_valueerror(self):
        """FMP path requires symbol + interval; without them we raise."""
        with pytest.raises(ValueError):
            _resolve_data_source(
                "fmp", symbol=None, interval=None,
                start=None, end=None, user_settings=None,
            )


# ============================================================================
# OBBject return shape
# ============================================================================


class TestOBBjectReturnShape:
    """``run_compiled`` returns an ``OBBject`` (the OpenBB Platform contract
    type), not a bare dict or DataFrame."""

    def test_return_is_obbject(self):
        from openbb_core.app.model.obbject import OBBject  # local to keep import isolated

        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert isinstance(obj, OBBject)

    def test_obbject_results_is_dataframe(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert isinstance(obj.results, pd.DataFrame)

    def test_obbject_extra_is_dict(self):
        cm = _trivial_plot_close_module()
        df = _byo_frame()
        obj = run_compiled(cm, provider_or_data=df, symbol="X", interval="1d")
        assert isinstance(obj.extra, dict)
