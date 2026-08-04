// Editor selection CodeAction tests (#1827). node:test, no vscode host.

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "editor",
  "codeAction.js",
);

function fakeDoc(text) {
  return { getText: () => text };
}

if (!fs.existsSync(compiledPath)) {
  test("codeAction.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath}`);
  });
} else {
  const Module = require("node:module");
  const origResolve = Module._resolveFilename;
  const fakeVscodePath = path.join(__dirname, "__vscode_stub_ca.js");
  fs.writeFileSync(
    fakeVscodePath,
    `module.exports = {
      CodeActionTriggerKind: { Invoke: 1, Automatic: 2 },
      CodeActionKind: { RefactorRewrite: { value: "refactor.rewrite" } },
      CodeAction: class { constructor(title, kind) { this.title = title; this.kind = kind; } },
      languages: { registerCodeActionsProvider() { return { dispose() {} }; } },
    };`,
  );
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") return fakeVscodePath;
    return origResolve.call(this, request, parent, ...rest);
  };
  const { TickerSelectionActionProvider, matchTicker } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const provider = new TickerSelectionActionProvider();
  const INVOKE = { triggerKind: 1 };
  const AUTO = { triggerKind: 2 };

  test("AAPL → 1 CodeAction with arguments: ['AAPL']", () => {
    const result = provider.provideCodeActions(fakeDoc("AAPL"), {}, INVOKE);
    assert.equal(result.length, 1);
    assert.deepEqual(result[0].command.arguments, ["AAPL"]);
    assert.equal(result[0].command.command, "openbb.openSymbolInTerminal");
    assert.equal(result[0].title, "Open AAPL in OpenBB Terminal");
  });

  test("NVDA:NASDAQ → matches with EXCHANGE suffix", () => {
    const result = provider.provideCodeActions(
      fakeDoc("NVDA:NASDAQ"),
      {},
      INVOKE,
    );
    assert.equal(result.length, 1);
    assert.deepEqual(result[0].command.arguments, ["NVDA:NASDAQ"]);
  });

  test("lowercase 'api' → undefined", () => {
    assert.equal(
      provider.provideCodeActions(fakeDoc("api"), {}, INVOKE),
      undefined,
    );
  });

  test("'apple' (>5 chars lowercase) → undefined", () => {
    assert.equal(
      provider.provideCodeActions(fakeDoc("apple"), {}, INVOKE),
      undefined,
    );
  });

  test("empty selection → undefined", () => {
    assert.equal(
      provider.provideCodeActions(fakeDoc(""), {}, INVOKE),
      undefined,
    );
  });

  test("whitespace-padded ' AAPL ' → trimmed match, 1 action", () => {
    const result = provider.provideCodeActions(fakeDoc(" AAPL "), {}, INVOKE);
    assert.equal(result.length, 1);
    assert.deepEqual(result[0].command.arguments, ["AAPL"]);
  });

  test("Automatic trigger → undefined (only Invoke)", () => {
    assert.equal(
      provider.provideCodeActions(fakeDoc("AAPL"), {}, AUTO),
      undefined,
    );
  });

  test("matchTicker helper: TSLA ok, 123 bad", () => {
    assert.equal(matchTicker("TSLA"), "TSLA");
    assert.equal(matchTicker("123"), undefined);
    assert.equal(matchTicker(""), undefined);
    assert.equal(matchTicker("  MSFT  "), "MSFT");
  });
}
