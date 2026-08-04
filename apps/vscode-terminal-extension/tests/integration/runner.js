// Integration-test bootstrap for the OpenBB Terminal VS Code extension (#1840).
//
// Uses @vscode/test-electron to download a stable VS Code build,
// launch it with the extension loaded, and run the Mocha suite under
// tests/integration/*.test.js. Gated on RUN_INTEGRATION=1 so unit-only
// CI runs never pay the download / launch cost.

"use strict";

const path = require("node:path");

async function main() {
  if (process.env.RUN_INTEGRATION !== "1") {
    // eslint-disable-next-line no-console
    console.log(
      "tests/integration: skipped, set RUN_INTEGRATION=1 to enable",
    );
    return;
  }

  // Lazy-require so the module is only resolved when the gate is open.
  // @vscode/test-electron is a devDependency but may not be installed
  // in slim CI images that never flip the gate.
  const { runTests } = require("@vscode/test-electron");

  const extensionDevelopmentPath = path.resolve(__dirname, "..", "..");
  const extensionTestsPath = path.resolve(__dirname, "suite.js");

  await runTests({
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: ["--disable-extensions"],
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("integration runner failed:", err);
  process.exit(1);
});
