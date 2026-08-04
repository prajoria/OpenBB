// Unit tests for command palette registrations (#1822).

const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "commands",
  "register.js",
);

function makeFakeVscode() {
  const registered = [];
  const infoMessages = [];
  const warnMessages = [];
  let nextInput;
  return {
    api: {
      commands: {
        registerCommand(id, handler) {
          registered.push({ id, handler });
          return { dispose() {} };
        },
      },
      window: {
        async showInputBox() {
          return nextInput;
        },
        async showInformationMessage(msg) {
          infoMessages.push(msg);
          return undefined;
        },
        async showWarningMessage(msg) {
          warnMessages.push(msg);
          return undefined;
        },
      },
    },
    registered,
    infoMessages,
    warnMessages,
    setNextInput(v) {
      nextInput = v;
    },
  };
}

function makeFakeContext() {
  return { subscriptions: [] };
}

if (!fs.existsSync(compiledPath)) {
  test("register.ts compiled output missing — run npm run compile", () => {
    assert.ok(
      fs.existsSync(compiledPath),
      `expected ${compiledPath} to exist`,
    );
  });
} else {
  const Module = require("node:module");
  const origResolve = Module._resolveFilename;
  const fakePanelPath = path.join(__dirname, "__panel_stub.js");
  const fakeVscodePath = path.join(__dirname, "__vscode_stub.js");
  fs.writeFileSync(
    fakePanelPath,
    "module.exports.openTerminalPanel = function(){ return {}; };",
  );
  fs.writeFileSync(fakeVscodePath, "module.exports = {};");
  Module._resolveFilename = function (request, parent, ...rest) {
    if (request === "vscode") {
      return fakeVscodePath;
    }
    if (
      parent &&
      parent.filename === compiledPath &&
      request === "../webview/panel"
    ) {
      return fakePanelPath;
    }
    return origResolve.call(this, request, parent, ...rest);
  };
  const { registerCommands } = require(compiledPath);
  Module._resolveFilename = origResolve;

  const EXPECTED_IDS = [
    "openbb.newLayout",
    "openbb.openSymbolInTerminal",
    "openbb.openPortfolio",
    "openbb.openTradingDesk",
    "openbb.openRisk",
    "openbb.openChart",
    "openbb.setApiKey",
    "openbb.previewWidget",
    "openbb.paperBuyActive",
    "openbb.paperSellActive",
    "openbb.runAnalysis",
    "openbb.exportLayout",
    "openbb.importLayout",
    "openbb.renameLayout",
    "openbb.duplicateLayout",
    "openbb.deleteLayout",
  ];

  test("registerCommands registers exactly 16 commands", () => {
    const fake = makeFakeVscode();
    const ctx = makeFakeContext();
    const disposables = registerCommands(ctx, fake.api);
    assert.equal(disposables.length, 16);
    assert.equal(fake.registered.length, 16);
    assert.equal(ctx.subscriptions.length, 16);
  });

  test("registers the PRD §12.1 command IDs", () => {
    const fake = makeFakeVscode();
    registerCommands(makeFakeContext(), fake.api);
    const ids = fake.registered.map((r) => r.id).sort();
    assert.deepEqual(ids, [...EXPECTED_IDS].sort());
  });

  test("does not register backend-lifecycle commands (owned by #1819)", () => {
    const fake = makeFakeVscode();
    registerCommands(makeFakeContext(), fake.api);
    const ids = fake.registered.map((r) => r.id);
    for (const forbidden of [
      "openbb.startBackend",
      "openbb.stopBackend",
      "openbb.restartBackend",
      "openbb.openBackendLogs",
    ]) {
      assert.ok(!ids.includes(forbidden), `must not register ${forbidden}`);
    }
  });

  test("openSymbolInTerminal rejects invalid symbol via warning", async () => {
    const fake = makeFakeVscode();
    registerCommands(makeFakeContext(), fake.api);
    const cmd = fake.registered.find(
      (r) => r.id === "openbb.openSymbolInTerminal",
    );
    fake.setNextInput("not-a-symbol");
    await cmd.handler();
    assert.equal(fake.warnMessages.length, 1);
    assert.match(fake.warnMessages[0], /Invalid symbol/);
  });

  test("openSymbolInTerminal accepts a valid symbol", async () => {
    const fake = makeFakeVscode();
    registerCommands(makeFakeContext(), fake.api);
    const cmd = fake.registered.find(
      (r) => r.id === "openbb.openSymbolInTerminal",
    );
    fake.setNextInput("AAPL");
    await cmd.handler();
    assert.equal(fake.warnMessages.length, 0);
  });

  test("newLayout without a layoutManager warns", async () => {
    const fake = makeFakeVscode();
    registerCommands(makeFakeContext(), fake.api);
    const cmd = fake.registered.find((r) => r.id === "openbb.newLayout");
    fake.setNextInput("MyLayout");
    await cmd.handler();
    assert.equal(fake.warnMessages.length, 1);
    assert.match(fake.warnMessages[0], /Layout manager not wired/);
  });
}
