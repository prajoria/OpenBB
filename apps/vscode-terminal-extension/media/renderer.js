// Path-A generic renderer for OpenBB VS Code Terminal (#1816, #1820).
// Vanilla JS; no framework. Real React comes in a later phase.
// All interpolated values pass through esc() first — innerHTML use is safe.
//
// Data mode (#1820): when the host posts {type:"dataModeChange", mode:"live"},
// widgets fetch their `endpoint` from window.__OPENBB_API_BASE__ — with no
// bearer-style auth header and no token query param. Loopback binding is
// the auth control. `scripts/verify-auth-invariants.sh` guards these facts.
/* global document, window, fetch */
(function () {
  "use strict";

  var currentMode = "fixture";
  var lastLayout = null;
  var lastManifest = null;
  var lastRoot = null;

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

  function renderBodyFromData(widget, rows) {
    var t = widget.type;
    if (t === "table") return renderTable(rows);
    if (t === "metric") return renderMetric(rows);
    if (t === "chart") return "<div class=\"chart-placeholder\">Chart: " + esc(widget.name) + " (Path B upgrade in follow-up)</div>";
    if (t === "markdown") return "<div class=\"markdown\">" + esc(rows) + "</div>";
    if (t === "note") return "<pre class=\"note\">" + esc(rows) + "</pre>";
    return "<div class=\"type-not-supported\">type \"" + esc(t) + "\" not yet supported in the local viewer — see ADR #1810</div>";
  }

  function badge(mode) {
    if (mode === "live") return "<span class=\"badge badge-live\" style=\"background:#0a7c2f;color:#fff;padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px;\">LIVE</span>";
    return "<span class=\"badge badge-fixture\" style=\"background:#b58900;color:#000;padding:1px 6px;border-radius:3px;font-size:10px;margin-left:6px;\">FIXTURE</span>";
  }

  function fetchLive(widget, slotEl) {
    var apiBase = (typeof window !== "undefined" && window.__OPENBB_API_BASE__) || "";
    var endpoint = widget.endpoint || "";
    if (!endpoint) {
      var b0 = slotEl.querySelector(".body");
      if (b0) b0.innerHTML = "<div class=\"empty\">No endpoint</div>";
      return;
    }
    var path = endpoint.charAt(0) === "/" ? endpoint : "/" + endpoint;
    var url = apiBase + path;
    // No bearer-style auth header. No token query param. Loopback only.
    fetch(url, { method: "GET" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var rows = (data && data.results) ? data.results : data;
        var body = slotEl.querySelector(".body");
        if (body) body.innerHTML = renderBodyFromData(widget, rows);
      })
      .catch(function (err) {
        var msg = err && err.message ? err.message : String(err);
        var body = slotEl.querySelector(".body");
        if (!body) return;
        body.innerHTML =
          "<div class=\"error\" style=\"color:#c22;\">Error: " + esc(msg) + "</div>" +
          "<button class=\"retry\" type=\"button\">Retry</button>";
        var btn = body.querySelector(".retry");
        if (btn) {
          btn.addEventListener("click", function () {
            body.innerHTML = "<div class=\"loading\">Loading…</div>";
            fetchLive(widget, slotEl);
          });
        }
      });
  }

  function renderSlotContents(slotEl, widget) {
    if (!widget) {
      slotEl.innerHTML = "<header>Unknown</header><div class=\"missing\">Widget not found in manifest</div>";
      return;
    }
    var header = "<header>" + esc(widget.name) + badge(currentMode) + "</header>";
    if (currentMode === "live") {
      slotEl.innerHTML = header + "<div class=\"body\"><div class=\"loading\">Loading…</div></div>";
      fetchLive(widget, slotEl);
    } else {
      slotEl.innerHTML = header + "<div class=\"body\">" + renderBodyFromData(widget, widget.fixtureRows) + "</div>";
    }
  }

  function renderLayout(root, layout, widgetsManifest) {
    lastLayout = layout;
    lastManifest = widgetsManifest;
    lastRoot = root;
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
      renderSlotContents(div, widget);
      root.appendChild(div);
    });
  }

  function handleMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "dataModeChange" && (msg.mode === "live" || msg.mode === "fixture")) {
      if (msg.mode === currentMode) return;
      currentMode = msg.mode;
      if (lastRoot && lastLayout) {
        renderLayout(lastRoot, lastLayout, lastManifest);
      }
    }
  }

  if (typeof window !== "undefined") {
    window.OpenBBRenderer = { renderLayout: renderLayout };
    window.addEventListener("message", function (ev) {
      handleMessage(ev && ev.data);
    });
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { renderLayout: renderLayout };
  }
})();
