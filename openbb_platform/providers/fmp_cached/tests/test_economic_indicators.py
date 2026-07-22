"""Unit tests for economic-indicators fetcher (#1108)."""

from __future__ import annotations

import pytest


def test_economic_indicators_transform_data():
    """Simple 3-field row."""
    from openbb_fmp_cached.models.economic_indicators import (
        FMPCachedEconomicIndicatorsFetcher,
    )

    rows = [{"name": "GDP", "date": "2025-10-01", "value": 31422.526}]
    out = FMPCachedEconomicIndicatorsFetcher.transform_data(None, rows)
    assert out[0].name == "GDP"
    assert out[0].date == "2025-10-01"
    assert out[0].value == pytest.approx(31422.526)


def test_query_field_is_name():
    """economic-indicators takes name= (not symbol=)."""
    from openbb_fmp_cached.models.economic_indicators import (
        FMPCachedEconomicIndicatorsFetcher,
    )

    assert FMPCachedEconomicIndicatorsFetcher._query_field == "name"


def test_registered_in_provider():
    """Registration check."""
    from openbb_fmp_cached import fmp_cached_provider

    assert "EconomicIndicators" in fmp_cached_provider.fetcher_dict


def test_query_params_require_name():
    """_IndicatorNameQueryParams requires name field."""
    from openbb_fmp_cached.models.economic_indicators import _IndicatorNameQueryParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _IndicatorNameQueryParams()


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.economic_indicators import (
        FMPCachedEconomicIndicatorsFetcher,
    )

    assert FMPCachedEconomicIndicatorsFetcher.transform_data(None, []) == []
