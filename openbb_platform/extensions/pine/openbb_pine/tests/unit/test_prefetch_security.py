"""Tests for ``openbb_pine.runtime.security_dispatcher`` — D5 §4.2.

Covers the prefetch priority order (cache → data_resolver → dynamic-defer →
FMP + retry), primary-index alignment via forward-fill, cache put/get pair,
and the empty-contexts short-circuit. All FMP paths mock the OBB call
surface so the tests never hit the real API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from openbb_pine.compiler.types import SecurityContext
from openbb_pine.errors import (
    PineDataResolverError,
    PineFMPUnreachableError,
)
from openbb_pine.runtime.fmp_provider import FMPOHLCVProvider, FMPRequest
from openbb_pine.runtime import fmp_retry as fmp_retry_module
from openbb_pine.runtime import security_dispatcher as security_dispatcher_module
from openbb_pine.runtime.secondary_cache import SecondarySeriesCache
from openbb_pine.runtime.security_dispatcher import (
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


def _fmp_template(provider: str = "fmp") -> FMPOHLCVProvider:
    """Build a real FMPOHLCVProvider instance (the dispatcher only reads its
    ``.provider`` attribute — no fetches happen unless the test lets them)."""
    req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
    return FMPOHLCVProvider(req, provider=provider)


def _patch_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero out fmp_retry's sleep so retry-loop tests stay fast."""
    monkeypatch.setattr(fmp_retry_module.time, "sleep", lambda *_a, **_k: None)


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


# --- Empty contexts fast path ------------------------------------------------


class TestEmptyContexts:
    def test_none_contexts_returns_empty(self):
        # ``dict[str, SecurityContext]`` can't be None per signature, but
        # the runtime spec says "None or empty" → we take {} to be the
        # canonical empty. Empty must short-circuit with no fetches.
        primary = _primary_frame()
        result = prefetch_security_contexts(
            {}, primary, fmp_provider=None, data_resolver=None
        )
        assert result == {}

    def test_empty_contexts_never_touches_fmp(self):
        primary = _primary_frame()
        # Use a MagicMock so ANY attribute access would flag as called.
        fmp = MagicMock(spec=FMPOHLCVProvider)
        result = prefetch_security_contexts(
            {}, primary, fmp_provider=fmp, data_resolver=None
        )
        assert result == {}
        # No _fetch / no attribute access we care about.
        fmp.assert_not_called()


# --- data_resolver priority --------------------------------------------------


class TestDataResolverPriority:
    def test_data_resolver_wins_over_fmp(self, monkeypatch):
        """When data_resolver is supplied, fmp_provider MUST NOT be invoked."""
        _patch_sleep(monkeypatch)
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        secondary = _secondary_frame(rows=3)
        calls: list[tuple[str, str]] = []

        def resolver(symbol: str, timeframe: str) -> pd.DataFrame:
            calls.append((symbol, timeframe))
            return secondary

        fmp = MagicMock(spec=FMPOHLCVProvider)
        # If FMP were invoked we'd get a call log on _fetch — a real fetch
        # via the retry loop would blow up (no obb wired). The absence of
        # a raise is the primary assertion; the len==1 pins it further.
        result = prefetch_security_contexts(
            contexts,
            primary,
            fmp_provider=fmp,
            data_resolver=resolver,
        )
        assert calls == [("SPY", "1D")]
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
                fmp_provider=None,
                data_resolver=bad_resolver,
            )
        err = excinfo.value
        assert err.symbol == "MYPRIV"
        assert err.timeframe == "60"
        assert err.context_id == "ctx_7"
        # Original exception preserved via __cause__ (chained raise).
        assert isinstance(err.__cause__, RuntimeError)


# --- FMP path ---------------------------------------------------------------


class TestFMPPath:
    def test_fmp_fetch_called_with_correct_symbol_and_timeframe(self, monkeypatch):
        """Without data_resolver, the dispatcher must route through FMP with
        the SecurityContext's symbol + timeframe."""
        _patch_sleep(monkeypatch)
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }

        secondary = _secondary_frame(rows=5)
        # Track constructor args and _fetch invocations. We patch the
        # FMPOHLCVProvider imported by security_dispatcher, not the one in
        # fmp_provider.py — Python module-level name binding lives with the
        # importer.
        constructor_args: list[dict[str, Any]] = []

        def fake_provider_ctor(request: FMPRequest, *, provider: str):
            constructor_args.append({
                "symbol": request.symbol,
                "interval": request.interval,
                "provider": provider,
            })
            fake = MagicMock()
            fake._fetch.return_value = secondary
            return fake

        monkeypatch.setattr(
            security_dispatcher_module, "FMPOHLCVProvider", fake_provider_ctor
        )

        result = prefetch_security_contexts(
            contexts,
            primary,
            fmp_provider=_fmp_template(provider="fmp_cached"),
            data_resolver=None,
        )
        # One secondary → one FMP construction with (symbol=SPY, tf=1D).
        assert len(constructor_args) == 1
        assert constructor_args[0]["symbol"] == "SPY"
        assert constructor_args[0]["interval"] == "1D"
        assert constructor_args[0]["provider"] == "fmp_cached"
        # Aligned to primary index.
        assert list(result["ctx_0"].index) == list(primary.index)

    def test_fmp_failure_surfaces_as_pine_fmp_unreachable(self, monkeypatch):
        """Every FMP call must go through call_with_retry so a rate-limited
        or transient failure exhausts the shared budget as PineFMPUnreachableError."""
        _patch_sleep(monkeypatch)
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }

        def failing_ctor(_request: FMPRequest, *, provider: str):
            fake = MagicMock()
            fake._fetch.side_effect = Exception("HTTP 503 Service Unavailable")
            return fake

        monkeypatch.setattr(
            security_dispatcher_module, "FMPOHLCVProvider", failing_ctor
        )
        fmp_retry_module.reset_metrics()

        with pytest.raises(PineFMPUnreachableError):
            prefetch_security_contexts(
                contexts,
                primary,
                fmp_provider=_fmp_template(provider="fmp"),
                data_resolver=None,
            )
        # Retry envelope actually engaged (metric incremented once).
        assert fmp_retry_module._fmp_unreachable_counters.get("fmp", 0) == 1

    def test_fmp_provider_none_and_no_resolver_raises_valueerror(self):
        """Wiring bug — no FMP provider and no resolver for a static
        context. Better a clean ValueError than a downstream AttributeError."""
        primary = _primary_frame(rows=5)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        with pytest.raises(ValueError, match="ctx_0"):
            prefetch_security_contexts(
                contexts,
                primary,
                fmp_provider=None,
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
            fmp_provider=None,
            data_resolver=lambda *_a: secondary,
        )
        aligned = result["ctx_0"]
        assert list(aligned.index) == list(primary.index)
        # The tail bars carry the last-seen secondary close forward.
        assert aligned["close"].iloc[-1] == secondary["close"].iloc[-1]


# --- Cache path -------------------------------------------------------------


class TestCache:
    def test_cache_miss_then_hit(self, tmp_path, monkeypatch):
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
            fmp_provider=None,
            data_resolver=resolver,
            cache=cache,
        )
        assert len(calls) == 1

        r2 = prefetch_security_contexts(
            contexts,
            primary,
            fmp_provider=None,
            data_resolver=resolver,
            cache=cache,
        )
        # Hit — no additional call to the resolver.
        assert len(calls) == 1
        # Both frames are equivalent (same window, same alignment).
        assert list(r1["ctx_0"].index) == list(r2["ctx_0"].index)
        assert r1["ctx_0"]["close"].tolist() == r2["ctx_0"]["close"].tolist()

    def test_cache_hit_prevents_fmp_fetch(self, tmp_path, monkeypatch):
        """Cache hit must skip the entire FMP path — the ctor must NOT run
        on the second call. Prevents rate-limit blowup on repeated backtests."""
        _patch_sleep(monkeypatch)
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
            "SPY", "1D", primary.index[0], primary.index[-1],
            align_to_primary(secondary, primary.index),
        )

        ctor_calls: list[Any] = []

        def flag_ctor(*args, **kwargs):
            ctor_calls.append((args, kwargs))
            fake = MagicMock()
            fake._fetch.side_effect = AssertionError("should not fetch on cache hit")
            return fake

        monkeypatch.setattr(
            security_dispatcher_module, "FMPOHLCVProvider", flag_ctor
        )

        result = prefetch_security_contexts(
            contexts,
            primary,
            fmp_provider=_fmp_template(provider="fmp"),
            data_resolver=None,
            cache=cache,
        )
        assert ctor_calls == []
        assert list(result["ctx_0"].index) == list(primary.index)


# --- FMPRequest primary NotImplementedError (Wave-1 scope marker) ------------


class TestFMPRequestPrimaryScope:
    def test_fmprequest_primary_raises_notimplementederror(self):
        """Wave-1 scope: dispatcher expects a DataFrame primary because the
        executor pre-fetches. Passing an FMPRequest is a wiring bug and
        should fail loud, not silently."""
        req = FMPRequest(symbol="AAPL", interval="1d", start=None, end=None)
        contexts = {
            "ctx_0": SecurityContext(symbol="SPY", timeframe="1D", expr="close"),
        }
        with pytest.raises(NotImplementedError, match="FMPRequest"):
            prefetch_security_contexts(
                contexts,
                req,  # <-- FMPRequest instead of DataFrame
                fmp_provider=_fmp_template(),
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
