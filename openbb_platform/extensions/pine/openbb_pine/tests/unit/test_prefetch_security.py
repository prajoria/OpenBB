"""Tests for ``openbb_pine.runtime.security_dispatcher`` — D5 §4.2.

Post-E0.2 the dispatcher no longer references FMP-specific types
(``FMPOHLCVProvider``, ``FMPRequest``, ``infer_asset_class``,
``fmp_retry.call_with_retry``). The caller (E0.3: ``executor_shell``)
wraps its concrete provider in a :class:`_DataProviderStub` and passes
it via ``provider=``.

Covers:

* the prefetch priority order (cache → data_resolver → dynamic-defer →
  provider),
* primary-index alignment via forward-fill,
* cache put/get pair,
* the empty-contexts short-circuit,
* the two E0.2 gate tests that pin the FMP decoupling:

  - ``test_dispatcher_does_not_import_fmp_provider_symbols``
  - ``test_dispatcher_accepts_stub_provider``

FMP retry / ``PineFMPUnreachableError`` envelope tests move OUT of this
file post-E0.3 (they become executor_shell's concern — the caller wraps
its FMP-flavoured ``_DataProviderStub`` in ``call_with_retry``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import pandas as pd
import pytest

from pyne_compiler.compiler.types import SecurityContext
from pyne_compiler.errors.base import PineDataResolverError
from pynecore.providers.provider import Provider as _DataProviderStub
from pyne_compiler.runtime.secondary_cache import SecondarySeriesCache
from pyne_compiler.runtime.security_dispatcher import (
    align_to_primary,
    prefetch_security_contexts,
)


# --- Fixtures ---------------------------------------------------------------


def _primary_frame(rows: int = 5) -> pd.DataFrame:
    """Build a primary OHLCV DataFrame indexed by tz-aware daily bars."""
    idx = pd.DatetimeIndex(
        [datetime(2024, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=i) for i in range(rows)],
        name="date",
    )
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [101.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [100.5 + i for i in range(rows)],
            "volume": [1_000_000.0 + i for i in range(rows)],
        },
        index=idx,
    )


def _secondary_frame(rows: int = 3, start_offset_days: int = 0) -> pd.DataFrame:
    """Build a secondary frame with (possibly) a different bar count so
    alignment / forward-fill is observable."""
    idx = pd.DatetimeIndex(
        [
            datetime(2024, 1, 1, tzinfo=timezone.utc)
            + pd.Timedelta(days=start_offset_days + i)
            for i in range(rows)
        ],
        name="date",
    )
    return pd.DataFrame(
        {
            "open": [200.0 + i for i in range(rows)],
            "high": [202.0 + i for i in range(rows)],
            "low": [198.0 + i for i in range(rows)],
            "close": [201.0 + i for i in range(rows)],
            "volume": [500_000.0 + i for i in range(rows)],
        },
        index=idx,
    )


class _RecordingStub(_DataProviderStub):
    """In-memory :class:`_DataProviderStub` for testing.

    Records every ``fetch`` call so tests can assert the dispatcher
    invoked it with the expected ``(symbol, timeframe, start, end)``.
    Optionally raises a caller-supplied exception on ``fetch`` to
    exercise error-propagation paths.
    """

    def __init__(
        self,
        fetch_result: pd.DataFrame | None = None,
        fetch_error: BaseException | None = None,
        fetch_impl: Callable[[str, str, datetime | None, datetime | None], pd.DataFrame]
        | None = None,
    ) -> None:
        self.fetch_result = fetch_result if fetch_result is not None else pd.DataFrame()
        self.fetch_error = fetch_error
        self.fetch_impl = fetch_impl
        self.calls: list[dict[str, object]] = []

    def stream(self, symbol, timeframe, *, start=None, end=None, include_gaps=False):  # noqa: D401
        raise NotImplementedError("_RecordingStub does not implement stream() for E0")

    # --- Provider ABC stubs (post-E3.4 Provider base is abstract) ------
    # These methods are required to instantiate a Provider subclass, but
    # the dispatcher never invokes them (it only calls fetch / stream).
    @classmethod
    def to_tradingview_timeframe(cls, timeframe: str) -> str:  # noqa: D401
        raise NotImplementedError

    @classmethod
    def to_exchange_timeframe(cls, timeframe: str) -> str:  # noqa: D401
        raise NotImplementedError

    def get_list_of_symbols(self, *args, **kwargs):  # noqa: D401
        raise NotImplementedError

    def get_opening_hours_and_sessions(self):  # noqa: D401
        raise NotImplementedError

    def update_symbol_info(self):  # noqa: D401
        raise NotImplementedError

    def download_ohlcv(self, time_from=None, time_to=None, on_progress=None, limit=None):  # noqa: D401
        raise NotImplementedError

    def fetch(self, symbol, timeframe, *, start=None, end=None, include_gaps=False):
        self.calls.append(
            {"symbol": symbol, "timeframe": timeframe, "start": start, "end": end}
        )
        if self.fetch_error is not None:
            raise self.fetch_error
        if self.fetch_impl is not None:
            return self.fetch_impl(symbol, timeframe, start, end)
        return self.fetch_result

    # E3.4: pynecore.providers.Provider ABC no-op impls (was previously the
    # openbb_pine._data_provider_stub non-abstract base; that stub is deleted
    # in this bead). Tests only exercise fetch()/stream(), so these are stubs.
    @classmethod
    def to_tradingview_timeframe(cls, timeframe):
        return timeframe

    @classmethod
    def to_exchange_timeframe(cls, timeframe):
        return timeframe

    def get_list_of_symbols(self, *args, **kwargs):
        return []

    def update_symbol_info(self):
        raise NotImplementedError

    def get_opening_hours_and_sessions(self):
        raise NotImplementedError

    def download_ohlcv(self, time_from, time_to, on_progress=None):
        raise NotImplementedError


# --- align_to_primary --------------------------------------------------------


class TestAlignToPrimary:
    def test_ffill_extends_secondary_across_primary_gaps(self):
        primary = _primary_frame(rows=5)  # 5 daily bars: Jan 1 .. Jan 5
        # Secondary has only 3 bars, ending Jan 3.
        secondary = _secondary_frame(rows=3)
        aligned = align_to_primary(secondary, primary.index)
        # Index matches primary exactly.
        assert list(aligned.index) == list(primary.index)
        # Last 2 rows should carry forward the Jan 3 (=index 2) close.
        assert aligned["close"].iloc[3] == secondary["close"].iloc[-1]
        assert aligned["close"].iloc[4] == secondary["close"].iloc[-1]

    def test_empty_secondary_returns_empty(self):
        primary = _primary_frame(rows=5)
        empty = pd.DataFrame()
        aligned = align_to_primary(empty, primary.index)
        assert aligned.empty


# --- E0.2 gate tests (per plan §E0.2 step 3) --------------------------------


class TestE02DecouplingGates:
    """Pin the E0.2 decoupling: the dispatcher must NOT reference any
    FMP-specific names. If a future edit reintroduces one, these tests
    fail loudly so the reviewer catches the regression."""

    def test_dispatcher_does_not_import_fmp_provider_symbols(self) -> None:
        """E0.2 gate: security_dispatcher must NOT reference FMPOHLCVProvider,
        FMPRequest, infer_asset_class, or fmp_retry — those are FMP-specific
        and get pushed up to the caller (executor_shell) post-E0.2."""
        import inspect

        from openbb_pine.runtime import security_dispatcher

        src = inspect.getsource(security_dispatcher)
        for banned in (
            "FMPOHLCVProvider",
            "FMPRequest",
            "infer_asset_class",
            "from openbb_pine.runtime.fmp_provider",
            "from openbb_pine.runtime.fmp_retry",
        ):
            assert (
                banned not in src
            ), f"security_dispatcher still references {banned!r} — E0.2 incomplete"

    def test_dispatcher_accepts_stub_provider(self) -> None:
        """A minimal in-memory stub satisfying _DataProviderStub must work
        end-to-end, proving the dispatcher no longer depends on FMP-specific types."""
        primary = _primary_frame(rows=5)
        secondary = _secondary_frame(rows=3)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        stub = _RecordingStub(fetch_result=secondary)

        result = prefetch_security_contexts(
            contexts,
            primary,
            provider=stub,
        )

        assert set(result) == {"ctx_0"}
        assert list(result["ctx_0"].index) == list(primary.index)
        # Dispatcher forwarded the (symbol, timeframe) pair from the context.
        assert len(stub.calls) == 1
        assert stub.calls[0]["symbol"] == "SPY"
        assert stub.calls[0]["timeframe"] == "1D"


# --- Empty contexts fast path ------------------------------------------------


class TestEmptyContexts:
    def test_none_contexts_returns_empty(self):
        # Empty must short-circuit with no fetches.
        primary = _primary_frame()
        result = prefetch_security_contexts(
            {}, primary, provider=None, data_resolver=None
        )
        assert result == {}

    def test_empty_contexts_never_touches_provider(self):
        primary = _primary_frame()
        stub = _RecordingStub()
        result = prefetch_security_contexts(
            {}, primary, provider=stub, data_resolver=None
        )
        assert result == {}
        assert stub.calls == []


# --- data_resolver priority --------------------------------------------------


class TestDataResolverPriority:
    def test_data_resolver_wins_over_provider(self):
        """When data_resolver is supplied, provider.fetch MUST NOT be invoked."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondary = _secondary_frame(rows=3)
        calls: list[tuple[str, str]] = []

        def resolver(symbol: str, timeframe: str) -> pd.DataFrame:
            calls.append((symbol, timeframe))
            return secondary

        stub = _RecordingStub(fetch_result=secondary)
        result = prefetch_security_contexts(
            contexts,
            primary,
            provider=stub,
            data_resolver=resolver,
        )
        assert calls == [("SPY", "1D")]
        assert stub.calls == [], "provider.fetch must not run when resolver wins"
        assert set(result) == {"ctx_0"}
        # Alignment: index should match primary (forward-fill applied).
        assert list(result["ctx_0"].index) == list(primary.index)

    def test_data_resolver_error_wraps_as_pine_data_resolver_error(self):
        """A resolver that raises must surface as PineDataResolverError with
        the offending symbol / timeframe / context_id attached."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_7": SecurityContext(symbol="MYPRIV", timeframe="60", expr="close"),
        }

        def bad_resolver(_symbol: str, _timeframe: str) -> pd.DataFrame:
            raise RuntimeError("underlying data source is down")

        with pytest.raises(PineDataResolverError) as excinfo:
            prefetch_security_contexts(
                contexts,
                primary,
                provider=None,
                data_resolver=bad_resolver,
            )
        err = excinfo.value
        assert err.symbol == "MYPRIV"
        assert err.timeframe == "60"
        assert err.context_id == "ctx_7"
        # Original exception preserved via __cause__ (chained raise).
        assert isinstance(err.__cause__, RuntimeError)


# --- Provider path ----------------------------------------------------------


class TestProviderPath:
    def test_provider_fetch_called_with_correct_symbol_and_timeframe(self):
        """Without data_resolver, the dispatcher must route through the
        caller-installed provider with the SecurityContext's symbol +
        timeframe."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondary = _secondary_frame(rows=5)
        stub = _RecordingStub(fetch_result=secondary)

        result = prefetch_security_contexts(
            contexts,
            primary,
            provider=stub,
            data_resolver=None,
        )
        # One secondary → one provider fetch with (symbol=SPY, tf=1D).
        assert len(stub.calls) == 1
        assert stub.calls[0]["symbol"] == "SPY"
        assert stub.calls[0]["timeframe"] == "1D"
        # Omitted primary_start / primary_end must forward as None so a
        # future default change (e.g. datetime.now(UTC)) is caught here
        # rather than silently altering provider fetch windows.
        assert stub.calls[0]["start"] is None
        assert stub.calls[0]["end"] is None
        # Aligned to primary index.
        assert list(result["ctx_0"].index) == list(primary.index)

    def test_provider_fetch_receives_primary_window_bounds(self):
        """The caller may pass ``primary_start`` / ``primary_end`` which get
        forwarded to ``provider.fetch`` as-is. Concrete providers use the
        window to shape their request."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondary = _secondary_frame(rows=5)
        stub = _RecordingStub(fetch_result=secondary)
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 10, tzinfo=timezone.utc)

        prefetch_security_contexts(
            contexts,
            primary,
            provider=stub,
            primary_start=start,
            primary_end=end,
        )
        assert stub.calls[0]["start"] == start
        assert stub.calls[0]["end"] == end

    def test_provider_fetch_exception_propagates_unchanged(self):
        """Anything raised by ``provider.fetch`` propagates as-is — the
        caller owns retry / envelope semantics (e.g. ``call_with_retry``
        for FMP producing ``PineFMPUnreachableError``)."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        stub = _RecordingStub(fetch_error=RuntimeError("HTTP 503 Service Unavailable"))

        with pytest.raises(RuntimeError, match="503"):
            prefetch_security_contexts(
                contexts,
                primary,
                provider=stub,
                data_resolver=None,
            )

    def test_provider_none_and_no_resolver_raises_valueerror(self):
        """Wiring bug — no provider and no resolver for a static context.
        Better a clean ValueError than a downstream AttributeError."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        with pytest.raises(ValueError, match="ctx_0"):
            prefetch_security_contexts(
                contexts,
                primary,
                provider=None,
                data_resolver=None,
            )


# --- Alignment --------------------------------------------------------------


class TestAlignment:
    def test_resolver_result_aligned_to_primary(self):
        """After the resolver returns, the aligned DataFrame's index MUST
        equal the primary's index — that's D5 §4.2 step 4."""
        primary = _primary_frame(rows=6)
        # Secondary intentionally has only 3 bars — forward-fill fills the rest.
        secondary = _secondary_frame(rows=3)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }

        result = prefetch_security_contexts(
            contexts,
            primary,
            provider=None,
            data_resolver=lambda *_a: secondary,
        )
        aligned = result["ctx_0"]
        assert list(aligned.index) == list(primary.index)
        # The tail bars carry the last-seen secondary close forward.
        assert aligned["close"].iloc[-1] == secondary["close"].iloc[-1]


# --- Cache path -------------------------------------------------------------


class TestCache:
    def test_cache_miss_then_hit(self, tmp_path):
        """First call → resolver fires, cache is populated. Second call
        with the same key → cache hits, resolver NOT invoked again."""
        primary = _primary_frame(rows=5)
        secondary = _secondary_frame(rows=3)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        cache = SecondarySeriesCache(cache_dir=tmp_path / "sec_cache")

        calls: list[tuple[str, str]] = []

        def resolver(symbol: str, timeframe: str) -> pd.DataFrame:
            calls.append((symbol, timeframe))
            return secondary

        r1 = prefetch_security_contexts(
            contexts,
            primary,
            provider=None,
            data_resolver=resolver,
            cache=cache,
        )
        assert len(calls) == 1

        r2 = prefetch_security_contexts(
            contexts,
            primary,
            provider=None,
            data_resolver=resolver,
            cache=cache,
        )
        # Hit — no additional call to the resolver.
        assert len(calls) == 1
        # Both frames are equivalent (same window, same alignment).
        assert list(r1["ctx_0"].index) == list(r2["ctx_0"].index)
        assert r1["ctx_0"]["close"].tolist() == r2["ctx_0"]["close"].tolist()

    def test_cache_hit_prevents_provider_fetch(self, tmp_path):
        """Cache hit must skip the entire provider path — ``provider.fetch``
        must NOT run on the second call. Prevents rate-limit blowup on
        repeated backtests."""
        primary = _primary_frame(rows=5)
        secondary = _secondary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        cache = SecondarySeriesCache(cache_dir=tmp_path / "sec_cache")

        # Pre-populate cache directly (simulates a prior run).
        # NB: the cache stores whatever alignment shape was written; use the
        # same window inference as the dispatcher (first/last of primary index).
        cache.put(
            "SPY",
            "1D",
            primary.index[0],
            primary.index[-1],
            align_to_primary(secondary, primary.index),
        )

        stub = _RecordingStub(
            fetch_error=AssertionError("should not fetch on cache hit")
        )

        result = prefetch_security_contexts(
            contexts,
            primary,
            provider=stub,
            data_resolver=None,
            cache=cache,
        )
        assert stub.calls == []
        assert list(result["ctx_0"].index) == list(primary.index)


# --- Non-DataFrame primary NotImplementedError (Wave-1 scope marker) --------


class TestNonDataFramePrimaryScope:
    def test_non_dataframe_primary_raises_notimplementederror(self):
        """Wave-1 scope: dispatcher expects a DataFrame primary because the
        executor pre-fetches. Passing anything else (post-E0.2: any
        request-builder object; the dispatcher no longer imports such
        types) is a wiring bug and should fail loud, not silently.
        """

        # Any non-DataFrame will do; use a plain object() to avoid
        # coupling to any concrete request-builder type (which the
        # dispatcher no longer knows about).
        not_a_frame = object()
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        stub = _RecordingStub()
        with pytest.raises(NotImplementedError, match="pd.DataFrame"):
            prefetch_security_contexts(
                contexts,
                not_a_frame,  # type: ignore[arg-type]  -- deliberate wrong type
                provider=stub,
                data_resolver=None,
            )


# --- SecondarySeriesCache put/get roundtrip (sanity) ------------------------


class TestSecondaryCacheRoundtrip:
    def test_put_then_get_returns_equivalent_frame(self, tmp_path):
        cache = SecondarySeriesCache(cache_dir=tmp_path / "sec")
        df = _secondary_frame(rows=4)
        cache.put("SPY", "1D", "2024-01-01", "2024-01-05", df)
        got = cache.get("SPY", "1D", "2024-01-01", "2024-01-05")
        assert got is not None
        assert list(got.index) == list(df.index)
        assert got["close"].tolist() == df["close"].tolist()

    def test_miss_returns_none(self, tmp_path):
        cache = SecondarySeriesCache(cache_dir=tmp_path / "sec")
        assert cache.get("SPY", "1D", "?", "?") is None

    def test_put_rejects_non_dataframe(self, tmp_path):
        cache = SecondarySeriesCache(cache_dir=tmp_path / "sec")
        with pytest.raises(TypeError, match="pd.DataFrame"):
            cache.put("SPY", "1D", "?", "?", "not a frame")  # type: ignore[arg-type]
