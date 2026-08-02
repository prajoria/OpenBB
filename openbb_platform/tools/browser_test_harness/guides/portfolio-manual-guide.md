# Portfolio Intelligence Terminal (W0-W9 + widget-completeness) — Manual Test Guide

**Story:** `portfolio`
**Notebook series:** [`notebooks/portfolio/`](../../../notebooks/portfolio/)
**Total steps:** 49

> This guide is auto-generated from the Story data source. Do NOT edit by hand — edit `src/openbb_browser_test_harness/stories/portfolio.py` and regenerate with:
> 
> ```powershell
> python -m openbb_browser_test_harness.emit_guide --story portfolio
> ```

## Prep

1. Activate `.venv_portfolio` and install the harness:

   ```powershell
   pip install -e openbb_platform/tools/browser_test_harness/
   ```

2. Start the widget backend (harness spawns it automatically for automation mode; here for the manual mode you start it yourself):

   ```powershell
   $env:PI_WIDGET_BACKEND_AUTH_MODE = 'loopback-dev'
   uvicorn openbb_portfolio_intel.widget_backend.main:app --host 127.0.0.1 --port 6120
   ```

3. In OpenBB Workspace (`https://pro.openbb.co`): **Data connectors → Custom backend → Add** URL `http://127.0.0.1:6120`.

4. Load the appropriate Workspace app (**Portfolio Intelligence Terminal**).

---

## Steps
### Step W0 — Look at the provider health strip

**Step ID:** `W0.provider-health` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/01-getting-started-and-providers.ipynb`](../../../notebooks/portfolio/01-getting-started-and-providers.ipynb)

Every tab of the terminal has a provider-health chrome strip at the top showing the 5-tier data-sourcing chain (Track A paid, Track B free).

**Expected:** Two rows of tier-status badges: 'Track A (paid): fmp_cached / fmp / cboe / sec / yfinance-snap' and 'Track B (free): cboe / sec / yfinance', each tier tagged healthy / degraded / down.

**Endpoint:** `pi/health/providers`

![W0.provider-health](screenshots/portfolio/W0.provider-health.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W1 — Read the profile header

**Step ID:** `W1.symbol-header` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Enter symbol=AAPL; read pi_equity_profile_header.

**Expected:** Header shows Exchange, Sector/Industry, Price, Day Change.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/header`

![W1.symbol-header](screenshots/portfolio/W1.symbol-header.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W1 — Read the Key Stats table

**Step ID:** `W1.key-stats` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Read pi_equity_key_stats for the ticker on the Overview tab.

**Expected:** Table with Market Cap, P/E (TTM), Forward P/E, EV/EBITDA, P/S (TTM), Short Interest, Insider Ownership rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/key-stats`

![W1.key-stats](screenshots/portfolio/W1.key-stats.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W2 — Read Financial Statements (annual)

**Step ID:** `W2.financials` &nbsp; · &nbsp; **Tab:** `financials` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

On the Financials tab, verify period=annual returns 9 line items.

**Expected:** 9 rows: Revenue, Gross Profit, Operating Income, Net Income, Total Assets, Total Debt, Cash & Equivalents, OCF, FCF.

**Params:** `symbol=AAPL` · `period=annual`

**Endpoint:** `pi/equity/statements`

![W2.financials](screenshots/portfolio/W2.financials.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W3 — Sector composition pie

**Step ID:** `W3.xray-sector` &nbsp; · &nbsp; **Tab:** `xray` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Read pi_xray_sector on the X-Ray tab.

**Expected:** 6 sector rows totaling ~1.0; Information Technology ~0.38.

**Params:** `account_id=demo`

**Endpoint:** `pi/xray/sector`

![W3.xray-sector](screenshots/portfolio/W3.xray-sector.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W3 — Country composition pie

**Step ID:** `W3.xray-country` &nbsp; · &nbsp; **Tab:** `xray` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Read pi_xray_country on the X-Ray tab.

**Expected:** 6 country rows; United States ~0.72.

**Params:** `account_id=demo`

**Endpoint:** `pi/xray/country`

![W3.xray-country](screenshots/portfolio/W3.xray-country.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W3 — Concentration gauge (HHI)

**Step ID:** `W3.concentration` &nbsp; · &nbsp; **Tab:** `xray` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Read pi_concentration_gauge.

**Expected:** HHI metric between 0 and 1; demo value ~0.26.

**Params:** `account_id=demo`

**Endpoint:** `pi/concentration`

![W3.concentration](screenshots/portfolio/W3.concentration.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W4 — Read the risk dashboard

**Step ID:** `W4.risk-dashboard` &nbsp; · &nbsp; **Tab:** `risk` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Read pi_risk_dashboard.

**Expected:** vol_annualized, var_95_1d, beta_spy numeric values present, note field = 'demo book'.

**Params:** `account_id=demo`

**Endpoint:** `pi/risk/dashboard`

![W4.risk-dashboard](screenshots/portfolio/W4.risk-dashboard.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W4 — Brinson attribution waterfall

**Step ID:** `W4.brinson` &nbsp; · &nbsp; **Tab:** `risk` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Read pi_brinson_attribution.

**Expected:** Sector rows with allocation, selection, interaction, total.

**Params:** `window=1Y` · `benchmark_symbol=SPY`

**Endpoint:** `pi/attribution`

![W4.brinson](screenshots/portfolio/W4.brinson.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W5 — Read the event calendar

**Step ID:** `W5.calendar` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Read pi_event_calendar on the Calendar tab.

**Expected:** 5+ rows covering earnings, ex_dividend, form_8k events.

**Params:** `account_id=demo` · `horizon_days=30`

**Endpoint:** `pi/events/calendar`

![W5.calendar](screenshots/portfolio/W5.calendar.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W5 — Read the alerts panel

**Step ID:** `W5.alerts` &nbsp; · &nbsp; **Tab:** `alerts` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Read pi_alerts_panel on the Alerts tab.

**Expected:** At least one alert row present.

**Params:** `account_id=demo`

**Endpoint:** `pi/alerts`

![W5.alerts](screenshots/portfolio/W5.alerts.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W6 — Read the paper account KPIs

**Step ID:** `W6.paper-kpis` &nbsp; · &nbsp; **Tab:** `paper` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Read pi_paper_perf_kpis on the Paper Trading tab.

**Expected:** Total return, Sharpe, max drawdown numeric values.

**Params:** `account_id=demo`

**Endpoint:** `pi/paper/perf-kpis`

![W6.paper-kpis](screenshots/portfolio/W6.paper-kpis.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W7 — Try a hypothetical BUY

**Step ID:** `W7.whatif` &nbsp; · &nbsp; **Tab:** `risk` &nbsp; · &nbsp; **Action:** Input & observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Set delta_shares=100 on AAPL in pi_whatif_diff.

**Expected:** Markdown body labeled BUY AAPL x 100 with position deltas.

**Params:** `symbol=AAPL` · `delta_shares=100`

**Endpoint:** `pi/whatif`

![W7.whatif](screenshots/portfolio/W7.whatif.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W8 — Load the Morning Review composed one-pager

**Step ID:** `W8.morning-review` &nbsp; · &nbsp; **Tab:** `morning-review` &nbsp; · &nbsp; **Action:** Navigate &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/07-offline-recording-and-end-to-end.ipynb`](../../../notebooks/portfolio/07-offline-recording-and-end-to-end.ipynb)

Navigate to the Morning Review tab. It composes 5 REUSE widgets: concentration + risk dashboard + paper KPIs + event calendar + alerts panel.

**Expected:** All 5 widgets visible on one page. No blank slots. The apps.json layout is what B4's expected_layouts fixture validates.

![W8.morning-review](screenshots/portfolio/W8.morning-review.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W9 — Read the demo basket consensus

**Step ID:** `W9.basket-consensus` &nbsp; · &nbsp; **Tab:** `estimates` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/08-analyst-recommendations-basket.ipynb`](../../../notebooks/portfolio/08-analyst-recommendations-basket.ipynb)

Read pi_basket_analyst_consensus with basket_id=demo.

**Expected:** 5 rows (AAPL, MSFT, GOOGL, NVDA, META) with avg_target, buy, hold, sell, consensus fields.

**Params:** `basket_id=demo`

**Endpoint:** `pi/equity/basket-analyst-consensus`

![W9.basket-consensus](screenshots/portfolio/W9.basket-consensus.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step W9 — Verify basket safety invariant

**Step ID:** `W9.basket-guard` &nbsp; · &nbsp; **Tab:** `estimates` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/08-analyst-recommendations-basket.ipynb`](../../../notebooks/portfolio/08-analyst-recommendations-basket.ipynb)

Try basket_id=real_book. The endpoint MUST return 422 with a pointer to follow-up #1714, NOT demo rows disguised with a marker note.

**Expected:** HTTP 422 with detail 'basket_input_wiring_deferred' and follow_up = '#1714'. This is the load-bearing safety invariant codified in test_non_demo_basket_id_returns_422.

**Params:** `basket_id=real_book`

**Endpoint:** `pi/equity/basket-analyst-consensus`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![W9.basket-guard](screenshots/portfolio/W9.basket-guard.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_symbol_context chrome bar

**Step ID:** `CX.symbol-context` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Markdown badge echoing the ticker (AAPL).

**Params:** `symbol=AAPL`

**Endpoint:** `pi/context/symbol`

![CX.symbol-context](screenshots/portfolio/CX.symbol-context.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_book_context chrome bar

**Step ID:** `CX.book-context` &nbsp; · &nbsp; **Tab:** `xray` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Markdown badge echoing the account (demo).

**Params:** `account_id=demo`

**Endpoint:** `pi/context/book`

![CX.book-context](screenshots/portfolio/CX.book-context.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_financial_charts

**Step ID:** `CX.equity-financial-charts` &nbsp; · &nbsp; **Tab:** `financials` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Chart rows for 5-yr revenue + net income + margin.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/financials`

![CX.equity-financial-charts](screenshots/portfolio/CX.equity-financial-charts.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_technicals

**Step ID:** `CX.equity-technicals` &nbsp; · &nbsp; **Tab:** `technicals` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Consensus + pivot matrix rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/technicals`

![CX.equity-technicals](screenshots/portfolio/CX.equity-technicals.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_analyst_forecasts

**Step ID:** `CX.equity-analyst-forecasts` &nbsp; · &nbsp; **Tab:** `estimates` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Analyst rating distribution + surprise history rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/analyst-forecasts`

![CX.equity-analyst-forecasts](screenshots/portfolio/CX.equity-analyst-forecasts.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_complementary

**Step ID:** `CX.equity-complementary` &nbsp; · &nbsp; **Tab:** `comparison` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Top ETFs holding the ticker + bond ladder rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/complementary`

![CX.equity-complementary](screenshots/portfolio/CX.equity-complementary.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_competitors

**Step ID:** `CX.equity-competitors` &nbsp; · &nbsp; **Tab:** `comparison` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Regional industry competitors with live price rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/competitors`

![CX.equity-competitors](screenshots/portfolio/CX.equity-competitors.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_equity_price_history (line mode)

**Step ID:** `CX.equity-price-history` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** OHLC rows with date+close in line-chart mode.

**Params:** `symbol=AAPL` · `chart_type=line`

**Endpoint:** `pi/equity/price-history`

![CX.equity-price-history](screenshots/portfolio/CX.equity-price-history.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_charting (3M window)

**Step ID:** `CX.charting` &nbsp; · &nbsp; **Tab:** `technicals` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** OHLC + SMA20/SMA50/RSI14 overlays.

**Params:** `symbol=AAPL` · `window=3M`

**Endpoint:** `pi/equity/charting`

![CX.charting](screenshots/portfolio/CX.charting.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_institutional_ownership (13F holders)

**Step ID:** `CX.institutional-ownership` &nbsp; · &nbsp; **Tab:** `ownership` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Top holder rows with shares and pct_owned.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/institutional-ownership`

![CX.institutional-ownership](screenshots/portfolio/CX.institutional-ownership.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_stock_ownership (bucket pie)

**Step ID:** `CX.stock-ownership` &nbsp; · &nbsp; **Tab:** `ownership` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Ownership bucket rows (Institutions/Retail/ETFs/Insiders).

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/stock-ownership`

![CX.stock-ownership](screenshots/portfolio/CX.stock-ownership.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_insider_trading

**Step ID:** `CX.insider-trading` &nbsp; · &nbsp; **Tab:** `ownership` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Recent insider Form 4 transaction rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/insider-trading`

![CX.insider-trading](screenshots/portfolio/CX.insider-trading.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_earnings_history

**Step ID:** `CX.earnings-history` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Historical EPS actual vs. estimate rows with surprise%.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/earnings-history`

![CX.earnings-history](screenshots/portfolio/CX.earnings-history.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_stock_splits

**Step ID:** `CX.stock-splits` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Historical stock-split event rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/stock-splits`

![CX.stock-splits](screenshots/portfolio/CX.stock-splits.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_dividend_payment

**Step ID:** `CX.dividend-payment` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Recent dividend rows: ex-date, payment date, amount.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/dividend-payment`

![CX.dividend-payment](screenshots/portfolio/CX.dividend-payment.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_company_filings

**Step ID:** `CX.company-filings` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Recent 10-K/10-Q/8-K filing rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/company-filings`

![CX.company-filings](screenshots/portfolio/CX.company-filings.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_earnings_transcripts

**Step ID:** `CX.earnings-transcripts` &nbsp; · &nbsp; **Tab:** `calendar` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Markdown preview of latest earnings call transcript.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/earnings-transcripts`

![CX.earnings-transcripts](screenshots/portfolio/CX.earnings-transcripts.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_management_team

**Step ID:** `CX.management-team` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Key executives: name/title/pay/tenure rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/management-team`

![CX.management-team](screenshots/portfolio/CX.management-team.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_revenue_geography (pie)

**Step ID:** `CX.revenue-geography` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Region/revenue rows totaling ~total revenue.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/revenue-geography`

![CX.revenue-geography](screenshots/portfolio/CX.revenue-geography.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_revenue_business_line (pie)

**Step ID:** `CX.revenue-business-line` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Segment/revenue rows totaling ~total revenue.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/revenue-business-line`

![CX.revenue-business-line](screenshots/portfolio/CX.revenue-business-line.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_price_performance

**Step ID:** `CX.price-performance` &nbsp; · &nbsp; **Tab:** `overview` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** 9 horizon return rows (1D/1W/1M/3M/6M/YTD/1Y/3Y/5Y).

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/price-performance`

![CX.price-performance](screenshots/portfolio/CX.price-performance.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_peer_multiples

**Step ID:** `CX.peer-multiples` &nbsp; · &nbsp; **Tab:** `comparison` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Symbol + peers with P/E TTM, forward P/E, EV/EBITDA, P/S.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/peer-multiples`

![CX.peer-multiples](screenshots/portfolio/CX.peer-multiples.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_price_target_history

**Step ID:** `CX.price-target-history` &nbsp; · &nbsp; **Tab:** `estimates` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** analyst

**Notebook anchor:** [`notebooks/portfolio/02-single-name-deep-dive.ipynb`](../../../notebooks/portfolio/02-single-name-deep-dive.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Target-vs-close time series rows.

**Params:** `symbol=AAPL`

**Endpoint:** `pi/equity/price-target-history`

![CX.price-target-history](screenshots/portfolio/CX.price-target-history.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_lookthrough_top25

**Step ID:** `CX.lookthrough-top25` &nbsp; · &nbsp; **Tab:** `xray` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Top-25 effective holdings after ETF look-through.

**Params:** `account_id=demo`

**Endpoint:** `pi/lookthrough/top25`

![CX.lookthrough-top25](screenshots/portfolio/CX.lookthrough-top25.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_risk_vol_chart

**Step ID:** `CX.risk-vol-chart` &nbsp; · &nbsp; **Tab:** `risk` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/03-basket-xray-and-risk.ipynb`](../../../notebooks/portfolio/03-basket-xray-and-risk.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** 20d/60d rolling realized volatility rows.

**Params:** `account_id=demo`

**Endpoint:** `pi/risk/vol`

![CX.risk-vol-chart](screenshots/portfolio/CX.risk-vol-chart.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_whatif_card (structured diff)

**Step ID:** `CX.whatif-card` &nbsp; · &nbsp; **Tab:** `risk` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Structured before/after exposure diff rows.

**Params:** `symbol=AAPL` · `delta_shares=100`

**Endpoint:** `pi/whatif/card`

![CX.whatif-card](screenshots/portfolio/CX.whatif-card.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_paper_ticket (preview)

**Step ID:** `CX.paper-ticket` &nbsp; · &nbsp; **Tab:** `paper` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Markdown ticket preview (confirm=false).

**Params:** `account_id=demo` · `symbol=AAPL` · `side=buy` · `quantity=100` · `confirm=false`

**Endpoint:** `pi/paper/ticket`

![CX.paper-ticket](screenshots/portfolio/CX.paper-ticket.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_paper_blotter

**Step ID:** `CX.paper-blotter` &nbsp; · &nbsp; **Tab:** `paper` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Recent paper order rows with status.

**Params:** `account_id=demo`

**Endpoint:** `pi/paper/blotter`

![CX.paper-blotter](screenshots/portfolio/CX.paper-blotter.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_paper_performance

**Step ID:** `CX.paper-performance` &nbsp; · &nbsp; **Tab:** `paper` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`](../../../notebooks/portfolio/05-whatif-attribution-and-paper.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Paper account equity-curve rows.

**Params:** `account_id=demo`

**Endpoint:** `pi/paper/performance`

![CX.paper-performance](screenshots/portfolio/CX.paper-performance.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_backtest_button

**Step ID:** `CX.backtest-button` &nbsp; · &nbsp; **Tab:** `paper` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/06-backtest-and-validation.ipynb`](../../../notebooks/portfolio/06-backtest-and-validation.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Markdown widget kicking off one-click backtest.

**Params:** `account_id=demo`

**Endpoint:** `pi/backtest/oneclick`

![CX.backtest-button](screenshots/portfolio/CX.backtest-button.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_smart_money_ribbon

**Step ID:** `CX.smart-money-ribbon` &nbsp; · &nbsp; **Tab:** `alerts` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Insider + institutional move rows for held names.

**Params:** `account_id=demo`

**Endpoint:** `pi/smart-money/ribbon`

![CX.smart-money-ribbon](screenshots/portfolio/CX.smart-money-ribbon.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_news_ribbon

**Step ID:** `CX.news-ribbon` &nbsp; · &nbsp; **Tab:** `alerts` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Recent material news rows for held symbols.

**Params:** `account_id=demo` · `horizon_days=7`

**Endpoint:** `pi/news`

![CX.news-ribbon](screenshots/portfolio/CX.news-ribbon.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — pi_sentiment_gauge

**Step ID:** `CX.sentiment-gauge` &nbsp; · &nbsp; **Tab:** `alerts` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** portfolio manager

**Notebook anchor:** [`notebooks/portfolio/04-events-and-smart-money.ipynb`](../../../notebooks/portfolio/04-events-and-smart-money.ipynb)

Widget-completeness coverage step (B8 #1733). Confirms the widget's default endpoint responds with the expected shape.

**Expected:** Aggregate sentiment metric value.

**Params:** `account_id=demo`

**Endpoint:** `pi/sentiment`

![CX.sentiment-gauge](screenshots/portfolio/CX.sentiment-gauge.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story portfolio --mode workspace --capture-guide-screenshots` (B6 #1728).

---
