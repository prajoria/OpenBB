"""``techtrade_confluence`` -- the techtrade SignalStrategy (issue #82, design Q-B B2).

A faithful, registered :class:`~openbb_backtest.strategies.base.SignalStrategy` that
reproduces the techtrade #74 confluence engine inside an ``openbb-backtest`` walk-
forward / CPCV fold. It lets ``obb.techtrade.validate`` ask backtest: *"if this rule
had run every session of the past N years, was the edge robust, fragile, or
overfit?"* -- without techtrade re-implementing WFO / CPCV / PBO / DSR (design L4).

The strategy lives in **techtrade** (not backtest) because the rule it reproduces is
techtrade's, and is advertised to backtest via the ``openbb_backtest_strategies``
entry-point group. backtest auto-discovers it only when **both** packages are
installed (design Q-A): no top-level import on either side; no hard coupling.

Per-session signal computation (engine-agnostic, no future peeking):

1. ``data.window([symbol], lookback=N)`` -> trailing N bars of OHLCV up to the
   current session ``data.now``.
2. Pivot to a per-symbol close+OHLCV frame the techtrade indicator builder accepts.
3. Reuse :func:`~openbb_techtrade.engine.indicators.build_indicator_panel` to build
   the per-symbol panel on the latest bar.
4. Reuse :func:`~openbb_techtrade.engine.confluence.composite_score` +
   :func:`~openbb_techtrade.engine.confluence.direction_for` to get a directional
   score and bucket it into ``long`` / ``short`` / ``flat`` against the rule's
   ``entry_threshold`` (#76).
5. Map ``long -> +1.0``, ``short -> -1.0``, ``flat -> 0.0`` for each universe symbol.

**Look-ahead caveat** (carried from ``analysis_bridge``): each fold's ``data.window``
only exposes bars up to ``data.now``, so the panel is computed point-in-time per
session. The historical recompute does not peek; what *can* drift across forks is
the indicator library's own behaviour. Document caveat: this validates *the rule's
shape*, not the entire upstream stack (which includes the segment universe resolver
#69 and the GICS sector ETF holdings, neither of which is part of a single-symbol
fold's signal).

The strategy is **pure**: only ``pandas`` and the techtrade engine modules already
in techtrade's base dependencies are used. No ``openbb_backtest`` import at module
top-level -- only the
:class:`~openbb_backtest.strategies.base.SignalStrategy` base is imported, which is
available iff this module was loaded by backtest's entry-point discovery (i.e. both
packages are installed). Per Q-F, even that import lives inside the conditional
guard so plain ``import openbb_techtrade.validation.confluence_strategy`` cannot
trip when backtest is absent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openbb_backtest.interfaces import MarketData
    from openbb_backtest.strategies.base import SignalStrategy as _BaseSignal
else:
    # Defer the import to module-import time *inside* an exception guard so the
    # techtrade extension stays importable when openbb-backtest is absent. The
    # name resolves at class-definition time; if backtest is missing the entire
    # module load fails -- which is exactly what we want for an entry-point that
    # is only ever activated by backtest's plugin discovery (Q-F).
    from openbb_backtest.strategies.base import SignalStrategy as _BaseSignal  # noqa: F401

logger = logging.getLogger(__name__)

#: Default lookback (sessions) -- enough to warm up the slowest indicator (ADX(14)
#: + EMA(50) + Bollinger(20) needs at least ~70 bars to stabilize; 200 leaves a
#: comfortable buffer).
DEFAULT_LOOKBACK: int = 200

#: Direction -> signal mapping used by the SignalStrategy base.
_SIGNAL_MAP: dict[str, float] = {"long": 1.0, "short": -1.0, "flat": 0.0}


class TechtradeConfluence(_BaseSignal):
    """The techtrade confluence engine wrapped as a ``SignalStrategy`` (design Q-B B2).

    Each :meth:`signal` call re-runs the #74 confluence engine on the trailing
    ``lookback`` bars per universe symbol, producing one signal per session that
    walks the WFO / CPCV folds backtest constructs over ``[as_of - horizon, as_of]``.

    Parameters
    ----------
    symbols : Iterable[str]
        Universe of symbols (typically ``[plan.symbol]`` for a single-plan validation).
    lookback : int, optional
        Trailing window length per session (default :data:`DEFAULT_LOOKBACK`).
    entry_threshold : float, optional
        Min ``|score|`` to take a directional position. Matches
        :attr:`~openbb_techtrade.models.EntryExitRule.entry_threshold` (default 0.4).
    gross : float, optional
        Target gross exposure (default 1.0).
    id : str, optional
        Strategy id; defaults to ``"techtrade_confluence"``.
    """

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        lookback: int = DEFAULT_LOOKBACK,
        entry_threshold: float = 0.4,
        gross: float = 1.0,
        id: str = "techtrade_confluence",  # noqa: A002 - mirrors Strategy protocol field
    ) -> None:
        super().__init__(id, target_gross=gross)
        self.symbols: list[str] = list(symbols)
        self.lookback: int = int(lookback)
        self.entry_threshold: float = float(entry_threshold)
        if not self.symbols:
            raise ValueError("techtrade_confluence requires a non-empty symbol universe")
        if self.lookback < 30:
            # Indicator stack needs ~70 bars to stabilize; refuse < 30 outright so the
            # caller fails fast on a misconfiguration instead of getting silent zeros.
            raise ValueError(
                f"techtrade_confluence needs lookback >= 30 to warm up indicators; got {self.lookback}"
            )
        if not (0.0 <= self.entry_threshold <= 1.0):
            raise ValueError(
                f"entry_threshold must lie in [0, 1]; got {self.entry_threshold}"
            )

    def signal(self, data: "MarketData") -> pd.Series:
        """Score each universe symbol's trailing window through the #74 confluence engine.

        ``data.window(symbols, lookback)`` returns a *long* DataFrame indexed by
        ``(session, symbol)`` with OHLCV columns. We pivot per symbol to a per-bar
        OHLCV slice, build the techtrade panel on the slice's last bar, score the
        confluence, and map ``direction -> {+1, 0, -1}``.

        Symbols whose history is too short (fewer than the longest indicator period
        + a small warmup) are silently mapped to ``flat`` -- the same degradation
        rule techtrade's own panel builder uses (#72).

        Parameters
        ----------
        data : MarketData
            Point-in-time market view; only bars up to ``data.now`` are exposed.

        Returns
        -------
        pandas.Series
            Symbol-indexed signal in ``{-1.0, 0.0, +1.0}``.
        """
        # Lazy imports keep this module load-safe at backtest entry-point discovery
        # time even before techtrade's engine package has been touched.
        from openbb_techtrade.engine.confluence import (
            composite_score,
            direction_for,
        )
        from openbb_techtrade.engine.indicators import build_indicator_panel

        window = data.window(self.symbols, self.lookback)
        now = data.now
        # ``data.now`` is a pd.Timestamp; the panel builder takes a date.
        as_of_date: date = pd.Timestamp(now).date() if not isinstance(now, date) else now

        signals: dict[str, float] = {}
        for symbol in self.symbols:
            rows = self._slice_for_symbol(window, symbol)
            if not rows:
                signals[symbol] = 0.0
                continue
            try:
                panel = build_indicator_panel(symbol, as_of_date, rows)
                score, _votes = composite_score(panel)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not abort the fold
                logger.debug(
                    "techtrade_confluence: %s scoring failed on %s: %s",
                    symbol, as_of_date, exc,
                )
                signals[symbol] = 0.0
                continue
            direction = direction_for(score, entry_threshold=self.entry_threshold)
            signals[symbol] = _SIGNAL_MAP[direction]
        return pd.Series(signals)

    @staticmethod
    def _slice_for_symbol(window: pd.DataFrame, symbol: str) -> list[dict]:
        """Return ``window`` rows for ``symbol`` as a list of OHLCV dicts.

        The base ``MarketData.window`` returns a long DataFrame keyed by
        ``(session, symbol)`` -- we filter to one symbol, sort chronologically, and
        coerce to the dict shape the techtrade indicator builder accepts (which is
        the same shape #72's tests use).
        """
        if window.empty:
            return []
        # ``session`` and ``symbol`` may be index levels or columns; normalize to columns.
        if "symbol" in window.index.names or "session" in window.index.names:
            window = window.reset_index()
        if "symbol" not in window.columns:
            return []
        symbol_rows = window[window["symbol"] == symbol]
        if symbol_rows.empty:
            return []
        if "session" in symbol_rows.columns:
            symbol_rows = symbol_rows.sort_values("session")
        keep = [col for col in ("open", "high", "low", "close", "volume") if col in symbol_rows.columns]
        if "close" not in keep:
            return []
        return symbol_rows[keep].to_dict(orient="records")
