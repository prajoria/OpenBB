// Webview HTML snapshot tests (#1840, tier 2).
//
// Renders the terminal + preview panel HTML with a fixed nonce so the
// output is deterministic, and diffs against checked-in snapshots.
// Set UPDATE_SNAPSHOTS=1 to regenerate.
//
// The terminal panel's `renderHtml` is not exported (it captures a
// vscode WebviewPanel), so this file duplicates the template shape
// verbatim using the exported `buildCsp` helper. If panel.ts's template
// drifts, this test drifts with it and the snapshot must be updated.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

// preview/panel.ts imports `vscode` (only for type + Uri.joinPath at
// runtime paths we don't exercise here). Register an in-memory stub
// before requiring so the snapshot test can run outside the extension
// host.
const _origResolve = Module._resolveFilename;
const _origLoad = Module._load;
Module._load = function (request, ...rest) {
  if (request === "vscode") return {};
  return _origLoad.call(this, request, ...rest);
};
Module._resolveFilename = function (request, ...rest) {
  if (request === "vscode") return "vscode";
  return _origResolve.call(this, request, ...rest);
};

const csp = require("../../out/webview/csp.js");
const preview = require("../../out/preview/panel.js");

const SNAPSHOT_DIR = path.join(__dirname, "snapshots");
const API_BASE = "http://127.0.0.1:6900";
const FIXED_NONCE = "TEST_NONCE_00000000000000000000000000";

function terminalHtml(nonce, mediaUri) {
  const cspStr = csp.buildCsp({ apiBase: API_BASE, nonce });
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy" content="${cspStr}" />
  <title>OpenBB Terminal</title>
  <script nonce="${nonce}">
    window.__OPENBB_API_BASE__ = "${API_BASE}";
  </script>
</head>
<body>
  <div>Webview host ready — canvas mounted in #1816</div>
  <div id="root"></div>
  <script nonce="${nonce}" src="${mediaUri}/canvas.js"></script>
</body>
</html>`;
}

function unifiedDiff(expected, actual) {
  const a = expected.split("\n");
  const b = actual.split("\n");
  const lines = ["--- expected", "+++ actual"];
  const max = Math.max(a.length, b.length);
  for (let i = 0; i < max; i++) {
    if (a[i] !== b[i]) {
      if (a[i] !== undefined) lines.push(`-${i + 1}: ${a[i]}`);
      if (b[i] !== undefined) lines.push(`+${i + 1}: ${b[i]}`);
    }
  }
  return lines.join("\n");
}

function normalizeLineEndings(value) {
  return value.replace(/\r\n?/g, "\n");
}

function assertSnapshot(name, actual) {
  const p = path.join(SNAPSHOT_DIR, name);
  const normalizedActual = normalizeLineEndings(actual);
  if (process.env.UPDATE_SNAPSHOTS === "1") {
    fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });
    fs.writeFileSync(p, normalizedActual, "utf8");
    return;
  }
  const expected = normalizeLineEndings(fs.readFileSync(p, "utf8"));
  if (expected !== normalizedActual) {
    // eslint-disable-next-line no-console
    console.error(unifiedDiff(expected, normalizedActual));
    assert.equal(normalizedActual, expected, `snapshot mismatch: ${name}`);
  }
}

test("terminal panel HTML matches snapshot", () => {
  const html = terminalHtml(FIXED_NONCE, "vscode-webview://media");
  assertSnapshot("terminal-panel.html", html);
});

test("preview panel HTML matches snapshot", () => {
  const widgetMeta = {
    id: "pi_portfolio_summary",
    name: "Portfolio Summary",
    type: "metric",
    endpoint: "/pi/portfolio/summary",
    category: "Portfolio Overview",
  };
  const html = preview.buildPreviewHtml(
    widgetMeta,
    FIXED_NONCE,
    "vscode-webview:",
    API_BASE,
    "vscode-webview://media/renderer.js",
    "vscode-webview://media/preview.js",
  );
  assertSnapshot("preview-panel.html", html);
});
