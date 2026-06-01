"""SEC provider module."""

from openbb_core.provider.abstract.provider import Provider
from openbb_sec.models.cik_map import SecCikMapFetcher
from openbb_sec.models.company_filings import SecCompanyFilingsFetcher
from openbb_sec.models.compare_company_facts import SecCompareCompanyFactsFetcher
from openbb_sec.models.edgar_full_text_search import SecEdgarFullTextSearchFetcher
from openbb_sec.models.equity_ftd import SecEquityFtdFetcher
from openbb_sec.models.equity_search import SecEquitySearchFetcher
from openbb_sec.models.form_13FHR import SecForm13FHRFetcher
from openbb_sec.models.form_13f_holdings import SecForm13FHoldingsFetcher
from openbb_sec.models.htm_file import SecHtmFileFetcher
from openbb_sec.models.insider_trading import SecInsiderTradingFetcher
from openbb_sec.models.institutions_search import SecInstitutionsSearchFetcher
from openbb_sec.models.latest_financial_reports import SecLatestFinancialReportsFetcher
from openbb_sec.models.management_discussion_analysis import (
    SecManagementDiscussionAnalysisFetcher,
)
from openbb_sec.models.nport_disclosure import SecNportDisclosureFetcher
from openbb_sec.models.ownership_changes import SecOwnershipChangesFetcher
from openbb_sec.models.rss_litigation import SecRssLitigationFetcher
from openbb_sec.models.schema_files import SecSchemaFilesFetcher
from openbb_sec.models.sec_entity_info import SecEntityInfoFetcher
from openbb_sec.models.sec_filing import SecFilingFetcher
from openbb_sec.models.sic_search import SecSicSearchFetcher
from openbb_sec.models.symbol_map import SecSymbolMapFetcher
from openbb_sec.models.xbrl_company_concept import SecXbrlCompanyConceptFetcher

sec_provider = Provider(
    name="sec",
    website="https://www.sec.gov/data",
    description="SEC is the public listings regulatory body for the United States.",
    credentials=None,
    fetcher_dict={
        "CikMap": SecCikMapFetcher,
        "CompanyFilings": SecCompanyFilingsFetcher,
        "CompareCompanyFacts": SecCompareCompanyFactsFetcher,
        "EdgarFullTextSearch": SecEdgarFullTextSearchFetcher,
        "EquityFTD": SecEquityFtdFetcher,
        "EquitySearch": SecEquitySearchFetcher,
        "Filings": SecCompanyFilingsFetcher,
        "Form13FHR": SecForm13FHRFetcher,
        "Form13FHoldings": SecForm13FHoldingsFetcher,
        "SecHtmFile": SecHtmFileFetcher,
        "InsiderTrading": SecInsiderTradingFetcher,
        "InstitutionsSearch": SecInstitutionsSearchFetcher,
        "LatestFinancialReports": SecLatestFinancialReportsFetcher,
        "ManagementDiscussionAnalysis": SecManagementDiscussionAnalysisFetcher,
        "NportDisclosure": SecNportDisclosureFetcher,
        "OwnershipChanges": SecOwnershipChangesFetcher,
        "RssLitigation": SecRssLitigationFetcher,
        "SchemaFiles": SecSchemaFilesFetcher,
        "SecEntityInfo": SecEntityInfoFetcher,
        "SecFiling": SecFilingFetcher,
        "SicSearch": SecSicSearchFetcher,
        "SymbolMap": SecSymbolMapFetcher,
        "XbrlCompanyConcept": SecXbrlCompanyConceptFetcher,
    },
    repr_name="Securities and Exchange Commission (SEC)",
)
