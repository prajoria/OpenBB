"""Anti-overfitting validation framework (WFO / CPCV / PBO / DSR)."""

from openbb_backtest.validation.cpcv import cpcv, n_backtest_paths
from openbb_backtest.validation.pbo import pbo
from openbb_backtest.validation.report import build_validation_report, verdict
from openbb_backtest.validation.splitters import Fold, walk_forward
from openbb_backtest.validation.stats import (
    deflated_sharpe,
    min_backtest_length,
    probabilistic_sharpe,
)

__all__ = [
    "Fold",
    "build_validation_report",
    "cpcv",
    "deflated_sharpe",
    "min_backtest_length",
    "n_backtest_paths",
    "pbo",
    "probabilistic_sharpe",
    "verdict",
    "walk_forward",
]
