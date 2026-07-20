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

# Pre-existing pylint suppressions surfaced by CI (#909) — these patterns
# are used throughout fmp_cached and are out of scope for this hygiene PR.
# pylint: disable=import-outside-toplevel  # lazy imports for optional deps
# pylint: disable=logging-fstring-interpolation  # f-strings in log calls
# pylint: disable=unused-argument  # signature-required unused params
# pylint: disable=broad-exception-caught  # per-source failure isolation
# pylint: disable=too-many-lines,too-many-locals,too-many-branches  # legacy
# pylint: disable=too-many-statements,too-many-return-statements
# pylint: disable=too-many-nested-blocks,too-many-arguments,too-many-positional-arguments

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from openbb_fmp.models.institutional_ownership import (
    FMPInstitutionalOwnershipData,
    FMPInstitutionalOwnershipFetcher,
    FMPInstitutionalOwnershipQueryParams,
)
from pydantic import ValidationError

from openbb_fmp_cached.utils.database import (
    execute_query,
    init_database,
    replace_rows,
)

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

        # bd-uolr (PR #426 silent-failure-hunter P1): compute the effective
        # (year, quarter) ONCE up front, matching FMP's default-latest
        # logic. Use these values for BOTH the cache read AND the cache
        # write, so all cache-write paths (FMP + yfinance + SEC 13F)
        # stamp identical year/quarter into the payload. Otherwise
        # fallback-source rows would be written WITHOUT year/quarter and
        # every future read would treat them as cache-miss, disabling
        # caching for any symbol not served by FMP.
        eff_year, eff_quarter = _effective_year_quarter(query.year, query.quarter)

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
            cached = _get_cached_institutional(symbol, eff_year, eff_quarter)
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
            _store_institutional(
                fmp_results, data_source="fmp", year=eff_year, quarter=eff_quarter
            )
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
            _store_institutional(
                yf_results, data_source="yfinance", year=eff_year, quarter=eff_quarter
            )
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
            _store_institutional(
                sec_results, data_source="sec_13f", year=eff_year, quarter=eff_quarter
            )
            results.extend(sec_results)

        return results

    @staticmethod
    def transform_data(
        query: FMPInstitutionalOwnershipQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPInstitutionalOwnershipData]:
        """Transform raw data to FMP model, tolerating missing fields from fallback sources.

        The fallback chain (FMP → yfinance → SEC 13F) may return records
        with slightly different shapes. This method validates each record
        against ``FMPInstitutionalOwnershipData`` and skips ones that fail,
        so a single malformed record doesn't nuke the entire response.

        Failure logging (bd-0bp1)
        -------------------------
        Pre-fix each drop was logged at ``debug`` level with no exception
        context — invisible under the default logging config, so a
        caller debugging "why is institutional ownership empty for X?"
        had no log evidence. Post-fix each drop is logged at ``WARNING``
        with the symbol and the specific ``ValidationError``.

        All-dropped guard (bd-0bp1)
        ---------------------------
        If ``data`` is non-empty but EVERY record fails validation, the
        method raises ``ValueError`` rather than silently returning an
        empty list. The fallback design assumes at least one source
        succeeds; a complete drop indicates either schema drift in FMP
        or all fallback sources broken — both cases where "empty result"
        is indistinguishable from "no institutional owners for this
        ticker", which is a fundamentally different answer.

        An input list that is already empty (no records tried) is a
        valid degenerate case and returns ``[]`` without raising.
        """
        validated: list[FMPInstitutionalOwnershipData] = []
        drops = 0
        for record in data:
            try:
                validated.append(FMPInstitutionalOwnershipData.model_validate(record))
            except ValidationError as exc:
                # bd-0bp1: log at WARNING (not debug) with the specific
                # exception so operators debugging "why is this empty?"
                # have log evidence. Pre-fix used logger.debug + no exc.
                # PR #345 silent-failure-hunter (P2): narrow from
                # ``except Exception`` to ``except ValidationError`` so a
                # TypeError/AttributeError bug in Pydantic or in the
                # record dict itself isn't silently mislabeled as
                # 'schema mismatch' — real bugs propagate; only genuine
                # schema drift gets the tolerate-and-warn path.
                drops += 1
                logger.warning(
                    "Dropping institutional-ownership record for %s due to "
                    "schema mismatch: %s",
                    record.get("symbol", "unknown"),
                    exc,
                )

        # bd-0bp1: if we had input records but every single one was
        # dropped, that's a bug not a tolerable state — the fallback
        # design assumes at least one source produces a valid record.
        # Raise so the caller sees the schema-drift signal instead of
        # an ambiguous empty result.
        if drops and not validated:
            raise ValueError(
                f"All {drops} institutional-ownership record(s) failed FMP "
                f"schema validation for query symbol={query.symbol!r}; see "
                f"WARNING logs for per-record details. This indicates either "
                f"schema drift in FMPInstitutionalOwnershipData or a broken "
                f"fallback source (yfinance / SEC 13F); do NOT return an "
                f"empty list — that is indistinguishable from 'no owners' "
                f"(bd-0bp1)."
            )

        return validated


# ---------------------------------------------------------------------------
# Effective year/quarter (mirrors FMP's default-latest logic)
# ---------------------------------------------------------------------------


def _effective_year_quarter(year: int | None, quarter: int | None) -> tuple[int, int]:
    """Compute the effective (year, quarter) matching FMP's default logic.

    bd-uolr (PR #426 silent-failure-hunter P1): FMP applies a
    default-latest-quarter policy when year/quarter is None (see
    ``openbb_fmp/models/institutional_ownership.py::get_data_urls``
    lines 182-197). This helper mirrors that logic client-side so:

    1. All 3 cache-write paths (FMP, yfinance, SEC 13F) stamp identical
       year/quarter into the payload. Without this, yfinance/SEC-cached
       rows would be written without year/quarter and every future read
       would treat them as cache-miss, effectively disabling caching for
       any symbol not served by FMP.
    2. Cache read uses the SAME effective values, so a call with
       (year=None, quarter=None) hits cache on subsequent identical
       calls (was: guaranteed miss per D2 pre-fix).

    Kept in sync with FMP's implementation — if that logic changes,
    update this helper simultaneously.
    """
    from pandas import Timestamp, offsets

    y = year if year else None
    q = quarter if quarter else None

    if y is None and q is None:
        current = (Timestamp("now") + offsets.QuarterEnd()) - offsets.QuarterEnd()
        q = int(current.quarter)
        y = int(current.year)
    elif y is None and q is not None:
        y = int(Timestamp("now").year)
    elif y is not None and q is None:
        current = Timestamp("now")
        q = (
            4
            if y < current.year
            else (current.quarter - 1 if current.quarter > 1 else 1)
        )
    return int(y), int(q)  # type: ignore[arg-type]


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


def _get_cached_institutional(
    symbol: str,
    year: int | None,
    quarter: int | None,
) -> list[dict]:
    """Read fresh institutional ownership data from MySQL cache (bd-uolr).

    Filters by exact (symbol, year, quarter) match on the JSON payload.
    When year OR quarter is None, treats as cache-miss and returns [] so
    the caller falls through to FMP fetch (which applies its own
    default-latest-quarter logic — duplicating that client-side would
    risk drift).

    Pre-fix filtered only by symbol, silently returning whatever period
    was most-recently cached for that symbol regardless of the caller's
    year/quarter — poisoning historical time-series analytics.
    """
    # D2: without both year AND quarter, we can't build a deterministic
    # cache key that matches what FMP would compute. Skip cache; fall
    # through to fetch.
    if year is None or quarter is None:
        return []

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

    # D3: in-memory filter on the JSON payload's year/quarter fields.
    # bd-porh (future architectural PIT refactor) may promote these to
    # schema columns; this in-memory filter is the minimum-risk correctness
    # fix that unblocks historical time-series analytics today.
    # PR #426 code-reviewer P1: coerce payload year/quarter to int before
    # comparison — FMP's JSON has historically drifted between int and
    # string for numeric fields, and an equality mismatch would silently
    # turn every cache-hit into a cache-miss (permanent refetch storm).
    loaded = []
    for row in rows:
        payload = row.get("data_json")
        if not payload:
            continue
        decoded = json.loads(payload) if isinstance(payload, str) else payload
        try:
            row_year = (
                int(decoded.get("year")) if decoded.get("year") is not None else None
            )
            row_quarter = (
                int(decoded.get("quarter"))
                if decoded.get("quarter") is not None
                else None
            )
        except (TypeError, ValueError):
            # Legacy/malformed row: skip (safe degrade — treat as cache-miss
            # for this row, refetch will overwrite with well-formed data).
            continue
        if row_year == year and row_quarter == quarter:
            loaded.append(decoded)
    return loaded


def _store_institutional(
    records: list[dict],
    data_source: str = "fmp",
    *,
    year: int | None = None,
    quarter: int | None = None,
) -> None:
    """Persist institutional ownership records in MySQL cache (bd-n3sf/ihdn/uolr).

    Routes per-symbol DELETE+INSERT through ``replace_rows()`` from bd-kh08
    (PR #414) so each symbol's cache write is atomic — a partial-write
    failure between the DELETE and the INSERT no longer wipes prior cached
    quarters for the symbol.

    D1: one transaction per symbol (independent) — a per-symbol failure
    logs a warning naming that symbol and the loop continues with the
    remaining symbols. This matches the pre-fix "best effort per-symbol"
    surface where each symbol's execute_query DELETE either committed
    on its own (autocommit=True pre-fix) or failed independently.
    D6: empty records = no-op (no DELETE fires).
    D4: per-symbol try/except swallows so a single-symbol write failure
    MUST NOT block cache writes for the other symbols in the batch, and
    MUST NOT propagate to the read path in ``aextract_data``.

    Post-review-fix (PR #418 silent-failure-hunter P1-1): pre-fix version
    had the try/except OUTSIDE the loop, meaning the first mid-batch
    failure aborted every remaining symbol with only ONE warning that
    didn't identify which symbol died. Now each symbol gets its own
    try/except with the symbol name in the warning.

    Post-review-fix (PR #426 silent-failure-hunter P1): year and quarter
    are now keyword-only args that MUST be stamped into every record's
    payload before JSON-encoding. Without this, yfinance/SEC-cached rows
    would be written without year/quarter and every future cache read
    would treat them as cache-miss — disabling caching for any symbol
    not served by FMP. When year/quarter is None (only for legacy
    callers), the payload's own year/quarter is preserved (FMP populates
    them; other sources don't).
    """
    if not records:
        return

    # Group records by (uppercased) symbol so each symbol is one txn (D1).
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        sym = (item.get("symbol") or "").strip().upper()
        if not sym:
            continue
        # Attach provenance in-place (preserves pre-fix mutation semantics).
        item["data_source"] = data_source
        # bd-uolr (PR #426): stamp the effective (year, quarter) into
        # EVERY payload — critical for yfinance/SEC rows which otherwise
        # lack these fields entirely. Overwrite any existing values so
        # the source of truth is the aextract_data caller (which computed
        # the effective values via _effective_year_quarter).
        if year is not None:
            item["year"] = year
        if quarter is not None:
            item["quarter"] = quarter
        by_symbol.setdefault(sym, []).append(
            {
                "symbol": sym,
                "date": item.get("date", date.today().isoformat()),
                "data_json": json.dumps(item, default=str),
            }
        )

    total_inserted = 0
    succeeded: list[str] = []
    for sym, rows in by_symbol.items():
        try:
            replace_rows(
                "institutional_ownership",
                "symbol",
                sym,
                rows,
                columns=["symbol", "date", "data_json"],
            )
            total_inserted += len(rows)
            succeeded.append(sym)
        except Exception as exc:
            # Per-symbol swallow (D1 + D4) — log the specific symbol so
            # operators can trace which write failed and which are un-
            # attempted-vs-attempted. Loop continues with next symbol.
            logger.warning(
                "Failed to cache institutional ownership for %s: %s", sym, exc
            )

    if total_inserted:
        logger.info(
            "Cached %d institutional ownership records (source=%s) for %s",
            total_inserted,
            data_source,
            ", ".join(sorted(succeeded)),
        )


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
