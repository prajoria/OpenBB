# Analyst-Recommendations Basket Notebook (Spec)

**Date:** 2026-07-26
**Owner:** Claude (autonomous cycle per user directive)
**Deliverable:** ONE notebook at `notebooks/portfolio/08-analyst-recommendations-basket.ipynb`, filled + executed + kernel-restart-clean, that (a) constructs a diversified all-sector ETF basket following the discipline used by well-known institutional PMs (Dalio all-weather, Bogleheads three-fund, Fidelity sector rotation), and (b) runs the full seven-phase Analysis + `portfolio_intel` stack on that basket to demonstrate the same review Sam would do on their own book.

The notebook is a SINGLE file — not a series expansion. It reads standalone but pulls in the same tools NB03-NB06 exercised.

---

## Why a "recommendations basket" notebook

The 7-notebook series already teaches how to analyze a basket. What it does NOT teach is **how to construct one from scratch** using published discipline. Software developers who land here typically ask two questions after finishing NB07:

1. "The 10-position through-line basket is synthetic — what would a real, defensible basket look like?"
2. "Which sources do actual traders use? Where do I go for signal beyond fmp_cached?"

This notebook answers both, in one file, with the same Sam-voice + Investopedia-linked teaching depth Phase C shipped.

**Not a stock-picking recommendation.** The notebook is an educational demonstration of *portfolio construction discipline*, using ETFs (broad, transparent, low-cost). Everything is time-stamped, cited, and marked as "illustrative" — reader is expected to run their own diligence before allocating capital.

---

## Sources this notebook cites

Every source below is used to explain *how* the basket is put together, not to make forward-looking predictions.

### Portfolio construction frameworks (methodology)

| Source | What we take from it | URL |
|---|---|---|
| Ray Dalio — "All Weather" portfolio (Bridgewater) | Risk parity across four macro regimes (growth up/down × inflation up/down); target allocation: 30% stocks / 40% long bonds / 15% intermediate bonds / 7.5% gold / 7.5% commodities | https://www.bridgewater.com/research-library |
| Bogleheads — three-fund portfolio (John Bogle) | Total US market + total international + total bond, low-cost, rebalance annually | https://www.bogleheads.org/wiki/Three-fund_portfolio |
| Fidelity — sector rotation framework | 11 GICS sectors, rotate exposure with the business cycle (early / mid / late / recession) | https://www.fidelity.com/learning-center/investment-products/mutual-funds/sector-rotation-strategy |
| Vanguard — target-date glide path | Age-weighted equity/bond mix; used here as the "starting point" for a 40-year-old investor | https://investor.vanguard.com/investment-products/list/target-retirement |
| Meb Faber — "The Ivy Portfolio" (Cambria) | Equal-weight across 5 asset classes (US equity / foreign equity / bonds / real estate / commodities) with a 10-month moving-average trend filter | https://mebfaber.com/ |

### Analyst / signal aggregation sites (research destinations)

Cited for reader follow-up; the notebook does NOT scrape these — that's future work.

| Site | What it aggregates | URL |
|---|---|---|
| TipRanks | Aggregated analyst price targets + insider/hedge-fund sentiment scores | https://www.tipranks.com/ |
| Zacks Investment Research | Zacks Rank (1-5) based on earnings-estimate revisions | https://www.zacks.com/ |
| Morningstar | Star ratings + fair-value estimates + moat analysis | https://www.morningstar.com/ |
| Seeking Alpha | Crowd-sourced analyst articles + Quant Ratings | https://seekingalpha.com/ |
| ETF.com | ETF-specific analyst reports, expense-ratio comparisons | https://www.etf.com/ |
| SEC EDGAR — 13F filings | Quarterly institutional holdings (Bridgewater, Renaissance, Berkshire, ARK...) | https://www.sec.gov/edgar/searchedgar/companysearch |

### Data providers (what the notebook actually calls)

- **fmp_cached** (primary) — quote, historical, key-metrics, ratios, financial scores.
- **fmp** (fallback per CLAUDE.md `area:fmp-cached-gap` rule) — only for endpoints not in the cache.
- **yfinance recorded snapshots** — ETF holdings look-through where fmp_cached lacks coverage. Never live under automation (per user rule).

### The Fortress CSV reference

The user referenced "Fortress CSV" as a construction hint. I don't have a file on disk under that name in `H:\masterswork\browser_exports\`, so I treat "Fortress" as a shorthand for *institutional-quality construction* — full-cycle diversified, all-sector, risk-managed. If a specific Fortress asset-management PDF or CSV exists that Daisy wants echoed, the notebook has a clearly-marked "swap your Fortress reference here" section (a one-line JSON edit).

---

## The recommendations basket — 15 ETFs

Composition follows the Dalio + Faber + Fidelity synthesis. Each row cites which framework contributes it.

### Broad market spine (55%)

| Ticker | Name | Weight | Sector role | Framework citation |
|---|---|---:|---|---|
| VTI | Vanguard Total US Stock Market | 30% | US equity broad | Bogleheads three-fund |
| VXUS | Vanguard Total International | 15% | Ex-US developed + EM | Bogleheads three-fund |
| VNQ | Vanguard Real Estate | 5% | REITs | Faber Ivy |
| GLD | SPDR Gold Trust | 5% | Inflation hedge | Dalio all-weather |

### Fixed-income ballast (25%)

| Ticker | Name | Weight | Sector role | Framework citation |
|---|---|---:|---|---|
| BND | Vanguard Total Bond | 15% | Investment-grade agg | Bogleheads three-fund |
| TLT | iShares 20+ Year Treasury | 5% | Long-duration hedge | Dalio all-weather |
| SHY | iShares 1-3 Year Treasury | 3% | Short-duration liquidity | Dalio all-weather |
| TIP | iShares TIPS | 2% | Real-rate hedge | Dalio all-weather |

### Sector satellites (20%)

Chosen to cover the 11 GICS sectors that VTI is heavy in growth/tech but light in defensives (Fidelity sector rotation logic — overweight sectors that VTI structurally under-represents at the current cycle stage).

| Ticker | Name | Weight | GICS sector | Framework citation |
|---|---|---:|---|---|
| XLE | Energy Select Sector | 3% | Energy | Fidelity rotation (late-cycle inflation hedge) |
| XLF | Financials Select Sector | 3% | Financials | Fidelity rotation (rate-normalization play) |
| XLV | Health Care Select Sector | 3% | Health care | Defensive, secular demographics |
| XLU | Utilities Select Sector | 2% | Utilities | Defensive yield |
| XLB | Materials Select Sector | 2% | Materials | Cyclical + inflation-sensitive |
| XLI | Industrials Select Sector | 2% | Industrials | Cyclical, reshoring theme |
| DBC | Invesco DB Commodity | 3% | Broad commodities | Dalio all-weather + Faber Ivy |
| VWO | Vanguard Emerging Markets | 2% | EM equity | Faber Ivy diversifier |

**Total: 100%**

Design principle: the 15-position basket is small enough to reason about and rebalance monthly, but wide enough to survive a look-through pass (§3 will show it decomposes into ~2,500 underlying stocks and 8+ sovereign / IG bond issuers).

---

## Notebook structure — one file, 12 sections

Same Sam-voice + Investopedia glossary boxes + Rule-#10 discipline as NB01-NB07.

| § | Section | Kind | Depth |
|---|---|---|---|
| 0 | Preamble + venv sanity | code | short |
| 1 | Why this notebook + reader contract | md | primer |
| 2 | Portfolio construction — the 5 frameworks | md | primer with 5 Investopedia links |
| 3 | Trader/analyst sources — where the pros look | md | primer with 6 aggregator citations |
| 4 | The 15-ETF basket — table + rationale | md + code (writes `.notebook_state/analyst_basket.json`) | primer |
| 5 | Basket X-Ray (look-through) — sector, HHI, effective-N | code (calls NB03 machinery) | uses portfolio_intel.xray |
| 6 | Risk metrics — Sharpe / vol / MaxDD / tracking-error vs SPY | code | uses portfolio_intel.risk |
| 7 | Single-name spot-check — run the Analysis 7-phase on the largest holding (VTI's top constituent) | code | uses Analysis pipeline |
| 8 | Backtest — buy-and-hold vs monthly-rebalance to target weights on 2023-2024 | code | uses openbb_backtest |
| 9 | Sensitivity — what if the reader swaps in their Fortress reference? | md + code | one-line JSON edit demo |
| 10 | Where I'd go from here (analyst sources + rebalance cadence) | md | education |
| 11 | What is NOT in this notebook | md | honesty |
| 12 | 📚 Further reading | md | citations |

Total: ~10 code cells + ~10 markdown cells (5 primers + 4 sections + Further Reading appendix).

**Investopedia coverage target:** ≥15 unique links, respecting the series first-occurrence rule (skip links already used in NB01-NB07; bare-term pointers otherwise).

**New concepts introduced (not in NB01-NB07):**
- Risk parity
- All-weather / all-seasons portfolio
- Three-fund portfolio
- Sector rotation (business-cycle framing beyond the sentence in NB02)
- Target-date glide path
- 13F filing (deep — NB04 introduced; this notebook cites SEC EDGAR search flow)
- Trend-following overlay (Faber 10-month MA)

---

## Data / API-shape notes

- **Look-through** — same in-notebook pattern NB03 uses (`YFinanceEtfHoldingsRecordedFetcher.fetch_from_snapshot`). All 15 ETFs need snapshots on disk; the notebook checks and prints a `scrape-record record yahoo_etf_holdings --symbol TLT` instruction for any that are missing (graceful degradation).
- **Backtest** — `buy_and_hold` on the 15-ETF universe over 2023-01-03 → 2024-12-31 is the primary run; a monthly-rebalance-to-target-weights secondary run compares.
- **Single-name spot-check** — call `run_full_analysis(AnalysisConfig(symbol="MSFT"))` for the reader-visible chapter (MSFT is a large VTI constituent, already fixture-locked in NB02).

## Deliverables

- `docs/superpowers/specs/2026-07-26-analyst-recommendations-basket-spec.md` — this file.
- `notebooks/portfolio/08-analyst-recommendations-basket.ipynb` — the notebook itself.
- `notebooks/portfolio/README.md` — one-line addition pointing readers to NB08 as an optional standalone chapter (not part of the main NB01→NB07 reading order).

## Verification

- `pytest openbb_platform/tests/test_notebooks_portfolio_smoke.py` still 36+7=43 tests? — NO: smoke test is parametrized by `EXPECTED_NOTEBOOKS` list; adding NB08 grows to 42 tests (7 → 8 notebooks × 6 smoke families). The `EXPECTED_NOTEBOOKS` list gets updated in the same PR.
- Kernel-restart + Run All in `.venv_portfolio` — zero exceptions, zero red cells.
- `python scripts/reset_notebooks_for_checkin.py --check notebooks/portfolio/08-*.ipynb` — clean.
- No PII in shipped output (no real Fortress account balances, no operator paths).

## Non-goals

- Not a stock-picking service. No forward return targets. No "buy this."
- No live scraping of TipRanks / Zacks / Morningstar / Seeking Alpha — those are cited as reader destinations, not data sources.
- No Bridgewater / Renaissance 13F import — the notebook cites SEC EDGAR as the reader's destination, not an automated pull.
- No rebalancing execution — that's paper-trading territory (NB05) and beyond.

## Rules honored

- Sam-voice preserved throughout — first-person, concrete, no marketing tone.
- Every finance term linked to Investopedia on first-in-series occurrence (else bare-term pointer with "(see NB##)").
- Emoji restraint: 📖 (glossary) and 📚 (further reading) only.
- No PII / operator paths in cell outputs.
- Notebook stripped before commit per CLAUDE.md check-in hygiene rule.
