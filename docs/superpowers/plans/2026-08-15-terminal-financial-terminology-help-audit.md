# Terminal Financial Terminology and Help Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace developer-facing labels across all deficient Terminal widgets with explicit financial terminology and add glossary help to meaningful domain terms.

**Architecture:** Widget definitions own all display labels and glossary mappings. The local viewer consumes explicit metadata for table headers, row labels, chart legends, and metric cards; it never guesses financial meaning from snake_case. Each widget is tracked, implemented, tested, and committed under its own GitHub child issue.

**Tech Stack:** JSON widget manifests, self-contained HTML/CSS/JavaScript viewer, Node built-in test runner, pytest widget contracts, Playwright browser validation.

## Global Constraints

- Audit all 39 unique widgets used by the 12 Terminal tabs.
- Do not globally humanize snake_case.
- Do not add help to identifiers, symbols, dates, names, free text, statuses, or simple operational fields.
- All definitions must be curated static glossary records with safe external learning URLs.
- Unknown glossary keys render no help control.
- Preserve hover, keyboard focus, click-through, unique ARIA IDs, and tooltip teardown behavior.
- Implement child issues sequentially and cite the active issue in each commit.

---

### Task 1: Extend Help to Table Headers and Metric Cards (#2008)

**Files:**
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: `columnsDefs[].glossaryKey` and `data.metric.labels[field]` / `data.metric.metricGlossary[label]`.
- Produces: glossary-backed table-header and metric-card labels using the existing `metricHelpButtonHtml()` and `bindMetricHelpButtons()` behavior.

- [ ] Write failing tests proving a configured table header and metric card render approved text plus a help button, while unknown/unconfigured fields remain plain.
- [ ] Run `node --test openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs` and confirm the new tests fail.
- [ ] Update table column shaping to retain `glossaryKey`, render header content through a shared label/help builder, and pass widget metric metadata into `metricModel()` / `renderMetric()`.
- [ ] Run the Node viewer suite and confirm it passes.
- [ ] Commit only the renderer/test files with `Refs #2008`.

### Task 2: Fix Deficient Widgets Sequentially

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/openbb_portfolio_intel/widget_backend/widgets.json`
- Modify: `openbb_platform/extensions/portfolio/assets/local_viewer/index.html` for new glossary records only
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_pi_terminal_terminology_1987.py`
- Test: `openbb_platform/extensions/portfolio/assets/local_viewer/tests/viewer_render.test.mjs`

**Interfaces:**
- Consumes: Task 1 presentation metadata.
- Produces: explicit `columnsDefs`, chart series names, metric labels, and `metricGlossary` mappings for each issue below.

For each row, first claim the issue and set Project #4 to In Progress. Write a failing widget contract for the exact labels/help keys, implement only that widget and required glossary records, run the focused contract plus Node renderer suite, commit with the row's issue number, then close/release the claim before starting the next row.

| Order | Issue | Widget | Approved presentation | Help terms |
| --- | --- | --- | --- | --- |
| 1 | #1988 | `pi_equity_key_stats` | Keep current labels | Volume; 52-Week High; 52-Week Low |
| 2 | #1989 | `pi_financial_statements` | Line Item; Prior Period; Latest Period | Revenue; Gross Profit; Operating Income; Net Income; Total Assets; Total Debt; Cash & Equivalents; Operating Cash Flow; Free Cash Flow |
| 3 | #1990 | `pi_peer_multiples` | Symbol; P/E (TTM); P/E (Forward); EV/EBITDA; P/S (TTM) | all four valuation multiples |
| 4 | #1991 | `pi_earnings_history` | Quarter; Actual EPS; Estimated EPS; Surprise (%) | Actual EPS; Estimated EPS; Earnings Surprise |
| 5 | #1992 | `pi_price_target_history` | Date; Closing Price; Analyst Price Target | Closing Price; Analyst Price Target |
| 6 | #1993 | `pi_equity_technicals` | Analyst Consensus; Resistance 3/2/1; Pivot; Support 1/2/3; ATM Implied Volatility Term Structure | Consensus; Resistance; Pivot; Support; ATM Implied Volatility |
| 7 | #1994 | `pi_equity_competitors` | Symbol; Company; Price; Change (%) | Percentage Price Change |
| 8 | #1995 | `pi_equity_complementary` | Asset Type; Identifier; Name; Portfolio Weight (%); Market Value ($) | Portfolio Weight; Market Value |
| 9 | #1996 | `pi_equity_analyst_forecasts` | 12-Month Price Target; Target Range; Upside vs Current Price; Rating Distribution; EPS Surprise; Historical Revenue Estimate | all six forecast concepts |
| 10 | #1997 | `pi_basket_analyst_consensus` | Symbol; Average Price Target; Buy/Hold/Sell Ratings; Consensus Rating | Average Price Target; Consensus Rating |
| 11 | #1998 | `pi_lookthrough_top25` | Symbol; Holding; Effective Weight (%); Rank | Effective Weight |
| 12 | #1999 | `pi_concentration_gauge` | Concentration (HHI) | Herfindahl-Hirschman Index |
| 13 | #2000 | `pi_risk_dashboard` | Annualized Volatility; 1-Day VaR (95%); Beta vs SPY | all three risk measures |
| 14 | #2001 | `pi_risk_vol_chart` | 20-Day Volatility; 60-Day Volatility | both rolling volatility horizons |
| 15 | #2002 | `pi_brinson_attribution` | Sector; Allocation Effect; Selection Effect; Interaction Effect; Total Active Return | all four attribution effects |
| 16 | #2003 | `pi_whatif_card` | Symbol Weight (%); Sector Weight (%); Cash Weight (%); Beta vs SPY | all four portfolio-impact measures |
| 17 | #2004 | `pi_paper_perf_kpis` | Total Return (%); Annualized Sharpe Ratio; Maximum Drawdown (%) | all three performance measures |
| 18 | #2005 | `pi_paper_performance` | Date; Portfolio Equity | Portfolio Equity |
| 19 | #2006 | `pi_paper_blotter` | Time; Symbol; Side; Quantity; Status; Average Execution Price | Average Execution Price |
| 20 | #2007 | `pi_smart_money_ribbon` | Symbol; Activity Type; Actor; Transaction Value ($); Date | Transaction Value |

- [ ] Process rows 1–20 in order with one issue, focused test cycle, and commit per row.
- [ ] After every fifth row, run the full terminology contract and Node viewer suite.
- [ ] After row 20, run `.venv_portfolio\Scripts\python.exe -m pytest openbb_platform/extensions/portfolio_intel/tests/unit/test_pi_terminal_terminology_1987.py -q` and the Node viewer suite.

### Task 3: Final 12-Tab Live Audit and Publication

**Files:**
- Modify: `openbb_platform/extensions/portfolio_intel/tests/unit/test_pi_terminal_terminology_1987.py` only if the live audit exposes a missing contract.

**Interfaces:**
- Consumes: all child issue implementations.
- Produces: evidence on #1987 and a stacked pull request based on `feat/pi-f2-metric-help-gh-1984`.

- [ ] Restart the 6120 viewer in loopback-dev mode.
- [ ] Use Playwright to visit all 12 Terminal tabs and collect every table header, chart legend, and metric-card label.
- [ ] Fail the sweep if a user-facing label contains snake_case, any expected help control is absent, a widget is empty/failed, or the console reports an error.
- [ ] Run the Node viewer suite and full `portfolio_intel/tests/unit` non-integration suite.
- [ ] Post the 19 passing-widget inventory and final 20-widget fix evidence to #1987.
- [ ] Push the branch and open a PR in `prajoria/OpenBB` targeting `feat/pi-f2-metric-help-gh-1984`.
