"""Engine-agnostic strategy base templates (component 10, §base classes).

Three small templates that satisfy the
:class:`~openbb_backtest.interfaces.Strategy` protocol (``id`` + ``generate``) by
normalizing a single abstract hook into the symbol-indexed ``['weight']``
DataFrame both engines' ``_build_weights`` consume:

- :class:`WeightStrategy` — override :meth:`~WeightStrategy.target_weights` to
  return target weights; they are validated and passed through (NaN-safe).
- :class:`SignalStrategy` — override :meth:`~SignalStrategy.signal` to return
  discrete signals in ``{-1, 0, 1}``; they are mapped to weights whose gross
  exposure sums to ``target_gross``.
- :class:`CrossSectionalStrategy` — override :meth:`~CrossSectionalStrategy.rank`
  to return a cross-sectional score; scores are demeaned to a dollar-neutral
  book and scaled so gross exposure sums to ``target_gross``.

The templates are *engine-agnostic*: they only read ``data.window`` /
``data.now`` (point-in-time, no future peeking) and never import an engine.
They deliberately expose **no** ``initialize`` / ``finalize`` /
``StrategyContext`` — the :class:`Strategy` protocol is just ``id`` + ``generate``.

See ``docs/designs/backtest-design/10-strategies.md`` and
``openbb_backtest/interfaces.py`` (Strategy / MarketData protocols).
"""

from __future__ import annotations

import logging

import pandas as pd

from openbb_backtest.interfaces import MarketData

logger = logging.getLogger(__name__)

#: Column name carried by the DataFrame the engines' ``_build_weights`` consume.
_WEIGHT = "weight"
#: The only signal values accepted by :class:`SignalStrategy`.
_VALID_SIGNALS = frozenset({-1.0, 0.0, 1.0})


class _BaseStrategy:
    """Shared ``id`` plumbing + the weight-frame normalization helpers.

    Not a strategy on its own — concrete templates below supply the abstract
    hook and the :meth:`generate` that drives it.
    """

    def __init__(self, id: str | None = None) -> None:  # noqa: A002 - protocol field
        self.id: str = id if id is not None else type(self).__name__

    @staticmethod
    def _to_weight_frame(weights: pd.Series) -> pd.DataFrame:
        """Coerce a symbol-indexed series into a NaN-safe ``['weight']`` frame."""
        return weights.astype(float).fillna(0.0).to_frame(name=_WEIGHT)

    @staticmethod
    def _scale_to_gross(values: pd.Series, target_gross: float) -> pd.Series:
        """Scale ``values`` so the sum of absolute exposure equals ``target_gross``.

        A zero-gross book (all flat / fully demeaned to zero) is returned as-is,
        avoiding a divide-by-zero and yielding an all-zero weight vector.
        """
        gross = float(values.abs().sum())
        if gross == 0.0:
            return values.astype(float)
        return values.astype(float) * (target_gross / gross)


class WeightStrategy(_BaseStrategy):
    """Template for strategies that emit target weights directly."""

    def target_weights(self, data: MarketData) -> pd.Series:
        """Return symbol-indexed target weights (override me).

        Parameters
        ----------
        data
            Point-in-time market view (``window`` / ``now`` only).

        Returns
        -------
        pandas.Series
            Target weights indexed by symbol.
        """
        raise NotImplementedError("WeightStrategy subclasses must implement target_weights")

    def generate(self, data: MarketData) -> pd.DataFrame:
        """Validate and pass the hook's target weights through (NaN-safe)."""
        weights = self.target_weights(data)
        logger.debug("%s produced %d target weights", self.id, len(weights))
        return self._to_weight_frame(weights)


class SignalStrategy(_BaseStrategy):
    """Template mapping discrete ``{-1, 0, 1}`` signals to equal-gross weights."""

    def __init__(self, id: str | None = None, *, target_gross: float = 1.0) -> None:  # noqa: A002
        super().__init__(id)
        self.target_gross = target_gross

    def signal(self, data: MarketData) -> pd.Series:
        """Return symbol-indexed signals in ``{-1, 0, 1}`` (override me)."""
        raise NotImplementedError("SignalStrategy subclasses must implement signal")

    def generate(self, data: MarketData) -> pd.DataFrame:
        """Map validated signals to weights summing to ``target_gross``."""
        signals = self.signal(data).astype(float)
        invalid = set(signals.dropna().unique()) - _VALID_SIGNALS
        if invalid:
            raise ValueError(f"signal values must be in {{-1, 0, 1}}; got {sorted(invalid)}")
        signals = signals.fillna(0.0)
        weights = self._scale_to_gross(signals, self.target_gross)
        logger.debug("%s mapped %d signals to weights", self.id, len(weights))
        return self._to_weight_frame(weights)


class CrossSectionalStrategy(_BaseStrategy):
    """Template turning a cross-sectional score into dollar-neutral weights."""

    def __init__(self, id: str | None = None, *, target_gross: float = 1.0) -> None:  # noqa: A002
        super().__init__(id)
        self.target_gross = target_gross

    def rank(self, data: MarketData) -> pd.Series:
        """Return a symbol-indexed cross-sectional score (override me)."""
        raise NotImplementedError("CrossSectionalStrategy subclasses must implement rank")

    def generate(self, data: MarketData) -> pd.DataFrame:
        """Demean the score (dollar-neutral) then scale to ``target_gross``."""
        scores = self.rank(data).astype(float).fillna(0.0)
        demeaned = scores - scores.mean()
        weights = self._scale_to_gross(demeaned, self.target_gross)
        logger.debug("%s normalized %d ranks to weights", self.id, len(weights))
        return self._to_weight_frame(weights)
