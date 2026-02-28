"""Cached equity_peers model for FMP with dedicated database persistence."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.equity_peers import (
    FMPEquityPeersData,
    FMPEquityPeersFetcher,
    FMPEquityPeersQueryParams,
)
from openbb_fmp_cached.utils.cache_schema import create_equity_peers_table
from openbb_fmp_cached.utils.database import execute_query, execute_many, init_database

logger = logging.getLogger(__name__)

PEERS_TTL_DAYS = 7


class FMPCachedEquityPeersFetcher(FMPEquityPeersFetcher):
    """FMP Cached Equity Peers Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEquityPeersQueryParams:
        """Transform query params."""
        return FMPEquityPeersQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEquityPeersQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract peer data with database persistence."""
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_equity_peers_table()
        except Exception as exc:
            logger.warning("Peers cache init failed, using direct FMP call: %s", exc)
            return await FMPEquityPeersFetcher.aextract_data(query, resolved_credentials, **kwargs)

        cached = _get_cached_peers(query.symbol)
        if cached:
            return cached

        fresh_data = await FMPEquityPeersFetcher.aextract_data(query, resolved_credentials, **kwargs)
        if fresh_data:
            _store_peers(query.symbol, fresh_data)

        return fresh_data

    @staticmethod
    def transform_data(
        query: FMPEquityPeersQueryParams,
        data: list,
        **kwargs: Any,
    ) -> list[FMPEquityPeersData]:
        """Transform raw data to standardized model."""
        return FMPEquityPeersFetcher.transform_data(query, data, **kwargs)


def _resolve_credentials(credentials: dict[str, str] | None) -> dict[str, str] | None:
    """Resolve credentials and translate fmp_cached key if needed."""
    if credentials and credentials.get("fmp_api_key"):
        return credentials

    if credentials and credentials.get("fmp_cached_api_key"):
        return {"fmp_api_key": credentials["fmp_cached_api_key"]}

    try:
        from openbb_core.app.service.user_service import UserService

        user_settings = UserService().default_user_settings
        api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        if api_key:
            api_key_value = (
                api_key.get_secret_value()
                if hasattr(api_key, "get_secret_value")
                else str(api_key)
            )
            return {"fmp_api_key": api_key_value}
    except Exception as exc:
        logger.warning("Unable to resolve FMP credentials from user settings: %s", exc)

    return credentials


def _get_cached_peers(parent_symbol: str) -> list[dict[str, Any]]:
    """Read recent peers for the requested parent symbol."""
    freshness_cutoff = datetime.now() - timedelta(days=PEERS_TTL_DAYS)
    query = """
    SELECT data_json
    FROM equity_peers
    WHERE is_valid = TRUE
      AND cached_at >= %s
      AND JSON_UNQUOTE(JSON_EXTRACT(additional_fields, '$.parent_symbol')) = %s
    ORDER BY market_cap DESC, cached_at DESC
    """

    rows = execute_query(query, (freshness_cutoff, parent_symbol))
    if not rows:
        return []

    results: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("data_json")
        if not payload:
            continue
        results.append(json.loads(payload) if isinstance(payload, str) else payload)

    return results


def _store_peers(parent_symbol: str, peers: list[dict[str, Any]]) -> None:
    """Persist peers for the requested symbol."""
    cleanup_query = """
    DELETE FROM equity_peers
    WHERE JSON_UNQUOTE(JSON_EXTRACT(additional_fields, '$.parent_symbol')) = %s
    """
    insert_query = """
    INSERT INTO equity_peers (
        symbol,
        company_name,
        price,
        market_cap,
        data_json,
        additional_fields,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    execute_query(cleanup_query, (parent_symbol,))

    params_list = [
        (
            item.get("symbol"),
            item.get("companyName"),
            item.get("price"),
            item.get("mktCap"),
            json.dumps(item),
            json.dumps({"parent_symbol": parent_symbol}),
        )
        for item in peers
    ]

    if params_list:
        execute_many(insert_query, params_list)
