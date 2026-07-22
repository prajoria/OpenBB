"""Unit tests for single-param fetchers (#1085 #1099 #1224)."""

from __future__ import annotations

import pytest


def test_company_notes_transform_data():
    """company-notes returns {cik, symbol, title, exchange} — no aliases needed."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        FMPCachedCompanyNotesFetcher,
    )

    rows = [
        {
            "cik": "0000320193",
            "symbol": "AAPL",
            "title": "0.000% Notes due 2025",
            "exchange": "NASDAQ",
        }
    ]
    out = FMPCachedCompanyNotesFetcher.transform_data(None, rows)
    assert out[0].cik == "0000320193"
    assert isinstance(out[0].cik, str)
    assert out[0].symbol == "AAPL"


def test_executive_compensation_benchmark_maps_camelcase():
    """IndustryTitle -> industry_title, averageCompensation -> average_compensation."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        FMPCachedExecutiveCompensationBenchmarkFetcher,
    )

    rows = [
        {
            "industryTitle": "STEEL WORKS, BLAST FURNACES",
            "year": 2024,
            "averageCompensation": 1_250_000.5,
        }
    ]
    out = FMPCachedExecutiveCompensationBenchmarkFetcher.transform_data(None, rows)
    assert out[0].industry_title == "STEEL WORKS, BLAST FURNACES"
    assert out[0].year == 2024
    assert out[0].average_compensation == pytest.approx(1_250_000.5)


def test_holidays_by_exchange_maps_camelcase():
    """isClosed, adjOpenTime, adjCloseTime all remap."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        FMPCachedHolidaysByExchangeFetcher,
    )

    rows = [
        {
            "exchange": "NYSE",
            "date": "2026-07-03",
            "name": "Independence Day",
            "isClosed": True,
            "adjOpenTime": None,
            "adjCloseTime": None,
        },
        {
            "exchange": "NYSE",
            "date": "2026-12-24",
            "name": "Christmas Eve",
            "isClosed": False,
            "adjOpenTime": "09:30",
            "adjCloseTime": "13:00",
        },
    ]
    out = FMPCachedHolidaysByExchangeFetcher.transform_data(None, rows)
    assert out[0].date == "2026-07-03"
    assert out[0].is_closed is True
    assert out[0].adj_open_time is None
    assert out[1].is_closed is False
    assert out[1].adj_open_time == "09:30"


def test_query_field_configuration():
    """Each fetcher uses the correct FMP-specified query param."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        FMPCachedCompanyNotesFetcher,
        FMPCachedExecutiveCompensationBenchmarkFetcher,
        FMPCachedHolidaysByExchangeFetcher,
    )

    assert FMPCachedCompanyNotesFetcher._query_field == "symbol"
    assert FMPCachedExecutiveCompensationBenchmarkFetcher._query_field == "year"
    assert FMPCachedHolidaysByExchangeFetcher._query_field == "exchange"


def test_all_three_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "CompanyNotes",
        "ExecutiveCompensationBenchmark",
        "HolidaysByExchange",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_query_params_reject_missing_required():
    """Each typed QueryParams class requires its keyed field."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        _ExchangeQueryParams,
        _SymbolQueryParams,
        _YearQueryParams,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _SymbolQueryParams()
    with pytest.raises(ValidationError):
        _YearQueryParams()
    with pytest.raises(ValidationError):
        _ExchangeQueryParams()


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.single_param_endpoints import (
        FMPCachedCompanyNotesFetcher,
    )

    assert FMPCachedCompanyNotesFetcher.transform_data(None, []) == []
