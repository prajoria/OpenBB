"""SEC Entity Info Model."""

# pylint: disable=unused-argument

from typing import Any

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_info import (
    EquityInfoData,
    EquityInfoQueryParams,
)
from pydantic import Field


class SecEntityInfoQueryParams(EquityInfoQueryParams):
    """SEC Entity Info Query.

    Source: https://data.sec.gov/submissions/
    """

    symbol: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Ticker symbol of the company. Either symbol or cik must be provided.",
    )
    cik: str | None = Field(
        default=None,
        description="CIK number of the company. Either symbol or cik must be provided.",
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use cache for the request. Defaults to True.",
    )


class SecEntityInfoData(EquityInfoData):
    """SEC Entity Info Data.

    Full entity metadata from the EDGAR submissions API.
    """

    symbol: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Primary ticker symbol(s) of the company.",
    )
    entity_type: str | None = Field(
        default=None,
        description="The SEC entity type (e.g. 'operating', 'investment company').",
    )
    sic: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Standard Industrial Classification code.",
    )
    sic_description: str | None = Field(
        default=None,
        description="Human-readable description of the SIC code.",
    )
    ein: str | None = Field(
        default=None,
        description="IRS Employer Identification Number.",
    )
    lei: str | None = Field(  # type: ignore[assignment]
        default=None,
        description="Legal Entity Identifier.",
    )
    description: str | None = Field(
        default=None,
        description="Business description of the company.",
    )
    website: str | None = Field(
        default=None,
        description="Company website URL.",
    )
    investor_website: str | None = Field(
        default=None,
        description="Investor relations website URL.",
    )
    category: str | None = Field(
        default=None,
        description="SEC filer category (e.g. 'Large accelerated filer').",
    )
    fiscal_year_end: str | None = Field(
        default=None,
        description="Month and day of fiscal year end (e.g. '1231' for December 31).",
    )
    state_of_incorporation: str | None = Field(
        default=None,
        description="Two-letter state code where the company is incorporated.",
    )
    state_of_incorporation_description: str | None = Field(
        default=None,
        description="Full name of the state where the company is incorporated.",
    )
    phone: str | None = Field(
        default=None,
        description="Company phone number.",
    )
    mailing_street: str | None = Field(
        default=None,
        description="Mailing address street.",
    )
    mailing_city: str | None = Field(
        default=None,
        description="Mailing address city.",
    )
    mailing_state: str | None = Field(
        default=None,
        description="Mailing address state.",
    )
    mailing_zip: str | None = Field(
        default=None,
        description="Mailing address ZIP code.",
    )
    business_street: str | None = Field(
        default=None,
        description="Business address street.",
    )
    business_city: str | None = Field(
        default=None,
        description="Business address city.",
    )
    business_state: str | None = Field(
        default=None,
        description="Business address state.",
    )
    business_zip: str | None = Field(
        default=None,
        description="Business address ZIP code.",
    )
    tickers: str | None = Field(
        default=None,
        description="Comma-separated list of ticker symbols associated with the entity.",
    )
    exchanges: str | None = Field(
        default=None,
        description="Comma-separated list of exchanges where the entity is listed.",
    )
    former_names: str | None = Field(
        default=None,
        description="JSON-like string of former company names and the dates they changed.",
    )
    flags: str | None = Field(
        default=None,
        description="SEC flags associated with the entity.",
    )


class SecEntityInfoFetcher(
    Fetcher[SecEntityInfoQueryParams, list[SecEntityInfoData]]
):
    """SEC Entity Info Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> SecEntityInfoQueryParams:
        """Transform the query params."""
        return SecEntityInfoQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecEntityInfoQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract entity metadata from the SEC EDGAR submissions API."""
        # pylint: disable=import-outside-toplevel
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_sec.utils.helpers import get_entity_submissions, symbol_map

        if not query.symbol and not query.cik:
            raise OpenBBError("Either symbol or cik must be provided.")

        cik = query.cik
        if not cik and query.symbol:
            cik = await symbol_map(query.symbol, use_cache=query.use_cache)
        if not cik:
            raise OpenBBError(
                f"CIK not found for symbol '{query.symbol}'."
            )

        # Ensure 10-digit zero-padded CIK
        cik = str(cik).lstrip("0").zfill(10)

        data = await get_entity_submissions(cik, use_cache=query.use_cache)
        return [data]  # type: ignore

    @staticmethod
    def transform_data(
        query: SecEntityInfoQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[SecEntityInfoData]:
        """Transform the raw EDGAR entity JSON into SecEntityInfoData records."""
        if not data:
            return []

        raw = data[0]
        addresses = raw.get("addresses", {})
        mailing = addresses.get("mailing", {})
        business = addresses.get("business", {})

        # Flatten tickers / exchanges lists into comma-separated strings
        tickers_list = raw.get("tickers", [])
        exchanges_list = raw.get("exchanges", [])
        former_names_list = raw.get("formerNames", [])

        record = {
            "cik": str(raw.get("cik", "")),
            "name": raw.get("name"),
            "entity_type": raw.get("entityType"),
            "sic": raw.get("sic"),
            "sic_description": raw.get("sicDescription"),
            "ein": raw.get("ein"),
            "lei": raw.get("lei"),
            "description": raw.get("description"),
            "website": raw.get("website"),
            "investor_website": raw.get("investorWebsite"),
            "category": raw.get("category"),
            "fiscal_year_end": raw.get("fiscalYearEnd"),
            "state_of_incorporation": raw.get("stateOfIncorporation"),
            "state_of_incorporation_description": raw.get(
                "stateOfIncorporationDescription"
            ),
            "phone": raw.get("phone"),
            "mailing_street": mailing.get("street1"),
            "mailing_city": mailing.get("city"),
            "mailing_state": mailing.get("stateOrCountry"),
            "mailing_zip": mailing.get("zipCode"),
            "business_street": business.get("street1"),
            "business_city": business.get("city"),
            "business_state": business.get("stateOrCountry"),
            "business_zip": business.get("zipCode"),
            "symbol": ",".join(tickers_list) if tickers_list else None,
            "tickers": ",".join(tickers_list) if tickers_list else None,
            "exchanges": ",".join(exchanges_list) if exchanges_list else None,
            "former_names": str(former_names_list) if former_names_list else None,
            "flags": raw.get("flags"),
        }

        return [SecEntityInfoData.model_validate(record)]
