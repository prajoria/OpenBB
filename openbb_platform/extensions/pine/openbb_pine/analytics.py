"""Pine strategy result → openbb-backtest ``BacktestResult`` shape adapter (#589).

Sits between the Pine strategy runtime and ``openbb-backtest``'s analytics
layer. Sibling of #590's ``runtime.backtest_bridge.maybe_export_to_backtest``,
which is what actually wires this adapter into the strategies-router
happy path.

Contract
--------

:func:`ingest_pine_strategy` accepts a strategy :class:`OBBject` and
returns an :class:`openbb_backtest.models.BacktestResult`. The adapter
does not mutate the input's ``results`` field but appends a lossy-fields
warning to ``result.extra["warnings"]`` when the ``EquityPoint``
translation had to fabricate values (see §Fabricated fields below).

Translation map
---------------

+----------------------------------+----------------------------------+
| Pine wire shape                  | openbb-backtest shape            |
+==================================+==================================+
| ``TradeSummary`` (round-trip)    | Two ``Trade`` rows (fan-out):    |
| ``direction="long"``             |   entry side=buy, exit side=sell |
| ``direction="short"``            |   entry side=sell, exit side=buy |
+----------------------------------+----------------------------------+
| ``TradeSummary.qty`` (float,     | ``Trade.quantity`` (Decimal,     |
| absolute)                        | absolute — direction in ``side``)|
+----------------------------------+----------------------------------+
| ``TradeSummary.entry_time`` /    | Two ``Trade.timestamp``          |
| ``.exit_time`` (pd.Timestamp)    | (datetime — pandas → py conv)    |
+----------------------------------+----------------------------------+
| ``TradeSummary.entry_price`` /   | ``Trade.price`` on the two rows  |
| ``.exit_price``                  |                                  |
+----------------------------------+----------------------------------+
| ``TradeSummary.commission``      | Split 50/50 between entry + exit |
| (total across both legs)         | ``Trade.commission``             |
+----------------------------------+----------------------------------+
| ``equity_curve[i]`` dict         | ``EquityPoint[i]``:              |
|   ``{"bar_index", "equity",      |   ``date`` = fabricated          |
|      "drawdown"}``               |   ``equity`` = pass-through      |
|                                  |   ``cash`` = fabricated (=equity)|
|                                  |   ``exposure`` = fabricated (0.0)|
+----------------------------------+----------------------------------+
| Pine has no ``positions`` per    | ``positions=[]`` — deferred to a |
| bar                              | future Pine-runtime issue        |
+----------------------------------+----------------------------------+
| Metrics                          | Delegated to                     |
|                                  | ``openbb_backtest.analytics``    |
|                                  | ``.compute_metrics``             |
+----------------------------------+----------------------------------+

Fabricated fields (documented lossy)
------------------------------------

Pine's per-bar equity snapshot only carries ``bar_index``, ``equity``,
and ``drawdown``. openbb-backtest's :class:`EquityPoint` needs
``date`` + ``cash`` + ``exposure``. This adapter fabricates:

* ``date`` = ``_FABRICATED_EPOCH + timedelta(days=bar_index)`` — a
  deterministic monotonic datetime that lets downstream returns
  computations run without zero-timedelta division. **The absolute
  date is arbitrary**; only the deltas between adjacent bars carry
  meaning.
* ``cash`` = ``equity`` — assumes the strategy was flat at each
  snapshot, which is wrong for intra-trade bars. Downstream metrics
  that use ``cash`` are unreliable until the Pine runtime records
  real cash.
* ``exposure`` = ``0.0`` — constant. Same lossy story as ``cash``.

The adapter appends a single warning per call to
``result.extra["warnings"]`` naming all three fabricated fields so a
caller reading the warnings list can see the lossy translation without
inspecting individual :class:`EquityPoint` values. Follow-up work
(tracked as a separate Pine-runtime issue) will teach ``executor_shell``
to stamp real ``time`` / ``cash`` / ``exposure`` on each snapshot; once
that lands, this adapter's fabrication path can be deleted.
"""

# pylint: disable=import-outside-toplevel
# ^ Every `openbb_backtest` and `pandas` import in this module is a
# deliberate deferred import — analytics.py is only reachable via
# runtime.backtest_bridge.maybe_export_to_backtest(), which itself
# guards on openbb_backtest being installed. Moving these to top-of-
# module would defeat the soft-dep contract and make openbb_backtest a
# hard dependency at import time. Same reason each function that
# touches openbb_backtest keeps its `from openbb_backtest... import ...`
# inside the function body.

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover -- typing only
    from openbb_backtest.models import BacktestResult
    from openbb_core.app.model.obbject import OBBject


# Deterministic anchor for fabricated EquityPoint.date values. Chosen
# arbitrarily but stably so two runs of the same strategy produce the
# same synthetic dates. UTC to sidestep DST reasoning downstream.
_FABRICATED_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)

_LOSSY_EQUITY_WARNING = (
    "openbb-backtest EquityPoint fields `date`, `cash`, `exposure` were "
    "fabricated by the openbb_pine.analytics adapter — Pine's per-bar "
    "equity snapshot only carries bar_index / equity / drawdown. Metrics "
    "computed from these EquityPoints (esp. anything reading cash or "
    "exposure) are approximate. See openbb_pine.analytics module docstring "
    "for the fabrication scheme."
)


def _decimal(value: Any) -> Decimal:
    """Convert to :class:`Decimal` losslessly-enough for financial data.

    ``float → Decimal`` via ``str`` avoids the float-binary noise that
    ``Decimal(float_value)`` would carry (``Decimal(0.1)`` becomes
    ``0.1000000000000000055511151231257827021181583404541015625``).
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _summary_to_trade_rows(
    summary: Any,
    symbol: str,
) -> list[Any]:
    """Fan out one :class:`TradeSummary` to two ``Trade`` rows.

    Long round-trip: entry=buy, exit=sell.
    Short round-trip: entry=sell, exit=buy.

    ``commission`` (Pine's total across both legs) is split 50/50 across
    the two Trade rows so downstream cost aggregation still totals to
    the original commission without double-counting.
    """
    from openbb_backtest.models import Trade

    if summary.direction == "long":
        entry_side, exit_side = "buy", "sell"
    elif summary.direction == "short":
        entry_side, exit_side = "sell", "buy"
    else:  # defensive — the dataclass Literal already enforces this
        raise ValueError(
            f"unexpected TradeSummary.direction={summary.direction!r}; "
            "expected 'long' or 'short'"
        )

    quantity = _decimal(abs(summary.qty))
    half_commission = _decimal(summary.commission) / Decimal(2)

    entry_row = Trade(
        timestamp=(
            summary.entry_time.to_pydatetime()
            if hasattr(summary.entry_time, "to_pydatetime")
            else summary.entry_time
        ),
        symbol=symbol,
        side=entry_side,
        quantity=quantity,
        price=_decimal(summary.entry_price),
        commission=half_commission,
        slippage=Decimal("0"),
    )
    exit_row = Trade(
        timestamp=(
            summary.exit_time.to_pydatetime()
            if hasattr(summary.exit_time, "to_pydatetime")
            else summary.exit_time
        ),
        symbol=symbol,
        side=exit_side,
        quantity=quantity,
        price=_decimal(summary.exit_price),
        commission=half_commission,
        slippage=Decimal("0"),
    )
    return [entry_row, exit_row]


def _equity_curve_to_points(
    equity_curve: list[dict[str, Any]],
) -> list[Any]:
    """Translate Pine's per-bar equity dicts to :class:`EquityPoint` rows.

    Fabricates ``date`` (from bar_index), ``cash`` (=equity), and
    ``exposure`` (=0.0). See module docstring for the lossy-translation
    rationale.
    """
    from openbb_backtest.models import EquityPoint

    points: list[Any] = []
    for snap in equity_curve:
        bar_index = int(snap["bar_index"])
        equity = _decimal(snap["equity"])
        points.append(
            EquityPoint(
                date=_FABRICATED_EPOCH + timedelta(days=bar_index),
                equity=equity,
                cash=equity,
                exposure=0.0,
            )
        )
    return points


def _compute_metrics_from_points(
    points: list[Any],
    trades: list[Any],
) -> Any:
    """Delegate to ``openbb_backtest.analytics.compute_metrics``.

    Converts the fabricated :class:`EquityPoint` series into the
    normalized-returns ``pd.Series`` that ``compute_metrics`` expects.
    Uses daily sessions_per_year (252) since our fabricated dates step
    one day per bar.
    """
    import pandas as pd
    from openbb_backtest.analytics.metrics import compute_metrics

    if not points:
        # No equity data → produce a zero-return single-point series so
        # the metrics call has something to consume without dividing by
        # zero. Downstream metrics will be all zeros/NaN — a caller
        # reading the warnings list already knows the translation was
        # lossy.
        equity_series = pd.Series(
            [1.0],
            index=pd.DatetimeIndex([_FABRICATED_EPOCH]),
        )
    else:
        equity_series = pd.Series(
            [float(pt.equity) for pt in points],
            index=pd.DatetimeIndex([pt.date for pt in points]),
        )

    # to_returns → pct_change with first row dropped; if the equity has
    # <2 points there's no return to compute.
    returns = equity_series.pct_change().dropna()
    if returns.empty:
        # Same edge case: single equity point → no returns. Give
        # compute_metrics a single zero-return so it doesn't divide-by-
        # zero on an empty series.
        returns = pd.Series(
            [0.0],
            index=pd.DatetimeIndex([equity_series.index[0] + pd.Timedelta(days=1)]),
        )

    return compute_metrics(
        returns=returns,
        benchmark=None,
        trades=trades,
        sessions_per_year=252,
    )


def ingest_pine_strategy(strategy_result: OBBject) -> BacktestResult:
    """Translate a Pine strategy result into openbb-backtest's shape.

    Called by :func:`openbb_pine.runtime.backtest_bridge.maybe_export_to_backtest`
    on the happy path (openbb-backtest installed + result is a strategy).
    Direct callers (notebooks, tests, adapters) can invoke this too as
    long as ``strategy_result.extra['script_type'] == 'strategy'`` — a
    :class:`TypeError` fires immediately otherwise.

    Side effect: appends the fabricated-fields warning to
    ``strategy_result.extra['warnings']`` if the equity_curve was
    non-empty (see module docstring §Fabricated fields).

    Returns
    -------
    openbb_backtest.models.BacktestResult
        Fully-populated with ``trades``, ``equity_curve``, ``metrics``,
        an empty ``positions`` list (deferred), a synthesized
        ``BacktestConfig`` echo, and ``engine_used="pine-adapter"``.
    """
    from openbb_backtest.models import BacktestConfig, BacktestResult

    extra = getattr(strategy_result, "extra", None)
    if not isinstance(extra, dict):
        raise TypeError(
            "ingest_pine_strategy: strategy_result.extra must be a dict; "
            f"got {type(extra).__name__}"
        )
    if extra.get("script_type") != "strategy":
        raise TypeError(
            "ingest_pine_strategy: only accepts strategy results "
            f"(script_type='strategy'); got script_type="
            f"{extra.get('script_type')!r}"
        )

    symbol = str(extra.get("symbol", "UNKNOWN"))
    orders: list[Any] = list(extra.get("orders", []) or [])
    equity_curve: list[dict[str, Any]] = list(extra.get("equity_curve", []) or [])
    stats = extra.get("stats", {}) or {}
    initial_capital = float(stats.get("initial_capital", 100_000.0))

    # Fan out round-trips → Trade rows, then sort chronologically so
    # downstream FIFO metrics pairing sees the right order.
    trades: list[Any] = []
    for summary in orders:
        trades.extend(_summary_to_trade_rows(summary, symbol=symbol))
    trades.sort(key=lambda t: t.timestamp)

    equity_points = _equity_curve_to_points(equity_curve)

    if equity_points:
        # Only warn when we actually fabricated fields.
        extra.setdefault("warnings", []).append(_LOSSY_EQUITY_WARNING)

    metrics = _compute_metrics_from_points(equity_points, trades)

    # Synthesize a minimal BacktestConfig so BacktestResult.config is
    # populated. universe=[symbol], initial_cash from stats, dates
    # derived from the first/last fabricated equity date (or a 1-day
    # window if equity_curve was empty).
    if equity_points:
        start = equity_points[0].date.date()
        end = equity_points[-1].date.date()
        if end <= start:
            end = start + timedelta(days=1)
    else:
        start = _FABRICATED_EPOCH.date()
        end = start + timedelta(days=1)

    config = BacktestConfig(
        strategy="pine-adapter",
        universe=[symbol],
        start=start,
        end=end,
        initial_cash=_decimal(initial_capital),
    )

    return BacktestResult(
        equity_curve=equity_points,
        trades=trades,
        positions=[],  # deferred — Pine doesn't record per-bar positions
        metrics=metrics,
        engine_used="pine-adapter",
        config=config,
    )


__all__ = ["ingest_pine_strategy"]
