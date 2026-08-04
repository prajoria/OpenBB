// node:test coverage for PaperOrderHandler (#1835).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const compiledPath = path.join(
  __dirname,
  "..",
  "..",
  "out",
  "paper",
  "handler.js",
);

if (!fs.existsSync(compiledPath)) {
  test("handler.ts compiled output missing — run npm run compile", () => {
    assert.ok(fs.existsSync(compiledPath), `expected ${compiledPath} to exist`);
  });
} else {
  const { PaperOrderHandler } = require(compiledPath);

  function makeSymbolContext(symbol) {
    return { getActiveSymbol: () => symbol };
  }

  function makeOutputChannel() {
    const lines = [];
    return { appendLine: (l) => lines.push(l), lines };
  }

  function mockFetch(handler) {
    const calls = [];
    const fn = async (url, init) => {
      calls.push({ url, init });
      return handler(url, init);
    };
    fn.calls = calls;
    return fn;
  }

  function response(status, body) {
    return {
      status,
      text: async () =>
        typeof body === "string" ? body : JSON.stringify(body ?? {}),
    };
  }

  test("null active symbol → ok:false, no active symbol", async () => {
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext(null),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl: mockFetch(() => response(200, {})),
    });
    const r = await h.placeOrder("BUY");
    assert.equal(r.ok, false);
    assert.match(r.message, /no active symbol/i);
  });

  test("confirmation shown when confirmByDefault=true", async () => {
    const prompts = [];
    const fetchImpl = mockFetch(() => response(200, {}));
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: true,
      fetchImpl,
      confirmImpl: async (msg) => {
        prompts.push(msg);
        return "Yes";
      },
    });
    const r = await h.placeOrder("BUY");
    assert.equal(prompts.length, 1);
    assert.match(prompts[0], /PAPER BUY.*MSFT/);
    assert.equal(r.ok, true);
  });

  test("confirmation NOT shown when confirmByDefault=false", async () => {
    const prompts = [];
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl: mockFetch(() => response(200, {})),
      confirmImpl: async (msg) => {
        prompts.push(msg);
        return "Yes";
      },
    });
    const r = await h.placeOrder("BUY");
    assert.equal(prompts.length, 0);
    assert.equal(r.ok, true);
  });

  test("user cancels → ok:false with /cancelled/", async () => {
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: true,
      fetchImpl: mockFetch(() => response(200, {})),
      confirmImpl: async () => undefined,
    });
    const r = await h.placeOrder("BUY");
    assert.equal(r.ok, false);
    assert.match(r.message, /cancelled/i);
  });

  test("successful POST returns ok, no Authorization header", async () => {
    const fetchImpl = mockFetch(() => response(201, { id: "abc" }));
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl,
    });
    const r = await h.placeOrder("BUY");
    assert.equal(r.ok, true);
    assert.match(r.message, /accepted for MSFT/);
    const init = fetchImpl.calls[0].init || {};
    const headers = init.headers || {};
    const keys = Object.keys(headers).map((k) => k.toLowerCase());
    assert.ok(!keys.includes("authorization"), "no Authorization header");
    assert.equal(init.method, "POST");
    const body = JSON.parse(init.body);
    assert.equal(body.symbol, "MSFT");
    assert.equal(body.side, "BUY");
    assert.equal(body.quantity, 1);
    assert.equal(body.orderType, "MARKET");
  });

  test("404 returns ok:false with local-record message", async () => {
    const fetchImpl = mockFetch(() => response(404, "not found"));
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("AAPL"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl,
    });
    const r = await h.placeOrder("SELL");
    assert.equal(r.ok, false);
    assert.match(r.message, /not available in the running backend/i);
    assert.match(r.message, /recorded locally/i);
    assert.match(r.message, /"symbol":"AAPL"/);
    assert.match(r.message, /"side":"SELL"/);
  });

  test("request URL matches apiBase + endpoint path", async () => {
    const fetchImpl = mockFetch(() => response(200, {}));
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl,
    });
    await h.placeOrder("BUY");
    assert.equal(
      fetchImpl.calls[0].url,
      "http://127.0.0.1:6900/api/v1/portfolio_intel/paper/order",
    );
  });

  test("no token query param in URL", async () => {
    const fetchImpl = mockFetch(() => response(200, {}));
    const h = new PaperOrderHandler({
      apiBase: "http://127.0.0.1:6900",
      symbolContext: makeSymbolContext("MSFT"),
      outputChannel: makeOutputChannel(),
      confirmByDefault: false,
      fetchImpl,
    });
    await h.placeOrder("BUY");
    assert.ok(
      !fetchImpl.calls[0].url.includes("token="),
      "no token query param",
    );
  });
}
