// Mocha entrypoint invoked by @vscode/test-electron inside the extension
// host. Discovers *.test.js siblings and runs them.

"use strict";

const path = require("node:path");
const fs = require("node:fs");
const Mocha = require("mocha");

exports.run = async function run() {
  const mocha = new Mocha({ ui: "tdd", color: true, timeout: 60_000 });
  const dir = __dirname;
  for (const f of fs.readdirSync(dir)) {
    if (f.endsWith(".test.js")) {
      mocha.addFile(path.join(dir, f));
    }
  }
  return new Promise((resolve, reject) => {
    try {
      mocha.run((failures) => {
        if (failures > 0) {
          reject(new Error(`${failures} test(s) failed`));
        } else {
          resolve();
        }
      });
    } catch (err) {
      reject(err);
    }
  });
};
