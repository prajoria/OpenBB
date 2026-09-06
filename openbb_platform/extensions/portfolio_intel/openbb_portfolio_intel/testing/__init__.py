"""Testing utilities for portfolio-intel — synthetic fixtures + oracles."""

from openbb_portfolio_intel.testing.brinson_fixtures import (
    GOLDEN_CASES,
    OracleResult,
    SyntheticCase,
    generate_case,
    iter_random_cases,
    oracle_bf,
)

__all__ = [
    "GOLDEN_CASES",
    "OracleResult",
    "SyntheticCase",
    "generate_case",
    "iter_random_cases",
    "oracle_bf",
]
