"""Pure-function tick loop iterator: ``(session, tick_ts) -> list[JournalEvent]``.

Stateless w.r.t. the session between ticks — the session's mutable state
changes only through ``IntradaySession.emit()`` side effects. Rationale:
makes the whole loop replay-safe per PRD §11 golden-test contract.

P2.4 scope: full signal wiring. Bar-close detection triggers
``obb.techtrade.signals`` → ``obb.techtrade.plan`` → ``session._process_signal``
(chokepoint) → RiskManager → PaperBroker. Every quant op delegates to
``obb.techtrade.*``. NO signal math reimplemented here (G3 / NG2).

The five ``_fetch_*`` / ``_run_*`` / ``_build_*`` helpers are all
module-level so tests can monkey-patch them individually. That granularity
matters: a signal-wiring test can stub only the techtrade calls while
letting bar/quote/session-status fetching go through the same code path
production runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openbb_fmp_trading.models.journal_events import SignalEvent, TickEvent


def run_tick(session: Any, tick_ts: datetime) -> list[Any]:
    """Execute one tick: poll quotes, journal a TickEvent, dispatch signals if
    this tick lands on a bar close, return every emitted event.

    Bar-close discipline: we only run signals when the current tick coincides
    with a signal-bar close boundary (default 5-min). Non-close ticks keep
    the poll loop cheap — one batch-quote fetch and one TickEvent, nothing more.
    """
    events: list[Any] = []
    quotes = _fetch_batch_quote(session.plan.watchlist, provider="fmp_cached")
    tick = _build_tick_data(session, tick_ts, quotes)
    tick_event = TickEvent(
        ts=tick_ts,
        session_id=session.session_id,
        payload={
            "watchlist_size": len(session.plan.watchlist),
            "quotes_fetched": len(quotes),
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
    if _is_signal_bar_close(tick_ts, session.plan.preset):
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
# Module-level seams — all patched individually in unit tests. Keeping them
# as free functions (not methods) means a test can substitute one without
# constructing a full session or importing the real openbb runtime.
# ---------------------------------------------------------------------------


def _fetch_batch_quote(symbols: list[str], provider: str) -> list[dict[str, Any]]:
    """Fetch batched quotes for the watchlist via fmp_trading.quote_batch."""
    from openbb import obb

    result = obb.fmp_trading.quote_batch(symbols=symbols, short=True, provider=provider)
    return [r.model_dump() for r in result.results]


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


def _build_tick_data(session: Any, tick_ts: datetime, quotes: list[dict[str, Any]]) -> Any:
    """Assemble the TickData bundle handed to signals + RiskManager.

    Fetches recent bars + session status only when we're on a bar close —
    tests that stub ``_is_signal_bar_close`` to False skip the extra I/O.
    Kept as a helper so P2.5 can inject flat-by-close state without editing
    every call site of run_tick.
    """
    from openbb_fmp_trading.models.session_state import TickData

    if _is_signal_bar_close(tick_ts, session.plan.preset):
        bars_recent = _fetch_recent_bars(session.plan.watchlist)
        session_status = _fetch_session_status(exchange="NASDAQ")
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
    """
    from types import SimpleNamespace

    events: list[Any] = []
    if not hasattr(session, "broker") or not hasattr(session.broker, "positions"):
        return events

    positions = list(session.broker.positions() or [])
    for pos in positions:
        qty = getattr(pos, "qty", None)
        symbol = getattr(pos, "symbol", None)
        if not symbol or qty is None or qty == 0:
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
        events.extend(session._process_signal(exit_plan, tick))
    return events
