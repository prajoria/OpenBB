// Unit tests for the preview panel HTML template (#1832).
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(__dirname, "..", "..", "out", "preview", "panel.js");

if (!fs.existsSync(compiledPath)) {
  test("preview/panel.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath} to exist`);
  });
} else {
  const Module = require("node:module");
  const origResolve = Module._resolveFilename;
  const fakeVscodePath = path.join(__dirname, "..", "commands", "__vscode_stub.js");
  if (!fs.existsSync(fakeVscodePath)) {
    fs.writeFileSync(fakeVscodePath, "module.exports = {};");
  }
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") return fakeVscodePath;
    return origResolve.call(this, request, parent, ...rest);
  };
  const { buildPreviewHtml } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const sampleWidget = {
    id: "pi_portfolio_summary",
    name: "Portfolio Summary",
    type: "metric",
    endpoint: "/pi/portfolio/summary",
    category: "Portfolio Overview",
  };
  const NONCE = "abc123XYZ";
  const CSP_SOURCE = "vscode-webview://sample";
  const API_BASE = "http://127.0.0.1:6900";
  const RENDERER = "vscode-webview://sample/media/renderer.js";
  const PREVIEW = "vscode-webview://sample/media/preview.js";

  test("HTML embeds the widget name (interpolated + escaped)", () => {
    const html = buildPreviewHtml(sampleWidget, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    assert.ok(html.includes("Portfolio Summary"));
  });

  test("HTML injects window.__OPENBB_PREVIEW_WIDGET__ with widget JSON", () => {
    const html = buildPreviewHtml(sampleWidget, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    assert.match(html, /window\.__OPENBB_PREVIEW_WIDGET__\s*=\s*JSON\.parse\(/);
    assert.ok(html.includes("pi_portfolio_summary"));
    assert.ok(html.includes("/pi/portfolio/summary"));
  });

  test("CSP connect-src derives from apiBase (matches main panel shape)", () => {
    const html = buildPreviewHtml(sampleWidget, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    assert.ok(html.includes("connect-src http://127.0.0.1:6900 ws://127.0.0.1:6900"));
  });

  test("Every <script> tag carries the nonce", () => {
    const html = buildPreviewHtml(sampleWidget, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    const scriptTags = html.match(/<script[^>]*>/g) || [];
    assert.ok(scriptTags.length >= 3, "expected at least 3 script tags");
    for (const tag of scriptTags) {
      assert.ok(tag.includes(`nonce="${NONCE}"`), `missing nonce on: ${tag}`);
    }
  });

  test("Title matches Preview: name", () => {
    const html = buildPreviewHtml(sampleWidget, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    assert.match(html, /<title>Preview: Portfolio Summary<\/title>/);
  });

  test("HTML escapes <, >, quotes in widget name", () => {
    const evil = { ...sampleWidget, name: '<img>"AAPL' };
    const html = buildPreviewHtml(evil, NONCE, CSP_SOURCE, API_BASE, RENDERER, PREVIEW);
    assert.ok(!html.includes('<img>"AAPL'), "raw payload must not appear");
    assert.ok(html.includes("&lt;img&gt;"));
    assert.ok(html.includes("&quot;AAPL"));
    assert.match(html, /<title>Preview: &lt;img&gt;&quot;AAPL<\/title>/);
  });
}
