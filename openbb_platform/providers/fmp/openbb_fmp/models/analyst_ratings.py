"""FMP analyst / ratings endpoints — 6 symbol-parameterized fetchers.

Port of the ``fmp_cached`` analyst-ratings drain (#1057-#1063) to the
plain ``fmp`` provider under Tier-A parity (#1482 #1483 #1484 #1485
#1486 #1487). #1481 (AnalystRecommendations) is intentionally omitted
because FMP retired ``/stable/analyst-stock-recommendations`` — see
follow-up on #1481 for the aggregation-over-grades path.

Endpoints ported:
- ``ratings-snapshot``          (#1487) — current multi-factor rating
- ``ratings-historical``        (#1486) — daily rating history
- ``price-target-summary``      (#1485) — analyst target rollup
- ``grades``                    (#1482) — individual analyst grade changes
- ``grades-historical``         (#1484) — rollup counts by rating tier
- ``grades-consensus``          (#1483) — current consensus buy/hold/sell counts

Design note: unlike the ``fmp_cached`` copies these do NOT cache. Every
call hits ``financialmodelingprep.com/stable/<endpoint>`` live. Caching
is the ``fmp_cached`` provider's job by design (see repo CLAUDE.md
"Provider rule").
"""

# pylint: disable=unused-argument

from __future__ import annotations

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_core.provider.utils.helpers import amake_request
from pydantic import ConfigDict, Field

_FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"


# ---------------------------------------------------------------------------
# Shared query params — every one of these six endpoints takes just ``symbol``.
# ---------------------------------------------------------------------------


class FMPSymbolQueryParams(QueryParams):
    """Symbol-only query parameters shared across the six analyst endpoints."""

    symbol: str = Field(description="Ticker symbol.")


# ---------------------------------------------------------------------------
# Data models. Use ``extra=allow`` so a schema drift on FMP's side (they add
# a new scoring column) doesn't break the fetcher for the fields we DO map.
# ---------------------------------------------------------------------------


class FMPRatingsSnapshotData(Data):
    """Row from ``/stable/ratings-snapshot`` — multi-factor scoring rollup."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    rating: str | None = Field(default=None, description="Letter grade (A-F).")
    overall_score: int | None = Field(default=None, description="Composite 1-5.")


class FMPRatingsHistoricalData(Data):
    """Row from ``/stable/ratings-historical`` — daily rating history."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Snapshot date YYYY-MM-DD.")
    rating: str | None = Field(default=None, description="Letter grade.")


class FMPPriceTargetSummaryData(Data):
    """Row from ``/stable/price-target-summary`` — count + average rollup."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")


class FMPGradesData(Data):
    """Row from ``/stable/grades`` — individual analyst grade change."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Change date YYYY-MM-DD.")
    grading_company: str | None = Field(default=None, description="Analyst firm.")
    previous_grade: str | None = Field(default=None, description="Prior grade.")
    new_grade: str | None = Field(default=None, description="New grade.")
    action: str | None = Field(default=None, description="Action taken.")


class FMPGradesHistoricalData(Data):
    """Row from ``/stable/grades-historical`` — rollup counts by rating tier."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    date: str = Field(description="Rollup date YYYY-MM-DD.")


class FMPGradesConsensusData(Data):
    """Row from ``/stable/grades-consensus`` — current consensus rollup."""

    model_config = ConfigDict(extra="allow")

    symbol: str = Field(description="Ticker symbol.")
    strong_buy: int | None = Field(default=None, description="Strong-buy count.")
    buy: int | None = Field(default=None, description="Buy count.")
    hold: int | None = Field(default=None, description="Hold count.")
    sell: int | None = Field(default=None, description="Sell count.")
    strong_sell: int | None = Field(default=None, description="Strong-sell count.")
    consensus: str | None = Field(default=None, description="Overall consensus label.")


# Shared FMP-camelCase → snake_case alias maps.
_RATINGS_ALIASES = {"overallScore": "overall_score"}
_GRADES_ALIASES = {
    "gradingCompany": "grading_company",
    "previousGrade": "previous_grade",
    "newGrade": "new_grade",
}
_CONSENSUS_ALIASES = {"strongBuy": "strong_buy", "strongSell": "strong_sell"}


# ---------------------------------------------------------------------------
# Fetch/transform helpers — one per endpoint keeps Fetcher[QueryParams,
# list[DataCls]] a concrete generic (OpenBB's RegistryMap._validate rejects
# bare ``list``).
# ---------------------------------------------------------------------------


async def _fmp_stable_get(
    path: str, symbol: str, credentials: dict[str, str] | None
) -> list[dict]:
    """GET ``/stable/<path>?symbol=<S>&apikey=<K>`` and return the JSON list.

    Routes the API key through ``params`` (not the URL) so it stays out of
    tracebacks and proxy logs. Raises ``EmptyDataError`` when FMP returns
    a non-list payload (typical for 402 / auth errors), which is the
    exception type the fmp provider convention uses.
    """
    api_key = (credentials or {}).get("fmp_api_key", "")
    url = f"{_FMP_STABLE_BASE}/{path}"
    params = {"symbol": symbol, "apikey": api_key}
    payload = await amake_request(url, params=params)
    if not isinstance(payload, list):
        raise EmptyDataError(
            f"{path}: unexpected response shape from FMP "
            f"(got {type(payload).__name__}; expected list)."
        )
    return payload


def _apply_aliases(rows: list[dict], alias_map: dict[str, str]) -> list[dict]:
    """Rename FMP-camelCase keys to snake_case per ``alias_map``."""
    return [{alias_map.get(k, k): v for k, v in row.items()} for row in rows]


# ---------------------------------------------------------------------------
# Fetcher classes. One per endpoint.
# ---------------------------------------------------------------------------


class FMPRatingsSnapshotFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPRatingsSnapshotData]]
):
    """Fetcher for ``/stable/ratings-snapshot`` (#1487)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("ratings-snapshot", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPRatingsSnapshotData]:
        """Map raw rows to typed model instances."""
        return [
            FMPRatingsSnapshotData.model_validate(r)
            for r in _apply_aliases(data, _RATINGS_ALIASES)
        ]


class FMPRatingsHistoricalFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPRatingsHistoricalData]]
):
    """Fetcher for ``/stable/ratings-historical`` (#1486)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("ratings-historical", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPRatingsHistoricalData]:
        """Map raw rows to typed model instances."""
        return [
            FMPRatingsHistoricalData.model_validate(r)
            for r in _apply_aliases(data, _RATINGS_ALIASES)
        ]


class FMPPriceTargetSummaryFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPPriceTargetSummaryData]]
):
    """Fetcher for ``/stable/price-target-summary`` (#1485)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("price-target-summary", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPPriceTargetSummaryData]:
        """Map raw rows to typed model instances."""
        return [FMPPriceTargetSummaryData.model_validate(r) for r in data]


class FMPGradesFetcher(Fetcher[FMPSymbolQueryParams, list[FMPGradesData]]):
    """Fetcher for ``/stable/grades`` (#1482)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("grades", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPGradesData]:
        """Map raw rows to typed model instances."""
        return [
            FMPGradesData.model_validate(r)
            for r in _apply_aliases(data, _GRADES_ALIASES)
        ]


class FMPGradesHistoricalFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPGradesHistoricalData]]
):
    """Fetcher for ``/stable/grades-historical`` (#1484)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("grades-historical", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPGradesHistoricalData]:
        """Map raw rows to typed model instances."""
        return [FMPGradesHistoricalData.model_validate(r) for r in data]


class FMPGradesConsensusFetcher(
    Fetcher[FMPSymbolQueryParams, list[FMPGradesConsensusData]]
):
    """Fetcher for ``/stable/grades-consensus`` (#1483)."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPSymbolQueryParams:
        """Coerce raw params dict to typed query."""
        return FMPSymbolQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPSymbolQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Live pass-through fetch by symbol."""
        return await _fmp_stable_get("grades-consensus", query.symbol, credentials)

    @staticmethod
    def transform_data(
        query: FMPSymbolQueryParams, data: list[dict], **kwargs: Any
    ) -> list[FMPGradesConsensusData]:
        """Map raw rows to typed model instances."""
        return [
            FMPGradesConsensusData.model_validate(r)
            for r in _apply_aliases(data, _CONSENSUS_ALIASES)
        ]
