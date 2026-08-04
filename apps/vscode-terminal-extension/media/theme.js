// Webview-side theme applier (#1815, #1837).
(function () {
  var CORE = [
    ["--color-background", "--vscode-editor-background"],
    ["--color-foreground", "--vscode-editor-foreground"],
    ["--color-surface", "--vscode-sideBar-background"],
    ["--color-border", "--vscode-panel-border"],
    ["--color-primary", "--vscode-button-background"],
    ["--color-primary-fg", "--vscode-button-foreground"],
    ["--color-accent", "--vscode-focusBorder"],
    ["--color-success", "--vscode-terminal-ansiGreen"],
    ["--color-error", "--vscode-terminal-ansiRed"],
    ["--color-warning", "--vscode-terminal-ansiYellow"],
  ];
  var currentKind = "dark";
  function detectKindFromBody() {
    var cls = (document.body && document.body.className) || "";
    if (cls.indexOf("vscode-high-contrast") !== -1) return "high-contrast";
    if (cls.indexOf("vscode-light") !== -1) return "light";
    return "dark";
  }
  function applyVSCodeTheme(kindOverride) {
    var styles = getComputedStyle(document.body);
    var root = document.documentElement;
    for (var i = 0; i < CORE.length; i++) {
      var value = styles.getPropertyValue(CORE[i][1]).trim();
      if (value) root.style.setProperty(CORE[i][0], value);
    }
    var kind = kindOverride || detectKindFromBody();
    currentKind = kind;
    root.setAttribute("data-openbb-theme", kind);
  }
  function postReady() {
    try {
      if (typeof acquireVsCodeApi === "function") {
        var api = window.__openbbVsCodeApi || acquireVsCodeApi();
        window.__openbbVsCodeApi = api;
        api.postMessage({ type: "themeReady", kind: currentKind });
      }
    } catch (_e) {}
  }
  window.addEventListener("message", function (event) {
    var msg = event && event.data;
    if (msg && msg.type === "themeChange") applyVSCodeTheme(msg.kind);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      applyVSCodeTheme();
      postReady();
    });
  } else {
    applyVSCodeTheme();
    postReady();
  }
  window.applyVSCodeTheme = applyVSCodeTheme;
})();
