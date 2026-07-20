# P0 Data-Layer runtime audit (#513-#525)

**Date:** 2026-07-20

**Symbol universe:** AAPL / SPY / sp500

**Summary:** 22/28 OK, 0 EMPTY, 3 ERROR, 2 UNAVAILABLE, 1 SKIPPED.

## Legend

- **OK** — endpoint returned non-empty results. Downstream widgets unblocked.
- **EMPTY** — endpoint returned no rows; may be valid (e.g. no IPOs today) or silent-fail bug — investigate case-by-case.
- **ERROR** — endpoint raised. Reason recorded.
- **UNAVAILABLE** — endpoint not on ``obb.*`` in the current venv (missing extension install). File as env-sync bug.
- **SKIPPED** — deliberately not probed (cache infra with no upstream).

## Coverage matrix

| Cluster | Endpoint | Label | Status | Rows | Notes |
|--------:|----------|-------|--------|-----:|-------|
| #513 | `obb.economy.calendar` | Economic calendar | ✅ OK | 567 |  |
| #513 | `obb.fixedincome.government.treasury_rates` | Treasury rates | ✅ OK | 248 |  |
| #513 | `obb.economy.indicators` | Economic indicators (FRED) | ❌ ERROR |  | OpenBBError: 
[Error] -> 1 validations error(s)
[Arg] provider -> input: fred -> Input should be 'econdb' or 'imf' |
| #514 | `obb.equity.discovery.gainers` | Gainers | ✅ OK | 50 |  |
| #514 | `obb.equity.discovery.losers` | Losers | ✅ OK | 50 |  |
| #514 | `obb.equity.discovery.active` | Most active | ✅ OK | 50 |  |
| #514 | `obb.equity.compare.groups` | Sector rollup | ❓ UNAVAILABLE |  | AttributeError on obb.*: 'ROUTER_equity_compare' object has no attribute 'groups' |
| #515 | `obb.equity.price.historical` | OHLCV for TA (per-holding strip) | ✅ OK | 251 |  |
| #516 | `(no upstream)` | portfolio_intel_cache table | ➖ SKIPPED |  | Cache infrastructure — no upstream endpoint to probe |
| #517 | `obb.index.constituents` | SP500 constituents (warmer) | ✅ OK | 525 |  |
| #517 | `obb.etf.holdings` | ETF holdings warmer | ✅ OK | 504 |  |
| #517 | `obb.equity.price.historical` | OHLCV warmer | ✅ OK | 251 |  |
| #518 | `obb.etf.info` | ETF info | ✅ OK | 1 |  |
| #518 | `obb.etf.sectors` | ETF sector weightings | ✅ OK | 12 |  |
| #518 | `obb.etf.countries` | ETF country weightings | ✅ OK | 9 |  |
| #519 | `obb.equity.calendar.earnings` | Earnings calendar | ✅ OK | 9932 |  |
| #519 | `obb.equity.calendar.dividend` | Dividend calendar | ✅ OK | 1008 |  |
| #519 | `obb.equity.calendar.splits` | Splits calendar | ✅ OK | 49 |  |
| #519 | `obb.equity.calendar.ipo` | IPO calendar | ✅ OK | 2 |  |
| #520 | `obb.equity.estimates.analyst_search` | Analyst estimates | ❌ ERROR |  | OpenBBError: 
[Error] -> 1 validations error(s)
[Arg] provider -> input: fmp_cached -> Input should be 'benzinga' |
| #520 | `obb.equity.estimates.price_target` | Price target | ✅ OK | 100 |  |
| #520 | `obb.equity.estimates.consensus` | Price-target consensus | ✅ OK | 1 |  |
| #521 | `obb.equity.ownership.insider_trading` | Insider trading | ✅ OK | 1000 |  |
| #522 | `obb.equity.ownership.institutional` | Institutional ownership | ❌ ERROR |  | OpenBBError: 
[Unexpected Error] -> ValueError -> All 1 institutional-ownership record(s) failed FMP schema validation for query symbol='AAPL'; see WARNING logs for per-record details. This indicates  |
| #523 | `obb.regulators.sec.senate_trades` | Senate trades | ❓ UNAVAILABLE |  | AttributeError on obb.*: 'ROUTER_regulators_sec' object has no attribute 'senate_trades' |
| #524 | `obb.equity.fundamental.filings` | Company filings | ✅ OK | 80 |  |
| #525 | `obb.news.company` | Company news | ✅ OK | 250 |  |
| #525 | `obb.news.world` | World / general news | ✅ OK | 250 |  |

