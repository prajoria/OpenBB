"""SEC bulk Form 13F → CUSIP reverse-holdings index (issue #89).

This module is the **read/query + schema** half of the SEC bulk 13F feature. It
answers the reverse question Form 13F cannot answer natively — *"which
institutional managers hold ``<symbol>``?"* — by reading a local MySQL index
built from SEC's quarterly Form 13F **bulk data sets**.

Form 13F-HR is filed *by* managers and indexed by the **filer** (manager CIK),
not by the **held** company's ticker. To invert it we resolve a ticker to its
**CUSIP**(s) and scan a CUSIP-keyed holdings table populated once per quarter by
``Tools/ingest_sec_13f.py`` (the ingest half).

Design + decisions: ``docs/designs/ownership_13f/89-sec-bulk-13f-cusip-index.md``.

Responsibilities (single source of truth for the schema — see Q-A):
    * Table DDL + :func:`init_thirteen_f_index` (the ingest script imports and
      calls these; it never carries its own ``CREATE TABLE`` strings).
    * Read helpers :func:`resolve_cusip` and :func:`holders_for_cusip`.
    * Write helpers used by the ingest script
      (:func:`upsert_holdings`, :func:`upsert_cusip_map`, :func:`record_ingest_run`).
    * A small built-in seed map (B4) so the notebook universe resolves on day one.

Storage lives in the ``openbb_fmp_cache`` MySQL DB via the existing
``openbb_fmp_cached.utils.database`` helpers (imported lazily so this module does
not couple the SEC provider to ``fmp_cached`` at import time).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema (single source of truth — Q-A). All DDL is CREATE TABLE IF NOT EXISTS;
# loads use INSERT ... ON DUPLICATE KEY UPDATE keyed on the documented PKs (L7).
# ---------------------------------------------------------------------------

DDL_CUSIP_MAP = """
CREATE TABLE IF NOT EXISTS sec_13f_cusip_map (
    cusip        CHAR(9)      NOT NULL,
    issuer_name  VARCHAR(255) NOT NULL,
    ticker       VARCHAR(16)  NULL,
    title_class  VARCHAR(64)  NULL,
    figi         VARCHAR(12)  NULL,
    source       VARCHAR(32)  NOT NULL,
    updated_at   DATETIME     NOT NULL,
    PRIMARY KEY (cusip),
    KEY idx_ticker (ticker)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_HOLDINGS = """
CREATE TABLE IF NOT EXISTS sec_13f_holdings (
    cusip        CHAR(9)      NOT NULL,
    filer_cik    VARCHAR(16)  NOT NULL,
    filer_name   VARCHAR(255) NOT NULL,
    period       CHAR(7)      NOT NULL,
    shares       BIGINT       NULL,
    value_usd    BIGINT       NULL,
    put_call     VARCHAR(8)   NULL,
    source       VARCHAR(32)  NOT NULL,
    updated_at   DATETIME     NOT NULL,
    PRIMARY KEY (cusip, filer_cik, period),
    KEY idx_cusip_period (cusip, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

DDL_INGEST_RUNS = """
CREATE TABLE IF NOT EXISTS sec_13f_ingest_runs (
    id               BIGINT       NOT NULL AUTO_INCREMENT,
    period           CHAR(7)      NOT NULL,
    ingested_at      DATETIME     NOT NULL,
    row_count        BIGINT       NULL,
    holdings_count   BIGINT       NULL,
    source_zip_sha256 CHAR(64)    NULL,
    value_unit       VARCHAR(16)  NULL,
    PRIMARY KEY (id),
    KEY idx_period (period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

ALL_DDL = (DDL_CUSIP_MAP, DDL_HOLDINGS, DDL_INGEST_RUNS)

SOURCE_BULK = "sec_13f_bulk"
SOURCE_SEED = "seed"

# ---------------------------------------------------------------------------
# B4 seed map — common notebook/Analysis universe so resolve_cusip works on day
# one even before FIGI/bulk-derived tickers exist. CUSIPs are public identifiers.
# ---------------------------------------------------------------------------

SEED_CUSIP_MAP: dict[str, tuple[str, str]] = {
    # ticker: (cusip, issuer_name)
    "AAPL": ("037833100", "APPLE INC"),
    "MSFT": ("594918104", "MICROSOFT CORP"),
    "NVDA": ("67066G104", "NVIDIA CORP"),
    "AMZN": ("023135106", "AMAZON COM INC"),
    "GOOGL": ("02079K305", "ALPHABET INC CL A"),
    "GOOG": ("02079K107", "ALPHABET INC CL C"),
    "META": ("30303M102", "META PLATFORMS INC CL A"),
    "TSLA": ("88160R101", "TESLA INC"),
    "BRK.B": ("084670702", "BERKSHIRE HATHAWAY CL B"),
    "JPM": ("46625H100", "JPMORGAN CHASE & CO"),
    "V": ("92826C839", "VISA INC CL A"),
    "JNJ": ("478160104", "JOHNSON & JOHNSON"),
    "WMT": ("931142103", "WALMART INC"),
    "PG": ("742718109", "PROCTER & GAMBLE CO"),
    "XOM": ("30231G102", "EXXON MOBIL CORP"),
}


# ---------------------------------------------------------------------------
# Database access (lazy import to avoid coupling SEC provider to fmp_cached)
# ---------------------------------------------------------------------------


def _db():
    """Return the fmp_cached database helpers, imported lazily.

    Raises ``ImportError`` if the fmp_cached provider is not installed; callers
    treat that as "index unavailable → graceful empty".
    """
    from openbb_fmp_cached.utils import database  # noqa: PLC0415

    return database


# ---------------------------------------------------------------------------
# Period / value-unit helpers
# ---------------------------------------------------------------------------

_MONTH_TO_QUARTER = {
    "JAN": 1, "FEB": 1, "MAR": 1,
    "APR": 2, "MAY": 2, "JUN": 2,
    "JUL": 3, "AUG": 3, "SEP": 3,
    "OCT": 4, "NOV": 4, "DEC": 4,
}
_QUARTER_END = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}

# SEC amended Form 13F so VALUE is reported in whole dollars for data sets from
# 2023-Q2 onward; earlier data sets report VALUE in thousands (spike-confirmed).
_WHOLE_DOLLAR_FROM = (2023, 2)


def normalize_dataset_period(period: str) -> str:
    """Normalize a dataset/filing quarter to ``'YYYY-Qn'``.

    Accepts ``'2025q4'``, ``'2025Q4'``, ``'2025-Q4'``, ``'2025-q4'``.
    """
    raw = period.strip().upper().replace("-", "")
    if "Q" not in raw:
        raise ValueError(f"Unrecognized period: {period!r} (expected like '2025q4')")
    year_s, q_s = raw.split("Q", 1)
    year, quarter = int(year_s), int(q_s)
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"Quarter out of range in {period!r}")
    return f"{year:04d}-Q{quarter}"


def period_from_report_date(report_date: str) -> str | None:
    """Map a SEC ``PERIODOFREPORT`` like ``'31-MAR-2023'`` to ``'2023-Q1'``."""
    if not report_date:
        return None
    parts = report_date.strip().upper().split("-")
    if len(parts) != 3:
        return None
    _, mon, year = parts
    quarter = _MONTH_TO_QUARTER.get(mon[:3])
    if quarter is None or not year.isdigit():
        return None
    return f"{int(year):04d}-Q{quarter}"


def period_to_quarter_end(period: str) -> str:
    """``'2023-Q1'`` → ``'2023-03-31'`` (used for the FMP ``date`` field)."""
    year_s, q_s = period.split("-Q")
    return f"{year_s}-{_QUARTER_END[int(q_s)]}"


def value_unit_for_dataset(period: str) -> str:
    """Return ``'usd'`` or ``'thousands'`` for a dataset filing quarter."""
    norm = normalize_dataset_period(period)
    year_s, q_s = norm.split("-Q")
    year, quarter = int(year_s), int(q_s)
    return "usd" if (year, quarter) >= _WHOLE_DOLLAR_FROM else "thousands"


def normalize_value_to_usd(raw_value: int | float | None, value_unit: str) -> int | None:
    """Normalize a raw 13F VALUE to whole USD given the dataset's unit."""
    if raw_value is None:
        return None
    multiplier = 1000 if value_unit == "thousands" else 1
    return int(round(float(raw_value) * multiplier))


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------


def init_thirteen_f_index() -> bool:
    """Create the three 13F index tables if they do not exist (idempotent).

    Called by both the read path (best-effort) and the ingest script. Returns
    ``True`` on success; ``False`` if the database is unreachable.
    """
    try:
        db = _db()
        for ddl in ALL_DDL:
            db.execute_query(ddl)
        logger.info("13F index tables ready (sec_13f_holdings, sec_13f_cusip_map, sec_13f_ingest_runs)")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not initialize 13F index tables: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Write helpers (used by Tools/ingest_sec_13f.py)
# ---------------------------------------------------------------------------


def seed_cusip_map(seed: dict[str, tuple[str, str]] | None = None) -> int:
    """Load the B4 seed ticker→CUSIP rows into ``sec_13f_cusip_map``.

    Idempotent: existing rows are updated. Returns the number of rows written.
    """
    seed = seed if seed is not None else SEED_CUSIP_MAP
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        (cusip, issuer, ticker, None, None, SOURCE_SEED, now)
        for ticker, (cusip, issuer) in seed.items()
    ]
    return upsert_cusip_map(rows)


def upsert_cusip_map(rows: Iterable[tuple]) -> int:
    """Upsert rows into ``sec_13f_cusip_map``.

    Each row is ``(cusip, issuer_name, ticker, title_class, figi, source, updated_at)``.
    A non-seed source never overwrites a richer ``ticker`` with ``NULL``.
    """
    rows = list(rows)
    if not rows:
        return 0
    sql = """
    INSERT INTO sec_13f_cusip_map
        (cusip, issuer_name, ticker, title_class, figi, source, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        issuer_name = VALUES(issuer_name),
        ticker      = COALESCE(VALUES(ticker), ticker),
        title_class = COALESCE(VALUES(title_class), title_class),
        figi        = COALESCE(VALUES(figi), figi),
        source      = VALUES(source),
        updated_at  = VALUES(updated_at)
    """
    return _db().execute_many(sql, rows)


def upsert_holdings(rows: Iterable[tuple]) -> int:
    """Upsert rows into ``sec_13f_holdings``.

    Each row is ``(cusip, filer_cik, filer_name, period, shares, value_usd,
    put_call, source, updated_at)``. Re-running a quarter yields the same row
    count (L7 idempotency).
    """
    rows = list(rows)
    if not rows:
        return 0
    sql = """
    INSERT INTO sec_13f_holdings
        (cusip, filer_cik, filer_name, period, shares, value_usd, put_call, source, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        filer_name = VALUES(filer_name),
        shares     = VALUES(shares),
        value_usd  = VALUES(value_usd),
        put_call   = VALUES(put_call),
        source     = VALUES(source),
        updated_at = VALUES(updated_at)
    """
    return _db().execute_many(sql, rows)


def record_ingest_run(
    period: str,
    row_count: int | None,
    holdings_count: int | None,
    source_zip_sha256: str | None,
    value_unit: str | None,
) -> None:
    """Append an observability row to ``sec_13f_ingest_runs`` (Q-C)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sql = """
    INSERT INTO sec_13f_ingest_runs
        (period, ingested_at, row_count, holdings_count, source_zip_sha256, value_unit)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    try:
        _db().execute_query(
            sql,
            (
                normalize_dataset_period(period),
                now,
                row_count,
                holdings_count,
                source_zip_sha256,
                value_unit,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record ingest run for %s: %s", period, exc)


# ---------------------------------------------------------------------------
# Read helpers (T3) — the consuming fmp_cached tier calls these.
# ---------------------------------------------------------------------------


def resolve_cusip(symbol: str) -> list[str]:
    """Resolve a ticker to its CUSIP(s).

    One ticker can map to multiple CUSIPs (share classes), so this returns a
    **list** (Q-B). Returns ``[]`` when unknown or the index is unreachable.
    """
    if not symbol:
        return []
    sql = "SELECT cusip FROM sec_13f_cusip_map WHERE ticker = %s"
    try:
        rows = _db().execute_query(sql, (symbol.strip().upper(),))
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve_cusip(%s) failed: %s", symbol, exc)
        return []
    return [r["cusip"] for r in (rows or []) if r.get("cusip")]


def latest_period_for_cusips(cusips: list[str]) -> str | None:
    """Return the most recent ``period`` present for any of ``cusips``."""
    cusips = [c for c in (cusips or []) if c]
    if not cusips:
        return None
    placeholders = ", ".join(["%s"] * len(cusips))
    sql = (
        f"SELECT MAX(period) AS p FROM sec_13f_holdings WHERE cusip IN ({placeholders})"
    )
    try:
        rows = _db().execute_query(sql, tuple(cusips))
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest_period_for_cusips failed: %s", exc)
        return None
    if rows and rows[0].get("p"):
        return rows[0]["p"]
    return None


def holders_for_cusip(
    cusips: str | list[str], period: str | None = None
) -> list[dict[str, Any]]:
    """Return managers holding any of ``cusips``, ranked by ``value_usd`` desc.

    ``cusips`` may be a single CUSIP or a list (one ticker → many share-class
    CUSIPs, Q-B). When ``period`` is ``None`` the latest available period is
    used. Option rows are already excluded at ingest, so all rows are long
    positions. Returns ``[]`` when nothing is found or the index is unreachable.
    """
    if isinstance(cusips, str):
        cusips = [cusips]
    cusips = [c for c in (cusips or []) if c]
    if not cusips:
        return []

    if period is None:
        period = latest_period_for_cusips(cusips)
        if period is None:
            return []

    placeholders = ", ".join(["%s"] * len(cusips))
    sql = f"""
    SELECT cusip, filer_cik, filer_name, period, shares, value_usd, put_call
    FROM sec_13f_holdings
    WHERE cusip IN ({placeholders}) AND period = %s
    ORDER BY value_usd DESC
    """
    try:
        rows = _db().execute_query(sql, (*cusips, period))
    except Exception as exc:  # noqa: BLE001
        logger.warning("holders_for_cusip failed: %s", exc)
        return []
    return list(rows or [])
