# PRD & Functional Spec: Portfolio Intelligence Engine (`openbb-portfolio-intel`)

**Status:** Reviewed draft / Proposal — ready for leadership review
**Author:** Portfolio & Quant working group
**Reviewers:** Principal PM · Quant Research SME · Trading Desk Analyst — review pass 2026-07-11
**Target component:** OpenBB Platform first-party extension (`openbb-portfolio-intel`) + `portfolio_app` service extension + `fmp_cached` data bundle
**Companion documents:**
- [`docs/Specs/Backtesting-Engine-PRD.md`](./Backtesting-Engine-PRD.md) — the `openbb-backtest` engine this module delegates historical simulation to
- [`docs/Specs/Quant-Analysis-Module-Proposal.md`](./Quant-Analysis-Module-Proposal.md) — the `openbb-quant` strategy surface for signal generation
- [`docs/Specs/TechnicalTrading-Engine-PRD.md`](./TechnicalTrading-Engine-PRD.md) — technical-signal engine for entry/exit overlays
- [`Analysis/docs/PHASED_ANALYSIS_MASTER_PLAN.md`](../../Analysis/docs/PHASED_ANALYSIS_MASTER_PLAN.md) — 7-phase single-stock decision pipeline this rolls up to portfolio level
- [`docs/FMP-api/fmp-api-docs.md`](../FMP-api/fmp-api-docs.md) — canonical FMP endpoint catalog (86 sections, 279 endpoints) this PRD binds to
- [`portfolio_app/README.md`](../../portfolio_app/README.md) — existing positions service that this extension augments

**Date:** 2026-07-11
**Decision posture:** Correctness, privacy, and analytical rigor first; convenience second. Portfolio holdings are **sensitive lot-level data** — every design choice must preserve the existing `portfolio_basket` / `Portfolio_Positions` separation.
**Licensing posture:** The fork is **AGPL-3.0** and **non-commercial**. All new dependencies proposed here are permissive (MIT / BSD / Apache-2.0). No Commons-Clause exposure. FMP data is consumed under the fork's existing `fmp_cached` license and never redistributed.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Guiding Principles](#4-guiding-principles)
5. [Where This Fits in the Stack](#5-where-this-fits-in-the-stack)
6. [FMP Endpoint Coverage Matrix](#6-fmp-endpoint-coverage-matrix)
7. [Licensing Analysis](#7-licensing-analysis)
8. [Architecture — Layered Intelligence over `portfolio_basket`](#8-architecture--layered-intelligence-over-portfolio_basket)
9. [Functional Specification](#9-functional-specification)
10. [Data Layer & Caching Contract](#10-data-layer--caching-contract)
11. [Portfolio X-Ray (Look-Through Holdings)](#11-portfolio-x-ray-look-through-holdings)
12. [Event & Catalyst Calendar](#12-event--catalyst-calendar)
13. [Ownership & Smart-Money Overlay](#13-ownership--smart-money-overlay)
14. [Risk & Attribution Analytics](#14-risk--attribution-analytics)
15. [Rebalancing & What-If Simulator](#15-rebalancing--what-if-simulator)
16. [Paper Trading Engine](#16-paper-trading-engine)
17. [Alerting & Notifications](#17-alerting--notifications)
18. [Widget Surface (OpenBB Workspace)](#18-widget-surface-openbb-workspace)
19. [Non-Functional Requirements](#19-non-functional-requirements)
20. [Phased Delivery Roadmap](#20-phased-delivery-roadmap)
21. [Risks & Mitigations](#21-risks--mitigations)
22. [Open Questions / Decisions Needed](#22-open-questions--decisions-needed)
23. [Appendix A — FMP → Feature Traceability](#appendix-a--fmp--feature-traceability)
24. [Appendix B — Glossary](#appendix-b--glossary)

---

## 1. Executive Summary

This PRD proposes **`openbb-portfolio-intel`**, a first-party OpenBB Platform extension
and companion `portfolio_app` service layer that transforms the existing positions
service from a *display* of holdings into a full **portfolio intelligence engine**.

Today the fork can answer *"what do I own and what is it worth?"* — via `portfolio_app`
against `portfolio_basket` — and *"is this single stock a buy?"* — via `Analysis/`'s
7-phase pipeline. What it cannot yet answer is the set of questions every real portfolio
owner asks daily:

- *"What is my portfolio actually exposed to — sector, factor, geography, single-name concentration — once ETFs and funds are unwrapped?"*
- *"What earnings, dividends, splits, IPO lockups, or FOMC meetings hit my book in the next 30 days?"*
- *"Are insiders, 13F filers, or U.S. Senators buying or selling the names I hold?"*
- *"What is my portfolio's risk decomposition (beta, VaR, drawdown, contribution-to-risk) and where is it coming from?"*
- *"If I add / drop / resize position X, what happens to my sector weight, tracking error, and dividend yield — before I trade?"*

Answering these requires **pulling together ~40 of the 279 FMP endpoints** (≈32 of
them net-new bindings; the remainder already cached) and joining
them against the user's `portfolio_basket`, ETF holdings, and price/fundamental history
already in the `fmp_cached` MySQL cache. This PRD scopes that work as a single coherent
product surface — Python API, REST API, and OpenBB Workspace widgets — that becomes the
default landing experience of the desktop app.

**Central architectural decision:** the extension is **read-only over sanitized data**.
It consumes `portfolio_basket` (never raw `Portfolio_Positions`), reuses the
`fmp_cached` provider for all market data (never raw SQL against `equity_historical`),
and delegates historical simulation to `openbb-backtest`. It adds no new persistence
requirements beyond a small **derived-analytics cache** for expensive rollups
(look-through weights, factor exposures) that can be recomputed on demand.

**What ships in Phase 1:** X-Ray (look-through), Event Calendar, Insider/13F overlay,
and a Portfolio Risk Dashboard — all four wired to the OpenBB Workspace as first-class
widgets, with the underlying router callable directly from the `obb.portfolio.intel.*`
namespace. **Phase 2** adds a full **Paper Trading Engine** (§16) so every intelligence
widget works equally well against a real or a paper book.

**The ask (decision requested from leadership).** Approve a **16-week, ~1.5-engineer**
build (P0–P3, §20) to ship Phase 1 (X-Ray, Events, Risk, Smart-Money) and Phase 2
(What-If, Attribution, Paper Trading) as first-party OpenBB Workspace widgets. Two
decisions gate the architecture and need an explicit call: **Q7** — whether a
*read-only* lot channel for future tax analytics is acceptable within the privacy
boundary, and **Q8** — whether Paper Trading ships on a built-in fill model or waits
on `openbb-backtest` exposing a shared execution primitive (§22). Everything else in
this PRD is reversible and does not require sign-off to begin.

---

## 2. Problem Statement & Motivation

### 2.1 Where the fork is today

The fork already has three mature portfolio-adjacent layers:

| Layer | File(s) | What it does |
|---|---|---|
| **Data cache** | `openbb_platform/providers/fmp_cached/` | 67+ FMP models cached in MySQL; gap-detection; on-demand FMP fetch |
| **Positions service** | `portfolio_app/src/{db,data,service,main}.py` | FastAPI on :6903 that serves `portfolio_basket` positions + live market-value refresh |
| **Single-stock intelligence** | `Analysis/stock_analysis.py` | 7-phase decision pipeline: profile → fundamentals → technicals → valuation → risk → peer-relative → composite score |

### 2.2 The gap

None of these three layers answer **portfolio-level** questions. The `Analysis/` module
operates on **one symbol at a time**. The `portfolio_app` shows **positions and P&L**
but not exposures, risk, or events. Users must manually run `Analysis/` per ticker and
mentally aggregate — which defeats the point of owning a portfolio product.

FMP exposes the data required to close this gap, but it lives in **~40 different
endpoints across ~20 sections** of the API catalog (see §6) — roughly **32 of them
net-new bindings**, the remainder already cached. Without an integration
layer, users would have to hand-stitch:

- ETF/mutual fund holdings (`etfAndMutualFunds/holdings`) to unwrap fund positions
- Earnings/dividends/splits/IPO calendars to build a portfolio event stream
- Insider trades, Form 13F extracts, Senate disclosures for smart-money signals
- Ratings, price targets, upgrades/downgrades for sell-side sentiment
- Sector/industry classification for concentration analysis
- Historical prices + fundamentals for risk decomposition

### 2.3 Why now

- **`fmp_cached` is production-ready** — 67 models, cache-first, well-tested. The cost
  of adding more endpoint coverage is now marginal.
- **`portfolio_app` has stabilized** on `portfolio_basket` as the sanitized surface.
  A new intelligence layer can be built without touching sensitive lot data.
- **`openbb-backtest` and `openbb-quant` are being designed** in parallel. If we do
  *not* define the portfolio intelligence surface now, those engines will be built
  without a natural production consumer, and their outputs (weights, signals, factor
  loadings) will not compose cleanly.
- **Leadership is evaluating the fork's positioning** vs. Personal Capital, Kubera,
  Sharesight, and Portfolio Visualizer. The features in this PRD are the **table
  stakes** that make the fork a credible alternative.

### 2.4 Competitive landscape

| Capability | Personal Capital | Kubera | Sharesight | Portfolio Visualizer | **This PRD** |
|---|---|---|---|---|---|
| Aggregated holdings view | ✅ | ✅ | ✅ | ⚠️ manual | ✅ (via `portfolio_basket`) |
| ETF/fund look-through (X-Ray) | ⚠️ partial | ❌ | ⚠️ partial | ✅ | ✅ recursive — sector/country/name |
| Event & catalyst calendar | ❌ | ❌ | ⚠️ dividends only | ❌ | ✅ 5-stream merged |
| Smart-money overlay (insider/13F/Senate) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Risk decomposition + attribution | ⚠️ basic | ❌ | ⚠️ basic | ✅ | ✅ Brinson + component-VaR |
| What-if / rebalance preview | ❌ | ❌ | ❌ | ✅ | ✅ stateless |
| Paper trading | ❌ | ❌ | ❌ | ❌ | ✅ persistent, forward-time |
| Local-first / privacy-preserving | ❌ cloud | ⚠️ cloud | ❌ cloud | ❌ cloud | ✅ local cache, no PII egress |

> **Reviewer rationale (SME + PM):** the differentiated wedge is the *intersection* of
> (a) look-through X-Ray, (b) smart-money overlays, and (c) a privacy-preserving,
> local-first posture — **no incumbent combines all three**. Parity on commodity
> capabilities (aggregation, basic risk) is table stakes and we should not over-invest
> there. Paper trading is the retention hook that keeps users engaged *between*
> rebalances, when a pure tracker gives them no reason to open the app.

---

## 3. Goals & Non-Goals

### 3.1 Goals

- **G1 — Portfolio-level answers.** Turn every question in §1 into a single API call
  and a single widget.
- **G2 — Look-through correctness.** ETF/fund positions must be unwrapped to their
  underlying holdings for any exposure, sector, or concentration calculation.
- **G3 — Event-driven awareness.** A single "what's happening to my book in the next
  N days" stream that combines earnings, dividends, splits, IPO lockups, macro events,
  and analyst actions.
- **G4 — Smart-money overlay.** Insider trades, 13F changes, and Senate disclosures
  for every held name, surfaced as a per-position and per-portfolio ribbon.
- **G5 — Realistic risk math.** Portfolio beta, VaR/CVaR, drawdown, tracking error,
  and factor exposures, computed with the same conventions as `Analysis/` Phase 5.
- **G6 — What-If without side effects.** A staging surface for hypothetical trades
  that recomputes all §14 analytics in-memory without mutating `Portfolio_Positions`.
- **G7 — Workspace-native.** Every capability ships as an OpenBB Workspace widget
  alongside the existing single-stock widgets, using the same `widgets.json` model.
- **G8 — Privacy-preserving.** No lot-level, cost-basis, or owner-identifiable data
  ever leaves the `portfolio_basket` boundary. All API surfaces conform to the data
  access policy in `portfolio_app/src/data.py`.
- **G9 — Reproducible via `fmp_cached`.** Every analytic must be re-runnable from the
  cache with no live network dependency, given a warm cache.
- **G10 — Practice without risk.** A first-class **paper-trading** surface lets users
  place, fill, and track hypothetical orders against live prices with realistic fill
  mechanics, so every widget in this PRD works equally well against a *real* or *paper*
  book. Paper accounts are strictly isolated from real holdings.

### 3.2 Non-Goals

- **NG1 — Not a broker / not *real* order execution.** Nothing in this module places
  live trades, connects to brokerages, or writes back to `Portfolio_Positions`.
  Paper-trading orders (§16) live in a **separate namespace** (`paper_*` tables) and
  are explicitly labeled as simulated everywhere they surface.
- **NG2 — Not a tax engine.** Wash-sale, harvest, and lot-selection analytics are
  scoped separately (future PRD).
- **NG3 — Not a new data provider.** Everything consumes `fmp_cached`. If an endpoint
  is missing, we extend `fmp_cached`, not this module.
- **NG4 — Not a real-time streaming layer.** FMP websocket coverage is out of scope
  for Phase 1; refresh cadence is polling-based (configurable).
- **NG5 — Not a backtesting engine.** Historical simulation is delegated to
  `openbb-backtest`; this module *calls* it, does not re-implement it.
- **NG6 — Not a portfolio *optimizer*.** Weight optimization stays in `openbb-quant`;
  this module surfaces exposures and lets the user act on them.

### 3.3 Success Metrics & KPIs

Leadership should hold this proposal to measurable outcomes, not shipped-feature
counts. Proposed North-Star and supporting metrics:

- **North-Star — Weekly Active Portfolios (WAP):** distinct portfolios that render ≥1
  intelligence widget in a 7-day window. Target: **60% of active desktop users** reach
  a portfolio-intel widget within 30 days of GA.
- **Activation:** % of users who complete a first X-Ray in their first session — target
  ≥ 70%.
- **Depth:** median intelligence widgets pinned per portfolio — target ≥ 4.
- **Paper-trading adoption:** % of active portfolios opening ≥1 paper account in the
  first 60 days — target ≥ 25%.
- **Correctness / trust:** look-through coverage ratio (unwrapped weight ÷ total fund
  weight) — target ≥ 95% weighted coverage across held ETFs; unresolved funds are
  surfaced, never silently dropped (§11.3).
- **Performance:** warm-cache p95 latency within §19 targets on ≥ 95% of requests.
- **Reliability (hard gate):** **zero** cross-account or paper↔real leakage incidents.
  Any single incident is a Sev-1 release blocker (§21), not a dashboard number.

> **PM rationale (added in review):** these are deliberately *outcome* metrics. "32
> endpoints shipped" is output, not success — the product wins only if users **trust
> and act on** the exposure and risk numbers. The leakage KPI is binary on purpose: it
> is the one metric that can sink the product's credibility, so it is elevated to a
> release gate rather than a trailing indicator.

---

## 4. Guiding Principles

1. **Cache-first, provider-authoritative.** All FMP reads flow through the
   `fmp_cached` provider. Never raw SQL against `equity_historical` or any other
   FMP-owned table. Direct-DB access is limited to `portfolio_basket`.
2. **Compose, don't re-implement.** Wherever a risk metric already exists in
   `Analysis/stock_analysis.py`, expose the same function at portfolio level rather
   than re-derive.
3. **Deterministic outputs.** Every analytic pins the as-of date, cache snapshot,
   and FMP endpoint versions in the response envelope. Two runs at the same time
   against the same cache produce byte-identical output.
4. **Widget-first UX.** Every endpoint is designed with the target Workspace widget
   in mind — shapes, columns, and units chosen to render without post-processing.
5. **Fail visibly.** Missing look-through data (e.g. an unrecognized ETF) is surfaced
   as a warning row in the response, never silently dropped.
6. **Small, orthogonal endpoints.** Prefer 15 focused endpoints over 3 mega-endpoints
   so widgets can be independently cached and refreshed.

---

## 5. Where This Fits in the Stack

```
┌─────────────────────────────────────────────────────────────────────┐
│                        OpenBB Workspace                             │
│  (widgets.json — Portfolio X-Ray, Event Calendar, Smart-Money, …)   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP
        ┌──────────────────────┴──────────────────────┐
        │                                             │
┌───────▼───────────┐              ┌──────────────────▼──────────────┐
│  portfolio_app    │──── httpx ──▶│  OpenBB Platform API  (:6902)   │
│  (:6903)          │              │                                 │
│                   │              │  obb.portfolio.intel.*  ◀── NEW │
│  positions +      │              │  obb.equity.*                   │
│  X-Ray  ◀── NEW   │              │  obb.etf.*                      │
│  events ◀── NEW   │              │  obb.backtest.*                 │
│  risk   ◀── NEW   │              └──────────────┬──────────────────┘
└─────────┬─────────┘                             │
          │                                       │
          │ SQL (portfolio_basket ONLY)           │ fmp_cached provider
          ▼                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     MySQL cache (fmp_cached)                         │
│  67+ tables:  equity_historical, company_profile, etf_holdings,      │
│  earnings_calendar, insider_trades, form_13f_extract, senate_        │
│  disclosures, price_targets, ratings, sec_filings, …                 │
└──────────────────────────────────────────────────────────────────────┘
```

**Boundary rule:** the new `openbb-portfolio-intel` extension lives in the
**OpenBB Platform** and knows nothing about the user's holdings. The
`portfolio_app` **joins** `portfolio_basket` positions with the extension's
symbol-level analytics to produce portfolio-level answers. This preserves the
existing privacy boundary.

---

## 6. FMP Endpoint Coverage Matrix

The full FMP catalog has 279 endpoints across 86 sections. Phase 1 binds to the
subset below. Endpoints already wired into `fmp_cached` are marked ✅; new bindings
required are marked 🆕.

| FMP Section | Endpoint(s) | Status | Feature it feeds |
|---|---|---|---|
| Search | `search-symbol`, `search-name`, `search-cusip`, `search-isin` | ✅ | Symbol resolution for imported CSV/broker exports |
| Directory | `stock-list`, `etf-list`, `available-exchanges` | ✅ | Universe validation for X-Ray |
| Company | `profile`, `market-cap`, `shares-float`, `executive-compensation` | ✅ | X-Ray metadata, concentration table |
| Statements | `income`, `balance-sheet`, `cash-flow`, `ratios`, `key-metrics` | ✅ | Portfolio-weighted fundamentals |
| Analyst | `analyst-estimates`, `ratings-snapshot`, `price-target-consensus`, `grades-consensus` | 🆕 | Sell-side sentiment ribbon |
| Calendar | `dividends-calendar`, `earnings-calendar`, `ipos-calendar`, `splits-calendar` | 🆕 (partial) | Event Calendar |
| Chart | `historical-price-eod-full`, `historical-chart-1day`, `historical-chart-1hour` | ✅ | Risk metrics, drawdown, correlation |
| ETF & Funds | `etf/holdings`, `etf/info`, `etf/sector-weightings`, `etf/country-weightings` | 🆕 | **Look-through X-Ray (core dep)** |
| Form 13F | `institutional-ownership/extract`, `institutional-ownership/holder-performance-summary` | 🆕 | Smart-money overlay (institutional) |
| Insider Trades | `insider-trading/latest`, `insider-trading/search`, `insider-trading/statistics` | 🆕 | Smart-money overlay (insiders) |
| Senate | `senate-latest`, `senate-trading` | 🆕 | Smart-money overlay (political) |
| SEC Filings | `sec-filings-search/symbol`, `sec-filings-company-search/symbol`, `sec-filings-8-k` | 🆕 | Filing alerts |
| News | `news/stock`, `news/press-releases`, `news/general-latest` | 🆕 | Per-position news feed |
| Earnings Transcript | `earning-call-transcript`, `earning-call-transcript-latest` | 🆕 | Optional deep-dive drill-down |
| Market Performance | `sector-performance-snapshot`, `industry-performance-snapshot`, `biggest-gainers`, `biggest-losers` | 🆕 | Context bars around portfolio return |
| Economics | `economic-calendar`, `treasury-rates`, `economic-indicators` | 🆕 | Macro event overlay |
| Quote | `quote`, `quote-short`, `batch-quote` | ✅ | Live market-value refresh (already used) |
| Technical Indicators | `technical-indicators/*` | 🆕 | Per-holding technical strip in X-Ray |
| Commitment Of Traders | `commitment-of-traders-report` | 🆕 (v2) | Macro/commodity portfolios only |
| ESG | `esg-disclosures`, `esg-ratings` | 🆕 (v2) | ESG scorecard (opt-in) |

**Endpoint effort estimate.** 🆕 rows total ≈ 32 endpoints. Each follows the
established `fmp_cached` pattern (Pydantic model + SQL table + gap-fetch), estimated at
0.5 dev-day per endpoint = **~16 dev-days** to close data-layer gaps. This is a
prerequisite for Phase 1 and is tracked as an internal dependency, not a scope item.

---

## 7. Licensing Analysis

| Component | License | Compatible with AGPL-3.0 non-commercial fork? | Notes |
|---|---|---|---|
| FMP data | Commercial API terms | ✅ (per user's paid FMP account) | Never redistributed; cached locally under fair-use |
| `pandas`, `numpy`, `scipy` | BSD | ✅ | Existing dependency |
| `pyfolio-reloaded`, `empyrical-reloaded` | Apache-2.0 | ✅ | Optional — for tear-sheet rendering |
| `quantstats` | Apache-2.0 | ✅ | Optional |
| `riskfolio-lib` | BSD-3 | ✅ | Only if optimizer surfaces are added in v2 |
| `PyPortfolioOpt` | MIT | ✅ | Same |
| No Commons-Clause packages | — | ✅ | Explicitly excluded per fork policy |

All dependencies pinned in a new `[portfolio-intel]` extra so users who do not need
tear-sheet rendering can install a minimal footprint.

---

## 8. Architecture — Layered Intelligence over `portfolio_basket`

### 8.1 Component decomposition

```
openbb_platform/extensions/portfolio_intel/
├── openbb_portfolio_intel/
│   ├── __init__.py
│   ├── router.py                    # obb.portfolio.intel.* commands
│   ├── xray/
│   │   ├── lookthrough.py           # ETF/fund unwrap
│   │   ├── concentration.py         # HHI, top-N, single-name risk
│   │   └── exposures.py             # sector, country, factor
│   ├── events/
│   │   ├── calendar.py              # earnings + dividends + splits + IPO
│   │   └── macro.py                 # FOMC / CPI / treasury auctions
│   ├── smartmoney/
│   │   ├── insiders.py
│   │   ├── form13f.py
│   │   └── senate.py
│   ├── risk/
│   │   ├── decomposition.py         # portfolio VaR/CVaR/beta
│   │   ├── attribution.py           # Brinson-Fachler
│   │   └── drawdown.py
│   ├── whatif/
│   │   └── simulator.py             # in-memory rebalance preview
│   └── models/                      # Pydantic input/output schemas

portfolio_app/src/
├── intel.py                         # thin service layer joining
│                                    # portfolio_basket ⋈ intel.* endpoints
└── main.py                          # +7 new /portfolio/intel/* routes
```

### 8.2 Request lifecycle (X-Ray as reference)

1. Workspace widget calls `GET /portfolio/intel/xray?account=X`.
2. `portfolio_app` reads `portfolio_basket` rows for account X (SQL).
3. For each symbol classified as ETF/fund, `portfolio_app` calls
   `obb.etf.holdings(symbol=…)` via `openbb_client.py`.
4. For each equity holding, `portfolio_app` calls
   `obb.equity.profile(symbol=…)` + `obb.equity.compare.peers(symbol=…)` (already
   cached).
5. `portfolio_app` calls
   `obb.portfolio.intel.xray(positions=[…], underlyings=[…])` which returns the
   unwrapped exposure vector.
6. Result is post-processed for widget shape and returned as JSON.

All FMP reads are absorbed by `fmp_cached`; a warm cache serves the entire flow with
zero network I/O.

---

## 9. Functional Specification

For brevity, the spec below shows the router surface. Every command takes a
`positions: list[PositionInput]` and a `benchmark: str = "SPY"` unless noted, and
returns an `OBBject[Model]` per OpenBB conventions.

### 9.1 `obb.portfolio.intel.xray`
Unwraps ETFs/funds and returns a **look-through exposure vector** (sector, industry,
country, market-cap bucket, single-name weight).

### 9.2 `obb.portfolio.intel.concentration`
Herfindahl-Hirschman Index (HHI), top-10 weight, effective N, single-name-risk table.

### 9.3 `obb.portfolio.intel.events`
Merged event stream over a date range: earnings, dividends, ex-div, splits, IPO
lockups, 10-K/10-Q filings, macro releases from `economic-calendar`.

### 9.4 `obb.portfolio.intel.smart_money`
Aggregated insider net-buy, 13F net-position change, and Senate trades for every held
symbol over a trailing window. Includes per-holder performance summary.

### 9.5 `obb.portfolio.intel.risk`
Portfolio-level Sharpe / Sortino / VaR / CVaR / Max Drawdown / Ulcer / Beta / Alpha,
plus contribution-to-risk by symbol. Uses the same conventions as
`Analysis/stock_analysis.compute_risk_kpis`.

### 9.6 `obb.portfolio.intel.attribution`
Brinson-Fachler attribution vs. benchmark: allocation effect, selection effect,
interaction, over trailing 1M / 3M / 6M / 1Y windows.

### 9.7 `obb.portfolio.intel.whatif`
Accepts a **candidate trade list** (`[{symbol, delta_qty}, …]`) and returns a
side-by-side diff of X-Ray, concentration, and risk analytics. Stateless.

### 9.8 `obb.portfolio.intel.news`
Merged news + press-release + 8-K filing stream for held symbols; filter by severity
(material events only).

### 9.9 `obb.portfolio.intel.sentiment`
Weighted analyst rating, price-target upside, and recent upgrade/downgrade actions per
holding, rolled up to portfolio level.

---

## 10. Data Layer & Caching Contract

### 10.1 New `fmp_cached` models required

| Model | Endpoint | Table | Estimated rows/year (typical user) |
|---|---|---|---|
| `EtfHoldings` | `etf/holdings` | `etf_holdings` | 500 (ETFs held × avg 300 holdings) |
| `EarningsCalendar` | `earnings-calendar` | `earnings_calendar` | 50K (all US equities) |
| `DividendsCalendar` | `dividends-calendar` | `dividends_calendar` | 12K |
| `InsiderTrades` | `insider-trading/search` | `insider_trades` | 200K |
| `Form13FExtract` | `institutional-ownership/extract` | `form_13f_extract` | 5M (bulk) or filtered |
| `SenateDisclosures` | `senate-trading` | `senate_disclosures` | 3K |
| `PriceTargetConsensus` | `price-target-consensus` | `price_target_consensus` | 8K |
| `UpgradesDowngrades` | `grades-consensus` | `upgrades_downgrades` | 50K |
| `SecFilings8K` | `sec-filings-8-k` | `sec_filings_8k` | 80K |
| `EconomicCalendar` | `economic-calendar` | `economic_calendar` | 5K |
| `NewsStock` | `news/stock` | `news_stock` | 500K (windowed retention) |

> **Note:** the table above lists the highest-value **representative** models; the full
> set of ~32 net-new bindings (§6) follows the identical pattern and is enumerated in
> the P0 backlog, not duplicated here.

Each follows the existing `fmp_cached` pattern: Pydantic model → SQLAlchemy table →
gap-detection query → on-demand FMP fetch.

### 10.2 Derived-analytics cache (new)

To avoid recomputing look-through vectors every widget render, we add a tiny second
cache keyed by `(portfolio_hash, as_of_date, endpoint)`:

```
portfolio_intel_cache
├── portfolio_hash       CHAR(64)   -- SHA-256 of sorted (symbol, qty) tuples
├── as_of_date           DATE
├── endpoint             VARCHAR(64)
├── payload              JSON        -- endpoint response
├── created_at           TIMESTAMP
└── PRIMARY KEY (portfolio_hash, as_of_date, endpoint)
```

TTL = 1 trading day for exposure/X-Ray; 15 min for events; 1 hour for smart-money;
0 (never cached) for what-if.

### 10.3 Privacy contract (non-negotiable)

- Cache keys hash **(symbol, qty)** only. Never account, owner, cost basis, lot ID.
- `portfolio_intel_cache` may be inspected safely without exposing PII.
- All new endpoints inherit the `portfolio_basket`-only access rule from
  `portfolio_app/src/data.py`.

---

## 11. Portfolio X-Ray (Look-Through Holdings)

### 11.1 Algorithm

For each position `p = (symbol, weight_p)`:
- If `p` is an equity → contribute `weight_p` to `symbol`.
- If `p` is an ETF/fund → fetch its holdings `H = [(h_sym, w_h), …]`; contribute
  `weight_p × w_h` to each `h_sym`.
- Recursively unwrap funds-of-funds up to a configurable depth (default 2).

### 11.2 Rollups produced

- **By sector** (GICS)
- **By industry**
- **By country** (from `etf/country-weightings` when available; else `company.profile.country`)
- **By market-cap bucket** (mega/large/mid/small/micro)
- **By single name** (top-25 effective exposures)
- **Overlap matrix** (pairwise position → underlying overlap)

### 11.3 Warnings surfaced

- Fund not found in `etf/holdings` → carried at 100% weight to the fund symbol; row
  flagged `unresolved_fund=true`.
- Fund holdings older than 90 days → row flagged `holdings_stale=true`.
- Non-USD holdings → currency ISO code preserved; no FX normalization in Phase 1.

---

## 12. Event & Catalyst Calendar

Union of five streams, deduplicated on `(symbol, date, event_type)`:

1. **Earnings** — `earnings-calendar` filtered to held symbols; annotate with EPS
   estimate / prior EPS / surprise history from `analyst-estimates`.
2. **Dividends** — `dividends-calendar`; annotate ex-div, pay date, yield delta.
3. **Splits** — `splits-calendar`.
4. **IPO lockups** — `ipos-calendar` (position-relevant only if user holds newly-IPO'd
   name).
5. **Macro** — `economic-calendar` filtered to importance ≥ configured threshold
   (default: `high`).

Output shape optimized for a Workspace **timeline widget** (`date`, `symbol`,
`event_type`, `title`, `impact`, `notes`).

---

## 13. Ownership & Smart-Money Overlay

Per-position ribbon showing:

- **Insider net activity** over trailing 30 / 90 / 180 days
  (from `insider-trading/statistics`).
- **13F holder count delta** last quarter vs. prior (from
  `institutional-ownership/extract`).
- **Top-3 holder performance** (from `institutional-ownership/holder-performance-summary`).
- **Senate trades** in the last 90 days (from `senate-trading`), with party affiliation
  displayed neutrally.

Portfolio roll-up: **net smart-money score** = weighted average of per-position signals,
weighted by position size.

---

## 14. Risk & Attribution Analytics

### 14.1 Risk metrics

Reuse the exact math from `Analysis/stock_analysis.compute_risk_kpis` but at portfolio
return level:

- Sharpe / Sortino (rf-adjusted, annualized)
- Beta / Alpha vs. `benchmark`
- VaR 95%, CVaR 95% (historical + parametric)
- Max Drawdown, Ulcer Index
- Rolling 60-day volatility

### 14.2 Contribution to risk

Marginal VaR and component-VaR per position; component-beta per position; component-
volatility.

### 14.3 Brinson-Fachler attribution

Standard two-factor decomposition of active return vs. benchmark: **allocation** vs.
**selection** effect per sector. Requires benchmark constituent weights (from
`indexes/historical-constituents`).

---

## 15. Rebalancing & What-If Simulator

A stateless endpoint that:

1. Accepts current positions + a list of candidate deltas
   (`[{symbol: "NVDA", delta_qty: +10}, {symbol: "MSFT", delta_qty: -5}]`).
2. Applies deltas in memory; produces a **projected position vector**.
3. Recomputes X-Ray, concentration, and risk analytics on the projected vector.
4. Returns **diff view**: `{ metric, current, projected, delta }`.

No writes to any table. No trade execution.

Optional: delegate a "what would this portfolio have done over the last N years?"
question to `openbb-backtest` via `obb.backtest.portfolio(weights=…, start=…, end=…)`.

---

## 16. Paper Trading Engine

### 16.1 Purpose & framing

Paper trading is the **persistent, forward-time counterpart** to the stateless What-If
simulator (§15). Where What-If asks *"what would my exposure/risk look like right now
if I made this trade?"*, paper trading asks *"if I had actually placed this order
last Tuesday, what would have filled, when, at what price, and how has that position
performed since?"*

It is the natural bridge between three surfaces already in this stack:

- **`Analysis/` and `openbb-quant`** — generate a signal
- **Paper Trading (this section)** — practice acting on the signal in real time with a shadow book
- **`openbb-backtest`** — validate the signal historically over years of data

**Key architectural framing:** *paper trading = the backtest engine's execution model
run in forward-time mode against live-cache prices, with a persistent order/fill/
position ledger.* We therefore **reuse `openbb-backtest`'s execution primitives**
(slippage, commission, fill logic) rather than duplicate them. If `openbb-backtest`'s
execution model is not yet available when Phase 2 ships, we implement a minimal
`SimpleFillModel` inline and swap it in later.

> **Reviewer rationale (Trading Analyst + PM):** reusing `openbb-backtest`'s execution
> primitives is the right call — a second, divergent fill model would produce two
> different "truths" for the same order and erode trust the instant a user compares
> paper vs. backtest results. The `SimpleFillModel` fallback is acceptable *only* as a
> temporary bridge; **Q8 (§22) must be resolved before P2 code freeze** so we do not
> ship two execution engines by accident.

### 16.2 Scope

**In scope (Phase 2 of this PRD):**
- Multiple named **paper accounts** per user (e.g. `paper_default`, `paper_momentum`,
  `paper_options_test`), each with a configurable starting cash balance.
- Order types: `market`, `limit`, `stop`, `stop_limit`, `trailing_stop`.
- Time-in-force: `day`, `gtc`, `ioc`, `fok`.
- Long, short, and close-position orders on equities and ETFs.
- Realistic fill model: bid/ask spread from latest quote, configurable slippage bps,
  commission model (default: zero-commission, matching modern retail brokers).
- Cash management: buying power checked at submission; short proceeds held; margin
  disabled by default (Reg-T model available as opt-in).
- Corporate-action handling: dividends credited to cash on ex-date; splits adjust
  quantity; delisted symbols close at last price with a warning.
- Per-account **P&L, positions, and lot ledger**, computed with the **same math** as
  the real `portfolio_app` service (single source of truth for cost-basis logic).
- Every widget in §11–§14 works against a paper account via a `?account_id=<paper_*>`
  query parameter — the intelligence layer is book-agnostic.
- Explicit **PAPER** watermark/badge in every widget rendering a paper account, and a
  server-side rule that paper responses cannot be aliased under a real-account ID.

**Out of scope (deferred to v2):**
- Options, futures, and fixed-income paper orders.
- Multi-leg / bracket / OCO orders.
- Reg-T portfolio margin, cross-margin, or PDT rule enforcement.
- Order routing across simulated venues.
- Backfilled/historical paper accounts (that is what `openbb-backtest` is for).

### 16.3 Data model (new tables)

All tables live under a `paper_*` prefix, never intermixed with `Portfolio_Positions`
or `portfolio_basket`. A per-user isolation column (`user_id`) is mandatory.

```
paper_accounts
├── account_id            VARCHAR(64)  PK  -- e.g. "paper_default"
├── user_id               VARCHAR(64)  NOT NULL
├── display_name          VARCHAR(120)
├── starting_cash         NUMERIC(18,4)
├── cash_balance          NUMERIC(18,4)     -- current
├── currency              CHAR(3)  DEFAULT 'USD'
├── margin_enabled        BOOL      DEFAULT FALSE
├── commission_model      VARCHAR(32) DEFAULT 'zero'
├── slippage_bps          INT         DEFAULT 5
├── created_at            TIMESTAMP
└── UNIQUE (user_id, account_id)

paper_orders
├── order_id              UUID  PK
├── account_id            FK  → paper_accounts
├── symbol                VARCHAR(20)
├── side                  ENUM('buy','sell','sell_short','buy_to_cover')
├── qty                   NUMERIC(18,6)
├── order_type            ENUM('market','limit','stop','stop_limit','trailing_stop')
├── limit_price           NUMERIC(18,4)  NULL
├── stop_price            NUMERIC(18,4)  NULL
├── trail_amount          NUMERIC(18,4)  NULL   -- $ or %
├── time_in_force         ENUM('day','gtc','ioc','fok')
├── status                ENUM('open','filled','partial','cancelled','rejected','expired')
├── submitted_at          TIMESTAMP
├── filled_at             TIMESTAMP NULL
├── avg_fill_price        NUMERIC(18,4)  NULL
├── filled_qty            NUMERIC(18,6)  DEFAULT 0
├── rejection_reason      TEXT  NULL
└── INDEX (account_id, status), INDEX (account_id, symbol)

paper_fills
├── fill_id               UUID  PK
├── order_id              FK  → paper_orders
├── symbol                VARCHAR(20)
├── qty                   NUMERIC(18,6)
├── price                 NUMERIC(18,4)
├── commission            NUMERIC(18,4)
├── slippage_applied_bps  INT
├── filled_at             TIMESTAMP

paper_positions        -- derived, but persisted for widget latency
├── account_id            FK
├── symbol                VARCHAR(20)
├── quantity              NUMERIC(18,6)      -- signed (negative = short)
├── avg_cost              NUMERIC(18,4)
├── realized_pnl          NUMERIC(18,4)
├── PRIMARY KEY (account_id, symbol)

paper_ledger            -- append-only cash + corporate-action journal
├── entry_id              UUID  PK
├── account_id            FK
├── entry_type            ENUM('trade','dividend','split','fee','deposit','withdraw')
├── symbol                VARCHAR(20)  NULL
├── amount                NUMERIC(18,4)
├── occurred_at           TIMESTAMP
├── notes                 VARCHAR(255)
```

**Privacy note:** paper tables carry `user_id` but no lot-level PII from real
holdings. They are a separate privacy zone from `Portfolio_Positions`.

### 16.4 Fill model

Each `paper_orders` row is evaluated by a `FillEngine` on a fixed cadence
(configurable; default 5 s during market hours, disabled outside RTH unless
`allow_extended_hours=true` on the account).

**Fill rules (Phase 2 defaults):**

| Order type | Fill trigger | Fill price |
|---|---|---|
| `market` | Immediately on next tick | `mid` + `slippage_bps × side` if quote available; else `last` |
| `limit` (buy) | `ask ≤ limit_price` | `min(ask, limit_price)` |
| `limit` (sell) | `bid ≥ limit_price` | `max(bid, limit_price)` |
| `stop` (buy) | `last ≥ stop_price` | Converts to market at trigger |
| `stop_limit` | `last` crosses `stop_price` | Then behaves as `limit` |
| `trailing_stop` | Peak-tracking; triggers when `last` retraces by trail | Converts to market |

Partial fills are modeled if `qty × avg_daily_volume < 0.5%`; otherwise fills fully in
a single event. `ioc` cancels remainder immediately; `fok` requires full fill or
rejects; `day` orders expire at market close in the exchange's calendar.

**Quote source:** `obb.equity.price.quote(symbol=…)` via `fmp_cached`. If the cache
is > 60 s stale during RTH, the engine forces a refresh. Extended-hours quotes use
`quote-short` with a widened default spread (configurable).

**Commission model:** pluggable. Defaults included: `zero` (retail), `per_share`
(`$0.005/share, min $1`), `per_trade` (`$4.95`), `interactive_brokers_tiered`.

### 16.5 API surface

All new commands live under `obb.portfolio.intel.paper.*` (extension) and
`/portfolio/intel/paper/*` (portfolio_app).

| Command | Purpose |
|---|---|
| `paper.account.create({name, starting_cash, ...})` | Create paper account |
| `paper.account.list()` | List paper accounts for user |
| `paper.account.get(account_id)` | Account details + summary |
| `paper.account.reset(account_id)` | Wipe orders/fills/positions; restore starting_cash |
| `paper.account.delete(account_id)` | Soft-delete (marked closed) |
| `paper.order.submit(account_id, order)` | Submit an order; returns order_id |
| `paper.order.cancel(order_id)` | Cancel open order |
| `paper.order.replace(order_id, changes)` | Modify open order (qty / price / TIF) |
| `paper.order.list(account_id, status?, from?, to?)` | List orders |
| `paper.fills.list(account_id, from?, to?)` | List fills |
| `paper.positions.list(account_id)` | Current positions |
| `paper.ledger.list(account_id, from?, to?)` | Cash + corporate-action journal |
| `paper.performance(account_id, benchmark, window)` | Sharpe/Sortino/DD/return time series |

**Reuse of §11–§14 endpoints:** every existing intelligence endpoint accepts an
optional `account_id` query param. When present and `account_id` starts with
`paper_`, the endpoint loads positions from `paper_positions` instead of
`portfolio_basket`. No new endpoints needed for X-Ray/Events/Risk/Attribution against
paper — they are book-agnostic by construction.

### 16.6 UX contract

- Every widget rendered against a paper account displays a **PAPER** badge in the
  widget header and a subtle background tint.
- The account selector in the Workspace shows real and paper accounts in
  **separate groups**, real above paper, with a divider.
- Order submission is a **two-step confirm** dialog by default; can be disabled per
  account for power users.
- Order-book, blotter, and trade-history widgets ship alongside the intelligence
  widgets (see §18).

### 16.7 Determinism & reproducibility

- Fill decisions are logged with the exact quote snapshot that produced them
  (`paper_fills.slippage_applied_bps` + a per-fill `quote_snapshot_id` pointing to the
  cache row).
- A `paper.account.replay(account_id, from, to)` command reconstructs the account
  state at any point in time from the append-only `paper_ledger` — no destructive
  updates.
- Reset is destructive but audited via a `paper_reset_events` row (out of Phase 2
  scope; log-only for now).

### 16.8 Interaction with the rest of the PRD

| Feature | Behavior against paper account |
|---|---|
| §11 X-Ray | Works — positions come from `paper_positions` |
| §12 Events | Works — filtered to held paper symbols |
| §13 Smart-Money | Works — same overlay logic |
| §14 Risk & Attribution | Works — benchmark comparison uses real historical prices |
| §15 What-If | Works — treats paper positions as the base book |
| §17 Alerts | Extended: adds "paper order filled", "paper stop triggered" alerts |
| §18 Widgets | Adds 3 paper-specific widgets (blotter, order ticket, performance) |

### 16.9 Handoff to `openbb-backtest`

A `paper.account.export_backtest(account_id, start, end)` command generates a
`openbb-backtest`-compatible trade list from `paper_fills` so a user can validate
*"how would this paper strategy have done had I run it over the last 5 years?"*
without re-implementing the strategy. This is the single formal integration point
between the two engines.

---

## 17. Alerting & Notifications

**Phase 1:** in-widget only. The Event Calendar and Smart-Money widgets have a
"pinned alerts" panel that surfaces:

- Earnings in the next 5 trading days
- Ex-div in the next 5 trading days
- Insider open-market purchase > $100K
- 8-K filing for a held symbol
- Analyst downgrade for a top-10 holding
- **Paper-trading events:** order filled, stop triggered, GTC expiring soon,
  buying power < 10% of account equity

**Phase 2:** desktop-notification push and optional email digest (out of scope for this
PRD, tracked in v2).

---

## 18. Widget Surface (OpenBB Workspace)

New entries added to `portfolio_app/widgets.json`:

| Widget | Endpoint | Shape |
|---|---|---|
| Portfolio X-Ray (Sector) | `/portfolio/intel/xray?rollup=sector` | Pie |
| Portfolio X-Ray (Country) | `/portfolio/intel/xray?rollup=country` | Pie |
| Look-Through Top-25 | `/portfolio/intel/xray?rollup=name&top=25` | Table |
| Concentration & HHI | `/portfolio/intel/concentration` | Number + gauge |
| Event Calendar | `/portfolio/intel/events?days=30` | Timeline |
| Smart-Money Ribbon | `/portfolio/intel/smart_money?window=90d` | Table |
| Risk Dashboard | `/portfolio/intel/risk?benchmark=SPY` | Number-grid + chart |
| Brinson Attribution | `/portfolio/intel/attribution?window=1y` | Waterfall |
| What-If | `/portfolio/intel/whatif` | Diff card (interactive) |
| Analyst Sentiment | `/portfolio/intel/sentiment` | Table |
| Portfolio News | `/portfolio/intel/news?days=7` | List |
| **Paper: Order Ticket** | `POST /portfolio/intel/paper/order/submit` | Form |
| **Paper: Blotter** | `/portfolio/intel/paper/order/list?account_id=…` | Table |
| **Paper: Performance** | `/portfolio/intel/paper/performance?account_id=…` | Chart + KPI grid |

Widgets follow the same params/schema conventions already used for the 7 single-stock
widgets (see `portfolio_app/plans/single_stock_analysis_widgets.md`). Paper widgets
carry a **PAPER** badge and a distinct background tint per §16.6.

---

## 19. Non-Functional Requirements

| Concern | Target |
|---|---|
| Warm-cache p95 latency | X-Ray < 400ms · Events < 300ms · Risk < 600ms |
| Cold-cache p95 latency | X-Ray < 4s (fund holdings fetch) · Risk < 8s |
| Cache TTL | Per §10.2 |
| Concurrency | 20 rps sustained per portfolio_app instance |
| Memory | < 500 MB steady-state; < 2 GB peak during full X-Ray |
| Test coverage | Unit ≥ 90% on `intel/*`; integration ≥ 60% with recorded FMP fixtures |
| Determinism | Given a pinned cache snapshot, response bytes are stable |
| Observability | Every endpoint logs `(portfolio_hash, endpoint, cache_hit, latency_ms)` |
| Privacy | Zero PII in cache; verified by an automated schema test |
| Documentation | Every command has an `APIEx` and `PythonEx` example (OpenBB convention) |
| **Paper fill latency** | Fill decision within 1 tick (≤ 5 s) of quote crossing trigger |
| **Paper isolation** | Automated test asserts no query can return a paper row under a real-account ID or vice versa |

---

## 20. Phased Delivery Roadmap

| Phase | Duration | Scope | Exit criteria |
|---|---|---|---|
| **P0 — Data-layer gap fill** | 3 wks | Add 32 🆕 `fmp_cached` models per §6 | All models unit-tested; cache round-trips; gap-detection tested |
| **P1 — X-Ray + Events + Risk + Smart-Money** | 5 wks | §11–§14 + 8 widgets | E2E test: full dashboard renders in Workspace with real portfolio |
| **P2 — What-If + Attribution + Paper Trading** | 5 wks | §15, §14.3, §16 (paper accounts, orders, fills, positions, ledger, 3 widgets) | Diff view interactive; Brinson matches Bloomberg on a canned portfolio; paper account can round-trip a limit order end-to-end with correct fills and P&L |
| **P3 — News + Sentiment + Alerting v1 + Backtest hand-off** | 3 wks | §9.8, §9.9, §17 pinned alerts (including paper-fill alerts); wire `obb.backtest.portfolio`; `paper.account.export_backtest` | Alert panel renders; one-click "backtest this portfolio / this paper account" works |
| **v2 — Notifications, ESG, COT, tax, options paper** | tbd | Push notifications, ESG scorecard, tax-aware rebalancing, options/futures paper orders, Reg-T margin | Separate PRD |

Total P0–P3: **16 weeks** (≈ 1 quarter + 3 weeks), assumes 1 senior + 1 mid-level engineer.

> **Reviewer note on the estimate (PM):** the 16-week figure carries **no explicit
> buffer**. On this fork, data-layer integration (P0) has historically run ~20% long
> once FMP edge-cases surface (schema drift, missing fields, rate limits). Recommend
> leadership approve against an **18–20 week envelope**, treat 16 weeks as the stretch
> target, and hold **P3 (News / Sentiment / Alerts) as the de-scopable release valve**
> if the schedule slips — it is the lowest-severity, most deferrable slice.

---

## 21. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| FMP holdings coverage gaps for niche ETFs | Look-through under-reports exposure | Med | Warning row per §11.3; publish coverage report per portfolio |
| Cache bloat from Form 13F bulk data | MySQL disk pressure | Med | Store filtered-by-held-CUSIPs only in Phase 1; full bulk is opt-in |
| Attribution requires benchmark constituent history | Missing for non-S&P indices | Med | Ship SPY + QQQ + IWM + ACWI as Phase 1; document expansion path |
| Portfolio hash collisions leak cross-account data | Privacy incident | **High** | Hash includes account_id salt server-side; per-account cache namespace |
| FMP rate limits during cold-cache seeding | First-run latency spikes | Med | Background pre-warmer; token-bucket in `fmp_cached` |
| Widget spec drift vs. OpenBB Workspace | Widgets break on Workspace update | Low | Pin `widgets.json` schema; CI validation |
| Users conflate "smart-money buying" with "buy signal" | Miscommunication of intent | Med | Widget disclaimers; positioning as *context*, not *recommendation* |
| **Users mistake paper trades for real orders** | Behavioral / trust incident | **High** | Mandatory PAPER badge; distinct color; two-step confirm; server-side isolation test; separate account-selector group |
| **Paper fill model over-flatters strategies** | Users deploy losing real strategies | High | Default 5 bps slippage; document fill assumptions on every performance widget; encourage `openbb-backtest` validation via §16.9 |
| **Divergence between paper P&L math and real `portfolio_app` math** | Confusion when users compare | Med | Both surfaces call the **same** cost-basis/P&L functions; enforced by shared module + unit tests |
| **Corporate actions missed on paper positions** | Silent P&L drift | Med | Nightly job re-reconciles `paper_ledger` against `dividends-calendar` and `splits-calendar` |

---

## 22. Open Questions / Decisions Needed

1. **Multi-account rollup UX.** Should X-Ray default to per-account or all-accounts view?
2. **Currency normalization.** Phase 1 keeps native currency; is FX-normalized view a P1 or P2 feature?
3. **Look-through recursion depth.** Default 2 is safe; do we allow user override?
4. **Senate widget positioning.** Neutral display is required; should we hide party
   affiliation entirely to avoid politicization?
5. **13F retention policy.** Do we keep all history (5M+ rows/yr) or trailing 8 quarters?
6. **Backtest hand-off.** Does clicking "backtest this portfolio" open in a modal or
   navigate to a `openbb-backtest` view?
7. **Tax-lot integration.** Wash-sale and lot-selection analytics need lot-level data,
   which violates the current privacy boundary. Is a **read-only** lot channel
   acceptable, or does that require a separate PRD + threat model?
8. **Paper-trading fill model.** Do we ship with the built-in `SimpleFillModel` (§16.4)
   or gate P2 on `openbb-backtest` exposing a shared execution primitive? The former
   ships faster; the latter avoids future duplication.
9. **Paper account quotas.** How many paper accounts per user should be allowed? A
   soft cap (e.g. 10) prevents cache blow-up but may frustrate power users testing
   many strategies in parallel.
10. **Cross-account leakage guardrails.** Should the API refuse to return a paper
    account response if the caller last accessed a real account within the same
    session (to prevent screenshot-mix-up incidents), or is the PAPER badge sufficient?

---

## Appendix A — FMP → Feature Traceability

*(abridged — full matrix in §6; this table shows the reverse direction for the
capabilities that are new to the fork)*

| Feature | FMP endpoints consumed |
|---|---|
| X-Ray | `etf/holdings`, `etf/sector-weightings`, `etf/country-weightings`, `company/profile` |
| Event Calendar | `earnings-calendar`, `dividends-calendar`, `splits-calendar`, `ipos-calendar`, `economic-calendar` |
| Smart-Money | `insider-trading/latest`, `insider-trading/search`, `insider-trading/statistics`, `institutional-ownership/extract`, `institutional-ownership/holder-performance-summary`, `senate-latest`, `senate-trading` |
| Risk | `historical-price-eod-full`, `historical-chart-1day` |
| Attribution | `indexes/historical-constituents`, `historical-price-eod-full` |
| Sentiment | `ratings-snapshot`, `price-target-consensus`, `grades-consensus`, `analyst-estimates` |
| News | `news/stock`, `news/press-releases`, `sec-filings-8-k` |

---

## Appendix B — Glossary

- **Look-through** — resolving fund positions to their underlying holdings so exposure
  is measured at the security level, not the fund level.
- **HHI** — Herfindahl-Hirschman Index; sum of squared weights; concentration measure.
- **Brinson-Fachler** — attribution model decomposing active return into allocation
  and selection effects.
- **Component VaR** — a position's contribution to total portfolio VaR; sums to total
  VaR across positions.
- **13F** — SEC filing by institutional managers >$100M AUM listing equity holdings
  each quarter.
- **8-K** — SEC filing for material corporate events, filed within 4 business days.
- **`portfolio_basket`** — sanitized view of `Portfolio_Positions` exposed to API
  consumers; contains no lot / cost-basis / owner PII.
- **Paper trading** — persistent, forward-time simulated trading against live cache
  prices with realistic fill mechanics. Distinct from *what-if* (stateless preview)
  and *backtest* (historical replay).
- **Fill model** — the rule set that decides *whether* a resting order fills on a
  given tick and *at what price*. Governs slippage, partial fills, and TIF expiry.
- **Blotter** — the log of all orders (open, filled, cancelled, rejected) for a
  trading account, sortable and filterable in a widget.

---

## Reviewer's Closing Recommendation

*Added during the pre-leadership review pass — Principal PM · Quant Research SME ·
Trading Desk Analyst, 2026-07-11.*

**Recommendation: greenlight Phase 1 now; conditionally approve Phase 2.**

This is a well-scoped, architecturally disciplined proposal whose core strength is that
it *composes* existing, proven layers (`fmp_cached`, `portfolio_basket`, `Analysis/`,
`openbb-backtest`) rather than standing up parallel machinery. The privacy boundary is
treated as a first-class constraint — the correct posture for lot-level holdings data —
and the read-only-over-sanitized-data decision is the single most important thing this
design gets right.

Three conditions gate unconditional sign-off:

1. **Resolve Q8 (fill model) before P2 code freeze.** Shipping two execution engines is
   the most expensive *reversible* mistake available here; decide once, early.
2. **Elevate the cross-account / paper↔real leakage test to a release gate** (reflected
   in §3.3 and §21). One leakage incident is a credibility Sev-1.
3. **Re-baseline to an 18–20 week envelope** (§20 note) so P3 can absorb slippage
   without a fresh leadership approval cycle.

Phase 1 delivers the differentiated wedge — look-through X-Ray + smart-money overlay +
privacy-preserving posture (§2.4) — and should be greenlit immediately. Phase 2 (paper
trading) is high-value for retention but carries the two highest-severity risks in §21;
approve it **contingent** on conditions 1–2 above.

— *End review.*

---

*End of PRD.*
