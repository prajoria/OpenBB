"""Cached company_news model for FMP."""

from openbb_fmp.models.company_news import FMPCompanyNewsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP company_news fetcher
FMPCachedCompanyNewsFetcher = create_cached_fetcher_class(
    FMPCompanyNewsFetcher,
    "company_news"
)
