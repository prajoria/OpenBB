# fmp_cached coverage audit for P0 Data-Layer clusters (#827)

**Date:** 2026-07-19

**Models directory:** `openbb_platform\providers\fmp_cached\openbb_fmp_cached\models`

**Summary:** 29/33 endpoints covered by an fmp_cached module. 0 true gaps. 4 rows n/a (no upstream call — cache/derived).

## Coverage matrix

| Cluster | Endpoint | fmp_cached module | Status |
|---|---|---|---|
| #512 EtfHoldings | `obb.etf.holdings` | `models/etf_holdings.py` | ✅ OK |
| #513 Economics | `obb.economy.calendar` | `models/economic_calendar.py` | ✅ OK |
| #513 Economics | `obb.fixedincome.government.treasury_rates` | `models/treasury_rates.py` | ✅ OK |
| #513 Economics | `obb.fixedincome.government.yield_curve` | `models/yield_curve.py` | ✅ OK |
| #513 Economics | `obb.economy.indicators (FRED)` | `n/a (no upstream call)` | ➖ - |
| #514 Market Performance | `obb.equity.discovery.gainers` | `models/equity_gainers.py` | ✅ OK |
| #514 Market Performance | `obb.equity.discovery.losers` | `models/equity_losers.py` | ✅ OK |
| #514 Market Performance | `obb.equity.discovery.active` | `models/equity_most_active.py` | ✅ OK |
| #514 Market Performance | `obb.equity.compare.groups (sector rollup)` | `models/price_performance.py` | ✅ OK |
| #515 Technical Indicators (per-holding strip) | `obb.equity.price.historical (OHLCV feed)` | `models/equity_historical.py` | ✅ OK |
| #516 Derived-analytics cache table | `(no upstream call)` | `n/a (no upstream call)` | ➖ - |
| #517 Cache warmers for common ETFs + S&P500 constituents | `obb.index.constituents (SP500)` | `models/index_constituents.py` | ✅ OK |
| #517 Cache warmers for common ETFs + S&P500 constituents | `obb.etf.holdings (warmer)` | `models/etf_holdings.py` | ✅ OK |
| #517 Cache warmers for common ETFs + S&P500 constituents | `obb.equity.price.historical (warmer)` | `models/equity_historical.py` | ✅ OK |
| #518 EtfInfo + EtfSectorWeightings + EtfCountryWeightings | `obb.etf.info` | `models/etf_info.py` | ✅ OK |
| #518 EtfInfo + EtfSectorWeightings + EtfCountryWeightings | `obb.etf.sectors` | `models/etf_sectors.py` | ✅ OK |
| #518 EtfInfo + EtfSectorWeightings + EtfCountryWeightings | `obb.etf.countries` | `models/etf_countries.py` | ✅ OK |
| #519 Calendars: Earnings + Dividends + Splits + IPOs | `obb.equity.calendar.earnings` | `models/calendar_earnings.py` | ✅ OK |
| #519 Calendars: Earnings + Dividends + Splits + IPOs | `obb.equity.calendar.dividend` | `models/calendar_dividend.py` | ✅ OK |
| #519 Calendars: Earnings + Dividends + Splits + IPOs | `obb.equity.calendar.splits` | `models/calendar_splits.py` | ✅ OK |
| #519 Calendars: Earnings + Dividends + Splits + IPOs | `obb.equity.calendar.ipo` | `models/calendar_ipo.py` | ✅ OK |
| #520 Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades | `obb.equity.estimates.analyst_search` | `models/analyst_estimates.py` | ✅ OK |
| #520 Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades | `obb.equity.estimates.price_target` | `models/price_target.py` | ✅ OK |
| #520 Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades | `obb.equity.estimates.consensus (price_target_consensus)` | `models/price_target_consensus.py` | ✅ OK |
| #520 Analyst: Estimates + Ratings + PriceTarget + UpgradesDowngrades | `obb.equity.estimates.historical (upgrades/downgrades)` | `n/a (no upstream call)` | ➖ - |
| #521 InsiderTrades | `obb.equity.ownership.insider_trading` | `models/insider_trading.py` | ✅ OK |
| #522 Form 13F | `obb.equity.ownership.institutional (13F extract)` | `models/institutional_ownership.py` | ✅ OK |
| #522 Form 13F | `(holder performance = derived, no upstream)` | `n/a (no upstream call)` | ➖ - |
| #523 Senate Disclosures | `obb.regulators.sec.senate_trades / house_trades` | `models/government_trades.py` | ✅ OK |
| #524 SEC Filings | `obb.equity.fundamental.filings` | `models/company_filings.py` | ✅ OK |
| #524 SEC Filings | `obb.regulators.sec.filings` | `models/discovery_filings.py` | ✅ OK |
| #525 News | `obb.news.company` | `models/company_news.py` | ✅ OK |
| #525 News | `obb.news.world` | `models/world_news.py` | ✅ OK |

## Gaps requiring `area:fmp-cached-gap` follow-ups

None. Every endpoint listed in the P0 cluster specs has a matching fmp_cached module. The M1 preflight is unblocked; Kai's P0 cluster work can proceed without waiting on the fmp_cached team.


## Notes on this audit's scope

- **Module presence ≠ runtime health.** This audit verifies `models/<name>.py` exists. Whether the class inside is registered with the OpenBB router and returns non-empty data on a live call is a downstream check (see #780 for the pattern). If any consumer of a `✅` row hits an empty result on real data, file as an *implementation gap* (bug), not a *coverage gap* (new endpoint request).
- **`fmp` fallback still tracked.** Rows marked `➖ (n/a)` are cases where the P0 cluster explicitly has no upstream call (cache infrastructure, derived analytics). They are NOT `fmp` fallbacks — no `area:fmp-cached-gap` needed.
- **PRD-vs-fmp mapping is subject to revision.** The endpoint labels above match the P0 cluster issue bodies and PRD §14 as of the audit date. If Kai's implementation surfaces additional endpoints not enumerated here, extend `CLUSTERS` in `scripts/audit_fmp_cached_coverage.py` and re-run — the audit is deterministic and cheap to re-execute.
