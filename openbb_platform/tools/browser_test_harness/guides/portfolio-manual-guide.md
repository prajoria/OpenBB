# Portfolio Intelligence Terminal (W0-W9) — Manual Test Guide

**Story:** `portfolio`
**Notebook series:** [`notebooks/portfolio/`](../../../notebooks/portfolio/)
**Total steps:** 16

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
