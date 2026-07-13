"""Pure-function tick loop iterator: ``(session, tick_ts) -> list[JournalEvent]``.

Stateless w.r.t. the session between ticks — the session's mutable state
changes only through ``IntradaySession.emit()`` side effects. Rationale:
makes the whole loop replay-safe per PRD §11 golden-test contract.

P2.4 scope: full signal wiring. Bar-close detection triggers
``obb.techtrade.signals`` → ``obb.techtrade.plan`` → ``session._process_signal``
(chokepoint) → RiskManager → PaperBroker. Every quant op delegates to
``obb.techtrade.*``. NO signal math reimplemented here (G3 / NG2).

Data-fetch seams (bd-9nd.9 refactor): ``run_tick`` accepts an optional
``provider: DataProvider`` parameter. When omitted, a module-level
``LiveDataProvider`` is used — that provider delegates back to the
module-level ``_fetch_*`` / ``_is_signal_bar_close`` helpers below, so
existing test-monkeypatch of those helpers keeps working. Replay passes
a ``StubbedDataProvider`` that reads recorded events instead of hitting
FMP — no more module-global monkey-patching under a threading lock.

The five ``_fetch_*`` / ``_run_*`` / ``_build_*`` helpers stay
module-level (not methods) so tests that predate bd-9nd.9 continue to
work: any ``monkeypatch.setattr(tick_loop, "_fetch_batch_quote", ...)``
call will be picked up by ``LiveDataProvider`` because it dispatches
through the module attribute at call time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb_fmp_trading.core.data_provider import (
    DEFAULT_LIVE_PROVIDER,
    DataProvider,
)
from openbb_fmp_trading.models.journal_events import SignalEvent, TickEvent


def run_tick(
    session: Any,
    tick_ts: datetime,
    provider: DataProvider | None = None,
) -> list[Any]:
    """Execute one tick: poll quotes, journal a TickEvent, dispatch signals if
    this tick lands on a bar close, return every emitted event.

    Bar-close discipline: we only run signals when the current tick coincides
    with a signal-bar close boundary (default 5-min). Non-close ticks keep
    the poll loop cheap — one batch-quote fetch and one TickEvent, nothing more.

    Args:
        session: The :class:`IntradaySession` driving the tick.
        tick_ts: Current tick's tz-aware timestamp.
        provider: Optional :class:`DataProvider` for data fetches. Defaults
            to the module-level ``LiveDataProvider`` (which delegates to
            ``obb.fmp_trading.*``). Replay passes ``StubbedDataProvider``.
    """
    if provider is None:
        provider = DEFAULT_LIVE_PROVIDER

    events: list[Any] = []
    quotes = provider.fetch_batch_quote(
        session.plan.watchlist, provider="fmp_cached"
    )
    tick = _build_tick_data(session, tick_ts, quotes, provider)
    tick_event = TickEvent(
        ts=tick_ts,
        session_id=session.session_id,
        payload={
            "watchlist_size": len(session.plan.watchlist),
            "quotes_fetched": len(quotes),
            # bd-9nd.12: carry the actual quote content so replay's
            # StubbedDataProvider can feed real recorded quotes back to
            # techtrade.signals, enabling full signal-cascade determinism
            # (not just control-flow). Structured as list[dict] to match
            # what fetch_batch_quote returns. Storage cost: ~50-100 B per
            # symbol; at 30-symbol watchlist + 5-min ticks that's ~10 KB
            # per tick × ~7800 ticks/day = ~78 MB/day — acceptable.
            "quotes": list(quotes),
        },
    )
    events.append(tick_event)
    session.emit(tick_event)

    # Flat-by-close discipline runs BEFORE the signal cascade. During the
    # FORCE_CLOSE window, we synthesize exit plans for every open position
    # and route them through _process_signal (the chokepoint) so the same
    # RiskManager + journal path applies — no bypass.
    from openbb_fmp_trading.core.flat_by_close import WindowState, enter_flat_window
    window = enter_flat_window(tick_ts)
    if window == WindowState.FORCE_CLOSE:
        events.extend(_force_close_positions(session, tick))

    # Signal cascade only runs on bar-close ticks. This is the "OODA" step:
    # observe the closed bar, decide via techtrade, act through the
    # RiskManager-guarded chokepoint. The NO_NEW_OPENS + FORCE_CLOSE
    # windows do NOT short-circuit here — the RiskManager's G1 gate is
    # what rejects new opens, so any techtrade signal fires normally and
    # gets vetoed downstream (that veto is the audit trail we want).
    if provider.is_signal_bar_close(tick_ts, session.plan.preset):
        signals = _run_techtrade_signals(session.plan, tick)
        for sig in signals:
            signal_event = SignalEvent(
                ts=tick_ts,
                session_id=session.session_id,
                payload={
                    "symbol": getattr(sig, "symbol", None),
                    "score": _to_float_or_none(getattr(sig, "score", None)),
                    "direction": getattr(sig, "direction", None),
                },
            )
            events.append(signal_event)
            session.emit(signal_event)
            plan = _build_techtrade_plan(sig, tick)
            # _process_signal handles RiskManager + broker.submit + journal
            # of veto/order/fill events. Its return value extends this list.
            events.extend(session._process_signal(plan, tick))

    return events


# ---------------------------------------------------------------------------
# Module-level seams — kept for test-monkeypatch backward compat.
# LiveDataProvider (in data_provider.py) delegates to these at call time,
# so any monkeypatch here is transparently picked up.
# ---------------------------------------------------------------------------


def _fetch_batch_quote(symbols: list[str], provider: str) -> list[dict[str, Any]]:
    """Fetch batched quotes for the watchlist via fmp_trading.quote_batch.

    bd-9nd.12 round 2 (silent-failure hunter P0): use ``mode="json"`` so
    Decimal fields become strings and datetime fields become ISO strings
    HERE, at the emit boundary. Without ``mode="json"``, quotes carry
    Python-native Decimal/datetime, which ``event.model_dump_json()``
    coerces to strings at journal-write time — but ``json.loads`` at
    replay-read time gives strings back with no coercion (the payload
    field is typed ``dict[str, Any]``). Result: live-run quotes have
    ``Decimal("430.15")`` while replayed quotes have ``"430.15"``.
    Any techtrade consumer doing arithmetic on ``q["price"]`` would
    silently TypeError or, worse, do string-concat.

    Fix: normalize at the FETCH boundary so live and replayed quotes
    are structurally identical. Downstream consumers who need arithmetic
    now MUST parse to Decimal themselves — but they do so uniformly,
    not conditionally on whether the run is live or replayed.
    """
    from openbb import obb

    result = obb.fmp_trading.quote_batch(symbols=symbols, short=True, provider=provider)
    # mode="json" → Decimal/datetime → str/ISO. Idempotent through the
    # journal write/read cycle: live quotes == replayed quotes exactly.
    return [r.model_dump(mode="json") for r in result.results]


def _fetch_recent_bars(symbols: list[str]) -> dict[str, list[Any]]:
    """Fetch the last N 5-min bars per symbol (window sized by indicator lookback)."""
    from openbb import obb

    return {
        s: obb.fmp_trading.bars_intraday(
            symbols=[s], interval="5min", provider="fmp_cached"
        ).results
        for s in symbols
    }


def _fetch_session_status(exchange: str) -> Any:
    """Fetch the live session status (is_market_open, next_close, etc.)."""
    from openbb import obb

    return obb.fmp_trading.session_status(
        exchange=exchange, provider="fmp_cached"
    ).results


def _run_techtrade_signals(plan: Any, tick: Any) -> list[Any]:
    """Delegate signal computation to openbb-techtrade (G3 / NG2 — no math here)."""
    from openbb import obb

    result = obb.techtrade.signals(
        symbols=plan.watchlist, preset=plan.preset, bars=tick.bars_recent,
    )
    return list(result.results)


def _build_techtrade_plan(signal: Any, tick: Any) -> Any:
    """Delegate plan construction to openbb-techtrade."""
    from openbb import obb

    result = obb.techtrade.plan(signal=signal, tick=tick)
    return result.results


def _build_tick_data(
    session: Any,
    tick_ts: datetime,
    quotes: list[dict[str, Any]],
    provider: DataProvider,
) -> Any:
    """Assemble the TickData bundle handed to signals + RiskManager.

    Fetches recent bars + session status only when we're on a bar close —
    tests that stub ``is_signal_bar_close`` to False (via the provider)
    skip the extra I/O. Kept as a helper so P2.5 can inject flat-by-close
    state without editing every call site of run_tick.

    Data-fetch delegation: takes the DataProvider so bar / session-status
    fetches route through the same seam the top-level quote fetch does.
    """
    from openbb_fmp_trading.models.session_state import TickData

    if provider.is_signal_bar_close(tick_ts, session.plan.preset):
        bars_recent = provider.fetch_recent_bars(session.plan.watchlist)
        session_status = provider.fetch_session_status(exchange="NASDAQ")
    else:
        bars_recent = {}
        session_status = None
    return TickData(
        ts=tick_ts,
        quotes={q["symbol"]: q for q in quotes if "symbol" in q},
        bars_recent=bars_recent,
        session_status=session_status,
    )


def _is_signal_bar_close(tick_ts: datetime, preset: str) -> bool:
    """True when tick_ts lands on a 5-min bar close (default preset cadence).

    Presets may override this in the future (e.g. 1-min for scalping,
    15-min for slower confluence). Keeping the preset arg in the signature
    now so future callers don't need to be edited.

    Kept as a module-level helper so ``LiveDataProvider`` and any
    pre-bd-9nd.9 test monkeypatch have a single stable target.
    """
    return tick_ts.minute % 5 == 0 and tick_ts.second == 0


def _to_float_or_none(v: Any) -> float | None:
    """Coerce a possibly-Decimal score to float for JSON payloads; None-safe."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _force_close_positions(session: Any, tick: Any) -> list[Any]:
    """Route every open position through _process_signal as a synthetic exit.

    Called during the FORCE_CLOSE window (P4). We do NOT bypass
    _process_signal — the whole point of the chokepoint is that even
    end-of-day flatten operations go through RiskManager (which will
    approve exits regardless of gates that block opens).

    Position source: ``session.broker.positions()`` returns an iterable of
    Position-like objects with ``.symbol`` and ``.qty`` (signed: positive=long,
    negative=short). Each becomes a one-order synthetic plan.

    Duplicate-order guard (security-review HIGH #2): once we've queued a
    force-close for ``(symbol, session-date)`` during this session, we skip
    subsequent ticks for the same symbol. Without this, every tick in the
    FORCE_CLOSE window (12+ per minute at 5s cadence) would resubmit exit
    orders and stack up duplicates in the broker's order queue.

    Partial-failure isolation (security-review MEDIUM #3): each per-position
    _process_signal call is wrapped in try/except so one bad symbol cannot
    prevent flattening the rest of the book. Failures are journaled as
    VetoEvent-like entries via the standard log path in the session.
    """
    import logging
    from types import SimpleNamespace

    logger = logging.getLogger(__name__)

    events: list[Any] = []
    if not hasattr(session, "broker") or not hasattr(session.broker, "positions"):
        return events

    # Session-scoped idempotency ledger. Attribute-hasattr keeps the check
    # backward-compatible with any IntradaySession stubs in tests that don't
    # pre-populate the field.
    if not hasattr(session, "_forceclose_done"):
        session._forceclose_done = set()  # type: ignore[attr-defined]

    session_date = tick.ts.date() if hasattr(tick, "ts") else None

    positions = list(session.broker.positions() or [])
    for pos in positions:
        qty = getattr(pos, "qty", None)
        symbol = getattr(pos, "symbol", None)
        if not symbol or qty is None or qty == 0:
            continue

        # Skip symbols already queued for force-close this session-date
        dedup_key = (symbol, session_date)
        if dedup_key in session._forceclose_done:
            continue

        exit_intent = "CLOSE_LONG" if qty > 0 else "CLOSE_SHORT"
        exit_order = SimpleNamespace(
            ref=f"forceclose-{symbol}",
            symbol=symbol,
            qty=abs(qty),
            intent=exit_intent,
        )
        exit_plan = SimpleNamespace(
            symbol=symbol,
            intent=exit_intent,
            orders=[exit_order],
        )
        try:
            events.extend(session._process_signal(exit_plan, tick))
            # Only mark done after a successful chokepoint call. If the
            # RiskManager unexpectedly vetoes (shouldn't for exits, but
            # defense-in-depth), we still want to retry next tick.
            session._forceclose_done.add(dedup_key)
        except Exception as exc:  # noqa: BLE001 — end-of-day: never propagate
            logger.warning(
                "force-close for symbol=%s failed: %s; continuing with rest of book",
                symbol,
                exc,
            )
    return events
