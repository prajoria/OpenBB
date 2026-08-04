// Webview-side theme applier for the OpenBB VS Code terminal (#1815).
// Reads the mapped --vscode-* variables from computed styles and mirrors
// them onto --color-* on <html>, so layout code stays theme-agnostic.
// No imports/exports — this runs as a plain <script> inside the webview.

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

  function applyVSCodeTheme() {
    var styles = getComputedStyle(document.body);
    var root = document.documentElement;
    for (var i = 0; i < CORE.length; i++) {
      var target = CORE[i][0];
      var source = CORE[i][1];
      var value = styles.getPropertyValue(source).trim();
      if (value) {
        root.style.setProperty(target, value);
      }
    }
  }

  window.addEventListener("message", function (event) {
    var msg = event && event.data;
    if (msg && msg.type === "themeChange") {
      applyVSCodeTheme();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyVSCodeTheme);
  } else {
    applyVSCodeTheme();
  }

  window.applyVSCodeTheme = applyVSCodeTheme;
})();
