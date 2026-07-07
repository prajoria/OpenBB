"""Cached institutional_ownership model for FMP with multi-source fallback.

This module provides intelligent caching for institutional ownership data with
a three-tier fallback chain:

1. **MySQL Cache**: Check local MySQL for fresh cached data (TTL = 7 days)
2. **FMP API**: Primary source -- quarterly institutional ownership summary
3. **yfinance**: Fallback -- share_statistics endpoint (free, no key needed)
4. **SEC EDGAR**: Final fallback -- 13F-HR filings (free, public data)

Regardless of which source provides the data, results are normalised to the
FMP InstitutionalOwnershipData schema and cached in MySQL for future calls.

Database Schema:
    institutional_ownership table with data_json column storing the full
    normalised record plus a data_source column tracking provenance.
"""

import json
import logging
from datetime import datetime, timedelta, date
from typing import Any

from openbb_fmp.models.institutional_ownership import (
    FMPInstitutionalOwnershipData,
    FMPInstitutionalOwnershipFetcher,
    FMPInstitutionalOwnershipQueryParams,
)
from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

# Cache TTL -- institutional ownership is quarterly data, 7 days is conservative
INSTITUTIONAL_OWNERSHIP_TTL_DAYS = 7


class FMPCachedInstitutionalOwnershipFetcher(FMPInstitutionalOwnershipFetcher):
    """FMP Cached Institutional Ownership Fetcher with multi-source fallback.

    Fallback chain: cache -> FMP API -> yfinance -> SEC EDGAR 13F.
    All results are normalised to FMP schema and persisted in MySQL.
    """

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPInstitutionalOwnershipQueryParams:
        """Transform query params."""
        return FMPInstitutionalOwnershipQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPInstitutionalOwnershipQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract institutional ownership data with cache + multi-source fallback.

        Priority order:
        1. MySQL cache (if fresh data exists)
        2. FMP API (primary, requires paid plan)
        3. yfinance share_statistics (free)
        4. SEC EDGAR 13F (free, public)

        All fetched data is cached in MySQL for subsequent calls.
        """
        resolved_credentials = _resolve_credentials(credentials)

        # --- Database init (best-effort) ---
        try:
            init_database()
        except Exception as exc:
            logger.warning("Institutional ownership cache init failed: %s", exc)

        symbols = [s.strip() for s in query.symbol.split(",") if s.strip()]
        results: list[dict] = []
        symbols_to_fetch: list[str] = []

        # --- Step 1: Check cache ---
        for symbol in symbols:
            cached = _get_cached_institutional(symbol)
            if cached:
                results.extend(cached)
                logger.info("Institutional ownership cache HIT for %s", symbol)
            else:
                symbols_to_fetch.append(symbol)

        if not symbols_to_fetch:
            return results

        # --- Step 2: Try FMP API ---
        fmp_results = await _try_fmp(
            query, symbols_to_fetch, resolved_credentials, **kwargs
        )
        if fmp_results:
            _store_institutional(fmp_results, data_source="fmp")
            results.extend(fmp_results)
            fetched_symbols = {r.get("symbol", "").upper() for r in fmp_results}
            symbols_to_fetch = [
                s for s in symbols_to_fetch if s.upper() not in fetched_symbols
            ]

        if not symbols_to_fetch:
            return results

        # --- Step 3: Try yfinance ---
        yf_results = await _try_yfinance(symbols_to_fetch)
        if yf_results:
            _store_institutional(yf_results, data_source="yfinance")
            results.extend(yf_results)
            fetched_symbols = {r.get("symbol", "").upper() for r in yf_results}
            symbols_to_fetch = [
                s for s in symbols_to_fetch if s.upper() not in fetched_symbols
            ]

        if not symbols_to_fetch:
            return results

        # --- Step 4: Try SEC EDGAR 13F ---
        sec_results = await _try_sec_13f(symbols_to_fetch)
        if sec_results:
            _store_institutional(sec_results, data_source="sec_13f")
            results.extend(sec_results)

        return results

    @staticmethod
    def transform_data(
        query: FMPInstitutionalOwnershipQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPInstitutionalOwnershipData]:
        """Transform raw data to FMP model, tolerating missing fields from fallback sources."""
        validated = []
        for record in data:
            try:
                validated.append(FMPInstitutionalOwnershipData.model_validate(record))
            except Exception:
                # Fallback sources may not have all FMP fields -- skip invalid records
                # but log for debugging
                logger.debug(
                    "Skipping record that does not match FMP schema: %s",
                    record.get("symbol", "unknown"),
                )
        return validated


# ---------------------------------------------------------------------------
# Credential resolution (same pattern as balance_sheet.py)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------


def _get_cached_institutional(symbol: str) -> list[dict]:
    """Read fresh institutional ownership data from MySQL cache."""
    freshness_cutoff = datetime.now() - timedelta(days=INSTITUTIONAL_OWNERSHIP_TTL_DAYS)
    query = """
    SELECT data_json
    FROM institutional_ownership
    WHERE symbol = %s
      AND is_valid = TRUE
      AND cached_at >= %s
    ORDER BY date DESC
    """
    try:
        rows = execute_query(query, (symbol.upper(), freshness_cutoff))
    except Exception as exc:
        logger.warning("Cache read failed for %s: %s", symbol, exc)
        return []

    if not rows:
        return []

    loaded = []
    for row in rows:
        payload = row.get("data_json")
        if not payload:
            continue
        loaded.append(json.loads(payload) if isinstance(payload, str) else payload)
    return loaded


def _store_institutional(records: list[dict], data_source: str = "fmp") -> None:
    """Persist institutional ownership records in MySQL cache."""
    if not records:
        return

    cleanup_query = "DELETE FROM institutional_ownership WHERE symbol = %s"
    insert_query = """
    INSERT INTO institutional_ownership (
        symbol,
        date,
        data_json,
        is_valid,
        cached_at
    ) VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
    """

    try:
        # Remove old records for the symbols being stored
        symbols = {
            (r.get("symbol") or "").strip().upper() for r in records if r.get("symbol")
        }
        for symbol in symbols:
            execute_query(cleanup_query, (symbol,))

        # Insert new records
        params_list = []
        for item in records:
            # Attach provenance
            item["data_source"] = data_source
            params_list.append(
                (
                    (item.get("symbol") or "").upper(),
                    item.get("date", date.today().isoformat()),
                    json.dumps(item, default=str),
                )
            )

        if params_list:
            execute_many(insert_query, params_list)
            logger.info(
                "Cached %d institutional ownership records (source=%s) for %s",
                len(params_list),
                data_source,
                ", ".join(sorted({p[0] for p in params_list})),
            )
    except Exception as exc:
        logger.warning("Failed to cache institutional ownership data: %s", exc)


# ---------------------------------------------------------------------------
# Source 1: FMP API
# ---------------------------------------------------------------------------


async def _try_fmp(
    query: FMPInstitutionalOwnershipQueryParams,
    symbols: list[str],
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict]:
    """Try fetching from the FMP institutional ownership endpoint."""
    try:
        fetch_query = query.model_copy(update={"symbol": ",".join(symbols)})
        raw = await FMPInstitutionalOwnershipFetcher.aextract_data(
            fetch_query, credentials, **kwargs
        )
        if raw:
            logger.info("FMP institutional ownership: fetched %d records", len(raw))
            return raw
    except Exception as exc:
        logger.warning("FMP institutional ownership failed: %s", exc)
    return []


# ---------------------------------------------------------------------------
# Source 2: yfinance share_statistics
# ---------------------------------------------------------------------------


async def _try_yfinance(symbols: list[str]) -> list[dict]:
    """Try fetching institutional ownership from yfinance share_statistics.

    yfinance provides: institution_ownership (%), institution_float_ownership (%),
    institutions_count.  These are normalised into the FMP schema.
    """
    try:
        import asyncio
        from yfinance import Ticker

        results = []

        async def _get_one(symbol: str) -> dict | None:
            try:
                ticker = await asyncio.to_thread(lambda: Ticker(symbol))
                info = await asyncio.to_thread(lambda: ticker.get_info())
                if not info:
                    return None

                # Also try major_holders for more detail
                try:
                    major_holders = await asyncio.to_thread(
                        lambda: ticker.get_major_holders(as_dict=True).get("Value")
                    )
                    if major_holders:
                        info.update(major_holders)
                except Exception:
                    pass

                inst_pct = info.get("heldPercentInstitutions")
                if inst_pct is None:
                    return None

                today = date.today()
                return {
                    "symbol": symbol.upper(),
                    "cik": None,
                    "date": today.isoformat(),
                    "investors_holding": info.get("institutionsCount", 0) or 0,
                    "last_investors_holding": 0,
                    "investors_holding_change": 0,
                    "number_of_13f_shares": None,
                    "last_number_of_13f_shares": None,
                    "number_of_13f_shares_change": None,
                    "total_invested": 0.0,
                    "last_total_invested": 0.0,
                    "total_invested_change": 0.0,
                    "ownership_percent": inst_pct,
                    "last_ownership_percent": 0.0,
                    "ownership_percent_change": 0.0,
                    "new_positions": 0,
                    "last_new_positions": 0,
                    "new_positions_change": 0,
                    "increased_positions": 0,
                    "last_increased_positions": 0,
                    "increased_positions_change": 0,
                    "closed_positions": 0,
                    "last_closed_positions": 0,
                    "closed_positions_change": 0,
                    "reduced_positions": 0,
                    "last_reduced_positions": 0,
                    "reduced_positions_change": 0,
                    "total_calls": 0,
                    "last_total_calls": 0,
                    "total_calls_change": 0,
                    "total_puts": 0,
                    "last_total_puts": 0,
                    "total_puts_change": 0,
                    "put_call_ratio": 0.0,
                    "last_put_call_ratio": 0.0,
                    "put_call_ratio_change": 0.0,
                    "data_source": "yfinance",
                }
            except Exception as exc:
                logger.debug("yfinance failed for %s: %s", symbol, exc)
                return None

        tasks = [_get_one(sym) for sym in symbols]
        fetched = await asyncio.gather(*tasks)
        results = [r for r in fetched if r is not None]

        if results:
            logger.info(
                "yfinance institutional ownership: fetched %d records", len(results)
            )
        return results

    except ImportError:
        logger.warning("yfinance not installed -- skipping yfinance fallback")
        return []
    except Exception as exc:
        logger.warning("yfinance institutional ownership failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Source 3: SEC EDGAR 13F
# ---------------------------------------------------------------------------


def _period_to_date(period: str | None) -> date:
    """Convert a ``'<YYYY>-Q<n>'`` index period to its quarter-end date."""
    quarter_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    if period and "-Q" in period:
        try:
            year_s, q_s = period.split("-Q")
            month, day = quarter_end[int(q_s)]
            return date(int(year_s), month, day)
        except Exception:  # noqa: BLE001
            pass
    return date.today()


async def _try_sec_13f(symbols: list[str]) -> list[dict]:
    """Try institutional ownership from the SEC bulk 13F CUSIP index.

    Form 13F is filed *by* managers and indexed by the filer, so it cannot
    answer "who holds ``<symbol>``?" directly. We resolve the ticker to its
    CUSIP(s) via the local index (populated by ``Tools/ingest_sec_13f.py``) and
    aggregate the per-manager holding rows into a single summary row per symbol
    matching the FMP schema (design L4 -- single consumer, output unchanged).
    """
    try:
        from openbb_sec.utils.thirteen_f_index import (
            holders_for_cusip,
            init_thirteen_f_index,
            resolve_cusip,
        )

        # Best-effort: ensure the index tables exist (graceful if DB is down).
        try:
            init_thirteen_f_index()
        except Exception as exc:  # noqa: BLE001
            logger.debug("13F index init failed: %s", exc)

        results = []
        for symbol in symbols:
            try:
                cusips = resolve_cusip(symbol)
                if not cusips:
                    logger.debug("SEC 13F: no CUSIP for %s", symbol)
                    continue

                holders = holders_for_cusip(cusips)
                if not holders:
                    logger.debug(
                        "SEC 13F: no holders for %s (cusips=%s)", symbol, cusips
                    )
                    continue

                # All rows share the resolved (latest) period.
                period = holders[0].get("period")
                institutions_count = len({h.get("filer_cik") for h in holders})
                total_shares = sum(int(h.get("shares") or 0) for h in holders)
                total_value = sum(int(h.get("value_usd") or 0) for h in holders)

                as_of = _period_to_date(period)
                results.append(
                    {
                        "symbol": symbol.upper(),
                        "cik": None,
                        "date": as_of.isoformat(),
                        "investors_holding": institutions_count,
                        "last_investors_holding": 0,
                        "investors_holding_change": 0,
                        "number_of_13f_shares": total_shares,
                        "last_number_of_13f_shares": None,
                        "number_of_13f_shares_change": None,
                        "total_invested": float(total_value),
                        "last_total_invested": 0.0,
                        "total_invested_change": 0.0,
                        "ownership_percent": 0.0,
                        "last_ownership_percent": 0.0,
                        "ownership_percent_change": 0.0,
                        "new_positions": 0,
                        "last_new_positions": 0,
                        "new_positions_change": 0,
                        "increased_positions": 0,
                        "last_increased_positions": 0,
                        "increased_positions_change": 0,
                        "closed_positions": 0,
                        "last_closed_positions": 0,
                        "closed_positions_change": 0,
                        "reduced_positions": 0,
                        "last_reduced_positions": 0,
                        "reduced_positions_change": 0,
                        "total_calls": 0,
                        "last_total_calls": 0,
                        "total_calls_change": 0,
                        "total_puts": 0,
                        "last_total_puts": 0,
                        "total_puts_change": 0,
                        "put_call_ratio": 0.0,
                        "last_put_call_ratio": 0.0,
                        "put_call_ratio_change": 0.0,
                        "data_source": "sec_13f",
                    }
                )
            except Exception as exc:
                logger.debug("SEC 13F failed for %s: %s", symbol, exc)

        if results:
            logger.info(
                "SEC 13F institutional ownership: fetched %d records", len(results)
            )
        return results

    except ImportError:
        logger.warning("openbb_sec not installed -- skipping SEC fallback")
        return []
    except Exception as exc:
        logger.warning("SEC 13F institutional ownership failed: %s", exc)
        return []
