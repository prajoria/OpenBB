// Preview bootstrap (#1832): bootstraps the Path-A renderer against a
// single widget in FIXTURE mode. Reads window.__OPENBB_PREVIEW_WIDGET__
// injected by the host and forwards to window.OpenBBRenderer.
/* global document, window */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var widget = window.__OPENBB_PREVIEW_WIDGET__;
    var root = document.getElementById("widget-root");
    if (!widget || !root) return;
    var renderer = window.OpenBBRenderer;
    if (renderer && typeof renderer.renderLayout === "function") {
      var layout = {
        id: "preview-" + widget.id,
        name: widget.name,
        gridTemplate: "12",
        slots: [{ widgetId: widget.id, col: 1, span: 12, row: 1 }],
      };
      renderer.renderLayout(root, layout, [widget]);
      return;
    }
    root.textContent = "Renderer unavailable";
  });
})();
