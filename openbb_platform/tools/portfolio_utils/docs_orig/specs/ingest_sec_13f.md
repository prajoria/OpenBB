# ingest_sec_13f.py — Spec

| | |
|---|---|
| **Category** | DB loader |
| **Path** | `Tools/ingest_sec_13f.py` |
| **Writes** | `sec_13f_holdings`, `sec_13f_cusip_map`, `sec_13f_ingest_runs` |
| **Issue** | #89 (SEC bulk 13F -> CUSIP reverse-holdings index) |

## Purpose

Ingest one SEC quarterly **Form 13F bulk data set** (zip) into the local CUSIP
reverse-holdings index. This is the **ingest half** of #89; the read/query +
schema half lives in `openbb_sec.utils.thirteen_f_index` (which owns the DDL —
this script imports and calls it, carries no `CREATE TABLE` of its own).

The read helpers `resolve_cusip` / `holders_for_cusip` power the `fmp_cached`
institutional-ownership SEC tier (`_try_sec_13f`), aggregating real per-manager
holdings into the FMP summary schema.

## Pipeline (idempotent, resumable, off the read path)

1. Resolve the dataset filing quarter (`--period` or latest published).
2. Download `{YYYYqN}_form13f.zip` from SEC (`requests` + descriptive
   User-Agent, retry/backoff; never `aiohttp`).
3. Join `INFOTABLE` (held CUSIP, shares, value, put/call) -> `SUBMISSION`
   (filer CIK, report period) -> `COVERPAGE` (filing-manager name) on
   `ACCESSION_NUMBER`.
4. Exclude option rows (`PUTCALL` set); aggregate long positions per
   `(cusip, filer_cik, period)`; normalize VALUE to whole USD per dataset unit
   (thousands pre-2023-Q2, whole USD after — spike-confirmed).
5. Upsert into `sec_13f_holdings` + `sec_13f_cusip_map` (seeded by B4); append
   an observability row to `sec_13f_ingest_runs` (period, sha256, counts,
   value_unit).

## CLI

```
.venv_win\Scripts\python.exe Tools\ingest_sec_13f.py [--period 2025q4]
    [--user-agent "Name email"] [--no-seed] [--limit N] [--dry-run]
```

| Flag | Meaning |
|------|---------|
| `--period` | dataset quarter (e.g. `2025q4`); default latest published |
| `--user-agent` | descriptive UA (SEC requires it); else `SEC_USER_AGENT` env or generic |
| `--no-seed` | skip B4 CUSIP seed |
| `--limit` | cap rows (smoke test) |
| `--dry-run` | parse only, no writes |

## Tables

DDL is owned by `openbb_sec/utils/thirteen_f_index.py`:

- `sec_13f_holdings` — per `(cusip, filer_cik, period)` long aggregate.
- `sec_13f_cusip_map` — `(cusip, issuer_name, ticker, title_class, figi,
  source, updated_at)`; FIGI captured per-CUSIP here.
- `sec_13f_ingest_runs` — manifest / observability row per ingest.

**Persistence:** `INSERT ... ON DUPLICATE KEY UPDATE` throughout — idempotent.

## Notes

- Verified e2e: 2023q2 ingest (59,718 holdings / 4,523 CUSIPs);
  `resolve_cusip('MSFT')` / `('AAPL')` + ranked holders confirmed.
- VALUE-unit normalization is the subtle part: pre-2023-Q2 values are in
  thousands, whole-USD from 2023-Q2 onward.
- `populate_cusip_map.py` is the complementary loader that broadens the
  ticker -> CUSIP coverage of `sec_13f_cusip_map` for the S&P 500 without an
  SEC bulk download.
