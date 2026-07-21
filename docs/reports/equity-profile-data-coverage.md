# Single Equity Profile Dashboard — Data Coverage Audit (#781)

**Date:** 2026-07-21
**Scope:** Map every field in every section of the Equity Profile Dashboard PRD (#781) to `(provider, endpoint, field)`.
**Provider order of preference:** `fmp_cached` → `fmp` (with `area:fmp-cached-gap` GH issue) → out-of-scope.

Legend:

- ✅ **Covered** — endpoint exists in `fmp_cached` today; field maps directly.
- 🟡 **Covered-via-fmp** — endpoint exists only in raw `fmp`; use fallback + file `area:fmp-cached-gap` issue.
- ❌ **GAP** — no current provider covers this; needs external provider + new GH issue.
- 🧮 **Derived** — computed from covered fields (formula given).

---

## Section 1 — Header & Multi-Feed Live Price Ticker

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Asset Ticker | fmp_cached | `equity_profile` | `symbol` | ✅ |
| Issuer Name | fmp_cached | `equity_profile` | `name` | ✅ |
| Primary Exchange | fmp_cached | `equity_profile` | `exchange` | ✅ |
| Sector | fmp_cached | `equity_profile` | `sector` | ✅ |
| Industry | fmp_cached | `equity_profile` | `industry` | ✅ |
| Standard live price | fmp_cached | `equity_quote` | `last_price` | ✅ |
| Standard Δ (abs / %) | fmp_cached | `equity_quote` | `change`, `change_percent` | ✅ |
| Standard "Last update at HH:MM GMT-X" | fmp_cached | `equity_quote` | `last_timestamp` | ✅ |
| Overnight price (BOATS / ATS) | fmp_cached | `aftermarket_quote` | `price`, `timestamp` | ✅ |
| Overnight Δ (abs) | 🧮 | derived: `aftermarket_quote.price - equity_quote.previous_close` | | 🧮 |
| Overnight Δ (%) | 🧮 | derived: `aftermarket_quote.price / equity_quote.previous_close - 1` | | 🧮 |
| "Overnight via BOATS" label | UI | hard-coded string; provenance derives from `aftermarket_quote.data_source` | | ✅ |

**Section 1 verdict: 100% covered.** No provider gaps.

---

## Section 2 — Key Stats & Operating Metrics

### 2A. Primary statistics

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Market Cap | fmp_cached | `equity_profile` OR `key_metrics` | `market_cap` | ✅ |
| P/E TTM | fmp_cached | `key_metrics` | `pe_ratio_ttm` | ✅ |
| Basic EPS TTM | fmp_cached | `key_metrics` OR `historical_eps` | `eps_ttm` | ✅ |
| Net Income FY | fmp_cached | `income_statement` (annual) | `net_income` | ✅ |
| Revenue FY | fmp_cached | `income_statement` (annual) | `revenue` | ✅ |
| Shares Float | fmp_cached | `share_statistics` | `float_shares` | ✅ |
| Beta 1Y | fmp_cached | `equity_profile` OR `key_metrics` | `beta` | ✅ |
| Dividend Yield | fmp_cached | `key_metrics` | `dividend_yield_ttm` | ✅ |
| "—" disclaimer when non-paying | UI | check `dividend_yield_ttm is None OR 0` | | ✅ |
| Volume (today) | fmp_cached | `equity_quote` | `volume` | ✅ |
| 30-day avg volume | 🧮 | derived: `mean(equity_historical.volume[-30:])` | | 🧮 |

### 2B. Upcoming Earnings Milestone

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Countdown "In X days" | 🧮 | derived from `calendar_earnings.date - today()` | | 🧮 |
| Reporting date | fmp_cached | `calendar_earnings` (filter by symbol) | `date` | ✅ |
| Period (e.g. "Q2 2026") | fmp_cached | `calendar_earnings` | `period`, `fiscal_year` | ✅ |
| EPS estimate | fmp_cached | `calendar_earnings` OR `forward_eps_estimates` | `eps_estimated` | ✅ |
| Revenue estimate | fmp_cached | `calendar_earnings` OR `forward_ebitda_estimates` | `revenue_estimated` | ✅ |

### 2C. Employee Efficiency (FY)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Headcount | fmp_cached | `historical_employees` | `employee_count` | ✅ |
| Headcount YoY Δ | 🧮 | derived: `latest - prior_year` | | 🧮 |
| Revenue / Employee 1Y | 🧮 | derived: `income_statement.revenue / historical_employees.employee_count` | | 🧮 |
| Net Income / Employee 1Y | 🧮 | derived: `income_statement.net_income / historical_employees.employee_count` | | 🧮 |

**Section 2 verdict: 100% covered.** All non-derived fields come from `fmp_cached`.

---

## Section 3 — Financial Statement Charts

### 3A. Performance & Margins (5-yr Revenue / Net Income / Net Margin %)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Revenue (annual, 5-yr) | fmp_cached | `income_statement` | `revenue` × 5 rows | ✅ |
| Net Income (annual, 5-yr) | fmp_cached | `income_statement` | `net_income` × 5 rows | ✅ |
| Net Margin % (5-yr) | 🧮 | derived: `net_income / revenue` per year | | 🧮 |

### 3B. Revenue → Profit Funnel

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Total Revenue | fmp_cached | `income_statement` | `revenue` | ✅ |
| COGS | fmp_cached | `income_statement` | `cost_of_revenue` | ✅ |
| Gross Profit | fmp_cached | `income_statement` | `gross_profit` | ✅ |
| Expenses & Adjustments | 🧮 | derived: `gross_profit - net_income` (aggregates OPEX + tax + interest) | | 🧮 |
| Net Income | fmp_cached | `income_statement` | `net_income` | ✅ |

### 3C. Debt Level & Coverage (5-yr)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Total Debt (5-yr) | fmp_cached | `balance_sheet` | `total_debt` × 5 rows | ✅ |
| Free Cash Flow (5-yr) | fmp_cached | `cash_flow` | `free_cash_flow` × 5 rows | ✅ |
| Cash & Equivalents (5-yr) | fmp_cached | `balance_sheet` | `cash_and_cash_equivalents` × 5 rows | ✅ |

**Section 3 verdict: 100% covered.** All from `fmp_cached` income + balance + cash-flow.

---

## Section 4 — Technical Analysis, Pivots & Option Volatility

### 4A. Consensus Speedometer (Strong Sell / Sell / Neutral / Buy / Strong Buy)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Rating buckets (5) | fmp_cached | `price_target_consensus` OR `analyst_estimates` | `strong_buy`, `buy`, `hold`, `sell`, `strong_sell` | ✅ |

*Note:* Historically some providers only give a single mean rating (`1.0` – `5.0`); if so, bucket-splitting happens at the widget layer.

### 4B. ATM IV Term Structure (1W / 2W / 1M / 2M / 3M / 6M / 9M / 1Y)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| ATM IV per expiry | ❌ | **GAP** — no options-chain / IV endpoint in `fmp_cached` or `fmp` | | ❌ |

**GAP:** IV term structure has no coverage today. Options data (chain, greeks, IV surface) is not in the current provider set. **Action:** file `provider-gap` issue for options chain (candidates: `cboe`, `intrinio`, `tradier`) — probably a separate program.

### 4C. Pivot Point Matrix (Classic / Fibonacci / Camarilla / Woodie / DM × 7 levels)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| High / Low / Close (yesterday) | fmp_cached | `equity_historical` | `high`, `low`, `close` (previous session) | ✅ |
| Pivots (5 formulations × 7 levels) | 🧮 | **derived at widget layer** — coordinate with #780 (TV 31-indicator coverage: pivot calculators live under `openbb_technical` / `openbb_techtrade`; do NOT duplicate) | | 🧮 |

**Section 4 verdict:** partial — pivots + consensus OK. **IV term structure is a hard gap** requiring options data.

---

## Section 5 — Analyst Forecasts & Surprise Engine

### 5A. 1-Year Price Target Model

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Consensus target | fmp_cached | `price_target_consensus` | `target_consensus` | ✅ |
| Upside/downside vs current | 🧮 | derived: `(target - last_price) / last_price` | | 🧮 |
| Sample size | fmp_cached | `price_target_consensus` | `number_of_analysts` OR `analyst_estimates.number_analysts_estimated_revenue` | ✅ |
| Max / Min target range | fmp_cached | `price_target_consensus` | `target_high`, `target_low` | ✅ |

### 5B. Rating Distribution Gauge (past 3 mo)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Strong Buy / Buy / Hold / Sell / Strong Sell counts | fmp_cached | `price_target` (filter by symbol, date >= today-90d) then aggregate `new_grade` counts, OR `analyst_estimates` if it carries the split | derived aggregate | 🟡 |

**Sub-gap:** confirm whether `price_target` model carries `new_grade` per-analyst or only a numeric target. If only numeric, then rating-split has to come from `fmp` (`analyst-stock-recommendations` endpoint) — file `area:fmp-cached-gap` sub-issue.

### 5C. Historical EPS & Revenue Surprise

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Reported EPS per quarter | fmp_cached | `historical_eps` | `eps_actual` | ✅ |
| Estimated EPS per quarter | fmp_cached | `historical_eps` | `eps_estimated` | ✅ |
| EPS surprise % | 🧮 | derived: `(actual - estimated) / estimated` | | 🧮 |
| Reported Revenue per quarter | fmp_cached | `income_statement` (quarterly) | `revenue` | ✅ |
| Estimated Revenue per quarter | 🟡 | `analyst_estimates` gives forward estimates; need to snapshot pre-earnings estimates historically — verify whether `analyst_estimates` returns historical estimates by fiscal quarter | | 🟡 |
| Revenue surprise % | 🧮 | derived | | 🧮 |

**Section 5 verdict:** covered with two known sub-gaps to verify (rating-split, historical revenue estimate snapshotting). Both will be surfaced as `area:fmp-cached-gap` if `fmp_cached` doesn't carry them.

---

## Section 6 — Complementary Asset Exposure

### 6A. ETF Holdings Exposure (top ETFs holding this ticker)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| ETF Ticker / Name (top-N) | fmp_cached | `etf_equity_exposure` | `etf_symbol`, `etf_name` | ✅ |
| Weight % | fmp_cached | `etf_equity_exposure` | `weight` | ✅ |
| Market Value | 🧮 | derived: `etf.total_aum * weight` where `etf.total_aum` from `etf_info` | | 🧮 |

Also consumer of `EtfHoldings` (#542 shipped) if we want to render the ETF's own top holdings on hover.

### 6B. Highest-Yielding Debt (outstanding corporate bonds)

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Bond issuance list per issuer | ❌ | **GAP** — no corporate-bond endpoint in `fmp_cached` or `fmp` | | ❌ |
| YTM, coupon, maturity, fixed/floating | ❌ | ditto | | ❌ |

**GAP:** corporate bond data is not currently in `fmp_cached` / `fmp`. Candidates: `finra_trace`, `intrinio_bonds`, `bondwave`. **Action:** file `provider-gap` issue; likely deferred to a bond-data program.

---

## Section 7 — Competitor Comparison Strip

| Field | Provider | Endpoint | Model field | Status |
|---|---|---|---|---|
| Competitor tickers (regional industry) | fmp_cached | `equity_peers` | `peers_list` | ✅ |
| Competitor name | fmp_cached | `equity_profile` (batched per peer) | `name` | ✅ |
| Competitor live price | fmp_cached | `equity_quote` (batched per peer) | `last_price` | ✅ |
| % Δ | fmp_cached | `equity_quote` | `change_percent` | ✅ |

**Section 7 verdict: 100% covered.**

---

## Summary — Coverage Verdict by Section

| Section | Covered | Derived | Sub-gap (fmp_cached) | Hard Gap |
|---|---|---|---|---|
| 1 Header & Ticker | 11 | 2 | 0 | 0 |
| 2 Key Stats | 14 | 4 | 0 | 0 |
| 3 Financial Charts | 10 | 3 | 0 | 0 |
| 4 Technical / Pivots / IV | 3 | 2 | 0 | **1 (IV term structure)** |
| 5 Analyst Forecasts | 8 | 4 | 2 (rating split, historical rev estimate) | 0 |
| 6 Complementary Assets | 3 | 1 | 0 | **1 (corporate bonds)** |
| 7 Competitor Strip | 4 | 0 | 0 | 0 |

**Aggregate:** 53 direct-covered fields, 16 derived, 2 `area:fmp-cached-gap` items to verify, 2 hard provider gaps (options IV; corporate bonds).

---

## Follow-up issues to file

1. **7 per-section implementation issues** (children of #781):
   - #781.1 Section 1 — Header & multi-feed price ticker
   - #781.2 Section 2 — Key stats grid
   - #781.3 Section 3 — Financial statement charts (3 modules)
   - #781.4 Section 4 — Technicals + pivots + IV (IV blocked on §4-IV gap)
   - #781.5 Section 5 — Analyst forecasts + surprise engine
   - #781.6 Section 6 — ETF exposure + bond ladder (bonds blocked on §6-bond gap)
   - #781.7 Section 7 — Competitor comparison strip

2. **Provider-gap issues** (external programs):
   - Options chain + ATM IV term structure (§4B) — file with `area:provider-gap`
   - Corporate bond issuance + YTM (§6B) — file with `area:provider-gap`

3. **fmp_cached sub-gaps** (cross-team; per CLAUDE.md do not PR into `providers/fmp_cached/`):
   - Rating-split per analyst (§5B) — file with `area:fmp-cached-gap`
   - Historical revenue estimate snapshotting (§5C) — file with `area:fmp-cached-gap`

## Coordination notes

- **§4 pivot calculators** — DO NOT duplicate. Consume from `openbb_technical` / `openbb_techtrade` per #780.
- **§6 ETF exposure** — consume `EtfHoldings` model (#542 shipped) directly; no new provider integration.
- **All widget rendering** blocked until #981 (widget host), #982 (widget SDK), #983 (frontend CI) land.
