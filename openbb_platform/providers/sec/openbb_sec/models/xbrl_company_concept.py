"""SEC XBRL Company Concept Model."""

# pylint: disable=unused-argument

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class SecXbrlCompanyConceptQueryParams(QueryParams):
    """SEC XBRL Company Concept Query.

    Source: https://data.sec.gov/api/xbrl/companyconcept/

    Returns the full history of a single XBRL fact (concept) for one company,
    e.g. all reported values of ``Revenues`` for Microsoft.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    fact: str = Field(
        default="Revenues",
        description=(
            "The XBRL concept/tag name in UpperCamelCase "
            "(e.g. 'Revenues', 'Assets', 'NetIncomeLoss'). "
            "Defaults to 'Revenues'."
        ),
    )
    taxonomy: str = Field(
        default="us-gaap",
        description=(
            "XBRL taxonomy namespace. Defaults to 'us-gaap'. "
            "Other options include 'dei', 'ifrs-full'."
        ),
    )
    unit: str = Field(
        default="USD",
        description=(
            "Unit of measurement filter. Defaults to 'USD'. "
            "Use 'shares' for share counts or 'USD/shares' for per-share data."
        ),
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use cache for the request. Defaults to True.",
    )


class SecXbrlCompanyConceptData(Data):
    """SEC XBRL Company Concept Data.

    Each row is one reported value of the XBRL concept for the company.
    """

    cik: str = Field(description="The CIK number of the company.")
    name: str | None = Field(
        default=None, description="The name of the reporting company."
    )
    label: str | None = Field(
        default=None, description="The human-readable label for the XBRL concept."
    )
    taxonomy: str | None = Field(
        default=None, description="The XBRL taxonomy (e.g. 'us-gaap')."
    )
    tag: str | None = Field(
        default=None, description="The XBRL tag/concept name."
    )
    unit: str | None = Field(
        default=None, description="The unit of measurement."
    )
    start_date: dateType | None = Field(
        default=None, description="The start date of the reporting period."
    )
    end_date: dateType | None = Field(
        default=None, description="The end date of the reporting period."
    )
    value: float | None = Field(
        default=None, description="The reported value."
    )
    accession: str | None = Field(
        default=None, description="SEC filing accession number."
    )
    fiscal_year: int | None = Field(
        default=None, description="Fiscal year of the report."
    )
    fiscal_period: str | None = Field(
        default=None, description="Fiscal period (e.g. 'FY', 'Q1', 'Q2')."
    )
    form: str | None = Field(
        default=None, description="SEC form type (e.g. '10-K', '10-Q')."
    )
    filed: dateType | None = Field(
        default=None, description="Date the filing was submitted to the SEC."
    )
    frame: str | None = Field(
        default=None, description="XBRL frame identifier, if available."
    )


class SecXbrlCompanyConceptFetcher(
    Fetcher[SecXbrlCompanyConceptQueryParams, list[SecXbrlCompanyConceptData]]
):
    """SEC XBRL Company Concept Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecXbrlCompanyConceptQueryParams:
        """Transform the query params."""
        return SecXbrlCompanyConceptQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecXbrlCompanyConceptQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract XBRL company concept data from the SEC API."""
        # pylint: disable=import-outside-toplevel
        from aiohttp_client_cache import SQLiteBackend
        from aiohttp_client_cache.session import CachedSession
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_core.app.utils import get_user_cache_directory
        from openbb_core.provider.utils.helpers import amake_request
        from openbb_sec.utils.definitions import HEADERS
        from openbb_sec.utils.helpers import symbol_map

        cik = await symbol_map(query.symbol, use_cache=query.use_cache)
        if not cik:
            raise OpenBBError(f"CIK not found for symbol '{query.symbol}'.")

        cik = str(cik).lstrip("0").zfill(10)
        url = (
            f"https://data.sec.gov/api/xbrl/companyconcept/"
            f"CIK{cik}/{query.taxonomy}/{query.fact}.json"
        )

        response: dict = {}
        if query.use_cache:
            cache_dir = f"{get_user_cache_directory()}/http/sec_xbrl_concept"
            async with CachedSession(
                cache=SQLiteBackend(cache_dir, expire_after=3600 * 24)
            ) as session:
                try:
                    await session.delete_expired_responses()
                    response = await amake_request(  # type: ignore
                        url, headers=HEADERS, session=session
                    )
                finally:
                    await session.close()
        else:
            response = await amake_request(url, headers=HEADERS)  # type: ignore

        if not response or not isinstance(response, dict):
            raise OpenBBError(
                f"No XBRL data returned for {query.symbol} / {query.fact}."
            )

        return response

    @staticmethod
    def transform_data(
        query: SecXbrlCompanyConceptQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[SecXbrlCompanyConceptData]:
        """Transform the raw XBRL JSON into SecXbrlCompanyConceptData records."""
        # pylint: disable=import-outside-toplevel
        from datetime import datetime

        if not data:
            raise EmptyDataError("No XBRL concept data was returned.")

        cik = str(data.get("cik", ""))
        entity_name = data.get("entityName")
        label = data.get("label")
        taxonomy = query.taxonomy
        tag = query.fact

        units_block = data.get("units", {})
        unit_key = query.unit

        # Fall back to the first available unit key if the requested one is not present
        if unit_key not in units_block and units_block:
            unit_key = next(iter(units_block))

        unit_data = units_block.get(unit_key, [])

        if not unit_data:
            raise EmptyDataError(
                f"No data found for unit '{query.unit}' in concept '{query.fact}'."
            )

        def _parse_date(val: str | None) -> dateType | None:
            if not val:
                return None
            try:
                return datetime.strptime(val, "%Y-%m-%d").date()
            except ValueError:
                return None

        results: list[SecXbrlCompanyConceptData] = []
        for row in unit_data:
            record = SecXbrlCompanyConceptData(
                cik=cik,
                name=entity_name,
                label=label,
                taxonomy=taxonomy,
                tag=tag,
                unit=unit_key,
                start_date=_parse_date(row.get("start")),
                end_date=_parse_date(row.get("end")),
                value=row.get("val"),
                accession=row.get("accn"),
                fiscal_year=row.get("fy"),
                fiscal_period=row.get("fp"),
                form=row.get("form"),
                filed=_parse_date(row.get("filed")),
                frame=row.get("frame"),
            )
            results.append(record)

        return results
