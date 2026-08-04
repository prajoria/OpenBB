# Changelog

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
