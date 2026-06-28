"""Ingest one SEC quarterly Form 13F **bulk data set** into the local CUSIP index.

This is the **ingest half** of issue #89 (the read/query + schema half lives in
``openbb_sec.utils.thirteen_f_index``, which owns the DDL — this script imports
and calls it, per Q-A; it carries no ``CREATE TABLE`` of its own).

What it does (idempotent, resumable, off the read path — L6/L7):
    1. Resolve the dataset filing quarter (``--period`` or latest published).
    2. Download ``{YYYYqN}_form13f.zip`` from SEC (``requests`` + descriptive
       User-Agent, retry/backoff; never ``aiohttp`` per repo rules).
    3. Join INFOTABLE (held CUSIP, shares, value, put/call) → SUBMISSION
       (filer CIK, report period) → COVERPAGE (filing-manager name) on
       ACCESSION_NUMBER.
    4. Exclude option rows (``PUTCALL`` set); aggregate long positions per
       ``(cusip, filer_cik, period)``; normalize VALUE to whole USD per the
       dataset's unit (thousands pre-2023-Q2, whole USD after — spike-confirmed).
    5. Upsert into ``sec_13f_holdings`` + ``sec_13f_cusip_map`` (seeded by B4),
       and append an observability row to ``sec_13f_ingest_runs``.

Usage:
    .venv_win\\Scripts\\python.exe Tools\\ingest_sec_13f.py [--period 2025q4]
        [--user-agent "Name email"] [--no-seed] [--limit N] [--dry-run]

User-Agent: SEC requires a descriptive UA. Provide ``--user-agent`` or set
``SEC_USER_AGENT``; falls back to a generic research UA otherwise.
"""

import argparse
import csv
import hashlib
import io
import logging
import os
import sys
import time
import zipfile
from datetime import date, datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Path setup (Tools skeleton — bootstrap provider packages onto sys.path)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in [
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp_cached"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "fmp"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "providers", "sec"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "core"),
    os.path.join(PROJECT_ROOT, "openbb_platform", "platform"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("FMP_CACHE_AUTO_CREATE_DB", "false")

from openbb_sec.utils import thirteen_f_index as tfi  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ingest_sec_13f")

SEC_BASE = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
DEFAULT_UA = "OpenBBTechnical-Research research@openbbtech.local"
REQUEST_SLEEP = 0.3  # ≤10 req/s (L5)


# ---------------------------------------------------------------------------
# Dataset period resolution
# ---------------------------------------------------------------------------


def _quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def recent_quarters(today: date | None = None, count: int = 6) -> list[str]:
    """Return the last ``count`` filing quarters newest-first as ``'YYYYqN'``."""
    today = today or date.today()
    year, quarter = _quarter_of(today)
    out = []
    for _ in range(count):
        out.append(f"{year}q{quarter}")
        quarter -= 1
        if quarter == 0:
            quarter, year = 4, year - 1
    return out


def dataset_url(period: str) -> str:
    norm = tfi.normalize_dataset_period(period)  # validate
    year_s, q_s = norm.split("-Q")
    return f"{SEC_BASE}/{year_s}q{q_s}_form13f.zip"


def resolve_latest_published(session: requests.Session, ua: str) -> str | None:
    """HEAD-probe recent quarters and return the newest one SEC actually hosts."""
    for period in recent_quarters():
        url = dataset_url(period)
        try:
            resp = session.head(url, headers={"User-Agent": ua}, timeout=30, allow_redirects=True)
            time.sleep(REQUEST_SLEEP)
            if resp.status_code == 200:
                logger.info("Latest published dataset resolved: %s", period)
                return period
        except requests.RequestException as exc:
            logger.debug("HEAD %s failed: %s", period, exc)
    return None


def download_zip(session: requests.Session, period: str, ua: str, retries: int = 3) -> bytes:
    """Download a dataset zip with simple exponential backoff."""
    url = dataset_url(period)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("Downloading %s (attempt %d/%d)", url, attempt, retries)
            resp = session.get(url, headers={"User-Agent": ua}, timeout=180)
            if resp.status_code == 200:
                return resp.content
            last_exc = RuntimeError(f"HTTP {resp.status_code} for {url}")
        except requests.RequestException as exc:
            last_exc = exc
        sleep_for = REQUEST_SLEEP * (2 ** attempt)
        logger.warning("Retry in %.1fs (%s)", sleep_for, last_exc)
        time.sleep(sleep_for)
    raise RuntimeError(f"Failed to download {url}: {last_exc}")


# ---------------------------------------------------------------------------
# Pure parse / aggregate helpers (unit-tested in T5)
# ---------------------------------------------------------------------------


def parse_submission(rows: "csv.DictReader | list[dict]") -> dict[str, tuple[str, str | None]]:
    """ACCESSION_NUMBER → (filer CIK, report period 'YYYY-Qn')."""
    out: dict[str, tuple[str, str | None]] = {}
    for row in rows:
        acc = (row.get("ACCESSION_NUMBER") or "").strip()
        if not acc:
            continue
        cik = (row.get("CIK") or "").strip()
        period = tfi.period_from_report_date(row.get("PERIODOFREPORT") or "")
        out[acc] = (cik, period)
    return out


def parse_coverpage(rows: "csv.DictReader | list[dict]") -> dict[str, str]:
    """ACCESSION_NUMBER → filing-manager name."""
    out: dict[str, str] = {}
    for row in rows:
        acc = (row.get("ACCESSION_NUMBER") or "").strip()
        if not acc:
            continue
        out[acc] = (row.get("FILINGMANAGER_NAME") or "").strip()
    return out


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def aggregate_infotable(
    rows: "csv.DictReader | list[dict]",
    submission: dict[str, tuple[str, str | None]],
    coverpage: dict[str, str],
    value_unit: str,
) -> tuple[list[tuple], list[tuple], dict[str, int]]:
    """Aggregate INFOTABLE rows into holdings + cusip-map upsert tuples.

    Long positions only (option rows where ``PUTCALL`` is set are skipped, Q-D).
    Multiple rows for the same ``(cusip, filer_cik, period)`` are summed. Returns
    ``(holdings_rows, cusip_map_rows, stats)``.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # key (cusip, cik, period) -> [shares, value_usd, filer_name]
    agg: dict[tuple[str, str, str], list] = {}
    cusip_meta: dict[str, tuple[str, str | None]] = {}  # cusip -> (issuer, figi)
    stats = {"read": 0, "options_skipped": 0, "no_submission": 0, "kept": 0}

    for row in rows:
        stats["read"] += 1
        if (row.get("PUTCALL") or "").strip():
            stats["options_skipped"] += 1
            continue
        acc = (row.get("ACCESSION_NUMBER") or "").strip()
        sub = submission.get(acc)
        if not sub or not sub[0] or not sub[1]:
            stats["no_submission"] += 1
            continue
        cik, period = sub
        cusip = (row.get("CUSIP") or "").strip().upper()
        if not cusip:
            continue
        shares = _to_int(row.get("SSHPRNAMT"))
        value_usd = tfi.normalize_value_to_usd(_to_int(row.get("VALUE")), value_unit)
        filer_name = coverpage.get(acc, "")

        key = (cusip, cik, period)
        if key not in agg:
            agg[key] = [0, 0, filer_name]
        agg[key][0] += shares or 0
        agg[key][1] += value_usd or 0
        if filer_name and not agg[key][2]:
            agg[key][2] = filer_name

        if cusip not in cusip_meta:
            cusip_meta[cusip] = (
                (row.get("NAMEOFISSUER") or "").strip() or cusip,
                (row.get("FIGI") or "").strip() or None,
            )
        stats["kept"] += 1

    holdings_rows = [
        (cusip, cik, filer_name or cik, period, shares, value_usd, None, tfi.SOURCE_BULK, now)
        for (cusip, cik, period), (shares, value_usd, filer_name) in agg.items()
    ]
    cusip_map_rows = [
        (cusip, issuer, None, None, figi, tfi.SOURCE_BULK, now)
        for cusip, (issuer, figi) in cusip_meta.items()
    ]
    return holdings_rows, cusip_map_rows, stats


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _read_tsv(zf: zipfile.ZipFile, member: str) -> list[dict]:
    with zf.open(member) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
        return list(csv.DictReader(text, delimiter="\t"))


def ingest(period: str | None, ua: str, seed: bool, limit: int | None, dry_run: bool) -> int:
    session = requests.Session()

    if period is None:
        period = resolve_latest_published(session, ua)
        if period is None:
            logger.error("Could not resolve a published 13F dataset from SEC.")
            return 1

    norm_period = tfi.normalize_dataset_period(period)
    value_unit = tfi.value_unit_for_dataset(period)
    logger.info("Ingesting dataset %s (value_unit=%s)", norm_period, value_unit)

    content = download_zip(session, period, ua)
    sha256 = hashlib.sha256(content).hexdigest()
    logger.info("Downloaded %.1f MB (sha256=%s)", len(content) / 1024 / 1024, sha256[:12])

    zf = zipfile.ZipFile(io.BytesIO(content))
    names = {n.upper(): n for n in zf.namelist()}
    submission = parse_submission(_read_tsv(zf, names["SUBMISSION.TSV"]))
    coverpage = parse_coverpage(_read_tsv(zf, names["COVERPAGE.TSV"]))

    info_rows = _read_tsv(zf, names["INFOTABLE.TSV"])
    if limit:
        info_rows = info_rows[:limit]
    holdings_rows, cusip_map_rows, stats = aggregate_infotable(
        info_rows, submission, coverpage, value_unit
    )
    logger.info(
        "Parsed: read=%d kept=%d options_skipped=%d no_submission=%d | holdings=%d cusips=%d",
        stats["read"], stats["kept"], stats["options_skipped"], stats["no_submission"],
        len(holdings_rows), len(cusip_map_rows),
    )

    if dry_run:
        logger.info("Dry run — no database writes.")
        return 0

    if not tfi.init_thirteen_f_index():
        logger.error("Database unavailable — aborting load.")
        return 1
    if seed:
        seeded = tfi.seed_cusip_map()
        logger.info("Seeded %d ticker→CUSIP rows (B4)", seeded)

    tfi.upsert_cusip_map(cusip_map_rows)
    written = tfi.upsert_holdings(holdings_rows)
    tfi.record_ingest_run(
        period=norm_period,
        row_count=stats["read"],
        holdings_count=len(holdings_rows),
        source_zip_sha256=sha256,
        value_unit=value_unit,
    )
    logger.info("Load complete: %d holdings rows upserted for %s", written, norm_period)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a SEC Form 13F bulk data set into the CUSIP index.")
    parser.add_argument("--period", default=None, help="Filing quarter, e.g. 2025q4 (default: latest published)")
    parser.add_argument("--user-agent", default=os.getenv("SEC_USER_AGENT", DEFAULT_UA),
                        help="Descriptive SEC User-Agent (required by SEC)")
    parser.add_argument("--no-seed", action="store_true", help="Skip loading the B4 seed ticker→CUSIP map")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N INFOTABLE rows (debug)")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write to the database")
    args = parser.parse_args()
    return ingest(args.period, args.user_agent, not args.no_seed, args.limit, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
