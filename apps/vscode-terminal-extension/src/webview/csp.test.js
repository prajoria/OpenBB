// CSP builder tests (#1817).
//
// Runs under `node --test` from package.json. The csp module is pure
// TypeScript with no vscode imports, so we require the compiled JS
// from ../../out after `npm run compile`.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { buildCsp, generateNonce } = require("../../out/webview/csp");

const NONCE = "abc123XYZ";

function directive(csp, name) {
  return csp
    .split(";")
    .map((s) => s.trim())
    .find((s) => s.startsWith(name + " "));
}

test("buildCsp contains default-src 'none'", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(csp.includes("default-src 'none'"));
});

test("buildCsp embeds the per-panel nonce in script-src", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(csp.includes(`script-src 'nonce-${NONCE}'`));
});

test("buildCsp allows unsafe-inline in style-src (chart libs)", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(csp.includes(`style-src 'nonce-${NONCE}' 'unsafe-inline'`));
});

test("buildCsp connect-src lists api + ws for http apiBase", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(csp.includes("connect-src http://127.0.0.1:6900 ws://127.0.0.1:6900"));
});

test("buildCsp forbids unsafe-eval anywhere", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(!csp.includes("unsafe-eval"));
});

test("buildCsp has no wildcard in script-src or connect-src", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  const script = directive(csp, "script-src");
  const connect = directive(csp, "connect-src");
  assert.ok(script && !script.includes("*"), "script-src wildcard forbidden");
  assert.ok(connect && !connect.includes("*"), "connect-src wildcard forbidden");
});

test("buildCsp forbids blob:, filesystem:, chrome-extension: schemes", () => {
  const csp = buildCsp({ apiBase: "http://127.0.0.1:6900", nonce: NONCE });
  assert.ok(!csp.includes("blob:"));
  assert.ok(!csp.includes("filesystem:"));
  assert.ok(!csp.includes("chrome-extension:"));
});

test("generateNonce returns >=32 chars and differs between calls", () => {
  const a = generateNonce();
  const b = generateNonce();
  assert.ok(a.length >= 32, `nonce too short: ${a.length}`);
  assert.notStrictEqual(a, b);
});
