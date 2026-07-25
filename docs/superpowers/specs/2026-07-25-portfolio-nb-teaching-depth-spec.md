# Portfolio Notebook Series — Teaching-Depth Enhancement (Spec)

**Date:** 2026-07-25
**Scope:** `notebooks/portfolio/*.ipynb` (7 notebooks: NB01-NB07)
**Reference model:** `notebooks/01-foundations-techtrade-and-analysis.ipynb`
**Author:** Claude (autonomous cycle per user directive)

---

## Why

The 7-notebook Portfolio Intelligence Engine user guide (`notebooks/portfolio/`)
ships correct, kernel-restart-clean code but **teaches only the code path**.
It documents *what the platform does*; it does not teach *why a trader would
care* or *what the underlying finance concept means*.

Contrast with the reference `notebooks/01-foundations-techtrade-and-analysis.ipynb`:

| Metric | Reference NB01 | Portfolio NB01 | Portfolio NB07 (best) |
|---|---:|---:|---:|
| Markdown cells | 30 | 8 | 12 |
| Markdown chars | ~24,000 | 7,569 | 10,522 |
| Investopedia hyperlinks | 76 | 0 | 0 |
| "Jargon" / "Glossary" / "Primer" boxes | 82 | 0 | 0 |
| Callout boxes (`> …` blockquote teaching) | ~40 | 0 | 0 |

**Target audience:** software developers who use these notebooks to learn
trading + portfolio management simultaneously. Every finance term must be
either (a) linked to Investopedia, or (b) inlined as a short definition
box the first time it appears. No term appears twice without a link. A
reader with zero finance background should finish NB07 with a working
mental model of: sector concentration, look-through, HHI, effective-N,
Sharpe, MaxDD, drawdown recovery, position sizing, walk-forward, PBO,
Brinson attribution, and paper trading.

## What this spec is NOT

- Not a code change. All existing code cells keep their outputs and their
  execution semantics unchanged. This is a markdown-only enhancement.
- Not a rewrite of the narrative voice. Sam-voice (first-person,
  concrete) is preserved; teaching content is layered *inside* Sam's
  reflections ("I didn't know what a Sharpe ratio was — here's what
  Investopedia said, and here's what mine turned out to be").
- Not a scope expansion beyond `notebooks/portfolio/`. The reference
  `notebooks/01-06` (techtrade lane) already meets the bar and is
  outside this cycle.

---

## Content model — what each teaching cell looks like

Three cell types get added / expanded, all markdown:

### Type A: Glossary callout box (short, per term)

```markdown
> **📖 Sharpe ratio** — annualized return per unit of volatility;
> anything above 1.0 is "decent" for a long-only equity portfolio;
> above 2.0 warrants suspicion (you're probably data-mining or ignoring
> a fat-tail risk). [Investopedia →](https://www.investopedia.com/terms/s/sharperatio.asp)
```

Placed **immediately before** the code cell that produces the term. One
callout per new concept, per notebook. If NB03 introduces "HHI" and NB05
uses it again, NB05 says "HHI (see NB03)" — no duplication.

### Type B: Concept primer (mid-length, per section)

A ~300-word markdown block that opens each major section, explaining
**why this concept matters to a portfolio manager** (not just what the
code does). Structure:

1. The trader's problem in plain English ("You own 10 stocks. How
   concentrated are you really?").
2. The finance concept the platform uses to answer it, with an
   Investopedia link on first mention.
3. What "healthy" vs "unhealthy" numbers look like, with 2-3 rules of
   thumb.
4. What the platform's specific approach adds beyond textbook.

### Type C: "Read more" appendix (per notebook, end-of-file)

A final markdown cell titled **`## 📚 Further reading`** listing every
Investopedia link cited in the notebook, plus 3-5 canonical papers/blog
posts (e.g. Bailey & Lopez de Prado on PBO for NB06). Format:

```markdown
- **Sharpe ratio** — https://www.investopedia.com/terms/s/sharperatio.asp
- **Herfindahl-Hirschman Index (HHI)** — https://www.investopedia.com/terms/h/hhi.asp
- **Bailey & Lopez de Prado (2014), *"The Probability of Backtest Overfitting"*** — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
```

---

## Per-notebook coverage target

| # | Notebook | Concepts to teach | Investopedia links (target) |
|---|---|---|---:|
| 01 | Getting Started + Providers | provider, fetcher, endpoint, quote, OHLCV, ETF, adjusted close, split, dividend, market cap | 10+ |
| 02 | Single-Name Deep Dive | fundamental analysis, DCF, owner earnings, EV, EV/EBITDA, ROIC, financial health scores, ATR, price-target consensus, regime, sector rotation, composite score | 15+ |
| 03 | Basket X-Ray + Risk | portfolio, position, weight, sector concentration, look-through, HHI, effective-N, Sharpe, volatility (annualized), max drawdown, tracking error, benchmark, correlation | 12+ |
| 04 | Events + Smart Money | earnings, dividend, ex-date, stock split, 13F filing, insider transaction, cluster buy, congressional trades (STOCK Act), news sentiment, event-driven trading | 10+ |
| 05 | What-If + Attribution + Paper | position sizing, trade rationale, Brinson-Fachler attribution, allocation effect, selection effect, interaction effect, paper trading, market order, GTC/DAY time-in-force, buying power, low-BP alert | 12+ |
| 06 | Backtest + Validation | backtest, equity curve, drawdown, rebalance, look-ahead bias, walk-forward analysis, PBO (probability of backtest overfitting), Deflated Sharpe Ratio, factor investing, quantile portfolio, alpha, beta, information ratio | 15+ |
| 07 | Offline Recording + End-to-End | snapshot, cassette, reproducibility, portfolio review cadence, execution plan, market microstructure (very light) | 8+ |

**Total series target:** ~80+ Investopedia links across 7 notebooks, plus
~30 concept-primer blocks and ~20 further-reading references.

---

## Voice + style rules

- **Preserve Sam-voice.** Teaching content lives INSIDE Sam's reflections
  ("I didn't know what HHI was either — turns out …"). It never becomes
  a lecture.
- **First occurrence rule.** Every finance term gets a glossary box or
  inline link the first time it appears in the series. Second+
  appearance: bare term, no link, no repetition.
- **No emojis in narrative text.** The 📖 / 📚 icons are the *only*
  allowed emoji, used as visual anchors for glossary boxes and
  further-reading sections. This matches CLAUDE.md file-hygiene rule.
- **Investopedia is the default source.** When Investopedia doesn't
  have a good page (rare — e.g. PBO), use the canonical academic paper
  or a well-known finance blog (SSRN, Quantpedia).
- **Rules-of-thumb come from cited sources.** Never invent a "Sharpe
  above 1.0 = good" threshold without linking to who says so.
- **Update `STORY_BIBLE.md`** to add a "§10 Teaching contract" section
  that codifies these rules so future notebook authors follow them.

---

## Structural changes to `README.md`

Add a new section right after the "Suggested reading order" table:

```markdown
### 📚 Learning path (for developers new to trading)

If you have never taken a finance class, read the notebooks with these
Investopedia primers open in a second tab. Each notebook's `📚 Further
reading` appendix lists all links cited in that notebook.

- **Before NB01:** [What is a stock?](https://www.investopedia.com/terms/s/stock.asp) · [What is an ETF?](https://www.investopedia.com/terms/e/etf.asp) · [OHLCV](https://www.investopedia.com/terms/o/ohlcchart.asp)
- **Before NB02:** [Fundamental analysis](https://www.investopedia.com/terms/f/fundamentalanalysis.asp) · [DCF valuation](https://www.investopedia.com/terms/d/dcf.asp) · [Owner earnings](https://www.investopedia.com/terms/o/ownersearnings.asp)
- **Before NB03:** [Portfolio diversification](https://www.investopedia.com/terms/d/diversification.asp) · [HHI](https://www.investopedia.com/terms/h/hhi.asp) · [Sharpe ratio](https://www.investopedia.com/terms/s/sharperatio.asp)
- **Before NB04:** [SEC 13F filings](https://www.investopedia.com/terms/1/13f.asp) · [Insider trading](https://www.investopedia.com/terms/i/insidertrading.asp) · [STOCK Act](https://www.investopedia.com/terms/s/stock-act.asp)
- **Before NB05:** [Brinson attribution](https://www.investopedia.com/terms/p/performance-attribution.asp) · [Paper trading](https://www.investopedia.com/terms/p/papertrade.asp)
- **Before NB06:** [Backtesting](https://www.investopedia.com/terms/b/backtesting.asp) · [Walk-forward analysis](https://www.investopedia.com/terms/w/walkforward-optimization.asp) · [Overfitting](https://www.investopedia.com/terms/o/overfitting.asp)
- **Before NB07:** [Portfolio review cadence](https://www.investopedia.com/articles/investing/122714/how-often-should-you-review-your-portfolio.asp)
```

---

## Implementation plan

Break into **7 sub-issues (one per notebook)**, each landing as a
separate PR against `portfolio`. All 7 sub-issues attached to a new
parent epic under Project #4. This mirrors the shape that worked for
Phase B code fulfillment (7 code-fulfillment PRs, one per NB).

### Sequence + estimated effort per notebook

Given each notebook already has correct code + outputs, the work is
**purely markdown insertion**. Estimated 20-30 minutes per notebook
for a well-prepared author. Cluster in three PR batches so review
stays tractable:

- **PR 1 — NB01 + NB02** (foundations + deep dive)
- **PR 2 — NB03 + NB04 + NB05** (portfolio-level chapters)
- **PR 3 — NB06 + NB07** (validation + capstone)

Each PR also updates `STORY_BIBLE.md` (§10) and `README.md` (learning
path) if it hasn't been updated yet. First PR does both docs; later PRs
just cite them.

### Verification per PR

1. Every existing code cell + output preserved byte-for-byte (only
   markdown added / edited). Verify with `nbformat` diff.
2. Kernel-restart + Run All still clean (no error cells). This is
   defense against accidental cell reordering.
3. `openbb_platform/tests/test_notebooks_portfolio_smoke.py` passes.
4. Grep count: `grep -c investopedia.com <nb>` matches the per-notebook
   target from the coverage table above.
5. Grep count: no repeated Investopedia link across the same notebook
   (first-occurrence rule).

### What this PR delivers vs what stays pending

**Delivers:** NB01-NB07 teaching-depth enhancement + `STORY_BIBLE.md`
§10 teaching contract + `README.md` learning path.

**Does NOT deliver:** interactive quizzes, embedded YouTube videos,
downloadable cheat-sheets, or fork-external content (Coursera, Khan
Academy). Those are separate work.

---

## Success criteria

- A developer with zero finance background can complete NB01 → NB07 in
  a weekend and, without opening any resource beyond the linked
  Investopedia pages, explain **all** of: Sharpe ratio, HHI, look-through,
  drawdown, walk-forward analysis, PBO, Brinson attribution, and paper
  trading.
- Every finance term appears at most once as a link (first-occurrence
  rule enforced by review).
- Series `notebooks/portfolio/` cites ≥ 80 Investopedia links and ≥ 5
  canonical papers/blog posts total.
- `STORY_BIBLE.md` §10 codifies the teaching contract so future authors
  don't have to re-derive these rules.
