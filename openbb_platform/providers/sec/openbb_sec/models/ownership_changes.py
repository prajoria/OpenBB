"""SEC Ownership Changes Model — Quarter-over-Quarter Position Deltas."""

# pylint: disable=unused-argument

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator


class SecOwnershipChangesQueryParams(QueryParams):
    """SEC Ownership Changes Query — QoQ 13F Position Deltas.

    Source: https://efts.sec.gov/LATEST/search-index (13F-HR filings)

    Compares institutional 13F-HR holdings for two consecutive quarters and
    reports quarter-over-quarter position changes for a given ticker.
    """

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))
    date: dateType | None = Field(
        default=None,
        description=(
            QUERY_DESCRIPTIONS.get("date", "")
            + " The most-recent quarter to compare. "
            "Defaults to the last complete calendar quarter."
        ),
    )
    compare_date: dateType | None = Field(
        default=None,
        description=(
            "The prior quarter to compare against. "
            "Defaults to one quarter before `date`."
        ),
    )
    min_value: int = Field(
        default=0,
        description=(
            "Minimum holding value ($000s) to include in results. "
            "Filters out very small positions. Defaults to 0."
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


class SecOwnershipChangesData(Data):
    """SEC Ownership Changes Data — QoQ 13F Position Delta.

    Each row represents one institutional filer's position change for the
    target security between two consecutive 13F reporting quarters.
    """

    filer_name: str | None = Field(
        default=None,
        description="Name of the institutional filer.",
    )
    filer_cik: str | None = Field(
        default=None,
        description="CIK number of the institutional filer.",
    )
    period_ending: dateType | None = Field(
        default=None,
        description="End-of-quarter date of the current (most recent) 13F-HR filing.",
    )
    prior_period: dateType | None = Field(
        default=None,
        description="End-of-quarter date of the prior 13F-HR filing.",
    )
    shares: int | None = Field(
        default=None,
        description="Number of shares (or principal units) held in the current quarter.",
    )
    prior_shares: int | None = Field(
        default=None,
        description="Number of shares (or principal units) held in the prior quarter.",
    )
    change_shares: int | None = Field(
        default=None,
        description="Change in shares from the prior quarter (positive = increased).",
    )
    change_pct: float | None = Field(
        default=None,
        description="Percentage change in shares from the prior quarter.",
        json_schema_extra={
            "x-unit_measurement": "percent",
            "x-frontend_multiply": 100,
        },
    )
    value: int | None = Field(
        default=None,
        description="Fair market value of the current holding ($000s).",
    )
    action: Literal["New", "Increased", "Decreased", "Closed", "Unchanged"] | None = Field(
        default=None,
        description=(
            "Change action classification: "
            "'New' = appeared this quarter; "
            "'Increased' = position grew; "
            "'Decreased' = position shrank; "
            "'Closed' = position exited; "
            "'Unchanged' = no change."
        ),
    )


def _quarter_offset(quarter_end_str: str, quarters: int = -1) -> str:
    """Return a quarter-end date offset by `quarters` quarters from the given date."""
    from pandas import to_datetime  # pylint: disable=import-outside-toplevel
    from pandas.tseries.offsets import QuarterEnd  # pylint: disable=import-outside-toplevel

    dt = to_datetime(quarter_end_str)
    # Move by N quarters
    shifted = dt + quarters * QuarterEnd()
    # Snap to the actual quarter-end
    snapped = (shifted.to_period("Q").to_timestamp("D") + QuarterEnd()).date()
    return snapped.strftime("%Y-%m-%d")


class SecOwnershipChangesFetcher(
    Fetcher[SecOwnershipChangesQueryParams, list[SecOwnershipChangesData]]
):
    """SEC Ownership Changes Fetcher — QoQ 13F Position Deltas."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> SecOwnershipChangesQueryParams:
        """Transform the query params."""
        return SecOwnershipChangesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecOwnershipChangesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract holdings for the current and prior quarter via Form13FHoldings logic."""
        # pylint: disable=import-outside-toplevel
        from datetime import date, timedelta

        from openbb_sec.models.form_13f_holdings import SecForm13FHoldingsFetcher
        from openbb_sec.utils.parse_13f import date_to_quarter_end

        # ---- Resolve the current quarter-end date --------------------------------
        if query.date is not None:
            current_qe = date_to_quarter_end(query.date.strftime("%Y-%m-%d"))
        else:
            from pandas import to_datetime  # type: ignore
            from pandas.tseries.offsets import QuarterEnd  # type: ignore

            today = date.today()
            current_qe = (
                (to_datetime(today - timedelta(days=1)).to_period("Q").to_timestamp("D") + QuarterEnd())
                .date()
                .strftime("%Y-%m-%d")
            )

        # ---- Resolve the prior quarter-end date ----------------------------------
        if query.compare_date is not None:
            prior_qe = date_to_quarter_end(
                query.compare_date.strftime("%Y-%m-%d")
            )
        else:
            prior_qe = _quarter_offset(current_qe, quarters=-1)

        # ---- Fetch holdings for both quarters ------------------------------------
        fetcher = SecForm13FHoldingsFetcher()
        from datetime import datetime as _dt

        current_params: dict[str, Any] = {
            "symbol": query.symbol,
            "date": _dt.strptime(current_qe, "%Y-%m-%d").date(),
            "limit": query.limit,
            "use_cache": query.use_cache,
        }
        prior_params: dict[str, Any] = {
            "symbol": query.symbol,
            "date": _dt.strptime(prior_qe, "%Y-%m-%d").date(),
            "limit": query.limit,
            "use_cache": query.use_cache,
        }

        import asyncio

        async def _safe_fetch(params: dict) -> list:
            try:
                raw = await fetcher.fetch_data(params, credentials or {})
                return [r.model_dump() for r in raw]  # type: ignore
            except Exception:  # pylint: disable=broad-except
                return []

        current_holdings, prior_holdings = await asyncio.gather(
            _safe_fetch(current_params),
            _safe_fetch(prior_params),
        )

        return {
            "current": current_holdings,
            "prior": prior_holdings,
            "current_qe": current_qe,
            "prior_qe": prior_qe,
        }

    @staticmethod
    def transform_data(
        query: SecOwnershipChangesQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[SecOwnershipChangesData]:
        """Join current and prior quarter holdings and compute QoQ deltas."""
        if not data:
            raise EmptyDataError("No holdings data returned.")

        current_holdings: list[dict] = data.get("current", [])
        prior_holdings: list[dict] = data.get("prior", [])
        current_qe: str = data.get("current_qe", "")
        prior_qe: str = data.get("prior_qe", "")

        from datetime import datetime

        current_date = (
            datetime.strptime(current_qe, "%Y-%m-%d").date() if current_qe else None
        )
        prior_date = (
            datetime.strptime(prior_qe, "%Y-%m-%d").date() if prior_qe else None
        )

        # ---- Build lookup dict keyed by filer_cik --------------------------------
        prior_map: dict[str, dict] = {
            r["filer_cik"]: r for r in prior_holdings if r.get("filer_cik")
        }
        current_map: dict[str, dict] = {
            r["filer_cik"]: r for r in current_holdings if r.get("filer_cik")
        }

        # All unique filer CIKs across both quarters
        all_ciks = set(current_map.keys()) | set(prior_map.keys())

        results: list[SecOwnershipChangesData] = []

        for cik in all_ciks:
            curr = current_map.get(cik)
            prev = prior_map.get(cik)

            curr_shares = int(curr.get("principal_amount") or 0) if curr else None
            prev_shares = int(prev.get("principal_amount") or 0) if prev else None
            curr_value = int(curr.get("value") or 0) if curr else None

            if curr_value is not None and curr_value < query.min_value:
                continue

            # Classify the change action
            if curr is None:
                action = "Closed"
                change_shares = -(prev_shares or 0)
                change_pct = -1.0
                filer_name = prev.get("filer_name") if prev else None  # type: ignore
            elif prev is None:
                action = "New"
                change_shares = curr_shares or 0
                change_pct = None
                filer_name = curr.get("filer_name")
            else:
                filer_name = curr.get("filer_name")
                delta = (curr_shares or 0) - (prev_shares or 0)
                change_shares = delta
                if prev_shares and prev_shares != 0:
                    change_pct = round(delta / prev_shares, 6)
                else:
                    change_pct = None

                if delta > 0:
                    action = "Increased"
                elif delta < 0:
                    action = "Decreased"
                else:
                    action = "Unchanged"

            results.append(
                SecOwnershipChangesData(
                    filer_name=filer_name,
                    filer_cik=cik,
                    period_ending=current_date if curr else None,
                    prior_period=prior_date if prev else None,
                    shares=curr_shares,
                    prior_shares=prev_shares,
                    change_shares=change_shares,
                    change_pct=change_pct,
                    value=curr_value,
                    action=action,  # type: ignore
                )
            )

        if not results:
            raise EmptyDataError(
                f"No ownership change data found for '{query.symbol}'."
            )

        return sorted(
            results,
            key=lambda r: abs(r.change_shares or 0),
            reverse=True,
        )
