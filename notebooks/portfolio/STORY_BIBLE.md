# Portfolio Notebook Series — Story Bible

> **Not shipped to readers.** This is the authoring reference for the
> 7-notebook series under `notebooks/portfolio/`. Every notebook author
> reads this before adding a cell. Every reviewer checks a PR against it.
> If a narrative choice contradicts this file, either the notebook needs
> revision or this file does — no drift without an update here first.
>
> Closes: **prajoria/OpenBB#1353** (Phase 0 of epic #1352).

---

## 1. The learner persona

**Name:** Sam Rivera.
**Age:** 34.
**Job:** Backend engineer, writes Python daily.
**Trading tenure:** 14 months of self-directed retail trading; before
that, a decade of "put money in index funds and forget it."
**Account size:** modest — small enough that a bad quarter hurts,
large enough that a good process would compound. (Deliberately no dollar
figures anywhere in the series — no PII, no anchoring the reader to
Sam's number instead of theirs.)
**Portfolio-tracking tool today:** a Google Sheet Sam updates on
Sundays. Cost basis is guessed for two positions Sam kept from an old
broker.

**What Sam believes entering NB01:**
- "I read a lot of Twitter/X finance. I know a lot of names."
- "I'm up 4% while SPY is up 22% over the same window. That has to be
  noise, not skill (or lack of it). If I can just find one better
  setup, I'll catch up."
- "Concentration risk is for institutions. I have 10-12 names; that's
  already diversified."
- "I don't backtest because backtests lie."
- "Options and bonds are for other people."

**What Sam believes leaving NB07:**
- "Alpha is not a good stock pick; it's a repeatable process. I now
  have one."
- "I actually own 47 things through 10 tickers. My 'diversified 12'
  was 41% one sector."
- "The three trades I was about to make this weekend would have made
  my concentration worse, and one of them had negative smart-money
  signal. The what-if showed me before I clicked."
- "My first backtest showed PBO = 0.68. That means the strategy
  probably had zero real edge and I was going to trade it. I now know
  how to spot that in 90 seconds."
- "I can rebuild this whole analysis Monday morning in 45 minutes on
  a plane with no internet. That's the actual product."

**Voice:** first-person, plain, sometimes self-deprecating. Sam is
smart but new; Sam admits when a metric was mysterious the first
time; Sam is honest about the sheet-of-paper calculation Sam used to
do before this. **Never** condescending, never "as any trader knows..."
Every jargon term is defined the first time it appears, in Sam's
words, not a textbook's.

---

## 2. The 7-act arc

Each act opens with the discovery of the previous notebook, then
plants a question the next notebook has to answer. Continuity is
mandatory — a reviewer who reads only the last markdown cell of NB_N
and the first markdown cell of NB_{N+1} should see one continuous
thought.

### Act 1 — NB01: Getting Started + Providers
**Discovery:** the system exists, has a stable vocabulary, and works
without paid keys. The `obb` object gives Sam one entry point to
~160 fetchers and 3 tool CLIs, none of which Sam knew about.
**Closing question:** *"OK, the plumbing works. Before I look at my
whole portfolio, what does 'analyzing one name well' even look like?
Show me MSFT end-to-end."*

### Act 2 — NB02: Single-Name Deep Dive
**Discovery:** there are 7 questions about a stock, not 1. Sam's
"MSFT is a good company" turns into 7 separately-scored answers
composed into a decision label with a staged entry protocol.
**Closing question:** *"MSFT scored well standalone. But MSFT is 1 of
10 things I hold. What do the 10 look like together?"*

### Act 3 — NB03: Basket X-Ray + Risk — **the pivot chapter**
**Discovery:** the "I own 10, actually 47" moment. Sam's "diversified
12" is 41% one sector after look-through. HHI + effective-N + Sharpe
+ MaxDD all land on one page and none of them are what Sam guessed.
**Closing question:** *"Now that I can see what I own — is anyone
with better information doing something in these names RIGHT NOW,
and what's coming up on the calendar that will move them?"*

### Act 4 — NB04: Events + Smart Money
**Discovery:** three of Sam's 10 names have hostile events (earnings
into a bad regime) OR deteriorating smart-money signal in the next
14 days. Sam learns the difference between "one congressperson sold"
and "insider cluster buy + 13F increase + no gov activity."
**Closing question:** *"Three names look wrong. What actually
happens to my portfolio if I trim / rotate / close them?"*

### Act 5 — NB05: What-If + Attribution + Paper
**Discovery:** the what-if diff shows Sam's proposed trades would
*worsen* concentration. Brinson attribution reveals Sam's small
alpha over the last year came from being lucky in one sector, not
from stock picking. Sam paper-trades a revised plan with rationales,
sees a real `Alert` when Sam over-sizes.
**Closing question:** *"The paper trade is on. But was the underlying
strategy any good historically, or did I just get lucky in one
what-if?"*

### Act 6 — NB06: Backtest + Validation
**Discovery:** Sam's toy strategy shows Sharpe 1.4 in the base run,
looks great — then the sweep shows the neighbor parameter cells at
Sharpe 0.2, and PBO = 0.68 (coin flip). The tool told Sam. Sam
would have shipped this. Sam now knows what "probability of backtest
overfitting > 0.5" means and reads a tearsheet in 90 seconds.
**Closing question:** *"Everything so far assumed live data. What if
I don't have internet on Monday morning? How is any of this
reproducible from a git checkout six months from now?"*

### Act 7 — NB07: Offline Recording + End-to-End
**Discovery:** the whole pipeline runs from checked-in snapshots.
Sam's Monday-morning routine end-to-end: 45 minutes, one HTML
report, works on a plane. Sam sees the 14-widget map and understands
that every notebook section maps to a widget-in-progress.
**Closing note:** Sam's before/after — what changed after six weeks
of running this routine.

---

## 3. The through-line basket

**Locked. Do not modify without opening a follow-up issue that cites
the specific "aha" this basket fails to produce.**

Ten positions, chosen deliberately so NB03 lands the "hidden
concentration" moment on real, current data. No dollar sizes — weights
only. Round-number synthetic weights (never a real portfolio).

| Ticker | Weight | Notes for authors |
|--------|--------|-------------------|
| MSFT | 12% | Sam's "flagship pick" — the NB02 deep-dive subject |
| NVDA | 10% | Concentrated tech overlap when combined with QQQ + VTI |
| GOOGL | 8% | Same |
| AAPL | 8% | Same |
| AMD | 6% | Semiconductor sub-cluster — surfaces peer-relative risk |
| QQQ | 15% | 100% overlap with top holdings → x-ray reveals doubling |
| VTI | 20% | Broad market — still ~30% tech under the hood in 2026 |
| VNQ | 8% | REIT ETF — adds a distinct sector for diversification story |
| BND | 10% | The `BondLadder` demo target for NB01 + NB07 |
| GLD | 3% | Tail-hedge tilt — Sam will discover it's too small to matter |

**Guaranteed narrative outcomes on this basket:**
1. NB03: raw sector view says "36% Tech" — after look-through, closer
   to 60% Tech. That is the pivot moment. (Fixture-locked from the
   Phase B fulfillment run: 36.0% → 60.3%, per #1403.)
2. NB03: per-name concentration goes the OTHER direction — HHI drops
   from 0.1206 to 0.0693 and Effective-N rises from 8.3 to 14.4,
   because ETFs decompose into many small sub-positions. Both
   stories are true simultaneously: sector concentration UP,
   per-name concentration DOWN. Sam has to hold both facts at once
   to make the trade call.
3. NB04: at least one of MSFT/NVDA/GOOGL/AAPL/AMD has a live insider
   or 13F signal in any given month. (If none surface on the day
   NB04 runs, the fallback fixture shows a canonical example
   labelled `example — signal shape as of 2026-06-30`.)
4. NB05: proposing "add more NVDA + trim VNQ" (the intuitive trade)
   makes HHI worse and Sharpe delta near-zero. The tool catches Sam.
5. NB06: a naive top-5 owner-earnings rebalance on this basket
   sweep-shows Sharpe collapse and PBO > 0.5. Honest teaching moment.
6. NB07: BND holdings via `YFinanceBondLadderFetcher` (offline snapshot)
   fits naturally into the "reproducible from disk" chapter.

If any of these outcomes fail to reproduce during Phase B code
fulfillment, the response is to open a follow-up sub-issue against
epic #1352, **not** to rewrite the narrative. The narrative is the
product.

---

## 4. Cross-link map

Every "we saw in NB_X that..." reference in the series must resolve.
Both directions matter — a backward reference from NB_N implies a
forward hook in NB_X.

| Source location | Reference | Target |
|-----------------|-----------|--------|
| NB01 §6 (fetchers teased) | "these 20 fetchers reappear in..." | NB02 §fetchers-under-the-hood |
| NB01 §7 (offline snapshots) | "the pattern for record-once-serve-forever..." | NB07 §2-3 (framework deep-dive) |
| NB02 §regime | "regime awareness will also change basket-level risk..." | NB03 §risk-metrics |
| NB02 §handoff-artifact | "staged tranches become paper orders in..." | NB05 §paper-blotter |
| NB03 §look-through | "single-name view of any concentrated holding..." | NB02 (any name) |
| NB03 §silent-failure-guards | "same discipline shows up in the strategy validator..." | NB06 §validation |
| NB04 §smart-money | "signals here become the trade rationale in..." | NB05 §trade-rationales |
| NB04 §events | "hostile events on a name → immediate NB02 re-run" | NB02 |
| NB05 §what-if | "post-trade x-ray should be recomputed..." | NB03 §xray |
| NB05 §what-if | "the strategy the paper trade tests needs..." | NB06 §run |
| NB06 §backtest | "flagged names deserve a fresh single-name check..." | NB02 |
| NB06 §validation | "the PBO discipline mirrors NB03's silent-failure guards..." | NB03 |
| NB07 §monday-routine | back-reference to ALL prior notebooks — reunion chapter | NB01-NB06 (each named) |
| NB07 §widget-map | every widget row → the notebook section that demos its router | NB01-NB06 (per widget) |

**Forward-hook rule:** every backward reference above must have a
matching sentence in the *earlier* notebook that reads roughly *"we
come back to this in NB_N."* This is what turns a set of tutorials
into a single narrative — the reader is always slightly leaning
forward.

---

## 5. Non-goals

The series will NOT cover any of the following. These are legitimate
topics, but they belong to other lanes or later work — trying to fit
them will break the arc and dilute Sam's story.

- **Techtrade lane.** `notebooks/01-06` covers techtrade + Analysis
  end-to-end already. The portfolio series never opens `obb.techtrade`.
- **Real-time streams.** No websockets, no L2 book, no tick data.
  Sam runs this on Monday morning and again on Friday afternoon;
  intraday is out of scope.
- **Live broker adapter.** Paper trading only. NB05 explicitly says
  "when a real broker adapter lands, this is where it plugs in."
- **MCP client-side demos.** `openbb_platform/extensions/mcp_server/`
  exists; how to *drive* the MCP surface from Claude/Cursor/etc. is a
  separate guide. NB07 gets one paragraph pointing at it.
- **Alternative data.** Only free-tier `fmp_cached` + `yfinance` +
  checked-in `scrape_record` snapshots. Anything requiring paid keys
  is called out and skipped.
- **Widget frontend authoring.** NB07 shows the widget map (which
  router serves which widget); how the React frontend renders it is
  in `desktop/` docs, not here.
- **Upstream promotion policy.** Mentioned once in NB07's "where to
  go next"; not walked through.
- **Fund-level compliance / tax reporting / wash-sale accounting.**
  Explicitly out of scope. Sam is a retail trader; these belong in
  their own compliance guide.

If a reviewer sees material creeping into any of the above, cut it
back to a pointer paragraph in NB07 §where-to-go-next.

---

## 6. Voice sample

Every author matches this tone. When in doubt, read it aloud — Sam
sounds like this.

> I ran the x-ray on my "diversified 10" and stared at the
> screen for a while. The raw sector view said 36% Tech, which was
> already more than I thought. Then I clicked the look-through button
> and it turned into 60%. Sixty. Because QQQ is basically MSFT
> and NVDA in a trench coat, and VTI has more MSFT in it than I do
> directly. My "diversified" book was one sector with a hat on.
>
> I've been trading for 14 months. Nobody told me this. It took the
> tool 400 milliseconds to tell me this. That's the moment I stopped
> trusting my sheet.

Rules the sample encodes:
- First person. Present tense for the discovery moment; past tense
  for the setup.
- Concrete numbers when they matter (36%, 60%, 400ms). Never fake
  precision.
- Metaphor OK when it lands ("QQQ is basically MSFT and NVDA in a
  trench coat") — never twice per section, never at the expense of
  the number.
- Self-deprecation is on the SETUP, not the fix. "I've been trading
  for 14 months, nobody told me this" is fine. "Wow the tool is
  amazing" is not.
- No exclamation marks. No emoji. No "let's dive in!"

---

## 7. Editorial rules (mechanical)

1. **`.venv_portfolio` in every cell-1 preamble.** Not `.venv_win`.
2. **No absolute paths in any narrative cell.** Repo-relative only.
3. **No emoji, no headers with icons.** Sam is a text creature.
4. **Every code cell has a one-line comment on top** stating which
   narrative bullet it fulfills. Grep-friendly for the
   Phase-B-fulfillment audit.
5. **"What is NOT shipped" section in every notebook**, before the
   "preview next" section. No dishonest happy endings.
6. **Cross-links use markdown anchors** (`[NB03 §xray](03-basket-xray-and-risk.ipynb#xray)`),
   not "see the other notebook." Every anchor gets defined in the
   target notebook's cell.
7. **Fictional data disclaimers.** Any time a screenshot, table, or
   dollar figure appears, a footnote reads "example — not a real
   portfolio; synthetic weights only."
8. **No PII, ever.** No operator username, no absolute path with a
   home directory, no real screenshot with a real broker window.
9. **Runtime budget stated in each notebook's README section.**
   Sam is a working person; if a notebook takes 45 minutes to run,
   Sam needs to know before starting.
10. **Every promise is kept.** If a narrative cell says "we'll now
    see the hidden concentration," the next code cell must actually
    show it. If the data doesn't cooperate on the day, the fix is a
    fallback fixture (labelled as such) — not weasel words.

---

## 8. Where each thing lives

| Artifact | Path | Ships? |
|---|---|---|
| This bible | `notebooks/portfolio/STORY_BIBLE.md` | No (author reference) |
| Reader README | `notebooks/portfolio/README.md` | Yes |
| Notebooks | `notebooks/portfolio/NN-*.ipynb` | Yes |
| State passed between notebooks | `notebooks/portfolio/.notebook_state/` | Yes (gitignored contents, structure documented) |
| CI smoke tests | `openbb_platform/tests/test_notebooks_portfolio_smoke.py` | Yes |
| Fallback fixtures for degraded-run mode | `notebooks/portfolio/fixtures/` | Yes |

---

## 9. What this bible is NOT

- Not a design doc for `portfolio_intel`, `backtest`, or any router.
- Not a rewrite target — locked once approved. Revisions require a
  new sub-issue against epic #1352 with a rationale.
- Not a checklist the reader ever sees.
- Not an inventory of every feature. Anything not needed for Sam's
  arc stays out, per §5.

---

## 10. Teaching contract (added 2026-07-25)

The reference notebook `notebooks/01-foundations-techtrade-and-analysis.ipynb`
ships 76 Investopedia links across 82 glossary boxes. The portfolio
series is targeting ~80 links across all 7 notebooks. The rules below
codify how those links + glossary boxes get written so future authors
don't have to re-derive them.

### 10.1 First-occurrence rule

Every finance term gets a glossary box (Type A) or inline link the
**first time** it appears in the series — never twice. Second and
later appearances use the bare term. If NB03 introduces HHI and NB05
uses it again, NB05 writes `HHI (see NB03 §2)`, no link, no
re-definition. Enforced at review by grepping each notebook for
`investopedia.com` URLs that are already present in an earlier
notebook.

Exception: each notebook's own `📚 Further reading` appendix
(Type C) re-lists every link cited in that notebook. That is a
reference index, not a re-introduction — allowed. And the reader
README's `📚 Learning path` block deliberately re-uses the URLs
because that is the pre-read.

### 10.2 Callout format (Type A — glossary box)

Blockquote (`>`) prefix so it renders as a visually distinct box in
Jupyter, GitHub, and nbviewer. Anchored by the 📖 emoji, then the
term in bold, then a one-sentence definition, then the Investopedia
link:

```markdown
> **📖 Sharpe ratio** — annualized return per unit of volatility;
> anything above 1.0 is decent for a long-only equity portfolio;
> above 2.0 warrants suspicion. [Investopedia →](https://www.investopedia.com/terms/s/sharperatio.asp)
```

Placed **immediately before** the code cell that first uses the term.

### 10.3 Concept primer (Type B) — 200-300 words per major section

A short primer opens each major numbered section that introduces a
new cluster of concepts. Structure:

1. The trader's problem in plain English.
2. The finance concept the platform uses to answer it, with an
   Investopedia link on first mention.
3. What "healthy" vs "unhealthy" numbers look like, with 2-3 rules
   of thumb — always cited to the source, never invented.
4. What the platform's specific implementation adds beyond textbook.

### 10.4 Voice preservation

Teaching content lives INSIDE Sam's reflections — never becomes a
lecture. Every glossary box should be readable as something Sam
looked up while writing the notebook, not a textbook footnote.
Sample:

> "I typed `obb.equity.price.quote('MSFT')` and got back a dict.
> Wait — what's the difference between a **quote** and a **bar**?
> Turns out one's a single snapshot, the other's an aggregated
> interval. [Investopedia on OHLCV →]…"

### 10.5 Emoji restraint

The only two emoji allowed in teaching content are 📖 (glossary
boxes) and 📚 (Further reading + Learning path headers). No 🎯 ✅
⚠️ 💡 🚀 or any other decoration in body text. This matches the
CLAUDE.md file-hygiene rule ("only use emojis if the user
explicitly requests it") and keeps the notebooks legible in
terminal-rendered previews.

### 10.6 Sources hierarchy

Investopedia is the default source. Use canonical academic papers
or well-known finance blogs (SSRN, Quantpedia, Damodaran's
website) only when Investopedia does not have a good page — rare
in practice, but PBO (probability of backtest overfitting) is one
example. Never cite Wikipedia in a glossary box (its finance
pages drift); citing it inline in a primer for scope-of-topic is
OK.

### 10.7 Rules-of-thumb citation rule

Never invent a threshold. If a primer says "Sharpe above 1.0 is
decent," the accompanying link must land on a page that says the
same thing. If no such source exists, either drop the threshold
or attribute it explicitly ("in Sam's book, I'll call above 1.0
decent").

### 10.8 Coverage targets

- ≥ 80 unique Investopedia links across NB01-NB07 combined
- ≥ 30 concept-primer blocks (Type B) across the series
- ≥ 20 further-reading references (Type C entries + external
  papers/blogs) across the series

Per-notebook per-notebook targets live in
`docs/superpowers/specs/2026-07-25-portfolio-nb-teaching-depth-spec.md`.

---
