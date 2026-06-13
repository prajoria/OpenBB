"""Reconciliation gate: event-driven vs vectorized engine (component 05, §3).

The key exit criterion for trusting the fast vectorized engine: run the *same*
strategy/config through :class:`VectorizedEngine` and :class:`EventDrivenEngine`
and assert their equity curves agree within ``reconcile_tolerance`` (1e-6).

Parity is checked against the event engine's ``close_on_decision`` fill basis,
which uses the identical close-to-close, one-bar-lag convention as the
vectorized matrix. The realistic ``next_bar_open`` ledger fills at the next
bar's open and is therefore one bar offset from the close-to-close matrix — a
documented fill-basis nuance, not a look-ahead leak.

A look-ahead-leaking stub engine is included as a negative control: it MUST
fail the gate, which is what gives the gate its teeth.

See ``docs/designs/backtest-design/04-vectorized-engine.md`` §3 and
``05-event-driven-engine.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from openbb_backtest.models import CommissionModel, SlippageModel

# ---- Shared fixtures (open==close so fill-basis nuance is isolated) ------

_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    """Two symbols, five sessions; AAA rises 1%/day, BBB falls 1%/day.

    open==high==low==close on every bar, so the only timing difference between
    engines is the fill basis (isolated, not an intraday artifact).
    """
    rows = []
    for sym, base, step in (("AAA", 100.0, 1.01), ("BBB", 100.0, 0.99)):
        price = base
        for sess in _SESSIONS:
            rows.append(
                {
                    "symbol": sym,
                    "session": sess,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1_000_000.0,
                    "adj_factor": 1.0,
                }
            )
            price *= step
    return pd.DataFrame(rows)


class _MatrixFeed:
    """Minimal ``DataFeed`` over an in-memory OHLCV frame (no look-ahead)."""

    def __init__(self, ohlcv: pd.DataFrame) -> None:
        self._ohlcv = ohlcv

    def history(self, symbols, end, lookback):
        end = pd.Timestamp(end)
        frame = self._ohlcv
        mask = frame["symbol"].isin(symbols) & (frame["session"] <= end)
        return (
            frame.loc[mask]
            .sort_values("session")
            .groupby("symbol", group_keys=False)
            .tail(lookback)
            .reset_index(drop=True)
        )

    def sessions(self, start, end):
        s = self._ohlcv["session"]
        return pd.DatetimeIndex(
            sorted(s[(s >= pd.Timestamp(start)) & (s <= pd.Timestamp(end))].unique())
        )


class _SpikeStrategy:
    """All-in AAA at exactly one session, flat otherwise.

    A timing-sensitive strategy: with the mandatory one-bar lag the spike earns
    the *next* day; a look-ahead-leaking engine would book it the *same* day, so
    this strategy makes the negative control diverge sharply.
    """

    id = "spike"

    def __init__(self, spike: pd.Timestamp) -> None:
        self._spike = pd.Timestamp(spike)

    def generate(self, data) -> pd.DataFrame:
        on = pd.Timestamp(data.now) == self._spike
        return pd.DataFrame(
            {"weight": [1.0 if on else 0.0, 0.0]}, index=["AAA", "BBB"]
        )


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="spike",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="event",
        initial_cash=Decimal("100000"),
        commission=CommissionModel(),
        slippage=SlippageModel(),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _broker(config):
    from openbb_backtest.engine.execution import RealisticBroker

    return RealisticBroker(config.commission, config.slippage)


class _CloseBasisEventEngine:
    """Adapter running :class:`EventDrivenEngine` on the ``close_on_decision`` basis.

    Keeps ``reconcile`` engine-agnostic (it calls ``run(strategy, config, feed,
    broker)`` with no fill-basis kwarg) while exposing the close-to-close parity
    path that lines up bar-for-bar with the vectorized matrix.
    """

    name = "event"

    def run(self, strategy, config, feed, broker):
        from openbb_backtest.engine.event_driven import EventDrivenEngine

        return EventDrivenEngine().run(
            strategy, config, feed, broker, fill_basis="close_on_decision"
        )


class _LookAheadLeakEngine:
    """NEGATIVE CONTROL: books each session's weight against the SAME session.

    Drops the mandatory one-bar lag, so a signal fills on its own bar — a
    textbook look-ahead leak. The reconciliation gate MUST catch this.
    """

    name = "leak"

    def run(self, strategy, config, feed, broker):
        from openbb_backtest.engine.vectorized import (
            _as_utc,
            _build_weights,
            _metrics_from_returns,
            _prepare,
            _round_money,
            equity_curve_values,
            portfolio_returns,
            turnover,
        )
        from openbb_backtest.models import BacktestResult, EquityPoint

        market = _prepare(config, feed)
        weights = _build_weights(strategy, feed, market.sessions, market.symbols)
        # NO lag_weights: apply the same-bar weight to the same-bar return.
        costs = np.zeros(len(market.sessions))
        port = portfolio_returns(weights, market.returns, costs)
        equity = equity_curve_values(float(config.initial_cash), port)
        net = weights.sum(axis=1)
        curve = [
            EquityPoint(
                date=_as_utc(s),
                equity=_round_money(equity[i]),
                cash=_round_money(equity[i] * (1.0 - net[i])),
                exposure=float(net[i]),
            )
            for i, s in enumerate(market.sessions)
        ]
        return BacktestResult(
            equity_curve=curve,
            trades=[],
            positions=[],
            metrics=_metrics_from_returns(equity, port, turnover(weights)),
            engine_used=self.name,
            config=config,
        )


# ---- Frictionless parity -------------------------------------------------


def test_reconcile_frictionless_passes_within_tolerance():
    from openbb_backtest.engine.reconcile import reconcile
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    feed = _MatrixFeed(_ohlcv_frame())
    report = reconcile(
        VectorizedEngine(),
        _CloseBasisEventEngine(),
        _SpikeStrategy(_SESSIONS[1]),
        cfg,
        feed,
        _broker(cfg),
    )
    assert report.passed is True
    assert report.max_divergence <= 1e-6


def test_reconcile_frictionless_strict_does_not_raise():
    from openbb_backtest.engine.reconcile import reconcile
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    feed = _MatrixFeed(_ohlcv_frame())
    # Strict mode raises ReconciliationError on divergence; a passing run must
    # return a report quietly.
    report = reconcile(
        VectorizedEngine(),
        _CloseBasisEventEngine(),
        _SpikeStrategy(_SESSIONS[1]),
        cfg,
        feed,
        _broker(cfg),
        strict=True,
    )
    assert report.passed is True


# ---- Negative control: a look-ahead leak must FAIL the gate --------------


def test_reconcile_detects_look_ahead_leak():
    from openbb_backtest.engine.reconcile import reconcile
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    feed = _MatrixFeed(_ohlcv_frame())
    report = reconcile(
        VectorizedEngine(),
        _LookAheadLeakEngine(),
        _SpikeStrategy(_SESSIONS[1]),
        cfg,
        feed,
        _broker(cfg),
    )
    # The leak books the spike a day early, so the curves diverge well beyond 1e-6.
    assert report.passed is False
    assert report.max_divergence > 1e-6


def test_reconcile_strict_raises_on_look_ahead_leak():
    from openbb_backtest.engine.reconcile import ReconciliationError, reconcile
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    feed = _MatrixFeed(_ohlcv_frame())
    with pytest.raises(ReconciliationError, match="diverged"):
        reconcile(
            VectorizedEngine(),
            _LookAheadLeakEngine(),
            _SpikeStrategy(_SESSIONS[1]),
            cfg,
            feed,
            _broker(cfg),
            strict=True,
        )


# ---- Cost parity: percent commission + fixed_bps slippage ----------------


def test_reconcile_cost_parity_within_tolerance():
    from openbb_backtest.engine.reconcile import reconcile
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config(
        commission=CommissionModel(kind="percent", value=Decimal("0.0005")),
        slippage=SlippageModel(kind="fixed_bps", value=Decimal("10")),
    )
    feed = _MatrixFeed(_ohlcv_frame())
    report = reconcile(
        VectorizedEngine(),
        _CloseBasisEventEngine(),
        _SpikeStrategy(_SESSIONS[1]),
        cfg,
        feed,
        _broker(cfg),
        strict=True,
    )
    # Both engines express fixed_bps slippage + percent commission as the same
    # flat turnover rate, so the cost drag matches to the cent.
    assert report.passed is True
    assert report.max_divergence <= 1e-6
