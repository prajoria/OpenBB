# Changelog

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
