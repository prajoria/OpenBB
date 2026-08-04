import { test } from "node:test";
import assert from "node:assert/strict";
import { CORE_TOKEN_MAP, DARK_FALLBACK } from "./tokens";

test("CORE_TOKEN_MAP has exactly 10 pairs", () => {
  assert.equal(CORE_TOKEN_MAP.length, 10);
});

test("every CORE_TOKEN_MAP entry is a pair of non-empty CSS custom properties", () => {
  for (const pair of CORE_TOKEN_MAP) {
    assert.equal(pair.length, 2);
    const [target, source] = pair;
    assert.equal(typeof target, "string");
    assert.equal(typeof source, "string");
    assert.ok(target.length > 0, `target key empty: ${JSON.stringify(pair)}`);
    assert.ok(source.length > 0, `source key empty: ${JSON.stringify(pair)}`);
    assert.ok(target.startsWith("--"), `target must start with --: ${target}`);
    assert.ok(source.startsWith("--"), `source must start with --: ${source}`);
  }
});

test("DARK_FALLBACK covers every --color-* key from CORE_TOKEN_MAP", () => {
  for (const [target] of CORE_TOKEN_MAP) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(DARK_FALLBACK, target),
      `DARK_FALLBACK missing key: ${target}`,
    );
    const value = DARK_FALLBACK[target];
    assert.equal(typeof value, "string");
    assert.ok(value.length > 0, `DARK_FALLBACK[${target}] is empty`);
  }
});
