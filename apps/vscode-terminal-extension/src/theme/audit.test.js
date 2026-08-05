const { test } = require("node:test");
const assert = require("node:assert/strict");
const {
  DARK_FALLBACK,
  LIGHT_FALLBACK,
  HIGH_CONTRAST_FALLBACK,
} = require("../../out/theme/tokens");
const { auditTheme, contrastRatio } = require("../../out/theme/audit");

test("valid DARK_FALLBACK -> no missing / no warnings", () => {
  const r = auditTheme(DARK_FALLBACK, "dark");
  assert.equal(r.kind, "dark");
  assert.deepEqual(r.missingTokens, []);
  assert.deepEqual(r.contrastWarnings, []);
});
test("valid LIGHT_FALLBACK -> no missing / no warnings", () => {
  const r = auditTheme(LIGHT_FALLBACK, "light");
  assert.deepEqual(r.missingTokens, []);
  assert.deepEqual(r.contrastWarnings, []);
});
test("valid HIGH_CONTRAST_FALLBACK -> no missing / no warnings", () => {
  const r = auditTheme(HIGH_CONTRAST_FALLBACK, "high-contrast");
  assert.deepEqual(r.missingTokens, []);
  assert.deepEqual(r.contrastWarnings, []);
});
test("empty --color-primary flagged in missingTokens", () => {
  const r = auditTheme({ ...DARK_FALLBACK, "--color-primary": "" }, "dark");
  assert.ok(r.missingTokens.includes("--color-primary"));
});
test("fg=#000 on bg=#101010 -> contrast warning (<4.5:1)", () => {
  const r = auditTheme(
    {
      ...DARK_FALLBACK,
      "--color-foreground": "#000000",
      "--color-background": "#101010",
    },
    "dark",
  );
  assert.equal(r.contrastWarnings.length, 1);
  assert.match(r.contrastWarnings[0], /below WCAG AA/);
});
test("fg=#000 on bg=#fff -> no contrast warning", () => {
  const r = auditTheme(
    {
      ...LIGHT_FALLBACK,
      "--color-foreground": "#000000",
      "--color-background": "#ffffff",
    },
    "light",
  );
  assert.deepEqual(r.contrastWarnings, []);
});
test("contrastRatio black/white ~= 21", () => {
  const r = contrastRatio("#000000", "#ffffff");
  assert.ok(r && r > 20.9 && r < 21.1);
});
test("contrastRatio returns null on unparseable hex", () => {
  assert.equal(contrastRatio("not-a-color", "#ffffff"), null);
});
