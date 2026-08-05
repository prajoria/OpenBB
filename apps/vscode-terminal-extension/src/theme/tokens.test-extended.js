const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  CORE_TOKEN_MAP,
  DARK_FALLBACK,
  LIGHT_FALLBACK,
  HIGH_CONTRAST_FALLBACK,
  getFallbackForTheme,
} = require("../../out/theme/tokens");

function assertCoversMap(name, palette) {
  for (const [target] of CORE_TOKEN_MAP) {
    assert.ok(
      Object.prototype.hasOwnProperty.call(palette, target),
      name + " missing " + target,
    );
    const value = palette[target];
    assert.equal(typeof value, "string");
    assert.ok(value.trim().length > 0, name + "[" + target + "] empty");
  }
}

test("LIGHT_FALLBACK covers every CORE_TOKEN_MAP key", () => {
  assertCoversMap("LIGHT_FALLBACK", LIGHT_FALLBACK);
});
test("HIGH_CONTRAST_FALLBACK covers every CORE_TOKEN_MAP key", () => {
  assertCoversMap("HIGH_CONTRAST_FALLBACK", HIGH_CONTRAST_FALLBACK);
});
test("getFallbackForTheme('dark') returns DARK_FALLBACK", () => {
  assert.deepEqual(getFallbackForTheme("dark"), DARK_FALLBACK);
});
test("getFallbackForTheme('light') returns LIGHT_FALLBACK", () => {
  assert.deepEqual(getFallbackForTheme("light"), LIGHT_FALLBACK);
});
test("getFallbackForTheme('high-contrast') returns HIGH_CONTRAST_FALLBACK", () => {
  assert.deepEqual(getFallbackForTheme("high-contrast"), HIGH_CONTRAST_FALLBACK);
});
test("getFallbackForTheme returns fresh objects", () => {
  const p = getFallbackForTheme("dark");
  p["--color-background"] = "#deadbe";
  assert.notEqual(DARK_FALLBACK["--color-background"], "#deadbe");
});
