r"""Tools/enrich_cusip_figi.py -- broad ticker->CUSIP coverage via OpenFIGI (#93).

Walks the un-tickered CUSIPs in ``sec_13f_holdings`` (left-anti-joined against
``sec_13f_cusip_map``), batches them through OpenFIGI /v3/mapping, picks the
US-composite match via ``select_match()`` (R3), and upserts the result into
``sec_13f_cusip_map`` with ``source='openfigi'`` (or ``'openfigi_ambiguous'``
on skip per R4).

Read the design at docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md
for the locked decisions (L1-L8, R1-R9).

Usage
=====

    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --dry-run
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --limit 100
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --refresh --limit 50
    .venv_win\\Scripts\\python.exe Tools/enrich_cusip_figi.py --audit-disagreements --limit 25

Flags mirror Tools/populate_cusip_map.py plus the five #93-specific ones
(--max-batches --since --reresolve-flagged --audit-disagreements --refresh).
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make stdout UTF-8 (Windows console default is cp1252) -- same as populate_cusip_map.py
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Add SEC + fmp_cached provider source dirs to sys.path so this script runs as a
# bare ``python Tools/enrich_cusip_figi.py`` without requiring an editable install
# of every provider (mirrors populate_cusip_map.py's sys.path mutations).
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "openbb_platform" / "providers" / "sec"))
sys.path.insert(0, str(_REPO_ROOT / "openbb_platform" / "providers" / "fmp_cached"))

logger = logging.getLogger("enrich_cusip_figi")

SOURCE_OPENFIGI = "openfigi"
SOURCE_AMBIGUOUS = "openfigi_ambiguous"


# ---------------------------------------------------------------------------
# R5 source query -- distinct un-mapped CUSIPs ranked by latest-period held USD
# ---------------------------------------------------------------------------

# The fmp_cached `execute_query` helper checks the FIRST WORD of the query to
# decide whether to return rows (`fetchall`) or a rowcount (`int`). It only
# treats statements starting with "SELECT" as queries -- a leading "WITH" CTE
# silently returns 0. So we express the latest-period-per-filer join inline as
# subqueries rather than a CTE chain.
SELECT_UNMAPPED_CUSIPS_SQL = """
SELECT r.cusip
FROM (
    SELECT lr.cusip, SUM(lr.value_usd) AS held_usd
    FROM (
        SELECT h.cusip, h.value_usd
        FROM sec_13f_holdings h
        JOIN (
            SELECT filer_cik, MAX(period) AS max_period
            FROM sec_13f_holdings
            GROUP BY filer_cik
        ) lp
          ON lp.filer_cik = h.filer_cik AND lp.max_period = h.period
        WHERE h.put_call IS NULL
          AND CHAR_LENGTH(h.cusip) = 9
    ) lr
    GROUP BY lr.cusip
) r
LEFT JOIN sec_13f_cusip_map m ON m.cusip = r.cusip
WHERE (m.cusip IS NULL)
   OR (m.ticker IS NULL
       AND (m.source IS NULL
            OR m.source NOT IN ('seed','fmp_profile','openfigi','openfigi_ambiguous')))
ORDER BY r.held_usd DESC
"""

SELECT_FLAGGED_CUSIPS_SQL = """
SELECT cusip
FROM sec_13f_cusip_map
WHERE source = 'openfigi_ambiguous'
ORDER BY updated_at ASC
"""


def _db():
    """Lazy import of the fmp_cached database module (same pattern as openfigi._db)."""
    from openbb_fmp_cached.utils import database as _database  # noqa: PLC0415

    return _database


def select_target_cusips(
    *, since: str | None, reresolve_flagged: bool, limit: int | None
) -> list[str]:
    """R5 source query. Returns up to ``limit`` distinct CUSIPs ordered by held USD."""
    if reresolve_flagged:
        rows = _db().execute_query(SELECT_FLAGGED_CUSIPS_SQL)
    elif since:
        sql = SELECT_UNMAPPED_CUSIPS_SQL.replace(
            "WHERE h.put_call IS NULL",
            "WHERE h.put_call IS NULL AND h.updated_at >= %s",
            1,
        )
        rows = _db().execute_query(sql, (since,))
    else:
        rows = _db().execute_query(SELECT_UNMAPPED_CUSIPS_SQL)

    cusips = [r["cusip"] for r in (rows or []) if r.get("cusip")]
    if limit is not None:
        cusips = cusips[:limit]
    return cusips


# ---------------------------------------------------------------------------
# Enrichment loop -- map -> select -> upsert (per-batch transactional, R5)
# ---------------------------------------------------------------------------


def _row_for_upsert(
    cusip: str,
    match,
    issuer_hint: str | None = None,
    *,
    source: str = SOURCE_OPENFIGI,
) -> tuple:
    """Build a sec_13f_cusip_map upsert tuple from a select_match() result.

    The schema's 7-tuple is ``(cusip, issuer_name, ticker, title_class, figi,
    source, updated_at)`` (see thirteen_f_index.py:240-261). For ambiguous /
    no-match rows we persist NULL ticker + ``source='openfigi_ambiguous'`` (R4).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if match is None:
        return (cusip, issuer_hint or "", None, None, None, source, now)
    return (
        cusip,
        match.get("name") or issuer_hint or "",
        match.get("ticker"),
        # 'Common Stock' / 'Preferred Stock' -> title_class (R3, the picked
        # security type is persisted so downstream consumers can filter).
        match.get("securityType2"),
        match.get("figi"),
        source,
        now,
    )


def _existing_row(cusip: str) -> dict | None:
    rows = _db().execute_query(
        "SELECT ticker, source FROM sec_13f_cusip_map WHERE cusip=%s",
        (cusip,),
    )
    return rows[0] if rows else None


def enrich(
    cusips: list[str],
    *,
    api_key: str | None,
    refresh: bool,
    dry_run: bool,
    audit_disagreements: bool,
    max_batches: int | None,
) -> dict:
    """Map -> select -> upsert. Returns a stats dict (also logged at end).

    Per-batch transactional upsert: an uncaught exception in a batch drops
    that batch's writes rather than partial-upserting (R5 last bullet).
    """
    from openbb_sec.utils.openfigi import (  # noqa: PLC0415
        RateLimitPolicy,
        map_cusips,
        select_match,
    )
    from openbb_sec.utils.thirteen_f_index import upsert_cusip_map  # noqa: PLC0415

    policy = RateLimitPolicy.keyed() if api_key else RateLimitPolicy.keyless()
    stats = {
        "requested": len(cusips),
        "mapped_ok": 0,
        "ambiguous": 0,
        "no_match": 0,
        "errors": 0,
        "disagreements": 0,
        "written": 0,
    }

    # Window the work into ``policy.batch_size`` chunks to keep the per-batch
    # transactional upsert window bounded and predictable.
    total_chunks = math.ceil(len(cusips) / max(1, policy.batch_size))
    if max_batches is not None:
        total_chunks = min(total_chunks, max_batches)
        cusips = cusips[: total_chunks * policy.batch_size]

    for batch_idx in range(total_chunks):
        chunk = cusips[batch_idx * policy.batch_size : (batch_idx + 1) * policy.batch_size]
        if not chunk:
            break
        logger.info("batch %d/%d: %d cusips", batch_idx + 1, total_chunks, len(chunk))
        try:
            results = map_cusips(chunk, api_key=api_key, policy=policy, refresh=refresh)
        except Exception as exc:  # noqa: BLE001 -- drop the in-flight batch, never partial-upsert
            logger.error("batch %d dropped (uncaught error): %s", batch_idx + 1, exc)
            stats["errors"] += len(chunk)
            continue

        rows_to_upsert: list[tuple] = []
        for cusip in chunk:
            job = results.get(cusip)
            if job is None or "error" in (job or {}):
                stats["errors"] += 1
                continue
            match = select_match(job)
            if match is None:
                # No match OR ambiguous -- both persist as a flagged row (R4)
                # so future runs anti-join past them.
                if not (job.get("data") or []):
                    stats["no_match"] += 1
                else:
                    stats["ambiguous"] += 1
                if not (dry_run or audit_disagreements):
                    rows_to_upsert.append(
                        _row_for_upsert(cusip, None, source=SOURCE_AMBIGUOUS)
                    )
                continue

            stats["mapped_ok"] += 1
            if audit_disagreements:
                existing = _existing_row(cusip)
                if (
                    existing
                    and existing.get("ticker")
                    and existing["ticker"] != match.get("ticker")
                ):
                    stats["disagreements"] += 1
                    logger.warning(
                        "OpenFIGI disagreement: cusip=%s existing=%s (%s) openfigi=%s",
                        cusip,
                        existing["ticker"],
                        existing.get("source"),
                        match.get("ticker"),
                    )
                continue  # audit mode never writes

            if dry_run:
                continue
            rows_to_upsert.append(_row_for_upsert(cusip, match))

        if rows_to_upsert:
            written = upsert_cusip_map(rows_to_upsert)
            stats["written"] += written

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Enrich sec_13f_cusip_map via OpenFIGI (#93).")
    parser.add_argument(
        "--database", default=None,
        help="Target MySQL database (default: from DatabaseConfig)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Cap distinct CUSIPs to enrich this run",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.0,
        help="Extra sleep between batches (sec), atop RateLimitPolicy",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Plan only -- no DB writes (still does cache reads + API calls)",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Override OpenFIGI key (else env OPEN_FIGI_API_KEY -> user_settings -> keyless)",
    )
    parser.add_argument(
        "--max-batches", type=int, default=None,
        help="Stop after N batches (CI safety; R2 reviewer note 4)",
    )
    parser.add_argument(
        "--since", default=None,
        help="YYYY-MM-DD: only consider CUSIPs whose holdings updated_at >= since",
    )
    parser.add_argument(
        "--reresolve-flagged", action="store_true",
        help="Re-attempt CUSIPs previously flagged as openfigi_ambiguous",
    )
    parser.add_argument(
        "--audit-disagreements", action="store_true",
        help="Map but do not write; WARN-log OpenFIGI <-> existing ticker diffs",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Bypass openfigi_map_cache reads and overwrite the row (R9 CLI bypass)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    from openbb_sec.utils.openfigi import (  # noqa: PLC0415
        init_openfigi_cache,
        resolve_credentials,
    )

    api_key, source = resolve_credentials(args.api_key)
    policy_label = "keyed" if api_key else "keyless"
    batch_size = 100 if api_key else 10
    init_openfigi_cache()

    cusips = select_target_cusips(
        since=args.since,
        reresolve_flagged=args.reresolve_flagged,
        limit=args.limit,
    )
    total = len(cusips)
    batches_est = math.ceil(total / batch_size) if total else 0
    if args.max_batches is not None:
        batches_est = min(batches_est, args.max_batches)

    print("=" * 70)  # noqa: T201
    print("  ENRICH sec_13f_cusip_map via OpenFIGI (#93)")  # noqa: T201
    print("=" * 70)  # noqa: T201
    print(f"  Distinct un-mapped: {total}")  # noqa: T201
    print(f"  To enrich this run: {total}")  # noqa: T201
    print(  # noqa: T201
        f"  Estimated batches : {batches_est}  "
        f"(size {batch_size}, mode {policy_label}, source {source})"
    )
    if args.dry_run:
        print("\n  DRY RUN -- no DB writes (cache reads + OpenFIGI calls still happen).")  # noqa: T201

    started = time.monotonic()
    stats = enrich(
        cusips,
        api_key=api_key,
        refresh=args.refresh,
        dry_run=args.dry_run,
        audit_disagreements=args.audit_disagreements,
        max_batches=args.max_batches,
    )
    elapsed = time.monotonic() - started

    print(f"\n{'=' * 70}")  # noqa: T201
    print("  RESULTS")  # noqa: T201
    print(f"{'=' * 70}")  # noqa: T201
    print(f"  Requested     : {stats['requested']}")  # noqa: T201
    print(  # noqa: T201
        f"  Mapped OK     : {stats['mapped_ok']}"
    )
    print(  # noqa: T201
        f"  Ambiguous     : {stats['ambiguous']}  (persisted as source='openfigi_ambiguous')"
    )
    print(f"  No match      : {stats['no_match']}")  # noqa: T201
    print(f"  Errors        : {stats['errors']}")  # noqa: T201
    if args.audit_disagreements:
        print(  # noqa: T201
            f"  Disagreements : {stats['disagreements']}  (WARN-logged; not written)"
        )
    print(f"  Rows written  : {stats['written']}")  # noqa: T201
    print(f"  Elapsed       : {elapsed:.1f}s")  # noqa: T201
    print("=" * 70)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
