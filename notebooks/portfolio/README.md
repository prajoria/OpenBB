# Portfolio Intelligence Engine — User Guide

> A seven-notebook journey through the portfolio-engine surface of the
> OpenBB fork. Told through the eyes of one retail trader (Sam) working
> through a real basket, one Sunday at a time.

## Who this is for

You write Python at work or on the side. You have a small self-directed
brokerage account. You've been placing trades on hunches, or on
takes you read online, and you're not sure whether your process is
actually a process or just a habit. You suspect there is a better way
but every guide you've opened has either been (a) a math textbook
pretending to be a tutorial, or (b) a shill for a paid service.

This is neither.

Everything in these seven notebooks runs on the free tier of the
providers we ship with, plus a set of checked-in offline snapshots
for endpoints where free live coverage is unreliable (Yahoo Finance
quote/info/etf-holdings/options/bond-holdings). No paid
subscription, no API key hunt. If a cell requires internet, it
degrades to a canned fallback and prints a note.

## Sam

We follow one learner throughout. Sam is 34, a backend engineer, 14
months into retail trading, up 4% while SPY is up 22% over the same
window. Sam believes concentration risk is for institutions and that
backtests always lie. By the end of NB07, Sam believes neither of
those things.

Sam's account size is deliberately never quoted — no anchoring to
someone else's number. Sam's basket, however, is fully public and
locked, because every discovery in the series depends on the specific
shape of what Sam owns.

## The basket

The through-line, referenced from every notebook:

| Ticker | Weight | Why it's here |
|--------|--------|---------------|
| MSFT | 12% | The single-name deep-dive subject (NB02) |
| NVDA | 10% | Semiconductor cluster — feeds NB03's overlap surprise |
| GOOGL | 8% | Mega-cap tech |
| AAPL | 8% | Mega-cap tech |
| AMD | 6% | Semi-cluster peer |
| QQQ | 15% | ETF whose top holdings ARE the tickers above |
| VTI | 20% | Broad-market ETF, still ~30% tech under the hood |
| VNQ | 8% | REIT ETF — supplies a distinct sector |
| BND | 10% | The `BondLadder` fetcher's demo target (NB01 + NB07) |
| GLD | 3% | Tail-hedge tilt — Sam learns it's too small to matter |

Weights are round-number synthetic. This is not anyone's real portfolio.

## Reading order

Do them in order the first time. Later, any notebook is runnable
standalone — each one has a fallback that regenerates any state it
needs from the prior notebooks.

| # | File | Runtime | What Sam discovers |
|---|------|---------|--------------------|
| 01 | `01-getting-started-and-providers.ipynb` | ~5 min | The system exists, has a stable vocabulary, works without paid keys |
| 02 | `02-single-name-deep-dive.ipynb` | ~8 min | There are 7 questions about a stock, not 1 |
| 03 | `03-basket-xray-and-risk.ipynb` | ~4 min | The pivot chapter: "I own 10, actually 47" |
| 04 | `04-events-and-smart-money.ipynb` | ~5 min | Who else is trading these names, and what hits the calendar this week |
| 05 | `05-whatif-attribution-and-paper.ipynb` | ~5 min | The intuitive trade would make things worse; paper-trade the revised plan |
| 06 | `06-backtest-and-validation.ipynb` | ~15 min | The base run looked great; the sweep + PBO said "you got lucky" |
| 07 | `07-offline-recording-and-end-to-end.ipynb` | ~10 min | Monday-morning routine, reproducible from disk, works on a plane |

### 📚 Learning path (for developers new to trading)

If you have never taken a finance class, read the notebooks with these
Investopedia primers open in a second tab. Each notebook's `📚 Further
reading` appendix lists every link cited in that notebook; the bullets
below are the *pre-reading* — the minimum vocabulary each notebook
assumes you already have.

- **Before NB01:** [What is a stock?](https://www.investopedia.com/terms/s/stock.asp) · [What is an ETF?](https://www.investopedia.com/terms/e/etf.asp) · [OHLCV chart](https://www.investopedia.com/terms/o/ohlcchart.asp)
- **Before NB02:** [Fundamental analysis](https://www.investopedia.com/terms/f/fundamentalanalysis.asp) · [DCF valuation](https://www.investopedia.com/terms/d/dcf.asp) · [Owner earnings](https://www.investopedia.com/terms/o/ownersearnings.asp)
- **Before NB03:** [Portfolio diversification](https://www.investopedia.com/terms/d/diversification.asp) · [Herfindahl-Hirschman Index (HHI)](https://www.investopedia.com/terms/h/hhi.asp) · [Sharpe ratio](https://www.investopedia.com/terms/s/sharperatio.asp)
- **Before NB04:** [SEC 13F filings](https://www.investopedia.com/terms/1/13f.asp) · [Insider trading](https://www.investopedia.com/terms/i/insidertrading.asp) · [STOCK Act](https://www.investopedia.com/terms/s/stock-act.asp)
- **Before NB05:** [Brinson attribution](https://www.investopedia.com/terms/p/performance-attribution.asp) · [Paper trading](https://www.investopedia.com/terms/p/papertrade.asp)
- **Before NB06:** [Backtesting](https://www.investopedia.com/terms/b/backtesting.asp) · [Walk-forward analysis](https://www.investopedia.com/terms/w/walkforward-optimization.asp) · [Overfitting](https://www.investopedia.com/terms/o/overfitting.asp)
- **Before NB07:** [Portfolio review cadence](https://www.investopedia.com/articles/investing/122714/how-often-should-you-review-your-portfolio.asp)

Duplicates between this list and a notebook's `📚 Further reading` are
intentional — one is a pre-read, the other is a citation index.

## The arc

```
NB01 ─ "the plumbing works"
   │  Q: what does analyzing one name well look like?
NB02 ─ "7 questions per stock, one composite decision"
   │  Q: what do my 10 things look like together?
NB03 ─ "I own 10, actually 47" ◄─── the pivot
   │  Q: who else is trading these RIGHT NOW?
NB04 ─ "signals to trade rationale"
   │  Q: what happens to my book if I make the trade?
NB05 ─ "the intuitive trade makes it worse"
   │  Q: is the strategy any good, or was I lucky?
NB06 ─ "sweep + PBO catches the lucky one"
   │  Q: what if I don't have internet Monday?
NB07 ─ "reproducible from disk, 45 min, works on a plane"
       ╰── the routine
```

## Prerequisites

- Python 3.10-3.13
- `.venv_portfolio` (NOT `.venv_win` — that env belongs to the
  techtrade lane and gets polluted). Setup is in the fork root
  `CLAUDE.md`; the short version is `python -m venv .venv_portfolio`
  followed by `pip install -e` on the six portfolio packages.
- A Jupyter kernel pointing at that venv:
  `python -m ipykernel install --user --name openbb-portfolio`
- **No paid API keys.** `fmp_cached` free tier + `yfinance` + checked-in
  offline snapshots cover every cell.

## What this series is NOT

- Not a rewrite of the techtrade notebooks. `notebooks/01-06` covers
  that lane; this series covers the portfolio engine. They are
  complementary, not overlapping.
- Not a demo of real-time streaming, alternative data, live broker
  adapters, MCP clients, or wash-sale tax accounting. Each of those is
  a legitimate topic but out of scope. NB07 gives pointers.
- Not a promise that following this makes you a good trader. It's a
  promise that following this replaces "hunches" with a repeatable
  process. What you do with the process is on you.

## Provenance

Filed under epic [#1352](https://github.com/prajoria/OpenBB/issues/1352)
on Project #4 (Portfolio Intelligence Engine). Each notebook cites
its shipping PR. Story bible (author reference) at
`STORY_BIBLE.md`.

### Optional standalone chapter — NB08: analyst-recommendations basket

`08-analyst-recommendations-basket.ipynb` (filed under
[#1367](https://github.com/prajoria/OpenBB/issues/1367)) is an
optional companion to the main NB01→NB07 arc. It builds a 15-ETF
all-weather basket from the Dalio / Bogleheads / Faber / Fidelity
frameworks and runs the same review numbers on it. Reads
standalone — no `.notebook_state/` artifact from NB01-NB07 required.
