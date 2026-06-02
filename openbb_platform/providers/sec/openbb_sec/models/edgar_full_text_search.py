"""SEC EDGAR Full-Text Search Model."""

# pylint: disable=unused-argument

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field


class SecEdgarFullTextSearchQueryParams(QueryParams):
    """SEC EDGAR Full-Text Search Query.

    Source: https://efts.sec.gov/LATEST/search-index

    Performs keyword search across all historical SEC EDGAR filings using the
    EDGAR full-text search API.  No API key is required.
    """

    query: str = Field(description="Search query string.")
    forms: str | None = Field(
        default=None,
        description=(
            "Comma-separated list of SEC form types to filter by "
            "(e.g. '10-K,10-Q'). Defaults to all form types."
        ),
    )
    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )
    limit: int = Field(
        default=40,
        description=QUERY_DESCRIPTIONS.get("limit", "")
        + " Maximum 1000. Defaults to 40.",
    )


class SecEdgarFullTextSearchData(Data):
    """SEC EDGAR Full-Text Search Data."""

    filing_date: str | None = Field(
        default=None, description="Date the filing was submitted to the SEC."
    )
    period_ending: str | None = Field(
        default=None, description="End date of the period covered by the filing."
    )
    symbol: str | None = Field(
        default=None,
        description="Ticker symbol(s) associated with the filing entity.",
    )
    name: str | None = Field(
        default=None, description="Name of the filing entity."
    )
    cik: str | None = Field(
        default=None, description="Central Index Key of the filing entity."
    )
    form_type: str | None = Field(
        default=None, description="SEC form type (e.g. '10-K', '8-K')."
    )
    description: str | None = Field(
        default=None, description="Description of the filing."
    )
    accession_number: str | None = Field(
        default=None, description="SEC accession number for the filing."
    )
    url: str | None = Field(
        default=None, description="URL to the primary document."
    )
    index_headers_url: str | None = Field(
        default=None, description="URL to the filing index headers."
    )
    complete_submission_url: str | None = Field(
        default=None, description="URL to the complete submission text file."
    )


class SecEdgarFullTextSearchFetcher(
    Fetcher[
        SecEdgarFullTextSearchQueryParams, list[SecEdgarFullTextSearchData]
    ]
):
    """SEC EDGAR Full-Text Search Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecEdgarFullTextSearchQueryParams:
        """Transform the query params."""
        return SecEdgarFullTextSearchQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecEdgarFullTextSearchQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract filings from the EDGAR full-text search API."""
        # pylint: disable=import-outside-toplevel
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_core.provider.utils.helpers import amake_request
        from warnings import warn

        SEARCH_HEADERS = {
            "User-Agent": "my real company name definitelynot@fakecompany.com",
            "Accept-Encoding": "gzip, deflate",
        }

        limit = min(query.limit, 1000)
        batch = 100

        # Build date range fragment
        date_fragment = ""
        if query.start_date or query.end_date:
            date_fragment = "&dateRange=custom"
            if query.start_date:
                date_fragment += f"&startdt={query.start_date}"
            if query.end_date:
                date_fragment += f"&enddt={query.end_date}"

        forms_fragment = f"&forms={query.forms}" if query.forms else ""

        def build_url(offset: int, count: int) -> str:
            return (
                "https://efts.sec.gov/LATEST/search-index"
                f"?q={query.query}"
                f"{forms_fragment}"
                f"{date_fragment}"
                f"&from={offset}&count={count}"
            )

        results: list[dict] = []
        offset = 0

        try:
            response = await amake_request(
                build_url(0, min(batch, limit)), headers=SEARCH_HEADERS
            )
        except Exception as e:  # pylint: disable=broad-except
            raise OpenBBError(f"EDGAR full-text search request failed: {e}") from e

        if not isinstance(response, dict):
            raise OpenBBError(
                f"Unexpected response type: {type(response).__name__}"
            )

        hits = response.get("hits", {})
        total = hits.get("total", {}).get("value", 0)
        batch_hits = hits.get("hits", [])
        results.extend(batch_hits)
        offset += len(batch_hits)

        while offset < min(total, limit):
            try:
                response = await amake_request(
                    build_url(offset, min(batch, limit - offset)),
                    headers=SEARCH_HEADERS,
                )
            except Exception as e:  # pylint: disable=broad-except
                warn(f"Failed to retrieve page at offset {offset}: {e}")
                break

            hits = response.get("hits", {})  # type: ignore
            batch_hits = hits.get("hits", [])
            if not batch_hits:
                break
            results.extend(batch_hits)
            offset += len(batch_hits)

        if not results:
            raise EmptyDataError(
                f"No results returned for query '{query.query}'."
            )

        return results

    @staticmethod
    def transform_data(
        query: SecEdgarFullTextSearchQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[SecEdgarFullTextSearchData]:
        """Transform raw EDGAR search hits into SecEdgarFullTextSearchData records."""
        results: list[SecEdgarFullTextSearchData] = []
        seen: set = set()

        for entry in data:
            src = entry.get("_source", {})
            _id = entry.get("_id", "")
            ciks = src.get("ciks", [])
            display_names = src.get("display_names", [])

            names: list[str] = []
            tickers: list[str] = []
            for dn in display_names:
                if "(" in dn and ")" in dn:
                    ticker = dn.split("(")[1].split(")")[0].strip()
                    name = dn.split("(")[0].strip()
                else:
                    ticker = ""
                    name = dn.strip()
                tickers.append(ticker)
                names.append(name)

            adsh = src.get("adsh", "")
            root_url = ""
            if ciks and adsh:
                root_url = (
                    "https://www.sec.gov/Archives/edgar/data/"
                    + ciks[0]
                    + "/"
                    + adsh.replace("-", "")
                    + "/"
                )

            primary_doc_url = (root_url + _id.split(":")[1]) if ":" in _id and root_url else None
            index_headers_url = (
                root_url + _id.split(":")[0] + "-index-headers.html"
                if ":" in _id and root_url
                else None
            )
            complete_submission_url = (
                root_url + _id.split(":")[0] + ".txt"
                if ":" in _id and root_url
                else None
            )

            record = {
                "filing_date": src.get("file_date"),
                "period_ending": src.get("period_ending"),
                "symbol": ",".join(t for t in tickers if t).replace(" ", "") or None,
                "name": ",".join(names) or None,
                "cik": ",".join(ciks) if ciks else None,
                "form_type": src.get("form"),
                "description": src.get("file_description"),
                "accession_number": adsh or None,
                "url": primary_doc_url,
                "index_headers_url": index_headers_url,
                "complete_submission_url": complete_submission_url,
            }

            key = record.get("url") or record.get("accession_number") or str(record)
            if key not in seen:
                seen.add(key)
                results.append(SecEdgarFullTextSearchData.model_validate(record))

        return results
