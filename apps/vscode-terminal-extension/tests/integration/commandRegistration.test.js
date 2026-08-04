// Integration: every command declared in package.json's
// contributes.commands is registered at activation time.

"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const vscode = require("vscode");
const pkg = require(path.resolve(__dirname, "..", "..", "package.json"));

suite("command registration", () => {
  test("all declared commands are registered", async () => {
    const declared = (pkg.contributes.commands || []).map((c) => c.command);
    const registered = await vscode.commands.getCommands(true);
    const missing = declared.filter((c) => !registered.includes(c));
    assert.deepEqual(
      missing,
      [],
      `missing commands: ${missing.join(", ")}`,
    );
  });
});
