"""DataProvider abstraction for the tick loop (P5-followup / bd-9nd.9).

Replaces the module-level monkey-patching of fetch seams in
``core/tick_loop.py`` with a proper ``Protocol`` that ``run_tick`` accepts
as a parameter. Two implementations ship:

* :class:`LiveDataProvider` — wraps the real ``obb.fmp_trading.*`` calls.
  Default when no provider is passed to ``run_tick``.
* :class:`StubbedDataProvider` — used by ``reporting.replay.replay`` to
  feed recorded quotes/bars back to the tick loop without touching FMP.

Design goals (bd-9nd.9):

1. **No more module-global monkey-patching.** The prior
   ``reporting.replay._stub_fetch_seams`` context manager mutated
   ``tick_loop._fetch_batch_quote`` etc. under a lock — fragile,
   non-thread-safe by construction, and any code that captured the
   original reference before the swap kept calling the original.
2. **Backward-compatible.** Existing callers of ``run_tick(session,
   tick_ts)`` continue to work — a module-level ``LiveDataProvider``
   instance is used when ``provider`` is omitted. Existing tests that
   monkey-patch ``tick_loop._fetch_batch_quote`` etc. also continue to
   work: the ``LiveDataProvider`` delegates to those module-level
   helpers rather than duplicating their bodies.
3. **Explicit dependency graph.** ``StubbedDataProvider`` accepts the
   recorded events at construction, resolves quotes by ``tick_ts`` at
   call time. No thread-lock, no reentrancy hazard.

The signal-cascade replay (feeding real recorded quote content back
through techtrade) still requires bd-9nd.12 (widen ``TickEvent.payload``
to carry quotes). This module provides the seam; 9nd.12 fills it in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataProvider(Protocol):
    """The five data-fetch operations ``run_tick`` needs.

    Implementations must satisfy all five signatures. The Protocol is
    ``@runtime_checkable`` so a construction-time
    ``isinstance(provider, DataProvider)`` guard works without a base
    class — matches how the shipped ``AgentBackend`` Protocol in
    ``agent.backend`` behaves.
    """

    def fetch_batch_quote(
        self, symbols: list[str], provider: str
    ) -> list[dict[str, Any]]:
        """Batched quote for the watchlist."""
        ...

    def fetch_recent_bars(self, symbols: list[str]) -> dict[str, list[Any]]:
        """Last N 5-min bars per symbol (window sized by indicator lookback)."""
        ...

    def fetch_session_status(self, exchange: str) -> Any:
        """Live session status (is_market_open, next_close, etc.)."""
        ...

    def is_signal_bar_close(self, tick_ts: datetime, preset: str) -> bool:
        """True when ``tick_ts`` lands on a signal-bar close boundary."""
        ...


# ---------------------------------------------------------------------------
# Live implementation — wraps the module-level helpers in tick_loop
# ---------------------------------------------------------------------------


class LiveDataProvider:
    """Real ``obb.fmp_trading.*``-backed provider.

    Delegates to the existing module-level helpers in
    :mod:`openbb_fmp_trading.core.tick_loop` (``_fetch_batch_quote``,
    ``_fetch_recent_bars``, ``_fetch_session_status``,
    ``_is_signal_bar_close``) rather than duplicating their bodies.
    This means:

    * Existing tests that ``monkeypatch.setattr(tick_loop,
      "_fetch_batch_quote", ...)`` continue to work — the
      ``LiveDataProvider`` will pick up the patched version because it
      calls the module attribute at request time, not import time.
    * A single source of truth for the fetch bodies (the module-level
      helpers) — no risk of ``LiveDataProvider`` and the module-level
      helpers drifting apart.

    The whole point of the refactor is to give ``run_tick`` an
    *injectable* seam; keeping ``LiveDataProvider`` a thin dispatcher
    preserves the existing test-patching contract while enabling
    replay to bypass it entirely.
    """

    def fetch_batch_quote(
        self, symbols: list[str], provider: str
    ) -> list[dict[str, Any]]:
        from openbb_fmp_trading.core import tick_loop
        return tick_loop._fetch_batch_quote(symbols, provider)

    def fetch_recent_bars(self, symbols: list[str]) -> dict[str, list[Any]]:
        from openbb_fmp_trading.core import tick_loop
        return tick_loop._fetch_recent_bars(symbols)

    def fetch_session_status(self, exchange: str) -> Any:
        from openbb_fmp_trading.core import tick_loop
        return tick_loop._fetch_session_status(exchange)

    def is_signal_bar_close(self, tick_ts: datetime, preset: str) -> bool:
        from openbb_fmp_trading.core import tick_loop
        return tick_loop._is_signal_bar_close(tick_ts, preset)


# ---------------------------------------------------------------------------
# Stubbed implementation — for replay + tests
# ---------------------------------------------------------------------------


class StubbedDataProvider:
    """Feeds recorded quotes/bars back to ``run_tick`` from a journal.

    Used by :func:`openbb_fmp_trading.reporting.replay.replay` to drive
    ``IntradaySession`` through recorded ticks without hitting FMP.

    Current implementation returns empty quotes/bars from every fetch
    call, because Phase 2's ``TickEvent.payload`` stores
    ``quotes_fetched: int`` (a count) rather than the quote content.
    bd-9nd.12 widens ``TickEvent.payload`` to carry the actual quotes;
    at that point this class extends to read them out of the payload
    keyed by ``tick_ts``.

    Design note: this class replaces the old
    ``reporting.replay._stub_fetch_seams`` context manager, which
    monkey-patched module globals under a threading lock. The
    Protocol-based design is thread-safe by construction (no shared
    mutable state), reentrant, and doesn't need the lock.

    Strict-lookup mode (bd-9nd.9 round 2, silent-failure-hunter finding):
    when ``strict=True`` (default), calls to :meth:`is_signal_bar_close`
    with a ts NOT present in the recorded events dict raise
    :class:`ReplayTsMismatch`. Rationale: a tz-offset or microsecond
    precision drift between the driving ``tick_event.ts`` and the
    recorded ``SignalEvent.ts`` would otherwise SILENTLY return False,
    causing replay to report "no divergence" while having skipped every
    signal cascade. Prefer noisy failure over silent skip. Set
    ``strict=False`` for legacy callers who explicitly want the tolerant
    behavior (e.g. replaying a partial-window journal).
    """

    def __init__(self, events: list | None = None, strict: bool = True) -> None:
        """Store journal events for future quote lookup (bd-9nd.12).

        Args:
          events: Recorded JournalEvent list from the source run.
          strict: When True (default), ``is_signal_bar_close`` raises
            :class:`ReplayTsMismatch` on unknown ts. When False, unknown
            ts returns False silently — legacy tolerant behavior.
        """
        # Bucket events by ts for O(1) per-tick lookup by the comparator
        # and by fetch_batch_quote's quote extraction.
        self._events_by_ts: dict = {}
        # TickEvent-specific lookup for fetch_batch_quote — a ts can
        # only have one TickEvent (the tick loop emits exactly one per
        # call), so keying by ts is unambiguous.
        self._tick_by_ts: dict = {}
        # Track ts values seen in TickEvents specifically — these are
        # the ts values run_tick is expected to be driven with (round-2
        # strict-mode check).
        self._known_tick_ts: set = set()
        for e in events or []:
            ts = getattr(e, "ts", None)
            if ts is not None:
                self._events_by_ts.setdefault(ts, []).append(e)
                if getattr(e, "event_type", None) == "tick":
                    self._tick_by_ts[ts] = e
                    self._known_tick_ts.add(ts)
        # Set by :meth:`set_current_tick_ts` before each ``run_tick``
        # call so ``fetch_batch_quote`` knows which recorded tick to
        # read quotes from. None until first set — legacy callers get
        # empty quotes, matching pre-9nd.12 behavior.
        self._current_tick_ts: Any = None
        self._strict = strict

    def set_current_tick_ts(self, tick_ts) -> None:
        """Set which recorded ``TickEvent.ts`` to read quotes from.

        Called by :func:`~openbb_fmp_trading.reporting.replay.replay`
        immediately before each ``run_tick(session, tick_ts, provider=self)``
        invocation. This is the seam that makes ``fetch_batch_quote``
        return the recorded quotes for the CURRENT tick rather than
        having to scan every event for a ts match.
        """
        self._current_tick_ts = tick_ts

    def fetch_batch_quote(
        self, symbols: list[str], provider: str
    ) -> list[dict[str, Any]]:
        """Return recorded quotes for the tick_ts we're currently replaying.

        bd-9nd.12 implementation: reads ``quotes`` out of the most recent
        ``TickEvent.payload["quotes"]`` seen at ``_current_tick_ts``.
        The caller (:func:`replay`) sets that timestamp before each
        ``run_tick`` call via :meth:`set_current_tick_ts`.

        Returns ``[]`` when:
          * ``_current_tick_ts`` is None (never set — bare use)
          * No TickEvent at that ts (partial-journal edge case)
          * TickEvent.payload lacks the "quotes" key (pre-9nd.12 journal)

        In each of those cases the tick loop still runs; the signal
        cascade just sees no quotes (matches pre-9nd.12 replay behavior).
        """
        if self._current_tick_ts is None:
            return []
        tick_event = self._tick_by_ts.get(self._current_tick_ts)
        if tick_event is None:
            return []
        payload = getattr(tick_event, "payload", {}) or {}
        recorded_quotes = payload.get("quotes")
        if not recorded_quotes:
            return []
        # Filter to requested symbols so partial-watchlist replay works
        symbol_set = set(symbols)
        return [q for q in recorded_quotes if q.get("symbol") in symbol_set]

    def fetch_recent_bars(self, symbols: list[str]) -> dict[str, list[Any]]:
        return {s: [] for s in symbols}

    def fetch_session_status(self, exchange: str) -> Any:
        # Return a minimal duck-typed object with is_market_open=True —
        # the tick loop only reads the attribute in _build_tick_data.
        return _StubSessionStatus(exchange=exchange, is_market_open=True)

    def is_signal_bar_close(self, tick_ts: datetime, preset: str) -> bool:
        # Round-2 review fix: catch tz/precision drift LOUDLY. If tick_ts
        # is not among the recorded TickEvent ts values, either the caller
        # is driving us with a fabricated ts (bug) or there's a
        # tz/microsecond mismatch that would silently skip the signal
        # cascade. Both cases should fail loud in strict mode.
        if self._strict and tick_ts not in self._known_tick_ts:
            # Show closest known ts to help the operator diagnose the drift.
            # Guard against tz-naive-vs-aware subtraction: if tick_ts is
            # naive but recorded is aware (or vice versa), the subtraction
            # in the key lambda raises TypeError, masking the intended
            # ReplayTsMismatch. Fall back to "no closest" in that case —
            # the error message still names the drift class.
            try:
                closest = min(
                    self._known_tick_ts,
                    key=lambda k: abs((k - tick_ts).total_seconds()),
                    default=None,
                )
            except TypeError:
                closest = None
            raise ReplayTsMismatch(
                f"tick_ts {tick_ts!r} not among recorded TickEvent ts values "
                f"(closest recorded: {closest!r}). This usually indicates a "
                f"timezone-offset or microsecond-precision drift between the "
                f"driving loop and the recorded journal — check tzinfo on "
                f"both sides. Pass strict=False to StubbedDataProvider to "
                f"restore the tolerant (silent-skip) behavior."
            )
        recorded_at_ts = self._events_by_ts.get(tick_ts, [])
        return any(
            getattr(e, "event_type", None) == "signal" for e in recorded_at_ts
        )


class ReplayTsMismatch(ValueError):
    """Raised when :class:`StubbedDataProvider` (strict mode) is asked
    about a ``tick_ts`` that wasn't in the recorded events.

    Almost always means a timezone-offset or microsecond-precision drift
    between the driving loop and the recorded journal. Silent-skip would
    hide this — see the ``strict`` argument on
    :class:`StubbedDataProvider`.
    """


class _StubSessionStatus:
    """Minimal duck-typed session_status for :class:`StubbedDataProvider`.

    The tick loop reads ``.is_market_open`` and ``.exchange``; anything
    else is not touched. Dataclass-free to avoid adding a dependency.
    """

    def __init__(self, exchange: str, is_market_open: bool) -> None:
        self.exchange = exchange
        self.is_market_open = is_market_open


# Module-level singleton used by ``run_tick`` when no provider is passed.
# Instantiating once at module load matches the "backward compat" goal —
# a caller writing ``run_tick(session, tick_ts)`` sees exactly the same
# behavior as before this refactor.
DEFAULT_LIVE_PROVIDER: DataProvider = LiveDataProvider()


__all__ = [
    "DEFAULT_LIVE_PROVIDER",
    "DataProvider",
    "LiveDataProvider",
    "ReplayTsMismatch",
    "StubbedDataProvider",
]
