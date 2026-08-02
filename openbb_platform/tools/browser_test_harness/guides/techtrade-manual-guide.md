# Techtrade Trading-Desk (T1-T6 + widget-completeness + invariants) — Manual Test Guide

**Story:** `techtrade`
**Notebook series:** [`notebooks/techtrade/`](../../../notebooks/techtrade/)
**Total steps:** 22

> This guide is auto-generated from the Story data source. Do NOT edit by hand — edit `src/openbb_browser_test_harness/stories/techtrade.py` and regenerate with:
> 
> ```powershell
> python -m openbb_browser_test_harness.emit_guide --story techtrade
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

4. Load the appropriate Workspace app (**Techtrade Trading Desk**).

---

## Steps
### Step T1 — Read the segment movers + scan table

**Step ID:** `T1.morning-scan` &nbsp; · &nbsp; **Tab:** `morning-scan` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/02-morning-scan.ipynb`](../../../notebooks/techtrade/02-morning-scan.ipynb)

Open the Morning Scan tab, read both widgets.

**Expected:** 6 segment rows (3 gainers, 3 losers) and 6 ticker rows.

**Endpoint:** `tt/scan/segment-movers`

![T1.morning-scan](screenshots/techtrade/T1.morning-scan.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T1 — Filter the scan table by segment

**Step ID:** `T1.filter` &nbsp; · &nbsp; **Tab:** `morning-scan` &nbsp; · &nbsp; **Action:** Input & observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/02-morning-scan.ipynb`](../../../notebooks/techtrade/02-morning-scan.ipynb)

Set segment=Technology on tt_scan_table.

**Expected:** 3 rows: NVDA, AAPL, MSFT.

**Params:** `segment=Technology`

**Endpoint:** `tt/scan/table`

![T1.filter](screenshots/techtrade/T1.filter.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T2 — Read the signal card for NVDA

**Step ID:** `T2.signal-card` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Set symbol=NVDA, read tt_signal_card.

**Expected:** Signal type BREAKOUT, direction LONG, confidence 0.87.

**Params:** `symbol=NVDA`

**Endpoint:** `tt/position/signal-card`

![T2.signal-card](screenshots/techtrade/T2.signal-card.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T2 — Read the plan card

**Step ID:** `T2.plan-card` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Read tt_plan_card.

**Expected:** Entry $173.50, Stop $168.20, Target $189.00, R:R 2.9x.

**Params:** `symbol=NVDA`

**Endpoint:** `tt/position/plan-card`

![T2.plan-card](screenshots/techtrade/T2.plan-card.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T2 — Read the order legs table

**Step ID:** `T2.order-legs` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Read tt_order_legs.

**Expected:** 3 rows (ENTRY, STOP, TARGET) with side, quantity, price, order_type.

**Params:** `symbol=NVDA`

**Endpoint:** `tt/position/order-legs`

![T2.order-legs](screenshots/techtrade/T2.order-legs.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T2 — Read the simulated P&L chart

**Step ID:** `T2.simulate` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Read tt_simulate_result.

**Expected:** 15 daily P&L values ranging 0 to 118 with two drawdown wobbles.

**Params:** `symbol=NVDA`

**Endpoint:** `tt/position/simulate`

![T2.simulate](screenshots/techtrade/T2.simulate.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T3 — Read the validation verdict

**Step ID:** `T3.verdict` &nbsp; · &nbsp; **Tab:** `validation` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/04-validation-gate.ipynb`](../../../notebooks/techtrade/04-validation-gate.ipynb)

Read tt_validation_verdict on the Validation tab.

**Expected:** 4 rows: PBO 0.18/PASS, DSR 1.47/PASS, OOS Sharpe 1.62/PASS, Verdict PASS. Verdict is a discrete gate — PASS or FAIL only.

**Params:** `symbol=AAPL`

**Endpoint:** `tt/validation/verdict`

![T3.verdict](screenshots/techtrade/T3.verdict.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T4 — Read the tuning report

**Step ID:** `T4.tuning` &nbsp; · &nbsp; **Tab:** `tuning` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/05-tuning-per-sector.ipynb`](../../../notebooks/techtrade/05-tuning-per-sector.ipynb)

Read tt_tuning_report.

**Expected:** 4 param rows (atr_period, sma_fast, sma_slow, risk_pct) with current, proposed, delta, and per-param validate_gate PASS or FAIL.

**Params:** `symbol=AAPL`

**Endpoint:** `tt/tuning/report`

![T4.tuning](screenshots/techtrade/T4.tuning.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T5 — Read the engine status

**Step ID:** `T5.engine-status` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Read tt_engine_status on the Engine Status tab.

**Expected:** Scheduler RUNNING, Signal engine READY, Execution engine IDLE.

**Endpoint:** `tt/engine/status`

![T5.engine-status](screenshots/techtrade/T5.engine-status.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T5 — Verdict FAIL blocks the execute bridge

**Step ID:** `T5.execute-blocked` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Set verdict=FAIL on tt_execute_bridge. Body MUST contain BLOCKED and MUST NOT contain READY (belt-and-suspenders per PR #1720).

**Expected:** Markdown body reads 'Execute Bridge: BLOCKED'.

**Params:** `verdict=FAIL`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![T5.execute-blocked](screenshots/techtrade/T5.execute-blocked.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T5 — Verdict PASS unblocks the execute bridge

**Step ID:** `T5.execute-ready` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Set verdict=PASS. Body should contain READY.

**Expected:** Markdown body reads 'Execute Bridge: READY'.

**Params:** `verdict=PASS`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![T5.execute-ready](screenshots/techtrade/T5.execute-ready.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Step T6 — Read the audit journal

**Step ID:** `T6.audit` &nbsp; · &nbsp; **Tab:** `audit` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Read tt_audit_journal on the Audit tab.

**Expected:** 5 rows with bar_date, replay_pnl, forward_pnl, deviation_bps.

**Params:** `symbol=AAPL`

**Endpoint:** `tt/audit/journal`

![T6.audit](screenshots/techtrade/T6.audit.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Coverage — tt_export_button

**Step ID:** `CX.tt-export-button` &nbsp; · &nbsp; **Tab:** `morning-scan` &nbsp; · &nbsp; **Action:** Observe &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/02-morning-scan.ipynb`](../../../notebooks/techtrade/02-morning-scan.ipynb)

Widget-completeness coverage step (B8 #1733). The scan tab's export button widget returns a markdown link block.

**Expected:** Markdown body with CSV/JSON export links + guidance.

**Endpoint:** `tt/scan/export`

![CX.tt-export-button](screenshots/techtrade/CX.tt-export-button.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — execute-bridge verdict enum rejects 'MAYBE'

**Step ID:** `IV.execute-bridge-verdict-invalid` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Deep invariant sweep (B9 #1734). execute-bridge verdict enum rejects 'MAYBE'. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `verdict=MAYBE`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.execute-bridge-verdict-invalid](screenshots/techtrade/IV.execute-bridge-verdict-invalid.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — execute-bridge verdict enum is case-sensitive (pass != PASS)

**Step ID:** `IV.execute-bridge-verdict-lowercase` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Deep invariant sweep (B9 #1734). execute-bridge verdict enum is case-sensitive (pass != PASS). If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `verdict=pass`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.execute-bridge-verdict-lowercase](screenshots/techtrade/IV.execute-bridge-verdict-lowercase.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — execute-bridge verdict rejects HTML-wrapped payload

**Step ID:** `IV.execute-bridge-verdict-xss` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Deep invariant sweep (B9 #1734). execute-bridge verdict rejects HTML-wrapped payload. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `verdict=<script>PASS</script>`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.execute-bridge-verdict-xss](screenshots/techtrade/IV.execute-bridge-verdict-xss.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — execute-bridge verdict rejects empty string

**Step ID:** `IV.execute-bridge-verdict-empty` &nbsp; · &nbsp; **Tab:** `engine-status` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Deep invariant sweep (B9 #1734). execute-bridge verdict rejects empty string. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `verdict=`

**Endpoint:** `tt/execute/bridge`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.execute-bridge-verdict-empty](screenshots/techtrade/IV.execute-bridge-verdict-empty.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — techtrade signal-card symbol rejects <script>

**Step ID:** `IV.tt-signal-card-symbol-xss` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Deep invariant sweep (B9 #1734). techtrade signal-card symbol rejects <script>. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `symbol=<script>alert(1)</script>`

**Endpoint:** `tt/position/signal-card`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.tt-signal-card-symbol-xss](screenshots/techtrade/IV.tt-signal-card-symbol-xss.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — techtrade plan-card symbol rejects shell metachars

**Step ID:** `IV.tt-plan-card-symbol-shell` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Deep invariant sweep (B9 #1734). techtrade plan-card symbol rejects shell metachars. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `symbol=NVDA;rm -rf /`

**Endpoint:** `tt/position/plan-card`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.tt-plan-card-symbol-shell](screenshots/techtrade/IV.tt-plan-card-symbol-shell.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — techtrade order-legs symbol >10 chars rejected

**Step ID:** `IV.tt-order-legs-symbol-oversize` &nbsp; · &nbsp; **Tab:** `position-workbench` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/03-single-position-deep-dive.ipynb`](../../../notebooks/techtrade/03-single-position-deep-dive.ipynb)

Deep invariant sweep (B9 #1734). techtrade order-legs symbol >10 chars rejected. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `symbol=NNNNNNNNNNN`

**Endpoint:** `tt/position/order-legs`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.tt-order-legs-symbol-oversize](screenshots/techtrade/IV.tt-order-legs-symbol-oversize.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — techtrade validation symbol rejects HTML img tag

**Step ID:** `IV.tt-validation-verdict-symbol-xss` &nbsp; · &nbsp; **Tab:** `validation` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/04-validation-gate.ipynb`](../../../notebooks/techtrade/04-validation-gate.ipynb)

Deep invariant sweep (B9 #1734). techtrade validation symbol rejects HTML img tag. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `symbol=<img onerror=1>`

**Endpoint:** `tt/validation/verdict`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.tt-validation-verdict-symbol-xss](screenshots/techtrade/IV.tt-validation-verdict-symbol-xss.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---

### Invariant — techtrade audit-journal symbol rejects javascript: URI

**Step ID:** `IV.tt-audit-journal-symbol-xss` &nbsp; · &nbsp; **Tab:** `audit` &nbsp; · &nbsp; **Action:** Assert (safety invariant) &nbsp; · &nbsp; **Persona:** systematic trader

**Notebook anchor:** [`notebooks/techtrade/06-audit-and-replay.ipynb`](../../../notebooks/techtrade/06-audit-and-replay.ipynb)

Deep invariant sweep (B9 #1734). techtrade audit-journal symbol rejects javascript: URI. If the guard is removed by a future change, the harness fails at PR time.

**Expected:** HTTP 400 rejection.

**Params:** `symbol=javascript:alert(1)`

**Endpoint:** `tt/audit/journal`

> ⚠️ **Safety invariant** — this step guards a load-bearing behavior. If it fails, DO NOT ship.

![IV.tt-audit-journal-symbol-xss](screenshots/techtrade/IV.tt-audit-journal-symbol-xss.png)

*Screenshot will be captured by* `python -m openbb_browser_test_harness.run --story techtrade --mode workspace --capture-guide-screenshots` (B6 #1728).

---
