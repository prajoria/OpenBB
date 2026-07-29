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

from openbb_fmp_cached.utils.database import (
    execute_query,
    init_database,
    replace_rows,
)

logger = logging.getLogger(__name__)

ETF_HOLDINGS_TTL_DAYS = 1


def _get_cached_etf_holdings(etf_symbol: str) -> list[dict]:
    """Return cached holdings rows for an ETF if fresh+valid, else [].

    Note (#512): drops rows whose weight looks like a pre-normalize
    fraction (0 < w < 1 with total sum < 5) — a signature of the
    pre-#512 SSGA-parser bug that stored fraction-shaped weights.
    Post-#512 the parser stores percentages (sum ≈ 100). Serving a
    pre-#512 cached row through the FMPEtfHoldingsData validator
    would divide by 100 again, producing weights 100× understated.
    Fail-safe: drop suspicious rows so the tier chain re-populates
    from the fixed parser.
    """
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
                logger.warning(
                    "etf_holdings cache: bad JSON for %s: %s", etf_symbol, exc
                )
                continue
        else:
            loaded.append(payload)

    # #512 fail-safe: detect and drop rows that look like pre-fix
    # fraction-shaped weights (SSGA parser previously stored fractions
    # for large holdings and unnormalized-percents for sub-1% holdings —
    # the tell is a total weight sum well below 5). Correct post-fix
    # rows are percentages summing to ~100. If we see a partial-fraction
    # cache row, treat as if empty so the tier chain re-runs the fixed
    # parser. Fires at most once per (etf, ttl) window.
    if loaded:
        weights = [r.get("weight") for r in loaded if r.get("weight") is not None]
        if weights:
            total = sum(w for w in weights if isinstance(w, (int, float)))
            # A well-formed cached SSGA/FMP payload sums to ~100 (percent).
            # An FMP-tier row already-normalized to fractions would sum to
            # ~1 (some paths store post-validator output). Anything in
            # (2, 50) is suspicious — likely the mixed-normalize bug.
            if 2.0 < total < 50.0:
                logger.warning(
                    "etf_holdings cache for %s has suspicious weight sum "
                    "%.2f (expected ~100 or ~1); treating as stale — "
                    "tier chain will re-populate. See #512.",
                    etf_symbol,
                    total,
                )
                return []

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

    try:
        # bd-n3sf: route DELETE+INSERT through replace_rows() for atomicity.
        # Preserves the site-level try/except (D4) — cache write failures
        # log a warning but do NOT break the read path.
        rows_out: list[dict[str, Any]] = []
        for r in rows:
            payload = dict(r)
            payload["data_source"] = data_source
            rows_out.append(
                {
                    "symbol": etf,
                    "data_json": json.dumps(payload, default=str),
                }
            )
        if rows_out:
            replace_rows(
                "etf_holdings",
                "symbol",
                etf,
                rows_out,
                columns=["symbol", "data_json"],
            )
            logger.info(
                "Cached %d etf_holdings rows for %s (source=%s)",
                len(rows_out),
                etf,
                data_source,
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
        fetch_query = query.model_copy(update={"symbol": symbol})
        raw = await FMPEtfHoldingsFetcher.aextract_data(
            fetch_query,
            credentials,
            **kwargs,
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
        # pylint: disable=import-outside-toplevel
        from openbb_fmp_cached.models.etf_holdings_issuer import (  # noqa: PLC0415
            fetch_issuer_holdings,
        )

        return await asyncio.to_thread(fetch_issuer_holdings, symbol)
    except Exception as exc:  # noqa: BLE001
        # bd-3ka: DEBUG (not WARNING) — Tier-3 may rescue, and the
        # aggregate WARNING at aextract_data covers real all-tiers-fail.
        logger.debug("issuer-tier %s failed: %s", symbol, exc)
        return []


async def _try_nport(symbol: str) -> list[dict]:
    """SEC N-PORT tier — authoritative ETF look-through for #1459.

    Wired to ``SecNportDisclosureFetcher`` (same fetcher powering
    ``obb.etf.nport_disclosure(provider="sec")``) so that when the FMP
    and issuer tiers both come up empty, we still return the ~99% of
    ETF NAV that N-PORT filings disclose.

    Row shape returned (dict keys) matches the tier-1/tier-2 contract:
    ``symbol, name, weight, cusip, isin, balance, value, country``.
    ``weight`` is emitted in **percent form (0-100)** to match the
    issuer tier — ``FMPEtfHoldingsData.normalize_percent`` will divide
    by 100 downstream. SEC's own ``normalize_percent`` already scaled
    the raw ``pctVal`` to a fraction; we multiply back so the two
    stages compose to identity.

    Fails soft: any exception (network, EmptyDataError for a symbol
    that has no N-PORT filing, XML parse) is logged at DEBUG and
    returns ``[]`` — matches the ``_try_fmp`` / ``_try_issuer`` pattern
    so a real SEC outage doesn't crash the aggregator.
    """
    if not symbol:
        return []
    try:
        # Lazy import — the SEC provider pulls a heavy XML stack
        # (aiohttp_client_cache, xmltodict, pandas). Not needed unless
        # the two upstream tiers are exhausted.
        # pylint: disable=import-outside-toplevel
        from openbb_sec.models.nport_disclosure import (  # noqa: PLC0415
            SecNportDisclosureFetcher,
        )

        query = SecNportDisclosureFetcher.transform_query({"symbol": symbol})
        raw = await SecNportDisclosureFetcher.aextract_data(query, credentials=None)
        annotated = SecNportDisclosureFetcher.transform_data(query, raw)
        records = getattr(annotated, "result", annotated) or []
    except Exception as exc:  # noqa: BLE001
        # DEBUG (not WARNING) — the aggregate WARNING at aextract_data
        # covers the "all tiers failed" surface. A no-N-PORT-filing
        # symbol is expected (equities, commodity trusts).
        logger.debug("N-PORT tier %s failed: %s", symbol, exc)
        return []

    rows: list[dict] = []
    skipped_no_id = 0
    for rec in records:
        # SecNportDisclosureData or bare dict — accept both.
        d = rec.model_dump() if hasattr(rec, "model_dump") else dict(rec)
        # SEC N-PORT rows often ship without a ``symbol`` (ticker not
        # required in the filing) — many funds file with only ``name`` +
        # ``cusip`` + ``lei`` + ``isin``. Fall through to those in
        # priority order so we don't lose 100% of QQQ (which is what the
        # #1459 bug reported). Only truly-anonymous rows (no ticker, no
        # cusip, no isin) — usually cash pools or derivatives — are
        # dropped.
        sym = d.get("symbol") or d.get("ticker") or d.get("cusip") or d.get("isin")
        if not sym:
            skipped_no_id += 1
            continue
        # SEC's normalize_percent divided pctVal by 100 -> fraction.
        # The issuer tier emits percent (0-100). Match the issuer contract
        # so FMPEtfHoldingsData validation composes correctly.
        weight_fraction = d.get("weight")
        weight_percent = (
            float(weight_fraction) * 100.0
            if isinstance(weight_fraction, (int, float))
            else None
        )
        rows.append(
            {
                "symbol": str(sym).strip().upper(),
                "name": d.get("name"),
                "weight": weight_percent,
                "cusip": d.get("cusip"),
                "isin": d.get("isin"),
                "balance": d.get("balance"),
                "value": d.get("value"),
                "country": d.get("country"),
                "data_source": "sec_nport",
            }
        )
    if skipped_no_id:
        logger.debug(
            "N-PORT tier %s: kept %d rows, skipped %d with no ticker/cusip/isin",
            symbol,
            len(rows),
            skipped_no_id,
        )
    return rows


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
            "— returning empty holdings list",
            symbol,
        )
        return []

    @staticmethod
    def transform_data(
        query: FMPEtfHoldingsQueryParams,  # pylint: disable=unused-argument
        data: list[dict],
        **kwargs: Any,  # pylint: disable=unused-argument
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
                failed_count,
                len(data),
                sample_error or "(no error captured)",
            )
        return validated
