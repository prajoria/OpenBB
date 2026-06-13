"""Event-driven source-of-truth engine (component 05).

A bar-by-bar session loop that is **look-ahead-free by construction**: at each
session the strategy sees a point-in-time :class:`~openbb_backtest.interfaces.MarketData`
view bounded at ``now``, and orders decided at session ``t`` only fill at ``t+1``
(no same-bar fill). This is the engine of record against which the fast
vectorized engine (component 04) is reconciled.

Two fill bases are supported:

- ``next_bar_open`` (default) — a realistic Decimal cash + positions ledger.
  Target weights become signed share orders filled through the shared
  :class:`~openbb_backtest.engine.execution.RealisticBroker` at the next bar's
  open, emitting full ``trades[]`` / ``positions[]`` / ``equity_curve[]``.
- ``close_on_decision`` — a frictionless weight-based path (close-to-close
  returns, one-bar hold) used for exact parity with the vectorized engine's
  matrix accounting, which is what makes the reconciliation gate (C05.3)
  meaningful.

Reuses the vectorized engine's pure helpers (``_PITView``, ``turnover``,
``_metrics_from_returns``, ``_round_money``, ``_as_utc``) so the shared numbers
agree by construction.

See ``docs/designs/backtest-design/05-event-driven-engine.md`` and
``06-execution-realism.md``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal

import numpy as np
import pandas as pd

from openbb_backtest.engine.vectorized import (
    _as_utc,
    _metrics_from_returns,
    _PITView,
    _round_money,
    cost_rate,
    turnover,
)
from openbb_backtest.interfaces import Broker, DataFeed, Strategy
from openbb_backtest.models import (
    BacktestConfig,
    BacktestResult,
    Bar,
    EquityPoint,
    PositionSnapshot,
    Trade,
)
from openbb_backtest.registry import register_engine

logger = logging.getLogger(__name__)

FillBasis = Literal["next_bar_open", "close_on_decision"]

_OHLC = ("open", "high", "low", "close")


def _bars_at(
    feed: DataFeed, sess: pd.Timestamp, symbols: list[str]
) -> dict[str, dict]:
    """Return the OHLCV row per symbol at ``sess`` (look-ahead-free).

    Uses the feed's ``history`` with ``lookback=1`` so only data up to ``sess``
    is visible. Symbols without a bar exactly at ``sess`` are omitted.
    """
    hist = feed.history(symbols, end=sess, lookback=1)
    if hist is None or hist.empty:
        return {}
    out: dict[str, dict] = {}
    for sym, row in hist.set_index("symbol").iterrows():
        if pd.Timestamp(row["session"]) == pd.Timestamp(sess):
            out[str(sym)] = row.to_dict()
    return out


def _make_bar(symbol: str, ts: pd.Timestamp, row: dict) -> Bar:
    """Build a :class:`Bar` (Decimal OHLCV) from a feed row for the broker."""
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row.get("volume", 0) or 0)),
        spread_bps=float(row.get("spread_bps", 0.0) or 0.0),
    )


def _session_weights(
    strategy: Strategy,
    feed: DataFeed,
    sess: pd.Timestamp,
    symbols: list[str],
    col_index: dict[str, int],
) -> np.ndarray:
    """Target weight vector generated at ``sess`` from a point-in-time view.

    Mirrors the vectorized engine's per-session parsing (``weight`` or
    ``signal`` column, NaN weights skipped, out-of-universe names ignored) so
    both engines build the same weights from the same strategy.
    """
    gen = strategy.generate(_PITView(feed, sess))
    weights = np.zeros(len(symbols))
    if gen is None or len(gen) == 0:
        return weights
    wcol = "weight" if "weight" in gen.columns else "signal"
    for sym, val in gen[wcol].items():
        j = col_index.get(sym)
        if j is not None and pd.notna(val):
            weights[j] = float(val)
    return weights


def _simple_return(close_now: np.ndarray, prev_close: np.ndarray | None) -> np.ndarray:
    """Per-symbol simple return into the current bar (zero on the first bar)."""
    if prev_close is None:
        return np.zeros_like(close_now)
    valid = (prev_close != 0) & ~np.isnan(prev_close) & ~np.isnan(close_now)
    ret = np.zeros_like(close_now)
    ret[valid] = (close_now[valid] - prev_close[valid]) / prev_close[valid]
    return ret


def _run_weight_based(
    strategy: Strategy,
    config: BacktestConfig,
    feed: DataFeed,
    sessions: pd.DatetimeIndex,
    symbols: list[str],
) -> BacktestResult:
    """Close-to-close weight accounting (``close_on_decision``).

    An independent event-loop implementation of the vectorized engine's matrix
    accounting: the weight decided at a session is *held* into the next and
    applied to the close-to-close return, with the SAME shared per-turnover cost
    rate subtracted. This is the apples-to-apples parity path that reconciles
    with the vectorized curve to within tolerance (the reconciliation gate).
    """
    col_index = {sym: j for j, sym in enumerate(symbols)}
    rate = cost_rate(config.commission, config.slippage)
    equity = float(config.initial_cash)
    held = np.zeros(len(symbols))  # weights held INTO the current session
    prev_held = np.zeros(len(symbols))
    prev_close: np.ndarray | None = None

    equity_curve: list[EquityPoint] = []
    equity_values: list[float] = []
    port_returns: list[float] = []
    held_matrix: list[np.ndarray] = []

    for sess in sessions:
        close_now = _closes(feed, sess, symbols)
        ret = _simple_return(close_now, prev_close)
        # Same cost convention as the vectorized engine: turnover * flat rate.
        session_turnover = float(np.abs(held - prev_held).sum())
        port_ret = float((held * ret).sum()) - session_turnover * rate
        equity *= 1.0 + port_ret

        net_exposure = float(held.sum())
        equity_curve.append(
            EquityPoint(
                date=_as_utc(sess),
                equity=_round_money(equity),
                cash=_round_money(equity * (1.0 - net_exposure)),
                exposure=net_exposure,
            )
        )
        equity_values.append(equity)
        port_returns.append(port_ret)
        held_matrix.append(held.copy())

        prev_held = held
        held = _session_weights(strategy, feed, sess, symbols, col_index)
        prev_close = close_now

    metrics = _metrics_from_returns(
        np.array(equity_values), np.array(port_returns), turnover(np.array(held_matrix))
    )
    return BacktestResult(
        equity_curve=equity_curve,
        trades=[],
        positions=[],
        metrics=metrics,
        engine_used=EventDrivenEngine.name,
        config=config,
    )


def _closes(feed: DataFeed, sess: pd.Timestamp, symbols: list[str]) -> np.ndarray:
    """Close price per symbol at ``sess`` (NaN when missing)."""
    bars = _bars_at(feed, sess, symbols)
    return np.array([float(bars[s]["close"]) if s in bars else np.nan for s in symbols])


def _apply_trade(
    cash: Decimal, positions: dict[str, Decimal], trade: Trade
) -> Decimal:
    """Update ``cash`` and ``positions`` (in place) for a filled ``trade``."""
    signed = trade.quantity if trade.side == "buy" else -trade.quantity
    cash -= signed * trade.price
    cash -= trade.commission
    positions[trade.symbol] = positions.get(trade.symbol, Decimal("0")) + signed
    return cash


def _run_ledger(
    strategy: Strategy,
    config: BacktestConfig,
    feed: DataFeed,
    broker: Broker,
    sessions: pd.DatetimeIndex,
    symbols: list[str],
) -> BacktestResult:
    """Realistic Decimal ledger with next-bar-open broker fills.

    Orders decided at session ``t`` fill at ``t+1``'s open through the shared
    broker, so the path is structurally look-ahead-free and its execution costs
    match the vectorized engine's broker exactly.
    """
    col_index = {sym: j for j, sym in enumerate(symbols)}
    cash = Decimal(str(config.initial_cash))
    positions: dict[str, Decimal] = {s: Decimal("0") for s in symbols}
    pending: np.ndarray | None = None  # target weights decided at the prior bar

    equity_curve: list[EquityPoint] = []
    position_snaps: list[PositionSnapshot] = []
    trades: list[Trade] = []
    equity_values: list[float] = []
    port_returns: list[float] = []
    weights_matrix: list[np.ndarray] = []
    prev_equity = float(config.initial_cash)

    for sess in sessions:
        ts = _as_utc(sess)
        bars = _bars_at(feed, sess, symbols)

        # 1) Fill orders decided at the previous bar, at THIS bar's open.
        if pending is not None:
            equity_at_fill = cash + sum(
                positions[s] * Decimal(str(bars[s]["open"]))
                for s in symbols
                if s in bars
            )
            for s in symbols:
                if s not in bars:
                    continue
                open_px = Decimal(str(bars[s]["open"]))
                if open_px <= 0:
                    continue
                target_shares = (
                    Decimal(str(pending[col_index[s]])) * equity_at_fill / open_px
                )
                order_qty = target_shares - positions[s]
                if order_qty == 0:
                    continue
                bar = _make_bar(s, ts, bars[s])
                orders = pd.DataFrame({"quantity": [order_qty]}, index=[s])
                for trade in broker.fill(orders, bar):
                    cash = _apply_trade(cash, positions, trade)
                    trades.append(trade)

        # 2) Mark-to-market at this bar's close.
        invested = Decimal("0")
        held_value: dict[str, Decimal] = {}
        for s in symbols:
            if positions[s] != 0 and s in bars:
                mv = positions[s] * Decimal(str(bars[s]["close"]))
                held_value[s] = mv
                invested += mv
        equity = cash + invested
        equity_f = float(equity)
        exposure = float(invested / equity) if equity != 0 else 0.0

        equity_curve.append(
            EquityPoint(
                date=ts,
                equity=_round_money(equity_f),
                cash=_round_money(float(cash)),
                exposure=exposure,
            )
        )
        weight_row = np.zeros(len(symbols))
        for s, mv in held_value.items():
            w = float(mv / equity) if equity != 0 else 0.0
            weight_row[col_index[s]] = w
            position_snaps.append(
                PositionSnapshot(
                    date=ts,
                    symbol=s,
                    quantity=positions[s],
                    market_value=_round_money(float(mv)),
                    weight=w,
                )
            )
        port_returns.append(equity_f / prev_equity - 1.0 if prev_equity else 0.0)
        equity_values.append(equity_f)
        weights_matrix.append(weight_row)
        prev_equity = equity_f

        # 3) Decide target weights for the NEXT bar (held one bar -> no same-bar fill).
        pending = _session_weights(strategy, feed, sess, symbols, col_index)

    metrics = _metrics_from_returns(
        np.array(equity_values),
        np.array(port_returns),
        turnover(np.array(weights_matrix)),
    )
    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        positions=position_snaps,
        metrics=metrics,
        engine_used=EventDrivenEngine.name,
        config=config,
    )


@register_engine("event")
class EventDrivenEngine:
    """Bar-by-bar source-of-truth engine implementing ``Engine``.

    Orders decided at a session are held into the *next* session, so a strategy
    can never trade on its own signal bar — the same one-bar lag the vectorized
    engine applies via :func:`~openbb_backtest.engine.vectorized.lag_weights`.
    """

    name = "event"

    def run(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        feed: DataFeed,
        broker: Broker,
        fill_basis: FillBasis = "next_bar_open",
    ) -> BacktestResult:
        """Execute the event-driven backtest and return the canonical result.

        ``fill_basis`` selects the realistic broker ledger (``next_bar_open``,
        default) or the frictionless weight-based parity path
        (``close_on_decision``).
        """
        sessions = pd.DatetimeIndex(feed.sessions(config.start, config.end))
        if len(sessions) == 0:
            raise ValueError(
                "no trading sessions in "
                f"[{config.start}, {config.end}] for calendar {config.calendar!r}"
            )
        symbols = list(config.universe)
        if fill_basis == "close_on_decision":
            return _run_weight_based(strategy, config, feed, sessions, symbols)
        return _run_ledger(strategy, config, feed, broker, sessions, symbols)
