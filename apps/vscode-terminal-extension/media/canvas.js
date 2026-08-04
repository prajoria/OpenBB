// Placeholder canvas bundle for the OpenBB Terminal webview (#1814).
// The real React canvas mounts in #1816. Until then, this script:
//   1. reads the injected API base URL,
//   2. shows the last host->webview message on screen,
//   3. posts a "ready" message back to the extension host.
(function () {
  const apiBase = window.__OPENBB_API_BASE__;
  console.log("OpenBB API base:", apiBase);

  const pre = document.createElement("pre");
  pre.id = "last-message";
  const root = document.getElementById("root");
  if (root && root.parentNode) {
    root.parentNode.insertBefore(pre, root);
  } else {
    document.body.appendChild(pre);
  }

  window.addEventListener("message", function (event) {
    console.log("webview received", event.data);
    const el = document.getElementById("last-message");
    if (el) {
      el.textContent = JSON.stringify(event.data);
    }
  });

  const vscode = acquireVsCodeApi();
  vscode.postMessage({ type: "ready" });
})();
