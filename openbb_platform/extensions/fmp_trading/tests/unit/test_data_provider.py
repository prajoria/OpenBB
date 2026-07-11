"""Unit tests for core/data_provider.py (bd-9nd.9).

Verifies:
  * DataProvider protocol conformance for both shipped implementations
  * LiveDataProvider delegates to module-level helpers (existing test
    monkeypatch pattern still works)
  * StubbedDataProvider returns empty data + only True is_signal_bar_close
    for tick_ts values that had a recorded SignalEvent (prevents
    spurious bar closes during partial-journal replay)
  * run_tick accepts provider= kwarg (backward compat: omission works)
  * Concurrent replay() calls don't interfere (no shared state)
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock


class TestDataProviderProtocolConformance:
    def test_live_provider_is_data_provider(self):
        from openbb_fmp_trading.core.data_provider import (
            DataProvider,
            LiveDataProvider,
        )

        assert isinstance(LiveDataProvider(), DataProvider)

    def test_stubbed_provider_is_data_provider(self):
        from openbb_fmp_trading.core.data_provider import (
            DataProvider,
            StubbedDataProvider,
        )

        assert isinstance(StubbedDataProvider(), DataProvider)


class TestLiveProviderDelegates:
    """The whole point of LiveDataProvider is that it delegates to the
    module-level tick_loop helpers, so existing tests that
    monkeypatch tick_loop._fetch_batch_quote (etc.) keep working."""

    def test_live_provider_fetch_batch_quote_delegates(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.data_provider import LiveDataProvider

        captured = {}

        def fake_fetch(symbols, provider):
            captured["symbols"] = symbols
            captured["provider"] = provider
            return [{"symbol": "MSFT", "price": "430"}]

        monkeypatch.setattr(tick_loop, "_fetch_batch_quote", fake_fetch)
        result = LiveDataProvider().fetch_batch_quote(
            ["MSFT"], provider="fmp_cached"
        )

        assert result == [{"symbol": "MSFT", "price": "430"}]
        assert captured == {"symbols": ["MSFT"], "provider": "fmp_cached"}

    def test_live_provider_is_signal_bar_close_delegates(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.data_provider import LiveDataProvider

        monkeypatch.setattr(
            tick_loop, "_is_signal_bar_close", lambda ts, preset: True
        )
        assert LiveDataProvider().is_signal_bar_close(
            datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc),
            "intraday_momentum",
        )


class TestStubbedProviderReadsRecordedEvents:
    """StubbedDataProvider must only return True is_signal_bar_close for
    tick_ts values where the recorded events contained a SignalEvent —
    otherwise replay of a partial journal window would invent bar closes."""

    def test_empty_events_never_signals_bar_close(self):
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        provider = StubbedDataProvider(events=[])
        assert not provider.is_signal_bar_close(
            datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc),
            "intraday_momentum",
        )

    def test_signal_at_ts_returns_true(self):
        """A recorded SignalEvent at ts N means the ORIGINAL run had a
        bar close there — replay must reproduce that timing."""
        from openbb_fmp_trading.models.journal_events import SignalEvent
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        signal_ts = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        events = [
            SignalEvent(
                ts=signal_ts,
                session_id="s",
                payload={"symbol": "MSFT"},
            ),
        ]
        provider = StubbedDataProvider(events=events)
        assert provider.is_signal_bar_close(signal_ts, "intraday_momentum")
        # Any other ts returns False — no spurious bar closes
        other_ts = datetime(2026, 7, 13, 13, 35, tzinfo=timezone.utc)
        assert not provider.is_signal_bar_close(other_ts, "intraday_momentum")

    def test_fetch_batch_quote_returns_empty(self):
        """Current bd-9nd.9 shape: empty quotes. bd-9nd.12 will change this."""
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        provider = StubbedDataProvider()
        assert provider.fetch_batch_quote(["MSFT", "AAPL"], "fmp_cached") == []

    def test_fetch_recent_bars_returns_empty_dict_per_symbol(self):
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        provider = StubbedDataProvider()
        assert provider.fetch_recent_bars(["MSFT", "AAPL"]) == {
            "MSFT": [],
            "AAPL": [],
        }

    def test_fetch_session_status_returns_open_stub(self):
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        provider = StubbedDataProvider()
        status = provider.fetch_session_status(exchange="NASDAQ")
        assert status.exchange == "NASDAQ"
        assert status.is_market_open is True


class TestRunTickAcceptsProvider:
    """Backward-compat + injection-point contract."""

    def test_run_tick_default_uses_live_provider(self, monkeypatch):
        """No provider= arg -> DEFAULT_LIVE_PROVIDER is used (existing
        callers keep working)."""
        from openbb_fmp_trading.core import tick_loop

        # Spy on the module-level helper — LiveDataProvider delegates
        # here, so if the default resolves correctly this fires.
        call_count = [0]

        def spy(symbols, provider):
            call_count[0] += 1
            return []

        monkeypatch.setattr(tick_loop, "_fetch_batch_quote", spy)

        session = MagicMock()
        session.plan.watchlist = ["MSFT"]
        session.plan.preset = "intraday_momentum"
        session.session_id = "s"

        tick_loop.run_tick(
            session, datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc)
        )
        assert call_count[0] == 1

    def test_run_tick_explicit_provider_bypasses_module_helpers(
        self, monkeypatch
    ):
        """Passing provider= means module-level monkeypatches are NOT called."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        # Set a booby-trap on the module helper: it should NOT be called
        module_call_count = [0]

        def booby_trap(symbols, provider):
            module_call_count[0] += 1
            return []

        monkeypatch.setattr(tick_loop, "_fetch_batch_quote", booby_trap)

        session = MagicMock()
        session.plan.watchlist = ["MSFT"]
        session.plan.preset = "intraday_momentum"
        session.session_id = "s"

        tick_loop.run_tick(
            session,
            datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc),
            provider=StubbedDataProvider(),
        )

        # Module helper NEVER called — provider argument short-circuited it
        assert module_call_count[0] == 0


class TestNoSharedMutableState:
    """bd-9nd.9 P0: two concurrent StubbedDataProvider instances must not
    interfere. The prior threading.RLock guarded against monkey-patch
    corruption; the refactor removes both the lock AND the interference
    by design (no shared state)."""

    def test_two_provider_instances_have_independent_events(self):
        from openbb_fmp_trading.models.journal_events import SignalEvent
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider

        ts_a = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        ts_b = datetime(2026, 7, 13, 13, 35, tzinfo=timezone.utc)

        p_a = StubbedDataProvider(
            events=[SignalEvent(ts=ts_a, session_id="a", payload={})]
        )
        p_b = StubbedDataProvider(
            events=[SignalEvent(ts=ts_b, session_id="b", payload={})]
        )

        # p_a knows about ts_a; p_b knows about ts_b; neither knows the other
        assert p_a.is_signal_bar_close(ts_a, "x")
        assert not p_a.is_signal_bar_close(ts_b, "x")
        assert p_b.is_signal_bar_close(ts_b, "x")
        assert not p_b.is_signal_bar_close(ts_a, "x")

    def test_concurrent_run_tick_with_stubbed_providers_no_interference(
        self, monkeypatch
    ):
        """Two threads each running run_tick with their own
        StubbedDataProvider must not corrupt each other's data.

        Regression for bd-9nd.9 P0: the prior monkey-patch approach was
        thread-safe ONLY because of a global lock. This refactor removes
        the lock — the isolation is now structural."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import SignalEvent

        # Booby-trap the module helper so if the injection path fails
        # and it falls through to the live path, we notice.
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: (_ for _ in ()).throw(
                AssertionError("Module helper called — provider injection failed")
            ),
        )

        ts_a = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        ts_b = datetime(2026, 7, 13, 13, 35, tzinfo=timezone.utc)
        p_a = StubbedDataProvider(
            events=[SignalEvent(ts=ts_a, session_id="a", payload={})]
        )
        p_b = StubbedDataProvider(
            events=[SignalEvent(ts=ts_b, session_id="b", payload={})]
        )

        errors: list = []

        def worker(provider, tick_ts):
            try:
                session = MagicMock()
                session.plan.watchlist = ["MSFT"]
                session.plan.preset = "intraday_momentum"
                session.session_id = "concurrent"
                tick_loop.run_tick(session, tick_ts, provider=provider)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(p_a, ts_a)),
            threading.Thread(target=worker, args=(p_b, ts_b)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Concurrent run_tick errored: {errors}"
