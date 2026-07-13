"""openbb-regime — shared market-regime detector for OpenBB.

Exposes :class:`~openbb_regime.detector.MarketRegime` and
:func:`~openbb_regime.detector.detect_market_regime` for direct use by
Analysis / techtrade / any future consumer. The ``obb.regime.*`` router
surface ships in Phase B4 (bd-0h2.16); this package's pure-function
detector is import-usable now.

See :mod:`openbb_regime.detector` for the classification logic and
:doc:`README <..>` for design invariants (hysteresis, golden fixtures).
"""

from openbb_regime.detector import MarketRegime, detect_market_regime

__all__ = ["MarketRegime", "detect_market_regime"]
