# PRD & Functional Spec: VS Code Trading Terminal Extension (`openbb-terminal-vscode`)

**Status:** Draft / Proposal — for leadership review  
**Author:** Portfolio & Platform working group  
**Target component:** VS Code Extension (`openbb-terminal-vscode`) + companion webview host + OpenBB Platform REST back-end  
**Companion documents:**
- [`docs/Specs/Portfolio-Intelligence-Engine-PRD.md`](./Portfolio-Intelligence-Engine-PRD.md) — Portfolio Intel engine whose widgets this terminal hosts
- [`docs/Specs/TechnicalTrading-Engine-PRD.md`](./TechnicalTrading-Engine-PRD.md) — Techtrade engine whose scan/signal/order widgets live in this terminal
- [`docs/Specs/Backtesting-Engine-PRD.md`](./Backtesting-Engine-PRD.md) — Backtesting engine surfaced via terminal panels
- [`desktop/README.md`](../../desktop/README.md) — Tauri desktop app: shares the React widget SDK and grid canvas
- [`openbb_platform/extensions/portfolio_intel/`](../../openbb_platform/extensions/portfolio_intel/) — Portfolio-Intel extension providing 60+ backend widget routes
- [`openbb_platform/extensions/techtrade/`](../../openbb_platform/extensions/techtrade/) — Techtrade extension providing scan, signal, plan, and execution widgets

**Date:** 2026-08-03  
**Decision posture:** Developer-resident UX first — the terminal lives where the developer already is (VS Code), sharing 100% of the existing Python back-end and React widget SDK; no new data paths or signal logic are introduced. A new front-end shell, not a new engine.  
**Licensing posture:** The fork is **AGPL-3.0** and **non-commercial**. Every dependency proposed here (VS Code Extension API, React, Vite) is MIT/Apache-2.0. No Commons-Clause exposure.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Guiding Principles](#4-guiding-principles)
5. [Product Vision & User Personas](#5-product-vision--user-personas)
6. [Competitive Landscape & Differentiation](#6-competitive-landscape--differentiation)
7. [Architecture Overview](#7-architecture-overview)
8. [VS Code Extension Host Layer](#8-vs-code-extension-host-layer)
9. [Webview Shell & Widget Canvas](#9-webview-shell--widget-canvas)
10. [Widget Inventory & Panel Assignments](#10-widget-inventory--panel-assignments)
11. [Terminal Layouts & Workspace Modes](#11-terminal-layouts--workspace-modes)
12. [Command Palette & Keybindings](#12-command-palette--keybindings)
13. [Symbol Context Propagation](#13-symbol-context-propagation)
14. [Back-End Integration & Local API Bridge](#14-back-end-integration--local-api-bridge)
15. [Authentication & API Key Management](#15-authentication--api-key-management)
16. [Theming & VS Code Token Integration](#16-theming--vs-code-token-integration)
17. [Non-Functional Requirements](#17-non-functional-requirements)
18. [Phased Delivery Roadmap](#18-phased-delivery-roadmap)
19. [Risks & Mitigations](#19-risks--mitigations)
20. [Open Questions / Decisions Needed](#20-open-questions--decisions-needed)
21. [Appendix A — Widget × Panel Mapping](#appendix-a--widget--panel-mapping)
22. [Appendix B — VS Code API Surface Used](#appendix-b--vs-code-api-surface-used)
23. [Appendix C — Glossary](#appendix-c--glossary)

---

## 1. Executive Summary

This PRD proposes **`openbb-terminal-vscode`**, a VS Code extension that embeds the
full OpenBB trading-terminal experience directly inside the editor. The goal is to bring
the **tick-by-tick UX of OpenBB Workspace** — multi-panel widget canvas, live data
streams, charting, portfolio analytics, trade scanning, and paper-order execution — into
the environment where quant developers and trader-developers already spend most of their
working day.

The extension is a **front-end shell, not a new engine**. It reuses:

- The **React widget SDK and 12-column `WidgetCanvas`** already shipping in `desktop/`
- Every widget registered by `openbb-portfolio-intel` (60+ routes), `openbb-techtrade`,
  `openbb-portfolio`, and `openbb-regime`
- The **OpenBB Platform REST API** (`uvicorn openbb_core.api.rest_api:app`) running
  locally, unchanged
- The **`fmp_cached` MySQL data layer** and all existing provider caches

What it adds is a thin VS Code host layer: a `TreeView` sidebar for workspace/layout
management, a Webview Panel per terminal tab, a command palette surface, symbol-context
sharing between the editor (hover, open file, active notebook) and running widgets, and
VS Code token-based theming so the terminal inherits the user's chosen VS Code theme
automatically.

**Why VS Code?** The target user (quant developer, portfolio-aware trader, self-directed
investor who writes code) already has VS Code open. Switching to a separate Electron or
browser window to check positions or scan movers costs context. A panel-resident
terminal eliminates the switch. The extension also opens the path to **notebook cell
commands** (e.g. `openbb.run_analysis("MSFT")` from a notebook cell widget) and
**code-adjacent data views** (hover a ticker symbol in Python source, see a live
mini-chart inline).

---

## 2. Problem Statement & Motivation

### 2.1 The Context-Switch Tax

Quant developers who use OpenBB typically have at least three windows open: VS Code (or
another editor) for strategy code, a browser tab for OpenBB Workspace, and a terminal
for the Python REPL or CLI. Any time they want to look up a chart, check a position, or
run a scan they must alt-tab out of their coding flow. This is a well-documented
productivity tax for developer-traders.

### 2.2 The Existing Desktop App Covers a Different Persona

The Tauri `desktop/` app is a standalone application optimised for the **portfolio-owner
persona**: install, start the back-end, open positions, review risk. It is not editor-
resident and does not have VS Code integration points (hover providers, notebook
widgets, command palette commands wired to open files).

### 2.3 OpenBB CLI Is Terminal-Resident But Not Visual

The `cli/` command-line interface gives developer-friendly access to data but does not
render charts, grids, or the 12-column widget canvas. Complex multi-panel layouts are
not expressible in a text terminal.

### 2.4 The Gap

There is no path today to:
- See a live mini-chart for the symbol currently under the cursor in a Python file
- Open a full Portfolio Intelligence terminal **without leaving VS Code**
- Run `techtrade` scan results in a docked side-panel while editing strategy code
- Execute a paper order triggered by a keybinding while reviewing the analysis notebook
- Share "the active symbol" between an open `.ipynb` notebook and a running chart widget

**`openbb-terminal-vscode`** fills this gap by making the full terminal a first-class
VS Code citizen.

---

## 3. Goals & Non-Goals

### Goals

| # | Goal |
|---|------|
| G1 | Embed full OpenBB widget canvas in VS Code Webview panels |
| G2 | Support all registered widgets from all platform extensions (portfolio, portfolio_intel, techtrade, regime, etc.) |
| G3 | Provide a multi-tab, multi-layout workspace experience equivalent to OpenBB Workspace inside VS Code |
| G4 | Implement symbol-context propagation: editor selection / hover / notebook variable → active symbol in all panels |
| G5 | Surface OpenBB commands in the VS Code Command Palette and status bar |
| G6 | Inherit VS Code theme tokens so the terminal looks native in any user theme |
| G7 | Provide a one-click "Start OpenBB back-end" action for first-run and restart |
| G8 | Support live data streaming (SSE / WebSocket) inside Webview panels |
| G9 | Maintain 100% widget parity with the `desktop/` Tauri app — no widgets only available in one host |
| G10 | Enable paper-order execution keybindings without leaving the editor |

### Non-Goals

| # | Non-Goal |
|---|----------|
| N1 | Building a new data engine, provider, or indicator library (all existing) |
| N2 | Real brokerage order routing (paper trading only in v1) |
| N3 | Cross-machine / cloud sync of terminal state (local-only v1) |
| N4 | Publishing to the VS Code Marketplace under the `OpenBB-finance` org in v1 (fork-internal) |
| N5 | Mobile / web deployment of the extension |
| N6 | Replacing the Tauri desktop app (parallel, complementary product) |
| N7 | Adding new Python back-end routes that don't already exist in the platform extensions |

---

## 4. Guiding Principles

1. **Shell, not engine.** This extension contributes zero new data logic. Every data
   capability is delegated to the running OpenBB Platform REST API. The extension is a
   presentation host.
2. **Widget registry is the contract.** Any widget that registers itself in the SDK
   (`registerWidget()` in `desktop/src/pi/sdk/registry.ts`) is automatically
   available in the VS Code terminal with no per-widget extension code.
3. **VS Code API as the integration seam.** Symbol propagation, theme tokens, command
   palette, status bar, and notebook integration all use VS Code's published extension
   API — no hacks, no DOM manipulation outside the Webview sandbox.
4. **Progressive enhancement.** The terminal is useful with the back-end stopped
   (fixture / snapshot mode). Each widget that supports `fixture={true}` renders
   demonstrative data without a live API call.
5. **Zero configuration for day 2.** Once the back-end is running and API keys are
   configured (via the existing `user_settings.json` mechanism), the extension has
   no additional setup requirements.

---

## 5. Product Vision & User Personas

### 5.1 Primary Persona — The Quant Developer

**"I write strategy code and I want to see live market data without leaving my
editor."**

- Has VS Code open 8+ hours a day
- Writes Python notebooks and `.py` strategy files
- Currently alt-tabs to a browser to check charts or positions
- Wants chart-on-hover for ticker symbols, inline notebook widgets, and fast scan results

### 5.2 Secondary Persona — The Portfolio-Aware Developer

**"I own a personal stock portfolio and use this fork to monitor and analyse it. I also
write OpenBB extensions. I want both in one place."**

- Runs the full portfolio intelligence stack locally
- Wants the portfolio risk dashboard, event calendar, and paper-trading blotter docked
  in VS Code alongside the code they write to manage the portfolio

### 5.3 Tertiary Persona — The Plugin Author

**"I'm writing a new OpenBB widget or extension and I want to preview it inside VS Code
during development."**

- Needs fixture-mode widget preview
- Needs hot-reload of the Webview when widget source changes
- Needs the backend logs panel open alongside the widget

---

## 6. Competitive Landscape & Differentiation

| Product | Where it lives | Widget canvas | OpenBB back-end | Code integration |
|---------|---------------|---------------|-----------------|-----------------|
| OpenBB Workspace (cloud) | Browser tab | ✅ | ✅ (cloud) | ❌ |
| OpenBB Tauri Desktop (`desktop/`) | Standalone app | ✅ | ✅ (local) | ❌ |
| Bloomberg Terminal | Standalone app | ✅ | ❌ | Limited |
| TradingView | Browser tab | Charts only | ❌ | ❌ |
| Refinitiv Eikon VSCode plugin | VS Code sidebar | Limited | ❌ | Limited |
| **`openbb-terminal-vscode`** (this) | **VS Code** | **✅ full** | **✅ (local)** | **✅ deep** |

The extension's differentiation is the combination of: **full widget parity with the
desktop app + deep VS Code integration points (hover, notebooks, command palette) +
open-source AGPL-3.0 + local-first / no cloud dependency**.

---

## 7. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        VS Code Process                           │
│                                                                  │
│  ┌─────────────────────────┐   ┌──────────────────────────────┐  │
│  │   Extension Host (Node) │   │   Webview Panel (Chromium)   │  │
│  │                         │   │                              │  │
│  │  • TreeView sidebar     │◄──►  • React app (Vite bundle)  │  │
│  │  • Command palette cmds │ msg │  • WidgetCanvas (12-col)   │  │
│  │  • Status bar items     │ bus │  • Widget SDK registry     │  │
│  │  • Symbol context API   │   │  • SSE / WS data streams    │  │
│  │  • Back-end lifecycle   │   │  • VS Code theme CSS vars   │  │
│  │  • Settings provider    │   │                              │  │
│  └─────────────┬───────────┘   └──────────┬───────────────────┘  │
│                │ spawn / monitor           │ fetch / EventSource  │
└────────────────┼───────────────────────────┼─────────────────────┘
                 ▼                           ▼
        ┌────────────────┐         ┌──────────────────────┐
        │  Python venv   │         │  OpenBB Platform API │
        │  (.venv_port-  │         │  uvicorn :8000       │
        │   folio)       │         │                      │
        │                │         │  /api/v1/…           │
        │  openbb_core   │◄────────│  /widgets.json       │
        │  portfolio_intel│        │  /apps.json          │
        │  techtrade     │         │  /sse/…              │
        │  fmp_cached    │         └──────────────────────┘
        └────────────────┘
```

### 7.1 Key Architectural Decisions

**AD-1 — Webview-per-tab, not single Webview.**  
Each terminal tab (Layout) is a separate `WebviewPanel`. This isolates React state
between tabs, enables independent refresh cycles, and maps naturally to VS Code's
tab/group model.

**AD-2 — Message bus, not direct REST from extension host.**  
The Extension Host node process communicates with each Webview via VS Code's
`postMessage` / `onDidReceiveMessage` channel, not by having the extension host proxy
HTTP. REST calls from widgets go directly from the Webview's `fetch` to the local
OpenBB API. The Extension Host only relays VS Code context events (active symbol,
theme change, command).

**AD-3 — Shared React bundle, multiple entry points.**  
The Webview React app is built by Vite into a single bundle loaded by every panel.
Panel identity (which layout to render) is passed as a query param from the extension
host. This keeps one build artifact and avoids per-layout bundle bloat.

**AD-4 — Widget SDK registry is the source of truth.**  
No extension-level widget registration. The VS Code extension loads the same widget
registry bundle built from `desktop/src/pi/sdk/registry.ts`. New widgets registered
there are automatically available in the VS Code terminal.

**AD-5 — Back-end lifecycle managed by extension host.**  
The extension host watches the `.venv_portfolio` Python interpreter, can spawn the
`uvicorn` server on first open, monitors the health endpoint (`GET /healthz`), and
displays a status-bar indicator. Users do not need a separate terminal to start the
back-end.

---

## 8. VS Code Extension Host Layer

### 8.1 Extension Manifest (`package.json`) Key Contributions

```jsonc
{
  "name": "openbb-terminal-vscode",
  "displayName": "OpenBB Trading Terminal",
  "publisher": "prajoria",
  "engines": { "vscode": "^1.85.0" },
  "categories": ["Other", "Data Science", "Visualization"],
  "activationEvents": [
    "onStartupFinished",
    "onCommand:openbb.openTerminal",
    "onLanguage:python"
  ],
  "contributes": {
    "commands": [ /* see §12 */ ],
    "views": {
      "openbb-explorer": [
        { "id": "openbbLayouts", "name": "Layouts" },
        { "id": "openbbWidgets", "name": "Widget Browser" },
        { "id": "openbbBackend", "name": "Back-end Status" }
      ]
    },
    "viewsContainers": {
      "activitybar": [
        {
          "id": "openbb-explorer",
          "title": "OpenBB Terminal",
          "icon": "assets/openbb-icon.svg"
        }
      ]
    },
    "configuration": { /* see §15 */ },
    "keybindings": [ /* see §12 */ ]
  }
}
```

### 8.2 TreeView: Layouts (`openbbLayouts`)

The Layouts tree shows named terminal layouts (equivalent to "workspaces" in OpenBB
Workspace). Each layout node is serialised as JSON in VS Code's `globalState`:

```typescript
interface TerminalLayout {
  id: string;           // uuid
  name: string;         // display name
  slots: WidgetSlot[];  // widget IDs + per-instance config
  gridTemplate?: string; // optional CSS grid template for non-standard layouts
  activeSymbol?: string; // last symbol context in this layout
}
```

**Tree node actions:**
- Open → creates/focuses Webview panel for this layout
- Rename → inline rename
- Duplicate → creates a copy with a new UUID
- Delete → removes from `globalState`
- Export → saves layout JSON to workspace `.openbb/layouts/` folder

### 8.3 TreeView: Widget Browser (`openbbWidgets`)

Flat list of all registered widget IDs (from `allWidgetIds()`), grouped by prefix
(`pi_*`, `tt_*`, `portfolio_*`, `regime_*`). Each node has:
- Drag to open layout → adds widget slot to the active layout
- Preview → opens a single-widget Webview in fixture mode
- "Add to current layout" inline action button

### 8.4 TreeView: Back-end Status (`openbbBackend`)

Shows:
- API server status (green/red indicator) — polled via `GET http://127.0.0.1:8000/healthz`
- Python environment path (from settings)
- Data provider health (from `pi_provider_health` widget data endpoint)
- Start / Stop / Restart inline actions
- "View logs" → opens Output Channel with `uvicorn` stdout/stderr

### 8.5 Symbol Hover Provider

Registers a `HoverProvider` for Python and Jupyter Notebook documents. When the cursor
rests on a string literal that matches a valid ticker symbol pattern (1–5 uppercase
letters, optionally followed by `:EXCHANGE`) for at least 500 ms:

1. Fetches a sparkline (5-day price, from `GET /api/v1/equity/price/historical?symbol={sym}&interval=1d&limit=5`) from the running back-end.
2. Renders an inline hover card (VS Code `MarkdownString` with an embedded SVG sparkline) showing: symbol, last price, 1-day change %, volume.
3. Includes a "📊 Open in Terminal" link that fires `openbb.openSymbolInTerminal`.

### 8.6 Notebook Kernel Variable Watcher

When the active editor is a Jupyter Notebook, the extension watches for kernel variable
assignments containing a ticker-like value (e.g. `symbol = "AAPL"`, `ticker = "MSFT"`).
When detected, it propagates the new symbol to all open terminal panels as the active
symbol context. This is implemented via VS Code's `NotebookDocument` events and does not
require injecting code into the kernel.

---

## 9. Webview Shell & Widget Canvas

### 9.1 Webview React App

The Webview app is a Vite-built React application, co-located in
`desktop/src/` (the existing bundle location) with a new entry point
`desktop/src/vscode-main.tsx`. It reuses 100% of the existing:

- `WidgetCanvas` component (`desktop/src/pi/canvas/WidgetCanvas.tsx`)
- Widget SDK registry (`desktop/src/pi/sdk/`)
- All registered widgets under `desktop/src/pi/widgets/`
- Tailwind CSS configuration

The VS Code Webview injects a `acquireVsCodeApi()` handle and mounts a thin bridge layer:

```typescript
// desktop/src/vscode-main.tsx  (new file)
const vscode = acquireVsCodeApi();

window.addEventListener("message", (event) => {
  const msg = event.data;
  if (msg.type === "symbolChange") setActiveSymbol(msg.symbol);
  if (msg.type === "themeChange") applyVSCodeTheme(msg.tokens);
  if (msg.type === "layoutLoad") setSlots(msg.slots);
});
```

### 9.2 Layout Modes

The terminal supports four layout modes, toggled from the layout toolbar:

| Mode | Description | Default grid |
|------|-------------|--------------|
| **Single** | One widget full-panel | 12/12 |
| **Split** | Two columns | 6/6 |
| **Triple** | 1 wide + 2 stacked right | 8/4 top / 8/4 bottom |
| **Dashboard** | 4-quadrant + 1 strip | OpenBB Workspace default |
| **Custom** | Drag-resize any slot | User-defined |

Layout mode is saved per-layout in `TerminalLayout.gridTemplate`.

### 9.3 Widget Toolbar

Each widget slot in the canvas renders a header bar (12px, collapsible) with:
- Widget title (from `WidgetMeta.title`)
- Symbol selector (text input, bound to active symbol context)
- Refresh button
- Detach to new panel icon
- PAPER badge (automatic when `WidgetMeta.isPaper === true`)
- Widget settings gear (for widgets that expose `config` props)

### 9.4 Live Data Streaming in Webview

VS Code Webview panels can make `fetch` and `EventSource` calls to `localhost` without
restriction (VS Code sets `localResourceRoots` to allow `http://127.0.0.1:8000`). The
extension host does not proxy streams. Widgets that use SSE (e.g. paper execution status,
live price feed) connect directly:

```typescript
const es = new EventSource("http://127.0.0.1:8000/api/v1/portfolio_intel/paper/stream");
es.onmessage = (e) => updateBlotter(JSON.parse(e.data));
```

---

## 10. Widget Inventory & Panel Assignments

All widgets from the existing registry are available. The table below maps each
registered widget to its recommended default panel in each built-in layout. A full
cross-reference is in [Appendix A](#appendix-a--widget--panel-mapping).

### 10.1 Portfolio Intelligence Widgets (`pi_*`)

| Widget ID | Title | Default Layout | Grid Cells |
|-----------|-------|----------------|-----------|
| `pi_equity_profile_header` | Company Header | Any equity panel, top strip | 12 |
| `pi_equity_key_stats` | Key Statistics | Equity Overview | 4 |
| `pi_equity_financial_charts` | Financial Charts | Equity Overview | 8 |
| `pi_equity_technicals` | Technical Indicators | Chart Layout | 8 |
| `pi_charting` | Price Chart | Chart Layout | 8 |
| `pi_price_performance` | Price Performance | Chart Layout | 4 |
| `pi_equity_analyst_forecasts` | Analyst Forecasts | Equity Overview | 6 |
| `pi_peer_multiples` | Peer Multiples | Equity Overview | 6 |
| `pi_xray_sector` | Sector X-Ray | Portfolio Risk | 6 |
| `pi_xray_country` | Country X-Ray | Portfolio Risk | 6 |
| `pi_lookthrough_top25` | Look-Through Top 25 | Portfolio Risk | 12 |
| `pi_concentration_gauge` | Concentration Gauge | Portfolio Risk | 4 |
| `pi_risk_dashboard` | Risk Dashboard | Portfolio Risk | 8 |
| `pi_risk_vol_chart` | Volatility Chart | Portfolio Risk | 12 |
| `pi_brinson_attribution` | Brinson Attribution | Portfolio Risk | 12 |
| `pi_event_calendar` | Event Calendar | Events | 12 |
| `pi_smart_money_ribbon` | Smart Money Ribbon | Equity Overview | 12 |
| `pi_institutional_ownership` | Institutional Ownership | Equity Detail | 6 |
| `pi_insider_trading` | Insider Trading | Equity Detail | 6 |
| `pi_earnings_history` | Earnings History | Equity Detail | 6 |
| `pi_earnings_transcripts` | Earnings Transcripts | Equity Detail | 6 |
| `pi_financial_statements` | Financial Statements | Equity Detail | 12 |
| `pi_company_filings` | Company Filings | Equity Detail | 6 |
| `pi_management_team` | Management Team | Equity Detail | 6 |
| `pi_revenue_geography` | Revenue by Geography | Equity Detail | 6 |
| `pi_revenue_business_line` | Revenue by Business Line | Equity Detail | 6 |
| `pi_price_target_history` | Price Target History | Equity Detail | 6 |
| `pi_stock_splits` | Stock Splits | Equity Detail | 4 |
| `pi_dividend_payment` | Dividend History | Equity Detail | 4 |
| `pi_news_ribbon` | News Feed | Any layout, bottom strip | 12 |
| `pi_sentiment_gauge` | Sentiment Gauge | Equity Overview | 4 |
| `pi_alerts_panel` | Alerts | Any layout, sidebar | 4 |
| `pi_paper_ticket` | Paper Order Ticket | Trading Desk | 4 |
| `pi_paper_blotter` | Paper Blotter | Trading Desk | 8 |
| `pi_paper_performance` | Paper Performance | Trading Desk | 8 |
| `pi_paper_perf_kpis` | Paper KPIs | Trading Desk | 4 |
| `pi_whatif_diff` | What-If Diff | Portfolio Risk | 8 |
| `pi_whatif_card` | What-If Card | Portfolio Risk | 4 |
| `pi_backtest_button` | Run Backtest | Any layout, toolbar | 4 |
| `pi_basket_analyst_consensus` | Basket Analyst Consensus | Portfolio Overview | 12 |
| `pi_provider_health` | Provider Health | Back-end Status panel | 12 |
| `pi_symbol_context` | Symbol Context Bar | Every layout, top | 12 |
| `pi_book_context` | Book Context | Portfolio Overview | 4 |
| `pi_equity_complementary` | Complementary Assets | Equity Overview | 6 |
| `pi_equity_competitors` | Competitors | Equity Overview | 6 |
| `pi_equity_price_history` | Price History Table | Equity Detail | 12 |
| `pi_stock_ownership` | Stock Ownership | Equity Detail | 6 |

### 10.2 Portfolio Widgets (`portfolio_*`)

| Widget ID | Title | Default Layout |
|-----------|-------|----------------|
| `portfolio_positions` | Positions | Portfolio Overview |
| `portfolio_summary` | Portfolio Summary | Portfolio Overview |
| `portfolio_allocation` | Allocation | Portfolio Overview |
| `portfolio_cost_basis` | Cost Basis | Portfolio Overview |
| `portfolio_tax_summary` | Tax Summary | Portfolio Overview |
| `portfolio_performance` | Performance | Portfolio Overview |
| `portfolio_snapshots` | Snapshots | Portfolio Overview |
| `equity_historical` | Equity History | Chart Layout |
| `stock_context` | Stock Context | Equity Overview |
| `stock_profile` | Stock Profile | Equity Overview |
| `stock_fundamentals` | Fundamentals | Equity Overview |
| `stock_technicals` | Technicals | Chart Layout |
| `stock_valuation` | Valuation | Equity Overview |
| `stock_risk` | Stock Risk | Portfolio Risk |
| `stock_relative` | Relative Performance | Chart Layout |
| `stock_decision` | Decision | Equity Overview |
| `espp_purchases` | ESPP Purchases | Portfolio Overview |

### 10.3 TechTrade Widgets (`tt_*`)

| Widget ID | Title | Default Layout |
|-----------|-------|----------------|
| `tt_segment_movers` | Segment Movers | Trading Desk |
| `tt_scan_table` | Scan Table | Trading Desk |
| `tt_signal_card` | Signal Card | Trading Desk |
| `tt_plan_card` | Trade Plan | Trading Desk |
| `tt_order_legs` | Order Legs | Trading Desk |
| `tt_simulate_result` | Simulate Result | Trading Desk |
| `tt_validation_verdict` | Validation Verdict | Trading Desk |
| `tt_tuning_report` | Tuning Report | Trading Desk |
| `tt_audit_journal` | Audit Journal | Trading Desk |
| `tt_engine_status` | Engine Status | Trading Desk |
| `tt_execute_bridge` | Execute Bridge | Trading Desk |
| `tt_execute_paper_status` | Paper Execution Status | Trading Desk |
| `tt_export_button` | Export | Trading Desk |

### 10.4 Regime Widget

| Widget ID | Title | Default Layout |
|-----------|-------|----------------|
| `regime_detect` | Regime Detector | Portfolio Risk / Trading Desk |

---

## 11. Terminal Layouts & Workspace Modes

### 11.1 Built-in Layouts

The extension ships five pre-defined layout templates that users can instantiate
from the Layouts tree-view or Command Palette:

#### Layout 1: Portfolio Overview
**Purpose:** Morning review of portfolio state.

```
┌─────────────────────┬──────────────┐
│  portfolio_summary  │  pi_book_    │
│  (8 cols)           │  context (4) │
├──────────┬──────────┼──────────────┤
│portfolio_│portfolio_│pi_concentration│
│positions │allocation│gauge (4)      │
│ (4)      │ (4)      │               │
├──────────┴──────────┴──────────────┤
│       pi_event_calendar (12)       │
├──────────────────────────────────--┤
│       pi_news_ribbon (12)          │
└────────────────────────────────────┘
```

#### Layout 2: Equity Deep-Dive
**Purpose:** Single-stock analysis.

```
┌──────────────────────────────────────┐
│   pi_equity_profile_header (12)      │
├────────────────┬─────────────────────┤
│ pi_charting    │ pi_equity_key_stats │
│   (8)          │   (4)               │
├────────────────┼─────────────────────┤
│pi_equity_      │pi_equity_analyst_   │
│financial_charts│forecasts (6)        │
│  (6)           │                     │
├────────────────┴─────────────────────┤
│   pi_news_ribbon (12)                │
└──────────────────────────────────────┘
```

#### Layout 3: Portfolio Risk
**Purpose:** Risk decomposition and what-if analysis.

```
┌────────────┬───────────┬─────────────┐
│pi_xray_    │pi_xray_   │pi_concentr- │
│sector (4)  │country (4)│ation_gauge  │
│            │           │    (4)      │
├────────────┴───────────┴─────────────┤
│   pi_risk_dashboard (8) │pi_whatif_  │
│                         │card (4)    │
├─────────────────────────┴────────────┤
│   pi_brinson_attribution (12)        │
├──────────────────────────────────────┤
│   pi_whatif_diff (12)                │
└──────────────────────────────────────┘
```

#### Layout 4: Trading Desk
**Purpose:** Scan, signal, plan, execute.

```
┌────────────────┬─────────────────────┐
│tt_segment_     │ tt_signal_card (4)  │
│movers (8)      │ tt_plan_card (4)    │
│                │ tt_order_legs (4)   │
├────────────────┴─────────────────────┤
│        tt_scan_table (12)            │
├─────────────────┬────────────────────┤
│pi_paper_ticket  │ pi_paper_blotter   │
│   (4)           │    (8)             │
├─────────────────┴────────────────────┤
│   pi_paper_performance (8) │KPIs (4) │
└──────────────────────────────────────┘
```

#### Layout 5: Chart Focus
**Purpose:** Technical charting + indicator overlay.

```
┌──────────────────────────────────────┐
│   pi_charting (12)                   │
├──────────────────────────────────────┤
│pi_equity_technicals (8) │pi_price_   │
│                         │performance │
│                         │  (4)       │
├──────────────────────────────────────┤
│   regime_detect (6) │tt_signal_card  │
│                     │    (6)         │
└──────────────────────────────────────┘
```

### 11.2 User-Defined Layouts

Users create layouts from the Layouts tree-view ("+" button) or from
`openbb.newLayout`. They name the layout, select a template to start from, and can
drag widgets from the Widget Browser into slots. Layout state is persisted in VS Code
`globalState` (cross-session) and optionally exported to `.openbb/layouts/<name>.json`
in the open workspace folder (enabling team-shared layouts committed to the repo).

---

## 12. Command Palette & Keybindings

### 12.1 Commands

| Command ID | Title | Description |
|-----------|-------|-------------|
| `openbb.openTerminal` | OpenBB: Open Terminal | Opens/focuses last active layout |
| `openbb.newLayout` | OpenBB: New Layout… | Creates a new terminal layout |
| `openbb.openSymbolInTerminal` | OpenBB: Open Symbol… | Prompts for symbol, opens Equity Deep-Dive |
| `openbb.openPortfolio` | OpenBB: Open Portfolio Overview | Opens Portfolio Overview layout |
| `openbb.openTradingDesk` | OpenBB: Open Trading Desk | Opens Trading Desk layout |
| `openbb.openRisk` | OpenBB: Open Risk Dashboard | Opens Portfolio Risk layout |
| `openbb.openChart` | OpenBB: Open Chart… | Prompts for symbol, opens Chart Focus layout |
| `openbb.startBackend` | OpenBB: Start Back-end | Spawns uvicorn if not running |
| `openbb.stopBackend` | OpenBB: Stop Back-end | Terminates uvicorn |
| `openbb.restartBackend` | OpenBB: Restart Back-end | Stop + Start |
| `openbb.openBackendLogs` | OpenBB: Show Back-end Logs | Opens Output Channel |
| `openbb.setApiKey` | OpenBB: Configure API Keys… | Opens VS Code settings UI filtered to openbb credentials |
| `openbb.previewWidget` | OpenBB: Preview Widget… | Quick pick of all widget IDs, opens fixture preview |
| `openbb.paperBuyActive` | OpenBB: Paper Buy Active Symbol | Places paper buy order for current active symbol |
| `openbb.paperSellActive` | OpenBB: Paper Sell Active Symbol | Places paper sell order for current active symbol |
| `openbb.runAnalysis` | OpenBB: Run Full Analysis… | Runs 7-phase `Analysis/` pipeline for symbol, opens notebook |
| `openbb.exportLayout` | OpenBB: Export Current Layout | Saves layout JSON to workspace |
| `openbb.importLayout` | OpenBB: Import Layout… | Loads layout JSON from file |

### 12.2 Default Keybindings

| Keybinding | Command | Condition |
|-----------|---------|-----------|
| `Ctrl+Shift+O` (Win/Linux) / `Cmd+Shift+O` (Mac) | `openbb.openTerminal` | Always |
| `Ctrl+Shift+Q` | `openbb.openPortfolio` | Always |
| `Ctrl+Shift+T` | `openbb.openTradingDesk` | Always |
| `Ctrl+Shift+R` | `openbb.openRisk` | Always |
| `Ctrl+Alt+B` | `openbb.paperBuyActive` | `openbb.terminalFocused` |
| `Ctrl+Alt+S` | `openbb.paperSellActive` | `openbb.terminalFocused` |
| `F9` | `openbb.openChart` | `editorTextFocus && python` |

---

## 13. Symbol Context Propagation

Symbol context is the "active symbol" shared between all open terminal panels and the
VS Code editor. It is the mechanism that makes the terminal feel integrated with the
code editor rather than a separate app.

### 13.1 Sources (how symbol context is set)

| Source | Trigger | Priority |
|--------|---------|----------|
| Widget symbol selector | User types ticker in a widget's symbol input | Highest — explicit user action |
| Command Palette | `openbb.openSymbolInTerminal` or `openbb.openChart` | High |
| Editor hover | Cursor rests 500ms on a ticker string in Python/Notebook | Medium |
| Notebook variable watcher | Assignment `symbol = "AAPL"` detected in notebook cell | Medium |
| Editor selection | User selects 1–5 uppercase letters that match a symbol pattern | Low |
| Layout default | `TerminalLayout.activeSymbol` loaded on layout open | Lowest |

### 13.2 Consumers (how symbol context is used)

- All open Webview panels receive a `symbolChange` postMessage from the extension host
- Each widget with a symbol selector updates its display independently
- The VS Code status bar item shows the active symbol and last price
- The hover provider uses the propagated symbol to pre-warm its sparkline cache

### 13.3 Symbol Validation

Before broadcasting a new symbol, the extension host validates it against the back-end
`GET /api/v1/equity/search?query={sym}&limit=1`. If the API returns no results, the
symbol is rejected and the previous context is retained. Validation is debounced (300 ms)
and cached (5 min) to avoid hammering the back-end on every keystroke.

---

## 14. Back-End Integration & Local API Bridge

### 14.1 Back-End Lifecycle

The extension manages the uvicorn server process:

```typescript
interface BackendState {
  status: "stopped" | "starting" | "running" | "error";
  pid?: number;
  port: number;       // default 8000, configurable
  lastHealthAt?: Date;
}
```

**Start sequence:**
1. Check `GET http://127.0.0.1:{port}/healthz` — if 200, mark running (already started externally or from previous session).
2. If not running, read Python interpreter path from settings (`openbb.pythonPath`).
3. Spawn: `{pythonPath} -m uvicorn openbb_core.api.rest_api:app --host 127.0.0.1 --port {port}`
4. Pipe stdout/stderr to an Output Channel named "OpenBB Back-end".
5. Poll `/healthz` every 2 s until 200 (timeout 60 s).
6. Update status bar, fire `onBackendStatusChange` event.

**Stop sequence:**
1. Send `SIGTERM` to process group.
2. Wait 3 s; if not exited, `SIGKILL`.
3. Update state to `stopped`.

**Health monitoring:**
- Poll `/healthz` every 10 s while running.
- Two consecutive failures → state transitions to `error`, status bar turns red, notification shown.
- User can restart from notification toast or status bar click.

### 14.2 API Base URL

Configurable via `openbb.apiBaseUrl` (default `http://127.0.0.1:8000`). All Webview
`fetch` calls use this base URL, injected as a `window.__OPENBB_API_BASE__` global by
the extension host when creating the Webview.

### 14.3 Widgets JSON Discovery

On startup (after back-end healthy), the extension host fetches:
- `GET {apiBase}/widgets.json` → widget manifest for all registered extensions
- `GET {apiBase}/apps.json` → app/layout templates registered by extensions

These are stored in `globalState` and used to populate the Widget Browser tree-view
and validate layout slot configurations.

---

## 15. Authentication & API Key Management

### 15.1 No New Auth Mechanism

API keys continue to live in `~/.openbb_platform/user_settings.json` (the existing
platform convention). The extension does not store credentials itself.

### 15.2 VS Code Settings Surface

The extension contributes read-only settings that point to the platform config:

```jsonc
{
  "openbb.pythonPath": {
    "type": "string",
    "default": "",
    "description": "Path to the Python interpreter with OpenBB Platform installed (e.g. .venv_portfolio/Scripts/python.exe)"
  },
  "openbb.apiBaseUrl": {
    "type": "string",
    "default": "http://127.0.0.1:8000",
    "description": "Base URL for the OpenBB Platform REST API"
  },
  "openbb.apiPort": {
    "type": "number",
    "default": 8000
  },
  "openbb.autoStartBackend": {
    "type": "boolean",
    "default": true,
    "description": "Automatically start the OpenBB back-end when VS Code starts"
  },
  "openbb.userSettingsPath": {
    "type": "string",
    "default": "",
    "description": "Override path to user_settings.json (leave blank to use platform default ~/.openbb_platform/user_settings.json)"
  }
}
```

### 15.3 API Key Configuration Command

`openbb.setApiKey` opens a quick-pick list of providers (FMP, FRED, etc.) and walks
the user through updating `user_settings.json` via VS Code's file editor, with
validation feedback on save.

---

## 16. Theming & VS Code Token Integration

### 16.1 CSS Variable Bridge

VS Code injects theme colours as CSS variables on the Webview `<body>` via the
`--vscode-*` custom property namespace. The React app reads these at mount time and
maps them to Tailwind CSS tokens:

```typescript
// desktop/src/vscode-theme.ts  (new file)
export function applyVSCodeTheme(): void {
  const style = getComputedStyle(document.body);
  const map: Record<string, string> = {
    "--color-background":    style.getPropertyValue("--vscode-editor-background"),
    "--color-foreground":    style.getPropertyValue("--vscode-editor-foreground"),
    "--color-surface":       style.getPropertyValue("--vscode-sideBar-background"),
    "--color-border":        style.getPropertyValue("--vscode-panel-border"),
    "--color-primary":       style.getPropertyValue("--vscode-button-background"),
    "--color-primary-fg":    style.getPropertyValue("--vscode-button-foreground"),
    "--color-accent":        style.getPropertyValue("--vscode-focusBorder"),
    "--color-success":       style.getPropertyValue("--vscode-terminal-ansiGreen"),
    "--color-error":         style.getPropertyValue("--vscode-terminal-ansiRed"),
    "--color-warning":       style.getPropertyValue("--vscode-terminal-ansiYellow"),
  };
  for (const [k, v] of Object.entries(map)) {
    document.documentElement.style.setProperty(k, v);
  }
}
```

The extension host also sends a `themeChange` postMessage whenever the VS Code theme
changes (`window.onDidChangeActiveColorTheme`), triggering a re-apply.

### 16.2 Dark / Light / High-Contrast

All three VS Code theme kinds (dark, light, high-contrast) are supported. Chart
libraries (Recharts, Plotly) accept theme tokens via the same CSS variable bridge.

---

## 17. Non-Functional Requirements

### 17.1 Performance

| Metric | Target |
|--------|--------|
| Extension activation time | < 500 ms (excludes back-end start) |
| Webview first-paint (fixture mode) | < 300 ms |
| Webview first-paint (live API) | < 1000 ms after back-end reports healthy |
| Symbol context propagation latency | < 100 ms end-to-end (extension host → all panels) |
| Back-end start time | < 30 s from cold (existing platform startup time) |
| Widget hot-reload (dev mode) | < 2 s after source change |

### 17.2 Memory & Resource

- Each Webview panel uses ~50–80 MB RAM (Chromium process, same as existing Tauri app
  per window). Max recommended concurrent panels: 5.
- Extension host Node process: < 50 MB.
- No persistent background processes when VS Code is closed.

### 17.3 Security

- Webview CSP: `connect-src http://127.0.0.1:8000 ws://127.0.0.1:8000; script-src 'nonce-{nonce}'`
  No external script loading. No `eval`.
- `retainContextWhenHidden: true` — panels retain state when hidden to avoid
  re-fetching on focus. Trade-off: higher memory while panels are open.
- No credential storage in the extension; all secrets live in `user_settings.json`
  outside the extension's control.
- Back-end bound to `127.0.0.1` (loopback) only; not accessible from the network.

### 17.4 Reliability

- Webview error boundary per widget slot (inherited from `WidgetCanvas` — already
  implemented). One failing widget does not blank the panel.
- Back-end crash → extension shows notification + auto-restart option (if
  `openbb.autoRestartBackend` setting is true).
- Fixture mode provides a usable terminal without any back-end running (for demos,
  development, and offline use).

### 17.5 Compatibility

| Requirement | Target |
|-------------|--------|
| VS Code version | 1.85.0+ |
| OS | Windows 10+, macOS 13+, Ubuntu 22.04+ |
| Python | 3.10–3.13 (inherits platform support matrix) |
| Node.js (build-time only) | 20+ |

---

## 18. Phased Delivery Roadmap

### Phase 1 — MVP: Static Shell + Widget Canvas (Sprint 1–2)

**Scope:**
- Extension scaffold: `package.json`, activation, commands, Layouts tree-view stub
- Webview host: loads existing `desktop/` Vite bundle in a panel
- `WidgetCanvas` renders in Webview with fixture data
- VS Code theme token bridge (dark theme only)
- Manual back-end start (user must start uvicorn externally in Phase 1)
- Two built-in layouts: Portfolio Overview and Equity Deep-Dive (fixture data only)

**Done criteria:**
- `openbb.openTerminal` opens a panel showing portfolio widgets with fixture data
- Theme tokens applied (background, foreground, borders match VS Code theme)
- CI: Webview snapshot tests pass

### Phase 2 — Live Data + Back-end Lifecycle (Sprint 3–4)

**Scope:**
- Back-end lifecycle management (start/stop/health poll/status bar)
- Webview switches from fixture to live API on back-end healthy
- All five built-in layout templates
- Symbol context propagation (widget selector only)
- Command palette for all commands in §12.1

**Done criteria:**
- `openbb.startBackend` starts uvicorn, status bar turns green
- Widgets fetch live data from running back-end
- All five layout templates available

### Phase 3 — Editor Integration (Sprint 5–6)

**Scope:**
- Symbol hover provider (Python + Notebook)
- Notebook variable watcher
- Editor selection → symbol context
- `openbb.runAnalysis` command (opens Analysis notebook)
- `openbb.openChart` with symbol prompt

**Done criteria:**
- Hovering a ticker in a Python file shows sparkline mini-card
- Variable assignment in notebook propagates to open terminal panels

### Phase 4 — Full Widget Parity + Layout Management (Sprint 7–8)

**Scope:**
- All widgets from §10 available in Widget Browser
- Drag-to-layout from Widget Browser
- User-defined layouts (create, rename, duplicate, delete, export/import)
- Layout export to `.openbb/layouts/*.json`
- Fixture-mode preview for every widget (`openbb.previewWidget`)
- Widget Browser grouping by prefix

**Done criteria:**
- Every widget in the registry renders in VS Code (verified by automated preview scan)
- Layout save/load round-trips correctly

### Phase 5 — Paper Trading Keybindings + Polish (Sprint 9–10)

**Scope:**
- Paper buy/sell keybindings (`Ctrl+Alt+B`, `Ctrl+Alt+S`)
- API key configuration command
- High-contrast theme support
- Full dark/light theme support for all widgets and charts
- Back-end auto-start on VS Code start
- Auto-restart on crash
- Performance tuning to hit all targets in §17.1

**Done criteria:**
- All NFRs in §17 pass
- Extension functions on Windows, macOS, Ubuntu
- Full manual QA pass against all five layouts with live back-end

---

## 19. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | VS Code Webview CSP blocks live data fetch | Medium | High | Test CSP config early in Phase 1; use `localResourceRoots` and explicit `http://127.0.0.1` in `connect-src` |
| R2 | Widget bundle size causes slow Webview first-paint | Medium | Medium | Code-split by layout using Vite dynamic imports; measure in Phase 1 |
| R3 | Back-end process management differs on Windows vs macOS (SIGTERM vs TerminateProcess) | High | Medium | Use Node.js `child_process` with platform-specific kill logic; test on both OSes in Phase 2 |
| R4 | Theme token mapping is incomplete for some VS Code themes | Low | Low | Map the 10 core tokens; fall back to hardcoded dark theme values if a token is missing |
| R5 | Symbol hover provider creates performance regression in large Python files | Medium | Medium | Gate on `configuration.inspect()` setting; debounce and limit to visible viewport ranges |
| R6 | Widget registry divergence between `desktop/` bundle and VS Code bundle (two build artefacts) | Low | High | Single `desktop/` Vite config with two entry points (`desktop-main.tsx`, `vscode-main.tsx`); share 100% of widget source |
| R7 | Notebook variable watcher breaks with non-OpenBB Jupyter kernels | Low | Low | Scope watcher to notebooks that have OpenBB imported (check kernel variables for `obb` or `openbb`) |
| R8 | Open-source VS Code Marketplace publish requires Microsoft review | N/A (v1 fork-internal) | Low | Explicitly scoped as Non-Goal N4 for v1 |

---

## 20. Open Questions / Decisions Needed

| # | Question | Owner | Due |
|---|----------|-------|-----|
| Q1 | Should the Webview back-end URL be configurable per-workspace or per-user? (`workspace` vs `user` settings scope) | Platform PM | Phase 1 |
| Q2 | Do we want `retainContextWhenHidden: true` (higher memory, no reload on focus) or `false` (lower memory, reload on focus)? Default recommendation: `true` for ≤3 panels, configurable. | UX lead | Phase 2 |
| Q3 | Should layout state be stored in VS Code `globalState` (cross-workspace) or `workspaceState` (per-folder)? Recommendation: `globalState` default, with workspace-scoped export as opt-in. | Platform PM | Phase 1 |
| Q4 | Should the extension auto-start the back-end on VS Code launch (`onStartupFinished`) or only on first terminal open (`onCommand`)? Recommendation: configurable, default `onCommand` to avoid startup delay for users not actively trading. | Platform PM | Phase 1 |
| Q5 | Which charting library for sparkline hover cards — reuse `pi_charting` widget (full React bundle import, slower) or a lightweight SVG sparkline (fast, < 2 KB)? Recommendation: lightweight SVG for hover, full widget for panels. | Frontend lead | Phase 3 |
| Q6 | Should `openbb.runAnalysis` open the existing `notebooks/portfolio/` notebooks or spawn a new notebook from a template? Recommendation: template-based to avoid modifying checked-in notebooks. | Platform PM | Phase 3 |

---

## Appendix A — Widget × Panel Mapping

Full cross-reference of every registered widget to the built-in layout(s) it appears in
by default, and whether it is included in the Widget Browser for drag-placement.

| Widget ID | Portfolio Overview | Equity Deep-Dive | Portfolio Risk | Trading Desk | Chart Focus | Widget Browser |
|-----------|:-----------------:|:----------------:|:--------------:|:------------:|:-----------:|:--------------:|
| `pi_symbol_context` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `pi_equity_profile_header` | | ✅ | | | | ✅ |
| `pi_equity_key_stats` | | ✅ | | | | ✅ |
| `pi_equity_financial_charts` | | ✅ | | | | ✅ |
| `pi_charting` | | | | | ✅ | ✅ |
| `pi_equity_technicals` | | | | | ✅ | ✅ |
| `pi_price_performance` | | | | | ✅ | ✅ |
| `pi_equity_analyst_forecasts` | | ✅ | | | | ✅ |
| `pi_peer_multiples` | | ✅ | | | | ✅ |
| `pi_xray_sector` | | | ✅ | | | ✅ |
| `pi_xray_country` | | | ✅ | | | ✅ |
| `pi_lookthrough_top25` | | | ✅ | | | ✅ |
| `pi_concentration_gauge` | | | ✅ | | | ✅ |
| `pi_risk_dashboard` | | | ✅ | | | ✅ |
| `pi_risk_vol_chart` | | | ✅ | | | ✅ |
| `pi_brinson_attribution` | | | ✅ | | | ✅ |
| `pi_event_calendar` | ✅ | | | | | ✅ |
| `pi_smart_money_ribbon` | | ✅ | | | | ✅ |
| `pi_institutional_ownership` | | ✅ | | | | ✅ |
| `pi_insider_trading` | | ✅ | | | | ✅ |
| `pi_earnings_history` | | ✅ | | | | ✅ |
| `pi_earnings_transcripts` | | ✅ | | | | ✅ |
| `pi_financial_statements` | | ✅ | | | | ✅ |
| `pi_news_ribbon` | ✅ | ✅ | | | | ✅ |
| `pi_sentiment_gauge` | | ✅ | | | | ✅ |
| `pi_alerts_panel` | ✅ | | | ✅ | | ✅ |
| `pi_paper_ticket` | | | | ✅ | | ✅ |
| `pi_paper_blotter` | | | | ✅ | | ✅ |
| `pi_paper_performance` | | | | ✅ | | ✅ |
| `pi_paper_perf_kpis` | | | | ✅ | | ✅ |
| `pi_whatif_diff` | | | ✅ | | | ✅ |
| `pi_whatif_card` | | | ✅ | | | ✅ |
| `pi_backtest_button` | | ✅ | | ✅ | | ✅ |
| `pi_book_context` | ✅ | | | | | ✅ |
| `pi_basket_analyst_consensus` | ✅ | | | | | ✅ |
| `pi_provider_health` | | | | | | ✅ |
| `portfolio_positions` | ✅ | | | | | ✅ |
| `portfolio_summary` | ✅ | | | | | ✅ |
| `portfolio_allocation` | ✅ | | | | | ✅ |
| `portfolio_performance` | ✅ | | | | | ✅ |
| `tt_segment_movers` | | | | ✅ | | ✅ |
| `tt_scan_table` | | | | ✅ | | ✅ |
| `tt_signal_card` | | | | ✅ | | ✅ |
| `tt_plan_card` | | | | ✅ | | ✅ |
| `tt_order_legs` | | | | ✅ | | ✅ |
| `tt_engine_status` | | | | ✅ | | ✅ |
| `tt_execute_paper_status` | | | | ✅ | | ✅ |
| `regime_detect` | | | ✅ | ✅ | | ✅ |

---

## Appendix B — VS Code API Surface Used

| API | Used for | Version available |
|-----|----------|-----------------|
| `vscode.window.createWebviewPanel` | Terminal panels | 1.23+ |
| `vscode.window.createTreeView` | Layouts + Widget Browser sidebar | 1.25+ |
| `vscode.window.createStatusBarItem` | Back-end status + active symbol | 1.0+ |
| `vscode.commands.registerCommand` | All commands in §12.1 | 1.0+ |
| `vscode.languages.registerHoverProvider` | Ticker symbol hover cards | 1.0+ |
| `vscode.workspace.onDidChangeConfiguration` | Settings changes | 1.0+ |
| `vscode.window.onDidChangeActiveColorTheme` | Theme sync | 1.45+ |
| `vscode.notebook.onDidChangeNotebookDocument` | Notebook variable watcher | 1.50+ |
| `vscode.ExtensionContext.globalState` | Layout persistence | 1.0+ |
| `vscode.window.createOutputChannel` | Back-end logs | 1.0+ |
| `child_process.spawn` (Node.js) | uvicorn lifecycle | Node built-in |

All APIs are available in VS Code 1.85.0+. No proposed or experimental API is required.

---

## Appendix C — Glossary

| Term | Definition |
|------|------------|
| **Webview** | VS Code's sandboxed browser iframe, used to host React UIs inside the editor |
| **Extension Host** | The Node.js process VS Code uses to run extension code (separate from the Webview renderer) |
| **WidgetCanvas** | The 12-column React grid that mounts widget slots, defined in `desktop/src/pi/canvas/WidgetCanvas.tsx` |
| **Widget Registry** | The module-scoped Map of all registered widgets, keyed by stable ID, defined in `desktop/src/pi/sdk/registry.ts` |
| **WidgetSlot** | A `{widgetId, config?}` tuple that identifies one widget instance in a layout |
| **Layout** | A named set of `WidgetSlot[]` plus grid configuration, persisted in VS Code `globalState` |
| **Active Symbol** | The ticker symbol currently in focus, propagated from editor context to all open terminal panels |
| **SSE** | Server-Sent Events — the streaming transport used by back-end routes like paper execution status |
| **Fixture mode** | Widget render mode using hardcoded sample data instead of live API calls; used for previews and offline use |
| **PAPER badge** | Visual indicator (yellow pill) automatically added by `WidgetCanvas` to widgets with `isPaper: true` |
| **postMessage** | The VS Code extension ↔ Webview message channel; the only permitted cross-boundary communication |
| **CSP** | Content Security Policy — the Webview security header restricting script sources and network targets |
| **fmp_cached** | The first-party FMP data provider with MySQL caching, used by all back-end widget routes |
| **uvicorn** | The ASGI server that hosts the OpenBB Platform REST API (`openbb_core.api.rest_api:app`) |
