# ADR: VSCode Trading Terminal — widget rendering model

- **Date:** 2026-08-04
- **Status:** Accepted
- **Epic:** #1806 (VSCode Trading Terminal Extension)
- **Parent:** #1807 (Phase-0 hard-gate ADRs)
- **Issue:** #1810
- **PRD:** `docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md` §21.2, §22.10, §18

## 1. Context

PRD §10 enumerates 60+ named widgets (blotter, scan tables, risk dashboard,
option surface, factor tearsheet, …) as if they exist today as first-class
React components. The actual runtime registry in
`desktop/src/pi/sdk/registry.ts` has exactly **one** widget registered
(`hello`); every other widget listed in §10 corresponds to a backlog item
in the #529–#577 range and is not implemented.

The gap has two consequences:

1. Phase 4 as written in the PRD ("wire up all widgets in the terminal")
   is not schedulable — it silently expands to shipping 60+ bespoke
   components, which is the multi-quarter #529–#577 backlog, not a
   sprint.
2. All 60+ backend endpoints (`portfolio_intel`, `techtrade`,
   `backtest`, `fmp_cached`) are already producing structured
   `widgets.json` output today, keyed by a `type` field
   (`table`, `chart`, `markdown`, `metric`, `note`, …). Those payloads
   are inert until *something* renders them.

The upstream reference (`pro.openbb.co` Workspace) resolves this with a
single generic renderer keyed off the widget payload's `type`. That is
the pattern this ADR adopts.

## 2. Decision

**Path A first, selective Path B upgrades later.**

- Phase 4 ships **one** generic renderer plus a widget browser. The
  renderer fetches each widget's declared `endpoint`, inspects the
  `type` field on the returned payload, and dispatches to a small set
  of type-keyed React components (see §3). All 60+ backend endpoints
  become reachable from the terminal on day one, at fixture parity.
- **Path B** — bespoke, hand-authored React components under
  `desktop/src/pi/widgets/<name>/` registered via `registerWidget(...)` —
  is retained as a targeted upgrade mechanism, applied only to widgets
  that clear the criteria in §4. Path B is the mechanism behind
  #529–#577; those issues remain valid but are re-scoped as
  post-Phase-4 upgrades, not Phase-4 blockers.

Rationale: the parity problem is a breadth problem, and the correct
answer to a breadth problem is a dispatcher, not 60 hand-authored
implementations. Fidelity gaps for specific high-value widgets are a
depth problem, and Path B is the correct answer there.

## 3. Rendering type map

The generic renderer lives at `desktop/src/pi/renderer/GenericWidget.tsx`.
It reads `payload.type` and dispatches:

| `widgets.json` `type` | Component                         | Notes                                                                                     |
| --------------------- | --------------------------------- | ----------------------------------------------------------------------------------------- |
| `table`               | `<TableWidget>`                   | Column defs from payload; sortable; virtualized for >1k rows.                              |
| `chart`               | `<ChartWidget>`                   | Thin wrapper over the existing Plotly wrapper already used elsewhere in `desktop/`.       |
| `markdown`            | `<MarkdownWidget>`                | Rendered through the shared sanitizer; no raw HTML, no inline scripts.                    |
| `metric`              | `<MetricWidget>`                  | Single scalar with label, unit, delta, and optional sparkline slot.                        |
| `note`                | `<NoteWidget>`                    | Plain-text block with title; used by warnings, empty-state messages, provenance stamps.    |
| *anything else*       | `<UnsupportedWidget>` placeholder | Renders literal `"type not supported in local viewer"` plus the raw `type` string for triage. |

Registration: the generic renderer is registered once against a
sentinel key (`__generic__`) at boot; widget descriptors in
`widgets.json` that do not match a bespoke `registerWidget(...)` entry
fall through to it. Bespoke registrations always win — that is the
Path B upgrade path.

## 4. When to promote a widget to Path B

A widget is a Path B candidate when at least one of the following is
true:

- **Interaction depth** — drag-to-select, keyboard hotkey semantics,
  cell-level context menus, inline edit. The generic table cannot
  express these without becoming a general-purpose grid.
- **Custom chart affordances** — crosshair-linked panels, streaming
  updates, overlay drawing (trendlines, Fib), regime shading. Beyond
  what the shared Plotly wrapper exposes.
- **Order-entry semantics** — anything that can send a live order (or
  a paper-trading equivalent) needs bespoke validation, confirm-modal,
  and audit-trail wiring. Never generic.
- **Dense multi-pane composition** — e.g. a risk dashboard whose
  layout is not a flat list of cells.

Widgets that do **not** clear any of the above stay on Path A
permanently; a generic table over a well-shaped endpoint is often the
end state, not a placeholder.

## 5. Impact on PRD §18 phase scoping

PRD §18 is updated as part of this ADR's follow-up edit:

- **Phase 4 (was: "50 bespoke widgets")** → "build + harden generic
  renderer, widget browser, and Path A dispatch table." Definition of
  done: every backend endpoint listed in PRD §10 renders through
  `<GenericWidget>` at fixture parity, and the widget browser lists
  every entry from `widgets.json`.
- **Phase 5+** — targeted Path B upgrades for widgets clearing §4
  criteria (initial candidates: charting, blotter, scan table, risk
  dashboard). Each upgrade lands under its existing #529–#577 issue,
  now re-scoped from "build the widget" to "upgrade the widget from
  generic to bespoke."

## 6. Rejected alternatives

- **Path B only (bespoke component per widget).** Rejected. This is
  literally the #529–#577 backlog. Attempting it inside Phase 4
  either slips the phase by quarters or ships an unusable partial
  terminal that renders `hello` and 3 other widgets while §10 promises
  60. The reviewer's parity concern is real and this path does not
  fix it.
- **No renderer at all — widgets remain fixture-only.** Rejected. The
  backend endpoints already exist and produce structured `widgets.json`
  output; not rendering them means the terminal permanently trails
  the platform's own data surface. Also blocks any user validation of
  §10 flows until every bespoke component is hand-authored.
- **Generic renderer + no Path B upgrade path.** Rejected. Some
  widgets (§4) genuinely need bespoke code; foreclosing that path
  leaves high-value flows stuck at generic-table fidelity forever.
  Retaining `registerWidget(...)` as an override is nearly free and
  preserves optionality.

## 7. Follow-ups

- Edit PRD §18 to reflect the Phase-4 re-scope (separate PR, gated on
  this ADR merging).
- File a Phase-4 tracker issue for the generic renderer + widget
  browser build-out; link back to this ADR.
- Re-label #529–#577 as "Path B upgrade" candidates and add the §4
  criteria checklist to each so future triage can accept/defer
  consistently.
