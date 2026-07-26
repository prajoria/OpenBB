# scrape-record

Record / replay / correct browser scrapes for **offline provider snapshots**.

**Sibling of `portfolio_export`.** Where `portfolio_export` records
authenticated brokerage flows and downloads user data OUTSIDE the repo,
`scrape-record` records **public** provider pages (Yahoo Finance options
chains, ETF holdings, etc.) and saves the extracted data as JSON
**INSIDE the repo** so downstream fetchers can serve the data offline
without live scraping at query time.

## Why

Two provider gaps in the OpenBB Platform's Portfolio Intelligence Engine
(#999 options chains, #1000 corporate bond ladders) have no free live
API. Yahoo Finance carries the data on public pages, but scraping it
inline at query time (the `yfinance` Python lib approach) is brittle:
Yahoo changes HTML/JSON periodically, and there's no support channel
when it breaks.

This tool decouples **scrape** from **serve**:

1. Record a scrape flow once per (source, symbol). Saved to
   `snapshots/<name>/<symbol>.json`.
2. Fetchers read from the snapshot files — never hit the live source at
   query time.
3. When the site drifts, re-record. The fetcher keeps working from the
   old snapshot until you refresh.

## Design vs `portfolio_export`

| Concern | `portfolio_export` | `scrape_record` |
|---|---|---|
| Target sites | Authenticated brokerage (Fidelity, Schwab, ...) | Public provider (Yahoo, CBOE, ...) |
| Downloads path | OUTSIDE repo (strict rule) | OUTSIDE repo (user-local SQLite DB, see #1425) |
| Login | Required, persistent Chrome profile | Optional (persistent profile if the site rate-limits anonymous) |
| Output | CSV / HTML dumps for user consumption | Structured JSON envelopes in a per-operator SQLite store |
| Freshness | On-demand per user run | Per-operator record cadence; nothing shipped |

## Where snapshots live (post-#1425)

Real Yahoo-shaped provider snapshots live in a **user-local SQLite DB**
at `~/.scrape_record/snapshots.db` (override via
`SCRAPE_RECORD_DB_PATH`). One row per `(name, symbol)`, idempotent
upsert. Nothing Yahoo-shaped is committed to this repo — this aligns
with Yahoo Finance's ToS and with how `yfinance` is documented
("personal use only"): every operator records and keeps their own copy
in a non-abusive, personal-use fashion.

A minimal set of clearly-labeled **synthetic** fixtures lives inside
the repo under `synthetic_fixtures/` — test-only, see the README there.

During the migration window the reader path is DB-first with a legacy
`snapshots/` JSON fallback; the writer path emits to both. The JSON
fallback will be dropped in a follow-up once every operator has
migrated.

## CLI

```bash
# Record a new scrape (opens Chromium via Playwright) — writes to DB + JSON
scrape-record record yahoo_options_chain --symbol AAPL --url https://finance.yahoo.com/quote/AAPL/options

# Re-record an existing recording (regenerates snapshot)
scrape-record replay yahoo_options_chain --symbol AAPL

# List all snapshots on disk (legacy JSON tree; use `sqlite3 ~/.scrape_record/snapshots.db 'SELECT name,symbol FROM snapshot'` for DB)
scrape-record list

# Print config paths (including db_path)
scrape-record config

# Dry-run: verify a snapshot parses under its extractor without opening a browser
scrape-record verify yahoo_options_chain --symbol AAPL

# One-time import of any legacy snapshots/*.json into the user-local DB (idempotent)
scrape-record migrate            # real
scrape-record migrate --dry-run  # report only
```

## Repo layout

```
scrape_record/
├── scrape_record/
│   ├── __init__.py
│   ├── cli.py           # argparse dispatcher (incl. `migrate`)
│   ├── config.py        # profile_dir + db_path (both OUTSIDE repo)
│   ├── session.py       # persistent Chrome context (optional login)
│   ├── record.py        # Playwright record → save envelope (DB+JSON)
│   ├── replay.py        # replay a recording → regenerate snapshot
│   ├── store.py         # SQLite snapshot store (SnapshotStore)
│   ├── extract.py       # apply extractor to raw snapshot → structured JSON
│   └── extractors/
│       ├── __init__.py
│       └── yahoo_options_chain.py
├── synthetic_fixtures/  # test-only synthetic snapshots (labeled)
│   └── README.md
├── recordings/
│   └── yahoo_options_chain.py  # per-source recorder script
├── tests/
└── pyproject.toml
```

## First fetcher

`YFinanceRecordedOptionsChainsFetcher` in `openbb_yfinance` reads
`snapshots/yahoo_options_chain/<symbol>.json` at fetch time. No live
Yahoo calls. Ships in a follow-up PR (#1347).

## Related

- Epic: #1345
- PR 1 (this): framework skeleton + AAPL options snapshot (#1346)
- PR 2: options fetcher wiring (#1347) — closes #999
- PR 3: bond ETF holdings + fetcher (#1348) — closes #1000
