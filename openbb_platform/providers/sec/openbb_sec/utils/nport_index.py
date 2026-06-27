"""SEC Form N-PORT MySQL index (#99 T2).

Mirrors the #89 ``thirteen_f_index.py`` pattern verbatim: single source of
truth for the 4 ``sec_nport_*`` table DDL, idempotent write helpers, and
pure-DB read helpers consumed by ``fmp_cached._try_nport`` (T6) and the
ingest CLI (T5).

4 tables (L4):
  * ``sec_nport_filings`` — one row per accession (per G2, raw XML metadata
    lives here, not on holdings).
  * ``sec_nport_holdings`` — one row per holding; PK ``(accession_number,
    holding_key)`` where ``holding_key`` is content-derived per G4
    (``COALESCE(cusip, isin, lei, sha1(issuer_name||asset_category))`` with
    ``_lotN`` collision suffix appended by the parser at T3).
  * ``sec_nport_fund_map`` — ticker → (cik, series_id, class_id) resolver
    (§2.3). Seeded with the 11 GICS sector SPDRs at ``init_nport_index``.
  * ``sec_nport_ingest_runs`` — observability manifest + bulk-mode resume
    cursor (``last_accession_seen`` per G6).

Read helpers enforce L10 (as-of read semantics) and L11 (amendment
supersession — ``NPORT-P/A`` for the same ``(cik, series_id, period)``
supersedes prior ``NPORT-P``).

L12: every row returned by ``holdings_for_fund`` carries ``report_date``
plus a derived ``data_age_days`` so consumers can surface the
quarterly-snapshot staleness.

DB target: ``openbb_fmp_cache_test`` (same DB as ``sec_13f_cusip_map``
so cross-table CUSIP joins from N-PORT holdings to 13F resolver tables
work without cross-database plumbing).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provenance enum (L8)
# ---------------------------------------------------------------------------

SOURCE_NPORT_BULK = "sec_nport_bulk"
SOURCE_NPORT_SUBMISSIONS = "sec_nport_submissions"
SOURCE_NPORT_ARCHIVE = "sec_nport_archive"
SOURCE_SEED = "seed"
SOURCE_OPENFIGI_NPORT_ISIN = "openfigi_nport_isin"


# ---------------------------------------------------------------------------
# DDL (single source of truth — L4)
# ---------------------------------------------------------------------------

DDL_FILINGS = """
CREATE TABLE IF NOT EXISTS sec_nport_filings (
    accession_number   VARCHAR(32)  NOT NULL,
    cik                CHAR(10)     NOT NULL,
    series_id          VARCHAR(16)  NOT NULL,
    class_id           VARCHAR(16)  NULL,
    report_date        DATE         NOT NULL,
    filing_date        DATETIME     NULL,
    is_amendment       TINYINT(1)   NOT NULL DEFAULT 0,
    source             VARCHAR(32)  NOT NULL,
    ingested_at        DATETIME     NOT NULL,
    raw_xml_url        VARCHAR(512) NULL,
    raw_xml_sha256     CHAR(64)     NULL,
    raw_xml_blob       LONGTEXT     NULL,
    PRIMARY KEY (accession_number),
    KEY idx_cik_series_report (cik, series_id, report_date),
    KEY idx_report_date (report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_HOLDINGS = """
CREATE TABLE IF NOT EXISTS sec_nport_holdings (
    accession_number   VARCHAR(32)   NOT NULL,
    holding_key        VARCHAR(64)   NOT NULL,
    issuer_name        VARCHAR(255)  NOT NULL,
    ticker             VARCHAR(16)   NULL,
    cusip              CHAR(9)       NULL,
    isin               VARCHAR(12)   NULL,
    lei                CHAR(20)      NULL,
    asset_category     VARCHAR(16)   NULL,
    units              DECIMAL(24,6) NULL,
    value_usd          DECIMAL(20,2) NULL,
    pct_nav            DECIMAL(12,8) NULL,
    payoff_direction   VARCHAR(8)    NULL,
    derivative_flag    TINYINT(1)    NOT NULL DEFAULT 0,
    PRIMARY KEY (accession_number, holding_key),
    KEY idx_cusip (cusip),
    KEY idx_isin (isin),
    KEY idx_ticker (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_FUND_MAP = """
CREATE TABLE IF NOT EXISTS sec_nport_fund_map (
    ticker             VARCHAR(16)  NOT NULL,
    cik                CHAR(10)     NOT NULL,
    series_id          VARCHAR(16)  NOT NULL,
    class_id           VARCHAR(16)  NULL,
    fund_name          VARCHAR(255) NULL,
    is_etf             TINYINT(1)   NOT NULL DEFAULT 0,
    is_uit             TINYINT(1)   NOT NULL DEFAULT 0,
    source             VARCHAR(32)  NOT NULL,
    updated_at         DATETIME     NOT NULL,
    PRIMARY KEY (ticker, series_id),
    KEY idx_cik (cik),
    KEY idx_series (series_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_INGEST_RUNS = """
CREATE TABLE IF NOT EXISTS sec_nport_ingest_runs (
    id                    BIGINT       NOT NULL AUTO_INCREMENT,
    quarter               CHAR(7)      NOT NULL,
    mode                  VARCHAR(16)  NOT NULL,
    ingested_at           DATETIME     NOT NULL,
    source_zip_sha256     CHAR(64)     NULL,
    fund_count            BIGINT       NULL,
    holding_count         BIGINT       NULL,
    last_member           VARCHAR(255) NULL,
    last_accession_seen   VARCHAR(32)  NULL,
    PRIMARY KEY (id),
    KEY idx_quarter (quarter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

ALL_DDL = (DDL_FILINGS, DDL_HOLDINGS, DDL_FUND_MAP, DDL_INGEST_RUNS)


# ---------------------------------------------------------------------------
# SPDR seed (§2.3) — 11 GICS sector SPDRs, mirrors #89's B4 seed pattern
# ---------------------------------------------------------------------------

# (ticker: (cik, series_id, fund_name, is_etf))
SPDR_FUND_MAP: dict[str, tuple[str, str, str, bool]] = {
    "XLB": ("0000884394", "S000004305", "Materials Select Sector SPDR Fund", True),
    "XLC": ("0000884394", "S000058281", "Communication Services Select Sector SPDR Fund", True),
    "XLE": ("0000884394", "S000004307", "Energy Select Sector SPDR Fund", True),
    "XLF": ("0000884394", "S000004308", "Financial Select Sector SPDR Fund", True),
    "XLI": ("0000884394", "S000004309", "Industrial Select Sector SPDR Fund", True),
    "XLK": ("0000884394", "S000004310", "Technology Select Sector SPDR Fund", True),
    "XLP": ("0000884394", "S000004311", "Consumer Staples Select Sector SPDR Fund", True),
    "XLRE": ("0000884394", "S000050817", "Real Estate Select Sector SPDR Fund", True),
    "XLU": ("0000884394", "S000004312", "Utilities Select Sector SPDR Fund", True),
    "XLV": ("0000884394", "S000004313", "Health Care Select Sector SPDR Fund", True),
    "XLY": ("0000884394", "S000004314", "Consumer Discretionary Select Sector SPDR Fund", True),
}


# ---------------------------------------------------------------------------
# DB access (lazy import — mirrors thirteen_f_index._db pattern)
# ---------------------------------------------------------------------------


def _db():
    """Return the fmp_cached database module (lazy import).

    Raises ``ImportError`` if fmp_cached is not installed; read-helper callers
    catch that as "index unavailable → graceful empty".
    """
    from openbb_fmp_cached.utils import database  # noqa: PLC0415

    return database


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def init_nport_index() -> bool:
    """Create the 4 N-PORT tables and seed the SPDR fund map.

    Idempotent: re-running is safe. Returns ``True`` on success,
    ``False`` if the database is unreachable.
    """
    try:
        db = _db()
        for ddl in ALL_DDL:
            db.execute_query(ddl)
        # Seed the 11 SPDRs so holdings_for_fund("XLK") resolves on day 1
        seed_fund_map()
        logger.info(
            "N-PORT index tables ready "
            "(sec_nport_filings, sec_nport_holdings, sec_nport_fund_map, sec_nport_ingest_runs)"
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not initialize N-PORT index tables: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Write helpers (used by Tools/ingest_sec_nport.py at T5 + T6 wiring)
# ---------------------------------------------------------------------------


def seed_fund_map(seed: dict[str, tuple[str, str, str, bool]] | None = None) -> int:
    """Upsert the SPDR seed rows into ``sec_nport_fund_map``.

    Each seed entry becomes an 8-tuple matching ``upsert_fund_map``'s contract.
    Idempotent: re-running upserts the same rows (L5).
    Returns the number of rows written.
    """
    seed = seed if seed is not None else SPDR_FUND_MAP
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        (ticker, cik, series_id, None, fund_name, is_etf, SOURCE_SEED, now)
        for ticker, (cik, series_id, fund_name, is_etf) in seed.items()
    ]
    return upsert_fund_map(rows)


def upsert_filing(rows: Iterable[tuple]) -> int:
    """Upsert ``sec_nport_filings`` rows.

    Each row is a 12-tuple: ``(accession_number, cik, series_id, class_id,
    report_date, filing_date, is_amendment, source, ingested_at,
    raw_xml_url, raw_xml_sha256, raw_xml_blob)``.

    Idempotent via PK ``accession_number``: re-ingesting the same filing
    updates the existing row without creating duplicates (L5).
    """
    rows = list(rows)
    if not rows:
        return 0
    for r in rows:
        if len(r) != 12:
            raise ValueError(f"upsert_filing row must be 12-tuple, got {len(r)}")
    sql = """
    INSERT INTO sec_nport_filings
        (accession_number, cik, series_id, class_id,
         report_date, filing_date, is_amendment, source, ingested_at,
         raw_xml_url, raw_xml_sha256, raw_xml_blob)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        cik             = VALUES(cik),
        series_id       = VALUES(series_id),
        class_id        = COALESCE(VALUES(class_id), class_id),
        report_date     = VALUES(report_date),
        filing_date     = COALESCE(VALUES(filing_date), filing_date),
        is_amendment    = VALUES(is_amendment),
        source          = VALUES(source),
        ingested_at     = VALUES(ingested_at),
        raw_xml_url     = COALESCE(VALUES(raw_xml_url), raw_xml_url),
        raw_xml_sha256  = COALESCE(VALUES(raw_xml_sha256), raw_xml_sha256),
        raw_xml_blob    = COALESCE(VALUES(raw_xml_blob), raw_xml_blob)
    """
    return _db().execute_many(sql, rows)


def upsert_holdings(rows: Iterable[tuple]) -> int:
    """Upsert ``sec_nport_holdings`` rows.

    Each row is a 13-tuple: ``(accession_number, holding_key, issuer_name,
    ticker, cusip, isin, lei, asset_category, units, value_usd, pct_nav,
    payoff_direction, derivative_flag)``.

    Idempotent via PK ``(accession_number, holding_key)`` where
    ``holding_key`` is content-derived per G4 — re-parsing the same accession
    yields the same rows regardless of XML element order (no parse-order
    ordinal collisions).
    """
    rows = list(rows)
    if not rows:
        return 0
    for r in rows:
        if len(r) != 13:
            raise ValueError(f"upsert_holdings row must be 13-tuple, got {len(r)}")
    sql = """
    INSERT INTO sec_nport_holdings
        (accession_number, holding_key, issuer_name,
         ticker, cusip, isin, lei, asset_category,
         units, value_usd, pct_nav, payoff_direction, derivative_flag)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        issuer_name      = VALUES(issuer_name),
        ticker           = COALESCE(VALUES(ticker), ticker),
        cusip            = COALESCE(VALUES(cusip), cusip),
        isin             = COALESCE(VALUES(isin), isin),
        lei              = COALESCE(VALUES(lei), lei),
        asset_category   = COALESCE(VALUES(asset_category), asset_category),
        units            = VALUES(units),
        value_usd        = VALUES(value_usd),
        pct_nav          = VALUES(pct_nav),
        payoff_direction = COALESCE(VALUES(payoff_direction), payoff_direction),
        derivative_flag  = VALUES(derivative_flag)
    """
    return _db().execute_many(sql, rows)


def upsert_fund_map(rows: Iterable[tuple]) -> int:
    """Upsert ``sec_nport_fund_map`` rows.

    Each row is an 8-tuple: ``(ticker, cik, series_id, class_id, fund_name,
    is_etf, source, updated_at)``.

    Idempotent via composite PK ``(ticker, series_id)``: one ticker can map
    to multiple share classes via distinct series IDs (rare but valid).
    """
    rows = list(rows)
    if not rows:
        return 0
    for r in rows:
        if len(r) != 8:
            raise ValueError(f"upsert_fund_map row must be 8-tuple, got {len(r)}")
    sql = """
    INSERT INTO sec_nport_fund_map
        (ticker, cik, series_id, class_id, fund_name, is_etf, source, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        cik         = VALUES(cik),
        class_id    = COALESCE(VALUES(class_id), class_id),
        fund_name   = COALESCE(VALUES(fund_name), fund_name),
        is_etf      = VALUES(is_etf),
        source      = VALUES(source),
        updated_at  = VALUES(updated_at)
    """
    return _db().execute_many(sql, rows)


def record_ingest_run(
    quarter: str,
    mode: str,
    source_zip_sha256: str | None,
    fund_count: int | None,
    holding_count: int | None,
) -> None:
    """Append an observability row to ``sec_nport_ingest_runs``."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = """
    INSERT INTO sec_nport_ingest_runs
        (quarter, mode, ingested_at, source_zip_sha256, fund_count, holding_count)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        _db().execute_query(
            sql, (quarter, mode, now, source_zip_sha256, fund_count, holding_count),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_ingest_run(%s) failed: %s", quarter, exc)


def record_resume_cursor(quarter: str, member: str, last_accession_seen: str) -> None:
    """Persist the bulk-mode resume cursor per G6.

    Writes a row to ``sec_nport_ingest_runs`` so a SIGINT mid-ingest can
    resume from the last completed chunk. Caller invokes after each
    2000-row batch successfully upserts.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = """
    INSERT INTO sec_nport_ingest_runs
        (quarter, mode, ingested_at, last_member, last_accession_seen)
    VALUES (%s, %s, %s, %s, %s)
    """
    try:
        _db().execute_query(sql, (quarter, "bulk-cursor", now, member, last_accession_seen))
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_resume_cursor(%s, %s) failed: %s", quarter, member, exc)


# ---------------------------------------------------------------------------
# Read helpers (consumed by fmp_cached._try_nport at T6)
# ---------------------------------------------------------------------------


def fund_for_ticker(ticker: str) -> dict | None:
    """Resolve ETF ticker → ``{cik, series_id, fund_name, is_etf, is_uit}`` or None.

    Returns ``None`` for unknown ticker or DB error (graceful).
    """
    if not ticker:
        return None
    sql = (
        "SELECT cik, series_id, fund_name, is_etf, is_uit "
        "FROM sec_nport_fund_map WHERE ticker = %s LIMIT 1"
    )
    try:
        rows = _db().execute_query(sql, (ticker.strip().upper(),))
    except Exception as exc:  # noqa: BLE001
        logger.warning("fund_for_ticker(%s) failed: %s", ticker, exc)
        return None
    if not rows:
        return None
    row = rows[0]
    # Normalize TINYINT(1) flags to bool
    return {
        "cik": row.get("cik"),
        "series_id": row.get("series_id"),
        "fund_name": row.get("fund_name"),
        "is_etf": bool(row.get("is_etf")),
        "is_uit": bool(row.get("is_uit")),
    }


def latest_period_for_fund(cik: str, series_id: str | None = None) -> date | None:
    """Return the most recent ``report_date`` for a fund, or None if no filings."""
    if not cik:
        return None
    if series_id:
        sql = (
            "SELECT MAX(report_date) AS max_report_date FROM sec_nport_filings "
            "WHERE cik = %s AND series_id = %s"
        )
        params: tuple = (cik, series_id)
    else:
        sql = (
            "SELECT MAX(report_date) AS max_report_date FROM sec_nport_filings "
            "WHERE cik = %s"
        )
        params = (cik,)
    try:
        rows = _db().execute_query(sql, params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest_period_for_fund(%s, %s) failed: %s", cik, series_id, exc)
        return None
    if not rows:
        return None
    return rows[0].get("max_report_date")


def holdings_for_fund(
    ticker_or_cik: str,
    asof: date | None = None,
    series_id: str | None = None,
) -> list[dict]:
    """Return holdings for a fund, enforcing L10 + L11 + L12.

    Resolution flow:
      1. If ``ticker_or_cik`` looks like a ticker (uppercase alpha/dot/dash,
         not all digits), look it up in ``sec_nport_fund_map`` to get the
         (cik, series_id) pair. Otherwise treat as CIK (10-digit zero-padded).
      2. If the resolved fund has ``is_uit=True``, return ``[]`` immediately
         — UITs may not file NPORT-P (e.g. SPY).
      3. Find the LATEST accession in ``sec_nport_filings`` for that
         (cik, series_id) where ``report_date <= asof`` (L10 as-of semantics;
         ``asof=None`` means today). Tie-break: prefer ``is_amendment=True``,
         then ``filing_date DESC`` (L11 amendment supersession — NPORT-P/A
         for the same period beats NPORT-P).
      4. Return all holdings for that single accession, each row carrying
         ``report_date`` and a derived ``data_age_days`` (L12 staleness
         disclosure).

    Returns ``[]`` for unknown fund, UIT, no filings ≤ asof, or any DB error
    — never raises.
    """
    if not ticker_or_cik:
        return []

    cleaned = ticker_or_cik.strip().upper()
    # Heuristic: 10-digit zero-padded string → CIK; otherwise → ticker
    if cleaned.isdigit() and len(cleaned) == 10:
        cik = cleaned
        fund_series = series_id
        fund = None  # UIT check below requires the fund row; with bare CIK we skip
    else:
        fund = fund_for_ticker(cleaned)
        if fund is None:
            return []
        if fund["is_uit"]:
            logger.info(
                "holdings_for_fund(%s): fund is UIT; UITs may not file NPORT-P → []",
                cleaned,
            )
            return []
        cik = fund["cik"]
        fund_series = fund["series_id"]

    if asof is None:
        asof = date.today()

    # L10 + L11: find the latest accession ≤ asof; amendment supersedes original
    try:
        if fund_series:
            filing_sql = (
                "SELECT accession_number, report_date, is_amendment "
                "FROM sec_nport_filings "
                "WHERE cik = %s AND series_id = %s AND report_date <= %s "
                "ORDER BY report_date DESC, is_amendment DESC, "
                "        filing_date DESC, accession_number DESC "
                "LIMIT 1"
            )
            filing_params: tuple = (cik, fund_series, asof)
        else:
            filing_sql = (
                "SELECT accession_number, report_date, is_amendment "
                "FROM sec_nport_filings "
                "WHERE cik = %s AND report_date <= %s "
                "ORDER BY report_date DESC, is_amendment DESC, "
                "        filing_date DESC, accession_number DESC "
                "LIMIT 1"
            )
            filing_params = (cik, asof)

        filing_rows = _db().execute_query(filing_sql, filing_params)
        if not filing_rows:
            return []
        accession_number = filing_rows[0]["accession_number"]
        report_date = filing_rows[0]["report_date"]

        # Pull holdings for that single accession
        holdings_sql = (
            "SELECT accession_number, holding_key, issuer_name, ticker, "
            "       cusip, isin, lei, asset_category, units, value_usd, "
            "       pct_nav, payoff_direction, derivative_flag "
            "FROM sec_nport_holdings WHERE accession_number = %s"
        )
        holding_rows = _db().execute_query(holdings_sql, (accession_number,))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "holdings_for_fund(%s, asof=%s) failed: %s", ticker_or_cik, asof, exc,
        )
        return []

    # L12: stamp report_date + data_age_days on every returned row
    today = date.today()
    age_days = (today - report_date).days if isinstance(report_date, date) else None
    out = []
    for r in holding_rows or []:
        enriched = dict(r)
        enriched["report_date"] = report_date
        enriched["data_age_days"] = age_days
        out.append(enriched)
    return out
