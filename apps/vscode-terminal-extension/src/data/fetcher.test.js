// node:test coverage for WidgetFetcher (#1820).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { WidgetFetcher } = require("../../out/data/fetcher.js");

function mockFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init);
  };
  fn.calls = calls;
  return fn;
}

function jsonResponse(status, body) {
  return {
    status,
    json: async () => body,
  };
}

test("URL is built from apiBase + endpoint + params", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(200, { ok: true }));
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  await f.fetchWidget("/api/v1/equity/price/quote", { symbol: "MSFT" });
  assert.equal(fetchImpl.calls[0].url, "http://127.0.0.1:6900/api/v1/equity/price/quote?symbol=MSFT");
});

test("no Authorization header is set", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(200, {}));
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  await f.fetchWidget("/x");
  const init = fetchImpl.calls[0].init || {};
  const headers = init.headers || {};
  const keys = Object.keys(headers).map((k) => k.toLowerCase());
  assert.ok(!keys.includes("authorization"), "Authorization header must not be set");
});

test("no token query param is added", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(200, {}));
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  await f.fetchWidget("/x", { symbol: "AAPL" });
  assert.ok(!fetchImpl.calls[0].url.includes("token="), "no token query param");
});

test("200 JSON returns data", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(200, { results: [1, 2, 3] }));
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  const r = await f.fetchWidget("/x");
  assert.equal(r.status, 200);
  assert.deepEqual(r.data, { results: [1, 2, 3] });
  assert.equal(r.error, undefined);
});

test("500 status returns error", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(500, null));
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  const r = await f.fetchWidget("/x");
  assert.equal(r.status, 500);
  assert.equal(r.data, null);
  assert.match(r.error || "", /HTTP 500/);
});

test("thrown fetch (timeout) returns error result", async () => {
  const fetchImpl = async () => {
    throw new Error("timeout");
  };
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl });
  const r = await f.fetchWidget("/x");
  assert.equal(r.status, 0);
  assert.match(r.error || "", /timeout/);
});

test("empty array triggers loud-empty warning via outputChannel", async () => {
  const fetchImpl = mockFetch(() => jsonResponse(200, []));
  const lines = [];
  const outputChannel = { appendLine: (l) => lines.push(l) };
  const f = new WidgetFetcher({ apiBase: "http://127.0.0.1:6900", fetchImpl, outputChannel });
  await f.fetchWidget("/api/v1/equity/movers");
  assert.ok(lines.some((l) => /empty response/.test(l)), "loud-empty warning must be logged");
});
