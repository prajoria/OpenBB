# enrich_cusip_figi.py — Spec

| | |
|---|---|
| **Category** | DB loader (provider enrichment) |
| **Path** | `Tools/enrich_cusip_figi.py` (~390 lines) |
| **Reads** | `sec_13f_holdings`, `sec_13f_cusip_map` |
| **Writes** | `sec_13f_cusip_map`, `openfigi_map_cache` |
| **Issue** | [#93](https://github.com/prajoria/OpenBB/issues/93) (broad ticker → CUSIP via OpenFIGI) |
| **Design** | [`docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md`](../../../docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md) |
| **Sibling** | [`populate_cusip_map.py`](populate_cusip_map.md) (covers S&P 500 via FMP profile; this script covers the long tail via OpenFIGI) |

## Purpose

Close the long-tail ticker → CUSIP gap left by `populate_cusip_map.py` (S&P 500
only). Every CUSIP institutions report holding lives in `sec_13f_holdings`, but
the matching `ticker` is missing for everything outside the S&P 500 universe.
This script enriches those rows using Bloomberg's free [**OpenFIGI
`/v3/mapping`**](https://www.openfigi.com/api) — the deterministic FIGI bridge
locked in #89 Q-B and #93 R3 — so `resolve_cusip(<long-tail ticker>)` stops
returning `[]`.

The defining constraint is legal, not technical: a ticker↔CUSIP master is a
**licensed** product (CUSIP Global Services / S&P) and may not be redistributed.
We never copy such a list. Instead, we derive CUSIPs from public SEC 13F bulk
data (already in `sec_13f_holdings` via #89) and use FIGI — an open identifier
— as the cross-reference to recover the ticker.

## How it works

1. **Select** distinct CUSIPs from `sec_13f_holdings` where `put_call IS NULL`
   ∧ `CHAR_LENGTH(cusip)=9`, ranked by `SUM(value_usd)` over the **latest
   period per filer**, **left-anti-joined** against `sec_13f_cusip_map` rows
   whose `source ∈ {'seed','fmp_profile','openfigi','openfigi_ambiguous'}`
   (R5/R6). This guarantees OpenFIGI never even attempts a CUSIP already
   mapped by the seed or FMP-profile path — **provenance precedence is
   enforced app-side, not by `COALESCE`** (R6).
2. **Batch** the un-mapped CUSIPs into chunks of `policy.batch_size` (100
   keyed, 10 keyless per R2) and call
   `openbb_sec.utils.openfigi.map_cusips(...)`. Cache hits short-circuit
   the HTTP call; misses are POSTed to `/v3/mapping`, raw responses upserted
   into `openfigi_map_cache` (R9, TTL 180d), then merged in.
3. **Select one match** per CUSIP via the deterministic
   [R3 ladder](#r3-match-selection-ladder).
4. **Upsert** the chosen `(ticker, figi)` into `sec_13f_cusip_map` with
   `source='openfigi'`. Ambiguous / no-match CUSIPs persist as
   `(ticker=NULL, source='openfigi_ambiguous')` so subsequent runs anti-join
   past them (R4); `--reresolve-flagged` re-attempts them on demand.
5. **Per-batch transactional upsert** (R5): if any batch raises uncaught,
   that batch's writes are dropped (not partial-written); errors counted, run
   continues.

## CLI

```bash
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --dry-run          # plan + cache reads, no DB writes
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --limit 100        # bounded live run
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --refresh --limit 50  # bypass cache for these CUSIPs
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --audit-disagreements  # map + WARN on ticker mismatches, no writes
.venv_win\Scripts\python.exe Tools/enrich_cusip_figi.py --reresolve-flagged    # retry previously-ambiguous rows
```

| Flag | Default | Meaning |
|---|---|---|
| `--database` | from `DatabaseConfig` | target / source DB |
| `--limit` | none | cap **distinct CUSIPs** to enrich this run (not job count) |
| `--sleep` | `0.0` | extra sleep between batches atop `RateLimitPolicy` |
| `--dry-run` | off | plan only — no DB writes (cache reads + OpenFIGI calls still happen) |
| `--api-key` | none | overrides credential chain (next bullet) |
| `--max-batches` | none | CI / cron safety cap |
| `--since` | none | `YYYY-MM-DD` — only consider CUSIPs whose holdings `updated_at >= since` |
| `--reresolve-flagged` | off | re-attempt CUSIPs previously stored as `openfigi_ambiguous` |
| `--audit-disagreements` | off | map but do not write; WARN on OpenFIGI ↔ existing ticker diffs |
| `--refresh` | off | bypass `openfigi_map_cache` reads and overwrite rows (R9) |
| `-v / --verbose` | off | DEBUG-level logging |

## Credentials (R2)

The OpenFIGI key is resolved in order; the first hit wins. Run mode + source
are logged at startup (never the key value):

1. `--api-key` CLI flag
2. `OPEN_FIGI_API_KEY` env var
3. `user_settings.credentials.openfigi_api_key` (via `openbb_core.UserService`)
4. **Keyless** — falls back to the conservative shared rate limit

## R3 match selection ladder

OpenFIGI may return many matches per CUSIP (different exchanges, share classes,
composite vs local FIGIs). We need exactly one `(ticker, figi)` per CUSIP. The
ladder is applied in order; first single match wins:

1. Filter to `marketSector == "Equity"` ∧ `securityType2 ∈ {"Common Stock",
   "Preferred Stock"}` ∧ `exchCode ∈ US_COMPOSITE_SET` (`{"US"}`).
2. Of survivors, prefer rows where `figi == compositeFIGI`.
3. If still tied, prefer `Common Stock` over `Preferred Stock`.
4. If still ambiguous → **skip + flag** as `source='openfigi_ambiguous'`.

Preferred Stock is **deliberately not excluded** — 13F holdings include
preferred shares with their own CUSIPs and they're legitimately resolvable.
The picked `securityType2` is persisted in the existing `title_class` column
(no schema change; honors L3).

## Cadence

- **One-shot** after #93 lands (this script + #89's `ingest_sec_13f.py` quarter
  loaded).
- **Re-run** quarterly after each new `ingest_sec_13f.py` quarter expands the
  un-mapped CUSIP pool.
- `--reresolve-flagged` opportunistic when OpenFIGI fixes data upstream.
- FIGIs can change after corporate actions; refresh stale rows (>~18 months)
  via a follow-up bd (R7, post-MVP).

## Acceptance checks (from design §3)

- [x] `--dry-run` lists N un-tickered CUSIPs ranked by held value, maps
  nothing. *Verified live during T2 smoke (5 CUSIPs → 2 mapped OK + 3
  ambiguous, 0 writes).*
- [ ] A live run maps a bounded `--limit` set, upserts `(ticker, figi,
  source='openfigi')`, and is **idempotent** (second run → 0 net new rows).
  *T4.*
- [ ] `resolve_cusip(<a non-S&P-500 ticker present in 13F>)` returns its
  CUSIP(s) after enrichment (was `[]` before). *T4.*
- [x] Existing seed / S&P 500 tickers are **never overwritten** (R6 app-side
  anti-join). *Encoded in `SELECT_UNMAPPED_CUSIPS_SQL`.*
- [x] Multi-match CUSIPs resolve to the US-composite ticker; truly ambiguous
  ones are skipped + logged + persisted, **never guessed** (L5, R3, R4).
  *Encoded in `openfigi.select_match` + R4 ambiguous-row persistence.*
- [x] **OpenFIGI responses are cached** (`openfigi_map_cache`): a second
  enrichment run for the same CUSIPs hits the cache (0 calls within TTL),
  and `--refresh` forces a re-fetch (§2.3, R9). *Encoded in
  `openfigi.map_cusips`; unit-tested in `test_openfigi.py`.*
- [x] Unit tests pass offline (fixtures); no `aiohttp`; respects rate limits
  with backoff. *20/20 passing.*
- [x] `Tools/docs/DESIGN.md` + this per-tool spec document the new script.

## Notes / gotchas

- The R5 SQL is written without CTEs because the `fmp_cached.execute_query`
  helper checks the first word of the query (`SELECT` → rows; otherwise →
  rowcount as `int`). A leading `WITH` silently returns 0. Inline subqueries
  express the same latest-period-per-filer join.
- `--limit` counts **distinct CUSIPs**, not jobs/rows — important because a
  single batch contains up to 100 CUSIPs.
- Single-threaded by design (R2 reviewer note 5): the batch endpoint already
  amortizes network cost; adding threads only makes the rate-limiter harder.
- CUSIP identifiers are **licensed** (CUSIP Global Services / S&P) — local
  use only; never redistribute the table.
