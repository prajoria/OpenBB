"""Unit tests for bd-9nd.12: TickEvent.payload carries quote content.

The refactor added a "quotes" key to TickEvent.payload so replay's
StubbedDataProvider can feed real recorded market data back to the
signal cascade — not just empty quotes like the pre-9nd.12 replay.

Verifies:
  * run_tick writes fetched quotes into TickEvent.payload["quotes"]
  * StubbedDataProvider.fetch_batch_quote reads them back keyed by
    the current tick_ts (set via set_current_tick_ts)
  * Backward compat: pre-9nd.12 journals (no "quotes" key) still
    yield empty quotes without crashing
  * Symbol filtering: fetch_batch_quote returns only symbols in the
    caller's watchlist (partial-watchlist replay works)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock


class TestRunTickWritesQuotesToPayload:
    """The forward change: run_tick puts the fetched quotes in the
    TickEvent it emits so a future replay can extract them."""

    def test_tick_event_payload_carries_quotes_list(self, monkeypatch):
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.models.journal_events import TickEvent

        recorded_quotes = [
            {"symbol": "MSFT", "price": "430.15"},
            {"symbol": "AAPL", "price": "212.50"},
        ]
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: recorded_quotes,
        )

        emitted: list = []
        session = MagicMock()
        session.plan.watchlist = ["MSFT", "AAPL"]
        session.plan.preset = "intraday_momentum"
        session.session_id = "s"
        session.emit = lambda e: emitted.append(e)

        tick_loop.run_tick(
            session,
            datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc),
        )

        ticks = [e for e in emitted if isinstance(e, TickEvent)]
        assert len(ticks) == 1
        payload = ticks[0].payload
        assert payload["quotes_fetched"] == 2  # count preserved
        assert payload["quotes"] == recorded_quotes  # NEW: content too

    def test_empty_quotes_still_emit_empty_list_field(self, monkeypatch):
        """When no quotes come back, the key is still present as [] so
        StubbedDataProvider can distinguish "no quotes" from "old event
        shape without the key" — that boundary matters for the
        backward-compat fall-through."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.models.journal_events import TickEvent

        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: [],
        )

        emitted: list = []
        session = MagicMock()
        session.plan.watchlist = ["MSFT"]
        session.plan.preset = "intraday_momentum"
        session.session_id = "s"
        session.emit = lambda e: emitted.append(e)

        tick_loop.run_tick(
            session,
            datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc),
        )

        ticks = [e for e in emitted if isinstance(e, TickEvent)]
        assert ticks[0].payload["quotes"] == []


class TestStubbedProviderReadsRecordedQuotes:
    """The other side: StubbedDataProvider reads the recorded quotes
    back when it's told which tick_ts to serve."""

    def test_fetch_batch_quote_returns_recorded_quotes_at_current_ts(self):
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import TickEvent

        ts = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        recorded_quotes = [
            {"symbol": "MSFT", "price": "430"},
            {"symbol": "AAPL", "price": "212"},
        ]
        tick = TickEvent(
            ts=ts,
            session_id="s",
            payload={
                "watchlist_size": 2,
                "quotes_fetched": 2,
                "quotes": recorded_quotes,
            },
        )
        provider = StubbedDataProvider(events=[tick])
        provider.set_current_tick_ts(ts)

        result = provider.fetch_batch_quote(["MSFT", "AAPL"], "fmp_cached")
        assert result == recorded_quotes

    def test_fetch_batch_quote_filters_by_requested_symbols(self):
        """Partial-watchlist replay: the tick has 3 quotes, caller asks
        for 2 — only the requested pair returns."""
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import TickEvent

        ts = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        tick = TickEvent(
            ts=ts, session_id="s",
            payload={
                "watchlist_size": 3,
                "quotes_fetched": 3,
                "quotes": [
                    {"symbol": "MSFT", "price": "430"},
                    {"symbol": "AAPL", "price": "212"},
                    {"symbol": "NVDA", "price": "1100"},
                ],
            },
        )
        provider = StubbedDataProvider(events=[tick])
        provider.set_current_tick_ts(ts)

        result = provider.fetch_batch_quote(["MSFT", "NVDA"], "fmp_cached")
        symbols = {q["symbol"] for q in result}
        assert symbols == {"MSFT", "NVDA"}  # AAPL filtered out

    def test_fetch_batch_quote_returns_empty_when_no_current_ts_set(self):
        """Pre-set-current-tick_ts state: empty quotes (safe default)."""
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import TickEvent

        ts = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        tick = TickEvent(
            ts=ts, session_id="s",
            payload={"quotes": [{"symbol": "MSFT", "price": "430"}]},
        )
        provider = StubbedDataProvider(events=[tick])
        # NOT calling set_current_tick_ts — bare instance
        assert provider.fetch_batch_quote(["MSFT"], "fmp_cached") == []

    def test_fetch_batch_quote_returns_empty_for_pre_9nd12_journal(self):
        """Backward compat: old journal without 'quotes' payload key
        returns empty (matches pre-9nd.12 replay behavior — no crash)."""
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import TickEvent

        ts = datetime(2026, 7, 13, 13, 30, tzinfo=timezone.utc)
        legacy_tick = TickEvent(
            ts=ts,
            session_id="s",
            payload={"watchlist_size": 1, "quotes_fetched": 1},
            # NOTE: no "quotes" key
        )
        provider = StubbedDataProvider(events=[legacy_tick])
        provider.set_current_tick_ts(ts)

        # Empty (not None, not KeyError) — clean legacy handling
        assert provider.fetch_batch_quote(["MSFT"], "fmp_cached") == []


class TestFullReplayRoundTripWithQuotes:
    """The whole point of bd-9nd.12: a journal produced by the current
    (post-9nd.12) run_tick can be replayed with fetch_batch_quote
    returning identical quotes — closing the loop."""

    def test_write_then_replay_yields_same_quotes(self, monkeypatch):
        """Simulate a live run's TickEvent + replay it: fetch_batch_quote
        during replay returns the exact quotes the live run recorded."""
        from openbb_fmp_trading.core import tick_loop
        from openbb_fmp_trading.core.data_provider import StubbedDataProvider
        from openbb_fmp_trading.models.journal_events import TickEvent

        live_quotes = [
            {"symbol": "MSFT", "price": "430.15", "ts": "2026-07-13T13:30:00+00:00"},
            {"symbol": "AAPL", "price": "212.50", "ts": "2026-07-13T13:30:00+00:00"},
        ]

        # --- Live run ---
        monkeypatch.setattr(
            tick_loop, "_fetch_batch_quote",
            lambda symbols, provider: live_quotes,
        )
        emitted: list = []
        session = MagicMock()
        session.plan.watchlist = ["MSFT", "AAPL"]
        session.plan.preset = "intraday_momentum"
        session.session_id = "s"
        session.emit = lambda e: emitted.append(e)

        tick_ts = datetime(2026, 7, 13, 13, 33, tzinfo=timezone.utc)
        tick_loop.run_tick(session, tick_ts)

        recorded_tick = next(e for e in emitted if isinstance(e, TickEvent))

        # --- Replay ---
        provider = StubbedDataProvider(events=[recorded_tick])
        provider.set_current_tick_ts(tick_ts)

        replayed_quotes = provider.fetch_batch_quote(
            ["MSFT", "AAPL"], "fmp_cached"
        )
        assert replayed_quotes == live_quotes
