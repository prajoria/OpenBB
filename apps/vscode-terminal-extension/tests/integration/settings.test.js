// Integration: every configuration property declared in package.json is
// readable via vscode.workspace.getConfiguration.

"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const vscode = require("vscode");
const pkg = require(path.resolve(__dirname, "..", "..", "package.json"));

suite("settings declarations", () => {
  test("each declared property inspects cleanly", () => {
    const props = pkg.contributes.configuration.properties || {};
    for (const fq of Object.keys(props)) {
      const [section, ...rest] = fq.split(".");
      const key = rest.join(".");
      const cfg = vscode.workspace.getConfiguration(section);
      const info = cfg.inspect(key);
      assert.ok(
        info !== undefined,
        `inspect returned undefined for ${fq}`,
      );
    }
  });
});
