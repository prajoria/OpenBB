// Symbol wiring inside the webview (#1823). Vanilla JS — CSP forbids
// inline scripts + unsafe-eval, so this is loaded via <script src>.

(function () {
  "use strict";

  function applySymbol(sym) {
    var inputs = document.querySelectorAll("[data-widget-symbol-input]");
    for (var i = 0; i < inputs.length; i++) {
      var input = inputs[i];
      input.value = sym;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function postSymbolFromInput(input) {
    var vscode =
      typeof acquireVsCodeApi === "function" ? acquireVsCodeApi() : null;
    if (!vscode) {
      return;
    }
    vscode.postMessage({
      type: "symbolFromWidget",
      symbol: String(input.value || "")
        .trim()
        .toUpperCase(),
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    window.addEventListener("message", function (event) {
      var data = event.data;
      if (data && data.type === "symbolChange") {
        applySymbol(data.symbol);
      }
    });
    var inputs = document.querySelectorAll("[data-widget-symbol-input]");
    for (var i = 0; i < inputs.length; i++) {
      (function (input) {
        input.addEventListener("change", function () {
          postSymbolFromInput(input);
        });
      })(inputs[i]);
    }
  });

  window.__openbbSymbol = { applySymbol: applySymbol };
})();
