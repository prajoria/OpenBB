"""Cached + multi-tier ``etf_holdings`` model for FMP (#97).

Fallback chain (L3 of the design): MySQL cache -> FMP API -> issuer-file
(SSGA SPDRs today, extensible to iShares/Vanguard) -> SEC N-PORT bulk index
(deferred to a follow-up bead; ``_try_nport`` is a stub returning ``[]``).

Every tier normalizes to dict rows compatible with ``EtfHoldingsData``;
``data_source`` records provenance. The cache reuses the existing
``etf_holdings`` table's ``data_json`` column (one row per holding,
JSON-blob payload) -- same pattern as ``institutional_ownership.py``.

This module replaces the previous 10-line ``create_cached_fetcher_class``
wrapper. Class name ``FMPCachedEtfHoldingsFetcher`` is preserved so the
provider entry-point registration in ``pyproject.toml`` does not change.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from openbb_fmp.models.etf_holdings import (
    FMPEtfHoldingsData,
    FMPEtfHoldingsFetcher,
    FMPEtfHoldingsQueryParams,
)

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

ETF_HOLDINGS_TTL_DAYS = 1


def _get_cached_etf_holdings(etf_symbol: str) -> list[dict]:
    """Return cached holdings rows for an ETF if fresh+valid, else []."""
    if not etf_symbol:
        return []
    freshness_cutoff = datetime.now() - timedelta(days=ETF_HOLDINGS_TTL_DAYS)
    query = """
    SELECT data_json
    FROM etf_holdings
    WHERE symbol = %s
      AND is_valid = TRUE
      AND cached_at >= %s
    """
    try:
        rows = execute_query(query, (etf_symbol.upper(), freshness_cutoff))
    except Exception as exc:  # noqa: BLE001
        logger.warning("etf_holdings cache read for %s failed: %s", etf_symbol, exc)
        return []

    loaded: list[dict] = []
    for row in rows or []:
        payload = row.get("data_json")
        if not payload:
            continue
        if isinstance(payload, str):
            try:
                loaded.append(json.loads(payload))
            except json.JSONDecodeError as exc:
                logger.warning("etf_holdings cache: bad JSON for %s: %s", etf_symbol, exc)
                continue
        else:
            loaded.append(payload)
    return loaded


def _store_etf_holdings(
    etf_symbol: str,
    rows: list[dict],
    *,
    data_source: str,
) -> None:
    """Persist ETF holding rows in the cache (delete-then-insert per ETF)."""
    if not etf_symbol or not rows:
        return
    etf = etf_symbol.upper()

    cleanup_sql = "DELETE FROM etf_holdings WHERE symbol = %s"
    insert_sql = """
    INSERT INTO etf_holdings
        (symbol, data_json, is_valid, cached_at)
    VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP)
    """
    try:
        execute_query(cleanup_sql, (etf,))
        params_list = []
        for r in rows:
            payload = dict(r)
            payload["data_source"] = data_source
            params_list.append((etf, json.dumps(payload, default=str)))
        if params_list:
            execute_many(insert_sql, params_list)
            logger.info(
                "Cached %d etf_holdings rows for %s (source=%s)",
                len(params_list), etf, data_source,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("etf_holdings cache write for %s failed: %s", etf_symbol, exc)


async def _try_fmp(
    query: FMPEtfHoldingsQueryParams,
    symbol: str,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict]:
    """FMP API tier. Returns [] on 402 / any error (never raises).

    bd-3ka: per-tier failures are logged at DEBUG here (never WARNING).
    The aggregate ALL-tiers-failed WARNING lives in aextract_data so
    a benign 402-then-rescue doesn't produce user-facing noise.
    """
    try:
        fetch_query = FMPEtfHoldingsQueryParams(symbol=symbol)
        raw = await FMPEtfHoldingsFetcher.aextract_data(
            fetch_query, credentials, **kwargs,
        )
        return list(raw or [])
    except Exception as exc:  # noqa: BLE001
        # bd-3ka: DEBUG (not WARNING) — Tier-2/3 fallback may rescue.
        # The aggregate WARNING at aextract_data fires only when EVERY
        # tier fails, so ops still sees real breakage.
        logger.debug("FMP etf_holdings %s failed: %s", symbol, exc)
        return []


async def _try_issuer(symbol: str) -> list[dict]:
    """Issuer-file tier. Returns [] for unknown ticker / HTTP error.

    bd-3ka: per-tier failures are logged at DEBUG here (never WARNING).
    """
    try:
        from openbb_fmp_cached.models.etf_holdings_issuer import (  # noqa: PLC0415
            fetch_issuer_holdings,
        )
        return await asyncio.to_thread(fetch_issuer_holdings, symbol)
    except Exception as exc:  # noqa: BLE001
        # bd-3ka: DEBUG (not WARNING) — Tier-3 may rescue, and the
        # aggregate WARNING at aextract_data covers real all-tiers-fail.
        logger.debug("issuer-tier %s failed: %s", symbol, exc)
        return []


async def _try_nport(symbol: str) -> list[dict]:  # noqa: ARG001
    """SEC N-PORT tier (stub).

    Deferred per the T1 spike: SEC N-PORT bulk-dataset URL was not at any
    probed path. Follow-up beads OpenBBTechnical-0p0 and -022 stay deferred
    until the URL is hand-confirmed. Until then, this returns [].
    """
    return []


class FMPCachedEtfHoldingsFetcher(FMPEtfHoldingsFetcher):
    """FMP Cached ETF Holdings Fetcher with multi-tier fallback."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FMPEtfHoldingsQueryParams:
        """Transform query params."""
        return FMPEtfHoldingsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPEtfHoldingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract ETF holdings with cache + multi-tier fallback."""
        try:
            init_database()
        except Exception as exc:  # noqa: BLE001
            logger.warning("etf_holdings cache init failed: %s", exc)

        symbol = (query.symbol or "").strip().upper()
        if not symbol:
            return []

        # Tier 0: cache
        cached = _get_cached_etf_holdings(symbol)
        if cached:
            logger.info("etf_holdings cache HIT for %s (%d rows)", symbol, len(cached))
            return cached

        # Tier 1: FMP
        fmp_rows = await _try_fmp(query, symbol, credentials, **kwargs)
        if fmp_rows:
            for r in fmp_rows:
                r.setdefault("data_source", "fmp")
            _store_etf_holdings(symbol, fmp_rows, data_source="fmp")
            return fmp_rows

        # Tier 2: issuer-file
        issuer_rows = await _try_issuer(symbol)
        if issuer_rows:
            tag = issuer_rows[0].get("data_source", "issuer_ssga")
            _store_etf_holdings(symbol, issuer_rows, data_source=tag)
            return issuer_rows

        # Tier 3: SEC N-PORT (stub)
        nport_rows = await _try_nport(symbol)
        if nport_rows:
            _store_etf_holdings(symbol, nport_rows, data_source="sec_nport")
            return nport_rows

        # bd-3ka: single aggregate WARNING when ALL tiers exhausted.
        # This is the ONLY log line ops should see at WARNING level from
        # this fetcher — per-tier failures are DEBUG (see _try_fmp /
        # _try_issuer) because a lower tier may rescue. A benign 402 on
        # FMP followed by an issuer-tier success produces zero WARNINGs.
        logger.warning(
            "etf_holdings %s: all tiers exhausted (FMP, issuer, N-PORT) "
            "— returning empty holdings list", symbol,
        )
        return []

    @staticmethod
    def transform_data(
        query: FMPEtfHoldingsQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FMPEtfHoldingsData]:
        """Normalize to FMPEtfHoldingsData; tolerate missing fields from fallback tiers.

        bd-5in: if EVERY row in a non-empty response fails validation
        (100% schema drift), promote from DEBUG to WARNING with a sample
        error message. Partial failures stay at DEBUG per existing
        tolerance — the WARN only fires for the case where a caller
        thinks they got no data but the truth is "endpoint returned N
        rows and all N failed validation."
        """
        validated: list[FMPEtfHoldingsData] = []
        failed_count = 0
        sample_error: str | None = None
        for record in data or []:
            try:
                validated.append(FMPEtfHoldingsData.model_validate(record))
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                if sample_error is None:
                    sample_error = f"{type(exc).__name__}: {exc}"
                logger.debug(
                    "Skipping etf_holdings record that does not match FMP schema: %s",
                    record.get("symbol", "?") if isinstance(record, dict) else "?",
                )

        # bd-5in loud-empty: N/N validation failures on non-empty input
        # → schema drift (or wholesale endpoint contract change). Promote
        # to WARNING with a sample so ops can distinguish this from
        # "endpoint returned []" or the benign partial-failure case.
        if data and failed_count == len(data):
            logger.warning(
                "etf_holdings transform: %d/%d rows failed schema validation "
                "— possible upstream schema drift. Sample error: %s",
                failed_count, len(data), sample_error or "(no error captured)",
            )
        return validated
