# OpenBB Terminal — VS Code Extension User Guide

The OpenBB Terminal extension embeds the OpenBB trading terminal directly
inside VS Code: activity-bar tree views for Layouts, Widget Browser, and
Back-end Status; a webview-hosted terminal panel with 5 built-in and 4
curated golden layouts; a symbol-context bus driven by widgets, Python
hovers, notebook source text, and editor selections; and a
loopback-only Python back-end (`openbb-api`) supervised by the extension.

For the product vision, non-functional requirements, and design rationale
see [`docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md`](../../../docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md).

---

## 1. Introduction

**What it is.** A VS Code extension (`openbb-terminal-vscode`) that
renders OpenBB layouts and widgets in a webview, drives them from the
same `openbb-api` server the standalone terminal uses, and integrates
symbol context with the surrounding Python / notebook editor.

**Who it is for.** Portfolio-intelligence and quantitative research
users who already work in VS Code and want charts, tables, and paper
trading side-by-side with source code and notebooks — without leaving
the editor.

**What it is NOT.** It is not a live brokerage front-end. Paper trading
posts to a local endpoint only (see §9). It is not a hosted service —
everything runs on `127.0.0.1`.

---

## 2. Prerequisites

- **VS Code 1.85 or newer** (`engines.vscode: ^1.85.0`).
- **Python 3.10 – 3.13** with `openbb-api` installed. Portfolio work
  uses the project venv at `.venv_portfolio\Scripts\python.exe`
  (Windows) — see the repo `CLAUDE.md` for the exact editable-install
  recipe.
- A workspace-trust decision. Untrusted workspaces disable back-end
  spawn, clear `openbb.pythonPath` / `openbb.userSettingsPath`, and
  force `openbb.autoStartBackend = false`.

### Back-end spawn paths

The extension talks to a single loopback endpoint. Two supported
paths:

- **Path A — extension-managed spawn.** Set `openbb.pythonPath` to the
  absolute path of a Python interpreter that has `openbb-api` on its
  `Scripts/` (Windows) or `bin/` (POSIX) path. Typical value:
  `.venv_portfolio\Scripts\python.exe`. The extension resolves
  `openbb-api` from that interpreter and launches
  `openbb-api --host 127.0.0.1 --port <openbb.apiPort>`.
- **Path B — user-managed process.** Start the back-end manually in a
  terminal:

  ```bash
  openbb-api --host 127.0.0.1 --port 6900
  ```

  The extension probes `/widgets.json` first and attaches to the
  running process instead of spawning a new one. This is the fallback
  when `openbb.autoStartBackend` is `false`.

**Port note.** The extension defaults to **6900**, distinct from the
repo helper `./openbb.sh api` (which listens on **8000**). If you use
the helper, either change `openbb.apiPort` / `openbb.apiBaseUrl` to
`8000` or start `openbb-api` explicitly on `6900`.

### Health probes

- **Readiness probe:** `GET /widgets.json` — polled every 2 s during
  `starting` with a 60 s ceiling. Two consecutive failures during the
  running phase transition the lifecycle to `error`. Source of truth
  for widget registration; see
  [`docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`](../../../docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md)
  (ADR-#1808).
- **Provider health:** `GET /pi/health/providers` — surfaced by the
  Back-end Status tree view and used by the Trading Desk / Portfolio
  Overview layouts to badge FIXTURE vs LIVE data per widget.

---

## 3. Installation

### Path A — Extension Development Host (recommended during dev)

```bash
cd apps/vscode-terminal-extension
npm install
npm run compile
```

Then press **F5** inside VS Code. A second VS Code window opens with
the extension loaded.

### Path B — Sideload a packaged `.vsix`

```bash
cd apps/vscode-terminal-extension
npm run package        # emits openbb-terminal-vscode-<version>.vsix
code --install-extension openbb-terminal-vscode-<version>.vsix
```

Restart VS Code after installation.

---

## 4. First run

1. Click the **OpenBB Terminal** icon in the activity bar. Three
   sidebar tree views appear: **Layouts**, **Widget Browser**,
   **Back-end Status**.
2. `openbb.autoStartBackend` is **`false`** by default. Open the
   command palette (`Ctrl+Shift+P`) and run **OpenBB: Start Back-end**,
   or set the setting to `true` for automatic startup.
3. Watch the left-hand status bar item cycle through
   `stopped` → `starting` → `running`. If the readiness probe fails
   twice the item goes to `error` (red) — click it to open
   **OpenBB: Open Back-end Logs**.
4. Press **Ctrl+Shift+O** (macOS `Cmd+Shift+O`) to open the terminal
   webview. It boots into the Portfolio Overview layout by default.
5. Each widget renders a small header badge — **FIXTURE** while the
   back-end is unreachable or the widget is served from
   `fixtures/widgets.sample.json`; **LIVE** once the back-end reports
   ready and the fetcher returns real data.

---

## 5. Command reference

Every command from `package.json` `contributes.commands` (27 total),
grouped by concern. The Palette title matches what appears in the
picker under `OpenBB: …`.

### Terminal & layouts

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.openTerminal` | OpenBB: Open Terminal | `Ctrl+Shift+O` / `Cmd+Shift+O` | Open the terminal webview panel with the active layout. |
| `openbb.newLayout` | OpenBB: New Layout | — | Create a user layout, optionally from a built-in template. |
| `openbb.openPortfolio` | OpenBB: Open Portfolio Overview | `Ctrl+Shift+Q` / `Cmd+Shift+Q` | Load the built-in Portfolio Overview layout. |
| `openbb.openTradingDesk` | OpenBB: Open Trading Desk | `Ctrl+Shift+T` / `Cmd+Shift+T` | Load the built-in Trading Desk layout. |
| `openbb.openRisk` | OpenBB: Open Portfolio Risk | `Ctrl+Shift+R` / `Cmd+Shift+R` | Load the built-in Portfolio Risk layout. |
| `openbb.openChart` | OpenBB: Open Chart | `F9` (when `editorTextFocus && resourceLangId == python`) | Load Chart Focus and adopt the ticker under cursor if valid. |
| `openbb.exportLayout` | OpenBB: Export Layout | — | Write the active user layout to `.openbb/layouts/<slug>.json`. |
| `openbb.importLayout` | OpenBB: Import Layout | — | Import a layout JSON file into `globalState`. |
| `openbb.renameLayout` | OpenBB: Rename Layout | — | Rename a user layout (built-ins immutable). |
| `openbb.duplicateLayout` | OpenBB: Duplicate Layout | — | Copy a layout with a new id and `(copy)` name suffix. |
| `openbb.deleteLayout` | OpenBB: Delete Layout | — | Delete a user layout (modal confirm). |
| `openbb.loadGoldenLayout` | OpenBB: Load Golden Layout | — | Pick a curated golden layout; deep-copies into user layouts. |
| `openbb.resetToDefaultLayouts` | OpenBB: Reset to Default Layouts | — | Clear `openbb.userLayouts` (modal confirm). |

### Symbol

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.openSymbolInTerminal` | OpenBB: Open Symbol in Terminal | — | Prompt for a ticker (`^[A-Z]{1,5}(:[A-Z]+)?$`), broadcast on the symbol bus. |

### Back-end

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.startBackend` | OpenBB: Start Back-end | — | Attach to a running loopback back-end or spawn a new one. |
| `openbb.stopBackend` | OpenBB: Stop Back-end | — | SIGTERM/SIGKILL (POSIX) or `taskkill /F` (Windows). |
| `openbb.restartBackend` | OpenBB: Restart Back-end | — | Stop then start; also triggered by `autoRestartBackend`. |
| `openbb.openBackendLogs` | OpenBB: Open Back-end Logs | — | Reveal the `"OpenBB Terminal"` output channel. |

### Widgets

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.previewWidget` | OpenBB: Preview Widget | — | Palette pick a widget; open a single-widget preview panel. |
| `openbb.previewWidgetFromBrowser` | OpenBB: Preview Widget | — | Inline eye icon on the Widget Browser tree row. |
| `openbb.addWidgetToActiveLayout` | OpenBB: Add Widget to Active Layout | — | Inline add icon; drops widget into the current layout. |

### Paper trading

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.paperBuyActive` | OpenBB: Paper Buy (Active Symbol) | `Ctrl+Alt+B` / `Cmd+Alt+B` (when `openbb.terminalFocused`) | Modal-confirm and POST a paper buy for the active symbol. |
| `openbb.paperSellActive` | OpenBB: Paper Sell (Active Symbol) | `Ctrl+Alt+S` / `Cmd+Alt+S` (when `openbb.terminalFocused`) | Modal-confirm and POST a paper sell for the active symbol. |

### Analysis

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.runAnalysis` | OpenBB: Run Analysis | — | Prompt for a symbol, spawn a fresh untitled notebook that runs the 7-phase `Analysis/stock_analysis.py` pipeline. |

### Config

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.setApiKey` | OpenBB: Set API Key | — | Pick a known credential (FMP, FMP-cached, FRED, Polygon, Intrinio, Tiingo); open `user_settings.json` for direct entry — the extension never accepts or logs the key value. |

### Diagnostics

| Command ID | Palette title | Keybinding | What it does |
|---|---|---|---|
| `openbb.showPerfReport` | OpenBB: Show Performance Report | — | Dump the perf-harness report and NFR budget check into the output channel. |

---

## 6. Default keybindings

Seven defaults ship with the extension:

| Key (Windows / Linux) | Key (macOS) | Command | `when` clause |
|---|---|---|---|
| `Ctrl+Shift+O` | `Cmd+Shift+O` | `openbb.openTerminal` | — |
| `Ctrl+Shift+Q` | `Cmd+Shift+Q` | `openbb.openPortfolio` | — |
| `Ctrl+Shift+T` | `Cmd+Shift+T` | `openbb.openTradingDesk` | — |
| `Ctrl+Shift+R` | `Cmd+Shift+R` | `openbb.openRisk` | — |
| `Ctrl+Alt+B` | `Cmd+Alt+B` | `openbb.paperBuyActive` | `openbb.terminalFocused` |
| `Ctrl+Alt+S` | `Cmd+Alt+S` | `openbb.paperSellActive` | `openbb.terminalFocused` |
| `F9` | `F9` | `openbb.openChart` | `editorTextFocus && resourceLangId == python` |

Rebind through **File > Preferences > Keyboard Shortcuts** — search
for `openbb.` to filter.

---

## 7. Layouts

### Built-in layouts (5)

Loaded from repo-versioned fixtures in `fixtures/layouts/`:

- **Portfolio Overview** — landing page; portfolio composition, risk
  summary, top movers.
- **Equity Deep-Dive** — single-stock analytics on the active symbol.
- **Portfolio Risk** — sector / country X-Ray, concentration gauge,
  Brinson attribution, what-if diff.
- **Trading Desk** — segment movers, scan table, paper ticket +
  blotter, paper performance + KPIs.
- **Chart Focus** — charting canvas, equity technicals, regime detect.

### Golden layouts (4)

Curated JSON in `golden_layouts/`. Loaded through **OpenBB: Load
Golden Layout** (quick-pick), which deep-copies the picked layout
into your user layouts with a fresh id and preserves
`sourceGoldenId`:

- `momentum-scan`
- `risk-review`
- `single-stock-deep-dive`
- `paper-trading-cockpit`

### User layouts

Live in `globalState["openbb.userLayouts"]` with `schemaVersion: 1`.
CRUD via **New Layout**, **Rename**, **Duplicate**, **Delete**.

### Workspace export

**OpenBB: Export Layout** writes the active layout to
`.openbb/layouts/<slug>.json` in the workspace via
`vscode.workspace.fs`. Check the resulting file into git if you want
the layout to travel with the repo. **OpenBB: Import Layout** does the
reverse, with fresh-id collision avoidance.

**OpenBB: Reset to Default Layouts** clears every user layout after a
modal confirm (built-ins remain immutable).

---

## 8. Symbol context

The active symbol is broadcast on a bus that any open OpenBB Terminal
webview subscribes to. Per PRD §13.1, symbol sources are strictly
priority-ordered — a higher-priority event wins:

1. **Widget input.** A `[data-widget-symbol-input]` field inside any
   webview. Explicit user action, highest trust.
2. **`OpenBB: Open Symbol in Terminal`.** Palette entry; validates
   against `^[A-Z]{1,5}(:[A-Z]+)?$`.
3. **Python hover.** `HoverProvider` for Python source files and
   Python notebook cells. Regex accepts assignment forms
   (`symbol = "AAPL"`, `ticker='MSFT'`) and quoted literals
   (`"NVDA"`). Rejects bare identifiers (`API`, `URL`, `MAX`, `SQL`,
   `DDL`), single letters, ≥6-char runs, and lower/mixed case.
4. **Notebook source-text watcher.** Scans cell source for
   `\b(?:symbol|ticker)\s*=\s*["']([A-Z]{2,5})(?::[A-Z]+)?["']` and
   calls `SymbolContext.setSymbol(..., 'notebook')`. **Source text
   only** — does not introspect Jupyter kernel runtime variable
   values.
5. **Editor selection CodeAction.** Lightbulb "Open <SYM> in OpenBB
   Terminal" when the current selection matches
   `^[A-Z]{1,5}(:[A-Z]+)?$`. Fires only on explicit `Invoke` trigger
   (never in auto-suggest); never auto-broadcasts — you must click.

Symbol validation caches for 5 minutes per symbol against
`GET /api/v1/equity/search`, with in-flight request coalescing.

---

## 9. Paper trading

- **Trigger:** `Ctrl+Alt+B` (buy) / `Ctrl+Alt+S` (sell) when the
  webview panel is focused, or via the palette entries.
- **Confirmation:** modal by default before any order goes out.
- **Endpoint:** `POST /api/v1/portfolio_intel/paper/order` on the
  loopback back-end.
- **Auth:** none — no `Authorization` header, no `?token=` query.
  See ADR-#1809 below.
- **Graceful degradation:** a 404 from the back-end degrades into a
  "recorded locally" warning so the hotkeys stay useful while the
  endpoint rolls out.
- **Not a real broker.** Per PRD §N2 the paper endpoint has no route
  to any live brokerage. Nothing you do here moves real money.

---

## 10. Notebook + Analysis integration

**OpenBB: Run Analysis** prompts for a symbol (regex-validated),
verifies the target Python can `import stock_analysis`, then opens a
fresh untitled notebook built from a template with three cells:

1. Title markdown.
2. Pipeline invocation calling `run_full_analysis(AnalysisConfig(...))`.
3. Phase-by-phase results.

Per PRD Q6 the extension **does not** modify the checked-in notebooks
in `notebooks/portfolio/`. The generated notebook lives in the
workspace as an untitled document until you save it — put it under
`notebooks_local/` to run against personal data (see repo `CLAUDE.md`
"Notebook local sandbox").

---

## 11. Configuration reference

Every `openbb.*` property from `package.json`
`contributes.configuration.properties`:

| Setting | Type | Default | Scope | Description |
|---|---|---|---|---|
| `openbb.pythonPath` | string | `""` | machine | Absolute path to the Python interpreter with `openbb-api` installed. Blank → resolve `python` from `PATH`. |
| `openbb.apiPort` | number | `6900` | window | Local port for the back-end. Must match `openbb.apiBaseUrl`. |
| `openbb.apiBaseUrl` | string | `http://127.0.0.1:6900` | machine | Base URL for readiness + health probes. Loopback only. |
| `openbb.autoStartBackend` | boolean | `false` | machine | If true, spawn / attach to the back-end on VS Code startup. |
| `openbb.userSettingsPath` | string | `""` | machine | Override for `user_settings.json`. Blank → `~/.openbb_platform/user_settings.json`. |
| `openbb.autoRestartBackend` | boolean | `false` | machine | Auto-restart on a health-check failure with 2s/4s/8s backoff. |
| `openbb.autoRestartMaxAttempts` | number | `3` | machine | Restart-attempt ceiling before surfacing an error notification. |

The machine-scope choices are deliberate: they close the workspace
override attack surface documented in ADR-#1809 (see §13).

---

## 12. Theming

- **Auto-inherit.** The extension detects the VS Code active color
  theme (`Dark`, `Light`, `HighContrast`, `HighContrastLight`) and
  posts a matching token pack to each webview.
- **WCAG-AA baseline.** `src/theme/audit.ts` runs a relative-luminance
  contrast check (4.5:1) and reports missing tokens.
- **`data-openbb-theme` attribute.** The webview root is tagged with
  `<html data-openbb-theme="dark|light|high-contrast">` on every
  apply so widget CSS can branch cleanly.
- **Fallback palettes.** `DARK_FALLBACK`, `LIGHT_FALLBACK`, and
  `HIGH_CONTRAST_FALLBACK` in `src/theme/tokens.ts` cover the case
  where VS Code has not resolved a token yet.

Details in [`docs/theme.md`](theme.md).

---

## 13. Security posture

- **Loopback-only.** `openbb.apiBaseUrl` must be `http` or `https`
  targeting `127.0.0.1` / `localhost`. Any other value is rejected
  with a `[security]` warning; the extension falls back to
  `http://127.0.0.1:${apiPort}`.
- **Workspace-trust.** `capabilities.untrustedWorkspaces = "limited"`.
  In untrusted workspaces the extension clears `openbb.pythonPath`
  and `openbb.userSettingsPath`, forces `autoStartBackend = false`,
  and refuses to spawn a new back-end (attaching to an already-running
  loopback back-end still works so the webview keeps rendering).
- **File perms.** `ApiKeyManager.writeSettings` writes
  `user_settings.json` and any `.bak` sibling with `mode: 0o600` on
  POSIX and removes the `.bak` after a successful write.
- **No auth over loopback.** Per ADR-#1809
  ([`docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md`](../../../docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md)),
  the extension never sends an `Authorization` header and never
  appends a `?token=` query parameter to loopback requests. The
  `verify:invariants` script (grep guards) enforces this on every
  compile.

Details in [`docs/security.md`](security.md).

---

## 14. Troubleshooting

### Red status bar item

Two consecutive readiness-probe failures push the lifecycle to
`error`. Common causes:

- `openbb-api` is not installed in the interpreter that
  `openbb.pythonPath` points at. Fix: `pip install openbb-api` in
  the venv, or repoint `openbb.pythonPath`.
- A stale process is holding `openbb.apiPort`. Fix: kill it or change
  the port (`openbb.apiPort` + `openbb.apiBaseUrl` together).
- Workspace is untrusted and no user-managed back-end is running.
  Fix: trust the workspace or start `openbb-api` manually per §2
  Path B.

Click the status bar item to open the logs.

### FIXTURE badge stuck on a widget

- Back-end is not `running` yet — check the Back-end Status tree view.
- The widget's endpoint returned an empty response. `WidgetFetcher`
  surfaces a loud-empty warning in the output channel — inspect it
  before assuming the widget is broken.
- Provider health degraded. `GET /pi/health/providers` will show which
  provider is red; often a missing API key (`OpenBB: Set API Key`).

### Hover shows nothing on a ticker string

The hover regex is intentionally strict:

- Quoted string of **exactly 2–5 uppercase letters**.
- Optional `:<venue>` suffix (`"NVDA:NASDAQ"`).
- Bare identifiers, single letters, ≥6-char runs, and
  lower/mixed-case tokens are rejected on purpose to avoid noise.

If your ticker is `"a"` or `"apple"`, that's the guard doing its job.

### Workspace-mode terminal or notebook won't launch

The workspace-mode integration lives under the browser-test harness.
See
[`openbb_platform/tools/browser_test_harness/docs/workspace-mode.md`](../../../openbb_platform/tools/browser_test_harness/docs/workspace-mode.md)
for the recorded playbook.

---

## 15. Advanced

- **Performance report.** `OpenBB: Show Performance Report` dumps the
  perf harness report and NFR budget check into the
  `"OpenBB Terminal"` output channel. Six NFR targets covered:
  activation, webview first-paint (fixture / live), symbol context
  propagation, back-end start, widget hot reload. Detail:
  [`docs/perf.md`](perf.md).
- **Pre-release QA matrix.** 5 layouts × 3 themes × 2 modes = 30-cell
  hand-check before shipping a release. See
  [`docs/qa-matrix.md`](qa-matrix.md).
- **Testing strategy.** Four-tier doctrine (unit, snapshot, fixture
  round-trip, `@vscode/test-electron` integration) with grep-based
  auth invariant guards. See
  [`docs/testing-strategy.md`](testing-strategy.md).

---

## References

- Product Requirements Document — [`docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md`](../../../docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md)
- ADR-#1808 back-end spawn — [`docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`](../../../docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md)
- ADR rendering model — [`docs/Specs/adr/2026-08-04-vscode-terminal-rendering-model.md`](../../../docs/Specs/adr/2026-08-04-vscode-terminal-rendering-model.md)
- ADR-#1809 webview auth — [`docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md`](../../../docs/Specs/adr/2026-08-04-vscode-terminal-webview-auth.md)
- Security posture — [`docs/security.md`](security.md)
- Theming — [`docs/theme.md`](theme.md)
- Performance — [`docs/perf.md`](perf.md)
- QA matrix — [`docs/qa-matrix.md`](qa-matrix.md)
- Testing strategy — [`docs/testing-strategy.md`](testing-strategy.md)
