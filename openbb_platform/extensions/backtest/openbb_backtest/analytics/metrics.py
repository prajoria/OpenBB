"""Performance metric computation (component 07, §1).

:func:`compute_metrics` turns a normalized return :class:`~pandas.Series` (plus an
optional benchmark and the executed trades) into a
:class:`~openbb_backtest.models.PerformanceMetrics`. It is engine-agnostic: the
returns come from either engine's ``BacktestResult.equity_curve`` (via
:func:`~openbb_backtest.analytics._common.to_returns`), so the same numbers describe
the vectorized and event-driven runs.

Design (see ``docs/designs/backtest-design/07-analytics.md`` §1):

- **empyrical-reloaded** is the source for the return-based fields (cagr, sharpe,
  sortino, calmar, max_drawdown, volatility, var_95, cvar_95, beta, alpha). It is
  *lazy-imported* via :func:`~openbb_backtest.analytics._common.optional_import`, so
  importing this module never pulls a heavy dependency.
- When empyrical is absent we fall back to the vectorized engine's closed-form
  oracle :func:`~openbb_backtest.engine.vectorized._metrics_from_returns` (and a
  matching closed-form beta/alpha), so the layer still produces correct,
  engine-consistent numbers with zero heavy deps.
- **Annualization** always uses the passed ``sessions_per_year`` (the config
  calendar's sessions/year), never a hardcoded 252.
- ``win_rate`` / ``profit_factor`` are computed in-house from FIFO trade
  round-trip pairing with :class:`~decimal.Decimal` intermediates (money stays
  exact until the final float ratio).
- ``turnover`` is an annualized estimate from trade notional relative to the
  base (first-session) gross notional.
- **Privacy:** the input return series is run through
  :func:`~openbb_backtest.analytics._common.assert_normalized` first, so dollar
  levels / Decimal / non-finite series are rejected before anything is emitted.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from types import ModuleType
from typing import TYPE_CHECKING, SupportsFloat

import numpy as np
import pandas as pd

from openbb_backtest.analytics._common import assert_normalized, optional_import
from openbb_backtest.models import PerformanceMetrics

if TYPE_CHECKING:
    from openbb_backtest.models import Trade


def _empyrical() -> ModuleType | None:
    """Return the ``empyrical`` module, or ``None`` when it is not installed.

    Lazy + swallowing: analytics must degrade to the closed-form fallback rather
    than fail when the optional dependency is absent. Patched in unit tests to
    force the fallback path deterministically.
    """
    try:
        return optional_import("empyrical")
    except ImportError:
        return None


def compute_metrics(
    returns: pd.Series,
    benchmark: pd.Series | None,
    trades: list[Trade],
    sessions_per_year: int,
) -> PerformanceMetrics:
    """Compute :class:`PerformanceMetrics` from returns, a benchmark and trades.

    Parameters
    ----------
    returns
        Normalized per-session float returns (e.g. from
        :func:`~openbb_backtest.analytics._common.to_returns`). Validated by the
        privacy gate before use.
    benchmark
        Optional benchmark return series for ``beta``/``alpha``; ``None`` leaves
        both fields ``None``. Aligned to ``returns`` on the shared index.
    trades
        Executed trades, used in-house for ``win_rate``/``profit_factor`` (FIFO
        round-trip pairing) and ``turnover`` (notional based).
    sessions_per_year
        Trading sessions per year from the config calendar; drives all
        annualization (never a hardcoded 252).
    """
    assert_normalized(returns)
    spy = float(sessions_per_year)
    ep = _empyrical()

    if ep is not None:
        base = _metrics_via_empyrical(ep, returns, spy)
        beta, alpha = _beta_alpha_via_empyrical(ep, returns, benchmark, spy)
    else:
        base = _metrics_via_fallback(returns, spy)
        beta, alpha = _beta_alpha_fallback(returns, benchmark, spy)

    win_rate, profit_factor = _win_rate_profit_factor(trades)
    turnover = _turnover_from_trades(trades, returns, spy)

    return PerformanceMetrics(
        cagr=base["cagr"],
        sharpe=base["sharpe"],
        sortino=base["sortino"],
        calmar=base["calmar"],
        max_drawdown=base["max_drawdown"],
        volatility=base["volatility"],
        var_95=base["var_95"],
        cvar_95=base["cvar_95"],
        win_rate=win_rate,
        profit_factor=profit_factor,
        turnover=turnover,
        beta=beta,
        alpha=alpha,
    )


# --- return-based fields --------------------------------------------------


def _metrics_via_empyrical(ep: ModuleType, returns: pd.Series, spy: float) -> dict[str, float]:
    """Return-based fields from empyrical, annualized by ``spy`` sessions/year."""
    return {
        "cagr": float(ep.annual_return(returns, annualization=spy)),
        "sharpe": _finite(ep.sharpe_ratio(returns, annualization=spy)),
        "sortino": _finite(ep.sortino_ratio(returns, annualization=spy)),
        "calmar": _finite(ep.calmar_ratio(returns, annualization=spy)),
        "max_drawdown": _finite(ep.max_drawdown(returns)),
        "volatility": float(ep.annual_volatility(returns, annualization=spy)),
        "var_95": _finite(ep.value_at_risk(returns, cutoff=0.05)),
        "cvar_95": _finite(ep.conditional_value_at_risk(returns, cutoff=0.05)),
    }


def _metrics_via_fallback(returns: pd.Series, spy: float) -> dict[str, float]:
    """Return-based fields from the vectorized engine's closed-form oracle.

    Reuses the engine math directly (parameterized by ``spy``) so the analytics
    fallback and the engine agree to machine precision.
    """
    from openbb_backtest.engine.vectorized import (
        _metrics_from_returns,
        equity_curve_values,
    )

    port = returns.to_numpy(dtype=float)
    equity = equity_curve_values(1.0, port)
    m = _metrics_from_returns(
        equity, port, np.zeros_like(port), periods_per_year=spy
    )
    return {
        "cagr": m.cagr,
        "sharpe": m.sharpe,
        "sortino": m.sortino,
        "calmar": m.calmar,
        "max_drawdown": m.max_drawdown,
        "volatility": m.volatility,
        "var_95": m.var_95,
        "cvar_95": m.cvar_95,
    }


# --- beta / alpha ---------------------------------------------------------


def _aligned(returns: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Inner-join ``returns`` and ``benchmark`` on their shared index."""
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    return joined.iloc[:, 0], joined.iloc[:, 1]


def _beta_alpha_via_empyrical(
    ep: ModuleType, returns: pd.Series, benchmark: pd.Series | None, spy: float
) -> tuple[float | None, float | None]:
    if benchmark is None:
        return None, None
    r, b = _aligned(returns, benchmark)
    if r.empty:
        return None, None
    beta = _finite(ep.beta(r, b))
    alpha = _finite(ep.alpha(r, b, annualization=spy))
    return beta, alpha


def _beta_alpha_fallback(
    returns: pd.Series, benchmark: pd.Series | None, spy: float
) -> tuple[float | None, float | None]:
    """Closed-form beta (cov/var, ddof=1) and geometrically annualized alpha.

    Matches empyrical's definitions so the fallback and empyrical paths agree.
    """
    if benchmark is None:
        return None, None
    r, b = _aligned(returns, benchmark)
    rv = r.to_numpy(dtype=float)
    bv = b.to_numpy(dtype=float)
    if rv.size < 2:
        return None, None
    cov = np.cov(rv, bv, ddof=1)
    var_b = float(cov[1, 1])
    if var_b == 0.0:
        return None, None
    beta = float(cov[0, 1] / var_b)
    alpha_daily = float(np.mean(rv - beta * bv))
    alpha = float((1.0 + alpha_daily) ** spy - 1.0)
    return _finite(beta), _finite(alpha)


# --- in-house trade analytics ---------------------------------------------


def _win_rate_profit_factor(trades: list[Trade]) -> tuple[float, float]:
    """FIFO round-trip ``(win_rate, profit_factor)`` from executed trades.

    Opens (in the position's current direction) are queued; closes are matched
    FIFO against them, realizing a per-share PnL. Commissions on both legs are
    apportioned into the realized PnL so a fee-eroded "winner" is correctly a
    loss. All money math uses :class:`~decimal.Decimal`; only the final ratios
    are floats.
    """
    pnls = _round_trip_pnls(trades)
    if not pnls:
        return 0.0, 0.0
    wins = [p for p in pnls if p > 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum((-p for p in pnls if p < 0), Decimal("0"))
    win_rate = len(wins) / len(pnls)
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0
    return float(win_rate), profit_factor


def _round_trip_pnls(trades: list[Trade]) -> list[Decimal]:
    """Realized PnL per FIFO round-trip, per symbol, with Decimal money.

    A position is built up by trades in its current direction and closed by
    opposite trades; each close pairs FIFO against the open lots, realizing
    ``(close_price - open_price) * matched_qty`` for longs (sign-flipped for
    shorts). Commission per share on each leg is subtracted from the matched
    realized PnL.
    """
    pnls: list[Decimal] = []
    # Per-symbol queue of open lots: (signed_qty, price, commission_per_share).
    books: dict[str, deque[list[Decimal]]] = {}
    # Per-symbol net signed position, to know if a trade opens or closes.
    net: dict[str, Decimal] = {}

    for tr in trades:
        sym = tr.symbol
        signed = tr.quantity if tr.side == "buy" else -tr.quantity
        comm_ps = (tr.commission / tr.quantity) if tr.quantity != 0 else Decimal("0")
        book = books.setdefault(sym, deque())
        pos = net.get(sym, Decimal("0"))

        remaining = signed
        # Close against opposite-direction open lots first (FIFO).
        while remaining != 0 and book and (book[0][0] > 0) != (remaining > 0):
            lot = book[0]
            lot_qty, open_price, open_comm_ps = lot[0], lot[1], lot[2]
            match = min(abs(lot_qty), abs(remaining))
            direction = Decimal(1) if lot_qty > 0 else Decimal(-1)
            gross = (tr.price - open_price) * match * direction
            fees = (comm_ps + open_comm_ps) * match
            pnls.append(gross - fees)
            # Shrink / drop the matched lot.
            new_lot_qty = lot_qty - direction * match
            if new_lot_qty == 0:
                book.popleft()
            else:
                lot[0] = new_lot_qty
            remaining += direction * match  # remaining moves toward zero

        # Any leftover opens a new lot in the trade's direction.
        if remaining != 0:
            book.append([remaining, tr.price, comm_ps])
        net[sym] = pos + signed

    return pnls


def _turnover_from_trades(trades: list[Trade], returns: pd.Series, spy: float) -> float:
    """Annualized turnover estimated from trade notional.

    Turnover is total traded notional over the window, normalized by the base
    (first-session) gross notional, then annualized by ``spy / n_sessions``. With
    a single-session window this reduces to ``traded / base * spy / n``. Returns
    ``0.0`` when there are no trades or no sessions.
    """
    n = int(returns.shape[0])
    if not trades or n == 0:
        return 0.0
    notionals = [tr.quantity * tr.price for tr in trades]
    base = notionals[0]
    if base <= 0:
        return 0.0
    total = sum(notionals, Decimal("0"))
    fraction = float(total / base)
    return fraction * (spy / n)


def _finite(value: SupportsFloat) -> float:
    """Coerce ``value`` to float, mapping non-finite results to ``0.0``.

    empyrical (and the closed-form fallbacks) can yield ``nan``/``inf`` on
    degenerate inputs (e.g. zero-variance series); metrics are reported as plain
    finite floats, so those collapse to ``0.0``.
    """
    out = float(value)
    return out if np.isfinite(out) else 0.0
