"""Cached financial_ratios model for FMP with dedicated database persistence.

Restatement handling (bd-ygoh)
------------------------------
The cache reads are gated purely on ``cached_at`` (via
``FINANCIAL_RATIOS_TTL_DAYS``). Once a symbol's rows are cached, the
1-day TTL keeps them fresh from a wall-clock perspective — but the
FMP source can restate historical ratios (methodology fix, amended
filing) at any time. Pre-fix a restatement would silently disagree
with the cache until the row aged out.

Post-fix (option B from bd-ygoh): callers who suspect a restatement
pass ``refresh=True`` to ``aextract_data`` to BYPASS the cache-read
step and refetch every requested symbol. The write path
(``_store_financial_ratios``) already DELETE-then-INSERTs per symbol,
so the refetch cleanly overwrites the stale rows.

The proper fix (option A: persist ``acceptedDate``/``filing_date`` and
version rows per-(symbol, date, filing_date)) is deferred to a Tier-3
refactor with its own schema migration — tracked separately. Until
then, ``refresh=True`` is the tactical escape hatch.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.financial_ratios import (
    FMPFinancialRatiosData,
    FMPFinancialRatiosFetcher,
    FMPFinancialRatiosQueryParams,
)

from openbb_fmp_cached.utils.cache_schema import (
    create_financial_ratios_table,
    ensure_financial_ratios_unique_index,
)
from openbb_fmp_cached.utils.database import (
    execute_query,
    init_database,
    replace_rows,
)

logger = logging.getLogger(__name__)

# See module docstring above for the restatement-handling design note
# (bd-ygoh). This 1-day TTL is wall-clock-only; it does NOT detect
# source-side restatements. Callers who need restatement-aware reads
# should pass ``refresh=True`` to ``aextract_data``.
FINANCIAL_RATIOS_TTL_DAYS = 1


class FMPCachedFinancialRatiosFetcher(FMPFinancialRatiosFetcher):
    """FMP Cached Financial Ratios Fetcher with dedicated database persistence."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPFinancialRatiosQueryParams:
        """Transform query params."""
        return FMPFinancialRatiosQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPFinancialRatiosQueryParams,
        credentials: dict[str, str] | None,
        *,
        refresh: bool = False,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract financial ratios data with database persistence.

        Cache-bypass keyword (bd-ygoh)
        ------------------------------
        Pass ``refresh=True`` to skip the cache-read step, refetch every
        requested symbol from FMP, AND unconditionally evict any stale
        rows for those symbols — even if the fresh fetch returns an
        empty list (delisting, methodology drop, transient upstream
        error). Use this when you suspect a restatement (methodology
        fix, amended filing) has changed historical values that the
        cache still holds. Default is ``refresh=False`` — cache-first
        behavior is unchanged.

        ``refresh`` is a **direct-fetcher-only escape hatch** (PR #355
        code-reviewer P1): the OBB router surface at
        ``obb.equity.fundamental.ratios(...)`` currently does NOT
        propagate arbitrary kwargs — the ``Query`` builder at
        ``openbb_core/provider/query.py`` composes ``params = {**
        standard_dict, **extra_dict}`` which drops unrecognized keys.
        Callers who need restatement-aware reads via the public router
        surface must either (a) bypass the cached provider by using
        ``provider='fmp'`` instead of ``'fmp_cached'`` for the affected
        call, or (b) wait for the Tier-3 per-row filing_date
        versioning refactor that will make cache reads restatement-
        aware without a manual flag. This escape hatch is documented
        here for scripts and notebooks that import the fetcher class
        directly.

        Keyword-only slot (PR #355 code-reviewer P2)
        --------------------------------------------
        ``refresh`` is declared as a keyword-only argument (after ``*``)
        rather than popped from ``**kwargs``. Self-documenting; future
        cache-layer kwargs can't accidentally leak to upstream.
        Upstream ``FMPFinancialRatiosFetcher.aextract_data`` doesn't
        accept ``refresh`` and would raise TypeError if it received it.
        """
        resolved_credentials = _resolve_credentials(credentials)

        try:
            init_database()
            create_financial_ratios_table()
            # bd-hyzu: migrate existing installs to UNIQUE(symbol,date,period).
            # Idempotent — no-op on fresh installs (constraint already inline)
            # or repeat runs (ALTER TABLE ADD UNIQUE already fails on duplicate).
            ensure_financial_ratios_unique_index()
        except Exception as exc:
            logger.warning(
                "Financial ratios cache init failed, using direct FMP call: %s", exc
            )
            return await FMPFinancialRatiosFetcher.aextract_data(
                query,
                resolved_credentials,
                **kwargs,
            )

        symbols = [
            symbol.strip() for symbol in query.symbol.split(",") if symbol.strip()
        ]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        if refresh:
            # bd-ygoh: bypass the cache-read step entirely. Every
            # requested symbol goes to upstream. PR #355 review P1:
            # eagerly DELETE the per-symbol cache rows BEFORE the
            # fetch so a subsequent empty upstream response (delisting,
            # methodology drop, transient failure) doesn't leave the
            # stale rows in place. The whole point of refresh=True is
            # "trust source over cache" — leaving stale rows on empty
            # response would silently regress to the pre-fix behavior
            # for exactly the class of restatement (methodology drop)
            # that this flag was meant to catch.
            logger.info(
                "financial_ratios refresh=True: bypassing cache for %d symbol(s) "
                "and pre-evicting stale rows (bd-ygoh restatement escape hatch)",
                len(symbols),
            )
            _evict_symbols_from_cache(symbols)
            symbols_to_fetch = list(symbols)
        else:
            for symbol in symbols:
                cached = _get_cached_financial_ratios(symbol, query)
                if cached:
                    results.extend(cached)
                else:
                    symbols_to_fetch.append(symbol)

        if symbols_to_fetch:
            fetch_query = query.model_copy(
                update={"symbol": ",".join(symbols_to_fetch)}
            )
            fresh_data = await FMPFinancialRatiosFetcher.aextract_data(
                fetch_query,
                resolved_credentials,
                **kwargs,
            )
            if fresh_data:
                _store_financial_ratios(fresh_data)
                results.extend(fresh_data)

        return sorted(
            results,
            key=lambda item: (
                (
                    symbols.index(item.get("symbol", ""))
                    if item.get("symbol") in symbols
                    else len(symbols)
                ),
                item.get("date", ""),
            ),
            reverse=True,
        )

    @staticmethod
    def transform_data(
        query: FMPFinancialRatiosQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPFinancialRatiosData]:
        """Transform raw data to standardized model."""
        return FMPFinancialRatiosFetcher.transform_data(query, data, **kwargs)


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


def _get_cached_financial_ratios(
    symbol: str,
    query_params: FMPFinancialRatiosQueryParams,
) -> list[dict[str, Any]]:
    """Read recent financial ratios data from cache."""
    freshness_cutoff = datetime.now() - timedelta(days=FINANCIAL_RATIOS_TTL_DAYS)
    query = """
    SELECT data_json
    FROM financial_ratios
    WHERE symbol = %s
      AND is_valid = TRUE
      AND cached_at >= %s
    ORDER BY date DESC
    """

    rows = execute_query(query, (symbol, freshness_cutoff))
    if not rows:
        return []

    loaded = []
    for row in rows:
        payload = row.get("data_json")
        if not payload:
            continue
        loaded.append(json.loads(payload) if isinstance(payload, str) else payload)

    loaded = _filter_by_ttm(loaded, query_params.ttm)
    if query_params.ttm != "only":
        loaded = _filter_by_period(loaded, str(query_params.period))
    max_records = query_params.limit if query_params.limit else 5
    if query_params.ttm == "only":
        return loaded
    return loaded[:max_records]


def _filter_by_ttm(records: list[dict[str, Any]], ttm: str) -> list[dict[str, Any]]:
    """Filter financial ratios records by TTM selection."""
    if ttm == "only":
        return [
            item for item in records if str(item.get("period", "")).upper() == "TTM"
        ]
    if ttm == "exclude":
        return [
            item for item in records if str(item.get("period", "")).upper() != "TTM"
        ]
    return records


def _filter_by_period(
    records: list[dict[str, Any]], period: str
) -> list[dict[str, Any]]:
    """Filter financial ratios records by requested period when not TTM."""
    if not period:
        return records
    if period.upper() == "TTM":
        return records
    return [
        item
        for item in records
        if str(item.get("period", "")).lower() == period.lower()
    ]


def _evict_symbols_from_cache(symbols: list[str]) -> None:
    """DELETE cached financial_ratios rows for the given symbols (bd-ygoh).

    Called by ``aextract_data`` under ``refresh=True`` BEFORE the
    upstream fetch, so a subsequent empty-response fetch doesn't leave
    stale rows behind. This is separate from ``_store_financial_ratios``'s
    own DELETE-then-INSERT (which fires only when there is fresh data
    to insert) — the eviction must be unconditional.

    Empty ``symbols`` list is a no-op.
    """
    if not symbols:
        return
    cleanup_query = "DELETE FROM financial_ratios WHERE symbol = %s"
    for symbol in symbols:
        s = symbol.strip()
        if s:
            execute_query(cleanup_query, (s,))


def _store_financial_ratios(ratios: list[dict[str, Any]]) -> None:
    """Persist financial ratios records atomically per symbol (bd-n3sf)."""
    if not ratios:
        return

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in ratios:
        sym = (item.get("symbol") or "").strip()
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(
            {
                "symbol": sym,
                "date": item.get("date"),
                "period": item.get("period"),
                "currency": item.get("reportedCurrency"),
                "pe_ratio": (
                    item.get("priceToEarningsRatio")
                    or item.get("priceToEarningsRatioTTM")
                ),
                "pb_ratio": (
                    item.get("priceToBookRatio") or item.get("priceToBookRatioTTM")
                ),
                "debt_to_equity": (
                    item.get("debtToEquityRatio") or item.get("debtToEquityRatioTTM")
                ),
                "current_ratio": (
                    item.get("currentRatio") or item.get("currentRatioTTM")
                ),
                "roe": item.get("returnOnEquity") or item.get("returnOnEquityTTM"),
                "roa": item.get("returnOnAssets") or item.get("returnOnAssetsTTM"),
                "data_json": json.dumps(item),
            }
        )

    for sym, rows in by_symbol.items():
        replace_rows(
            "financial_ratios",
            "symbol",
            sym,
            rows,
            columns=[
                "symbol",
                "date",
                "period",
                "currency",
                "pe_ratio",
                "pb_ratio",
                "debt_to_equity",
                "current_ratio",
                "roe",
                "roa",
                "data_json",
            ],
        )
