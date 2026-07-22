"""Unit tests for W7 MarketPerformance fetchers (#1212-#1219)."""

from __future__ import annotations

import pytest


def test_sector_perf_snapshot():
    """sector-performance-snapshot returns date-keyed sector rows."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedSectorPerformanceSnapshotFetcher,
    )

    rows = [{"date": "2026-07-17", "sector": "Technology", "averageChange": 1.23}]
    out = FMPCachedSectorPerformanceSnapshotFetcher.transform_data(None, rows)
    assert out[0].date == "2026-07-17"
    assert out[0].sector == "Technology"


def test_historical_sector_perf_maps_average_change():
    """historical-sector-performance: averageChange -> average_change."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedHistoricalSectorPerformanceFetcher,
    )

    rows = [
        {
            "date": "2024-03-01",
            "sector": "Technology",
            "exchange": "NASDAQ",
            "averageChange": -0.4723,
        }
    ]
    out = FMPCachedHistoricalSectorPerformanceFetcher.transform_data(None, rows)
    assert out[0].sector == "Technology"
    assert out[0].average_change == pytest.approx(-0.4723)


def test_historical_industry_perf_maps_average_change():
    """Same alias, industry keyed."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedHistoricalIndustryPerformanceFetcher,
    )

    rows = [
        {
            "date": "2024-03-01",
            "industry": "Semiconductors",
            "exchange": "NASDAQ",
            "averageChange": 4.82,
        }
    ]
    out = FMPCachedHistoricalIndustryPerformanceFetcher.transform_data(None, rows)
    assert out[0].industry == "Semiconductors"
    assert out[0].average_change == pytest.approx(4.82)


def test_historical_sector_pe_returns_pe_float():
    """historical-sector-pe: pe field passes through as float."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedHistoricalSectorPeFetcher,
    )

    rows = [
        {"date": "2024-03-01", "sector": "Technology", "exchange": "NASDAQ", "pe": 0.77}
    ]
    out = FMPCachedHistoricalSectorPeFetcher.transform_data(None, rows)
    assert out[0].pe == pytest.approx(0.77)


def test_query_field_configuration():
    """Each fetcher sends the correct FMP-specified query param."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedHistoricalIndustryPeFetcher,
        FMPCachedHistoricalIndustryPerformanceFetcher,
        FMPCachedHistoricalSectorPeFetcher,
        FMPCachedHistoricalSectorPerformanceFetcher,
        FMPCachedIndustryPerformanceSnapshotFetcher,
        FMPCachedIndustryPeSnapshotFetcher,
        FMPCachedSectorPerformanceSnapshotFetcher,
        FMPCachedSectorPeSnapshotFetcher,
    )

    # Snapshots take date
    for f in (
        FMPCachedSectorPerformanceSnapshotFetcher,
        FMPCachedIndustryPerformanceSnapshotFetcher,
        FMPCachedSectorPeSnapshotFetcher,
        FMPCachedIndustryPeSnapshotFetcher,
    ):
        assert f._query_field == "date", f"{f.__name__} wrong param"
    # Sector-keyed
    for f in (
        FMPCachedHistoricalSectorPerformanceFetcher,
        FMPCachedHistoricalSectorPeFetcher,
    ):
        assert f._query_field == "sector", f"{f.__name__} wrong param"
    # Industry-keyed
    for f in (
        FMPCachedHistoricalIndustryPerformanceFetcher,
        FMPCachedHistoricalIndustryPeFetcher,
    ):
        assert f._query_field == "industry", f"{f.__name__} wrong param"


def test_all_eight_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in (
        "SectorPerformanceSnapshot",
        "IndustryPerformanceSnapshot",
        "SectorPeSnapshot",
        "IndustryPeSnapshot",
        "HistoricalSectorPerformance",
        "HistoricalIndustryPerformance",
        "HistoricalSectorPe",
        "HistoricalIndustryPe",
    ):
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"


def test_query_params_require_field():
    """Each typed QueryParams class requires its keyed field."""
    from openbb_fmp_cached.models.sector_performance import (
        _DateQueryParams,
        _IndustryQueryParams,
        _SectorQueryParams,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _DateQueryParams()
    with pytest.raises(ValidationError):
        _SectorQueryParams()
    with pytest.raises(ValidationError):
        _IndustryQueryParams()


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out."""
    from openbb_fmp_cached.models.sector_performance import (
        FMPCachedSectorPerformanceSnapshotFetcher,
    )

    assert FMPCachedSectorPerformanceSnapshotFetcher.transform_data(None, []) == []
