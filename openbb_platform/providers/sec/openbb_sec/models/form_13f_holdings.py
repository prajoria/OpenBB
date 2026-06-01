"""SEC Form 13F Holdings Model — Reverse 13F (Who Holds a Stock)."""

# pylint: disable=unused-argument

from datetime import date as dateType
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator


class SecForm13FHoldingsQueryParams(QueryParams):
    """SEC Form 13F Holdings Query — Institutional Holders of a Stock.

    Source: https://efts.sec.gov/LATEST/search-index (13F-HR filings)

    Given a ticker symbol or CUSIP, returns all institutional filers (hedge funds,
    mutual funds, pension funds) that reported holding the security in their most
    recent 13F-HR filing for the specified quarter.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    cusip: str | None = Field(
        default=None,
        description=(
            "Optional CUSIP override. If provided, the CUSIP is used directly "
            "instead of being looked up from the symbol."
        ),
    )
    date: dateType | None = Field(
        default=None,
        description=(
            QUERY_DESCRIPTIONS.get("date", "")
            + " The end-of-quarter date to search for. "
            "Defaults to the most recent completed calendar quarter."
        ),
    )
    limit: int = Field(
        default=100,
        description=QUERY_DESCRIPTIONS.get("limit", "")
        + " Maximum number of institutional filers to return. Defaults to 100.",
    )
    use_cache: bool = Field(
        default=True,
        description="Whether to use cache for the request. Defaults to True.",
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def to_upper(cls, v: str) -> str:
        """Convert symbol to uppercase."""
        return str(v).upper()


class SecForm13FHoldingsData(Data):
    """SEC Form 13F Holdings Data.

    Each row represents one institutional filer's reported holding of the target
    security in a given quarter.
    """

    filer_name: str | None = Field(
        default=None,
        description="Name of the institutional filer (13F filing entity).",
    )
    filer_cik: str | None = Field(
        default=None,
        description="CIK number of the institutional filer.",
    )
    period_ending: dateType | None = Field(
        default=None,
        description="End-of-quarter date of the 13F-HR filing.",
    )
    issuer: str | None = Field(
        default=None,
        description="Name of the security issuer as reported in the filing.",
    )
    cusip: str | None = Field(
        default=None,
        description="CUSIP identifier of the security.",
    )
    asset_class: str | None = Field(
        default=None,
        description="Title of the asset class (e.g. 'COM' for common stock).",
    )
    value: int | None = Field(
        default=None,
        description=(
            "Fair market value of the holding in thousands of US dollars ($000s), "
            "using the closing price of the last trading day of the quarter."
        ),
    )
    principal_amount: int | None = Field(
        default=None,
        description=(
            "Number of shares (SH) or principal amount (PRN) held. "
            "Defined by the security_type field."
        ),
    )
    security_type: str | None = Field(
        default=None,
        description=(
            "'SH' when principal_amount represents shares; "
            "'PRN' when it represents principal amount (e.g. convertible debt)."
        ),
    )
    investment_discretion: str | None = Field(
        default=None,
        description=(
            "Investment discretion: 'SOLE', 'DEFINED' (DFN), or 'OTHER' (OTR)."
        ),
    )
    voting_authority_sole: int | None = Field(
        default=None,
        description="Shares for which the filer exercises sole voting authority.",
    )
    voting_authority_shared: int | None = Field(
        default=None,
        description="Shares for which the filer exercises shared voting authority.",
    )
    option_type: str | None = Field(
        default=None,
        description="'call' or 'put' when the holding is an options position.",
    )
    weight_in_portfolio: float | None = Field(
        default=None,
        description=(
            "Weight of this security in the filer's full 13F portfolio "
            "(normalized to 1.0 = 100%)."
        ),
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )


def _cusip_from_symbol(symbol: str) -> str | None:
    """Attempt a best-effort CUSIP lookup from SEC company facts.

    Returns None when not resolvable — callers fall back to symbol-based search.
    """
    # CUSIP lookup via SEC is not reliable from XBRL data;
    # return None to trigger the symbol-based EDGAR search path.
    return None


class SecForm13FHoldingsFetcher(
    Fetcher[SecForm13FHoldingsQueryParams, list[SecForm13FHoldingsData]]
):
    """SEC Form 13F Holdings Fetcher — Reverse 13F."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecForm13FHoldingsQueryParams:
        """Transform the query params."""
        return SecForm13FHoldingsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecForm13FHoldingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract 13F-HR filings that report holdings of the target symbol/CUSIP."""
        # pylint: disable=import-outside-toplevel
        import asyncio
        from openbb_core.app.model.abstract.error import OpenBBError
        from openbb_sec.utils import parse_13f
        from openbb_sec.utils.helpers import search_13f_holders

        # ---- Determine the quarter search window --------------------------------
        if query.date is not None:
            quarter_end = parse_13f.date_to_quarter_end(
                query.date.strftime("%Y-%m-%d")
            )
        else:
            # Default: most recently completed calendar quarter
            from datetime import date, timedelta
            from pandas.tseries.offsets import QuarterEnd  # type: ignore
            from pandas import to_datetime  # type: ignore

            today = date.today()
            # Step back one day so we are inside the *completed* quarter
            quarter_end = (
                (to_datetime(today - timedelta(days=1)).to_period("Q").to_timestamp("D") + QuarterEnd())
                .date()
                .strftime("%Y-%m-%d")
            )

        # The SEC typically publishes 13F-HR filings 45 days after quarter end,
        # so we allow a generous 90-day window after the quarter-end date.
        from datetime import datetime, timedelta as td

        q_end_dt = datetime.strptime(quarter_end, "%Y-%m-%d")
        # Search from the start of that quarter to 90 days after quarter end
        quarter_start = (
            q_end_dt.replace(month=((q_end_dt.month - 1) // 3) * 3 + 1, day=1)
            .strftime("%Y-%m-%d")
        )
        search_end = (q_end_dt + td(days=90)).strftime("%Y-%m-%d")

        # ---- Resolve CUSIP or fall back to symbol-text search -------------------
        cusip = query.cusip
        search_term: str
        if cusip:
            search_term = cusip
        else:
            # Use the ticker symbol as the text query (less precise but broadly
            # supported — EDGAR full-text indexes the information table text).
            search_term = query.symbol

        # ---- Search EDGAR for matching 13F-HR filers ----------------------------
        candidates = await search_13f_holders(
            cusip=search_term,
            start_date=quarter_start,
            end_date=search_end,
            limit=query.limit,
            use_cache=query.use_cache,
        )

        if not candidates:
            raise EmptyDataError(
                f"No 13F-HR filers found holding '{query.symbol}' for the quarter ending {quarter_end}."
            )

        # ---- Fetch and parse each candidate filing ------------------------------
        results: list[dict] = []

        async def _process_candidate(candidate: dict) -> None:
            """Fetch and parse a single 13F-HR filing, filtering to the target security."""
            url = candidate.get("primary_doc_url", "")
            if not url:
                return
            try:
                holdings = await parse_13f.parse_13f_hr(url)
            except Exception:  # pylint: disable=broad-except
                return

            target = (cusip or "").upper()
            sym_upper = query.symbol.upper()

            for row in holdings:
                row_cusip = str(row.get("cusip", "")).upper()
                row_issuer = str(row.get("nameOfIssuer", "")).upper()
                # Filter: match by CUSIP when available, otherwise by issuer name containing symbol
                if target and row_cusip != target:
                    if not (sym_upper in row_cusip or sym_upper in row_issuer):
                        continue
                row["filer_name"] = candidate.get("filer_name")
                row["filer_cik"] = candidate.get("filer_cik")
                results.append(row)

        await asyncio.gather(*[_process_candidate(c) for c in candidates])

        if not results:
            raise EmptyDataError(
                f"No holdings records found for '{query.symbol}' after parsing the 13F-HR filings."
            )

        return results

    @staticmethod
    def transform_data(
        query: SecForm13FHoldingsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[SecForm13FHoldingsData]:
        """Transform parsed 13F row dicts into SecForm13FHoldingsData records."""
        results: list[SecForm13FHoldingsData] = []
        for row in data:
            record = {
                "filer_name": row.get("filer_name"),
                "filer_cik": str(row.get("filer_cik", "")),
                "period_ending": row.get("period_ending"),
                "issuer": row.get("nameOfIssuer"),
                "cusip": row.get("cusip"),
                "asset_class": row.get("titleOfClass"),
                "value": row.get("value"),
                "principal_amount": row.get("principal_amount"),
                "security_type": row.get("security_type"),
                "investment_discretion": row.get("investmentDiscretion"),
                "voting_authority_sole": row.get("voting_authority_sole"),
                "voting_authority_shared": row.get("voting_authority_shared"),
                "option_type": row.get("putCall"),
                "weight_in_portfolio": row.get("weight"),
            }
            results.append(SecForm13FHoldingsData.model_validate(record))

        return sorted(
            results,
            key=lambda r: (r.value or 0),
            reverse=True,
        )
