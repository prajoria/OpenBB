"""Curated reference strategy library."""

from openbb_backtest.strategies.analysis_bridge import (
    default_run_analysis,
    make_analysis_score_provider,
)
from openbb_backtest.strategies.base import (
    CrossSectionalStrategy,
    SignalStrategy,
    WeightStrategy,
)
from openbb_backtest.strategies.buy_and_hold import BuyAndHold
from openbb_backtest.strategies.discovery import discover, load_plugins, resolve
from openbb_backtest.strategies.factor_tilt import FactorTilt
from openbb_backtest.strategies.mean_reversion import MeanReversion
from openbb_backtest.strategies.momentum import Momentum
from openbb_backtest.strategies.risk_parity import RiskParity
from openbb_backtest.strategies.vol_targeting import VolTargeting

__all__ = [
    "BuyAndHold",
    "CrossSectionalStrategy",
    "FactorTilt",
    "MeanReversion",
    "Momentum",
    "RiskParity",
    "SignalStrategy",
    "VolTargeting",
    "WeightStrategy",
    "default_run_analysis",
    "discover",
    "load_plugins",
    "make_analysis_score_provider",
    "resolve",
]
