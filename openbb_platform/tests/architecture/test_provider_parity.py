"""CI guardrail: every fmp fetcher key must exist in fmp_cached.

Enforces PRD §5 acceptance criterion AC-parity-1:
    set(fmp_provider.fetcher_dict) ⊂ set(fmp_cached_provider.fetcher_dict)

Also asserts the six new Phase-0 intraday fetchers land in both providers
in the same commit (no drift window).
"""

from __future__ import annotations

import pytest

# Fetcher keys introduced by the fmp-day-trading PRD Phase 0 (PRD §5.1 matrix).
# Each MUST land in both providers before this test goes green.
PRD_PHASE_0_FETCHERS: frozenset[str] = frozenset(
    {
        "EquityIntradayHistorical",
        "AftermarketQuote",
        "AftermarketTrade",
        "EquityQuoteBatchShort",
        "ExchangeMarketHours",
        "TechnicalIndicatorIntraday",
    }
)


@pytest.fixture(scope="module")
def fmp_keys() -> frozenset[str]:
    from openbb_fmp import fmp_provider

    return frozenset(fmp_provider.fetcher_dict.keys())


@pytest.fixture(scope="module")
def fmp_cached_keys() -> frozenset[str]:
    from openbb_fmp_cached import fmp_cached_provider

    return frozenset(fmp_cached_provider.fetcher_dict.keys())


def test_fmp_keys_subset_of_fmp_cached(
    fmp_keys: frozenset[str], fmp_cached_keys: frozenset[str]
) -> None:
    """AC-parity-1: fmp is a subset of fmp_cached."""
    missing = fmp_keys - fmp_cached_keys
    assert not missing, (
        f"{len(missing)} fmp fetcher(s) missing from fmp_cached: "
        f"{sorted(missing)}\n\n"
        "Every fmp fetcher MUST have an fmp_cached twin registered in the "
        "same commit (PRD §5, AC-parity-1)."
    )


def test_prd_phase_0_fetchers_in_fmp(fmp_keys: frozenset[str]) -> None:
    """All six Phase-0 fetchers registered in openbb_fmp."""
    missing = PRD_PHASE_0_FETCHERS - fmp_keys
    assert not missing, (
        f"Phase-0 fetchers not yet registered in openbb_fmp: {sorted(missing)}"
    )


def test_prd_phase_0_fetchers_in_fmp_cached(
    fmp_cached_keys: frozenset[str],
) -> None:
    """All six Phase-0 fetchers registered in openbb_fmp_cached."""
    missing = PRD_PHASE_0_FETCHERS - fmp_cached_keys
    assert not missing, (
        f"Phase-0 fetchers not yet registered in openbb_fmp_cached: "
        f"{sorted(missing)}"
    )
