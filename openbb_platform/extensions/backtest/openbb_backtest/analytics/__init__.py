"""Performance analytics and reporting wrappers."""

from openbb_backtest.analytics._common import (
    assert_normalized,
    optional_import,
    to_returns,
)
from openbb_backtest.analytics.export import export_html
from openbb_backtest.analytics.metrics import compute_metrics
from openbb_backtest.analytics.tearsheet import (
    build_tearsheet,
    compute_benchmark_stats,
)

__all__ = [
    "assert_normalized",
    "build_tearsheet",
    "compute_benchmark_stats",
    "compute_metrics",
    "export_html",
    "optional_import",
    "to_returns",
]
