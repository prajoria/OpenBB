"""Cached index_constituents model for FMP with MySQL persistence.

This module provides database-cached access to index constituents data (S&P 500,
Dow Jones, NASDAQ) from FMP. Data is stored in the `sp500_constituents` table.
The table is created if it doesn't exist, but the database is NOT created
(relies on existing database configured in user_settings.json).

Features:
    - Creates sp500_constituents table if needed (no database creation)
    - Reads from sp500_constituents table in MySQL
    - Configurable cache TTL (default: 7 days for constituent lists)
    - Supports sp500, dowjones, nasdaq indices
    - Historical additions/removals support
    - Falls back to direct FMP API call on DB errors
    - populate_cache() for seeding from API or another database
    - get_cache_stats() for table statistics

Usage (provider):
    obb.index.constituents(symbol="sp500", provider="fmp_cached")

Usage (standalone):
    from openbb_fmp_cached.models.index_constituents import populate_cache, get_cache_stats
    populate_cache(source="api")          # seed from FMP API
    populate_cache(source="copy",         # copy from another database
                   source_database="fmp_cache")
    stats = get_cache_stats()             # get row counts / sector breakdown
"""

import json
import logging
import os
from datetime import (
    date as dateType,
    datetime,
    timedelta,
)
from typing import Any, Literal

import pymysql
import pymysql.cursors
import requests
from dateutil import parser
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.index_constituents import (
    IndexConstituentsData,
    IndexConstituentsQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from pydantic import Field, field_validator

from openbb_fmp_cached.utils.database import execute_many, execute_query, init_database

logger = logging.getLogger(__name__)

# Cache TTL: how many days before we re-fetch constituent data from the API
CACHE_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Query Params
# ---------------------------------------------------------------------------


class FMPCachedIndexConstituentsQueryParams(IndexConstituentsQueryParams):
    """FMP Cached Index Constituents Query Parameters.

    Source: https://site.financialmodelingprep.com/developer/docs#sp-500
    """

    symbol: Literal["dowjones", "sp500", "nasdaq"] = Field(
        default="sp500",
    )
    historical: bool = Field(
        default=False,
        description="Flag to retrieve historical removals and additions.",
    )


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------


class FMPCachedIndexConstituentsData(IndexConstituentsData):
    """FMP Cached Index Constituents Data."""

    __alias_dict__ = {
        "headquarter": "headQuarter",
        "date_added": "dateFirstAdded",
        "industry": "subSector",
        "name": "addedSecurity",
        "removed_symbol": "removedTicker",
        "removed_name": "removedSecurity",
    }

    sector: str | None = Field(
        default=None,
        description="Sector classification for the constituent company in the index.",
    )
    industry: str | None = Field(
        default=None,
        description="Industry classification for the constituent company in the index.",
    )
    headquarter: str | None = Field(
        default=None,
        description="Location of the company's headquarters.",
    )
    date_added: dateType | str | None = Field(
        default=None,
        description="Date the constituent company was added to the index.",
    )
    cik: str | None = Field(
        description=DATA_DESCRIPTIONS.get("cik", ""),
        default=None,
        coerce_numbers_to_str=True,
    )
    founded: dateType | str | None = Field(
        default=None,
        description="When the company was founded.",
    )
    removed_symbol: str | None = Field(
        default=None,
        description="Symbol of the company removed from the index.",
    )
    removed_name: str | None = Field(
        default=None,
        description="Name of the company removed from the index.",
    )
    reason: str | None = Field(
        default=None,
        description="Reason for the removal from the index.",
    )
    date: dateType | None = Field(
        default=None,
        description="Date of the historical constituent data.",
    )

    @field_validator("date_added", "founded", "date", mode="before", check_fields=False)
    @classmethod
    def _parse_date(cls, v):
        """Parse date fields flexibly."""
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v)).date()
        except (ValueError, TypeError):
            try:
                return parser.parse(str(v)).date()
            except Exception:
                return str(v)

    @field_validator(
        "removed_symbol", "removed_name", "reason", mode="before", check_fields=False
    )
    @classmethod
    def _clean_empty_strings(cls, v):
        """Clean empty string values."""
        if not v or v in ("''", "", "None"):
            return None
        return v


# ---------------------------------------------------------------------------
# Table DDL & DML
# ---------------------------------------------------------------------------

TABLE_NAME = "sp500_constituents"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sp500_constituents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    security VARCHAR(200) NOT NULL,
    gics_sector VARCHAR(100) DEFAULT NULL,
    gics_sub_industry VARCHAR(150) DEFAULT NULL,
    headquarters_location VARCHAR(200) DEFAULT NULL,
    date_added DATE DEFAULT NULL,
    cik VARCHAR(10) DEFAULT NULL,
    founded VARCHAR(50) DEFAULT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active TINYINT(1) DEFAULT 1,
    UNIQUE KEY uq_symbol (symbol),
    KEY idx_sector (gics_sector),
    KEY idx_active (is_active),
    KEY idx_fetched (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

INSERT_SQL = """
INSERT INTO sp500_constituents
    (symbol, security, gics_sector, gics_sub_industry,
     headquarters_location, date_added, cik, founded, fetched_at, is_active)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    security = VALUES(security),
    gics_sector = VALUES(gics_sector),
    gics_sub_industry = VALUES(gics_sub_industry),
    headquarters_location = VALUES(headquarters_location),
    date_added = VALUES(date_added),
    cik = VALUES(cik),
    founded = VALUES(founded),
    updated_at = CURRENT_TIMESTAMP,
    is_active = VALUES(is_active)
"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _ensure_table():
    """Create the sp500_constituents table if it doesn't exist."""
    try:
        execute_query(CREATE_TABLE_SQL)
    except Exception as e:
        logger.warning(f"Could not ensure sp500_constituents table: {e}")


def _cache_is_fresh(index_name: str) -> bool:
    """Check whether cached data for the given index is still within TTL."""
    query = """
    SELECT MAX(fetched_at) AS last_fetch
    FROM sp500_constituents
    WHERE is_active = 1
    """
    try:
        rows = execute_query(query)
        if rows and rows[0].get("last_fetch"):
            last_fetch = rows[0]["last_fetch"]
            age = datetime.now() - last_fetch
            if age < timedelta(days=CACHE_TTL_DAYS):
                logger.info(
                    f"Cache HIT for {index_name} constituents "
                    f"(age={age.days}d, TTL={CACHE_TTL_DAYS}d)"
                )
                return True
            logger.info(
                f"Cache STALE for {index_name} constituents "
                f"(age={age.days}d, TTL={CACHE_TTL_DAYS}d)"
            )
        else:
            logger.info(f"Cache MISS for {index_name} constituents (no data)")
    except Exception as e:
        logger.warning(f"Cache freshness check failed: {e}")
    return False


def _read_from_cache(index_name: str) -> list[dict[str, Any]]:
    """Read constituents from the existing sp500_constituents table."""
    query = """
    SELECT symbol, security, gics_sector, gics_sub_industry,
           headquarters_location, date_added, cik, founded
    FROM sp500_constituents
    WHERE is_active = 1
    ORDER BY symbol
    """
    rows = execute_query(query)
    results = []
    for row in rows:
        results.append(
            {
                "symbol": row["symbol"],
                "name": row["security"],
                "sector": row.get("gics_sector"),
                "subSector": row.get("gics_sub_industry"),
                "headQuarter": row.get("headquarters_location"),
                "dateFirstAdded": (
                    row["date_added"].strftime("%Y-%m-%d")
                    if row.get("date_added")
                    else None
                ),
                "cik": row.get("cik"),
                "founded": row.get("founded"),
            }
        )
    return results


def _store_in_cache(index_name: str, api_data: list[dict[str, Any]]) -> None:
    """Store API response in the existing sp500_constituents table."""
    if not api_data:
        return

    batch = []
    now = datetime.now()
    for d in api_data:
        date_added = _safe_parse_date(d.get("dateFirstAdded") or d.get("date_added"))
        batch.append(
            (
                d.get("symbol", ""),
                d.get("name") or d.get("companyName") or d.get("addedSecurity", ""),
                d.get("sector"),
                d.get("subSector") or d.get("industry"),
                d.get("headQuarter") or d.get("headquarter"),
                date_added,
                str(d["cik"]) if d.get("cik") else None,
                d.get("founded"),
                now,
                1,  # is_active
            )
        )

    try:
        rows_affected = execute_many(INSERT_SQL, batch)
        logger.info(f"Stored {rows_affected} constituents for {index_name} in cache")
    except Exception as e:
        logger.warning(f"Failed to store {index_name} constituents in cache: {e}")


def _safe_parse_date(val) -> dateType | None:
    """Parse a date value safely, returning None on failure."""
    if not val:
        return None
    try:
        if isinstance(val, dateType):
            return val
        return parser.parse(str(val)).date()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API: populate_cache / get_cache_stats
# ---------------------------------------------------------------------------


def _get_db_config() -> dict[str, Any]:
    """Read MySQL connection config from OpenBB user_settings.json or env vars.

    User and password have no hardcoded defaults; they must be supplied via
    ``user_settings.json`` (``mysql_user``/``mysql_password``) or the
    ``DB_USER``/``DB_PASSWORD`` environment variables. Raises ``ValueError``
    when missing rather than falling back to a committed credential pair.
    """
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    host, port = "localhost", 3306
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    try:
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                settings = json.load(f)
                creds = settings.get("credentials", {})
                host = creds.get("mysql_host", host)
                port = int(creds.get("mysql_port", port))
                user = creds.get("mysql_user", user)
                password = creds.get("mysql_password", password)
    except Exception:
        pass
    missing = [n for n, v in (("user", user), ("password", password)) if not v]
    if missing:
        raise ValueError(
            "Missing MySQL credential(s): "
            f"{', '.join(missing)}. Configure 'mysql_user'/'mysql_password' in "
            "~/.openbb_platform/user_settings.json or set DB_USER/DB_PASSWORD. "
            "No default credentials are provided."
        )
    return {"host": host, "port": port, "user": user, "password": password}


def _get_api_key() -> str:
    """Resolve FMP API key from .env or user_settings.json."""
    # Try environment first (covers .env via dotenv)
    api_key = os.getenv("FMP_API_KEY") or os.getenv("FMP_CACHED_API_KEY")
    if api_key:
        return api_key

    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    try:
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                settings = json.load(f)
                creds = settings.get("credentials", {})
                return creds.get("fmp_api_key") or creds.get("fmp_cached_api_key", "")
    except Exception:
        pass
    return ""


def _get_raw_connection(database: str) -> "pymysql.Connection":
    """Get a raw pymysql connection to a specific database."""
    cfg = _get_db_config()
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        user=cfg["user"],
        password=cfg["password"],
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _fetch_from_api_sync() -> list[dict[str, Any]]:
    """Fetch S&P 500 constituents from FMP API (synchronous)."""
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("No FMP API key found in environment or user_settings.json")

    url = "https://financialmodelingprep.com/stable/sp500-constituent/"
    logger.info("Fetching S&P 500 constituents from FMP API")
    # apikey via params= keeps it out of URL strings that could land in
    # HTTPError.url, tracebacks, or proxy access logs (bd-6641 / bd-ygtq).
    response = requests.get(url, params={"apikey": api_key}, timeout=30)
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict) and data.get("Error Message"):
        raise RuntimeError(f"FMP API error: {data['Error Message']}")

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected API response type: {type(data)}")

    logger.info(f"Received {len(data)} constituents from FMP API")
    return data


def _copy_from_source_db(source_database: str) -> list[dict[str, Any]]:
    """Read sp500_constituents rows from another MySQL database."""
    logger.info(f"Copying from {source_database}.sp500_constituents")
    conn = _get_raw_connection(source_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM sp500_constituents WHERE is_active = 1 ORDER BY symbol"
            )
            rows: list[dict[str, Any]] = list(cur.fetchall())  # type: ignore[arg-type]
        logger.info(f"Read {len(rows)} rows from {source_database}")
        return rows
    finally:
        conn.close()


def populate_cache(
    source: str = "api",
    source_database: str = "fmp_cache",
    target_database: str | None = None,
) -> dict[str, Any]:
    """Populate the sp500_constituents table from API or another database.

    This is the authoritative entry point for seeding / refreshing the
    sp500_constituents cache.  It ensures the table exists, fetches data
    from the chosen source, upserts, and returns a stats dict.

    Args:
        source: "api" to fetch from FMP, "copy" to copy from source_database.
        source_database: Database to copy from when source="copy" (default: "fmp_cache").
        target_database: Override the target database name.  If None, uses the
                         database configured in DatabaseConfig (respects
                         FMP_CACHE_TEST_MODE).

    Returns:
        dict with keys: total_rows, sectors, top_sectors, source, database
    """
    # Ensure table in target DB via the provider's own database layer
    init_database(auto_create=False)
    _ensure_table()

    # Resolve target database name
    if target_database is None:
        from openbb_fmp_cached.utils.database import DatabaseConfig

        target_database = DatabaseConfig().config["database"]

    assert target_database is not None  # guaranteed by DatabaseConfig fallback
    conn = _get_raw_connection(target_database)
    cur = conn.cursor()

    try:
        # Fetch data from chosen source
        if source == "copy":
            rows = _copy_from_source_db(source_database)
            batch = [
                (
                    row["symbol"],
                    row["security"],
                    row.get("gics_sector"),
                    row.get("gics_sub_industry"),
                    row.get("headquarters_location"),
                    row.get("date_added"),
                    row.get("cik"),
                    row.get("founded"),
                    row.get("fetched_at", datetime.now()),
                    row.get("is_active", 1),
                )
                for row in rows
            ]
        elif source == "api":
            api_data = _fetch_from_api_sync()
            batch = [
                (
                    d.get("symbol", ""),
                    d.get("name") or d.get("companyName", ""),
                    d.get("sector"),
                    d.get("subSector") or d.get("industry"),
                    d.get("headQuarter") or d.get("headquarter"),
                    _safe_parse_date(d.get("dateFirstAdded") or d.get("date_added")),
                    str(d["cik"]) if d.get("cik") else None,
                    d.get("founded"),
                    datetime.now(),
                    1,
                )
                for d in api_data
                if d.get("symbol")
            ]
        else:
            raise ValueError(f"Unknown source: {source!r}  (use 'api' or 'copy')")

        # Upsert
        logger.info(f"Upserting {len(batch)} rows into {target_database}.{TABLE_NAME}")
        cur.executemany(INSERT_SQL, batch)
        conn.commit()

        # Return stats
        return get_cache_stats(target_database)

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def get_cache_stats(database: str | None = None) -> dict[str, Any]:
    """Return statistics about the sp500_constituents table.

    Args:
        database: Database name to query.  Defaults to configured database.

    Returns:
        dict with keys: total_rows, sectors, top_sectors, database
    """
    if database is None:
        from openbb_fmp_cached.utils.database import DatabaseConfig

        database = DatabaseConfig().config["database"]

    assert database is not None  # guaranteed by DatabaseConfig fallback
    conn = _get_raw_connection(database)
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) AS cnt FROM sp500_constituents")
        row = cur.fetchone()
        total_rows = row["cnt"] if row else 0  # type: ignore[index]

        cur.execute("SELECT COUNT(DISTINCT gics_sector) AS cnt FROM sp500_constituents")
        row = cur.fetchone()
        sectors = row["cnt"] if row else 0  # type: ignore[index]

        cur.execute(
            "SELECT gics_sector, COUNT(*) AS cnt FROM sp500_constituents "
            "WHERE is_active = 1 GROUP BY gics_sector ORDER BY cnt DESC LIMIT 5"
        )
        top_sectors = cur.fetchall()

        return {
            "database": database,
            "total_rows": total_rows,
            "sectors": sectors,
            "top_sectors": top_sectors,
        }
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# FMP API direct fetch (no dependency on openbb_fmp provider)
# ---------------------------------------------------------------------------


async def _fetch_from_fmp_api(
    query: FMPCachedIndexConstituentsQueryParams,
    credentials: dict[str, str] | None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Fetch index constituents directly from FMP API."""
    from openbb_core.provider.utils.helpers import amake_request

    api_key = credentials.get("fmp_api_key") if credentials else ""
    if not api_key:
        raise ValueError("No FMP API key provided")

    base_url = "https://financialmodelingprep.com/stable"
    historical = "historical-" if query.historical else ""
    url = f"{base_url}/{historical}{query.symbol}-constituent/"

    logger.info(f"Fetching {query.symbol} constituents from FMP API")

    async def _callback(response, _):
        if response.status != 200:
            msg = await response.text()
            raise RuntimeError(f"FMP API error {response.status}: {msg}")
        return await response.json()

    # apikey via params= keeps it out of URL strings that could land in
    # tracebacks or proxy access logs (bd-6641 / bd-ygtq).
    data = await amake_request(
        url, response_callback=_callback, params={"apikey": api_key}, **kwargs
    )

    if isinstance(data, dict) and data.get("Error Message"):
        raise RuntimeError(f"FMP API error: {data['Error Message']}")

    if not isinstance(data, list):
        return []

    return data


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------


class FMPCachedIndexConstituentsFetcher(
    Fetcher[
        FMPCachedIndexConstituentsQueryParams,
        list[FMPCachedIndexConstituentsData],
    ]
):
    """FMP Cached Index Constituents Fetcher with MySQL persistence."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FMPCachedIndexConstituentsQueryParams:
        """Transform the query params."""
        return FMPCachedIndexConstituentsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FMPCachedIndexConstituentsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Extract index constituents with database caching."""

        # Fix credential mapping: fmp_cached_api_key -> fmp_api_key
        if credentials and "fmp_cached_api_key" in credentials:
            fmp_credentials = {"fmp_api_key": credentials["fmp_cached_api_key"]}
        else:
            fmp_credentials = credentials

        # Historical queries always go to API (not cached)
        if query.historical:
            logger.info("Historical query - bypassing cache")
            return await _fetch_from_fmp_api(query, fmp_credentials, **kwargs)

        # Initialize database connection (do NOT create database, only tables)
        try:
            init_database(auto_create=False)
            _ensure_table()
        except Exception as e:
            logger.warning(f"Database init failed, falling back to API: {e}")
            return await _fetch_from_fmp_api(query, fmp_credentials, **kwargs)

        index_name = query.symbol  # "sp500", "dowjones", "nasdaq"

        # Check cache freshness
        if _cache_is_fresh(index_name):
            cached = _read_from_cache(index_name)
            if cached:
                logger.info(
                    f"Returning {len(cached)} cached constituents for {index_name}"
                )
                return cached

        # Cache miss or stale - fetch from API
        try:
            api_data = await _fetch_from_fmp_api(query, fmp_credentials, **kwargs)
            if api_data:
                _store_in_cache(index_name, api_data)
                logger.info(
                    f"Fetched and cached {len(api_data)} constituents for {index_name}"
                )
            return api_data
        except Exception as e:
            logger.warning(f"API fetch failed for {index_name}: {e}")
            # Try serving stale cache as fallback
            cached = _read_from_cache(index_name)
            if cached:
                logger.info(
                    f"Serving stale cache ({len(cached)} rows) for {index_name}"
                )
                return cached
            raise

    @staticmethod
    def transform_data(
        query: FMPCachedIndexConstituentsQueryParams,
        data: list[dict[str, Any]],
        **kwargs: Any,
    ) -> list[FMPCachedIndexConstituentsData]:
        """Transform raw data into FMPCachedIndexConstituentsData objects."""
        return [FMPCachedIndexConstituentsData.model_validate(d) for d in data]
