// SymbolValidator tests (#1823). Runs under `node --test`. Requires
// the compiled JS from ../../out after `npm run compile`.

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { SymbolValidator } = require("../../out/symbol/validator");

function makeFetch(handler) {
  const calls = { count: 0, urls: [] };
  const fn = async (url) => {
    calls.count++;
    calls.urls.push(url);
    return handler(url, calls.count);
  };
  return { fn, calls };
}

function jsonResp(body, status = 200) {
  return {
    status,
    async json() {
      return body;
    },
  };
}

test("rejects invalid syntax without network", async () => {
  const { fn, calls } = makeFetch(() => jsonResp({ results: [{ x: 1 }] }));
  const v = new SymbolValidator({ apiBase: "http://x", fetchImpl: fn, debounceMs: 0 });
  for (const bad of ["abc", "1234", "TOOLONG", "A B"]) {
    const r = await v.validate(bad);
    assert.equal(r.accepted, false);
    assert.equal(r.reason, "invalid syntax");
  }
  assert.equal(calls.count, 0);
});

test("fresh symbol fetched then served from cache", async () => {
  const { fn, calls } = makeFetch(() => jsonResp({ results: [{ symbol: "AAPL" }] }));
  const v = new SymbolValidator({ apiBase: "http://x", fetchImpl: fn, debounceMs: 0 });
  const a = await v.validate("AAPL");
  assert.equal(a.accepted, true);
  const b = await v.validate("AAPL");
  assert.equal(b.accepted, true);
  assert.equal(calls.count, 1);
});

test("TTL expiry re-fetches", async () => {
  const { fn, calls } = makeFetch(() => jsonResp({ results: [{ x: 1 }] }));
  const v = new SymbolValidator({
    apiBase: "http://x",
    fetchImpl: fn,
    debounceMs: 0,
    ttlMs: 1,
  });
  await v.validate("AAPL");
  await new Promise((r) => setTimeout(r, 5));
  await v.validate("AAPL");
  assert.equal(calls.count, 2);
});

test("500 error not cached", async () => {
  let count = 0;
  const fn = async () => {
    count++;
    return jsonResp({}, 500);
  };
  const v = new SymbolValidator({ apiBase: "http://x", fetchImpl: fn, debounceMs: 0 });
  const a = await v.validate("AAPL");
  assert.equal(a.accepted, false);
  assert.equal(a.reason, "validator unreachable");
  const b = await v.validate("AAPL");
  assert.equal(b.accepted, false);
  assert.equal(count, 2);
});

test("debounce coalesces two concurrent validate('AAPL') into ONE fetch", async () => {
  const { fn, calls } = makeFetch(() => jsonResp({ results: [{ x: 1 }] }));
  const v = new SymbolValidator({
    apiBase: "http://x",
    fetchImpl: fn,
    debounceMs: 20,
  });
  const [a, b] = await Promise.all([v.validate("AAPL"), v.validate("AAPL")]);
  assert.equal(a.accepted, true);
  assert.equal(b.accepted, true);
  assert.equal(calls.count, 1);
});

test("empty results -> no matches (cached)", async () => {
  let count = 0;
  const fn = async () => {
    count++;
    return jsonResp({ results: [] });
  };
  const v = new SymbolValidator({ apiBase: "http://x", fetchImpl: fn, debounceMs: 0 });
  const a = await v.validate("ZZZZZ");
  assert.equal(a.accepted, false);
  assert.equal(a.reason, "no matches");
  await v.validate("ZZZZZ");
  assert.equal(count, 1);
});
