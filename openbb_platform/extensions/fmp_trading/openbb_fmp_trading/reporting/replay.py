"""Journal-driven IntradaySession replay (P5.3).

Real replay — drives the shipped Phase 2 IntradaySession through recorded
ticks via a :class:`StubbedDataProvider` injected into ``run_tick``.
Emitted events are compared to recorded events per tick; divergence sets
``diverged_at_tick`` and raises :class:`ReplayDivergenceError` (review
finding #0 fold-in).

Refactor history:

* P5.3 shipping: used ``_stub_fetch_seams`` context manager to monkey-
  patch four module globals on ``core.tick_loop`` under a threading
  ``RLock`` for concurrency safety.
* **bd-9nd.9 (this file):** replaced the monkey-patch with an injected
  :class:`StubbedDataProvider` via ``run_tick``'s new ``provider=``
  parameter. Thread-safe by construction (no shared mutable state), no
  lock needed, no re-entrancy hazard.

What replay proves:
  * tick loop is a pure function of ``(session_state, tick_ts, market_data)``
  * no hidden state in module globals / closures survives
  * any ``_process_signal`` shape change fails this on stored journals

What replay does NOT prove:
  * live FMP data unchanged (stub feeds recorded data — reproducibility,
    not live-behavior)
  * BandwidthMeter (per PRD §8.7 — bandwidth is session-scoped ephemeral)
  * Full signal-cascade determinism across quote payloads — bd-9nd.12
    widens ``TickEvent.payload`` to carry quote content; until then
    ``StubbedDataProvider`` returns empty quotes and only control-flow
    determinism is exercised.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from openbb_fmp_trading.models.results import ReplayResult
from openbb_fmp_trading.reporting.errors import ReplayDivergenceError

logger = logging.getLogger(__name__)


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
    tick_events = [e for e in events if getattr(e, "event_type", None) == "tick"]

    # Slice by tick index
    sliced_ticks = (
        tick_events[from_tick:] if to_tick is None else tick_events[from_tick:to_tick]
    )

    session_start = _find_session_start(events)
    session_id = (
        getattr(session_start, "session_id", "unknown") if session_start else "unknown"
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
        broker=MagicMock(),  # replay doesn't re-submit orders
        bandwidth=MagicMock(),  # P6: no meter charging on replay
    )

    diverged_at_tick: int | None = None
    # bd-9nd.9 refactor: inject a StubbedDataProvider instead of
    # monkey-patching tick_loop module globals. Thread-safe by
    # construction — no shared mutable state, no lock, no reentrancy
    # hazard. Two concurrent replay() calls each get their own
    # StubbedDataProvider bound to their own recorded events.
    from openbb_fmp_trading.core.data_provider import StubbedDataProvider

    provider = StubbedDataProvider(events=events)
    for tick_idx, tick_event in enumerate(sliced_ticks):
        # Snapshot the emit log before this tick
        before_len = len(replayed_emit_log)
        # bd-9nd.12: tell the provider which recorded TickEvent's
        # quotes to serve for this tick so the signal cascade sees
        # real market data (not empty lists like pre-9nd.12 replay).
        provider.set_current_tick_ts(tick_event.ts)
        try:
            tick_loop.run_tick(session, tick_event.ts, provider=provider)
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
_DETERMINISTIC_PAYLOAD_KEYS = frozenset(
    {
        "fill_price",
        "fill_qty",
        "commission",
        "slippage",
        "order_ref",
        "symbol",
        "intent",
        "qty",
        "reason_code",
        "gate",
        "verdict",
        "watchlist_size",
        "quotes_fetched",
    }
)


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
                trading_date=session_date,
                watchlist=payload.get("watchlist", []),
                preset=payload.get("preset", "trend_follow"),
                alerts=[],
                session_risk=RiskConfig(),
                thesis="Reconstructed from journal replay.",
                agent_backend=payload.get("agent_backend", "none"),
            )
    return DailyPlan(
        as_of=datetime.now(timezone.utc),
        trading_date=session_date,
        watchlist=[],
        preset="trend_follow",
        alerts=[],
        session_risk=RiskConfig(),
        thesis="Reconstructed (no session_start event found).",
        agent_backend="none",
    )


__all__ = ["replay"]
