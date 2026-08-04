// Smoke test for the placeholder CSP shape (#1814).
//
// The real computeCsp lives in ./panel.ts, which imports the `vscode`
// module — unavailable outside the extension host. This test therefore
// duplicates the tiny string-generation logic and asserts the shape
// contract (nonce embedded, no unsafe-eval, no unsafe-inline in
// script-src). Full CSP coverage lands with the hardening work in
// #1817.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const API_BASE = "http://127.0.0.1:6900";
const WS_BASE = "ws://127.0.0.1:6900";

function computeCsp(nonce) {
  return (
    `default-src 'none'; ` +
    `script-src 'nonce-${nonce}'; ` +
    `style-src 'nonce-${nonce}' 'unsafe-inline'; ` +
    `connect-src ${API_BASE} ${WS_BASE}; ` +
    `img-src 'self' data:;`
  );
}

test("computeCsp embeds the per-panel nonce", () => {
  const csp = computeCsp("abc123");
  assert.match(csp, /'nonce-abc123'/);
});

test("computeCsp forbids unsafe-eval anywhere", () => {
  const csp = computeCsp("n");
  assert.ok(!csp.includes("unsafe-eval"), "CSP must not allow unsafe-eval");
});

test("computeCsp forbids unsafe-inline in script-src", () => {
  const csp = computeCsp("n");
  const scriptSrc = csp
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith("script-src "));
  assert.ok(scriptSrc, "script-src directive present");
  assert.ok(
    !scriptSrc.includes("unsafe-inline"),
    "script-src must not allow unsafe-inline",
  );
});

test("computeCsp restricts connect-src to loopback API + WS", () => {
  const csp = computeCsp("n");
  assert.ok(csp.includes("connect-src http://127.0.0.1:6900 ws://127.0.0.1:6900"));
});
