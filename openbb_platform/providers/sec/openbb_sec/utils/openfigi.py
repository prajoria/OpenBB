"""OpenFIGI /v3/mapping client + read-through cache (issue #93).

Owns the ``openfigi_map_cache`` table (R9). Helper lives under
``openbb_sec.utils`` — same package as ``thirteen_f_index.py`` from #89 — so
any future SEC-provider command can call it without a circular ``Tools/``
import. Today's only runtime caller is ``Tools/enrich_cusip_figi.py``.

The vendored fork at ``third_party/openfigi-api/python/example.py`` documents
the v3 contract this module wraps; we never import that script (it isn't on
the installed package path, same one-way rule #89 Q-A applied to ``Tools/``).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPEN_FIGI_API_URL = "https://api.openfigi.com/v3/mapping"
US_COMPOSITE_SET = frozenset({"US"})
OPENFIGI_CACHE_TTL_DAYS = 180
_DEFAULT_USER_AGENT = "OpenBBTechnical/openfigi-enrich/0.1"
_DEFAULT_TIMEOUT_SECS = 30


# ---------------------------------------------------------------------------
# Public TypedDicts / errors
# ---------------------------------------------------------------------------


class OpenFIGIMatch(TypedDict, total=False):
    """Typed view of one OpenFIGI /v3/mapping match (a subset of fields we read)."""

    figi: str
    ticker: str
    name: str
    exchCode: str
    securityType: str
    securityType2: str
    compositeFIGI: str
    marketSector: str


class OpenFIGIError(Exception):
    """Non-recoverable OpenFIGI client error (auth, malformed batch, etc.)."""


# ---------------------------------------------------------------------------
# RateLimitPolicy — keyed vs keyless caps (R2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitPolicy:
    """OpenFIGI per-mode rate limits + batch size.

    Numbers are a conservative reading of the OpenFIGI v3 docs as of June 2026;
    verify against https://www.openfigi.com/api at deploy time and update here
    rather than scattering magic numbers through the call sites.
    """

    requests_per_minute: int
    requests_per_6h: int
    batch_size: int

    @classmethod
    def keyed(cls) -> RateLimitPolicy:
        """Higher caps when ``X-OPENFIGI-APIKEY`` header is present."""
        return cls(requests_per_minute=25, requests_per_6h=25_000, batch_size=100)

    @classmethod
    def keyless(cls) -> RateLimitPolicy:
        """Conservative caps when no API key is supplied."""
        return cls(requests_per_minute=25, requests_per_6h=250, batch_size=10)


# ---------------------------------------------------------------------------
# R3 — select_match() deterministic ladder
# ---------------------------------------------------------------------------


def select_match(job_result: dict) -> OpenFIGIMatch | None:
    """Pick exactly one match from an OpenFIGI /v3/mapping job result.

    Applies the R3 deterministic ladder; returns ``None`` for no-match,
    error payloads, or genuinely ambiguous (>1 surviving US-composite
    Common Stock with distinct compositeFIGI).
    """
    matches = job_result.get("data") or []
    if not matches:
        return None

    # Rung (a): equity + (Common|Preferred) + US composite
    survivors = [
        m
        for m in matches
        if m.get("marketSector") == "Equity"
        and m.get("securityType2") in {"Common Stock", "Preferred Stock"}
        and m.get("exchCode") in US_COMPOSITE_SET
    ]
    if not survivors:
        return None
    if len(survivors) == 1:
        return survivors[0]  # type: ignore[return-value]

    # Rung (b): figi == compositeFIGI
    composite = [m for m in survivors if m.get("figi") and m["figi"] == m.get("compositeFIGI")]
    if len(composite) == 1:
        return composite[0]  # type: ignore[return-value]
    pool = composite or survivors

    # Rung (c): Common over Preferred
    commons = [m for m in pool if m.get("securityType2") == "Common Stock"]
    if len(commons) == 1:
        return commons[0]  # type: ignore[return-value]

    # Rung (d): genuinely ambiguous
    return None


# ---------------------------------------------------------------------------
# Credential resolution (R2) — implemented in Step 8
# ---------------------------------------------------------------------------


def _user_service_credentials() -> Any | None:
    """Return ``user_settings.credentials`` or ``None`` if openbb_core is absent."""
    try:
        from openbb_core.app.service.user_service import UserService  # noqa: PLC0415

        return UserService().default_user_settings.credentials
    except Exception as exc:  # noqa: BLE001
        logger.debug("openbb_core UserService unavailable for OpenFIGI creds: %s", exc)
        return None


def resolve_credentials(api_key_arg: str | None) -> tuple[str | None, str]:
    """Resolve OpenFIGI key per R2: flag -> env -> user_settings -> keyless.

    Returns ``(key_or_None, source_label)`` where source ∈
    ``{"flag", "env", "user_settings", "keyless"}``. Never logs the key value.
    """
    if api_key_arg:
        return api_key_arg, "flag"
    env_key = os.environ.get("OPEN_FIGI_API_KEY")
    if env_key:
        return env_key, "env"
    creds = _user_service_credentials()
    if creds is not None:
        settings_key = getattr(creds, "openfigi_api_key", None)
        if settings_key:
            return settings_key, "user_settings"
    return None, "keyless"


# ---------------------------------------------------------------------------
# Read-through cache (R9) — implemented in Step 9
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Read-through cache (R9): openfigi_map_cache table + helpers
# ---------------------------------------------------------------------------

DDL_OPENFIGI_CACHE = """
CREATE TABLE IF NOT EXISTS openfigi_map_cache (
    id_type       VARCHAR(16)  NOT NULL,
    id_value      VARCHAR(32)  NOT NULL,
    exch_code     VARCHAR(8)   NOT NULL DEFAULT '',
    response_json LONGTEXT     NOT NULL,
    status        VARCHAR(16)  NOT NULL,
    match_count   INT          NOT NULL DEFAULT 0,
    fetched_at    DATETIME     NOT NULL,
    is_valid      TINYINT(1)   NOT NULL DEFAULT 1,
    PRIMARY KEY (id_type, id_value, exch_code),
    KEY idx_fetched_at (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _db():
    """Return the fmp_cached database module (lazy import).

    Mirrors the pattern in #89's ``thirteen_f_index._db()``: the SEC provider
    intentionally does not import fmp_cached at module top-level so a
    fmp-cached-less install still loads the module (callers handle the
    ImportError as "index unavailable -> graceful empty").
    """
    from openbb_fmp_cached.utils import database as _database  # noqa: PLC0415

    return _database


def _classify(job_result: dict) -> tuple[str, int]:
    """Classify a raw /v3/mapping job result into (status, match_count)."""
    if "error" in job_result:
        return ("error", 0)
    data = job_result.get("data") or []
    if not data:
        return ("no_match", 0)
    return ("ok", len(data))


def init_openfigi_cache() -> None:
    """Create ``openfigi_map_cache`` if absent (idempotent)."""
    _db().execute_query(DDL_OPENFIGI_CACHE)
    logger.info("openfigi_map_cache table ready")


def cache_get(id_value: str, *, id_type: str = "ID_CUSIP", exch_code: str = "") -> dict | None:
    """Return the cached raw job result if fresh+valid, else ``None``."""
    try:
        rows = _db().execute_query(
            "SELECT response_json, fetched_at, is_valid "
            "FROM openfigi_map_cache WHERE id_type=%s AND id_value=%s AND exch_code=%s",
            (id_type, id_value, exch_code),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("openfigi cache_get(%s) failed: %s", id_value, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    if not row.get("is_valid"):
        return None
    fetched_at = row.get("fetched_at")
    if fetched_at is None:
        return None
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=OPENFIGI_CACHE_TTL_DAYS
    )
    if fetched_at < cutoff:
        return None
    raw = row.get("response_json")
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def cache_put(
    id_value: str,
    job_result: dict,
    *,
    id_type: str = "ID_CUSIP",
    exch_code: str = "",
) -> None:
    """Upsert one raw job result (idempotent; L7)."""
    status, count = _classify(job_result)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = """
    INSERT INTO openfigi_map_cache
        (id_type, id_value, exch_code, response_json, status, match_count, fetched_at, is_valid)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
    ON DUPLICATE KEY UPDATE
        response_json = VALUES(response_json),
        status        = VALUES(status),
        match_count   = VALUES(match_count),
        fetched_at    = VALUES(fetched_at),
        is_valid      = 1
    """
    _db().execute_many(
        sql,
        [(id_type, id_value, exch_code, json.dumps(job_result), status, count, now)],
    )


# ---------------------------------------------------------------------------
# map_cusips() — implemented in Step 11
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# map_cusips() — public entry point: cache-aware batch /v3/mapping client
# ---------------------------------------------------------------------------


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _post_batch(jobs: list[dict], api_key: str | None, max_retries: int = 5) -> list[dict]:
    """POST one batch of jobs to /v3/mapping; honor Retry-After on 429."""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": _DEFAULT_USER_AGENT,
    }
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    backoff = 1.0
    for attempt in range(max_retries):
        resp = requests.post(
            OPEN_FIGI_API_URL,
            json=jobs,
            headers=headers,
            timeout=_DEFAULT_TIMEOUT_SECS,
        )
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After") if resp.headers else None
            wait = float(retry_after) if retry_after else backoff
            logger.info(
                "OpenFIGI 429; sleeping %.1fs (attempt %d/%d)",
                wait, attempt + 1, max_retries,
            )
            time.sleep(wait)
            backoff = min(backoff * 2, 60.0)
            continue
        resp.raise_for_status()
        return resp.json()
    raise OpenFIGIError(
        f"OpenFIGI /v3/mapping retry budget exhausted after {max_retries} 429s"
    )


def map_cusips(
    cusips: list[str],
    *,
    api_key: str | None = None,
    policy: RateLimitPolicy | None = None,
    refresh: bool = False,
) -> dict[str, dict]:
    """Map a list of CUSIPs to their raw OpenFIGI /v3/mapping job results.

    Read-through cache (R9): cache hits short-circuit the API; misses are
    batched per ``policy.batch_size`` and upserted into
    ``openfigi_map_cache``. Returns ``{cusip: raw_job_result}`` (cache hits
    + freshly-fetched, merged). Logs hit/miss/store counts at end.
    """
    policy = policy or (
        RateLimitPolicy.keyed() if api_key else RateLimitPolicy.keyless()
    )
    init_openfigi_cache()

    hits = 0
    misses: list[str] = []
    results: dict[str, dict] = {}
    if not refresh:
        for cusip in cusips:
            hit = cache_get(cusip)
            if hit is not None:
                results[cusip] = hit
                hits += 1
            else:
                misses.append(cusip)
    else:
        misses = list(cusips)

    stores = 0
    for batch in _chunked(misses, policy.batch_size):
        jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        responses = _post_batch(jobs, api_key=api_key)
        for cusip, job_result in zip(batch, responses, strict=True):
            cache_put(cusip, job_result)
            stores += 1
            results[cusip] = job_result
        # Crude per-minute rate respect: one sleep between batches.
        # RateLimitPolicy is the lever (single place to update on cap changes).
        time.sleep(60.0 / max(1, policy.requests_per_minute))

    logger.info(
        "openfigi map_cusips: cache hits=%d misses=%d stores=%d",
        hits, len(misses), stores,
    )
    return results
