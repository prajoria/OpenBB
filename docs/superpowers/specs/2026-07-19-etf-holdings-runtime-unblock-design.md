# Design — EtfHoldings runtime unblock (`obb.etf.holdings` E2E)

- **Date:** 2026-07-19
- **Issue:** [#512 `[portfolio] [P0][Data] EtfHoldings model (etf/holdings) — PRIORITY, unblocks Lane B`](https://github.com/prajoria/OpenBB/issues/512)
- **Parent epic:** #491 Portfolio Intelligence Engine
- **Branch:** `feat/pi-data/etf-holdings-gh-512`
- **Author:** Claude (openbb-dev-cycle v3, Phase 1)
- **Status:** Draft — scope-corrected after live verification of existing scaffolding

---

## 1. Purpose

Get `obb.etf.holdings(symbol=<any portfolio_basket ETF>, provider="fmp_cached")` returning **real holdings rows** on this fork, without requiring a live FMP API key, so **Lane B (Analytics)** can proceed with X-Ray look-through, /portfolio/intel/xray route (#541), and every downstream unwrap consumer.

## 2. Scope-correction from the issue title

The issue title says "EtfHoldings model — first reference model. Pydantic + SQLAlchemy + gap-detection + round-trip test + recorded fixture." That was the *original* intent when the tracker was seeded in July 2026, before the extensive `fmp_cached` refactor landed. Live verification today (2026-07-19) shows:

| Layer | State |
|---|---|
| Standard model `EtfHoldingsData` in `openbb-core` | ✅ Present, ~40 fields, unchanged for months |
| Extension `openbb-etf` with `router.command("/holdings")` | ✅ Present (`openbb_platform/extensions/etf/`) |
| Provider fetcher `FMPCachedEtfHoldingsFetcher` (3-tier: FMP → issuer → N-PORT stub) | ✅ Present, 282 lines, provider-registered |
| Extension installed in `.venv_win` | ⚠ Missing until `pip install -e openbb_platform/extensions/etf --no-deps` — `dev_install.py` LOCAL_DEPS installs but a fresh-checkout race leaves this venv without `openbb-etf` |
| `obb.etf.holdings("SPY", provider="fmp_cached")` returns non-empty | ❌ Returns 0 rows: FMP tier 401 (invalid key), issuer tier only covers 11 GICS SPDRs (`XLB`/`XLC`/…/`XLY`) — no `SPY`/`QQQ`/`IWM`/`DIA`/`VTI`, N-PORT tier is a stub |
| Recorded-fixture round-trip test | ❌ None |
| `@pytest.mark.integration` live smoke | ❌ None |

**Real deliverable = runtime unblock**, not "build the model". The below is what actually needs to ship to satisfy #512's *spirit*.

## 3. In / out of scope

**In scope:**

- **3.1 — Env-sync fix**: ensure `dev_install.py -e` reliably installs `openbb-etf` in the venv (parity with the seven other LOCAL_DEPS entries). Bug reproduces on this checkout; needs to not recur on other clones.
- **3.2 — Issuer-tier expansion**: add `SPY`, `QQQ`, `IWM`, `DIA`, `VTI`, `IVV`, `VOO`, `ACWI`, `EFA`, `EEM` to `ISSUER_REGISTRY` with the correct issuer-file adapter (SSGA for SPY/DIA, Invesco for QQQ, iShares/BlackRock for IWM/IVV/ACWI/EFA/EEM, Vanguard for VTI/VOO). Each vendor has a distinct file format, so new parsers land where the SSGA parser lives.
- **3.3 — Recorded-fixture unit test**: capture one real FMP response + one real SSGA workbook to disk (`openbb_platform/providers/fmp_cached/tests/fixtures/etf_holdings/`). Test hits the fetcher with `http` patched to serve the recorded bytes; asserts row count > 0 and the fields the router+xray consume are populated.
- **3.4 — Live integration test** (`@pytest.mark.integration`): calls the real `obb.etf.holdings("XLK")` end-to-end. Skipped without keys.
- **3.5 — Portfolio-basket coverage assertion**: single test enumerates the portfolio_basket ETF set (a constant list — the 10 symbols above plus the 11 SPDR sectors already covered) and asserts each is either in `ISSUER_REGISTRY` or has a live-integration guard. Discriminating — if someone adds a new ETF to the basket, this test fails until the registry entry lands.

**Out of scope:**

- **N-PORT bulk index** (tier 3). Stub stays a stub; deferred as a separate design (SEC quarterly bulk EDGAR ingest is a project of its own).
- **New provider fetchers** — no new Fetcher classes; strictly extending the existing `FMPCachedEtfHoldingsFetcher._try_issuer` path via `ISSUER_REGISTRY`.
- **Router-side conversion** to the xray `Holding` shape — that's the `/portfolio/intel/xray` route (#541), which is the next issue in the sequence, not this one.
- **Non-US ETFs** (Canadian ETFs, UCITS, JP-listed) — issuer files exist but the fixture cost per issuer is real; ship US first, file follow-ups.
- **Automatic staleness detection** for issuer files (SSGA rotates monthly). L2 cache in fmp_cached already TTL-caches to 1 day; that's good enough for this cut.

## 4. Design decisions (with rationale)

### 4.1 Why extend the existing fetcher rather than build a parallel one

`FMPCachedEtfHoldingsFetcher` already has the right 3-tier structure, MySQL cache, and gap-detection log wiring. Splitting into a parallel fetcher would fork the cache table, double the maintenance surface, and force every downstream to know which class to import. Extending it is one PR; forking is three.

### 4.2 Why add issuers via `ISSUER_REGISTRY` rather than a plugin system

The universe of ETF issuers is <10. A dict-lookup-with-per-vendor-parser is 1 file, ~500 lines total. A plugin/entry-point system is ~800 lines of scaffolding for one lookup. Not the time.

### 4.3 Why 10 tickers + the existing 11 SPDRs, not "all ETFs"

The portfolio_basket set is bounded (currently the ETFs held by the demo portfolios plus the sector rotation set). Ship for the actual demand; iShares alone has ~400 ETFs and we don't need them until we do. The `coverage_test` (§3.5) makes gaps visible without pretending to solve them.

### 4.4 Where the recorded fixtures live

`openbb_platform/providers/fmp_cached/tests/fixtures/etf_holdings/` with subdirs `fmp/` and `ssga/` (and `invesco/`, `blackrock/`, `vanguard/` as those parsers land). One JSON per FMP response (`spy_fmp.json`), one .xlsx per SSGA workbook (`spy_ssga.xlsx`, ~50KB). Fixtures are byte-exact recordings, checked in, dated in filename. Refresh cadence: **manual, on schema drift** — the recorded-fixture unit test's job is to fail loud when the shape changes, not to auto-refresh from live.

### 4.5 Env-sync — how

`dev_install.py`'s LOCAL_DEPS declaration includes `openbb-etf`, but a fresh checkout of this fork may not run `dev_install.py -e` before the first import attempt. Two safety nets:

1. Add a `[dev-only-shipped]` group entry so `poetry install --with dev-only-shipped` covers the fork extensions.
2. Add a tiny import-time assertion in `openbb_portfolio_intel/__init__.py` that logs a WARNING (not an error) when `obb.etf` is missing, naming the exact command to fix it.

Both are cheap and prevent the "why does obb.etf not exist" question from being asked again.

## 5. File layout

```
openbb_platform/
├── providers/fmp_cached/
│   ├── openbb_fmp_cached/models/
│   │   └── etf_holdings_issuer.py            # +10 registry entries, 2-3 new parser functions
│   └── tests/
│       ├── fixtures/etf_holdings/
│       │   ├── fmp/spy_fmp.json              # NEW recorded (small)
│       │   ├── ssga/spy_ssga.xlsx            # NEW recorded (~50KB)
│       │   └── ssga/xlk_ssga.xlsx            # NEW recorded (~50KB) — already-registered sector SPDR
│       ├── unit/test_etf_holdings_e2e.py     # NEW — 4-6 tests with recorded fixtures
│       └── integration/test_etf_holdings_live.py  # NEW — @pytest.mark.integration
├── extensions/portfolio_intel/
│   └── openbb_portfolio_intel/__init__.py    # +import-time obb.etf sanity warn
└── dev_install.py                            # +ensure openbb-etf ends up installed
```

Test count: 4-6 unit (all recorded fixtures, no network) + 1 integration (live-key gated) + 1 coverage test (schema-shaped, no network). Total ~7 new tests.

## 6. Testing plan

1. **`test_fmp_tier_happy_path`** — mock `http` to serve `spy_fmp.json`; assert 500+ rows, `symbol/name/weight` populated.
2. **`test_fmp_tier_401_falls_through_to_issuer`** — mock FMP to raise 401; mock SSGA to serve `spy_ssga.xlsx`; assert issuer-tier rows.
3. **`test_issuer_tier_unknown_ticker_returns_empty_no_raise`** — request `IBIT` (not registered); assert `[]` returned, no exception, warning logged.
4. **`test_ssga_parser_field_completeness_spy`** — parse `spy_ssga.xlsx`; assert every row has `symbol,name,weight`; assert weights sum to ~1.0 within 1% (SSGA rounds).
5. **`test_invesco_parser_field_completeness_qqq`** — parse a recorded QQQ file (Invesco CSV — different format from SSGA).
6. **`test_coverage_portfolio_basket_universe`** — enumerate the portfolio_basket ETF list; for each, assert it's either in `ISSUER_REGISTRY` or has an FMP fallback expectation (marks with `@pytest.mark.integration`).
7. **`test_live_obb_etf_holdings_spy` (integration)** — calls the real `obb.etf.holdings("SPY", provider="fmp_cached")`; asserts row count > 0. Skipped without `fmp_api_key` OR issuer-file network.

All tests use `.venv_win`. Discriminating per R7.11: temporarily wipe the registry entry, confirm test #4 fails.

## 7. Review — analyst & engineering hats

> Reviewer added inline. Two hats: (A) senior engineer — is the shape buildable and correct; (B) portfolio-analyst — is a widened `ISSUER_REGISTRY` actually what unblocks Lane B, or does that layer solve the wrong problem.

**A1. (engineer, MEDIUM)** — the "env-sync" fix in §4.5 is a symptom-treatment. The root cause of `openbb-etf` not being in the venv is unclear (LOCAL_DEPS *lists* it). Two options: (a) diagnose the root cause and fix `dev_install.py` properly; (b) ship the WARNING sanity check as a safety net. Recommend (b) as a belt-and-suspenders regardless — a warning message costs nothing and future sessions won't waste 20 minutes on the diagnosis loop.

**A2. (engineer, LOW)** — the ~50KB xlsx fixtures pass through git LFS territory only if we cross ~100 of them. 10-15 fixture files at 50KB each is 500-750KB total — fine for regular git. Note it in the fixtures README so nobody adds a 5MB workbook and blows the repo up.

**B1. (analyst, HIGH)** — the coverage_test enumerating "portfolio_basket ETF list" needs a single-source-of-truth. If the list lives in the test file, it drifts from the actual basket. Recommend: extract the basket ETF universe to a named constant in `openbb_portfolio_intel` (e.g. `PORTFOLIO_BASKET_ETFS`) and import it from the test. That way when Lane C adds a new ETF to a demo portfolio, the coverage test fails on the next CI run, not silently.

**B2. (analyst, MEDIUM)** — SSGA/Invesco/BlackRock/Vanguard issuer files publish **daily snapshots**. That's fine for real-time widgets but *bad* for backtest / historical replay. The 1-day TTL on the L2 cache means historical replay silently gets "today's holdings" not "the holdings on the trade date". Flag this in the module docstring as a known limitation; historical-holdings-by-date is a real project (needs SEC N-PORT tier 3 or a paid data feed).

**B3. (analyst, MEDIUM)** — the "issuer tier only covers 11 SPDRs" claim was verified for `_SPDR_SECTORS` but not for iShares/Invesco/Vanguard. Some vendors publish CSV, some XLSX, some require a POST-with-cookie handshake. Each new issuer is a new failure mode. Ship SSGA-only for this cut + file follow-ups per issuer, so the "just add 10 tickers" scope doesn't secretly become "write 4 parsers".

## 8. Scope re-cut in response to review

Based on B3 (a real risk — one parser per issuer is 100-200 lines each), narrowing §3.2:

- **This PR ships SSGA parsers only** for `SPY`, `DIA` (SPDR trust products). Doesn't need a new parser — reuses the SSGA XLSX parser already shipped.
- **Files 4 follow-up issues** for QQQ/IWM/IVV/ACWI/EFA/EEM/VTI/VOO (grouped by issuer: one issue per issuer = Invesco / BlackRock / Vanguard, plus one for a fourth misc issuer). Each new-parser PR ships one issuer's tickers + one recorded fixture per ticker.
- **Coverage test** stays in scope, but marks `ISSUER_REGISTRY`-covered tickers as covered and non-covered tickers with `pytest.xfail(reason="issuer-file parser not yet shipped, see #NNN")` referencing the specific follow-up.

Result: this PR is ~200 lines of registry + 2 fixtures + 4-6 tests, verifiable in one review pass. Follow-ups are 4 small parser-and-fixtures PRs that Lane B can grab as needed.

## 9. Verdict

Ship §3.1 + §3.3 + §3.4 + §3.5 + §4.5 + narrowed §3.2 (SPY/DIA via SSGA reuse) as the initial PR. Follow-ups: 4 issuer-specific parser issues (Invesco, BlackRock/iShares, Vanguard, misc). This unblocks the *broadest* Lane B use case (SPY as market benchmark, DIA as second-most-common) within one PR while honestly deferring the per-issuer parser tail.
