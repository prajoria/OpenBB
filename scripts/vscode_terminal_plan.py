"""One-shot: file EPIC + Features + underlying issues for the VS Code
Trading Terminal Extension, wire parent/child references, and add all
to Project #4.

Run once. Idempotent-ish: skips creation if the title already exists
open on prajoria/OpenBB (checks by exact title match).

Usage:
    python scripts/vscode_terminal_plan.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field

REPO = "prajoria/OpenBB"
PROJECT_ID = "PVT_kwHOAOc7384BdSTg"  # Project #4
PRD = "docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md"
PARENT_TRACKER = 1804  # docs tracker for the PRD itself


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        print(f"gh {' '.join(args)}\nSTDERR: {r.stderr}", file=sys.stderr)
        raise SystemExit(r.returncode)
    return r.stdout.strip()


def find_open_by_title(title: str) -> int | None:
    out = gh("issue", "list", "--repo", REPO, "--search", f'"{title}" in:title',
             "--state", "all", "--json", "number,title", "--limit", "10")
    for it in json.loads(out or "[]"):
        if it["title"].strip() == title.strip():
            return int(it["number"])
    return None


def create_issue(title: str, body: str, dry: bool) -> int:
    existing = find_open_by_title(title)
    if existing:
        print(f"  exists: #{existing}  {title[:70]}")
        return existing
    if dry:
        print(f"  DRY create: {title}")
        return 0
    url = gh("issue", "create", "--repo", REPO, "--title", title, "--body", body)
    n = int(url.rstrip("/").rsplit("/", 1)[-1])
    print(f"  created #{n}  {title[:70]}")
    return n


def node_id_for(num: int) -> str:
    return gh("api", f"repos/{REPO}/issues/{num}", "--jq", ".node_id")


def add_to_project(num: int, dry: bool) -> None:
    if dry or num == 0:
        return
    nid = node_id_for(num)
    q = 'mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}'
    gh("api", "graphql", "-f", f"query={q}", "-f", f"p={PROJECT_ID}", "-f", f"c={nid}")


@dataclass
class Node:
    title: str
    body: str
    children: list["Node"] = field(default_factory=list)
    number: int = 0


def build_plan() -> Node:
    def issue(title: str, body: str) -> Node:
        return Node(title=title, body=body)

    def feature(title: str, summary: str, kids: list[Node]) -> Node:
        return Node(title=title, body=summary, children=kids)

    # Phase 0 — Backend contract + rendering-model spike (§21.5)
    ph0 = feature(
        "[Feature] VSCode Terminal Phase 0 — Backend contract + rendering-model decision",
        """Phase 0 gate per PRD §21.5. Nothing in Phases 1–5 starts until this closes.

Scope
- Reconcile the three backend surfaces (`openbb-api :6900`, PI widget backend `:6120`,
  MCP `:8001`) into one canonical spawn for the VS Code extension.
- Prove one authed widget renders end-to-end in a webview against the chosen backend
  (CORS + token spike, PRD §21.3).
- Decide Path A (generic `widgets.json` renderer) vs Path B (bespoke React
  components) — PRD §21.2. Ship the decision as an ADR.

Non-goals
- No extension scaffold code beyond the spike (Phase 1 owns the scaffold).
- No layout system (Phase 2).

Load-bearing outcomes
- ADR documenting: canonical backend spawn, readiness endpoint, CORS/token strategy,
  rendering model.
- One passing spike (either standalone repo or a `spikes/` folder) that opens a webview
  and renders ≥1 real widget from the chosen backend.

Refs #1804 (PRD tracker).""",
        [
            issue(
                "[docs] ADR: canonical backend spawn + readiness endpoint for VS Code terminal",
                """Record the decision that closes PRD §21.1.

Deliverable
- New ADR `docs/Specs/adr/2026-08-XX-vscode-terminal-backend-spawn.md` naming: the
  canonical spawn command (recommend `openbb-api` on a fixed loopback port), the
  readiness gate (`GET /widgets.json`), and provider-health surface
  (`GET /pi/health/providers`).
- Update PRD §7 architecture diagram + §14.1 lifecycle text to match.

Not in scope
- No code. This is a decision record.

Refs #1804.""",
            ),
            issue(
                "[spike] CORS + token webview auth against widget backend",
                """Prove a webview can call an authed widget endpoint per PRD §21.3.

Do
- Configure widget backend `_ALLOWED_ORIGINS` to include the `vscode-webview://` origin
  (or spike the loopback-open `openbb-api` path).
- Wire `Authorization: Bearer <PI_WIDGET_BACKEND_TOKEN>` from extension host into the
  webview via postMessage; use it on both `fetch` and `EventSource`
  (URL-token strategy for SSE, per PRD C7).
- Render `/pi/health/providers` markdown in a stock webview end-to-end.

Deliverable
- Spike branch (`spike/vscode-webview-auth`) with a working minimal extension.
- One-page write-up on which token transport wins (header for REST, query for SSE).

Refs #1804.""",
            ),
            issue(
                "[docs] ADR: Path A widgets.json renderer vs Path B bespoke React components",
                """Close PRD §21.2 with a recorded decision.

Do
- Compare Path A (one generic renderer keyed off `widgets.json` `type`) vs Path B
  (60+ bespoke components matching backlog #529–#577).
- Recommendation per PRD §22.10: Path A first for breadth, selective Path B upgrades
  later for high-value widgets (charting, blotter, scan table, risk dashboard).

Deliverable
- ADR `docs/Specs/adr/2026-08-XX-vscode-terminal-rendering-model.md`.
- Update PRD §18 phase scoping to match.

Refs #1804.""",
            ),
            issue(
                "[docs] Widget-registry drift guard — Appendix A generator + verification",
                """Prevent silent drift between PRD Appendix A and the real registry.

Do
- Add `scripts/generate_widget_matrix.py` that fetches `widgets.json` from the
  canonical backend and regenerates PRD Appendix A.
- Add a `tests/` file (or a make target) that fails if the checked-in matrix
  diverges from what the generator would produce.

Refs #1804 (PRD §10 review note #8).""",
            ),
        ],
    )

    # Phase 1 — Extension scaffold + webview shell + widget canvas
    ph1 = feature(
        "[Feature] VSCode Terminal Phase 1 — Extension scaffold + webview shell + widget canvas",
        """Ship the minimum-viable VS Code extension that opens a webview panel and renders
widgets in fixture mode.

Scope (per PRD §18 Phase 1, corrected)
- Extension package layout under `apps/vscode-terminal-extension/` (kept out of `desktop/`
  to avoid Tauri scope creep per review comment #6).
- Activation events, `openbb.openTerminal` command, Layouts tree-view stub.
- Webview host that loads the shared React canvas (Vite bundle produced by a shared
  `packages/webview-shell/` if Path A, or `desktop/` re-use if the ADR from Phase 0
  says so).
- Theme token bridge (dark theme only) per PRD §16.
- Two built-in layouts (`Portfolio Overview`, `Equity Deep-Dive`) in FIXTURE mode only
  (real backend deferred to Phase 2).
- CSP allowing `style-src 'unsafe-inline'` for chart libs (review comment #10).

Done criteria
- `Ctrl+Shift+O` → panel opens with 2 fixture layouts, VS Code theme colours applied.
- Snapshot test in extension CI passes.

Refs #1804.""",
        [
            issue(
                "[vscode-terminal] Scaffold apps/vscode-terminal-extension/ package + activation",
                """New folder `apps/vscode-terminal-extension/` (or `packages/`, TBD by Phase 0 ADR).

Do
- `package.json` per PRD §8.1 with `openbb-terminal-vscode` metadata.
- Activation on `onCommand:openbb.openTerminal` and `onStartupFinished`.
- Empty `openbb-explorer` view container with three view stubs (Layouts, Widget Browser,
  Back-end Status).
- CI: `vsce package` produces a valid `.vsix`.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Webview host: loads shared canvas bundle + postMessage bridge",
                """PRD §9.

Do
- `WebviewPanel` factory (one per layout).
- Inject `acquireVsCodeApi()` handle + CSP with per-panel nonce.
- postMessage channel: `symbolChange`, `themeChange`, `layoutLoad`.
- Point `connect-src` at the canonical backend port from the Phase-0 ADR.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] VS Code theme token bridge (dark theme first)",
                """PRD §16.

Do
- Map the 10 core `--vscode-*` tokens to Tailwind CSS custom properties.
- Re-apply on `onDidChangeActiveColorTheme`.
- Verify against three VS Code default dark themes (Dark+, Monokai, One Dark Pro if
  installable in CI).

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Ship two fixture-mode layouts (Portfolio Overview + Equity Deep-Dive)",
                """PRD §11.1 Layouts 1 and 2.

Do
- Encode both layouts as JSON templates seeded into globalState on first-run.
- Each widget slot renders in FIXTURE mode (no live backend).
- Snapshot test in extension CI.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] CSP: allow style-src 'unsafe-inline' for chart libraries",
                """PRD §17.3 review comment #10.

Do
- Add `style-src 'nonce-{nonce}' 'unsafe-inline'` to the webview CSP.
- Document why (Recharts/Plotly inject inline styles) in an inline comment + PRD §17.3.
- Verify: chart lib renders in a fixture layout without CSP violation logs.

Refs #1804.""",
            ),
        ],
    )

    # Phase 2 — Live data + backend lifecycle
    ph2 = feature(
        "[Feature] VSCode Terminal Phase 2 — Live data + backend lifecycle + all 5 layouts",
        """Move from fixture-only to live backend, with lifecycle management.

Scope (PRD §18 Phase 2)
- Backend lifecycle: spawn/monitor/status-bar, using the canonical spawn from Phase 0.
- Health polling on the endpoint chosen in the Phase-0 ADR (`/widgets.json` per §21.1).
- All five built-in layouts (§11.1) rendering live data.
- Symbol context via widget selector (editor sources deferred to Phase 3).
- Full Command Palette per PRD §12.1.

Refs #1804.""",
        [
            issue(
                "[vscode-terminal] Backend lifecycle: spawn + health poll + status-bar",
                """PRD §14.1 + §21.1.

Do
- Spawn the canonical backend from the Phase-0 ADR.
- Health polling every 10s against the ADR-chosen readiness endpoint.
- Status-bar indicator: green/yellow/red + click-to-open logs.
- `openbb.startBackend`, `openbb.stopBackend`, `openbb.restartBackend`.
- Windows vs POSIX process-kill logic (PRD §19 R3).

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Live-data mode: switch fixture → real fetches with token injection",
                """PRD §14.2.

Do
- `window.__OPENBB_API_BASE__` set from the canonical port.
- Bearer token injection strategy from Phase-0 spike wired for production.
- Loading + error states per widget slot.
- Verify: `pi_provider_health` widget shows green live data.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Ship all five built-in layouts (Portfolio Risk, Trading Desk, Chart Focus)",
                """PRD §11.1 Layouts 3, 4, 5.

Do
- Encode the remaining three layout templates.
- Verify each renders live data end-to-end against the canonical backend.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Command Palette + default keybindings (full §12.1 surface)",
                """PRD §12.

Do
- Register all commands in §12.1.
- Bind the six default keybindings from §12.2.
- Wire `openbb.terminalFocused` context key.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Symbol context v1 — widget selector broadcasts to all panels",
                """PRD §13 (widget-selector source only; editor sources are Phase 3).

Do
- postMessage broadcast when any widget's symbol input changes.
- Debounced (300ms) validation against the search endpoint chosen in the ADR.
- Status-bar item shows active symbol.

Refs #1804.""",
            ),
        ],
    )

    # Phase 3 — Editor integration
    ph3 = feature(
        "[Feature] VSCode Terminal Phase 3 — Editor integration (hover, notebook, selection)",
        """Editor-resident integration points — the moat vs standalone terminals.

Scope (PRD §18 Phase 3, corrected per review comments #4 #5 #12)
- Symbol hover provider with **tightened regex** (only fires on quoted string literals
  matching `"[A-Z]{2,5}"` or in `symbol =` / `ticker =` assignment context, review #4).
- Notebook variable watcher, scoped to **source-text heuristic only** (review comment
  C4 + #5); runtime kernel introspection is a separate follow-up.
- Editor selection → symbol context.
- `openbb.runAnalysis` command.
- Lightweight SVG sparkline for hover (per PRD Q5).

Refs #1804.""",
        [
            issue(
                "[vscode-terminal] Symbol hover provider (Python + Notebook) with tightened regex",
                """PRD §8.5 + review comment #4.

Do
- Register HoverProvider for `python` and `jupyter-notebook` document types.
- Match ONLY on: (a) quoted string literal matching `"[A-Z]{2,5}"`, or (b) assignment
  target `symbol|ticker = "…"` context.
- 500ms cursor-rest debounce.
- Validate against ADR-chosen search endpoint before rendering.
- Render `MarkdownString` with SVG sparkline (Q5 → lightweight SVG, ~2KB).
- Include "📊 Open in Terminal" link → `openbb.openSymbolInTerminal`.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Notebook variable watcher — source-text heuristic (not runtime kernel)",
                """PRD §8.6 corrected per review comment C4.

Do
- Watch `NotebookDocument` source-text changes for cell content matching
  `(symbol|ticker)\\s*=\\s*"([A-Z]{2,5})"`.
- Propagate the matched symbol to open terminal panels.
- Document explicitly that this is source-text parsing, NOT kernel variable
  introspection (runtime introspection is a follow-up if we ever add it).

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Editor selection → symbol context",
                """PRD §13.1 low-priority source.

Do
- On `onDidChangeTextEditorSelection`, when 1–5 uppercase letter selection matches the
  ticker pattern, offer via inline code action (do NOT auto-broadcast; explicit only).

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] openbb.runAnalysis command opens 7-phase Analysis notebook",
                """PRD §12.1 + Q6.

Do
- Prompt for symbol.
- Spawn the 7-phase `Analysis/` pipeline via a subprocess against `.venv_portfolio`
  Python.
- Open a fresh notebook from a template (not modifying checked-in notebooks per Q6).

Refs #1804.""",
            ),
        ],
    )

    # Phase 4 — Full widget parity + layout management (tent-pole)
    ph4 = feature(
        "[Feature] VSCode Terminal Phase 4 — Widget parity + layout management (tent-pole)",
        """The tent-pole per PRD §21.5. Under Path A this is "build + harden the generic
`widgets.json` renderer + widget browser + user layouts". Under Path B this is 60+
bespoke components; scope will grow accordingly if that ADR is chosen.

Scope (PRD §18 Phase 4)
- Widget Browser tree-view (all widget IDs, drag-to-layout).
- User-defined layouts: create/rename/duplicate/delete.
- Layout export to `.openbb/layouts/*.json` in the workspace folder (PRD §11.2).
- `openbb.previewWidget` command reusing the existing preview route (PRD §21.4 C2).
- Golden-layout library committed to the repo (per §22.7 recommendation).

Refs #1804.""",
        [
            issue(
                "[vscode-terminal] Widget Browser tree-view (drag-to-layout, prefix grouping)",
                """PRD §8.3.

Do
- Populate from `widgets.json` (fetched in Phase 2).
- Group by prefix (`pi_*`, `tt_*`, `portfolio_*`, `regime_*`).
- Drag → adds a widget slot to the active layout.
- Inline "Preview" → fixture-mode single-widget preview.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] User-defined layouts: create / rename / duplicate / delete",
                """PRD §11.2.

Do
- Persist to `globalState` (default) with export to `.openbb/layouts/<name>.json`
  (workspace) as opt-in per Q3.
- Layout schema versioning field for forward-compat (§22.7).
- "Reset to default" affordance.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] openbb.previewWidget command (reuse existing preview route)",
                """PRD §12.1 + §21.4 C2.

Do
- Quick-pick over all widget IDs from `widgets.json`.
- On select, open a single-widget webview that reuses
  `desktop/src/routes/pi/preview/$widgetId.tsx` (already fixture-mode).

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Ship 3–5 golden layouts to the repo (versioned + shareable)",
                """PRD §22.7.

Do
- Commit `openbb_platform/tools/vscode-terminal-extension/golden_layouts/*.json`
  (or under the extension package) with the 5 layout templates from §11.1.
- Add a "Load golden layout" quick-pick.

Refs #1804.""",
            ),
        ],
    )

    # Phase 5 — Paper trading hotkeys + polish + NFR gate
    ph5 = feature(
        "[Feature] VSCode Terminal Phase 5 — Paper trading hotkeys + polish + NFR gate",
        """Final polish + NFR gate before v1.

Scope (PRD §18 Phase 5)
- Paper buy/sell keybindings (`Ctrl+Alt+B`, `Ctrl+Alt+S`).
- API key configuration command.
- High-contrast theme.
- Auto-start + auto-restart backend.
- Performance tuning to hit PRD §17.1 targets.
- **Testing strategy section** implemented (review comment #11): webview snapshot
  tests, VS Code extension test runner, recorded-fixture harness, manual QA matrix.

Refs #1804.""",
        [
            issue(
                "[vscode-terminal] Paper buy/sell keybindings for active symbol",
                """PRD §12.

Do
- Wire `Ctrl+Alt+B` / `Ctrl+Alt+S` gated on `openbb.terminalFocused`.
- Confirmation dialog (default "yes" toggleable in settings).
- POST to the paper-order endpoint via the token strategy from Phase 0.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] openbb.setApiKey guided quick-pick over user_settings.json",
                """PRD §15.3.

Do
- Quick-pick over known credential keys (FMP, FRED, …).
- Open `user_settings.json` in VS Code editor with the target key pre-navigated.
- Validate JSON on save; surface parse errors as diagnostics.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] High-contrast + light theme parity for widgets and charts",
                """PRD §16.2.

Do
- Extend theme bridge to cover light-theme mappings.
- Verify each widget + chart lib in light + high-contrast themes.
- File follow-up issues for any widget that regresses.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Auto-start + auto-restart backend (configurable)",
                """PRD §14.1 + §18 Phase 5.

Do
- `openbb.autoStartBackend` (default `false` per Q4 recommendation).
- `openbb.autoRestartBackend` on health-fail transitions.
- Toast + status-bar affordance to enable/disable per-session.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Performance gate: hit all §17.1 NFR targets",
                """PRD §17.1.

Do
- Add extension-CI harness that measures: activation time, first-paint fixture,
  first-paint live, symbol-broadcast latency.
- Fail CI if any metric regresses beyond target + 10%.
- Publish a rolling perf report to a GitHub Discussion or a checked-in JSON snapshot.

Refs #1804.""",
            ),
            issue(
                "[vscode-terminal] Testing strategy: webview snapshots + extension test runner + fixture harness",
                """Fills the review comment #11 gap.

Do
- Add `@vscode/test-electron` runner to CI.
- Webview snapshot tests per layout (fixture-mode).
- Recorded-fixture harness for each widget's data round-trip (extend existing
  browser_test_harness fixtures).
- Manual QA layout matrix committed as `docs/Specs/vscode-terminal-qa-matrix.md`.

Refs #1804.""",
            ),
        ],
    )

    epic = Node(
        title="[EPIC] VS Code Trading Terminal Extension (openbb-terminal-vscode)",
        body=(
            "Deliver an editor-resident OpenBB trading terminal as a VS Code extension.\n\n"
            "Spec: `docs/Specs/VSCode-Trading-Terminal-Extension-PRD.md` (tracker #1804).\n\n"
            "This epic is broken into 6 phases (0–5); each phase is a Feature ticket and each\n"
            "Feature has 3–6 underlying implementation issues. Phase 0 is a HARD GATE per\n"
            "PRD §21.5 — no Phase-1+ work starts until the Phase-0 Feature closes.\n\n"
            "**Rendering-model note.** The PRD's review §21.2 flags that widget parity\n"
            "under Path B (bespoke React components) is 60+ additional issues (backlog\n"
            "#529–#577). The plan below assumes Path A (generic `widgets.json` renderer)\n"
            "per §22.10 recommendation; if Phase-0 ADR chooses Path B, additional child\n"
            "issues will be filed under Phase 4.\n\n"
            "**Non-goals** (PRD §3 N1–N7): no new engines, no real brokerage routing, no\n"
            "cloud sync, no VS Code Marketplace publish in v1, no Tauri-app displacement.\n\n"
            "Refs #1804 (PRD tracker), #1794 (parent local-copilot-proxy)."
        ),
        children=[ph0, ph1, ph2, ph3, ph4, ph5],
    )
    return epic


def emit(node: Node, depth: int, dry: bool) -> None:
    prefix = "  " * depth
    print(f"{prefix}- {node.title}")
    node.number = create_issue(node.title, node.body, dry)
    add_to_project(node.number, dry)
    for child in node.children:
        # Prepend "Under EPIC/Feature" line so children link up in body.
        parent_ref = f"Parent: #{node.number}\n\n" if node.number else ""
        child.body = parent_ref + child.body
        emit(child, depth + 1, dry)


def update_epic_with_children(node: Node, dry: bool) -> None:
    """Rewrite epic body to list each phase feature by number."""
    if not node.children or dry or node.number == 0:
        return
    lines = ["", "## Phase breakdown", ""]
    for feat in node.children:
        lines.append(f"- **#{feat.number}** — {feat.title}")
        for kid in feat.children:
            if kid.number:
                lines.append(f"  - #{kid.number} — {kid.title}")
    new_body = node.body + "\n" + "\n".join(lines)
    gh("issue", "edit", str(node.number), "--repo", REPO, "--body", new_body)
    for feat in node.children:
        if not feat.number:
            continue
        feat_lines = [feat.body, "", "## Child issues", ""]
        for kid in feat.children:
            if kid.number:
                feat_lines.append(f"- #{kid.number} — {kid.title}")
        gh("issue", "edit", str(feat.number), "--repo", REPO, "--body", "\n".join(feat_lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    plan = build_plan()
    emit(plan, 0, args.dry_run)
    update_epic_with_children(plan, args.dry_run)
    print("\nDone.")
    if not args.dry_run:
        print(f"EPIC: https://github.com/{REPO}/issues/{plan.number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
