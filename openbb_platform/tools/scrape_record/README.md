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
| Downloads path | OUTSIDE repo (strict rule) | INSIDE repo (`snapshots/` checked in) |
| Login | Required, persistent Chrome profile | Optional (persistent profile if the site rate-limits anonymous) |
| Output | CSV / HTML dumps for user consumption | Structured JSON for downstream fetchers |
| Freshness | On-demand per user run | Snapshot committed; re-record on cadence |

## CLI

```bash
# Record a new scrape (opens Chromium via Playwright)
scrape-record record yahoo_options_chain --symbol AAPL --url https://finance.yahoo.com/quote/AAPL/options

# Re-record an existing recording (regenerates snapshot)
scrape-record replay yahoo_options_chain --symbol AAPL

# List all recordings + snapshot coverage
scrape-record list

# Print config paths
scrape-record config

# Dry-run: verify a snapshot parses under its extractor without opening a browser
scrape-record verify yahoo_options_chain --symbol AAPL
```

## Repo layout

```
scrape_record/
├── scrape_record/
│   ├── __init__.py
│   ├── cli.py           # argparse dispatcher
│   ├── config.py        # snapshots_dir (INSIDE repo), profile_dir (OUTSIDE)
│   ├── session.py       # persistent Chrome context (optional login)
│   ├── record.py        # Playwright record → save snapshot artifact
│   ├── replay.py        # replay a recording → regenerate snapshot
│   ├── extract.py       # apply extractor to raw snapshot → structured JSON
│   └── extractors/
│       ├── __init__.py
│       └── yahoo_options_chain.py
├── snapshots/
│   └── yahoo_options_chain/
│       └── AAPL.json    # checked-in canned data
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
