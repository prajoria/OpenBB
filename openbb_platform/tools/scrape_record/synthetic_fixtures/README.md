# Synthetic Fixtures — test-only, do NOT ship as data

**Post-#1425**, real Yahoo-shaped provider snapshots live in each
operator's user-local SQLite DB at `~/.scrape_record/snapshots.db` and
are never committed to this repo.

The JSON files under `synthetic_fixtures/` are a minimal set kept
INSIDE the repo **exclusively** for unit-test purposes:

- `yahoo_options_chain/AAPL.json` — extractor + `test_snapshot_load`
- `yahoo_bond_etf_holdings/BND.json` — extractor tests
- `yahoo_equity_info/MSFT.json` — extractor tests
- `yahoo_equity_quote/MSFT.json` — extractor tests
- `yahoo_etf_holdings/QQQ.json` — extractor tests

Every fixture is treated as **synthetic** for licensing purposes:

- It is loaded only by tests, never by a fetcher call path in the
  running platform. Fetchers read from the user-local DB (with a legacy
  JSON fallback pointing at `snapshots/`, NOT here).
- Values may match a real Yahoo response shape byte-for-byte because
  the extractors need realistic input, but the intent of the checked-in
  copy is to exercise parsers/extractors — not to redistribute Yahoo
  data. Treat any field as a fixture, not a fact.

If a test would benefit from a NEW synthetic fixture, add it under this
directory and label it plainly. Do NOT re-populate the `snapshots/`
directory: that path is now for the (per-user, user-local) fallback
during the DB migration window, and even that will be dropped in a
follow-up.
