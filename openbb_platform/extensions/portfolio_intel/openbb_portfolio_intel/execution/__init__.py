"""Execution primitives for the paper-trading side of portfolio-intel.

Every module here implements the ``openbb_backtest.interfaces.Broker``
Protocol so that a future swap between SimpleFillModel (paper trading
today) and openbb_backtest's RealisticBroker (backtest, or paper trading
after it gains all the features RealisticBroker has) is a constructor
argument change, not a rewrite.

Design decision: #498 A' resolution
See: docs/superpowers/plans/2026-07-16-portfolio-intel-roadmap.md § M3
"""

from openbb_portfolio_intel.execution.simple_fill import SimpleFillModel

__all__ = ["SimpleFillModel"]
