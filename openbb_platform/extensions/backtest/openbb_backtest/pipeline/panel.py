"""Factor panel: a tidy ``(date, asset)`` MultiIndex of factor values.

:class:`FactorPanel` is the canonical output of the cross-sectional pipeline
(component 05, §2): one row per ``(session, symbol)`` and one column per factor.
It round-trips losslessly to and from a plain frame and exposes per-session
cross-sections for ranking/allocation.

See ``docs/designs/backtest-design/05-event-driven-engine.md`` §2.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_INDEX_NAMES = ["date", "asset"]


@dataclass(frozen=True)
class FactorPanel:
    """Factor values indexed by ``(date, asset)`` with factors as columns."""

    frame: pd.DataFrame

    @staticmethod
    def from_frame(frame: pd.DataFrame) -> FactorPanel:
        """Wrap a ``(date, asset)`` MultiIndex frame, validating its shape.

        Raises :class:`ValueError` when the frame is not indexed by a 2-level
        ``(date, asset)`` MultiIndex, so a mis-shaped frame fails fast instead
        of silently producing wrong cross-sections.
        """
        if not isinstance(frame.index, pd.MultiIndex) or frame.index.nlevels != 2:
            raise ValueError(
                "FactorPanel requires a 2-level (date, asset) MultiIndex frame"
            )
        return FactorPanel(frame.copy())

    def to_frame(self) -> pd.DataFrame:
        """Return the underlying ``(date, asset)`` frame (a defensive copy)."""
        return self.frame.copy()

    @property
    def factors(self) -> list[str]:
        """Factor column names, in panel order."""
        return list(self.frame.columns)

    @property
    def assets(self) -> list[str]:
        """Distinct assets present in the panel, in first-seen order."""
        return list(self.frame.index.get_level_values(1).unique())

    @property
    def dates(self) -> pd.DatetimeIndex:
        """Distinct session dates present in the panel."""
        return pd.DatetimeIndex(self.frame.index.get_level_values(0).unique())

    def cross_section(self, date: pd.Timestamp) -> pd.DataFrame:
        """Return the ``asset x factor`` slice for a single session ``date``."""
        xs = self.frame.xs(pd.Timestamp(date), level=0)
        xs.index.name = "asset"
        return xs
