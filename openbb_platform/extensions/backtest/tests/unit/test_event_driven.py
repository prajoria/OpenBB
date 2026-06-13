"""Unit tests for the event-driven source-of-truth engine (component 05).

Covers the bar-by-bar session loop, the point-in-time ``MarketData`` view
(look-ahead-free by construction), the mandatory next-bar hold (a weight
requested at session ``t`` earns nothing until ``t+1``), and the frictionless
first-cut equity curve that must reconcile with the vectorized engine.

See ``docs/designs/backtest-design/05-event-driven-engine.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from openbb_backtest.models import CommissionModel, SlippageModel

# ---- Test fixtures: in-memory feed + deterministic strategies -----------

_SESSIONS = pd.to_datetime(
    ["2021-01-04", "2021-01-05", "2021-01-06", "2021-01-07", "2021-01-08"]
)


def _ohlcv_frame() -> pd.DataFrame:
    """Two symbols, five sessions; AAA rises 1%/day, BBB falls 1%/day."""
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


class _EqualWeightStrategy:
    """Stateless long-only equal-weight allocator across the universe."""

    id = "equal_weight"

    def generate(self, data) -> pd.DataFrame:
        win = data.window(["AAA", "BBB"], lookback=1)
        symbols = sorted(win["symbol"].unique())
        w = 1.0 / len(symbols)
        return pd.DataFrame({"weight": [w] * len(symbols)}, index=symbols)


class _SpikeAtSessionStrategy:
    """Goes all-in on AAA at exactly one session, flat otherwise.

    Used to prove the engine's next-bar hold: the weight requested *at* the
    spike session must earn nothing on that session and only take effect next.
    """

    id = "spike"

    def __init__(self, spike: pd.Timestamp) -> None:
        self._spike = pd.Timestamp(spike)

    def generate(self, data) -> pd.DataFrame:
        on = pd.Timestamp(data.now) == self._spike
        return pd.DataFrame(
            {"weight": [1.0 if on else 0.0, 0.0]}, index=["AAA", "BBB"]
        )


class _LookAheadAssertingStrategy:
    """Asserts the PIT view never exposes a bar beyond the current session."""

    id = "look_ahead_assert"

    def __init__(self) -> None:
        self.checked = 0

    def generate(self, data) -> pd.DataFrame:
        win = data.window(["AAA", "BBB"], lookback=99)
        if not win.empty:
            assert win["session"].max() <= pd.Timestamp(data.now)
        self.checked += 1
        return pd.DataFrame({"weight": [0.5, 0.5]}, index=["AAA", "BBB"])


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="equal_weight",
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


# ---- EventDrivenEngine identity & registration --------------------------


def test_event_engine_is_an_engine():
    from openbb_backtest.engine.event_driven import EventDrivenEngine
    from openbb_backtest.interfaces import Engine

    assert isinstance(EventDrivenEngine(), Engine)
    assert EventDrivenEngine().name == "event"


def test_event_engine_is_registered_for_discovery():
    import openbb_backtest.engine.event_driven  # noqa: F401
    from openbb_backtest.engine.event_driven import EventDrivenEngine
    from openbb_backtest.registry import get_engine

    assert get_engine("event") is EventDrivenEngine


# ---- EventDrivenEngine.run ----------------------------------------------


def test_run_produces_result_with_equity_curve_for_every_session():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config()
    res = EventDrivenEngine().run(
        _EqualWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    assert res.engine_used == "event"
    assert len(res.equity_curve) == len(_SESSIONS)
    # First point is the untouched starting cash (nothing held on bar 0).
    assert res.equity_curve[0].equity == pytest.approx(Decimal("100000"))


def test_run_money_fields_are_decimal():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config()
    res = EventDrivenEngine().run(
        _EqualWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    pt = res.equity_curve[-1]
    assert isinstance(pt.equity, Decimal)
    assert isinstance(pt.cash, Decimal)


def test_run_enforces_next_bar_hold_no_same_bar_fill():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config(strategy="spike")
    spike = _SESSIONS[1]  # request all-in AAA at session index 1
    res = EventDrivenEngine().run(
        _SpikeAtSessionStrategy(spike),
        cfg,
        _MatrixFeed(_ohlcv_frame()),
        _broker(cfg),
        fill_basis="close_on_decision",
    )
    eq = [float(p.equity) for p in res.equity_curve]
    # The weight is requested AT session 1, so it must NOT capture the move into
    # session 1: equity is unchanged through session 1.
    assert eq[1] == pytest.approx(eq[0])
    # It only takes effect on session 2 (AAA's 1->2 return, +1%).
    assert eq[2] == pytest.approx(eq[1] * 1.01, rel=1e-9)
    # After the single spike day the book is flat again: no further change.
    assert eq[3] == pytest.approx(eq[2])


def test_run_marketdata_view_is_look_ahead_free():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config(strategy="look_ahead_assert")
    strat = _LookAheadAssertingStrategy()
    EventDrivenEngine().run(strat, cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg))
    # The strategy is invoked once per session and its in-strategy assertion
    # (no bar beyond ``now``) held every time.
    assert strat.checked == len(_SESSIONS)


def test_run_frictionless_curve_matches_vectorized_engine():
    from openbb_backtest.engine.event_driven import EventDrivenEngine
    from openbb_backtest.engine.vectorized import VectorizedEngine

    cfg = _config()
    feed = _MatrixFeed(_ohlcv_frame())
    vec = VectorizedEngine().run(_EqualWeightStrategy(), cfg, feed, _broker(cfg))
    evt = EventDrivenEngine().run(
        _EqualWeightStrategy(),
        cfg,
        feed,
        _broker(cfg),
        fill_basis="close_on_decision",
    )
    # Shared lag + frictionless accounting => the two engines agree exactly.
    vec_eq = [float(p.equity) for p in vec.equity_curve]
    evt_eq = [float(p.equity) for p in evt.equity_curve]
    assert evt_eq == pytest.approx(vec_eq, rel=1e-9)


class _EmptySessionsFeed:
    """A feed whose calendar yields no sessions in the requested range."""

    def history(self, symbols, end, lookback):
        return pd.DataFrame(
            columns=["symbol", "session", "open", "high", "low", "close", "volume"]
        )

    def sessions(self, start, end):
        return pd.DatetimeIndex([])


def test_run_raises_clear_error_on_empty_session_window():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config()
    with pytest.raises(ValueError, match="no trading sessions"):
        EventDrivenEngine().run(
            _EqualWeightStrategy(), cfg, _EmptySessionsFeed(), _broker(cfg)
        )


# ---- C05.2: broker-driven Decimal ledger -> canonical BacktestResult ----

_TRIPLE = pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"])


def _triple_frame() -> pd.DataFrame:
    """Single symbol AAA, flat intraday (open==close), prices 10 -> 20 -> 25."""
    rows = []
    for sess, px in zip(_TRIPLE, (10.0, 20.0, 25.0)):
        rows.append(
            {
                "symbol": "AAA",
                "session": sess,
                "open": px,
                "high": px,
                "low": px,
                "close": px,
                "volume": 1_000_000.0,
                "adj_factor": 1.0,
            }
        )
    return pd.DataFrame(rows)


class _AllInAAAStrategy:
    """Targets 100% AAA every session (rebalances as price moves)."""

    id = "all_in_aaa"

    def generate(self, data) -> pd.DataFrame:
        return pd.DataFrame({"weight": [1.0]}, index=["AAA"])


def _triple_config(**kw):
    return _config(
        strategy="all_in_aaa",
        universe=["AAA"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 6),
        **kw,
    )


def _last_position(res, symbol):
    last_date = res.equity_curve[-1].date
    matches = [
        p for p in res.positions if p.date == last_date and p.symbol == symbol
    ]
    return matches[-1] if matches else None


def test_run_buy_and_hold_reproduces_hand_computed_ledger():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _triple_config()
    res = EventDrivenEngine().run(
        _AllInAAAStrategy(), cfg, _MatrixFeed(_triple_frame()), _broker(cfg)
    )
    # Hand-computed (next-bar-open, frictionless, fill-time sizing):
    #   S0 close 10: equity 100000, decide AAA=1.0 -> order fills at S1 open
    #   S1 open 20:  size 1.0 * 100000 / 20 = 5000 sh; buy 5000 @ 20 -> cash 0;
    #                mark@20 -> equity 100000. Re-decide AAA=1.0.
    #   S2 open 25:  target 1.0 * (5000*25) / 25 = 5000 sh == held -> NO trade
    #                (a 100%-weight single name is self-financing); mark@25 ->
    #                equity 5000*25 = 125000, cash 0.
    # => exactly one fill, ending fully invested.
    assert res.equity_curve[-1].equity == Decimal("125000.00")
    assert res.equity_curve[-1].cash == Decimal("0.00")
    assert len(res.trades) == 1
    pos = _last_position(res, "AAA")
    assert pos is not None
    assert pos.quantity == pytest.approx(Decimal("5000"))
    assert pos.market_value == Decimal("125000.00")


def test_run_trades_fill_at_next_bar_not_decision_bar():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _triple_config()
    res = EventDrivenEngine().run(
        _AllInAAAStrategy(), cfg, _MatrixFeed(_triple_frame()), _broker(cfg)
    )
    assert res.trades, "expected the engine to emit fills"
    # The decision is made at S0 close; the first fill must land at S1 (t+1),
    # never on the S0 decision bar -> structurally look-ahead-free.
    first = min(res.trades, key=lambda t: t.timestamp)
    assert pd.Timestamp(first.timestamp).date() == date(2021, 1, 5)
    assert all(pd.Timestamp(t.timestamp).date() != date(2021, 1, 4) for t in res.trades)


def test_run_trade_costs_equal_broker_output_and_reduce_equity():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    feed = _MatrixFeed(_triple_frame())
    free_cfg = _triple_config()
    free = EventDrivenEngine().run(
        _AllInAAAStrategy(), free_cfg, feed, _broker(free_cfg)
    )

    costly_cfg = _triple_config(
        commission=CommissionModel(kind="percent", value=Decimal("0.001"))
    )
    broker = _broker(costly_cfg)
    costly = EventDrivenEngine().run(_AllInAAAStrategy(), costly_cfg, feed, broker)

    assert costly.trades
    # Each Trade carries exactly the broker's commission for its (qty, price).
    for tr in costly.trades:
        assert tr.commission == broker.commission(tr.quantity, tr.price)
        assert tr.commission > 0
    # Commission must erode equity relative to the frictionless run.
    assert float(costly.equity_curve[-1].equity) < float(free.equity_curve[-1].equity)


def test_run_rejects_constrained_orders_without_filling():
    from openbb_backtest.engine.event_driven import EventDrivenEngine
    from openbb_backtest.engine.execution import Constraints, RealisticBroker

    cfg = _triple_config()
    broker = RealisticBroker(
        cfg.commission, cfg.slippage, constraints=Constraints(restricted={"AAA"})
    )
    res = EventDrivenEngine().run(
        _AllInAAAStrategy(), cfg, _MatrixFeed(_triple_frame()), broker
    )
    # The only tradable symbol is restricted: nothing fills, equity stays flat
    # at the initial cash, and the broker records the rejections (no silent drop).
    assert res.trades == []
    assert broker.rejected_orders > 0
    assert res.equity_curve[-1].equity == Decimal("100000.00")


def test_run_position_weights_sum_to_exposure():
    from openbb_backtest.engine.event_driven import EventDrivenEngine

    cfg = _config()  # equal-weight AAA/BBB over five sessions
    res = EventDrivenEngine().run(
        _EqualWeightStrategy(), cfg, _MatrixFeed(_ohlcv_frame()), _broker(cfg)
    )
    # On a session with holdings, the per-symbol weights reconcile to exposure.
    point = res.equity_curve[-1]
    weights = [p.weight for p in res.positions if p.date == point.date]
    assert weights, "expected held positions on the final session"
    assert sum(weights) == pytest.approx(point.exposure, rel=1e-9)

