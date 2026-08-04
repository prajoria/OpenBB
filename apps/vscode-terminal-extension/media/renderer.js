// Path-A generic renderer for OpenBB VS Code Terminal fixture mode (#1816).
// Vanilla JS; no framework. Real React comes in a later phase.
// All interpolated values pass through esc() first — innerHTML use is safe.
/* global document */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderTable(rows) {
    if (!Array.isArray(rows) || rows.length === 0) return "<div class=\"empty\">No rows</div>";
    var cols = Object.keys(rows[0]);
    var head = cols.map(function (c) { return "<th>" + esc(c) + "</th>"; }).join("");
    var body = rows.map(function (r) {
      return "<tr>" + cols.map(function (c) { return "<td>" + esc(r[c]) + "</td>"; }).join("") + "</tr>";
    }).join("");
    return "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function renderMetric(obj) {
    if (!obj || typeof obj !== "object") return "<div class=\"empty\">No metrics</div>";
    var items = Object.keys(obj).map(function (k) {
      return "<div class=\"kv\"><span class=\"k\">" + esc(k) + "</span><span class=\"v\">" + esc(obj[k]) + "</span></div>";
    });
    return "<div class=\"metric-list\">" + items.join("") + "</div>";
  }

  function renderBody(widget) {
    var t = widget.type;
    var rows = widget.fixtureRows;
    if (t === "table") return renderTable(rows);
    if (t === "metric") return renderMetric(rows);
    if (t === "chart") return "<div class=\"chart-placeholder\">Chart: " + esc(widget.name) + " (Path B upgrade in follow-up)</div>";
    if (t === "markdown") return "<div class=\"markdown\">" + esc(rows) + "</div>";
    if (t === "note") return "<pre class=\"note\">" + esc(rows) + "</pre>";
    return "<div class=\"type-not-supported\">type \"" + esc(t) + "\" not yet supported in the local viewer — see ADR #1810</div>";
  }

  function renderLayout(root, layout, widgetsManifest) {
    var byId = {};
    (widgetsManifest || []).forEach(function (w) { byId[w.id] = w; });
    root.style.display = "grid";
    root.style.gridTemplateColumns = "repeat(12, 1fr)";
    root.style.gap = "8px";
    root.innerHTML = "";
    (layout.slots || []).forEach(function (slot) {
      var widget = byId[slot.widgetId];
      var div = document.createElement("div");
      div.className = "slot";
      div.style.gridColumn = slot.col + " / span " + slot.span;
      if (slot.row) div.style.gridRow = String(slot.row);
      if (!widget) {
        div.innerHTML = "<header>" + esc(slot.widgetId) + "</header><div class=\"missing\">Widget not found in manifest</div>";
      } else {
        div.innerHTML = "<header>" + esc(widget.name) + "</header>" + renderBody(widget);
      }
      root.appendChild(div);
    });
  }

  if (typeof window !== "undefined") {
    window.OpenBBRenderer = { renderLayout: renderLayout };
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { renderLayout: renderLayout };
  }
})();
