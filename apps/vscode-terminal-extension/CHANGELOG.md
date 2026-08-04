# Changelog

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
