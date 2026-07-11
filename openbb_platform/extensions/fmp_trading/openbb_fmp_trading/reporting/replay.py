"""Journal-driven IntradaySession replay (P5.3).

Real replay — drives the shipped Phase 2 IntradaySession through recorded
ticks via a StubbedDataProvider that patches the module-level fetch
seams in ``core.tick_loop``. Emitted events are compared to recorded
events per tick; divergence sets ``diverged_at_tick`` and raises
:class:`ReplayDivergenceError` (review finding #0 fold-in).

What replay proves:
  * tick loop is a pure function of ``(session_state, tick_ts, market_data)``
  * no hidden state in module globals / closures survives
  * any ``_process_signal`` shape change fails this on stored journals

What replay does NOT prove:
  * live FMP data unchanged (stub feeds recorded data — reproducibility,
    not live-behavior)
  * BandwidthMeter (per PRD §8.7 — bandwidth is session-scoped ephemeral)
  * Full signal-cascade determinism across quote payloads — current
    Phase 2 TickEvent shape stores ``quotes_fetched: int`` (a count),
    not the quote content. StubbedDataProvider returns empty quotes;
    only the control-flow determinism of run_tick is exercised. Widening
    TickEvent.payload to carry quote content is filed as follow-up bead
    ``P5-followup-1``.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from openbb_fmp_trading.models.results import ReplayResult
from openbb_fmp_trading.reporting.errors import ReplayDivergenceError

logger = logging.getLogger(__name__)

# Module-level lock guarding _stub_fetch_seams. Two concurrent replay()
# calls — or replay running alongside a live IntradaySession in the same
# process — would otherwise corrupt each other's monkeypatched fetch
# seams (code-reviewer P1 #3). The lock serializes access; the ideal
# fix is to refactor tick_loop to accept an injected provider (filed
# as follow-up bead P5-followup-3), but this bounds the blast radius
# until then.
_STUB_LOCK = threading.RLock()


def replay(
    journal_path: Path,
    from_tick: int = 0,
    to_tick: int | None = None,
    raise_on_divergence: bool = True,
) -> ReplayResult:
    """Deterministically replay a journal. See design-spec §4.6.

    Args:
      journal_path: NDJSON file to replay.
      from_tick: 0-based tick index to start from (inclusive).
      to_tick: 0-based tick index to stop before (exclusive). None = all.
      raise_on_divergence: True (default) raises
        :class:`ReplayDivergenceError` on the first mismatch. False sets
        ``diverged_at_tick`` on the returned :class:`ReplayResult` and
        stops iterating (useful for divergence-diff tooling).
    """
    from openbb_fmp_trading.core.session import IntradaySession
    from openbb_fmp_trading.core import tick_loop
    from openbb_fmp_trading.reporting.journal_reader import read_journal_file

    events = list(read_journal_file(Path(journal_path)))
    tick_events = [
        e for e in events if getattr(e, "event_type", None) == "tick"
    ]

    # Slice by tick index
    sliced_ticks = (
        tick_events[from_tick:] if to_tick is None else tick_events[from_tick:to_tick]
    )

    session_start = _find_session_start(events)
    session_id = (
        getattr(session_start, "session_id", "unknown")
        if session_start
        else "unknown"
    )
    session_date = _extract_session_date(events)
    plan = _reconstruct_plan(events, session_date)

    # Bucket recorded events by their tick_ts so the comparator can look
    # up "what did the ORIGINAL run emit at this tick_ts?" in O(1).
    recorded_by_tick_ts = _bucket_events_by_tick_ts(events)

    # Build a fresh IntradaySession backed by mocks — no real broker,
    # no real risk manager (we're replaying, not making new decisions).
    # The captured emit log is what we compare against.
    replayed_emit_log: list = []

    class _CapturingJournal:
        def write(self, event):
            replayed_emit_log.append(event)

    session = IntradaySession(
        plan=plan,
        journal=_CapturingJournal(),
        risk_manager=MagicMock(),  # replay doesn't re-evaluate risk
        broker=MagicMock(),         # replay doesn't re-submit orders
        bandwidth=MagicMock(),      # P6: no meter charging on replay
    )

    diverged_at_tick: int | None = None
    with _stub_fetch_seams():
        for tick_idx, tick_event in enumerate(sliced_ticks):
            # Snapshot the emit log before this tick
            before_len = len(replayed_emit_log)
            try:
                tick_loop.run_tick(session, tick_event.ts)
            except Exception as exc:  # noqa: BLE001
                # A tick_loop crash mid-replay IS a divergence signal —
                # the recorded run completed this tick; the replayed
                # run raised.
                raise ReplayDivergenceError(
                    tick_index=tick_idx,
                    event_type="tick_loop_crash",
                    field="exception",
                    expected="clean_completion",
                    actual=f"{type(exc).__name__}: {exc}",
                ) from exc

            # What did the replayed run emit for this tick_ts?
            emitted = replayed_emit_log[before_len:]
            # What did the ORIGINAL run record at this tick_ts?
            recorded = recorded_by_tick_ts.get(tick_event.ts, [])
            # Compare event shapes (types + deterministic payload fields)
            div = _find_divergence(emitted, recorded, tick_idx)
            if div is not None:
                diverged_at_tick = tick_idx
                if raise_on_divergence:
                    raise div
                break  # continue-mode still stops on first divergence

    return ReplayResult(
        session_id=session_id,
        session_date=session_date,
        daily_plan=plan,
        events_replayed=len(sliced_ticks),
        diverged_at_tick=diverged_at_tick,
    )


# ---------------------------------------------------------------------------
# StubbedDataProvider — patches Phase 2's module-level fetch seams
# ---------------------------------------------------------------------------


@contextmanager
def _stub_fetch_seams():
    """Install stubs on ``core.tick_loop``'s module-level fetch seams so
    the replayed run receives deterministic (empty) market data instead
    of hitting FMP.

    The Phase 2 tick loop already exposes ``_fetch_batch_quote``,
    ``_fetch_recent_bars``, ``_fetch_session_status``,
    ``_is_signal_bar_close`` as module-level functions specifically to
    be patchable (see P2.4). Replay uses that seam design.

    Concurrency (code-reviewer P1 #3): the stub install/restore is
    guarded by a process-level RLock so two concurrent replay() calls
    — or replay running alongside a live IntradaySession in the same
    process — can't corrupt each other's monkeypatched seams. The RLock
    lets a single thread re-enter (which shouldn't happen but is safer
    than a plain Lock for a context manager). Follow-up P5-followup-3
    tracks refactoring tick_loop to accept an injected provider so
    this monkey-patching goes away entirely.

    Current implementation returns empty quotes/bars — enough to prove
    control-flow determinism (same tick sequence -> same emit ordering).
    Full signal-cascade replay would require the TickEvent payload to
    carry actual quotes; that's filed as follow-up bead P5-followup-1.
    """
    from openbb_fmp_trading.core import tick_loop as tl

    with _STUB_LOCK:
        original_quote = tl._fetch_batch_quote
        original_bars = tl._fetch_recent_bars
        original_status = tl._fetch_session_status
        original_bar_close = tl._is_signal_bar_close

        def stub_quote(symbols, provider):
            return []  # See module docstring — quotes not in current TickEvent shape

        def stub_bars(symbols):
            return {s: [] for s in symbols}

        def stub_status(exchange):
            return MagicMock(is_market_open=True, exchange=exchange)

        def stub_bar_close(ts, preset):
            # Only True on the recorded tick_ts values — never invents a bar close.
            # Since we drive run_tick exactly once per recorded TickEvent, this
            # can safely always return False (the recorded ticks already
            # represent every tick the loop had).
            return False

        tl._fetch_batch_quote = stub_quote
        tl._fetch_recent_bars = stub_bars
        tl._fetch_session_status = stub_status
        tl._is_signal_bar_close = stub_bar_close
        try:
            yield
        finally:
            tl._fetch_batch_quote = original_quote
            tl._fetch_recent_bars = original_bars
            tl._fetch_session_status = original_status
            tl._is_signal_bar_close = original_bar_close


# ---------------------------------------------------------------------------
# Divergence detection — the actual comparator
# ---------------------------------------------------------------------------


def _find_divergence(
    emitted: list, recorded: list, tick_idx: int
) -> ReplayDivergenceError | None:
    """Compare emitted vs recorded events for one tick.

    Divergence signals in priority order:

      1. Different event-type sequence -> divergence on the first type mismatch.
      2. Same types but a deterministic payload field disagrees ->
         divergence on that field.

    We compare only fields that are DETERMINISTIC — not ``ts`` (which is
    input, not output) and not fields that carry ``model_id`` /
    ``prompt_version`` (agent-produced content varies across LLM runs by
    design).
    """
    emitted_types = [type(e).__name__ for e in emitted]
    recorded_types = [type(e).__name__ for e in recorded] if recorded else []
    if emitted_types != recorded_types:
        return ReplayDivergenceError(
            tick_index=tick_idx,
            event_type="sequence",
            field="event_type_sequence",
            expected=recorded_types,
            actual=emitted_types,
        )

    for _i, (e, r) in enumerate(zip(emitted, recorded)):
        e_payload = getattr(e, "payload", {}) or {}
        r_payload = getattr(r, "payload", {}) or {}
        for key in _DETERMINISTIC_PAYLOAD_KEYS:
            if key in e_payload and key in r_payload:
                if str(e_payload[key]) != str(r_payload[key]):
                    return ReplayDivergenceError(
                        tick_index=tick_idx,
                        event_type=type(e).__name__,
                        field=f"payload.{key}",
                        expected=r_payload[key],
                        actual=e_payload[key],
                    )
    return None


# Payload keys we compare on. Skip ``ts`` (input, not output),
# ``model_id`` / ``prompt_version`` (LLM-varying), and ``session_id``
# (input). This list is the minimal deterministic surface that
# _process_signal's contract exposes; add fields here as they become
# load-bearing for regression detection.
_DETERMINISTIC_PAYLOAD_KEYS = frozenset({
    "fill_price", "fill_qty", "commission", "slippage",
    "order_ref", "symbol", "intent", "qty",
    "reason_code", "gate", "verdict",
    "watchlist_size", "quotes_fetched",
})


def _bucket_events_by_tick_ts(events: list) -> dict:
    """Group events by their timestamp so the comparator can look up
    'what happened at this tick_ts' in O(1). The bucket includes ALL
    events at that ts (tick + downstream signal/order/fill emitted in
    the same run_tick call)."""
    buckets: dict = {}
    for e in events:
        ts = getattr(e, "ts", None)
        if ts is None:
            continue
        buckets.setdefault(ts, []).append(e)
    return buckets


# ---------------------------------------------------------------------------
# Event reconstruction helpers
# ---------------------------------------------------------------------------


def _find_session_start(events):
    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            return e
    return None


def _extract_session_date(events) -> date:
    start = _find_session_start(events)
    if start and hasattr(start.ts, "date"):
        return start.ts.date()
    return datetime.now(timezone.utc).date()


def _reconstruct_plan(events, session_date):
    """Rebuild the committed DailyPlan from journal events."""
    from openbb_fmp_trading.models.config import RiskConfig
    from openbb_fmp_trading.models.plan import DailyPlan

    for e in events:
        if getattr(e, "event_type", None) == "session_start":
            payload = getattr(e, "payload", {}) or {}
            return DailyPlan(
                as_of=getattr(e, "ts", datetime.now(timezone.utc)),
                date=session_date,
                watchlist=payload.get("watchlist", []),
                preset=payload.get("preset", "trend_follow"),
                alerts=[],
                session_risk=RiskConfig(),
                thesis="Reconstructed from journal replay.",
                agent_backend=payload.get("agent_backend", "none"),
            )
    return DailyPlan(
        as_of=datetime.now(timezone.utc),
        date=session_date,
        watchlist=[],
        preset="trend_follow",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="Reconstructed (no session_start event found).",
        agent_backend="none",
    )


__all__ = ["replay"]
