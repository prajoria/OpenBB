"""Cached analyst_recommendations model (#997 / #1022).

Wraps FMP's ``/stable/grades`` endpoint (per-analyst grade timeline) and
aggregates it into a 5-bucket rating summary the Equity Profile widget
(#994 §5B) consumes.

Design (from #1021 spike):

- FMP retired ``/stable/analyst-stock-recommendations`` (404 on our tier
  as of 2026-07-21) so we hit ``/stable/grades`` and aggregate client-
  side. Storing the raw grade timeline is intentional — future widgets
  can render upgrade/downgrade rate, per-firm consensus history, etc.
- Table ``analyst_grades`` stores the raw per-firm rows keyed by
  ``(symbol, date, grading_company)``. ``ON DUPLICATE KEY UPDATE`` on
  insert handles re-fetch idempotency.
- ``transform_data`` returns a single-row summary bucketing the LATEST
  grade per firm into 5 categories via a fixed grade→bucket map.
  Oddball grades (firm-specific labels we haven't mapped) go into
  ``unknown_count`` and log a WARN so the map can be extended.
"""

# pylint: disable=import-outside-toplevel,broad-exception-caught
# pylint: disable=too-many-arguments,too-many-positional-arguments

from __future__ import annotations

import json
import logging
from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from pydantic import Field

from openbb_fmp_cached.utils.cache_schema import create_analyst_grades_table
from openbb_fmp_cached.utils.database import (
    execute_many,
    init_database,
)

logger = logging.getLogger(__name__)

_FMP_GRADES_URL = "https://financialmodelingprep.com/stable/grades"

# Grade → bucket map. Keys are lower-cased for lookup. Extend when we
# see WARN log lines for unmapped grades in production. Every mapping
# here is documented; do NOT add speculative entries.
_GRADE_TO_BUCKET: dict[str, str] = {
    # Strong Buy
    "strong buy": "strong_buy",
    "conviction buy": "strong_buy",
    "top pick": "strong_buy",
    # Buy
    "buy": "buy",
    "outperform": "buy",
    "overweight": "buy",
    "market outperform": "buy",
    "sector outperform": "buy",
    "positive": "buy",
    "accumulate": "buy",
    "add": "buy",
    "long-term buy": "buy",
    # Hold
    "hold": "hold",
    "neutral": "hold",
    "market perform": "hold",
    "sector perform": "hold",
    "equal-weight": "hold",
    "equal weight": "hold",
    "in-line": "hold",
    "in line": "hold",
    "peer perform": "hold",
    "perform": "hold",  # Cowen / Piper / Oppenheimer / BMO scale — market-perform equivalent
    "reduce": "hold",  # borderline — most firms mean "hold with caution"
    # Sell
    "sell": "sell",
    "underperform": "sell",
    "underweight": "sell",
    "market underperform": "sell",
    "sector underperform": "sell",
    "negative": "sell",
    "sell / short": "sell",
    # Strong Sell
    "strong sell": "strong_sell",
    "conviction sell": "strong_sell",
    "avoid": "strong_sell",
}

_BUCKETS = ("strong_buy", "buy", "hold", "sell", "strong_sell")


class FMPCachedAnalystRecommendationsQueryParams(QueryParams):
    """Query parameters for cached analyst recommendations aggregator."""

    symbol: str = Field(
        description=QUERY_DESCRIPTIONS.get("symbol", "Symbol to query.")
    )


class FMPCachedAnalystRecommendationsData(Data):
    """Aggregated rating distribution for a single symbol.

    Values are counts of distinct analyst firms in each bucket, using
    each firm's LATEST recorded grade for the symbol.
    """

    symbol: str = Field(description="Symbol.")
    as_of: str = Field(description="Date of the latest grade row folded in (ISO-8601).")
    strong_buy: int = Field(
        default=0, description="# firms with Strong Buy or equivalent."
    )
    buy: int = Field(
        default=0, description="# firms with Buy / Outperform / Overweight."
    )
    hold: int = Field(
        default=0, description="# firms with Hold / Neutral / Market Perform."
    )
    sell: int = Field(
        default=0, description="# firms with Sell / Underperform / Underweight."
    )
    strong_sell: int = Field(default=0, description="# firms with Strong Sell.")
    unknown_count: int = Field(
        default=0,
        description="# firms whose latest grade string is unmapped (logged at WARN).",
    )
    total: int = Field(default=0, description="Total distinct firms.")


class FMPCachedAnalystRecommendationsFetcher(
    Fetcher[
        FMPCachedAnalystRecommendationsQueryParams,
        list[FMPCachedAnalystRecommendationsData],
    ]
):
    """Fetcher that aggregates ``/stable/grades`` into a rating summary."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPCachedAnalystRecommendationsQueryParams:
        """Coerce a raw params dict into the typed query object."""
        return FMPCachedAnalystRecommendationsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedAnalystRecommendationsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch grade rows, cache them, return the raw payload."""
        resolved = _resolve_credentials(credentials)
        api_key = (resolved or {}).get("fmp_api_key")
        if not api_key:
            raise RuntimeError(
                "AnalystRecommendations: fmp_api_key not configured; "
                "set fmp_api_key or fmp_cached_api_key in user_settings.json"
            )

        # Try MySQL first. If DB is down / not configured, fall through
        # to a live fetch so widgets don't fail.
        try:
            init_database()
            create_analyst_grades_table()
        except Exception as exc:
            logger.warning(
                "AnalystRecommendations: cache init failed, using direct fetch: %s",
                exc,
            )
            return await _fetch_grades_live(query.symbol, api_key)

        rows = await _fetch_grades_live(query.symbol, api_key)
        if rows:
            _store_grades(query.symbol, rows)
        return rows

    @staticmethod
    def transform_data(
        query: FMPCachedAnalystRecommendationsQueryParams,
        data: list,
        **kwargs: Any,
    ) -> list[FMPCachedAnalystRecommendationsData]:
        """Aggregate raw grade rows into a single-row summary."""
        if not data:
            # Loud empty — return an all-zeros row rather than [] so the
            # widget renders a "no coverage" state instead of an error.
            return [
                FMPCachedAnalystRecommendationsData(
                    symbol=query.symbol,
                    as_of="",
                    total=0,
                )
            ]

        # Keep the latest grade per firm. FMP orders rows most-recent
        # first for a symbol, so first-seen wins; sort defensively anyway.
        sorted_rows = sorted(
            data,
            key=lambda r: (r.get("gradingCompany") or "", r.get("date") or ""),
            reverse=True,
        )
        latest_per_firm: dict[str, dict[str, Any]] = {}
        for row in sorted_rows:
            firm = row.get("gradingCompany")
            if not firm:
                continue
            if firm not in latest_per_firm:
                latest_per_firm[firm] = row

        counts = {b: 0 for b in _BUCKETS}
        unknown = 0
        for row in latest_per_firm.values():
            grade = (row.get("newGrade") or "").strip().lower()
            bucket = _GRADE_TO_BUCKET.get(grade)
            if bucket is None:
                unknown += 1
                logger.warning(
                    "AnalystRecommendations: unmapped grade %r from %r; "
                    "extend _GRADE_TO_BUCKET or log an issue.",
                    row.get("newGrade"),
                    row.get("gradingCompany"),
                )
            else:
                counts[bucket] += 1

        # as_of = max date across all rows we saw.
        as_of = max((r.get("date") or "" for r in data), default="")
        return [
            FMPCachedAnalystRecommendationsData(
                symbol=query.symbol,
                as_of=as_of,
                strong_buy=counts["strong_buy"],
                buy=counts["buy"],
                hold=counts["hold"],
                sell=counts["sell"],
                strong_sell=counts["strong_sell"],
                unknown_count=unknown,
                total=sum(counts.values()) + unknown,
            )
        ]


async def _fetch_grades_live(symbol: str, api_key: str) -> list[dict]:
    """Hit ``/stable/grades`` and return the raw list.

    Uses ``raise_for_status_redacted`` (bd-6641 / bd-q4b4 / bd-ygtq)
    to scrub ``apikey=<value>`` from any HTTPError message before it
    can propagate to logs or HTTP clients. FMP requires the key in
    the querystring but it must never appear in an exception.
    """
    import httpx

    from openbb_fmp_cached.utils.security import raise_for_status_redacted

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _FMP_GRADES_URL, params={"symbol": symbol, "apikey": api_key}
        )
    if resp.status_code == 404:
        # FMP returns 404 with [] body for unknown symbols; return [] so
        # transform_data can build the loud-empty row.
        return []
    raise_for_status_redacted(resp)
    payload = resp.json()
    if not isinstance(payload, list):
        raise RuntimeError(
            "AnalystRecommendations: unexpected response shape from FMP: "
            f"{type(payload).__name__}"
        )
    return payload


def _resolve_credentials(credentials: dict[str, str] | None) -> dict[str, str] | None:
    """Translate ``fmp_cached_api_key`` to ``fmp_api_key`` (same shim used elsewhere)."""
    if credentials and credentials.get("fmp_api_key"):
        return credentials
    if credentials and credentials.get("fmp_cached_api_key"):
        return {"fmp_api_key": credentials["fmp_cached_api_key"]}

    try:
        from openbb_core.app.service.user_service import UserService

        user_settings = UserService().default_user_settings
        api_key = getattr(user_settings.credentials, "fmp_api_key", None) or getattr(
            user_settings.credentials, "fmp_cached_api_key", None
        )
        if api_key:
            api_key_value = (
                api_key.get_secret_value()
                if hasattr(api_key, "get_secret_value")
                else str(api_key)
            )
            return {"fmp_api_key": api_key_value}
    except Exception as exc:
        logger.warning("AnalystRecommendations: credential resolution failed: %s", exc)
    return credentials


def _store_grades(symbol: str, rows: list[dict[str, Any]]) -> None:
    """Persist raw grade rows keyed by (symbol, date, grading_company)."""
    if not rows:
        return
    query = """
    INSERT INTO analyst_grades (
        symbol, date, grading_company, previous_grade, new_grade, action,
        data_json, cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    ON DUPLICATE KEY UPDATE
        previous_grade = VALUES(previous_grade),
        new_grade = VALUES(new_grade),
        action = VALUES(action),
        data_json = VALUES(data_json),
        cached_at = CURRENT_TIMESTAMP
    """
    params_list = [
        (
            symbol,
            r.get("date"),
            r.get("gradingCompany"),
            r.get("previousGrade"),
            r.get("newGrade"),
            r.get("action"),
            json.dumps(r),
        )
        for r in rows
    ]
    try:
        execute_many(query, params_list)
    except Exception as exc:
        logger.warning("AnalystRecommendations: cache write failed: %s", exc)


def bucketize_grade(raw_grade: str | None) -> str | None:
    """Public helper — exposed for testing the grade→bucket map.

    Returns bucket name (strong_buy/buy/hold/sell/strong_sell) or None
    if the grade is unmapped. Callers can extend ``_GRADE_TO_BUCKET``
    when None starts appearing in production.
    """
    if not raw_grade:
        return None
    return _GRADE_TO_BUCKET.get(raw_grade.strip().lower())
