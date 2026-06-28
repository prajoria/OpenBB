"""``factor_tilt`` — cross-sectional factor-score tilt (component 10.5).

A :class:`~openbb_backtest.strategies.base.CrossSectionalStrategy` that tilts the
book toward symbols carrying a high per-symbol **factor score**. The score for
each symbol is supplied by an *injected* ``score_provider`` rather than computed
inside the strategy, which is what keeps it deterministic, unit-testable and
**look-ahead-safe**:

- a static ``Mapping[str, float]`` (``{symbol: score}``), or
- a point-in-time ``Callable[[str, pandas.Timestamp], float]`` invoked as
  ``provider(symbol, data.now)`` — it only ever sees the current session, never a
  future one.

The raw scores are returned from :meth:`rank`; the base template demeans them
(dollar-neutral) and scales gross exposure to ``gross``, so the highest-scoring
names are the long leg and the lowest-scoring the short leg.

**Look-ahead caveat.** Point-in-time safety is the *provider's* responsibility:
a callable must return only information knowable as of the ``now`` it is given.
The bundled :mod:`openbb_backtest.strategies.analysis_bridge` adapter wraps
``Analysis.run_full_analysis``, which currently fetches *latest* fundamentals and
is therefore **not** strictly point-in-time — use it for research/illustration,
not as a historically faithful backtest input. A point-in-time Pipeline wiring is
deferred until the data layer (component 05) lands; see the follow-up bead.

See ``docs/designs/backtest-design/10-strategy-library.md`` §3.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping

import pandas as pd

from openbb_backtest.interfaces import MarketData
from openbb_backtest.registry import register_strategy
from openbb_backtest.strategies.base import CrossSectionalStrategy

logger = logging.getLogger(__name__)

#: A factor-score source: either a static ``{symbol: score}`` mapping or a
#: point-in-time ``callable(symbol, now) -> score``.
ScoreProvider = Mapping[str, float] | Callable[[str, pd.Timestamp], float]


@register_strategy("factor_tilt")
class FactorTilt(CrossSectionalStrategy):
    """Tilt long the highest-scoring names, short the lowest, dollar-neutral."""

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        score_provider: ScoreProvider | None,
        gross: float = 1.0,
        id: str = "factor_tilt",  # noqa: A002 - mirrors the Strategy protocol field
    ) -> None:
        super().__init__(id, target_gross=gross)
        self.symbols = list(symbols)
        if not self.symbols:
            raise ValueError("factor_tilt requires a non-empty symbol universe")
        if score_provider is None:
            raise ValueError("factor_tilt requires a score_provider (mapping or callable)")
        self.score_provider: ScoreProvider = score_provider

    def rank(self, data: MarketData) -> pd.Series:
        """Per-symbol factor score from the injected provider (missing -> 0.0)."""
        scores: dict[str, float] = {}
        for sym in self.symbols:
            scores[sym] = self._score(sym, data.now)
        logger.debug("%s scored %d symbols as of %s", self.id, len(scores), data.now)
        return pd.Series(scores)

    def _score(self, symbol: str, now: pd.Timestamp) -> float:
        """Resolve one symbol's score from a mapping or a point-in-time callable."""
        provider = self.score_provider
        if callable(provider):
            return float(provider(symbol, now))
        return float(provider.get(symbol, 0.0))
