"""Unit tests for W5/W6/W8 free-tier extras (30 fetchers, batch 15)."""

from __future__ import annotations

import pytest

# --- Registration ---


ALL_KEYS = [
    "DelistedCompanies",
    "MergersAcquisitionsLatest",
    "StandardIndustrialClassificationList",
    "AllIndustryClassification",
    "SenateLatest",
    "HouseLatest",
    "SenateProfile",
    "SenatePositions",
    "MergersAcquisitionsSearch",
    "AcquisitionOfBeneficialOwnership",
    "SecFilings8K",
    "SecProfile",
    "IndustryClassificationSearch",
    "SenateNetWorth",
    "SenateNetWorthAggregated",
    "IposDisclosure",
    "IposProspectus",
    "CrowdfundingOfferingsLatest",
    "FundraisingLatest",
    "FmpArticles",
    "NewsCryptoLatest",
    "NewsForexLatest",
    "CrowdfundingOfferingsSearch",
    "CrowdfundingOfferings",
    "FundraisingSearch",
    "Fundraising",
    "NewsCrypto",
    "NewsForex",
    "CommitmentOfTradersReport",
    "CommitmentOfTradersAnalysis",
]


def test_all_thirty_registered_in_provider():
    """Provider registration is what makes the coverage gate see them."""
    from openbb_fmp_cached import fmp_cached_provider

    for name in ALL_KEYS:
        assert name in fmp_cached_provider.fetcher_dict, f"{name} not registered"
    assert len(ALL_KEYS) == 30


# --- Query-field regression guards ---


def test_no_param_fetchers_use_unused_key():
    """The 17 no-param fetchers use _query_field='unused' (FMP ignores it)."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import (
        FMPCachedAllIndustryClassificationFetcher,
        FMPCachedCommitmentOfTradersAnalysisFetcher,
        FMPCachedCommitmentOfTradersReportFetcher,
        FMPCachedCrowdfundingOfferingsLatestFetcher,
        FMPCachedDelistedCompaniesFetcher,
        FMPCachedFmpArticlesFetcher,
        FMPCachedFundraisingLatestFetcher,
        FMPCachedHouseLatestFetcher,
        FMPCachedIposDisclosureFetcher,
        FMPCachedIposProspectusFetcher,
        FMPCachedMergersAcquisitionsLatestFetcher,
        FMPCachedNewsCryptoLatestFetcher,
        FMPCachedNewsForexLatestFetcher,
        FMPCachedSenateLatestFetcher,
        FMPCachedSenatePositionsFetcher,
        FMPCachedSenateProfileFetcher,
        FMPCachedStandardIndustrialClassificationListFetcher,
    )

    for f in (
        FMPCachedDelistedCompaniesFetcher,
        FMPCachedMergersAcquisitionsLatestFetcher,
        FMPCachedStandardIndustrialClassificationListFetcher,
        FMPCachedAllIndustryClassificationFetcher,
        FMPCachedSenateLatestFetcher,
        FMPCachedHouseLatestFetcher,
        FMPCachedSenateProfileFetcher,
        FMPCachedSenatePositionsFetcher,
        FMPCachedIposDisclosureFetcher,
        FMPCachedIposProspectusFetcher,
        FMPCachedCrowdfundingOfferingsLatestFetcher,
        FMPCachedFundraisingLatestFetcher,
        FMPCachedFmpArticlesFetcher,
        FMPCachedNewsCryptoLatestFetcher,
        FMPCachedNewsForexLatestFetcher,
        FMPCachedCommitmentOfTradersReportFetcher,
        FMPCachedCommitmentOfTradersAnalysisFetcher,
    ):
        assert f._query_field == "unused", f"{f.__name__} not no-param"


def test_param_fetchers_use_correct_field():
    """The 13 with-param fetchers each use the correct FMP-specified field."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import (
        FMPCachedAcquisitionOfBeneficialOwnershipFetcher,
        FMPCachedCrowdfundingOfferingsFetcher,
        FMPCachedCrowdfundingOfferingsSearchFetcher,
        FMPCachedFundraisingFetcher,
        FMPCachedFundraisingSearchFetcher,
        FMPCachedIndustryClassificationSearchFetcher,
        FMPCachedMergersAcquisitionsSearchFetcher,
        FMPCachedNewsCryptoFetcher,
        FMPCachedNewsForexFetcher,
        FMPCachedSecFilings8KFetcher,
        FMPCachedSecProfileFetcher,
        FMPCachedSenateNetWorthAggregatedFetcher,
        FMPCachedSenateNetWorthFetcher,
    )

    for f in (
        FMPCachedMergersAcquisitionsSearchFetcher,
        FMPCachedCrowdfundingOfferingsSearchFetcher,
        FMPCachedFundraisingSearchFetcher,
    ):
        assert f._query_field == "name", f"{f.__name__} wrong param"
    for f in (
        FMPCachedAcquisitionOfBeneficialOwnershipFetcher,
        FMPCachedSecProfileFetcher,
        FMPCachedIndustryClassificationSearchFetcher,
    ):
        assert f._query_field == "symbol", f"{f.__name__} wrong param"
    for f in (FMPCachedCrowdfundingOfferingsFetcher, FMPCachedFundraisingFetcher):
        assert f._query_field == "cik", f"{f.__name__} wrong param"
    for f in (
        FMPCachedSenateNetWorthFetcher,
        FMPCachedSenateNetWorthAggregatedFetcher,
    ):
        assert f._query_field == "senateID", f"{f.__name__} wrong param"
    for f in (FMPCachedNewsCryptoFetcher, FMPCachedNewsForexFetcher):
        assert f._query_field == "symbols", f"{f.__name__} wrong param"
    assert FMPCachedSecFilings8KFetcher._query_field == "page"


# --- Data class shape ---


def test_generic_row_extra_allow_preserves_arbitrary_fields():
    """FMPCachedGenericRowData with extra=allow preserves whatever FMP returns."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import FMPCachedGenericRowData

    row = {
        "symbol": "AAPL",
        "companyName": "Apple",
        "randomFmpField": 123,
        "nested": {"a": 1, "b": [2, 3]},
    }
    obj = FMPCachedGenericRowData.model_validate(row)
    d = obj.model_dump()
    assert d["symbol"] == "AAPL"
    assert d["randomFmpField"] == 123
    assert d["nested"] == {"a": 1, "b": [2, 3]}


def test_transform_data_handles_empty_input():
    """Empty list in -> empty list out for all fetchers (spot-check)."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import (
        FMPCachedDelistedCompaniesFetcher,
        FMPCachedNewsCryptoFetcher,
        FMPCachedSecProfileFetcher,
    )

    for f in (
        FMPCachedDelistedCompaniesFetcher,
        FMPCachedSecProfileFetcher,
        FMPCachedNewsCryptoFetcher,
    ):
        assert f.transform_data(None, []) == []


# --- New QueryParams shape ---


def test_new_query_params_require_field():
    """_NameQueryParams and _SenateIdQueryParams require their fields."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import (
        _NameQueryParams,
        _SenateIdQueryParams,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _NameQueryParams()
    with pytest.raises(ValidationError):
        _SenateIdQueryParams()
    # Filled succeeds
    q = _NameQueryParams(name="Apple")
    assert q.name == "Apple"
    s = _SenateIdQueryParams(senateID="A000360")
    assert s.senateID == "A000360"


def test_page_query_params_defaults_to_zero():
    """_PageQueryParams has default 0 (page= param optional)."""
    from openbb_fmp_cached.models.w5_w6_w8_extras import _PageQueryParams

    assert _PageQueryParams().page == 0
    assert _PageQueryParams(page=3).page == 3
