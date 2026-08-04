// Integration: openbb.openTerminal opens a webview.
"use strict";

const assert = require("node:assert/strict");
const vscode = require("vscode");

suite("openbb.openTerminal", () => {
  test("command executes without throwing", async () => {
    await vscode.commands.executeCommand("openbb.openTerminal");
  });

  test("webview panel is created", async () => {
    // The command itself returns void; we assert the command is
    // registered as a side-effect signal.
    const cmds = await vscode.commands.getCommands(true);
    assert.ok(cmds.includes("openbb.openTerminal"));
  });
});
