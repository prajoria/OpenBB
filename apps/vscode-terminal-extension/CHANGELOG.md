# Changelog

## 0.0.27 - Light + high-contrast theme parity + audit (#1837)

- Add LIGHT_FALLBACK and HIGH_CONTRAST_FALLBACK alongside DARK_FALLBACK in src/theme/tokens.ts, plus ThemeKind union and getFallbackForTheme selector.
- src/theme/bridge.ts: detectThemeKind() maps VS Code active theme (Dark/Light/HighContrast/HighContrastLight) to ThemeKind, folding both HC variants into high-contrast. collectThemeTokens(kind?) accepts an override; registerThemeSync now posts (tokens, kind).
- media/theme.js: tags <html data-openbb-theme="{kind}"> on every apply. Posts themeReady back to the host on boot.
- New src/theme/audit.ts: auditTheme(tokens, kind) returns { kind, missingTokens, contrastWarnings } with WCAG-AA 4.5:1 checks via relative-luminance.
- Tests: src/theme/tokens.test-extended.js and src/theme/audit.test.js.
- Docs: docs/theme.md rewritten around the 3-way fallback, data-openbb-theme, and the audit helper.

## 0.0.26 - Paper buy/sell command handlers wired (#1835)

- `PaperOrderHandler` (`src/paper/handler.ts`) wires the paper buy/sell
  keybindings (Ctrl+Alt+B / Ctrl+Alt+S) to a POST against
  `/api/v1/portfolio_intel/paper/order` on the loopback backend.
- Follows ADR-#1809: no `Authorization` header, no `?token=` query.
- Modal confirmation by default before any order goes out.
- 404 from the backend degrades gracefully into a "recorded locally"
  warning so the hotkeys stay useful while the backend endpoint rolls
  out.
- `registerCommands` gains an optional `paperOrderHandler` parameter;
  `extension.ts` wires the singleton after `SymbolContext` construction.

## 0.0.24 - Widget Browser tree-view + drag support (#1830)

- `WidgetBrowserTreeProvider` with prefix grouping (`pi_*` / `tt_*` /
  `portfolio_*` / `regime_*` / `other`).
- Drag source publishing `application/vnd.code.tree.openbb-widget` MIME
  for layout drop targets.
- Inline `openbb.previewWidgetFromBrowser` + `openbb.addWidgetToActiveLayout`
  placeholder commands wired via `view/item/context` menu.
- Node:test coverage of prefix ordering, alphabetical sort, unknown-prefix
  bucketing, empty manifest, refresh event.

## 0.0.23 - Preview widget command (single-widget panel) (#1832)

- Add `src/preview/panel.ts` — `openPreviewPanel(context, widgetMeta)`
  opens a `ViewColumn.Beside` webview titled `Preview: ${name}`. Reuses
  `buildCsp` + `generateNonce` from `src/webview/csp.ts` so the same
  hardened CSP applies (no bearer, no `?token=`). Injects
  `window.__OPENBB_PREVIEW_WIDGET__` as a nonce-tagged inline script.
- Add `media/preview.js` — 24-line vanilla bootstrap that reads
  `window.__OPENBB_PREVIEW_WIDGET__` and calls the Path-A renderer's
  `renderWidget` in FIXTURE mode.
- Replace `openbb.previewWidget` placeholder in `src/commands/register.ts`
  with a real QuickPick over `getFixtureWidgetsManifest(context)`.
- Node:test coverage: name/JSON/CSP/nonce/title/XSS-escape (name with
  `<img>` and `"` correctly escaped).

## 0.0.22 - Golden layouts library + load command + reset (#1833)

- Add curated `golden_layouts/*.json`: momentum-scan, risk-review,
  single-stock-deep-dive, paper-trading-cockpit (repo-versioned,
  distinct from ephemeral user layouts in globalState).
- Add `src/golden/loader.ts` — reads + validates each JSON against
  `widgets.sample.json`; module-scope cache with `resetCache()`.
- Add `src/golden/command.ts` — `openbb.loadGoldenLayout` (quick-pick,
  deep-copies picked layout into `openbb.userLayouts` with a fresh id
  and preserved `sourceGoldenId`) and `openbb.resetToDefaultLayouts`
  (modal confirm, clears the key).
- Node:test coverage over the four goldens shape / widget refs /
  overflow / overlap and loader cache semantics.

## 0.0.18 - Symbol hover provider (Python + Notebook) (#1825)

- Add `src/hover/regex.ts` — pure ticker detection with a tightened
  regex. Two modes: assignment (`symbol = "AAPL"` / `ticker='MSFT'`)
  and quoted literal (`"NVDA"`). Rejects bare identifiers (API, URL,
  MAX, SQL, DDL), single-letter tickers, ≥6-char runs, and
  lower/mixed case.
- Add `src/hover/sparkline.ts` — compact ~200x40 SVG sparkline; green
  `#4CAF50` for positive trend, red `#F44336` otherwise; handles empty
  and flat inputs without crashing.
- Add `src/hover/provider.ts` — VS Code `HoverProvider` for Python
  source files and Python notebook cells. Validates via
  `SymbolValidator` (5-min TTL), fetches
  `GET /api/v1/equity/price/historical?symbol=…&interval=1d&limit=5`
  with NO `Authorization` header and NO `?token=` parameter, renders a
  MarkdownString with header + sparkline data-URI + trusted command
  link to `openbb.openSymbolInTerminal`. 5-min per-symbol cache and a
  500 ms debounce prevent redundant fetches on rapid re-hovers.
- Wire `registerSymbolHoverProvider` in `src/extension.ts`.
- Tests: `src/hover/regex.test.js`, `src/hover/sparkline.test.js`.

## 0.0.17 - Notebook symbol watcher (source-text heuristic) (#1826)

- Add `src/notebook/watcher.ts` — registers `onDidOpenNotebookDocument`
  and `onDidChangeNotebookDocument` handlers. Scans cell source text
  for `\b(?:symbol|ticker)\s*=\s*["']([A-Z]{2,5})(?::[A-Z]+)?["']`;
  when matched, calls `SymbolContext.setSymbol(..., 'notebook')`.
  Per-notebook debounce (300ms) suppresses redundant broadcasts on
  rapid edits. **SOURCE-TEXT HEURISTIC ONLY** — does NOT introspect
  Jupyter kernel runtime variable values (that would require Jupyter
  extension API / debug adapter, tracked as separate follow-up).
- Extend `SymbolContext.setSymbol` source-union to include `"notebook"`
  and `"hover"` (matching the hover-provider work in #1825).
- Tests: `src/notebook/watcher.test.js` — 6 node:test cases covering
  symbol match, ticker match, non-match, comment match (dumb-parsing
  fine), debounce coalescing, and per-notebook state.

## 0.0.16 - openbb.runAnalysis command wired to 7-phase pipeline (#1828)

- Replace the placeholder `openbb.runAnalysis` with a real handler that
  prompts for a symbol (regex-validated), verifies the target Python can
  import `stock_analysis`, and opens a fresh workspace-local Jupyter
  notebook built from a template (3 cells: title markdown, pipeline
  invocation, phase-by-phase results). Per PRD Q6, we do NOT modify the
  checked-in notebooks in `notebooks/portfolio/`.
- Add `src/analysis/runner.ts` — `AnalysisRunner` with `resolvePython`,
  `ensureAnalysisModule`, and `runForSymbol`. Uses the checked-in
  `Analysis/stock_analysis.py` pipeline.
- Add `src/analysis/runner.test.js` — 10 node:test cases with mocked
  spawn + mocked vscode.
- Wire the runner in `src/extension.ts` from the `openbb.pythonPath`
  setting and pass it to `registerCommands`.

## 0.0.15 - Editor selection ticker CodeAction (#1827)

- Add `src/editor/codeAction.ts` — `TickerSelectionActionProvider`
  offers a lightbulb "Open <SYM> in OpenBB Terminal" CodeAction when
  the user's selection matches `^[A-Z]{1,5}(:[A-Z]+)?$`. Only fires
  on explicit `Invoke` trigger (never auto-suggest) and never
  auto-broadcasts. PRD §13.1: editor selection is the lowest-priority
  symbol source and requires explicit user acceptance.
- Wire `registerSelectionCodeAction(context)` in `src/extension.ts`.
- Tests: `src/editor/codeAction.test.js`.

## 0.0.12 - Live-data mode (fixture ↔ live) (#1820)

- Add `src/data/mode.ts` — `DataModeController` flips between `fixture`
  and `live` off the backend lifecycle state (`running` -> `live`).
- Add `src/data/fetcher.ts` — `WidgetFetcher`, loopback-only HTTP GET
  client. No bearer-style auth header. No token query param. Loud-empty
  warning on empty responses.
- Add `src/data/mode-glue.ts` — attaches the controller to a webview
  panel, broadcasting `{type:"dataModeChange", mode}` on transitions.
- `media/renderer.js` — listens for `dataModeChange`, renders from
  `widget.fixtureRows` in fixture mode and fetches
  `${window.__OPENBB_API_BASE__}${widget.endpoint}` in live mode; adds
  FIXTURE/LIVE header badges and a Retry button on fetch errors.
- Wire `DataModeController` + `attachDataModeToPanel` in
  `src/extension.ts`.
- Tests: `src/data/mode.test.js`, `src/data/fetcher.test.js`.

## 0.0.11 - Complete built-in layout set (Portfolio Risk, Trading Desk, Chart Focus) (#1821)

- Add `fixtures/layouts/portfolio-risk.json` (Layout 3): sector/country
  X-Ray + concentration gauge, risk dashboard + what-if card, Brinson
  attribution, what-if diff.
- Add `fixtures/layouts/trading-desk.json` (Layout 4): segment movers +
  signal card, scan table, paper ticket + blotter, paper performance +
  KPIs.
- Add `fixtures/layouts/chart-focus.json` (Layout 5): charting, equity
  technicals + price performance, regime detect + signal card.
- Extend `fixtures/widgets.sample.json` with 17 new synthetic-data
  widgets covering every new layout slot (round numbers only, no real
  portfolio data).
- Add `src/layouts/all-layouts.test.js` (node:test): asserts exactly
  5 layouts ship, every layout validates (shape, no overflow, no
  overlap), and every referenced widgetId resolves in the manifest.

## 0.0.9 - Command palette + keybindings (#1822)

- Add `src/commands/register.ts` registering the 13 non-backend-lifecycle
  commands from PRD §12.1. Backend lifecycle commands remain owned by #1819.
- Add `src/commands/context.ts` (`registerPanelFocusContext`) binding the
  `openbb.terminalFocused` context key to the webview panel's `active`
  state via `onDidChangeViewState`.
- `package.json`: register all 13 commands under `contributes.commands`
  with `OpenBB:` title prefixes and the seven default keybindings from
  PRD §12.2 (paper buy/sell gated on `openbb.terminalFocused`; F9 open
  chart gated on `editorTextFocus && resourceLangId == python`).
- Symbol validation on `openbb.openSymbolInTerminal` enforces
  `^[A-Z]{1,5}(:[A-Z]+)?$` and warns on mismatch.
- Add `src/commands/register.test.js` (node:test) covering registration
  count, ID set, backend-lifecycle exclusion, symbol validation, and
  the newLayout placeholder message.

## 0.0.8 - Symbol context v1 + validation (#1823)

- Add `SymbolContext` (`src/symbol/context.ts`) — single source of truth
  for the active symbol across all open OpenBB Terminal panels;
  broadcasts `symbolChange` messages to registered webviews.
- Add `SymbolValidator` (`src/symbol/validator.ts`) — syntax check
  (`^[A-Z]{1,5}(:[A-Z]+)?$`) plus remote validation against
  `${apiBase}/api/v1/equity/search` with 5-minute TTL cache and
  in-flight coalescing; no `Authorization` header, no `?token=`.
- Add `registerSymbolStatusBar` (`src/symbol/statusBar.ts`) — status bar
  entry on the right showing the active symbol, click routes to
  `openbb.openSymbolInTerminal`.
- Add `attachSymbolBridge` (`src/symbol/panel-glue.ts`) — wires each
  webview panel's `symbolFromWidget` messages into the `SymbolContext`.
- Add `media/symbol.js` — vanilla-JS listener applying broadcast symbol
  changes to `[data-widget-symbol-input]` inputs; loaded via
  `<script src>` under the nonce CSP.
- Wire everything into `activate()` in `src/extension.ts` (no new
  commands, no new config keys).

## 0.0.6 - Backend lifecycle + status bar (#1819)

- Add `src/backend/state.ts` — pure reducer for the back-end lifecycle
  state machine (`stopped` → `starting` → `running`/`error` → `stopped`),
  including a two-consecutive-`HEALTH_FAILED` transition into `error`
  per ADR `2026-08-04-vscode-terminal-backend-spawn.md` §2.3.
- Add `src/backend/lifecycle.ts` — `BackendLifecycle` class: attach-mode
  short-circuit (probes `/widgets.json` before spawning), spawns
  `openbb-api --host 127.0.0.1 --port <port>` via `child_process.spawn`,
  streams stdout/stderr into the `"OpenBB Terminal"` output channel,
  polls `/widgets.json` every 2 s (60 s readiness timeout), then runs a
  10 s health monitor. Stop path uses `SIGTERM`/`SIGKILL` (POSIX) or
  `execFile("taskkill", ["/pid", …, "/F"])` (Windows) — never `exec`
  with concatenated strings.
- Add `src/backend/statusBar.ts` — left-aligned `StatusBarItem` with
  `$(circle-slash)/$(sync~spin)/$(check)/$(error)` icons per state,
  tooltip carrying `port`, `lastHealthAt`, `lastError`; click routes to
  `OpenBB: Open Back-end Logs`.
- Add `src/backend/state.test.js` (node:test) — seven reducer scenarios
  including two-fail-to-error and full restart cycle.
- `package.json`: bump to `0.0.6`; add four commands (`openbb.start/stop/
  restart/openBackendLogs`) and four settings (`openbb.pythonPath`,
  `openbb.apiPort`, `openbb.apiBaseUrl`, `openbb.autoStartBackend`).
- Auth invariants preserved (ADR §5): no bearer auth header, no token
  query parameter anywhere in the module.

## 0.0.5 - CSP hardening + auth invariant guards (#1817)

- Extract CSP directive building into `src/webview/csp.ts` (`buildCsp`
  + `generateNonce`); `panel.ts` now imports both. Removes the inlined
  CSP string and the #1817 TODO.
- CSP now enforces `default-src 'none'`, `frame-src 'none'`,
  `object-src 'none'`, `base-uri 'none'`, `font-src 'self'` in addition
  to the prior directives; `style-src` retains `'unsafe-inline'` for
  chart libraries per PRD §17.3, per-panel nonce covers `script-src`
  and inline `<script>` tags.
- Add `src/webview/csp.test.js` (node:test): default-src, nonce
  wiring, `unsafe-inline` in style-src only, connect-src
  api+ws derivation, no `unsafe-eval`, no `*` wildcard, no
  `blob:`/`filesystem:`/`chrome-extension:` schemes, nonce length +
  uniqueness.
- Add `scripts/verify-auth-invariants.sh` (wired as
  `npm run verify:invariants`): four ADR §5 grep guards — no
  `Authorization: Bearer` header, no `'unsafe-eval'`, no
  `connect-src` wildcard, no `?token=` in URLs.
- Resolves PRD §17.3 review comment #10 (CSP source of truth) in
  shipped code.

## 0.0.4 - Theme token bridge (dark) (#1815)

- Add `src/theme/tokens.ts` with `CORE_TOKEN_MAP` (10 pairs bridging
  neutral `--color-*` tokens to VS Code `--vscode-*` variables) and a
  `DARK_FALLBACK` palette using VS Code Dark+ defaults.
- Add `src/theme/bridge.ts` with `collectThemeTokens()` and
  `registerThemeSync()`, which re-posts tokens to webviews whenever
  `vscode.window.onDidChangeActiveColorTheme` fires.
- Add `media/theme.js` webview-side applier that mirrors the mapped
  `--vscode-*` values onto `--color-*` on `<html>` and listens for
  `{ type: 'themeChange' }` messages.
- Add `src/theme/tokens.test.ts` (node:test) covering map size, key
  shape, and fallback coverage.
- Document mapping + fallback in `docs/theme.md`; light + high-contrast
  follow-up tracked in #1837.

## 0.0.3 - Fixture layouts + Path-A renderer (#1816)

- Ship `fixtures/widgets.sample.json` — 11-widget subset covering the
  first two PRD §11.1 layouts (Portfolio Overview + Equity Deep-Dive).
- Ship `fixtures/layouts/portfolio-overview.json` and
  `fixtures/layouts/equity-deep-dive.json` on a 12-col grid.
- Add `src/layouts/types.ts` — pure types + `validateLayout` shape /
  overlap / overflow checker (no `vscode` import so tests can consume).
- Add `src/layouts/registry.ts` — `getBuiltinLayouts` and
  `getFixtureWidgetsManifest` load JSON at activation time via
  `vscode.Uri.joinPath` + `fs/promises`.
- Add `media/renderer.js` — Path-A vanilla-JS generic renderer keyed
  off `widget.type` (`table`, `chart`, `markdown`, `metric`, `note`);
  every interpolated value escaped.
- Add `src/layouts/registry.test.ts` (`node:test`) covering layout
  shape, widgetId coverage, and overlap / >12-col detection.

## 0.0.2 - Webview host + postMessage bridge (#1814)

- `openTerminalPanel` opens a real VS Code webview (id `openbb.terminal`),
  injects `window.__OPENBB_API_BASE__`, loads `media/canvas.js`, and wires
  the extension-host <-> webview postMessage bridge.
- Placeholder CSP with per-panel nonce; full CSP tightening deferred to
  #1817.
- `postSymbolChange` / `postThemeChange` helpers for host -> webview
  events; `onDidReceiveMessage` logs to the "OpenBB Terminal" output
  channel.

## 0.0.1 - Phase 1 scaffold (#1813)

- Initial package scaffold: `package.json`, `tsconfig.json`, activation
  entry point, three placeholder sidebar tree views, `OpenBB: Open
  Terminal` command stub, monogram icon.
