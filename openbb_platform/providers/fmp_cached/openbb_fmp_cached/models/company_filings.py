"""Cached company_filings model for FMP."""

from openbb_fmp.models.company_filings import FMPCompanyFilingsFetcher
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP company_filings fetcher
FMPCachedCompanyFilingsFetcher = create_cached_fetcher_class(
    FMPCompanyFilingsFetcher,
    "company_filings"
)
