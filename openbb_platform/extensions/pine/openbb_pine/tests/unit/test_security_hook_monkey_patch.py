"""Tests for ``openbb_pine.runtime.security_hook`` — D5 §5.3.

Covers the monkey-patch context manager that swaps
``pynecore.lib.request.security`` for a version that reads from the
c1x dispatcher's prefetched ``{context_id: DataFrame}`` map:

* install → patched function returns prefetched values
* uninstall (context-manager exit) → original stub restored
* two-symbols map → correct (symbol, timeframe) → context_id resolution
* missing (symbol, timeframe) → :class:`PineSecurityContextNotFoundError`
  with ``reason="not_found"`` + ``available_keys`` populated
* bar-index accessor advances → hook returns different values across bars
* dynamic-symbol / dynamic-timeframe context →
  :class:`PineSecurityContextNotFoundError` with ``reason="dynamic_unsupported"``
* nested install → LIFO unwind restores each layer correctly
* exception inside the ``with`` block → restoration still happens (finally)
* expression coercion: Source-like sentinel objects (``.name`` attr) and
  plain strings both resolve; anything else raises ``TypeError``

We do NOT run real Pine scripts here — this file exercises the hook
plumbing in isolation, with hand-built ``SecurityContext`` instances +
hand-built ``pd.DataFrame`` s standing in for what c1x would produce.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from openbb_pine.compiler.types import SecurityContext
from openbb_pine.errors import PineSecurityContextNotFoundError
from openbb_pine.runtime.security_hook import (
    expression_column_name,
    install_secondaries_hook,
)


# --- Fixtures ---------------------------------------------------------------


def _daily_index(rows: int = 5) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        [datetime(2024, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=i) for i in range(rows)],
        name="date",
    )


def _secondary(
    rows: int = 5,
    close_offset: float = 200.0,
    volume_offset: float = 500_000.0,
) -> pd.DataFrame:
    """DataFrame with deterministic close/volume per bar for assertion."""
    idx = _daily_index(rows)
    return pd.DataFrame(
        {
            "open": [close_offset - 1.0 + i for i in range(rows)],
            "high": [close_offset + 1.0 + i for i in range(rows)],
            "low": [close_offset - 2.0 + i for i in range(rows)],
            "close": [close_offset + i for i in range(rows)],
            "volume": [volume_offset + i for i in range(rows)],
        },
        index=idx,
    )


class _FakeSource:
    """Stand-in for PyneCore's ``Source`` sentinel (``types/source.py``).

    We can't import PyneCore's real ``Source`` without pulling in the
    entire runtime bridge (``pynecore.lib``), and the hook only needs the
    ``.name`` attribute per :func:`expression_column_name`.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"_FakeSource({self.name!r})"


# --- expression_column_name --------------------------------------------------


class TestExpressionColumnName:
    def test_source_sentinel_uses_name_attr(self):
        assert expression_column_name(_FakeSource("close")) == "close"
        assert expression_column_name(_FakeSource("volume")) == "volume"

    def test_plain_string_passes_through(self):
        assert expression_column_name("close") == "close"
        assert expression_column_name("volume") == "volume"

    def test_unsupported_type_raises_typeerror(self):
        # A raw float isn't a valid expression — the hook should refuse it
        # loudly rather than mangle it into a column name.
        with pytest.raises(TypeError, match="unsupported expression type"):
            expression_column_name(3.14)
        with pytest.raises(TypeError, match="unsupported expression type"):
            expression_column_name(None)

    def test_empty_name_attr_falls_through_to_type_error(self):
        # A Source-like object whose .name is empty is not a valid column;
        # do NOT silently return "" — that would produce a KeyError deep in
        # the hook. Refuse at the boundary.
        with pytest.raises(TypeError, match="unsupported expression type"):
            expression_column_name(_FakeSource(""))


# --- Install / uninstall lifecycle ------------------------------------------


class TestInstallUninstall:
    def test_hook_intercepts_security_call(self):
        """Inside the ``with`` block, request.security returns the
        prefetched value at the current bar."""
        secondary = _secondary(rows=5)
        ctx = SecurityContext(symbol="SPY", timeframe="1D", expr="close")
        contexts = {"ctx_0": ctx}
        secondaries = {"ctx_0": secondary}
        bar_state = {"i": 0}

        # Local import so this test doesn't depend on module-import ordering.
        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries,
            contexts,
            get_current_bar_index=lambda: bar_state["i"],
        ):
            val = request_module.security("SPY", "1D", _FakeSource("close"))
            assert val == secondary["close"].iloc[0]

    def test_uninstall_restores_original(self):
        """After the ``with`` block exits, request.security is back to
        PyneCore's stub (which raises RuntimeError per its docstring)."""
        from pynecore.lib import request as request_module

        original = request_module.security

        with install_secondaries_hook(
            {}, {}, get_current_bar_index=lambda: 0
        ):
            assert request_module.security is not original

        # Restored.
        assert request_module.security is original

    def test_uninstall_restores_after_exception(self):
        """Restoration must happen in ``finally`` — a script crash inside
        the ``with`` block cannot leave the runtime patched."""
        from pynecore.lib import request as request_module

        original = request_module.security

        with pytest.raises(ValueError, match="boom"):
            with install_secondaries_hook(
                {}, {}, get_current_bar_index=lambda: 0
            ):
                raise ValueError("boom")

        assert request_module.security is original


# --- Two-symbol lookup ------------------------------------------------------


class TestTwoSymbolLookup:
    def test_correct_context_resolved_by_symbol_and_timeframe(self):
        """With two symbols, the hook must return the right one for each
        (symbol, timeframe) tuple."""
        spy = _secondary(rows=3, close_offset=400.0, volume_offset=1_000_000.0)
        qqq = _secondary(rows=3, close_offset=380.0, volume_offset=800_000.0)
        contexts = {
            "ctx_spy": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
            "ctx_qqq": SecurityContext(symbol="QQQ", timeframe="1D", expr="close"),
        }
        secondaries = {"ctx_spy": spy, "ctx_qqq": qqq}
        bar_state = {"i": 1}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries,
            contexts,
            get_current_bar_index=lambda: bar_state["i"],
        ):
            spy_val = request_module.security("SPY", "1D", _FakeSource("close"))
            qqq_val = request_module.security("QQQ", "1D", _FakeSource("close"))

        assert spy_val == spy["close"].iloc[1]
        assert qqq_val == qqq["close"].iloc[1]
        assert spy_val != qqq_val  # sanity: distinct values from distinct frames

    def test_symbol_alone_not_enough_when_timeframes_differ(self):
        """SPY@1D and SPY@1H are TWO distinct contexts. Looking up the
        second must NOT return the first's frame."""
        spy_daily = _secondary(rows=3, close_offset=400.0)
        spy_hourly = _secondary(rows=3, close_offset=401.5)
        contexts = {
            "ctx_daily": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
            "ctx_hourly": SecurityContext(symbol="SPY", timeframe="1H", expr="close"),
        }
        secondaries = {"ctx_daily": spy_daily, "ctx_hourly": spy_hourly}
        bar_state = {"i": 0}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries,
            contexts,
            get_current_bar_index=lambda: bar_state["i"],
        ):
            v_daily = request_module.security("SPY", "1D", _FakeSource("close"))
            v_hourly = request_module.security("SPY", "1H", _FakeSource("close"))

        assert v_daily == spy_daily["close"].iloc[0]
        assert v_hourly == spy_hourly["close"].iloc[0]


# --- Missing-context errors -------------------------------------------------


class TestMissingContext:
    def test_missing_symbol_raises_with_available_keys(self):
        """A lookup miss should surface :class:`PineSecurityContextNotFoundError`
        carrying the list of known contexts so the operator can spot
        the mismatch (e.g. ``"1D"`` vs ``"1d"``)."""
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondaries = {"ctx_0": _secondary()}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            with pytest.raises(PineSecurityContextNotFoundError) as excinfo:
                request_module.security("QQQ", "1D", _FakeSource("close"))

        err = excinfo.value
        assert err.symbol == "QQQ"
        assert err.timeframe == "1D"
        assert err.reason == "not_found"
        # Available keys mention SPY so the operator sees what IS in the map.
        assert err.available_keys is not None
        assert any("SPY" in k for k in err.available_keys)

    def test_case_or_format_mismatch_still_raises_not_found(self):
        """The hook does strict string equality; '1d' != '1D' → miss."""
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondaries = {"ctx_0": _secondary()}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            # Lowercase 'd' — Pine's canonical form is capital 'D', so
            # a compiler that emitted the wrong string would surface here.
            with pytest.raises(PineSecurityContextNotFoundError):
                request_module.security("SPY", "1d", _FakeSource("close"))

    def test_secondaries_missing_frame_for_registered_context(self):
        """Defensive path: the context_id is in ``security_contexts`` but
        ``secondaries`` has no frame (dispatcher wire-up bug). Same
        error class, same reason, but with a message pointing at the
        dispatcher."""
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondaries: dict[str, pd.DataFrame] = {}  # empty!

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            with pytest.raises(PineSecurityContextNotFoundError) as excinfo:
                request_module.security("SPY", "1D", _FakeSource("close"))
        assert excinfo.value.reason == "not_found"
        assert excinfo.value.context_id == "ctx_0"


# --- Bar-index advancement --------------------------------------------------


class TestBarIndexAdvancement:
    def test_hook_reads_current_bar_across_iterations(self):
        """The bar index is threaded via a callable so the hook can
        return different values as the executor advances."""
        secondary = _secondary(rows=5)
        contexts = {"ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close")}
        secondaries = {"ctx_0": secondary}
        bar_state = {"i": 0}

        from pynecore.lib import request as request_module

        readings: list[float] = []
        with install_secondaries_hook(
            secondaries,
            contexts,
            get_current_bar_index=lambda: bar_state["i"],
        ):
            for i in range(5):
                bar_state["i"] = i
                readings.append(
                    request_module.security("SPY", "1D", _FakeSource("close"))
                )

        assert readings == list(secondary["close"])

    def test_callable_invoked_each_time_not_snapshotted(self):
        """The callable must be invoked per-security-call — a snapshot
        at install time would freeze the hook to bar 0 forever."""
        secondary = _secondary(rows=3)
        contexts = {"ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close")}
        secondaries = {"ctx_0": secondary}

        getter = MagicMock(return_value=0)

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=getter
        ):
            request_module.security("SPY", "1D", _FakeSource("close"))
            request_module.security("SPY", "1D", _FakeSource("close"))
            request_module.security("SPY", "1D", _FakeSource("close"))

        # Called once per security() invocation, not once at install time.
        assert getter.call_count == 3


# --- Dynamic-context rejection ----------------------------------------------


class TestDynamicContextRejection:
    def _dynamic_ctx(self, **flags) -> Any:
        """Build a SecurityContext-shaped object with dynamic flags.

        ``SecurityContext`` is a frozen slotted dataclass without the
        ``dynamic_symbol`` / ``dynamic_timeframe`` fields yet (bead y86
        adds them concurrently with n6j). Wrap with a shim so we can flip
        the flags without touching the compiler's owned dataclass shape.
        """

        class _DynamicCtx:
            symbol = flags.pop("symbol", "SPY")
            timeframe = flags.pop("timeframe", "1D")
            expr = "close"
            dynamic_symbol = flags.pop("dynamic_symbol", False)
            dynamic_timeframe = flags.pop("dynamic_timeframe", False)

        return _DynamicCtx()

    def test_dynamic_symbol_raises_documented_error(self):
        ctx = self._dynamic_ctx(dynamic_symbol=True)
        contexts = {"ctx_0": ctx}
        secondaries = {"ctx_0": _secondary()}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            with pytest.raises(PineSecurityContextNotFoundError) as excinfo:
                request_module.security("SPY", "1D", _FakeSource("close"))

        err = excinfo.value
        assert err.reason == "dynamic_unsupported"
        assert err.context_id == "ctx_0"
        assert "not yet supported in M2" in str(err)

    def test_dynamic_timeframe_raises_documented_error(self):
        ctx = self._dynamic_ctx(dynamic_timeframe=True)
        contexts = {"ctx_0": ctx}
        secondaries = {"ctx_0": _secondary()}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            with pytest.raises(PineSecurityContextNotFoundError) as excinfo:
                request_module.security("SPY", "1D", _FakeSource("close"))
        assert excinfo.value.reason == "dynamic_unsupported"

    def test_static_context_unaffected_by_dynamic_check(self):
        """Sanity — a plain SecurityContext without the flags (the
        Wave-1 shape) must NOT trigger the dynamic-unsupported branch.
        Guards against a getattr default flipping to True by accident."""
        ctx = SecurityContext(symbol="SPY", timeframe="1D", expr="close")
        contexts = {"ctx_0": ctx}
        secondaries = {"ctx_0": _secondary()}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            # Must succeed — no dynamic flags set.
            v = request_module.security("SPY", "1D", _FakeSource("close"))
        assert v == _secondary()["close"].iloc[0]


# --- Nested install ---------------------------------------------------------


class TestNestedInstall:
    def test_lifo_unwind_restores_each_layer(self):
        """Installing the hook twice, then unwinding, must restore each
        layer's wrapper in LIFO order — outer install's function must be
        the one active after the inner exits."""
        from pynecore.lib import request as request_module

        original = request_module.security

        secondaries = {"ctx_0": _secondary()}
        contexts = {"ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close")}

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            outer_hook = request_module.security
            assert outer_hook is not original

            # Nest another install (e.g. a hypothetical recursive script
            # entrypoint). Different secondaries so we can prove the
            # inner takes precedence while active.
            inner_secondaries = {
                "ctx_0": _secondary(close_offset=999.0),
            }
            with install_secondaries_hook(
                inner_secondaries,
                contexts,
                get_current_bar_index=lambda: 0,
            ):
                # Inner hook is now active.
                assert request_module.security is not outer_hook
                v = request_module.security("SPY", "1D", _FakeSource("close"))
                # Inner's secondary starts at 999.
                assert v == inner_secondaries["ctx_0"]["close"].iloc[0]

            # Back to outer.
            assert request_module.security is outer_hook
            v = request_module.security("SPY", "1D", _FakeSource("close"))
            # Outer's secondary starts at 200 (default _secondary()).
            assert v == secondaries["ctx_0"]["close"].iloc[0]

        # Everything unwound.
        assert request_module.security is original


# --- Extra-kwargs tolerance -------------------------------------------------


class TestExtraKwargs:
    def test_extra_kwargs_accepted_and_ignored(self):
        """PyneCore's ``request.security`` signature accepts optional
        ``gaps`` / ``lookahead`` / ``ignore_invalid_symbol`` kwargs. The
        M2 hook accepts them but ignores their values (the c1x
        dispatcher already forward-filled)."""
        secondary = _secondary(rows=3)
        contexts = {"ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close")}
        secondaries = {"ctx_0": secondary}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            v = request_module.security(
                "SPY",
                "1D",
                _FakeSource("close"),
                gaps=object(),
                lookahead=object(),
                ignore_invalid_symbol=True,
            )
        assert v == secondary["close"].iloc[0]

    def test_missing_column_raises_keyerror(self):
        """A column-name that doesn't exist on the frame surfaces as
        KeyError, not silent NaN. Guards against a typo in the
        expression -> column mapping."""
        secondary = _secondary(rows=3)
        contexts = {"ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close")}
        secondaries = {"ctx_0": secondary}

        from pynecore.lib import request as request_module

        with install_secondaries_hook(
            secondaries, contexts, get_current_bar_index=lambda: 0
        ):
            with pytest.raises(KeyError, match="not_a_column"):
                request_module.security(
                    "SPY", "1D", _FakeSource("not_a_column")
                )
